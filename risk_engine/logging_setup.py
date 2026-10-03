"""Logging: human-readable console + rotating file. Call setup_logging() once at process start."""

from __future__ import annotations

import logging
import logging.handlers
import sys

from app.config import get_settings

_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
_configured = False


def setup_logging(level: str | None = None) -> None:
    global _configured
    if _configured:
        return
    settings = get_settings()
    lvl = getattr(logging, (level or settings.log_level).upper(), logging.INFO)

    root = logging.getLogger()
    root.setLevel(lvl)
    fmt = logging.Formatter(_FORMAT, datefmt="%Y-%m-%dT%H:%M:%S%z")

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    root.addHandler(console)

    log_dir = settings.resolve(settings.log_dir)
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(
            log_dir / "app.log", maxBytes=5_000_000, backupCount=3, encoding="utf-8"
        )
        fh.setFormatter(fmt)
        root.addHandler(fh)
    except OSError as exc:  # read-only FS etc. — console logging still works
        root.warning("file logging disabled: %s", exc)

    for noisy in ("httpx", "httpcore", "urllib3", "filelock", "huggingface_hub"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    _configured = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
