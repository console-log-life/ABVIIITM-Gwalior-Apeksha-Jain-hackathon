"""Central configuration. Every tunable comes from the environment / .env via pydantic-settings."""

from __future__ import annotations

from enum import Enum
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class AppMode(str, Enum):
    LIVE = "LIVE"
    REPLAY = "REPLAY"
    SCENARIO = "SCENARIO"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Runtime
    app_mode: AppMode = AppMode.SCENARIO
    log_level: str = "INFO"
    log_dir: Path = Path("./logs")

    # Storage
    db_path: Path = Path("./data/risk_engine.db")
    cache_dir: Path = Path("./data/cache")

    # API / dashboard
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    api_base_url: str = "http://127.0.0.1:8000"

    # Optional keys
    finnhub_api_key: str = ""
    bluesky_handle: str = ""
    bluesky_app_password: str = ""

    # HTTP behaviour (bounded by spec: <=10 s general, <=20 s GDELT, <=2 retries)
    user_agent: str = "risk-signal-engine/0.1 (hackathon research prototype)"
    http_timeout_s: float = Field(default=10.0, gt=0, le=10.0)
    gdelt_timeout_s: float = Field(default=20.0, gt=0, le=20.0)
    http_max_retries: int = Field(default=2, ge=0, le=2)
    ingest_interval_s: int = Field(default=300, ge=30)

    # Models
    model_cache_dir: Path = Path("./models")
    finbert_model: str = "ProsusAI/finbert"
    # auto = FinBERT, falling back to the lexicon if the model cannot load; finbert | lexicon force one backend
    sentiment_backend: str = Field(default="auto", pattern="^(auto|finbert|lexicon)$")
    # CPU threads for torch (FinBERT). 2 keeps API + dashboard + browser responsive on a 4-core laptop.
    torch_threads: int = Field(default=2, ge=1, le=32)
    enable_zero_shot: bool = False
    # Fine-tuned models (notebooks/train_models.ipynb -> scripts/import_trained_models.py). Used when the folder exists;
    # otherwise base FinBERT / the rule engine. Set to an empty string to force the base model / rules.
    model_sentiment_path: str = "./models/finetuned/sentiment_finbert_ft"
    model_event_path: str = "./models/finetuned/event_distilroberta_ft"
    # Hybrid event classifier: rules stay authoritative for these classes when their rule score reaches the minimum
    event_rules_authoritative: list[str] = ["Credit Event", "Supply Chain", "Litigation"]
    event_rules_authoritative_min_score: float = Field(default=2.0, ge=0)
    event_model_min_confidence: float = Field(default=0.6, ge=0, le=1)  # below this the rules decide
    model_quantize_int8: bool = False  # torch dynamic int8 quantisation of Linear layers (CPU RAM/latency)
    zero_shot_model: str = "typeform/distilbert-base-uncased-mnli"

    # NLP thresholds
    sentiment_neg_threshold: float = Field(default=-0.25, ge=-1.0, le=0.0)
    sentiment_pos_threshold: float = Field(default=0.25, ge=0.0, le=1.0)
    near_dup_threshold: int = Field(default=92, ge=50, le=100)
    corroboration_window_h: float = Field(default=6.0, gt=0)

    # Stress triggers
    trigger_systemic_min_impact: float = Field(default=7.0, ge=1, le=10)
    trigger_systemic_severe_impact: float = Field(default=8.5, ge=1, le=10)
    trigger_idiosyncratic_min_impact: float = Field(default=6.0, ge=1, le=10)
    # idiosyncratic (issuer) stress only for negative news: positive court/regulator news must not trigger
    trigger_idiosyncratic_max_sentiment: float = Field(default=-0.25, ge=-1, le=1)
    trigger_cooldown_min: int = Field(default=30, ge=0)
    # Only signals from these NEWS sources may trigger systemic (market-level) stress; social only corroborates.
    systemic_trigger_sources: list[str] = ["google_news", "finnhub", "gdelt"]
    risk_appetite_loss_pct: float = Field(default=2.0, gt=0)

    # Early-warning watchlist (GET /watchlist): rules-based status per HELD issuer; see docs/methodology.md
    watchlist_window_h: int = Field(default=24, ge=1, le=720)
    watchlist_negative_sentiment: float = Field(default=-0.25, ge=-1, le=0)  # a signal is "negative" at or below
    watchlist_watch_impact: float = Field(default=7.0, ge=1, le=10)  # one negative signal this strong → WATCH
    watchlist_watch_count: int = Field(default=2, ge=1)  # ...or this many negative signals
    watchlist_watch_count_impact: float = Field(default=5.0, ge=1, le=10)  # ...each at least this strong
    watchlist_monitor_impact: float = Field(default=4.0, ge=1, le=10)  # one negative signal this strong → MONITOR

    # Portfolio
    transaction_data_path: Path | None = None
    portfolio_path: Path = Path("./portfolio/portfolio_data.csv")

    # Demo / replay
    demo_seed: int = 42
    demo_step_seconds: float = Field(default=10.0, ge=0)
    demo_story_path: Path = Path("./data/scenarios/demo_story.json")
    replay_limit: int = Field(default=120, ge=1)
    replay_delay_s: float = Field(default=0.5, ge=0)

    @field_validator("transaction_data_path", mode="before")
    @classmethod
    def _blank_to_none(cls, v: object) -> object:
        return None if v in ("", None) else v

    @field_validator("log_level")
    @classmethod
    def _upper_level(cls, v: str) -> str:
        v = v.upper()
        if v not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError(f"invalid LOG_LEVEL {v!r}")
        return v

    def resolve(self, p: Path) -> Path:
        """Resolve a configured path relative to the project root (not the CWD)."""
        return p if p.is_absolute() else (PROJECT_ROOT / p).resolve()

    @property
    def db_file(self) -> Path:
        return self.resolve(self.db_path)

    @property
    def models_dir(self) -> Path:
        return self.resolve(self.model_cache_dir)

    @property
    def cache_path(self) -> Path:
        return self.resolve(self.cache_dir)

    @property
    def has_finnhub(self) -> bool:
        return bool(self.finnhub_api_key.strip())

    @property
    def has_bluesky(self) -> bool:
        return bool(self.bluesky_handle.strip() and self.bluesky_app_password.strip())

    @property
    def uses_provided_portfolio(self) -> bool:
        return self.transaction_data_path is not None and self.resolve(self.transaction_data_path).exists()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


STRESS_DISCLAIMER = (
    "Simplified, illustrative hackathon stress model. Not a production or regulatory risk model."
)
