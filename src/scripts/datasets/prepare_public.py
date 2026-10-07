"""Download the PUBLIC human-labelled datasets, build leakage-free splits and write their provenance.

  python src/scripts/datasets/prepare_public.py            # both datasets (needs requirements-dev.txt: datasets)

Writes:
  data/splits/<key>.json         (COMMITTED) split ids + sha256 + HF revision: the notebook rebuilds and checks them
  data/external/<key>_{train,dev,test}.csv   (git-ignored) text, dataset label, our label
  data/external/DATASETS.md      (COMMITTED) source, licence, sizes, label sets, usage, leakage removed
"""

from __future__ import annotations

import csv
import json
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

import yaml  # noqa: E402
from huggingface_hub import HfApi  # noqa: E402

from datasets import load_dataset  # noqa: E402
from risk_engine.training.public_data import DATASETS, build_split  # noqa: E402

EXT = ROOT / "data" / "external"
SPLITS = ROOT / "data" / "splits"
TAXONOMY = ROOT / "src" / "risk_engine" / "event_classifier" / "taxonomy.yaml"


def our_map(key: str) -> dict[str, str]:
    if key == "topic":
        return yaml.safe_load(TAXONOMY.read_text(encoding="utf-8"))["topic_map"]
    return DATASETS[key]["to_ours"]


def prepare(key: str) -> dict:
    meta = DATASETS[key]
    revision = HfApi().dataset_info(meta["hf_id"]).sha
    ds = load_dataset(meta["hf_id"], revision=revision)
    tr, te = ds["train"], ds["validation"]
    t0 = time.time()
    split = build_split(list(tr["text"]), list(tr["label"]), list(te["text"]))
    split.update(dataset=meta["hf_id"], revision=revision, hf_train_rows=len(tr), hf_validation_rows=len(te),
                 test_source="HF 'validation' split (held out)", built_seconds=round(time.time() - t0, 1))
    SPLITS.mkdir(parents=True, exist_ok=True)
    (SPLITS / f"{key}.json").write_text(json.dumps(split, separators=(",", ":")) + "\n", encoding="utf-8")

    mapping, names = our_map(key), meta["labels"]
    EXT.mkdir(parents=True, exist_ok=True)
    rows = {"train": (tr, split["train_ids"]), "dev": (tr, split["dev_ids"]), "test": (te, split["test_ids"])}
    stats = {}
    for part, (src, ids) in rows.items():
        with open(EXT / f"{key}_{part}.csv", "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["id", "text", "label_id", "label", "our_label"])
            for i in ids:
                name = names[src[i]["label"]]
                w.writerow([i, src[i]["text"], src[i]["label"], name, mapping[name]])
        stats[part] = {"n": len(ids), "our_labels": dict(Counter(mapping[names[src[i]["label"]]] for i in ids)
                                                         .most_common())}
    return {"key": key, "meta": meta, "revision": revision, "split": split, "stats": stats, "mapping": mapping}


def write_md(results: list[dict]) -> None:
    out = ["# External datasets", "",
           "Downloaded by `src/scripts/datasets/prepare_public.py` with the Hugging Face `datasets` library. The data "
           "itself is git-ignored; the split ids (with sha256 checksums) are committed in `data/splits/` so the "
           "training notebook rebuilds exactly the same splits.", "",
           "**Split rule (seed 42):** test = the dataset's own `validation` split, held out and used only for the "
           "final evaluation; train rows that duplicate a test row (same text after removing links) or nearly "
           "duplicate one (rapidfuzz ratio >= 92) are removed from train; dev = a stratified 10% of the rest.",
           "", "**Financial PhraseBank is NOT used** to evaluate FinBERT: ProsusAI/finbert was trained on it.", ""]
    for r in results:
        m, s, sp = r["meta"], r["stats"], r["split"]
        out += [f"## {m['hf_id']}", "",
                f"- Source: https://huggingface.co/datasets/{m['hf_id']} (revision `{r['revision']}`)",
                f"- Licence: {m['licence']}",
                "- Text: English finance-related tweets (Twitter API), human-annotated.",
                f"- Rows on the hub: train {sp['hf_train_rows']}, validation {sp['hf_validation_rows']}",
                f"- Leakage removed from train: **{len(sp['removed_leak_ids'])}** rows "
                f"(duplicates/near-duplicates of test rows)",
                f"- Our splits: train **{s['train']['n']}**, dev **{s['dev']['n']}**, test **{s['test']['n']}** "
                f"(sha256 `{sp['sha256'][:16]}…`)",
                f"- Dataset labels ({len(m['labels'])}): " + ", ".join(m["labels"]),
                "- Mapping to our labels: " + "; ".join(f"{k} → {v}" for k, v in r["mapping"].items()),
                f"- Test label distribution (ours): {s['test']['our_labels']}",
                "- Used for: " + ("fine-tuning FinBERT sentiment and comparing base vs fine-tuned on the held-out test"
                                  if r["key"] == "sentiment" else
                                  "training the learned event classifier (hybrid with the rules) and comparing it with "
                                  "the rule engine on the held-out test"), ""]
    out += ["## Considered and skipped", "",
            "- **SEntFiN 1.0** (Indian financial news headlines, entity-level sentiment): the official copy is on "
            "Kaggle (`ankurzing/aspect-based-sentiment-analysis-for-financial-news`), which needs a logged-in Kaggle "
            "API token that this machine does not have. The only Hugging Face copy found "
            "(`temetnosce01/phrasebank_and_sentfin`) is a third-party mix with Financial PhraseBank and no clear "
            "licence, so it was not used. It can be added later if downloaded manually with its licence recorded.",
            "- **EDT** (corporate event detection, github.com/Zhihan1996/TradeTheEvent): hosted on Google Drive; the "
            "repository states no licence (GitHub reports none), and only 2 of its 11 event types (Acquisition, "
            "dividends) map to ours. Skipped because the licence is unclear.", ""]
    (EXT / "DATASETS.md").write_text("\n".join(out), encoding="utf-8")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    keys = sys.argv[1:] or ["sentiment", "topic"]
    results = []
    for k in keys:
        r = prepare(k)
        sp = r["split"]
        print(f"{k}: train {len(sp['train_ids'])} dev {len(sp['dev_ids'])} test {len(sp['test_ids'])} "
              f"leak-removed {len(sp['removed_leak_ids'])} ({sp['built_seconds']} s) sha256 {sp['sha256'][:12]}")
        results.append(r)
    write_md(results)
    print(f"wrote {EXT / 'DATASETS.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
