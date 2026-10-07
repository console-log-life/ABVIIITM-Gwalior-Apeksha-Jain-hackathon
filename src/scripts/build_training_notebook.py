"""Generate src/notebooks/train_models.ipynb (and an identical .py for local smoke tests) from the repo's own code.

The split logic is inlined VERBATIM from src/risk_engine/training/public_data.py, and the expected split checksums and
dataset revisions come from data/splits/*.json, so the GPU run rebuilds exactly our splits (and stops if they differ).
The topic -> event mapping is inlined from taxonomy.yaml (topic_map).

  python src/scripts/build_training_notebook.py                 # writes src/notebooks/train_models.ipynb + .py
  RSE_SMOKE=1 RSE_SKIP_INSTALL=1 python src/notebooks/train_models.py   # tiny CPU run that exercises every cell
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
NB_DIR = ROOT / "src" / "notebooks"


def expected() -> dict:
    out = {}
    for key in ("sentiment", "topic"):
        s = json.loads((ROOT / "data" / "splits" / f"{key}.json").read_text(encoding="utf-8"))
        out[key] = {"revision": s["revision"], "sha256": s["sha256"], "train": len(s["train_ids"]),
                    "dev": len(s["dev_ids"]), "test": len(s["test_ids"])}
    return out


INTRO = """# Risk Signal Engine: fine-tune sentiment and event models on public human-labelled data

Runs top to bottom on a free **Kaggle** or **Google Colab** GPU (T4). Nothing needs editing; an optional Hugging Face
token can go in the first code cell. Steps: docs/TRAINING.md in the repository.

* **Sentiment:** fine-tunes `ProsusAI/finbert` on `zeroshot/twitter-financial-news-sentiment` (MIT).
* **Events:** fine-tunes `distilroberta-base` on `zeroshot/twitter-financial-news-topic` (MIT), mapped to our taxonomy.
  Two variants are trained (20 topics mapped at inference vs our classes directly); the one with the better **dev**
  macro-F1 is kept.
* **Evaluation:** on the held-out **test** split (the datasets' own validation split, never used for training or
  model selection): base FinBERT vs fine-tuned FinBERT, and the event model. The rule engine is evaluated on the same
  test split locally by `src/scripts/evaluate.py` (it needs the repository code).
* **Output:** `trained_models.zip` (< 1 GB): models in Hugging Face format, `metrics.json`, confusion-matrix PNGs and
  the test predictions used to verify the import on the laptop.

The splits are rebuilt with the repository's own code (inlined below) and checked against committed sha256 checksums.
"""

CONFIG = '''# ==== Configuration: the only cell you may edit ====
HF_TOKEN = ""  # optional Hugging Face read token (avoids anonymous rate limits); leave empty if you have none

import os
import time

SMOKE = os.environ.get("RSE_SMOKE") == "1"  # tiny CPU run used to test this notebook; stays False on Kaggle/Colab
SEED = 42
MAX_LEN = 64
LR = 2e-5
BATCH = 32
EPOCHS = 1 if SMOKE else 3
SENT_BASE = "ProsusAI/finbert"
EVENT_BASE = "distilroberta-base"
CACHE_DIR = os.environ.get("RSE_CACHE_DIR")  # local smoke runs reuse the repo's ./models cache
if os.path.isdir("/kaggle/working"):
    OUT = "/kaggle/working/out"
elif os.path.isdir("/content"):
    OUT = "/content/out"
else:
    OUT = os.environ.get("RSE_OUT", "out")
os.makedirs(OUT, exist_ok=True)
T_START = time.time()
print("output folder:", OUT, "| smoke run:", SMOKE)
'''

INSTALL = '''# Pinned packages (same versions as the repository). torch comes with the Kaggle/Colab image.
import subprocess
import sys

if os.environ.get("RSE_SKIP_INSTALL") != "1":
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "transformers==4.47.1", "datasets==3.0.1",
                    "rapidfuzz==3.11.0", "accelerate==1.2.1"], check=True)
import torch

GPU = torch.cuda.get_device_name(0) if torch.cuda.is_available() else "none (CPU)"
print("torch", torch.__version__, "| GPU:", GPU)
'''


def build_cells() -> list[tuple[str, str]]:
    src = (ROOT / "src" / "risk_engine" / "training" / "public_data.py").read_text(encoding="utf-8")
    src = src.replace("from __future__ import annotations\n", "")
    taxonomy = ROOT / "src/risk_engine/event_classifier/taxonomy.yaml"
    topic_map = yaml.safe_load(taxonomy.read_text("utf-8"))["topic_map"]
    exp = expected()
    splits = (f"# ---- inlined verbatim from src/risk_engine/training/public_data.py ----\n{src}\n"
              f"# ---- expected splits (data/splits/*.json) and the curated topic map (taxonomy.yaml) ----\n"
              f"EXPECTED = {json.dumps(exp, indent=1)}\n"
              f"TOPIC_MAP = {json.dumps(topic_map, indent=1)}\n")
    data = '''from datasets import load_dataset

data, split_info = {}, {}
for key in ("sentiment", "topic"):
    exp = EXPECTED[key]
    ds = load_dataset(DATASETS[key]["hf_id"], revision=exp["revision"], token=HF_TOKEN or None)
    tr_text, tr_lab = list(ds["train"]["text"]), list(ds["train"]["label"])
    te_text, te_lab = list(ds["validation"]["text"]), list(ds["validation"]["label"])
    split = build_split(tr_text, tr_lab, te_text)
    assert split["sha256"] == exp["sha256"], f"{key}: split checksum differs from the repository; stop"
    names = DATASETS[key]["labels"]
    parts = {"train": [(i, tr_text[i], names[tr_lab[i]]) for i in split["train_ids"]],
             "dev": [(i, tr_text[i], names[tr_lab[i]]) for i in split["dev_ids"]],
             "test": [(i, te_text[i], names[te_lab[i]]) for i in split["test_ids"]]}
    if SMOKE:
        parts = {k: v[: (64 if k == "train" else 32)] for k, v in parts.items()}
    data[key] = parts
    split_info[key] = {"dataset": DATASETS[key]["hf_id"], "revision": exp["revision"], "sha256": split["sha256"],
                       **{k: len(v) for k, v in parts.items()},
                       "leak_removed_from_train": len(split["removed_leak_ids"])}
    print(key, split_info[key])
'''
    helpers = '''import numpy as np
from PIL import Image, ImageDraw
from transformers import (AutoModelForSequenceClassification, AutoTokenizer, DataCollatorWithPadding,
                          EarlyStoppingCallback, Trainer, TrainingArguments, set_seed)

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
OUR_SENT = ["Negative", "Neutral", "Positive"]


def metrics(gold, pred, classes):
    """accuracy, macro-F1 over the GOLD classes present (as in src/scripts/evaluate.py), per-class F1, confusion."""
    idx = {c: i for i, c in enumerate(classes)}
    cm = np.zeros((len(classes), len(classes)), dtype=int)
    for g, p in zip(gold, pred):
        cm[idx[g], idx[p]] += 1
    per, f1s = {}, []
    for c, i in idx.items():
        tp, fp, fn, sup = cm[i, i], cm[:, i].sum() - cm[i, i], cm[i, :].sum() - cm[i, i], cm[i, :].sum()
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
        per[c] = {"precision": round(float(prec), 4), "recall": round(float(rec), 4), "f1": round(float(f1), 4),
                  "support": int(sup)}
        if sup:
            f1s.append(f1)
    return {"n": len(gold), "accuracy": round(float(np.trace(cm) / max(len(gold), 1)), 4),
            "macro_f1": round(float(np.mean(f1s)) if f1s else 0.0, 4), "per_class": per,
            "confusion": {"labels": classes, "matrix": cm.tolist()}}


def confusion_png(m, title, path):
    labels, cm = m["confusion"]["labels"], np.array(m["confusion"]["matrix"])
    cell, left, top = 46, 170, 60
    img = Image.new("RGB", (left + cell * len(labels) + 20, top + cell * len(labels) + 130), "white")
    d = ImageDraw.Draw(img)
    d.text((10, 10), f"{title}  (n={m['n']}, acc={m['accuracy']}, macro-F1={m['macro_f1']})", fill="black")
    d.text((10, 30), "rows = gold, columns = predicted", fill="gray")
    mx = max(int(cm.max()), 1)
    for r in range(len(labels)):
        d.text((5, top + r * cell + 16), labels[r][:24], fill="black")
        for c in range(len(labels)):
            v = int(cm[r, c])
            shade = 255 - int(200 * v / mx)
            d.rectangle([left + c * cell, top + r * cell, left + (c + 1) * cell - 2, top + (r + 1) * cell - 2],
                        fill=(shade, shade, 255))
            d.text((left + c * cell + 8, top + r * cell + 16), str(v), fill="black")
    for c in range(len(labels)):
        d.text((left + c * cell + 4, top + len(labels) * cell + 6 + (c % 3) * 14), labels[c][:8], fill="black")
    img.save(path)


@torch.no_grad()
def predict_probs(model, tok, texts, bs=128):
    model.to(DEVICE).eval()
    out = []
    for i in range(0, len(texts), bs):
        enc = tok(texts[i:i + bs], truncation=True, max_length=MAX_LEN, padding=True, return_tensors="pt").to(DEVICE)
        out.append(torch.softmax(model(**enc).logits.float(), dim=-1).cpu().numpy())
    return np.concatenate(out) if out else np.zeros((0, model.config.num_labels))


def softmax(logits):
    e = np.exp(logits - logits.max(axis=1, keepdims=True))
    return e / e.sum(axis=1, keepdims=True)


class EncDataset(torch.utils.data.Dataset):
    def __init__(self, tok, texts, labels):
        self.enc = tok(texts, truncation=True, max_length=MAX_LEN)
        self.labels = labels

    def __len__(self):
        return len(self.labels)

    def __getitem__(self, i):
        return {**{k: v[i] for k, v in self.enc.items()}, "labels": self.labels[i]}


class WeightedTrainer(Trainer):
    """Cross-entropy with class weights (imbalanced topics)."""

    def __init__(self, *a, class_weights=None, **kw):
        super().__init__(*a, **kw)
        self.class_weights = class_weights

    def compute_loss(self, model, inputs, return_outputs=False, **kw):
        labels = inputs.pop("labels")
        outputs = model(**inputs)
        w = None if self.class_weights is None else self.class_weights.to(outputs.logits.device)
        loss = torch.nn.functional.cross_entropy(outputs.logits.float(), labels, weight=w)
        return (loss, outputs) if return_outputs else loss


def train(model, tok, train_xy, dev_xy, dev_metric, name, class_weights=None):
    set_seed(SEED)
    args = TrainingArguments(
        output_dir=f"{OUT}/ckpt_{name}", eval_strategy="epoch", save_strategy="epoch", learning_rate=LR,
        per_device_train_batch_size=BATCH, per_device_eval_batch_size=128, num_train_epochs=EPOCHS,
        max_steps=2 if SMOKE else -1, weight_decay=0.01, warmup_ratio=0.06, load_best_model_at_end=True,
        metric_for_best_model="macro_f1", greater_is_better=True, save_total_limit=1, seed=SEED,
        fp16=torch.cuda.is_available(), report_to="none", logging_steps=50)
    trainer = WeightedTrainer(
        model=model, args=args, train_dataset=EncDataset(tok, *train_xy), eval_dataset=EncDataset(tok, *dev_xy),
        data_collator=DataCollatorWithPadding(tok), class_weights=class_weights,
        compute_metrics=lambda ev: {"macro_f1": dev_metric(softmax(np.asarray(ev.predictions)))},
        callbacks=[EarlyStoppingCallback(early_stopping_patience=1)])
    t0 = time.time()
    trainer.train()
    best = trainer.state.best_metric
    print(f"{name}: best dev macro-F1 {best} in {time.time() - t0:.0f} s")
    return trainer.model, round(float(best), 4), round(time.time() - t0, 1)


RESULTS = {"splits": split_info, "hyperparameters": {"max_len": MAX_LEN, "lr": LR, "batch": BATCH, "epochs": EPOCHS,
           "early_stopping": "patience 1 on dev macro-F1", "seed": SEED, "fp16": torch.cuda.is_available()},
           "macro_f1_definition": "mean F1 over the gold classes present in the evaluated split"}
PREDICTIONS = {}
'''
    sentiment = '''# ---- Model 1: SENTIMENT (FinBERT) ----
tok = AutoTokenizer.from_pretrained(SENT_BASE, cache_dir=CACHE_DIR)
base = AutoModelForSequenceClassification.from_pretrained(SENT_BASE, cache_dir=CACHE_DIR)
fb_id = {v.lower(): int(k) for k, v in base.config.id2label.items()}  # FinBERT: positive/negative/neutral
to_ours = DATASETS["sentiment"]["to_ours"]
S = data["sentiment"]


def sent_xy(part):
    return [t for _, t, _ in S[part]], [fb_id[to_ours[lab].lower()] for _, _, lab in S[part]]


def sent_names(ids, model):
    return [model.config.id2label[int(i)].capitalize() for i in ids]


test_x = [t for _, t, _ in S["test"]]
gold = [to_ours[lab] for _, _, lab in S["test"]]
base_pred = sent_names(predict_probs(base, tok, test_x).argmax(1), base)
dev_gold = [to_ours[lab] for _, _, lab in S["dev"]]
ft, dev_f1, secs = train(base, tok, sent_xy("train"), sent_xy("dev"),
                         lambda P: metrics(dev_gold, sent_names(P.argmax(1), base), OUR_SENT)["macro_f1"], "sentiment")
ft_pred = sent_names(predict_probs(ft, tok, test_x).argmax(1), ft)
RESULTS["sentiment"] = {"test_split": "held-out HF validation split", "base": metrics(gold, base_pred, OUR_SENT),
                        "finetuned": metrics(gold, ft_pred, OUR_SENT), "dev_macro_f1": dev_f1, "train_seconds": secs}
PREDICTIONS["sentiment"] = {"ids": [i for i, _, _ in S["test"]], "base": base_pred, "finetuned": ft_pred}
sent_dir = f"{OUT}/trained_models/sentiment_finbert_ft"
ft.save_pretrained(sent_dir, safe_serialization=True)
tok.save_pretrained(sent_dir)
json.dump({"task": "sentiment", "base_model": SENT_BASE, "label_space": "finbert",
           "to_ours": {v: v.capitalize() for v in fb_id}, "dataset": DATASETS["sentiment"]["hf_id"],
           "train_rows": len(S["train"]), "dev_macro_f1": dev_f1}, open(f"{sent_dir}/risk_engine_labels.json", "w"))
confusion_png(RESULTS["sentiment"]["base"], "Sentiment: base FinBERT", f"{OUT}/confusion_sentiment_base.png")
confusion_png(RESULTS["sentiment"]["finetuned"], "Sentiment: fine-tuned FinBERT", f"{OUT}/confusion_sentiment_ft.png")
print({k: (RESULTS["sentiment"][k]["accuracy"], RESULTS["sentiment"][k]["macro_f1"]) for k in ("base", "finetuned")})
del base
'''
    event = '''# ---- Model 2: EVENTS (distilroberta), two label spaces, pick by DEV macro-F1 on our classes ----
T = data["topic"]
TOPICS = DATASETS["topic"]["labels"]
OUR_EVENT = sorted(set(TOPIC_MAP.values()))
etok = AutoTokenizer.from_pretrained(EVENT_BASE, cache_dir=CACHE_DIR)
dev_gold = [TOPIC_MAP[lab] for _, _, lab in T["dev"]]
test_x = [t for _, t, _ in T["test"]]
test_gold = [TOPIC_MAP[lab] for _, _, lab in T["test"]]
variants = {}
for space, classes, to_label in (("topic20", TOPICS, lambda lab: lab), ("ours", OUR_EVENT, lambda lab: TOPIC_MAP[lab])):
    cid = {c: i for i, c in enumerate(classes)}
    y_tr = [cid[to_label(lab)] for _, _, lab in T["train"]]
    y_dev = [cid[to_label(lab)] for _, _, lab in T["dev"]]
    counts = np.bincount(y_tr, minlength=len(classes)).astype(float)
    weights = torch.tensor(len(y_tr) / (len(classes) * np.maximum(counts, 1.0)), dtype=torch.float)
    model = AutoModelForSequenceClassification.from_pretrained(
        EVENT_BASE, num_labels=len(classes), id2label=dict(enumerate(classes)), label2id=cid, cache_dir=CACHE_DIR)

    def to_ours_names(P, classes=classes):
        """Class decision from probabilities. Topic models: SUM the topic probabilities per mapped class, then argmax
        (identical to src/risk_engine/event_classifier/learned.py on the laptop)."""
        if classes is TOPICS:
            P = np.stack([P[:, [j for j, c in enumerate(classes) if TOPIC_MAP[c] == oc]].sum(1) for oc in OUR_EVENT], 1)
            return [OUR_EVENT[int(i)] for i in P.argmax(1)]
        return [classes[int(i)] for i in P.argmax(1)]

    model, dev_f1, secs = train(model, etok, ([t for _, t, _ in T["train"]], y_tr),
                                ([t for _, t, _ in T["dev"]], y_dev),
                                lambda P, f=to_ours_names: metrics(dev_gold, f(P), OUR_EVENT)["macro_f1"],
                                f"event_{space}", class_weights=weights)
    pred = to_ours_names(predict_probs(model, etok, test_x))
    variants[space] = {"model": model, "dev_macro_f1": dev_f1, "train_seconds": secs, "classes": classes,
                       "test": metrics(test_gold, pred, OUR_EVENT), "pred": pred}
    model.to("cpu")
selected = max(variants, key=lambda k: variants[k]["dev_macro_f1"])
v = variants[selected]
RESULTS["event"] = {"test_split": "held-out HF validation split, topics mapped with TOPIC_MAP",
                    "selected_label_space": selected, "selection": "higher DEV macro-F1 on our classes",
                    "variants": {k: {"dev_macro_f1": x["dev_macro_f1"], "train_seconds": x["train_seconds"],
                                     "test": x["test"]} for k, x in variants.items()},
                    "finetuned": v["test"], "classes": OUR_EVENT}
PREDICTIONS["event"] = {"ids": [i for i, _, _ in T["test"]], "finetuned": v["pred"]}
ev_dir = f"{OUT}/trained_models/event_distilroberta_ft"
v["model"].save_pretrained(ev_dir, safe_serialization=True)
etok.save_pretrained(ev_dir)
json.dump({"task": "event", "base_model": EVENT_BASE, "label_space": selected,
           "to_ours": {c: (TOPIC_MAP[c] if selected == "topic20" else c) for c in v["classes"]},
           "dataset": DATASETS["topic"]["hf_id"], "train_rows": len(T["train"]), "dev_macro_f1": v["dev_macro_f1"]},
          open(f"{ev_dir}/risk_engine_labels.json", "w"))
confusion_png(v["test"], f"Events: fine-tuned distilroberta ({selected})", f"{OUT}/confusion_event_ft.png")
print("selected", selected, {k: (x["dev_macro_f1"], x["test"]["macro_f1"]) for k, x in variants.items()})
'''
    save = '''# ---- Save metrics + predictions, zip everything ----
import shutil
import zipfile
from datetime import datetime, timezone

RESULTS.update(created_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"), gpu=GPU, smoke=SMOKE,
               total_seconds=round(time.time() - T_START, 1), torch=torch.__version__)
json.dump(RESULTS, open(f"{OUT}/metrics.json", "w"), indent=1)
json.dump(PREDICTIONS, open(f"{OUT}/predictions_test.json", "w"))
zpath = f"{OUT}/../trained_models.zip" if not SMOKE else f"{OUT}/trained_models.zip"
with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
    for root, _, files in os.walk(f"{OUT}/trained_models"):
        for f in files:
            full = os.path.join(root, f)
            z.write(full, os.path.relpath(full, OUT))
    for f in os.listdir(OUT):
        if f.endswith((".json", ".png")):
            z.write(os.path.join(OUT, f), f)
for d in os.listdir(OUT):
    if d.startswith("ckpt_"):
        shutil.rmtree(os.path.join(OUT, d), ignore_errors=True)
print(f"done in {RESULTS['total_seconds'] / 60:.1f} min on {GPU}; zip: {os.path.abspath(zpath)} "
      f"({os.path.getsize(zpath) / 1e6:.0f} MB)")
print(json.dumps({"sentiment": {k: RESULTS["sentiment"][k]["macro_f1"] for k in ("base", "finetuned")},
                  "event_selected": RESULTS["event"]["selected_label_space"],
                  "event_test_macro_f1": RESULTS["event"]["finetuned"]["macro_f1"]}, indent=1))
'''
    return [("markdown", INTRO), ("code", CONFIG), ("code", INSTALL), ("code", "import json\n\n" + splits),
            ("code", data), ("code", helpers), ("code", sentiment), ("code", event), ("code", save)]


def main() -> int:
    cells = build_cells()
    NB_DIR.mkdir(exist_ok=True)
    nb = {"nbformat": 4, "nbformat_minor": 5,
          "metadata": {"kernelspec": {"name": "python3", "display_name": "Python 3", "language": "python"},
                       "language_info": {"name": "python"}, "accelerator": "GPU"},
          "cells": [{"cell_type": t, "metadata": {}, "source": s.splitlines(keepends=True),
                     **({"execution_count": None, "outputs": []} if t == "code" else {}), "id": f"c{i}"}
                    for i, (t, s) in enumerate(cells)]}
    (NB_DIR / "train_models.ipynb").write_text(json.dumps(nb, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    py = "\n\n".join(s if t == "code" else '"""' + s + '"""' for t, s in cells)
    header = "# Generated by src/scripts/build_training_notebook.py; do not edit.\n# ruff: " + "noqa\n"
    (NB_DIR / "train_models.py").write_text(header + py, encoding="utf-8")
    print(f"wrote src/notebooks/train_models.ipynb ({len(cells)} cells) and src/notebooks/train_models.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
