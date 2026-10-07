"""Where the fine-tuned models live, and the shared int8 quantisation helper."""

from __future__ import annotations

import json
from pathlib import Path

from app.config import Settings

LABELS_FILE = "risk_engine_labels.json"  # written by src/notebooks/train_models.ipynb next to each model


def finetuned_dir(path_setting: str | None, settings: Settings) -> Path | None:
    """The fine-tuned model folder if it exists and looks like a Hugging Face model, else None (use base/rules)."""
    if not path_setting:
        return None
    p = settings.resolve(Path(path_setting))
    return p if (p / "config.json").exists() else None


def read_labels(model_dir: Path) -> dict:
    f = model_dir / LABELS_FILE
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}


def quantize_int8(model):
    """torch dynamic quantisation of Linear layers (CPU only): roughly halves RAM and speeds up inference."""
    import torch

    return torch.quantization.quantize_dynamic(model, {torch.nn.Linear}, dtype=torch.qint8)
