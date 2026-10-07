"""Portfolio loading.

- If TRANSACTION_DATA_PATH points to an existing CSV, it is loaded and must already use our column schema
  (no provided data exists for this build; a mapping layer would be added here and documented in
  docs/methodology.md). UI label: "Source: provided sample data".
- Otherwise data/portfolio/portfolio_data.csv is used; it is generated (seed 42) if missing. UI label: SYNTHETIC.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import pandas as pd

from app.config import Settings, get_settings
from portfolio.generate_portfolio import COLUMNS, generate

ASSET_TYPES = {"Loan", "Bond", "IRS", "CDS", "FXForward", "Equity"}
FUNDED_TYPES = {"Loan", "Bond", "Equity"}
RATING_BUCKETS = {"AAA-AA", "A", "BBB", "BB", "B-or-below"}
SIDES = {"pay_fixed", "receive_fixed", "protection_bought", "protection_sold", "long", "short"}


@dataclass(frozen=True)
class Portfolio:
    df: pd.DataFrame
    source_label: str  # "SYNTHETIC (generated, seed 42)" | "Source: provided sample data"
    provenance: str  # SYNTHETIC | PROVIDED
    path: str

    @property
    def funded_mv(self) -> float:
        return float(self.df.loc[self.df["asset_type"].isin(FUNDED_TYPES), "market_value"].sum())

    def positions(self) -> list[dict]:
        return self.df.to_dict(orient="records")


def validate(df: pd.DataFrame) -> pd.DataFrame:
    missing = [c for c in COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"portfolio is missing columns: {missing}")
    df = df[COLUMNS].copy()
    bad_type = set(df["asset_type"]) - ASSET_TYPES
    bad_rating = set(df["rating_bucket"]) - RATING_BUCKETS
    bad_side = set(df["side"]) - SIDES
    if bad_type or bad_rating or bad_side:
        raise ValueError(f"invalid values: asset_type {bad_type or '-'}, rating {bad_rating or '-'}, "
                         f"side {bad_side or '-'}")
    if df["asset_id"].duplicated().any():
        raise ValueError("duplicate asset_id values")
    df["issuer_id"] = df["issuer_id"].fillna("").astype(str)
    df["issuer_name"] = df["issuer_name"].fillna("").astype(str)
    df["is_floating"] = df["is_floating"].astype(str).str.lower().isin(["true", "1", "yes"])
    for c in ("notional", "market_value", "mod_duration", "convexity", "spread_duration", "pd_1y", "lgd", "dv01",
              "beta"):
        df[c] = pd.to_numeric(df[c], errors="raise").astype(float)
    return df


def load_portfolio(settings: Settings | None = None) -> Portfolio:
    s = settings or get_settings()
    if s.uses_provided_portfolio:
        path = s.resolve(s.transaction_data_path)
        return Portfolio(validate(pd.read_csv(path)), "Source: provided sample data", "PROVIDED", str(path))
    path = s.resolve(s.portfolio_path)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        generate(s.demo_seed).to_csv(path, index=False)
    return Portfolio(validate(pd.read_csv(path)), f"SYNTHETIC (generated, seed {s.demo_seed})", "SYNTHETIC",
                     str(path))


@lru_cache(maxsize=1)
def default_portfolio() -> Portfolio:
    return load_portfolio()


def issuer_exposures(portfolio: Portfolio | None = None) -> dict[str, float]:
    """issuer_id -> gross funded exposure (sum of market value of loans, bonds and equity)."""
    p = portfolio or default_portfolio()
    funded = p.df[p.df["asset_type"].isin(FUNDED_TYPES) & (p.df["issuer_id"] != "")]
    return {k: float(v) for k, v in funded.groupby("issuer_id")["market_value"].sum().items()}

