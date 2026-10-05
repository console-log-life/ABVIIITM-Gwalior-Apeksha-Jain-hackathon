"""Replay the local capture cache through the real pipeline (FinBERT) and the stress trigger rules, and report which
real headlines would have triggered stress runs.

Time is simulated from each document's timestamp, so the 30-minute cooldown behaves as it would have live.
Writes data/eval/trigger_replay_<label>.json and regenerates docs/trigger_replay.md (one column per stage).

Usage:  python scripts/replay_trigger_report.py --label n2_task1 [--captured-before 2026-10-04]
Stages (in table order): before (no fixes), night1 (news-only + figurative guards + 2-cue rule in classification),
n2_task1 (2-cue rule moved to triggers), n2_task2 (sentiment gate, verdict guard, rate direction).
"""

from __future__ import annotations

import argparse
import inspect
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import Settings, get_settings  # noqa: E402
from portfolio.loader import issuer_exposures, load_portfolio  # noqa: E402
from portfolio.stress_engine import StressEngine  # noqa: E402
from risk_engine.impact_scoring.corroboration import CorroborationTracker  # noqa: E402
from risk_engine.impact_scoring.scorer import ImpactScorer  # noqa: E402
from risk_engine.ingestion.replay import load_cached_documents  # noqa: E402
from risk_engine.pipeline import RiskPipeline  # noqa: E402
from risk_engine.sentiment.finbert import SentimentEngine  # noqa: E402

STAGES = [("before", "before fixes"), ("night1", "night-1 fixes"), ("n2_task1", "2-cue rule moved to triggers"),
          ("n2_task2", "+ sentiment gate, verdict guard, rate direction")]
NEWS = ("google_news", "finnhub", "gdelt")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    ap.add_argument("--captured-before", default="2026-10-04",
                    help="only documents captured before this UTC date (keeps the comparison set fixed); '' = all")
    args = ap.parse_args()

    s = get_settings()
    docs = load_cached_documents(s.cache_path)
    if args.captured_before:
        cutoff = datetime.fromisoformat(args.captured_before).replace(tzinfo=UTC)
        docs = [d for d in docs if d.captured_at < cutoff]
    portfolio = load_portfolio(s)
    pipe = RiskPipeline(sentiment=SentimentEngine(Settings(sentiment_backend="finbert")),
                        scorer=ImpactScorer(exposures=issuer_exposures(portfolio)),
                        corroboration=CorroborationTracker(6))
    engine = StressEngine(s, portfolio)
    now = {"t": 0.0}
    engine.triggers.clock = lambda: now["t"]
    takes_source = "source" in inspect.signature(engine.triggers.evaluate).parameters

    runs, candidates = [], []
    by_id = {d.doc_id: d for d in docs}
    for i in range(0, len(docs), 32):
        for sig in pipe.process_batch(docs[i : i + 32], skip_rejected=True):
            now["t"] = sig.timestamp.timestamp()
            doc = by_id[sig.doc_id]
            src = (doc.imitated_source or doc.source).value
            cands = engine.triggers.candidates(sig, source=src) if takes_source else engine.triggers.candidates(sig)
            for c in cands:
                candidates.append({"scenario": c.scenario, "source": src, "headline": doc.title[:140]})
            fired = engine.triggers.evaluate(sig, source=src) if takes_source else engine.triggers.evaluate(sig)
            for d in fired:
                runs.append({"scenario": d.scenario, "scope": d.scope_issuer_id or "MARKET", "kind": d.kind,
                             "source": src, "impact": sig.impact_score, "sentiment": sig.sentiment_score,
                             "event": sig.event_type, "entity": sig.company, "headline": doc.title[:140],
                             "rule": d.rule})

    out = {"label": args.label, "captured_before": args.captured_before, "documents": len(docs),
           "rule_candidates": len(candidates), "stress_runs": len(runs),
           "runs_by_kind": dict(Counter(r["kind"] for r in runs)),
           "runs_by_source": dict(Counter(r["source"] for r in runs)),
           "runs_by_scenario": dict(Counter(r["scenario"] for r in runs)), "runs": runs,
           "suppressed_by_cooldown": len(engine.triggers.suppressed)}
    path = ROOT / "data" / "eval" / f"trigger_replay_{args.label}.json"
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[{args.label}] {len(docs)} cached docs → {len(candidates)} rule candidates → {len(runs)} stress runs "
          f"(after cooldown); by kind {out['runs_by_kind']}; by source {out['runs_by_source']}")
    for r in runs:
        print(f"  {r['kind']:<13} {r['scenario']:<26} {r['source']:<11} {r['impact']:>4} {r['event']:<13} "
              f"{r['entity'][:16]:<16} {r['headline'][:90]}")
    print(f"wrote {path.relative_to(ROOT)}")
    write_comparison()
    return 0


def _social(d: dict) -> int:
    return sum(v for k, v in d["runs_by_source"].items() if k not in NEWS)


def _row(r: dict, with_impact: bool = False) -> str:
    impact = f" {r['impact']} |" if with_impact else ""
    return f"| {r['kind']} | {r['scenario']} | {r['source']} |{impact} {r['headline'].replace('|', '/')} |"


def write_comparison() -> None:
    """docs/trigger_replay.md: one column per available stage; removed/remaining lists vs the first stage."""
    stages = []
    for label, title in STAGES:
        p = ROOT / "data" / "eval" / f"trigger_replay_{label}.json"
        if p.exists():
            stages.append((title, json.loads(p.read_text(encoding="utf-8"))))
    if len(stages) < 2:
        return
    first, last = stages[0][1], stages[-1][1]
    head = "| | " + " | ".join(t for t, _ in stages) + " |"
    sep = "|---|" + "---:|" * len(stages)

    def line(name, fn):
        return f"| {name} | " + " | ".join(str(fn(d)) for _, d in stages) + " |"

    lines = [
        "# Stress-trigger replay over the local real cache",
        "",
        "Generated by `scripts/replay_trigger_report.py`: FinBERT, the full pipeline and the trigger rules, with time "
        "simulated from document timestamps so the 30-minute cooldown behaves as live. Input: every CACHED_REAL "
        f"document captured before {last.get('captured_before') or 'now'} in the developer's LOCAL capture cache, "
        "which is git-ignored and not published. Stress results are simulated (illustrative model).",
        "",
        head, sep,
        line("documents replayed", lambda d: d["documents"]),
        line("trigger-rule candidates", lambda d: d["rule_candidates"]),
        line("**stress runs (after cooldown)**", lambda d: f"**{d['stress_runs']}**"),
        line("systemic runs", lambda d: d["runs_by_kind"].get("systemic", 0)),
        line("idiosyncratic runs", lambda d: d["runs_by_kind"].get("idiosyncratic", 0)),
        line("runs triggered by social posts", _social),
        "",
        "Stages:",
        "- **night-1 fixes:** systemic stress only from news sources (social posts only corroborate), figurative-'war' "
        "guards, stricter fuzzy entity match, and a >= 2-cue rule applied in classification.",
        "- **2-cue rule moved to triggers (night 2, task 1):** classification restored. The >= 2 distinct-cue rule for "
        "MARKET-wide macro/geopolitical signals now only gates systemic stress runs.",
        "- **night 2, task 2:** idiosyncratic stress needs sentiment <= -0.25; analyst/opinion 'verdict' is not "
        "Litigation; rate direction is detected (cuts → `macro_rate_cut`, hikes → rate-shock scenarios, unclear → no "
        "systemic rate run).",
        "",
    ]
    if "runs_by_scenario" in last:
        lines += [f"Scenarios in the latest stage: {dict(sorted(last['runs_by_scenario'].items()))}", ""]
    last_heads = {r["headline"] for r in last["runs"]}
    first_heads = {r["headline"] for r in first["runs"]}
    removed = [r for r in first["runs"] if r["headline"] not in last_heads]
    added = [r for r in last["runs"] if r["headline"] not in first_heads]
    lines += [f"## Runs in '{stages[0][0]}' that no longer trigger ({len(removed)})", "",
              "| kind | scenario | source | headline |", "|---|---|---|---|"]
    lines += [_row(r) for r in removed]
    lines += ["", "Not every removed run was a false positive. Some genuine single-cue market stories no longer "
              "start a systemic run (recall cost). Read the list before relying on the totals.", "",
              f"## Runs that appear only in the latest stage ({len(added)})", "",
              "These come from new scenario mappings (for example rate cuts) or cooldown side effects.", "",
              "| kind | scenario | source | headline |", "|---|---|---|---|"]
    lines += [_row(r) for r in added]
    lines += ["", f"## All runs in the latest stage ({last['stress_runs']})", "",
              "| kind | scenario | source | impact | headline |", "|---|---|---|---:|---|"]
    lines += [_row(r, with_impact=True) for r in last["runs"]]
    newline = chr(10)
    (ROOT / "docs" / "trigger_replay.md").write_text(newline.join(lines) + newline, encoding="utf-8")
    print("wrote docs/trigger_replay.md")


if __name__ == "__main__":
    sys.exit(main())
