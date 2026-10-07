"""Generate the SYNTHETIC demo portfolio (seed 42) -> data/portfolio/portfolio_data.csv.

No sample transaction data was provided, so positions are generated. Target mix, measured on gross exposure
(market value for cash instruments, notional for derivative overlays):
  loans ~40%, bonds ~35%, derivative overlays (IRS / CDS / FX forwards) ~15%, equity <= 10%.
Includes CDS protection bought on two held high-yield issuers (hedges). Values in USD (INR positions are
expressed in USD equivalent). Every number here is synthetic.

Usage:  python -m portfolio.generate_portfolio [--seed 42] [--out data/portfolio/portfolio_data.csv]
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from risk_engine.entity_resolution.resolver import EntityResolver

ROOT = Path(__file__).resolve().parents[2]  # repository root
DEFAULT_OUT = ROOT / "data" / "portfolio" / "portfolio_data.csv"
GROSS_TOTAL = 1_000_000_000.0  # USD
MIX = {"Loan": 0.40, "Bond": 0.35, "Equity": 0.08, "IRS": 0.08, "CDS": 0.04, "FXForward": 0.05}
COLUMNS = ["asset_id", "asset_type", "issuer_id", "issuer_name", "sector", "country", "rating_bucket", "currency",
           "notional", "market_value", "mod_duration", "convexity", "spread_duration", "is_floating", "pd_1y", "lgd",
           "dv01", "side", "beta"]
BASE_PD = {"AAA-AA": 0.0002, "A": 0.0006, "BBB": 0.0020, "BB": 0.0100, "B-or-below": 0.0400}
# Walmart (US-WMT) and Pfizer (US-PFE) are deliberately NOT held, so "non-held resolved" signals exist.
LOAN_ISSUERS = ["US-JPM", "US-BAC", "US-GS", "US-TSLA", "US-F", "US-BA", "US-INTC", "US-AMZN", "US-XOM",
                "IN-RELIANCE", "IN-TATAMOTORS", "IN-ADANIENT", "IN-HDFCBANK", "IN-SBIN", "IN-INFY", "GB-HSBC"]
BOND_ISSUERS = ["SOV-US", "SOV-US", "SOV-IN", "US-AAPL", "US-MSFT", "US-JPM", "US-BAC", "US-F", "US-BA", "US-INTC",
                "US-META", "US-GOOGL", "IN-RELIANCE", "IN-TATAMOTORS", "IN-ADANIENT", "IN-SBIN", "GB-HSBC"]
EQUITY_ISSUERS = ["US-AAPL", "US-NVDA", "US-MSFT", "US-TSLA", "IN-RELIANCE", "IN-INFY"]
CDS_ISSUERS = ["IN-TATAMOTORS", "IN-ADANIENT", "US-F"]  # protection bought on held names


def _split(total: float, n: int, rng: np.random.Generator) -> np.ndarray:
    w = rng.uniform(0.6, 1.4, n)
    return total * w / w.sum()


def generate(seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    uni = {i.issuer_id: i for i in EntityResolver(use_spacy=False).issuers}
    rows: list[dict] = []

    def base(asset_type: str, iid: str | None, n: int) -> dict:
        iss = uni.get(iid) if iid else None
        return {
            "asset_id": f"{asset_type[:3].upper()}-{n:03d}", "asset_type": asset_type, "issuer_id": iid or "",
            "issuer_name": iss.name if iss else "", "sector": iss.sector if iss else "Rates/FX",
            "country": iss.country if iss else "US", "rating_bucket": iss.rating_bucket if iss else "AAA-AA",
            "currency": "INR" if iss and iss.country == "IN" else "USD", "notional": 0.0, "market_value": 0.0,
            "mod_duration": 0.0, "convexity": 0.0, "spread_duration": 0.0, "is_floating": False, "pd_1y": 0.0,
            "lgd": 0.0, "dv01": 0.0, "side": "long", "beta": 0.0,
        }

    for k, (iid, mv) in enumerate(zip(LOAN_ISSUERS, _split(GROSS_TOTAL * MIX["Loan"], len(LOAN_ISSUERS), rng),
                                      strict=True), 1):
        r = base("Loan", iid, k)
        floating = bool(rng.random() < 0.6)
        mat = float(rng.uniform(2, 6))
        pd1 = BASE_PD[r["rating_bucket"]] * float(rng.uniform(0.8, 1.25))
        r.update(notional=mv, market_value=mv, is_floating=floating, mod_duration=0.25 if floating else mat * 0.9,
                 spread_duration=mat * 0.9, pd_1y=round(pd1, 5), lgd=round(float(rng.uniform(0.35, 0.45)), 3))
        r["convexity"] = round(r["mod_duration"] ** 2 * 0.9, 3)
        rows.append(r)

    for k, (iid, mv) in enumerate(zip(BOND_ISSUERS, _split(GROSS_TOTAL * MIX["Bond"], len(BOND_ISSUERS), rng),
                                      strict=True), 1):
        r = base("Bond", iid, k)
        dur = float(rng.uniform(2.5, 9.0))
        r.update(notional=mv * float(rng.uniform(0.95, 1.05)), market_value=mv, mod_duration=round(dur, 3),
                 convexity=round(dur * (dur + 1) * 0.95, 3),
                 spread_duration=0.0 if r["sector"] == "Sovereign" and r["country"] == "US" else round(dur, 3),
                 pd_1y=round(BASE_PD[r["rating_bucket"]], 5), lgd=0.6)
        rows.append(r)

    for k, (iid, mv) in enumerate(zip(EQUITY_ISSUERS, _split(GROSS_TOTAL * MIX["Equity"], len(EQUITY_ISSUERS), rng),
                                      strict=True), 1):
        r = base("Equity", iid, k)
        r.update(notional=mv, market_value=mv, beta=round(float(rng.uniform(0.8, 1.5)), 2))
        rows.append(r)

    irs_sides = ["pay_fixed", "pay_fixed", "pay_fixed", "receive_fixed"]  # mostly hedging bond duration
    for k, (side, n) in enumerate(zip(irs_sides, _split(GROSS_TOTAL * MIX["IRS"], 4, rng), strict=True), 1):
        r = base("IRS", None, k)
        tenor = float(rng.choice([5.0, 7.0, 10.0]))
        r.update(notional=n, side=side, mod_duration=tenor * 0.88, dv01=round(n * tenor * 0.88 * 1e-4, 2))
        rows.append(r)

    for k, (iid, n) in enumerate(zip(CDS_ISSUERS, _split(GROSS_TOTAL * MIX["CDS"], len(CDS_ISSUERS), rng),
                                     strict=True), 1):
        r = base("CDS", iid, k)
        r.update(notional=n, side="protection_bought", spread_duration=round(float(rng.uniform(4.0, 4.8)), 3))
        rows.append(r)

    fx_sides = ["short", "short", "long"]  # short INR forwards hedge INR assets; one long INR carry position
    for k, (side, n) in enumerate(zip(fx_sides, _split(GROSS_TOTAL * MIX["FXForward"], 3, rng), strict=True), 1):
        r = base("FXForward", None, k)
        r.update(notional=n, side=side, currency="INR", country="IN", sector="Rates/FX")
        rows.append(r)

    df = pd.DataFrame(rows, columns=COLUMNS)
    for c in ("notional", "market_value"):
        df[c] = df[c].round(2)
    return df


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()
    df = generate(args.seed)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.out, index=False)
    gross = df["market_value"].where(df["market_value"] > 0, df["notional"])
    print(f"wrote {len(df)} SYNTHETIC positions to {args.out}")
    print((gross.groupby(df["asset_type"]).sum() / gross.sum()).round(3).to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
