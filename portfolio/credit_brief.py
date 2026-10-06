"""One-page issuer CREDIT BRIEF, template-based (no LLM): every sentence is filled from stored data and rules.

Sections: issuer + rating bucket; watch status and the rule that fired; exposure (direct + propagated over curated
links); the last N signals with their reason text; stress impact on this issuer's positions (an issuer-only shock
priced now, not saved, and the latest systemic run if one exists); hedges (CDS protection bought); disclaimer.
Rendered as HTML (dashboard) and PDF (fpdf2; core fonts, so text is mapped to Latin-1).
"""

from __future__ import annotations

import html
from datetime import UTC, datetime, timedelta
from typing import Any

from app.config import STRESS_DISCLAIMER, Settings
from portfolio.loader import FUNDED_TYPES
from portfolio.propagation import propagated_exposure
from portfolio.watchlist import NOTE, WatchRules, build_watchlist, issuer_table

N_SIGNALS = 6
ISSUER_SHOCK = "idiosyncratic_credit"


def build_brief(issuer_id: str, engine, store, settings: Settings, as_of: datetime | None = None) -> dict[str, Any]:
    """Collect everything the brief shows. `engine` = StressEngine, `store` = Store. Raises KeyError if not held."""
    port = engine.portfolio
    table = issuer_table(port)
    if issuer_id not in table:
        raise KeyError(issuer_id)
    meta = table[issuer_id]
    t = as_of or datetime.now(UTC)
    hours = settings.watchlist_window_h
    window = store.list_signals(since_ts=t - timedelta(hours=hours), until_ts=t, limit=50_000, ascending=True)
    wl = build_watchlist(port, window, WatchRules.from_settings(settings), hours, t, settings)
    row = next(r for r in wl["issuers"] if r["issuer_id"] == issuer_id)
    recent = [s for s in store.list_signals(limit=400, until_ts=t) if s.get("issuer_id") == issuer_id][:N_SIGNALS]
    exposures = {k: v["exposure_mv"] for k, v in table.items()}
    prop = propagated_exposure(issuer_id, exposures, port.funded_mv, settings)

    shock, shock_pos = engine.run(ISSUER_SHOCK, issuer_id, None, "credit brief (not saved)")
    mine = [p for p in shock_pos if p["issuer_id"] == issuer_id]
    positions = [{"asset_id": p["asset_id"], "asset_type": p["asset_type"], "side": p.get("side"),
                  "value_before": p["value_before"], "pnl": p["pnl"]} for p in mine]
    systemic = None
    latest = store.latest_stress_run(t)
    if latest and not latest.get("scope_issuer_id"):
        rows = [p for p in store.stress_positions(latest["run_id"]) if p["issuer_id"] == issuer_id]
        systemic = {"scenario_label": latest["scenario_label"], "created_at": latest.get("created_at"),
                    "loss_pct_book": latest["loss_pct"], "issuer_pnl": round(sum(p["pnl"] for p in rows), 2),
                    "rag": latest["rag"]}
    df = port.df[port.df["issuer_id"] == issuer_id]
    cds = df[(df["asset_type"] == "CDS") & (df["side"] == "protection_bought")]
    hedge_pnl = sum(p["pnl"] for p in mine if p["asset_type"] == "CDS")
    funded_pnl = sum(p["pnl"] for p in mine if p["asset_type"] in FUNDED_TYPES)
    ticker = row.get("ticker") or next((s.get("ticker") for s in recent if s.get("ticker")), None)
    return {
        "issuer_id": issuer_id, "issuer_name": meta["issuer_name"], "ticker": ticker, "sector": meta["sector"],
        "country": meta["country"], "rating_bucket": meta["rating_bucket"],
        "as_of": t.isoformat(timespec="minutes"), "generated_utc": datetime.now(UTC).isoformat(timespec="minutes"),
        "status": row["status"], "status_reason": row["status_reason"], "window_hours": hours,
        "signals_in_window": row["signal_count"], "rules": wl["rules"],
        "exposure": {"direct": meta["exposure_mv"], "direct_pct": meta["exposure_pct"],
                     "propagated": prop["propagated_exposure"], "propagated_pct": prop["propagated_pct"],
                     "total_pct": prop["total_pct"], "positions": meta["positions"],
                     "linked": [{"issuer_id": c["issuer_id"], "relation": c["relation"], "weight": c["weight"],
                                 "weighted": c["weighted"]} for c in prop["contributions"]]},
        "signals": [{k: s.get(k) for k in ("timestamp", "impact_score", "risk_level", "sentiment_score", "event_type",
                                            "reason", "text_excerpt", "provenance", "captured_at")} for s in recent],
        "stress": {"issuer_shock": {"scenario_label": shock["scenario_label"], "issuer_pnl": round(funded_pnl, 2),
                                    "hedge_pnl": round(hedge_pnl, 2), "net_pnl": round(funded_pnl + hedge_pnl, 2),
                                    "loss_pct_book": shock["loss_pct"], "shocks": shock["shocks"]},
                   "latest_systemic": systemic, "positions": positions},
        "hedges": {"cds_protection_notional": round(float(cds["notional"].sum()), 2),
                   "cds_positions": cds["asset_id"].tolist()},
        "portfolio_source": port.source_label, "note": NOTE, "disclaimer": STRESS_DISCLAIMER,
    }


def file_name(b: dict) -> str:
    tick = (b.get("ticker") or b["issuer_id"]).replace(".", "_").replace("/", "_")
    return f"credit_brief_{tick}_{b['as_of'][:10]}.pdf"


def _m(x: float) -> str:
    sign = "-" if x < 0 else ""
    return f"{sign}${abs(x) / 1e6:,.1f}m"


def summary_lines(b: dict) -> list[str]:
    """The brief's narrative, built from templates (the same text in HTML and PDF)."""
    e, s = b["exposure"], b["stress"]["issuer_shock"]
    lines = [
        f"{b['issuer_name']} is {b['status']} on the early-warning watchlist "
        f"({b['signals_in_window']} signals in the {b['window_hours']} h before {b['as_of'][:16]} UTC): "
        f"{b['status_reason']}.",
        f"We hold {_m(e['direct'])} ({e['direct_pct']:.2f}% of the funded book) across {e['positions']} positions, "
        f"rating bucket {b['rating_bucket']}. Linked issuers add {_m(e['propagated'])} of decay-weighted exposure "
        f"({e['propagated_pct']:.2f}%), {e['total_pct']:.2f}% in total.",
        f"An issuer-only shock ({s['scenario_label']}) would change these positions by {_m(s['issuer_pnl'])}"
        + (f", with CDS hedges offsetting {_m(s['hedge_pnl'])} (net {_m(s['net_pnl'])})" if s["hedge_pnl"] else
           ", with no CDS protection on this name") + f": {s['loss_pct_book']:.2f}% of the book.",
    ]
    sysr = b["stress"]["latest_systemic"]
    if sysr:
        lines.append(f"In the latest systemic run ({sysr['scenario_label']}, {str(sysr['created_at'])[:16]} UTC) "
                     f"this issuer's positions moved {_m(sysr['issuer_pnl'])}; the book lost "
                     f"{sysr['loss_pct_book']:.2f}% ({sysr['rag']}).")
    return lines


def render_html(b: dict) -> str:
    esc = html.escape
    sig_rows = "".join(
        f"<tr><td>{esc(str(s['timestamp'])[:16])}</td><td class='num'>{s['impact_score']:.1f}</td>"
        f"<td>{esc(s['risk_level'])}</td><td>{esc(s['event_type'])}</td><td class='num'>{s['sentiment_score']:+.2f}"
        f"</td><td>{esc(s['provenance'])}</td><td>{esc(s['reason'])}</td></tr>" for s in b["signals"]) or \
        "<tr><td colspan='7'>No signals on this issuer up to the selected time.</td></tr>"
    pos_rows = "".join(
        f"<tr><td>{esc(p['asset_id'])}</td><td>{esc(p['asset_type'])}</td><td>{esc(str(p['side']))}</td>"
        f"<td class='num'>{_m(p['value_before'])}</td><td class='num'>{_m(p['pnl'])}</td></tr>"
        for p in b["stress"]["positions"])
    linked = ", ".join(f"{esc(c['issuer_id'])} ({esc(c['relation'])} ×{c['weight']:g}: {_m(c['weighted'])})"
                       for c in b["exposure"]["linked"]) or "none (no curated links)"
    title = f"{esc(b['issuer_name'])}" + (f" ({esc(b['ticker'])})" if b.get("ticker") else "")
    paras = "".join(f"<p>{esc(x)}</p>" for x in summary_lines(b))
    return f"""<div class="brief">
<style>
.brief {{ font-family: 'IBM Plex Sans', Arial, sans-serif; color: #e6edf7; background: #111a2e;
         border: 1px solid #22304d;
         border-radius: 6px; padding: 18px 22px; }}
.brief h2 {{ font-family: 'Barlow Semi Condensed', Arial, sans-serif; margin: 0 0 4px 0; font-size: 1.5rem; }}
.brief .meta {{ color: #8b9bb8; font-size: 0.85rem; margin-bottom: 10px; }}
.brief .status {{ display: inline-block; padding: 1px 8px; border-radius: 4px; font-weight: 600; color: #0b1220;
                 background: {"#ef4444" if b["status"] == "WATCH-NEGATIVE" else ("#f5b841" if b["status"] == "MONITOR"
                                                                                   else "#22c55e")}; }}
.brief table {{ width: 100%; border-collapse: collapse; font-size: 0.82rem; margin: 6px 0 12px 0; }}
.brief th {{ text-align: left; color: #8b9bb8; border-bottom: 1px solid #22304d; padding: 4px 6px; }}
.brief td {{ border-bottom: 1px solid #1a2640; padding: 4px 6px; vertical-align: top; }}
.brief td.num {{ text-align: right; font-family: 'IBM Plex Mono', Consolas, monospace; }}
.brief h4 {{ margin: 12px 0 2px 0; color: #8b9bb8; text-transform: uppercase; font-size: 0.78rem;
             letter-spacing: 0.08em; }}
.brief .disc {{ border-left: 3px solid #ef4444; padding: 4px 10px; color: #8b9bb8; font-size: 0.8rem; }}
</style>
<h2>Credit brief · {title}</h2>
<div class="meta">{esc(b['sector'])} · {esc(b['country'])} · rating bucket {esc(b['rating_bucket'])} (illustrative) ·
as of {esc(b['as_of'][:16])} UTC · <span class="status">{esc(b['status'])}</span></div>
{paras}
<h4>Linked issuers (curated)</h4><p>{linked}</p>
<h4>Last {len(b['signals'])} signals</h4>
<table><tr><th>event time</th><th>impact</th><th>level</th><th>event</th><th>sent.</th><th>provenance</th>
<th>reason</th></tr>{sig_rows}</table>
<h4>Positions under the issuer-only shock (simulated)</h4>
<table><tr><th>asset</th><th>type</th><th>side</th><th>value</th><th>P&amp;L</th></tr>{pos_rows}</table>
<p class="meta">Hedges: CDS protection bought {_m(b['hedges']['cds_protection_notional'])} notional
({', '.join(b['hedges']['cds_positions']) or 'none'}). Portfolio: {esc(b['portfolio_source'])}.</p>
<div class="disc">{esc(b['disclaimer'])} {esc(b['note'])} Template-based brief generated from stored signals and
rules (no language model).</div>
</div>"""


_LATIN = str.maketrans({"→": "->", "≥": ">=", "≤": "<=", "−": "-", "×": "x", "…": "...", "–": "-", "—": "-",
                        "’": "'", "‘": "'", "“": '"', "”": '"', "₹": "Rs ", "€": "EUR ", "·": "|"})


def _latin(text: str) -> str:
    return str(text).translate(_LATIN).encode("latin-1", "replace").decode("latin-1")


def render_pdf(b: dict) -> bytes:
    from fpdf import FPDF

    pdf = FPDF(format="A4", unit="mm")
    pdf.set_auto_page_break(auto=True, margin=12)
    pdf.add_page()
    pdf.set_margins(14, 12, 14)
    w = pdf.w - 28
    pdf.set_font("Helvetica", "B", 16)
    title = b["issuer_name"] + (f" ({b['ticker']})" if b.get("ticker") else "")
    pdf.cell(w, 9, _latin(f"Credit brief: {title}"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(90, 100, 120)
    pdf.multi_cell(w, 5, _latin(f"{b['sector']} | {b['country']} | rating bucket {b['rating_bucket']} (illustrative) "
                                f"| as of {b['as_of'][:16]} UTC | status {b['status']}"), new_x="LMARGIN",
                   new_y="NEXT")
    pdf.set_text_color(0, 0, 0)
    pdf.ln(2)
    pdf.set_font("Helvetica", "", 10)
    for line in summary_lines(b):
        pdf.multi_cell(w, 5.2, _latin(line), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(1.5)

    def heading(text: str) -> None:
        pdf.ln(1)
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(w, 6, _latin(text.upper()), new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 8.5)

    heading("Linked issuers (curated links)")
    linked = "; ".join(f"{c['issuer_id']} ({c['relation']} x{c['weight']:g}: {_m(c['weighted'])})"
                       for c in b["exposure"]["linked"]) or "none"
    pdf.multi_cell(w, 4.6, _latin(linked), new_x="LMARGIN", new_y="NEXT")
    heading(f"Last {len(b['signals'])} signals")
    for s in b["signals"] or [{}]:
        if not s:
            pdf.multi_cell(w, 4.6, "No signals on this issuer up to the selected time.", new_x="LMARGIN",
                           new_y="NEXT")
            break
        pdf.multi_cell(w, 4.6, _latin(f"{str(s['timestamp'])[:16]} | impact {s['impact_score']:.1f} "
                                      f"{s['risk_level']} | {s['event_type']} | "
                                      f"sentiment {s['sentiment_score']:+.2f} | "
                                      f"{s['provenance']} | {s['reason']}"), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(0.8)
    heading("Positions under the issuer-only shock (simulated)")
    for p in b["stress"]["positions"]:
        pdf.cell(w, 4.6, _latin(f"{p['asset_id']:<10} {p['asset_type']:<10} {str(p['side']):<18} value "
                                f"{_m(p['value_before']):>9}   P&L {_m(p['pnl']):>8}"), new_x="LMARGIN", new_y="NEXT")
    pdf.multi_cell(w, 4.6, _latin(f"Hedges: CDS protection bought {_m(b['hedges']['cds_protection_notional'])} "
                                  f"notional. Portfolio: {b['portfolio_source']}."), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(150, 30, 30)
    pdf.multi_cell(w, 4.2, _latin(f"{b['disclaimer']} {b['note']} Template-based brief generated from stored signals "
                                  f"and rules (no language model). Generated {b['generated_utc'][:16]} UTC."),
                   new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())
