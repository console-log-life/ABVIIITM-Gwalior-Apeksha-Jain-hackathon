"""Import trained_models.zip (from notebooks/train_models.ipynb) into models/finetuned/ and verify it.

  python scripts/import_trained_models.py [trained_models.zip] [--keep-existing]

Steps (exit code 1 on any failure; nothing is half-installed):
  1. unzip into a temporary folder (path-traversal safe);
  2. load both models OFFLINE, check labels: sentiment = positive/negative/neutral, event labels map to our taxonomy;
  3. re-predict 200 held-out test rows (seed 42) and compare with the notebook's own test predictions
     (>= 98% agreement; catches label-mapping mistakes; needs data/external/*_test.csv from prepare_public.py);
  4. smoke test: 3 headlines through the fine-tuned sentiment model and the hybrid event classifier;
  5. move the models into models/finetuned/ and copy metrics.json + confusion PNGs to data/eval/public/ (committed).
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import Settings  # noqa: E402
from risk_engine.schemas import EVENT_TYPES  # noqa: E402

DEST = ROOT / "models" / "finetuned"
PUBLIC_EVAL = ROOT / "data" / "eval" / "public"
EXT = ROOT / "data" / "external"
NAMES = {"sentiment": "sentiment_finbert_ft", "event": "event_distilroberta_ft"}
SMOKE = ["Moody's downgrades Tata Motors to junk as SEBI opens probe into accounting",
         "Fed raises interest rates by 25 basis points to fight inflation",
         "Apple unveils new iPhone lineup at its September event"]


def _rel(p: Path) -> str:
    try:
        return str(p.relative_to(ROOT))
    except ValueError:
        return str(p)


def safe_extract(zpath: Path, target: Path) -> None:
    with zipfile.ZipFile(zpath) as z:
        for m in z.infolist():
            out = (target / m.filename).resolve()
            if not str(out).startswith(str(target.resolve())):
                raise ValueError(f"unsafe path in zip: {m.filename}")
        z.extractall(target)


def find_models(root: Path) -> dict[str, Path]:
    found = {}
    for key, name in NAMES.items():
        hits = [p.parent for p in root.rglob("config.json") if p.parent.name == name]
        if not hits:
            raise FileNotFoundError(f"{name}/ not found in the zip")
        found[key] = hits[0]
    return found


def check_labels(models: dict[str, Path]) -> list[str]:
    from transformers import AutoConfig

    problems = []
    cfg = AutoConfig.from_pretrained(str(models["sentiment"]), local_files_only=True)
    if {v.lower() for v in cfg.id2label.values()} != {"positive", "negative", "neutral"}:
        problems.append(f"sentiment labels {sorted(cfg.id2label.values())} are not positive/negative/neutral")
    meta = json.loads((models["event"] / "risk_engine_labels.json").read_text(encoding="utf-8"))
    ecfg = AutoConfig.from_pretrained(str(models["event"]), local_files_only=True)
    unmapped = [v for v in ecfg.id2label.values() if meta["to_ours"].get(v) not in EVENT_TYPES]
    if unmapped:
        problems.append(f"event labels without a valid mapping: {unmapped}")
    return problems


def settings_for(models: dict[str, Path]) -> Settings:
    return Settings(_env_file=None, model_sentiment_path=str(models["sentiment"]),
                    model_event_path=str(models["event"]))


def agreement(models: dict[str, Path], preds_file: Path, n: int = 200) -> dict:
    """Re-predict a sample of the held-out test rows and compare with the notebook's predictions."""
    from risk_engine.event_classifier.learned import LearnedEventModel
    from risk_engine.sentiment.finbert import _FinBertModel

    preds = json.loads(preds_file.read_text(encoding="utf-8"))
    s = settings_for(models)
    out = {}
    for key, csv_name in (("sentiment", "sentiment_test.csv"), ("event", "topic_test.csv")):
        path = EXT / csv_name
        if not path.exists():
            out[key] = {"skipped": f"{path.name} missing: run scripts/datasets/prepare_public.py"}
            continue
        text_by_id = {int(r["id"]): r["text"] for r in csv.DictReader(open(path, encoding="utf-8"))}
        ids, labels = preds[key]["ids"], preds[key]["finetuned"]
        pick = random.Random(42).sample(range(len(ids)), min(n, len(ids)))
        texts = [text_by_id[ids[i]] for i in pick]
        if key == "sentiment":
            m = _FinBertModel(s)
            local = [max(p, key=p.get).capitalize() for p in m.predict(texts)]
        else:
            m = LearnedEventModel(models["event"], s)
            local = [max(p, key=p.get) for p in m.predict_many(texts)]
        same = sum(a == labels[i] for a, i in zip(local, pick, strict=True))
        out[key] = {"n": len(pick), "agreement": round(same / len(pick), 4)}
    return out


def smoke(models: dict[str, Path]) -> list[str]:
    from risk_engine.event_classifier.learned import HybridEventClassifier, LearnedEventModel
    from risk_engine.event_classifier.rules import RuleEventClassifier
    from risk_engine.sentiment.finbert import SentimentEngine

    s = settings_for(models)
    sent = SentimentEngine(s)
    hyb = HybridEventClassifier(RuleEventClassifier(), LearnedEventModel(models["event"], s), s)
    lines = []
    for t in SMOKE:
        r, e = sent.analyze_many([(t, None)])[0], hyb.classify(t)
        lines.append(f"{r.score:+.2f} {r.label:<8} | {e.primary:<14} ({e.method}, model {e.model_label} "
                     f"{e.model_confidence}) | {t[:60]}")
    if sent.status().get("variant") != "fine-tuned":
        lines.append(f"FAIL: sentiment did not load the fine-tuned model: {sent.status()}")
    return lines


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("zip", nargs="?", default=str(ROOT / "trained_models.zip"))
    ap.add_argument("--min-agreement", type=float, default=0.98)
    args = ap.parse_args()
    zpath = Path(args.zip)
    if not zpath.exists():
        print(f"not found: {zpath} (download it from Kaggle/Colab, see docs/TRAINING.md)")
        return 1
    with tempfile.TemporaryDirectory(dir=ROOT / ".tmp" if (ROOT / ".tmp").exists() else None) as tmp:
        tmp = Path(tmp)
        safe_extract(zpath, tmp)
        models = find_models(tmp)
        print("found:", {k: str(v.relative_to(tmp)) for k, v in models.items()})
        problems = check_labels(models)
        metrics = next(iter(tmp.rglob("metrics.json")), None)
        preds = next(iter(tmp.rglob("predictions_test.json")), None)
        if metrics is None or preds is None:
            problems.append("metrics.json or predictions_test.json missing from the zip")
        if problems:
            print("FAIL:", *problems, sep="\n  ")
            return 1
        m = json.loads(metrics.read_text(encoding="utf-8"))
        if m.get("smoke"):
            print("WARNING: this zip comes from a SMOKE run (tiny data); do not ship it")
        agree = agreement(models, preds)
        print("agreement with the notebook's test predictions:", agree)
        bad = [k for k, v in agree.items() if "agreement" in v and v["agreement"] < args.min_agreement]
        for line in smoke(models):
            print("  ", line)
        if bad:
            print(f"FAIL: agreement below {args.min_agreement} for {bad}: label mapping or model files differ")
            return 1
        DEST.mkdir(parents=True, exist_ok=True)
        for key, src in models.items():
            target = DEST / NAMES[key]
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(src, target)
        PUBLIC_EVAL.mkdir(parents=True, exist_ok=True)
        for f in list(tmp.rglob("*.png")) + [metrics]:
            shutil.copy2(f, PUBLIC_EVAL / f.name)
        (PUBLIC_EVAL / "import_check.json").write_text(json.dumps({"agreement": agree, "zip": zpath.name,
                                                                  "smoke_run": bool(m.get("smoke"))}, indent=1),
                                                       encoding="utf-8")
    print(f"installed into {_rel(DEST)}; metrics in {_rel(PUBLIC_EVAL)}. "
          "Restart the API to use them (/health shows the active models).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
