"""Module B: strategic portfolio stress testing. Subscribes to `signal.created` on the bus; triggered runs
(and manual runs) are stored with their triggering signal_id and published on `stress.completed`.

Simplified, illustrative hackathon stress model. Not a production or regulatory risk model.
"""

from __future__ import annotations

import asyncio
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from app.config import STRESS_DISCLAIMER, Settings
from portfolio.loader import FUNDED_TYPES, Portfolio, issuer_exposures, load_portfolio
from portfolio.pricers import Shock, reprice
from portfolio.triggers import TriggerDecision, TriggerEngine
from risk_engine.bus import SIGNAL_CREATED, STRESS_COMPLETED
from risk_engine.logging_setup import get_logger
from risk_engine.schemas import RiskSignal

if TYPE_CHECKING:
    from app.runtime import Runtime

log = get_logger(__name__)
SCENARIOS_YAML = Path(__file__).with_name("scenarios.yaml")
IG_BUCKETS = {"AAA-AA", "A", "BBB"}
SHOCK_KEYS = ("rates_bp", "ig_spread_bp", "hy_spread_bp", "equity_pct", "em_fx_pct", "pd_multiplier")


def hhi(weights: dict[str, float]) -> float:
    total = sum(abs(v) for v in weights.values())
    return 0.0 if total == 0 else round(sum((abs(v) / total) ** 2 for v in weights.values()), 4)


class StressEngine:
    def __init__(self, settings: Settings, portfolio: Portfolio | None = None, path: Path = SCENARIOS_YAML):
        self.settings = settings
        self.portfolio = portfolio or load_portfolio(settings)
        self.cfg = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        self.scenarios: dict[str, dict] = self.cfg["scenarios"]
        held = set(issuer_exposures(self.portfolio))
        self.triggers = TriggerEngine(settings, held, self.cfg["systemic_family"],
                                      rate_cut_scenario=self.cfg.get("rate_cut_scenario"))

    # ------------------------------------------------------------------ shocks
    def position_shock(self, pos: dict, shocks: dict[str, float], scope_issuer_id: str | None) -> Shock:
        if scope_issuer_id is not None and pos["issuer_id"] != scope_issuer_id:
            return Shock()  # idiosyncratic scenario: only the named issuer moves
        bucket = pos["rating_bucket"]
        scale = self.cfg["rating_spread_scaling"][bucket]
        base = shocks["ig_spread_bp"] if scale["base"] == "ig" else shocks["hy_spread_bp"]
        if scope_issuer_id is not None:  # issuer shock: +300 bp if investment grade, +600 bp if high yield
            spread = shocks["ig_spread_bp"] if bucket in IG_BUCKETS else shocks["hy_spread_bp"]
        else:
            spread = base * float(scale["factor"])
        m = 1 + (float(shocks["pd_multiplier"]) - 1) * float(self.cfg["pd_sensitivity"][bucket])
        if scope_issuer_id is not None:
            m = float(shocks["pd_multiplier"])
        fx = shocks["em_fx_pct"] if pos["currency"] != "USD" or pos["asset_type"] == "FXForward" else 0.0
        return Shock(rates_bp=float(shocks["rates_bp"]), spread_bp=float(spread),
                     equity_pct=float(shocks["equity_pct"]),
                     em_fx_pct=float(fx), pd_multiplier=m)

    # ------------------------------------------------------------------ run
    def run(self, scenario: str | None = None, scope_issuer_id: str | None = None, trigger_signal_id: str | None = None,
            rule: str | None = None, custom_shocks: dict[str, float] | None = None) -> tuple[dict, list[dict]]:
        if custom_shocks is not None:
            shocks = {k: float(custom_shocks.get(k, 0.0 if k != "pd_multiplier" else 1.0)) for k in SHOCK_KEYS}
            name, label = "custom", "Custom shock vector"
            rationale = "User-supplied shock vector."
        else:
            if scenario not in self.scenarios:
                raise KeyError(f"unknown scenario {scenario!r}; choose from {sorted(self.scenarios)}")
            sc = self.scenarios[scenario]
            if sc.get("issuer_only") and not scope_issuer_id:
                raise ValueError(f"scenario {scenario} needs an issuer_id")
            shocks = {k: float(sc["shocks"][k]) for k in SHOCK_KEYS}
            name, label, rationale = scenario, sc["label"], sc["rationale"]
        if scope_issuer_id and scope_issuer_id not in set(self.portfolio.df["issuer_id"]):
            raise ValueError(f"issuer {scope_issuer_id} is not held in the portfolio")

        positions = []
        for pos in self.portfolio.positions():
            dv = reprice(pos, self.position_shock(pos, shocks, scope_issuer_id))
            before = float(pos["market_value"])
            positions.append({
                "asset_id": pos["asset_id"], "asset_type": pos["asset_type"], "issuer_id": pos["issuer_id"] or None,
                "issuer_name": pos["issuer_name"] or None, "sector": pos["sector"], "country": pos["country"],
                "rating_bucket": pos["rating_bucket"], "side": pos["side"], "value_before": round(before, 2),
                "value_after": round(before + dv, 2), "pnl": round(dv, 2), "is_hedge": dv > 0,
            })
        summary = self._summarise(name, label, rationale, shocks, scope_issuer_id, trigger_signal_id, rule, positions)
        return summary, positions

    def _summarise(self, name, label, rationale, shocks, scope, trigger_signal_id, rule, positions) -> dict:
        before = self.portfolio.funded_mv
        pnl = sum(p["pnl"] for p in positions)
        loss = -pnl
        loss_pct = 100 * loss / before if before else 0.0
        limit = self.settings.risk_appetite_loss_pct
        rag = "GREEN" if loss_pct < 1.0 else ("AMBER" if loss_pct <= limit else "RED")

        def group(key: str) -> dict[str, float]:
            g: dict[str, float] = defaultdict(float)
            for p in positions:
                g[p[key] or "n/a"] += p["pnl"]
            return {k: round(v, 2) for k, v in sorted(g.items(), key=lambda kv: kv[1])}

        heat: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        for p in positions:
            heat[p["sector"]][p["asset_type"]] += p["pnl"]
        funded = [p for p in positions if p["asset_type"] in FUNDED_TYPES]
        by_sector_mv: dict[str, float] = defaultdict(float)
        by_issuer_mv: dict[str, float] = defaultdict(float)
        for p in funded:
            by_sector_mv[p["sector"]] += p["value_before"]
            if p["issuer_id"]:
                by_issuer_mv[p["issuer_id"]] += p["value_before"]
        top = sorted(positions, key=lambda p: abs(p["pnl"]), reverse=True)[:10]
        return {
            "run_id": str(uuid.uuid4()), "created_at": datetime.now(UTC).isoformat(), "scenario": name,
            "scenario_label": label, "rationale": rationale, "shocks": shocks, "scope_issuer_id": scope,
            "trigger_signal_id": trigger_signal_id, "rule": rule or "manual run",
            "before_value": round(before, 2), "after_value": round(before + pnl, 2), "pnl": round(pnl, 2),
            "loss": round(loss, 2), "loss_pct": round(loss_pct, 4), "rag": rag, "risk_appetite_loss_pct": limit,
            "hedge_offset": round(sum(p["pnl"] for p in positions if p["pnl"] > 0), 2),
            "by_asset_class": group("asset_type"), "by_sector": group("sector"), "by_issuer": group("issuer_id"),
            "by_country": group("country"),
            "heatmap": {s: {a: round(v, 2) for a, v in row.items()} for s, row in heat.items()},
            "top_contributors": [{k: p[k] for k in ("asset_id", "asset_type", "issuer_name", "sector", "pnl",
                                                     "is_hedge")}
                                 for p in top],
            "hhi_sector": hhi(by_sector_mv), "hhi_issuer": hhi(by_issuer_mv),
            "portfolio_source": self.portfolio.source_label, "disclaimer": STRESS_DISCLAIMER,
        }

    # ------------------------------------------------------------------ bus integration
    def evaluate(self, sig: RiskSignal, source: str | None = None) -> list[TriggerDecision]:
        return self.triggers.evaluate(sig, source)

    def reset(self) -> None:
        self.triggers.reset()

    def portfolio_info(self) -> dict[str, Any]:
        df = self.portfolio.df
        return {"source": self.portfolio.source_label, "provenance": self.portfolio.provenance,
                "positions": int(len(df)), "funded_mv": round(self.portfolio.funded_mv, 2),
                "held_issuers": len(self.triggers.held)}


def attach_stress_engine(rt: Runtime) -> StressEngine:
    """Create the engine, subscribe it to signal.created, and give the NLP scorer the portfolio exposures."""
    engine = StressEngine(rt.settings)
    rt.stress = engine
    exposures = issuer_exposures(engine.portfolio)

    async def on_signal(sig: RiskSignal) -> None:
        # effective source: a scenario document counts as the source it imitates (stored on the document row)
        row = await asyncio.to_thread(rt.store.get_signal, sig.signal_id)
        source = (row or {}).get("imitated_source") or sig.source.value
        for d in engine.evaluate(sig, source):
            summary, positions = await asyncio.to_thread(engine.run, d.scenario, d.scope_issuer_id, d.signal_id, d.rule)
            demo = sig.provenance.value == "SYNTHETIC"
            await asyncio.to_thread(rt.store.save_stress_run, summary, positions, demo)
            log.info("stress run %s: %s loss %.2f%% (%s) triggered by %s", summary["run_id"], d.scenario,
                     summary["loss_pct"], summary["rag"], sig.signal_id)
            await rt.bus.publish(STRESS_COMPLETED, summary)

    rt.bus.subscribe(SIGNAL_CREATED, on_signal)
    rt.exposures = exposures
    if rt.pipeline_ready():
        rt.pipeline.scorer.set_exposures(exposures)
    return engine
