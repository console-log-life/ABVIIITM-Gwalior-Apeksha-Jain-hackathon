"""SQLite persistence (spec 7.1) via SQLAlchemy Core.

Tables: documents, signals, stress_runs, stress_results, source_health.
Indexes: signals(ticker, timestamp), signals(event_type).
`signals.seq` is an autoincrement integer giving a stable order for `since_id` paging and SSE catch-up.
`origin` records which path produced a signal: live | replay | scenario | api | real (used by /demo/reset).
`real` = the CACHED_REAL history loaded from the processed-history cache (risk_engine/history.py); it is kept by
/demo/reset, and its stress runs have run_ids starting with "real-".
Time machine: filters on the signal's EVENT time (signals.timestamp = publication time, or capture time when a
source gives none) with `until_ts` / `since_ts`. For the CACHED_REAL history this replays the real news timeline as
published; the items themselves were collected at their capture times (shown on every CACHED_REAL badge).
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    delete,
    event,
    func,
    insert,
    select,
    text,
    update,
)
from sqlalchemy.engine import Engine

from risk_engine.schemas import RawDocument, RiskSignal

# A live stress run is saved a moment AFTER its triggering signal's event time; "as of T" includes runs saved up to
# this long after T (REAL-history runs are stamped exactly at their signal's event time).
RUN_SAVE_TOLERANCE = timedelta(minutes=5)

metadata = MetaData()

documents = Table(
    "documents", metadata,
    Column("doc_id", String(40), primary_key=True),
    Column("source", String(20), nullable=False),
    Column("source_type", String(10), nullable=False),
    Column("provenance", String(12), nullable=False),
    Column("captured_at", DateTime(timezone=True), nullable=False),
    Column("published_at", DateTime(timezone=True)),
    Column("title", Text, nullable=False),
    Column("text", Text, nullable=False),
    Column("url", Text),
    Column("publisher", String(200)),
    Column("hint_ticker", String(16)),
    Column("imitated_source", String(20)),
    Column("origin", String(10), nullable=False),
)

signals = Table(
    "signals", metadata,
    Column("seq", Integer, primary_key=True, autoincrement=True),
    Column("signal_id", String(36), unique=True, nullable=False),
    Column("doc_id", String(40), unique=True, nullable=False),
    Column("ticker", String(16)),
    Column("issuer_id", String(32)),
    Column("company", String(120), nullable=False),
    Column("event_type", String(20), nullable=False),
    Column("impact_score", Float, nullable=False),
    Column("risk_level", String(10), nullable=False),
    Column("sentiment_score", Float, nullable=False),
    Column("source", String(20), nullable=False),
    Column("provenance", String(12), nullable=False),
    Column("timestamp", DateTime(timezone=True), nullable=False),
    Column("origin", String(10), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("payload", Text, nullable=False),  # full RiskSignal JSON
)
Index("ix_signals_ticker_ts", signals.c.ticker, signals.c.timestamp)
Index("ix_signals_event_type", signals.c.event_type)

stress_runs = Table(
    "stress_runs", metadata,
    Column("run_id", String(36), primary_key=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("trigger_signal_id", String(36)),
    Column("scenario", String(60), nullable=False),
    Column("scope_issuer_id", String(32)),
    Column("rule", Text),
    Column("before_value", Float, nullable=False),
    Column("after_value", Float, nullable=False),
    Column("loss", Float, nullable=False),
    Column("loss_pct", Float, nullable=False),
    Column("rag", String(6), nullable=False),
    Column("demo", Boolean, nullable=False, default=False),
    Column("summary", Text, nullable=False),  # full StressResult JSON
)

stress_results = Table(
    "stress_results", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("run_id", String(36), ForeignKey("stress_runs.run_id", ondelete="CASCADE"), nullable=False, index=True),
    Column("asset_id", String(32), nullable=False),
    Column("asset_type", String(12), nullable=False),
    Column("issuer_id", String(32)),
    Column("sector", String(40)),
    Column("country", String(4)),
    Column("value_before", Float, nullable=False),
    Column("value_after", Float, nullable=False),
    Column("pnl", Float, nullable=False),
)

source_health = Table(
    "source_health", metadata,
    Column("source", String(30), primary_key=True),
    Column("status", String(14), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    Column("payload", Text, nullable=False),
)


def _utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


class Store:
    def __init__(self, db_path: Path | str):
        url = "sqlite:///:memory:" if str(db_path) == ":memory:" else f"sqlite:///{Path(db_path).as_posix()}"
        if str(db_path) != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.engine: Engine = create_engine(url, connect_args={"check_same_thread": False}, future=True)

        @event.listens_for(self.engine, "connect")
        def _pragmas(dbapi_conn, _):  # pragma: no cover - trivial
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

        self._lock = threading.Lock()
        metadata.create_all(self.engine)

    def ping(self) -> bool:
        try:
            with self.engine.connect() as c:
                c.execute(text("SELECT 1"))
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------ documents / signals
    def has_document(self, doc_id: str) -> bool:
        with self.engine.connect() as c:
            return c.execute(select(signals.c.seq).where(signals.c.doc_id == doc_id)).first() is not None

    def save_signal(self, doc: RawDocument, sig: RiskSignal, origin: str) -> bool:
        """Persist document + signal atomically. Returns False (and stores nothing) if doc_id already exists."""
        with self._lock, self.engine.begin() as c:
            if c.execute(select(signals.c.seq).where(signals.c.doc_id == doc.doc_id)).first():
                return False
            if not c.execute(select(documents.c.doc_id).where(documents.c.doc_id == doc.doc_id)).first():
                c.execute(insert(documents).values(
                    doc_id=doc.doc_id, source=doc.source.value, source_type=doc.source_type.value,
                    provenance=doc.provenance.value, captured_at=_utc(doc.captured_at),
                    published_at=_utc(doc.published_at), title=doc.title, text=doc.text, url=doc.url,
                    publisher=doc.publisher, hint_ticker=doc.hint_ticker,
                    imitated_source=doc.imitated_source.value if doc.imitated_source else None, origin=origin,
                ))
            c.execute(insert(signals).values(
                signal_id=sig.signal_id, doc_id=sig.doc_id, ticker=sig.ticker, issuer_id=sig.issuer_id,
                company=sig.company, event_type=sig.event_type, impact_score=sig.impact_score,
                risk_level=sig.risk_level.value, sentiment_score=sig.sentiment_score, source=sig.source.value,
                provenance=sig.provenance.value, timestamp=_utc(sig.timestamp), origin=origin,
                created_at=datetime.now(UTC), payload=sig.model_dump_json(),
            ))
        return True

    def _signal_rows(self, stmt) -> list[dict[str, Any]]:
        j = signals.join(documents, signals.c.doc_id == documents.c.doc_id, isouter=True)
        stmt = stmt.select_from(j)
        with self.engine.connect() as c:
            rows = c.execute(stmt).all()
        out = []
        for r in rows:
            d = json.loads(r.payload)
            d.update(seq=r.seq, origin=r.origin, title=r.title, url=r.url, publisher=r.publisher,
                     imitated_source=r.imitated_source,
                     captured_at=_utc(r.captured_at).isoformat() if r.captured_at else None)
            out.append(d)
        return out

    def _base_select(self):
        return select(signals.c.seq, signals.c.payload, signals.c.origin, documents.c.title, documents.c.url,
                      documents.c.publisher, documents.c.captured_at, documents.c.imitated_source)

    def get_signal_by_doc(self, doc_id: str) -> dict[str, Any] | None:
        rows = self._signal_rows(self._base_select().where(signals.c.doc_id == doc_id))
        return rows[0] if rows else None

    def get_signal(self, signal_id: str) -> dict[str, Any] | None:
        rows = self._signal_rows(self._base_select().where(signals.c.signal_id == signal_id))
        return rows[0] if rows else None

    def seq_of(self, signal_id: str) -> int | None:
        with self.engine.connect() as c:
            r = c.execute(select(signals.c.seq).where(signals.c.signal_id == signal_id)).first()
        return r.seq if r else None

    def list_signals(self, *, ticker: str | None = None, event_type: str | None = None,
                     min_impact: float | None = None, provenance: str | None = None, since_seq: int | None = None,
                     limit: int = 50, ascending: bool = False, since_ts: datetime | None = None,
                     until_ts: datetime | None = None, origins: list[str] | None = None) -> list[dict[str, Any]]:
        q = self._base_select()
        if ticker:
            q = q.where(func.upper(signals.c.ticker) == ticker.upper())
        if event_type:
            q = q.where(signals.c.event_type == event_type)
        if min_impact is not None:
            q = q.where(signals.c.impact_score >= min_impact)
        if provenance:
            q = q.where(signals.c.provenance == provenance)
        if since_seq is not None:
            q = q.where(signals.c.seq > since_seq)
        if since_ts is not None:
            q = q.where(signals.c.timestamp >= _utc(since_ts))
        if until_ts is not None:
            q = q.where(signals.c.timestamp <= _utc(until_ts))
        if origins is not None:
            q = q.where(signals.c.origin.in_(origins))
        q = q.order_by(signals.c.seq.asc() if ascending else signals.c.seq.desc()).limit(limit)
        return self._signal_rows(q)

    def iter_signals(self, batch: int = 500, **filters: Any) -> Iterator[dict[str, Any]]:
        last = None
        while True:
            rows = self.list_signals(since_seq=last, limit=batch, ascending=True, **filters)
            if not rows:
                return
            yield from rows
            last = rows[-1]["seq"]

    def count_signals(self) -> int:
        with self.engine.connect() as c:
            return int(c.execute(select(func.count()).select_from(signals)).scalar_one())

    def recent_for_corroboration(self, since: datetime) -> list[dict[str, Any]]:
        return self.list_signals(since_ts=since, limit=50_000, ascending=True)

    # ------------------------------------------------------------------ stress
    def save_stress_run(self, run: dict[str, Any], positions: list[dict[str, Any]], demo: bool,
                        created_at: datetime | None = None) -> None:
        with self._lock, self.engine.begin() as c:
            c.execute(insert(stress_runs).values(
                run_id=run["run_id"], created_at=_utc(created_at) or datetime.now(UTC),
                trigger_signal_id=run.get("trigger_signal_id"),
                scenario=run["scenario"], scope_issuer_id=run.get("scope_issuer_id"), rule=run.get("rule"),
                before_value=run["before_value"], after_value=run["after_value"], loss=run["loss"],
                loss_pct=run["loss_pct"], rag=run["rag"], demo=demo, summary=json.dumps(run, default=str),
            ))
            if positions:
                c.execute(insert(stress_results), [
                    {"run_id": run["run_id"], "asset_id": p["asset_id"], "asset_type": p["asset_type"],
                     "issuer_id": p.get("issuer_id"), "sector": p.get("sector"), "country": p.get("country"),
                     "value_before": p["value_before"], "value_after": p["value_after"], "pnl": p["pnl"]}
                    for p in positions
                ])

    def list_stress_runs(self, limit: int = 50, as_of: datetime | None = None) -> list[dict[str, Any]]:
        q = select(stress_runs.c.run_id, stress_runs.c.created_at, stress_runs.c.trigger_signal_id,
                   stress_runs.c.scenario, stress_runs.c.scope_issuer_id, stress_runs.c.rule, stress_runs.c.loss,
                   stress_runs.c.loss_pct, stress_runs.c.rag, stress_runs.c.demo)
        if as_of is not None:
            q = q.where(stress_runs.c.created_at <= _utc(as_of) + RUN_SAVE_TOLERANCE)
        q = q.order_by(stress_runs.c.created_at.desc()).limit(limit)
        with self.engine.connect() as c:
            rows = c.execute(q).mappings().all()
        return [{**dict(r), "created_at": _utc(r["created_at"]).isoformat()} for r in rows]

    def latest_stress_run(self, as_of: datetime | None = None) -> dict[str, Any] | None:
        q = select(stress_runs.c.summary, stress_runs.c.created_at)
        if as_of is not None:
            q = q.where(stress_runs.c.created_at <= _utc(as_of) + RUN_SAVE_TOLERANCE)
        with self.engine.connect() as c:
            r = c.execute(q.order_by(stress_runs.c.created_at.desc()).limit(1)).first()
        return {**json.loads(r.summary), "created_at": _utc(r.created_at).isoformat()} if r else None

    def event_time_range(self) -> tuple[datetime | None, datetime | None]:
        """First and last event time (signals.timestamp) over stored signals."""
        with self.engine.connect() as c:
            lo, hi = c.execute(select(func.min(signals.c.timestamp), func.max(signals.c.timestamp))).one()
        return _utc(lo), _utc(hi)

    def get_stress_run(self, run_id: str) -> dict[str, Any] | None:
        with self.engine.connect() as c:
            r = c.execute(select(stress_runs.c.summary).where(stress_runs.c.run_id == run_id)).first()
        return json.loads(r.summary) if r else None

    def stress_positions(self, run_id: str) -> list[dict[str, Any]]:
        with self.engine.connect() as c:
            rows = c.execute(select(stress_results).where(stress_results.c.run_id == run_id)).mappings().all()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------ health
    def upsert_source_health(self, items: list[dict[str, Any]]) -> None:
        now = datetime.now(UTC)
        with self._lock, self.engine.begin() as c:
            for h in items:
                values = {"status": h["status"], "updated_at": now, "payload": json.dumps(h, default=str)}
                res = c.execute(update(source_health).where(source_health.c.source == h["source"]).values(**values))
                if res.rowcount == 0:
                    c.execute(insert(source_health).values(source=h["source"], **values))

    def source_health_rows(self) -> list[dict[str, Any]]:
        with self.engine.connect() as c:
            rows = c.execute(select(source_health.c.payload).order_by(source_health.c.source)).all()
        return [json.loads(r.payload) for r in rows]

    # ------------------------------------------------------------------ demo reset
    def reset_demo(self) -> dict[str, int]:
        """Delete demo-path signals (scenario, replay, api) and their stress runs. LIVE signals and the loaded
        CACHED_REAL history (origin "real", runs "real-*") are kept."""
        with self._lock, self.engine.begin() as c:
            demo_docs = select(signals.c.doc_id).where(signals.c.origin.in_(["scenario", "replay", "api"]))
            n_docs = c.execute(delete(documents).where(documents.c.doc_id.in_(demo_docs))).rowcount
            n_sig = c.execute(delete(signals).where(signals.c.origin.in_(["scenario", "replay", "api"]))).rowcount
            keep = stress_runs.c.run_id.like("real-%")
            c.execute(delete(stress_results).where(stress_results.c.run_id.in_(
                select(stress_runs.c.run_id).where(~keep))))
            n_runs = c.execute(delete(stress_runs).where(~keep)).rowcount
        return {"signals_deleted": n_sig, "documents_deleted": n_docs, "stress_runs_deleted": n_runs}
