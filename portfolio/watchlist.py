"""Early-warning watchlist: a credit-risk view of recent signals, one row per HELD issuer.

For every issuer in the portfolio, the signals inside the window (by event time) are aggregated and a
rules-based watch status is assigned (thresholds from config; documented in docs/methodology.md):

  WATCH-NEGATIVE  any negative signal with impact >= watch_impact,
                  or >= watch_count negative signals with impact >= watch_count_impact
  MONITOR         any negative signal with impact >= monitor_impact
  STABLE          otherwise (including no signals at all)
  MONITOR (propagated)  a STABLE issuer linked (curated links, weight >= WATCHLIST_PROPAGATION_MIN_WEIGHT) to a
                  WATCH-NEGATIVE issuer (portfolio/propagation.py); only when settings are passed

"Negative" means sentiment <= negative_sentiment. The status is an early-warning flag for analyst attention, not a
credit rating, a PD estimate or investment advice.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.config import Settings
from portfolio.loader import FUNDED_TYPES, Portfolio

WATCH, MONITOR, STABLE = "WATCH-NEGATIVE", "MONITOR", "STABLE"
STATUS_RANK = {WATCH: 2, MONITOR: 1, STABLE: 0}
NOTE = ("Rules-based early-warning flag for analyst attention: not a credit rating, a PD estimate or investment "
        "advice.")


@dataclass(frozen=True)
class WatchRules:
    negative_sentiment: float = -0.25
    watch_impact: float = 7.0
    watch_count: int = 2
    watch_count_impact: float = 5.0
    monitor_impact: float = 4.0

    @classmethod
    def from_settings(cls, s: Settings) -> WatchRules:
        return cls(s.watchlist_negative_sentiment, s.watchlist_watch_impact, s.watchlist_watch_count,
                   s.watchlist_watch_count_impact, s.watchlist_monitor_impact)

    def describe(self) -> dict[str, str]:
        neg = f"sentiment <= {self.negative_sentiment:g}"
        return {
            WATCH: f"any negative signal ({neg}) with impact >= {self.watch_impact:g}, or >= {self.watch_count} "
                   f"negative signals with impact >= {self.watch_count_impact:g}",
            MONITOR: f"any negative signal ({neg}) with impact >= {self.monitor_impact:g}",
            STABLE: "otherwise",
        }


def watch_status(signals: list[dict[str, Any]], rules: WatchRules) -> tuple[str, str]:
    """(status, human-readable reason) for one issuer's signals in the window."""
    neg = [s for s in signals if s["sentiment_score"] <= rules.negative_sentiment]
    strong = [s for s in neg if s["impact_score"] >= rules.watch_impact]
    if strong:
        s = max(strong, key=lambda x: x["impact_score"])
        return WATCH, (f"negative signal with impact {s['impact_score']:.1f} >= {rules.watch_impact:g} "
                       f"(sentiment {s['sentiment_score']:+.2f})")
    several = [s for s in neg if s["impact_score"] >= rules.watch_count_impact]
    if len(several) >= rules.watch_count:
        return WATCH, f"{len(several)} negative signals with impact >= {rules.watch_count_impact:g}"
    medium = [s for s in neg if s["impact_score"] >= rules.monitor_impact]
    if medium:
        s = max(medium, key=lambda x: x["impact_score"])
        return MONITOR, f"negative signal with impact {s['impact_score']:.1f} >= {rules.monitor_impact:g}"
    if not signals:
        return STABLE, "no signals in the window"
    return STABLE, f"no negative signal with impact >= {rules.monitor_impact:g}"


def _ts(sig: dict[str, Any]) -> datetime:
    return datetime.fromisoformat(str(sig["timestamp"]).replace("Z", "+00:00"))


def _source(sig: dict[str, Any]) -> str:
    return sig.get("imitated_source") or sig["source"]


def _brief(sig: dict[str, Any]) -> dict[str, Any]:
    return {k: sig.get(k) for k in ("signal_id", "timestamp", "impact_score", "risk_level", "sentiment_score",
                                    "event_type", "reason", "text_excerpt", "provenance", "captured_at")} | {
        "source": _source(sig)}


def issuer_table(portfolio: Portfolio) -> dict[str, dict[str, Any]]:
    """issuer_id -> name, sector, country, rating bucket, funded exposure, positions, CDS protection bought."""
    df = portfolio.df[portfolio.df["issuer_id"] != ""]
    book = portfolio.funded_mv or 1.0
    out: dict[str, dict[str, Any]] = {}
    for iid, g in df.groupby("issuer_id", sort=False):
        funded = g[g["asset_type"].isin(FUNDED_TYPES)]
        main = (funded if len(funded) else g).sort_values("market_value", ascending=False).iloc[0]
        cds = g[(g["asset_type"] == "CDS") & (g["side"] == "protection_bought")]
        mv = float(funded["market_value"].sum())
        out[str(iid)] = {
            "issuer_id": str(iid), "issuer_name": str(main["issuer_name"]), "sector": str(main["sector"]),
            "country": str(main["country"]), "rating_bucket": str(main["rating_bucket"]),
            "exposure_mv": round(mv, 2), "exposure_pct": round(100 * mv / book, 2), "positions": int(len(g)),
            "cds_protection_notional": round(float(cds["notional"].sum()), 2),
        }
    return out


def build_watchlist(portfolio: Portfolio, signals: list[dict[str, Any]], rules: WatchRules, hours: int,
                    as_of: datetime, settings: Settings | None = None) -> dict[str, Any]:
    """Aggregate stored signal rows (already filtered to the window) into one ranked row per held issuer."""
    issuers = issuer_table(portfolio)
    by_issuer: dict[str, list[dict[str, Any]]] = {k: [] for k in issuers}
    for s in signals:
        if s.get("issuer_id") in by_issuer:
            by_issuer[s["issuer_id"]].append(s)

    rows = []
    for iid, meta in issuers.items():
        sigs = sorted(by_issuer[iid], key=_ts)
        status, why = watch_status(sigs, rules)
        neg = [s for s in sigs if s["sentiment_score"] <= rules.negative_sentiment]
        top = sorted(sigs, key=lambda s: (s["impact_score"], _ts(s)), reverse=True)[:3]  # strongest, newest first
        rows.append({
            **meta,
            "ticker": next((s["ticker"] for s in reversed(sigs) if s.get("ticker")), None),
            "status": status, "status_reason": why,
            "signal_count": len(sigs), "negative_count": len(neg),
            "worst_impact": max((s["impact_score"] for s in sigs), default=None),
            "mean_sentiment": round(sum(s["sentiment_score"] for s in sigs) / len(sigs), 3) if sigs else None,
            "event_types": dict(Counter(s["event_type"] for s in sigs).most_common()),
            "sources": sorted({_source(s) for s in sigs}),
            "max_corroborating_sources": max((s["corroborating_sources"] for s in sigs), default=0),
            "top_signals": [_brief(s) for s in top],
            "impact_series": [{"timestamp": _ts(s).isoformat(), "impact_score": s["impact_score"],
                               "sentiment_score": s["sentiment_score"]} for s in sigs],
        })
    if settings is not None:  # second-order view: propagated exposure + propagation rule (curated links)
        from portfolio.propagation import propagated_exposure, propagation_monitor

        exposures = {k: v["exposure_mv"] for k, v in issuers.items()}
        for r in rows:
            p = propagated_exposure(r["issuer_id"], exposures, portfolio.funded_mv, settings)
            r["propagated_exposure"], r["propagated_pct"] = p["propagated_exposure"], p["propagated_pct"]
            r["linked_issuers"] = [c["issuer_id"] for c in p["contributions"]]
        for iid, why in propagation_monitor({r["issuer_id"]: r["status"] for r in rows}, settings).items():
            r = next(x for x in rows if x["issuer_id"] == iid)
            r.update(status=MONITOR, status_reason=why, via_propagation=True)
    rows.sort(key=lambda r: (-STATUS_RANK[r["status"]],
                             -max((s["impact_score"] for s in by_issuer[r["issuer_id"]]
                                   if s["sentiment_score"] <= rules.negative_sentiment), default=0.0),
                             -r["exposure_mv"]))
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    counts = Counter(r["status"] for r in rows)
    return {
        "as_of": as_of.isoformat(), "window_hours": hours,
        "counts": {k: counts.get(k, 0) for k in (WATCH, MONITOR, STABLE)},
        "rules": rules.describe(),
        "portfolio_source": portfolio.source_label,
        "signals_in_window": sum(len(v) for v in by_issuer.values()),
        "note": NOTE,
        "issuers": rows,
    }
