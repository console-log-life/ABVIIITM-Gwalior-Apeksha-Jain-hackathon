"""Public, human-labelled training/evaluation data: label maps and deterministic, leakage-free splits.

This file is the SINGLE source of the split logic. scripts/datasets/prepare_public.py runs it locally, and
scripts/build_training_notebook.py inlines it verbatim into notebooks/train_models.ipynb, so the Kaggle/Colab run
rebuilds exactly the same splits and checks them against the checksums committed in data/splits/*.json.

Splits (seed 42):
  test  = the dataset's own "validation" split, untouched, used ONLY for the final evaluation;
  train = the dataset's "train" split minus any row that leaks into test (same text after URL stripping, or
          rapidfuzz ratio >= 92 against any test text);
  dev   = a stratified 10% of the remaining train rows (early stopping / model selection).
Dependencies: numpy and rapidfuzz only (no project imports), so the notebook can run it standalone.
"""

from __future__ import annotations

import hashlib
import json
import re

import numpy as np
from rapidfuzz import fuzz, process

SEED = 42
DEV_FRACTION = 0.10
LEAK_THRESHOLD = 92  # rapidfuzz ratio, same threshold as our near-duplicate filter

DATASETS = {
    "sentiment": {
        "hf_id": "zeroshot/twitter-financial-news-sentiment",
        "licence": "MIT (dataset card: 'released under the MIT License')",
        "labels": ["Bearish", "Bullish", "Neutral"],  # dataset label ids 0, 1, 2
        "to_ours": {"Bearish": "Negative", "Bullish": "Positive", "Neutral": "Neutral"},
    },
    "topic": {
        "hf_id": "zeroshot/twitter-financial-news-topic",
        "licence": "MIT (dataset card: 'released under the MIT License')",
        "labels": ["Analyst Update", "Fed | Central Banks", "Company | Product News", "Treasuries | Corporate Debt",
                   "Dividend", "Earnings", "Energy | Oil", "Financials", "Currencies", "General News | Opinion",
                   "Gold | Metals | Materials", "IPO", "Legal | Regulation", "M&A | Investments", "Macro", "Markets",
                   "Politics", "Personnel Change", "Stock Commentary", "Stock Movement"],
        # to_ours comes from risk_engine/event_classifier/taxonomy.yaml (topic_map)
    },
}

_URL = re.compile(r"https?://\S+|www\.\S+")
_WS = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Comparison form: lower case, links removed (tweets often differ only by their t.co link), spaces collapsed."""
    return _WS.sub(" ", _URL.sub(" ", text.lower())).strip()


def leakage_ids(train_texts: list[str], test_texts: list[str], threshold: int = LEAK_THRESHOLD,
                workers: int = 2) -> list[int]:
    """Indices of train rows that duplicate or nearly duplicate ANY test row (removed from train, never from test)."""
    tr = [normalize(t) for t in train_texts]
    te = [normalize(t) for t in test_texts]
    exact = set(te)
    out = {i for i, t in enumerate(tr) if t in exact}
    rest = [i for i in range(len(tr)) if i not in out]
    if rest and te:
        scores = process.cdist([tr[i] for i in rest], te, scorer=fuzz.ratio, score_cutoff=threshold,
                               dtype=np.uint8, workers=workers)
        hit = np.nonzero(scores.max(axis=1) >= threshold)[0]
        out.update(rest[j] for j in hit.tolist())
    return sorted(out)


def stratified_dev(ids: list[int], labels: list[int], fraction: float = DEV_FRACTION, seed: int = SEED) -> list[int]:
    """A stratified `fraction` of `ids` (deterministic: numpy's legacy RandomState is stable across versions)."""
    rs = np.random.RandomState(seed)
    dev: list[int] = []
    for lab in sorted({labels[i] for i in ids}):
        members = [i for i in ids if labels[i] == lab]
        n_dev = max(1, int(round(len(members) * fraction)))
        perm = rs.permutation(len(members))
        dev.extend(members[j] for j in perm[:n_dev])
    return sorted(dev)


def checksum(split: dict) -> str:
    payload = json.dumps({k: split[k] for k in ("train_ids", "dev_ids", "test_ids")}, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def build_split(train_texts: list[str], train_labels: list[int], test_texts: list[str],
                threshold: int = LEAK_THRESHOLD, seed: int = SEED, fraction: float = DEV_FRACTION) -> dict:
    removed = leakage_ids(train_texts, test_texts, threshold)
    removed_set = set(removed)
    kept = [i for i in range(len(train_texts)) if i not in removed_set]
    dev = stratified_dev(kept, train_labels, fraction, seed)
    dev_set = set(dev)
    split = {"train_ids": [i for i in kept if i not in dev_set], "dev_ids": dev,
             "test_ids": list(range(len(test_texts))), "removed_leak_ids": removed,
             "seed": seed, "dev_fraction": fraction, "leak_threshold": threshold}
    split["sha256"] = checksum(split)
    return split


def map_labels(names: list[str], mapping: dict[str, str]) -> list[str]:
    missing = sorted(set(names) - set(mapping))
    if missing:
        raise ValueError(f"labels without a mapping: {missing}")
    return [mapping[n] for n in names]
