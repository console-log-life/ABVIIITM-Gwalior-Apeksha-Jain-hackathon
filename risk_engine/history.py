"""REAL history: the CACHED_REAL capture cache processed through the SAME pipeline and trigger rules, cached on disk.

Build (slow, once): every cached document, in the order it was captured, goes through RiskPipeline (FinBERT, events,
entities, corroboration, impact) and the stress TriggerEngine with a simulated clock = the document's capture time
("known time"). Triggered stress runs are simulated with the illustrative StressEngine on the SYNTHETIC portfolio and
stored with created_at = that known time and run_id "real-<uuid>". Nothing is invented: every signal comes from a real
captured document (provenance CACHED_REAL, capture time kept).

The result is a Store-format SQLite file (data/real_history.db, git-ignored). Loading copies it into the live store
(origin "real"), which takes about a second, so the dashboard starts with real data. A fingerprint (capture files +
taxonomy/weights/scenarios/portfolio + active models) marks the cache stale when any input changes.

On a fresh clone (no local captures) the committed 50-headline sample is used.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from app.config import PROJECT_ROOT, Settings
from risk_engine.ingestion.replay import cache_files, load_cached_documents
from risk_engine.logging_setup import get_logger
from risk_engine.model_paths import finetuned_dir
from risk_engine.store import Store

log = get_logger(__name__)
META_FILE_SUFFIX = ".meta.json"
INPUTS = ["risk_engine/event_classifier/taxonomy.yaml", "risk_engine/impact_scoring/weights.yaml",
          "portfolio/scenarios.yaml"]


def history_path(settings: Settings) -> Path:
    return settings.resolve(Path(settings.real_history_path))


def fingerprint(settings: Settings) -> dict:
    files = cache_files(settings.cache_path)
    h = hashlib.sha256()
    for f in files:
        h.update(f"{f.name}:{f.stat().st_size}".encode())
    for rel in INPUTS + [str(Path(settings.portfolio_path))]:
        p = settings.resolve(Path(rel)) if not Path(rel).is_absolute() else Path(rel)
        h.update(p.read_bytes() if p.exists() else b"-")
    models = {"sentiment": str(finetuned_dir(settings.model_sentiment_path, settings) or settings.finbert_model),
              "event": str(finetuned_dir(settings.model_event_path, settings) or "rules"),
              "backend": settings.sentiment_backend, "quantized": settings.model_quantize_int8}
    h.update(json.dumps(models, sort_keys=True).encode())
    sample = bool(files) and all(f.parent.name == "sample" for f in files)
    return {"sha256": h.hexdigest(), "capture_files": len(files), "source": "published sample" if sample else
            "local capture cache", "models": models}


def read_meta(path: Path) -> dict | None:
    m = path.with_name(path.name + META_FILE_SUFFIX)
    return json.loads(m.read_text(encoding="utf-8")) if m.exists() else None


def is_fresh(settings: Settings) -> bool:
    meta = read_meta(history_path(settings))
    return bool(meta) and history_path(settings).exists() and meta.get("fingerprint") == fingerprint(settings)["sha256"]


def build_history(settings: Settings, sentiment=None, progress: Callable[[int, int], None] | None = None) -> dict:
    """Process the whole capture cache into a fresh history DB (atomic replace). Returns the meta dict."""
    from portfolio.loader import issuer_exposures, load_portfolio
    from portfolio.stress_engine import StressEngine
    from risk_engine.impact_scoring.corroboration import CorroborationTracker
    from risk_engine.impact_scoring.scorer import ImpactScorer
    from risk_engine.pipeline import RiskPipeline
    from risk_engine.sentiment.finbert import SentimentEngine

    t0 = time.time()
    fp = fingerprint(settings)
    docs = load_cached_documents(settings.cache_path)
    docs.sort(key=lambda d: (d.captured_at, d.published_at or d.captured_at, d.doc_id))
    portfolio = load_portfolio(settings)
    pipe = RiskPipeline(settings=settings, sentiment=sentiment or SentimentEngine(settings),
                        scorer=ImpactScorer(exposures=issuer_exposures(portfolio)),
                        corroboration=CorroborationTracker(settings.corroboration_window_h))
    engine = StressEngine(settings, portfolio)
    clock = {"t": 0.0}
    engine.triggers.clock = lambda: clock["t"]

    out = history_path(settings)
    tmp = out.with_name(out.name + ".building")
    for p in (tmp, tmp.with_name(tmp.name + "-wal"), tmp.with_name(tmp.name + "-shm")):
        p.unlink(missing_ok=True)
    store = Store(tmp)
    by_id = {d.doc_id: d for d in docs}
    n_sig = n_runs = 0
    for i in range(0, len(docs), 32):
        for sig in pipe.process_batch(docs[i : i + 32], skip_rejected=True):
            doc = by_id[sig.doc_id]
            if not store.save_signal(doc, sig, "real"):
                continue
            n_sig += 1
            known = doc.captured_at
            clock["t"] = known.timestamp()
            src = (doc.imitated_source or doc.source).value
            for d in engine.evaluate(sig, src):
                summary, positions = engine.run(d.scenario, d.scope_issuer_id, d.signal_id, d.rule)
                summary["run_id"] = "real-" + summary["run_id"]
                summary["created_at"] = known.isoformat()
                summary["history"] = "simulated on the CACHED_REAL history (illustrative model, synthetic portfolio)"
                for p in positions:
                    p["run_id"] = summary["run_id"]
                store.save_stress_run(summary, positions, demo=False, created_at=known)
                n_runs += 1
        if progress:
            progress(min(i + 32, len(docs)), len(docs))
    store.engine.dispose()
    lo = min((d.captured_at for d in docs), default=None)
    hi = max((d.captured_at for d in docs), default=None)
    meta = {"fingerprint": fp["sha256"], "source": fp["source"], "capture_files": fp["capture_files"],
            "models": fp["models"], "documents": len(docs), "signals": n_sig, "stress_runs": n_runs,
            "first_capture": lo.isoformat() if lo else None, "last_capture": hi.isoformat() if hi else None,
            "built_at": datetime.now(UTC).isoformat(timespec="seconds"), "build_seconds": round(time.time() - t0, 1)}
    out.unlink(missing_ok=True)
    tmp.replace(out)
    out.with_name(out.name + META_FILE_SUFFIX).write_text(json.dumps(meta, indent=1), encoding="utf-8")
    log.info("real history built: %s", meta)
    return meta


def load_into(store: Store, path: Path) -> dict:
    """Replace the store's origin='real' rows with the history DB's content (signals, documents, stress runs).
    One explicit transaction on a raw sqlite3 connection (ATTACH/DETACH are not allowed inside a transaction)."""
    raw = store.engine.raw_connection()
    try:
        con = raw.driver_connection
        old = con.isolation_level
        con.isolation_level = None  # explicit BEGIN/COMMIT below
        con.execute("ATTACH DATABASE ? AS hist", (str(path),))
        try:
            with store._lock:
                con.execute("BEGIN IMMEDIATE")
                try:
                    con.execute("DELETE FROM stress_results WHERE run_id LIKE 'real-%'")
                    con.execute("DELETE FROM stress_runs WHERE run_id LIKE 'real-%'")
                    con.execute("DELETE FROM documents WHERE doc_id IN (SELECT doc_id FROM signals "
                                "WHERE origin='real')")
                    con.execute("DELETE FROM signals WHERE origin='real'")
                    # a document already stored by another path (e.g. REPLAY) keeps its own row; history skips it
                    con.execute("INSERT OR IGNORE INTO documents SELECT * FROM hist.documents WHERE doc_id NOT IN "
                                "(SELECT doc_id FROM main.signals)")
                    cols = ("signal_id, doc_id, ticker, issuer_id, company, event_type, impact_score, risk_level, "
                            "sentiment_score, source, provenance, timestamp, origin, created_at, payload")
                    n_sig = con.execute(f"INSERT OR IGNORE INTO signals ({cols}) SELECT {cols} FROM hist.signals "
                                        f"WHERE doc_id NOT IN (SELECT doc_id FROM main.signals) ORDER BY seq").rowcount
                    n_runs = con.execute("INSERT OR IGNORE INTO stress_runs SELECT * FROM hist.stress_runs").rowcount
                    con.execute("INSERT INTO stress_results (run_id, asset_id, asset_type, issuer_id, sector, "
                                "country, value_before, value_after, pnl) SELECT run_id, asset_id, asset_type, "
                                "issuer_id, sector, country, value_before, value_after, pnl FROM hist.stress_results")
                    con.execute("COMMIT")
                except Exception:
                    con.execute("ROLLBACK")
                    raise
        finally:
            con.execute("DETACH DATABASE hist")
            con.isolation_level = old
    finally:
        raw.close()
    return {"signals": n_sig, "stress_runs": n_runs}


def default_history_db() -> Path:
    return PROJECT_ROOT / "data" / "real_history.db"
