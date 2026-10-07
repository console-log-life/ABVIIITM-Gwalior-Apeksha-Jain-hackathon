"""Download all model weights once, then verify they load with the network disabled.

Usage:
  python src/scripts/setup_models.py              # FinBERT + spaCy en_core_web_sm
  python src/scripts/setup_models.py --zero-shot  # also the optional zero-shot model
  python src/scripts/setup_models.py --verify-only

After this succeeds, set HF_HUB_OFFLINE=1 and TRANSFORMERS_OFFLINE=1 for the offline demo.
"""

from __future__ import annotations

import argparse
import importlib
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from app.config import get_settings  # noqa: E402

SPACY_WHEEL_URL = (
    "https://github.com/explosion/spacy-models/releases/download/"
    "en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl"
)

VERIFY_SNIPPET = r"""
import sys
from transformers import AutoModelForSequenceClassification, AutoTokenizer
import torch
name, cache = sys.argv[1], sys.argv[2]
tok = AutoTokenizer.from_pretrained(name, cache_dir=cache, local_files_only=True)
mdl = AutoModelForSequenceClassification.from_pretrained(name, cache_dir=cache, local_files_only=True)
mdl.eval()
with torch.no_grad():
    enc = tok(["Company shares plunge after credit rating downgrade."], return_tensors="pt", truncation=True)
    probs = torch.softmax(mdl(**enc).logits, dim=-1)[0].tolist()
labels = {int(k): v for k, v in mdl.config.id2label.items()}
print("id2label=" + str(labels))
print("probs=" + str({labels[i]: round(p, 3) for i, p in enumerate(probs)}))
"""


def download_hf(name: str, cache: Path) -> None:
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    print(f"[download] {name} -> {cache}")
    AutoTokenizer.from_pretrained(name, cache_dir=str(cache))
    AutoModelForSequenceClassification.from_pretrained(name, cache_dir=str(cache))


def verify_hf_offline(name: str, cache: Path) -> bool:
    env = {**os.environ, "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"}
    proc = subprocess.run(
        [sys.executable, "-c", VERIFY_SNIPPET, name, str(cache)],
        env=env, capture_output=True, text=True, timeout=300,
    )
    if proc.returncode != 0:
        print(f"[verify] FAIL {name} offline load:\n{proc.stderr[-1500:]}")
        return False
    print(f"[verify] PASS {name} loads offline")
    for line in proc.stdout.strip().splitlines():
        print(f"         {line}")
    return True


def ensure_spacy(download: bool) -> bool:
    import spacy

    if not spacy.util.is_package("en_core_web_sm"):
        if not download:
            print("[verify] FAIL spaCy en_core_web_sm not installed")
            return False
        # Pinned wheel URL: skips spaCy's compatibility lookup, which needs an extra GitHub round-trip.
        rc = 1
        for attempt in range(1, 3):
            print(f"[download] spaCy {SPACY_WHEEL_URL.rsplit('/', 1)[-1]} (attempt {attempt}/2)")
            cmd = [sys.executable, "-m", "pip", "install", "--no-deps", SPACY_WHEEL_URL]
            rc = subprocess.run(cmd).returncode
            if rc == 0:
                break
        if rc != 0:
            print("[download] FAIL spaCy model download")
            return False
        importlib.invalidate_caches()
    nlp = spacy.load("en_core_web_sm")
    ents = [(e.text, e.label_) for e in nlp("Reliance Industries and Apple Inc. reported earnings.").ents]
    print(f"[verify] PASS spaCy en_core_web_sm loads; sample ents={ents}")
    return True


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows consoles default to cp1252
    ap = argparse.ArgumentParser()
    ap.add_argument("--zero-shot", action="store_true", help="also fetch the optional zero-shot model")
    ap.add_argument("--verify-only", action="store_true", help="skip downloads, only verify offline load")
    args = ap.parse_args()

    s = get_settings()
    cache = s.models_dir
    cache.mkdir(parents=True, exist_ok=True)
    # Keep every Hugging Face artefact (token, locks, xet cache) inside the project, not the user profile.
    os.environ.setdefault("HF_HOME", str(cache / ".hf_home"))
    models = [s.finbert_model] + ([s.zero_shot_model] if (args.zero_shot or s.enable_zero_shot) else [])

    ok = True
    for name in models:
        if not args.verify_only:
            try:
                download_hf(name, cache)
            except Exception as exc:  # network / hub errors must be reported, not crash silently
                print(f"[download] FAIL {name}: {type(exc).__name__}: {exc}")
                ok = False
                continue
        ok &= verify_hf_offline(name, cache)

    ok &= ensure_spacy(download=not args.verify_only)

    print("\nRESULT:", "ALL MODELS READY (offline-capable)" if ok else "SOME MODELS MISSING — see above")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
