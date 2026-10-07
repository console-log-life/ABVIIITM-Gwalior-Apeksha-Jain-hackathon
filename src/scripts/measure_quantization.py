"""Measure FinBERT with and without int8 dynamic quantisation: accuracy, RAM and latency.

  python src/scripts/measure_quantization.py

Runs each variant in its OWN process, one after the other (never two models in memory at once), on
  * our evaluation set (data/eval/labelled_headlines.csv, n = 147, labels preliminary) and
  * the public sentiment test split (data/external/sentiment_test.csv, if prepare_public.py has been run).
Writes data/eval/quantization_results.json and docs/quantization.md. Decision rule: int8 becomes the default only if
its accuracy on our set is within 1 point (0.01) of fp32.
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "src" / "scripts"))

OUT_JSON = ROOT / "data" / "eval" / "quantization_results.json"
OUT_MD = ROOT / "docs" / "quantization.md"
PUBLIC_TEST = ROOT / "data" / "external" / "sentiment_test.csv"
MAX_DROP = 0.01


def worker(variant: str) -> dict:
    import psutil

    from app.config import Settings
    from evaluate import load_rows, metrics
    from risk_engine.sentiment.finbert import SentimentEngine

    proc = psutil.Process()
    rss0 = proc.memory_info().rss
    t0 = time.perf_counter()
    eng = SentimentEngine(Settings(sentiment_backend="finbert", model_quantize_int8=(variant == "int8")))
    eng.analyze("warm-up")
    load_s = time.perf_counter() - t0
    rss_loaded = proc.memory_info().rss
    out: dict = {"variant": variant, "load_s": round(load_s, 1),
                 "model_rss_mb": round((rss_loaded - rss0) / 2**20), "process_rss_mb": round(rss_loaded / 2**20)}

    rows = load_rows()
    texts = [r["text"] for r in rows]
    t0 = time.perf_counter()
    pred = [x.label for x in eng.analyze_many([(t, None) for t in texts])]
    out["ours"] = metrics([r["gold_sentiment"] for r in rows], pred, ["Positive", "Neutral", "Negative"])
    out["ours"]["ms_per_doc"] = round(1000 * (time.perf_counter() - t0) / len(texts), 1)
    out["ours_predictions"] = pred
    if PUBLIC_TEST.exists():
        with open(PUBLIC_TEST, encoding="utf-8") as f:
            pub = list(csv.DictReader(f))
        t0 = time.perf_counter()
        ppred = []
        for i in range(0, len(pub), 64):  # small chunks keep the peak RAM low (the laptop often has < 1 GB free)
            ppred += [x.label for x in eng.analyze_many([(r["text"], None) for r in pub[i:i + 64]])]
        out["public_test"] = metrics([r["our_label"] for r in pub], ppred, ["Positive", "Neutral", "Negative"])
        out["public_test"]["ms_per_doc"] = round(1000 * (time.perf_counter() - t0) / len(pub), 1)
    mi = proc.memory_info()
    out["peak_process_mb"] = round(getattr(mi, "peak_wset", mi.rss) / 2**20)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--worker", choices=["fp32", "int8"], help=argparse.SUPPRESS)
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if args.worker:
        print(json.dumps(worker(args.worker)))
        return 0

    res: dict = {"generated_at": datetime.now(UTC).isoformat(), "max_accuracy_drop": MAX_DROP}
    for v in ("fp32", "int8"):
        print(f"measuring {v} (own process) ...", flush=True)
        p = subprocess.run([sys.executable, __file__, "--worker", v], capture_output=True, text=True,
                           encoding="utf-8", cwd=ROOT)
        if p.returncode != 0:
            print(p.stderr[-2000:])
            return 1
        res[v] = json.loads(p.stdout.strip().splitlines()[-1])
    a, b = res["fp32"], res["int8"]
    agree = sum(x == y for x, y in zip(a.pop("ours_predictions"), b.pop("ours_predictions"), strict=True))
    res["prediction_agreement_ours"] = round(agree / a["ours"]["n"], 3)
    drop = round(a["ours"]["accuracy"] - b["ours"]["accuracy"], 3)
    res["accuracy_drop_ours"] = drop
    res["int8_default"] = drop <= MAX_DROP
    OUT_JSON.write_text(json.dumps(res, indent=2), encoding="utf-8")

    def row(name: str, key: str) -> str:
        x, y = a.get(key), b.get(key)
        if not x:
            return ""
        return (f"| {name} | {x['n']} | {x['accuracy']:.3f} | {y['accuracy']:.3f} | {x['macro_f1']:.3f} | "
                f"{y['macro_f1']:.3f} | {x['ms_per_doc']} | {y['ms_per_doc']} |")

    md = ["# FinBERT int8 dynamic quantisation", "",
          f"Measured by `src/scripts/measure_quantization.py` on {res['generated_at'][:10]} (CPU, 2 torch threads; "
          "each variant in its own process). Our evaluation labels are still preliminary (draft, not yet human "
          "reviewed).", "",
          "| data set | n | accuracy fp32 | accuracy int8 | macro-F1 fp32 | macro-F1 int8 | ms/doc fp32 "
          "| ms/doc int8 |",
          "|---|---:|---:|---:|---:|---:|---:|---:|",
          row("our evaluation set", "ours"), row("public test split (twitter-financial-news-sentiment)",
                                                 "public_test"), "",
          "| memory | fp32 | int8 |", "|---|---:|---:|",
          f"| model RAM (process RSS after load minus before) | {a['model_rss_mb']} MB | {b['model_rss_mb']} MB |",
          f"| peak process working set | {a['peak_process_mb']} MB | {b['peak_process_mb']} MB |",
          f"| load time | {a['load_s']} s | {b['load_s']} s |", "",
          f"Same label for {res['prediction_agreement_ours']:.1%} of our {a['ours']['n']} items. Accuracy change on "
          f"our set: {-drop:+.3f}. Rule: int8 is the default only if accuracy drops by at most {MAX_DROP:.2f}. "
          f"**Decision: {'int8 ON by default' if res['int8_default'] else 'int8 stays OFF by default'}** "
          "(`MODEL_QUANTIZE_INT8` in `.env` overrides it)."]
    OUT_MD.write_text("\n".join(x for x in md if x is not None) + "\n", encoding="utf-8")
    print(OUT_MD.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
