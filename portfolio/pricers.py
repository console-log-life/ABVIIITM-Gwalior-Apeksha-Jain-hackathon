"""Simplified, documented pricers (spec 8.2). Simplified, illustrative hackathon stress model.
Not a production or regulatory risk model.

Conventions (all ΔV in USD; positive = gain):
  Shocks: rates_bp, spread_bp in basis points; equity_pct, em_fx_pct as decimals.
  Bond      ΔV = MV × (−D·Δr − SD·Δs + ½·C·Δy²), Δy = Δr + Δs (decimal). For corporates SD = D, which is the spec
            formula MV × (−D·Δy + ½·C·Δy²); US Treasuries have SD = 0 (no credit-spread shock).
  Loan      ΔV = −EAD × LGD × (PD_stressed − PD_base), PD_stressed = min(PD_base × m_bucket, 1); EAD = notional.
            Fixed-rate loans add the rate effect −MV × D × Δr; floating-rate loans have ≈ 0 rate effect.
  IRS       DV01 is stored POSITIVE (USD per 1 bp). pay_fixed: ΔV = +DV01 × Δr_bp (gains when rates rise);
            receive_fixed: ΔV = −DV01 × Δr_bp.
  CDS       protection_bought: ΔV = +notional × spread_duration × Δs (gains when spreads widen);
            protection_sold: the negative of that.
  FXForward ΔV = notional × em_fx_pct × direction; direction = +1 for long the EM currency, −1 for short.
  Equity    ΔV = MV × equity_pct × beta (long); short positions take the opposite sign.
"""

from __future__ import annotations

from dataclasses import dataclass

BP = 1e-4


@dataclass(frozen=True)
class Shock:
    """Per-position shock after rating-bucket scaling and issuer scoping."""
    rates_bp: float = 0.0
    spread_bp: float = 0.0
    equity_pct: float = 0.0
    em_fx_pct: float = 0.0
    pd_multiplier: float = 1.0


def price_bond(mv: float, mod_duration: float, convexity: float, spread_duration: float, s: Shock) -> float:
    dr, ds = s.rates_bp * BP, s.spread_bp * BP
    dy = dr + (ds if spread_duration > 0 else 0.0)
    return mv * (-mod_duration * dr - spread_duration * ds + 0.5 * convexity * dy * dy)


def price_loan(ead: float, lgd: float, pd_base: float, is_floating: bool, mod_duration: float, mv: float,
               s: Shock) -> float:
    pd_stressed = min(pd_base * s.pd_multiplier, 1.0)
    credit = -ead * lgd * (pd_stressed - pd_base)
    rate = 0.0 if is_floating else -mv * mod_duration * s.rates_bp * BP
    return credit + rate


def price_irs(dv01: float, side: str, s: Shock) -> float:
    sign = {"pay_fixed": 1.0, "receive_fixed": -1.0}[side]
    return sign * abs(dv01) * s.rates_bp


def price_cds(notional: float, spread_duration: float, side: str, s: Shock) -> float:
    sign = {"protection_bought": 1.0, "protection_sold": -1.0}[side]
    return sign * notional * spread_duration * s.spread_bp * BP


def price_fx_forward(notional: float, side: str, s: Shock) -> float:
    direction = {"long": 1.0, "short": -1.0}[side]
    return notional * s.em_fx_pct * direction


def price_equity(mv: float, beta: float, side: str, s: Shock) -> float:
    sign = -1.0 if side == "short" else 1.0
    return sign * mv * s.equity_pct * beta


def reprice(pos: dict, s: Shock) -> float:
    """ΔV for one position row (dict with the portfolio columns)."""
    t = pos["asset_type"]
    if t == "Bond":
        return price_bond(pos["market_value"], pos["mod_duration"], pos["convexity"], pos["spread_duration"], s)
    if t == "Loan":
        return price_loan(pos["notional"], pos["lgd"], pos["pd_1y"], bool(pos["is_floating"]), pos["mod_duration"],
                          pos["market_value"], s)
    if t == "IRS":
        return price_irs(pos["dv01"], pos["side"], s)
    if t == "CDS":
        return price_cds(pos["notional"], pos["spread_duration"], pos["side"], s)
    if t == "FXForward":
        return price_fx_forward(pos["notional"], pos["side"], s)
    if t == "Equity":
        return price_equity(pos["market_value"], pos["beta"], pos["side"], s)
    raise ValueError(f"unknown asset_type {t!r}")
