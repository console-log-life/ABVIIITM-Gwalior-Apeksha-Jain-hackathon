"""Evaluate sentiment, event classification and entity resolution against data/eval/labelled_headlines.csv.

Writes docs/evaluation.md (human-readable, with n for every number), data/eval/eval_results.json (machine-readable,
used by scripts/build_submission.py) and data/eval/predictions.csv (model outputs, kept separate from gold labels).

Gold labels whose label_status is 'draft_agent' were drafted by an AI assistant and are NOT human-reviewed; all
metrics are then reported as PRELIMINARY.

Usage:  python scripts/evaluate.py [--no-zero-shot]
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sklearn.metrics import accuracy_score, confusion_matrix, f1_score  # noqa: E402

from app.config import Settings, get_settings  # noqa: E402
from risk_engine.entity_resolution.resolver import get_resolver  # noqa: E402
from risk_engine.event_classifier.rules import RuleEventClassifier  # noqa: E402
from risk_engine.pipeline import classify_and_resolve  # noqa: E402
from risk_engine.schemas import EVENT_TYPES  # noqa: E402
from risk_engine.sentiment.finbert import SentimentEngine  # noqa: E402

EVAL_CSV = ROOT / "data" / "eval" / "labelled_headlines.csv"
OUT_MD = ROOT / "docs" / "evaluation.md"
OUT_JSON = ROOT / "data" / "eval" / "eval_results.json"
OUT_PRED = ROOT / "data" / "eval" / "predictions.csv"
SENT_LABELS = ["Negative", "Neutral", "Positive"]


def load_rows() -> list[dict]:
    rows = list(csv.DictReader(open(EVAL_CSV, encoding="utf-8")))
    for r in rows:
        if r["gold_event"] not in EVENT_TYPES:
            raise ValueError(f"row {r['id']}: unknown gold_event {r['gold_event']!r}")
        if r["gold_sentiment"] not in SENT_LABELS:
            raise ValueError(f"row {r['id']}: unknown gold_sentiment {r['gold_sentiment']!r}")
    return rows


def entity_key(res) -> str:
    if res.kind in ("MARKET", "UNRESOLVED"):
        return res.kind
    if res.ticker:
        return res.ticker
    return res.issuer_id or res.company


def metrics(gold: list[str], pred: list[str], labels: list[str] | None = None) -> dict:
    labels = labels or sorted(set(gold) | set(pred))
    return {"n": len(gold), "accuracy": round(accuracy_score(gold, pred), 3),
            "macro_f1": round(f1_score(gold, pred, labels=sorted(set(gold)), average="macro", zero_division=0), 3),
            "labels": labels, "confusion": confusion_matrix(gold, pred, labels=labels).tolist()}


def md_confusion(m: dict, title: str) -> str:
    labels = m["labels"]
    short = {lab: lab.replace("Product Launch", "Product").replace("Credit Event", "Credit")
             .replace("Macroeconomic", "Macro").replace("Geopolitical", "Geo").replace("Supply Chain", "Supply")
             .replace("Management", "Mgmt").replace("Litigation", "Litig.").replace("Regulatory", "Reg.")
             for lab in labels}
    out = [f"**{title}** (rows = gold, columns = predicted)", "",
           "| gold \\ pred | " + " | ".join(short[x] for x in labels) + " |",
           "|---|" + "---:|" * len(labels)]
    for lab, row in zip(labels, m["confusion"], strict=True):
        out.append(f"| {short[lab]} | " + " | ".join(str(v) if v else "·" for v in row) + " |")
    return "\n".join(out)


def git_head() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True,
                              timeout=10).stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-zero-shot", action="store_true", help="skip the zero-shot comparison")
    args = ap.parse_args()

    rows = load_rows()
    n = len(rows)
    draft = sum(r["label_status"] == "draft_agent" for r in rows)
    preliminary = draft > 0
    texts = [r["text"] for r in rows]
    gold_s = [r["gold_sentiment"] for r in rows]
    gold_e = [r["gold_event"] for r in rows]
    gold_t = [r["gold_ticker"] for r in rows]
    random_idx = [i for i, r in enumerate(rows) if r["selection"] == "random"]

    s = get_settings()
    finbert = SentimentEngine(Settings(sentiment_backend="finbert"))
    lexicon = SentimentEngine(Settings(sentiment_backend="lexicon"))
    fin = finbert.analyze_many([(t, None) for t in texts])
    lex = lexicon.analyze_many([(t, None) for t in texts])
    rules = RuleEventClassifier()
    resolver = get_resolver()
    pairs = [classify_and_resolve(rules, resolver, t, None) for t in texts]  # same guard as the pipeline
    ev = [e for e, _ in pairs]
    ents = [entity_key(r) for _, r in pairs]

    pred_s, pred_lex = [x.label for x in fin], [x.label for x in lex]
    pred_e = [e.primary for e in ev]

    def sub(values, idx):
        return [values[i] for i in idx]

    res = {
        "generated_at": datetime.now(UTC).isoformat(), "git_commit": git_head(), "preliminary": preliminary,
        "label_status": dict(Counter(r["label_status"] for r in rows)), "n": n, "n_random_subset": len(random_idx),
        "gold_distribution": {"sentiment": dict(Counter(gold_s)), "event": dict(Counter(gold_e))},
        "sentiment_finbert": metrics(gold_s, pred_s, SENT_LABELS),
        "sentiment_lexicon_fallback": metrics(gold_s, pred_lex, SENT_LABELS),
        "event_rules": metrics(gold_e, pred_e),
        "entity": {"n": n, "accuracy": round(accuracy_score(gold_t, ents), 3)},
        "random_subset": {
            "sentiment_finbert": metrics(sub(gold_s, random_idx), sub(pred_s, random_idx), SENT_LABELS),
            "event_rules": metrics(sub(gold_e, random_idx), sub(pred_e, random_idx)),
            "entity_accuracy": round(accuracy_score(sub(gold_t, random_idx), sub(ents, random_idx)), 3),
        },
        "stocktwits_tag_agreement": {"n": 0, "note": "not measured: StockTwits blocked (HTTP 403) on our network, "
                                                     "so no Bullish/Bearish-tagged messages were captured"},
    }

    zs_note = "skipped (--no-zero-shot)"
    if not args.no_zero_shot and s.zero_shot_model:
        from risk_engine.event_classifier.zero_shot import ZeroShotTieBreaker
        try:
            zs = RuleEventClassifier(zero_shot=ZeroShotTieBreaker())
            pred_zs = [classify_and_resolve(zs, resolver, t, None)[0].primary for t in texts]
            res["event_rules_plus_zero_shot"] = metrics(gold_e, pred_zs)
            gain = res["event_rules_plus_zero_shot"]["macro_f1"] - res["event_rules"]["macro_f1"]
            res["zero_shot_decision"] = {
                "macro_f1_rules": res["event_rules"]["macro_f1"],
                "macro_f1_rules_plus_zero_shot": res["event_rules_plus_zero_shot"]["macro_f1"],
                "gain": round(gain, 3), "enable_by_default": gain > 0, "model": s.zero_shot_model}
            zs_note = (f"rules {res['event_rules']['macro_f1']} vs rules+zero-shot "
                       f"{res['event_rules_plus_zero_shot']['macro_f1']} macro-F1 (n={n}) → "
                       f"{'ENABLE' if gain > 0 else 'keep OFF'}")
        except Exception as exc:  # model not downloaded: report honestly
            zs_note = f"not measured: zero-shot model unavailable ({type(exc).__name__}: {str(exc)[:120]})"
    res["zero_shot_note"] = zs_note

    with open(OUT_PRED, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "text", "gold_sentiment", "pred_sentiment", "sentiment_score", "gold_event", "pred_event",
                    "evidence", "gold_ticker", "pred_entity"])
        for r, fs, e, ent in zip(rows, fin, ev, ents, strict=True):
            w.writerow([r["id"], r["text"], r["gold_sentiment"], fs.label, fs.score, r["gold_event"], e.primary,
                        "; ".join(e.evidence), r["gold_ticker"], ent])
    OUT_JSON.write_text(json.dumps(res, indent=2), encoding="utf-8")
    write_markdown(res, rows)

    sf, er, en = res["sentiment_finbert"], res["event_rules"], res["entity"]
    print(f"{'PRELIMINARY (draft labels) — ' if preliminary else ''}n={n}")
    print(f"sentiment FinBERT : accuracy {sf['accuracy']}  macro-F1 {sf['macro_f1']}")
    print(f"sentiment lexicon : accuracy {res['sentiment_lexicon_fallback']['accuracy']}  "
          f"macro-F1 {res['sentiment_lexicon_fallback']['macro_f1']}")
    print(f"event rules       : accuracy {er['accuracy']}  macro-F1 {er['macro_f1']}")
    print(f"entity resolution : accuracy {en['accuracy']}")
    print(f"zero-shot         : {zs_note}")
    print(f"random subset n={len(random_idx)}: sentiment acc {res['random_subset']['sentiment_finbert']['accuracy']}, "
          f"event acc {res['random_subset']['event_rules']['accuracy']}, entity acc "
          f"{res['random_subset']['entity_accuracy']}")
    print(f"wrote {OUT_MD.relative_to(ROOT)}, {OUT_JSON.relative_to(ROOT)}, {OUT_PRED.relative_to(ROOT)}")
    return 0


def write_markdown(res: dict, rows: list[dict]) -> None:
    sf, sl = res["sentiment_finbert"], res["sentiment_lexicon_fallback"]
    er, rs = res["event_rules"], res["random_subset"]
    head = ("# Evaluation\n\n> **PRELIMINARY — gold labels drafted by an AI assistant, pending human review.** "
            f"{res['label_status'].get('draft_agent', 0)} of {res['n']} rows have `label_status=draft_agent`. "
            "These numbers must not be presented as final results.\n" if res["preliminary"] else "# Evaluation\n")
    lines = [
        head,
        f"Generated by `scripts/evaluate.py` at {res['generated_at']} (commit `{res['git_commit']}`).",
        "",
        "## Data",
        f"- `data/eval/labelled_headlines.csv`: **n = {res['n']}** real headlines/posts drawn from the CACHED_REAL "
        f"capture cache (Google News, GDELT, Reddit, Mastodon). {res['n_random_subset']} rows were sampled at random "
        f"(seed 42, stratified by source); the rest were keyword-targeted to cover rarer event classes, which can "
        "inflate rule-based recall, so random-subset metrics are reported separately.",
        f"- Gold sentiment distribution: {res['gold_distribution']['sentiment']}",
        f"- Gold event distribution: {res['gold_distribution']['event']} (no Supply Chain examples in the sample: "
        "that class is untested).",
        "- Labels were never produced by the models being evaluated. Model outputs are in `data/eval/predictions.csv`.",
        "",
        "## Results (headline text only)",
        "",
        "| Task | Metric | All rows | Random subset |",
        "|---|---|---:|---:|",
        f"| Sentiment (FinBERT) | accuracy | {sf['accuracy']} (n={sf['n']}) | {rs['sentiment_finbert']['accuracy']} "
        f"(n={rs['sentiment_finbert']['n']}) |",
        f"| Sentiment (FinBERT) | macro-F1 | {sf['macro_f1']} | {rs['sentiment_finbert']['macro_f1']} |",
        f"| Sentiment (lexicon fallback) | accuracy | {sl['accuracy']} (n={sl['n']}) | — |",
        f"| Sentiment (lexicon fallback) | macro-F1 | {sl['macro_f1']} | — |",
        f"| Event classification (rules) | accuracy | {er['accuracy']} (n={er['n']}) | {rs['event_rules']['accuracy']} "
        f"(n={rs['event_rules']['n']}) |",
        f"| Event classification (rules) | macro-F1 | {er['macro_f1']} | {rs['event_rules']['macro_f1']} |",
        f"| Entity resolution | accuracy | {res['entity']['accuracy']} (n={res['entity']['n']}) | "
        f"{rs['entity_accuracy']} |",
        "",
        f"**Zero-shot tie-breaker:** {res['zero_shot_note']}.",
        f"**StockTwits Bullish/Bearish agreement:** {res['stocktwits_tag_agreement']['note']} (n=0).",
        "",
        "Macro-F1 averages over the gold classes present. Entity resolution counts a hit when the predicted "
        "ticker / sovereign issuer_id / MARKET / UNRESOLVED equals the gold value.",
        "",
        "## Confusion matrices",
        "",
        md_confusion(sf, "Sentiment (FinBERT)"),
        "",
        md_confusion(er, "Event classification (rules)"),
        "",
        "## How to read this",
        "- The set is small and labelled by one annotator, an AI assistant, so the confidence intervals are wide. "
        "Treat the numbers as a smoke test, not a benchmark.",
        "- **Same-author bias:** the draft labels, the event taxonomy rules and the lexicon fallback were all written "
        "by the same AI assistant. Rule-based event accuracy and the lexicon's sentiment score are therefore likely "
        "flattered relative to FinBERT, which was trained independently. In particular, a lexicon scoring at or "
        "above FinBERT here is NOT evidence that the lexicon is the better model.",
        "- FinBERT sees headline text only. Many items are stock-price chatter ('shares rise 3%') or analyst actions, "
        "where FinBERT's labels and a human's sentiment judgement often differ.",
        "- Many real posts are not risk events. 'Other' is the largest gold class, so event accuracy is dominated by "
        "how well the rules abstain.",
        "- Re-run `python scripts/evaluate.py` after human review of the labels (set `label_status=human_reviewed`) "
        "to replace these preliminary numbers.",
    ]
    if "event_rules_plus_zero_shot" in res:
        lines += ["", md_confusion(res["event_rules_plus_zero_shot"], "Event classification (rules + zero-shot)")]
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
