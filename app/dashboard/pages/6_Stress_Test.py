"""Sections 8–11: stress trigger banner, before/after waterfall, asset-level loss (hedges green), risk heatmap.
Plus manual scenario runs and the audit log. Every view carries the simplified-model disclaimer."""

from __future__ import annotations

import html

import pandas as pd
import streamlit as st
from components import charts
from components.ui import (
    RAG_COLORS,
    as_of,
    badge,
    disclaimer,
    fmt_ts,
    guard,
    kpi,
    money,
    provenance_badge,
    risk_badge,
    run_body,
    setup,
)

client = setup("Stress Testing (Module B)", "🧪")
disclaimer()


def trigger_banner(run: dict, signals_by_id: dict) -> None:
    sig = signals_by_id.get(run.get("trigger_signal_id"))
    rag = badge(run["rag"], RAG_COLORS.get(run["rag"], "#52514e"))
    if sig:
        trig = (f"{risk_badge(sig['risk_level'])}{provenance_badge(sig)} <b>{sig['impact_score']:.1f}</b> · "
                f"{html.escape(sig['company'])} · <i>{sig['event_type']}</i><br>“{html.escape(sig['text_excerpt'])}”")
    elif run.get("trigger_signal_id"):
        trig = f"signal {run['trigger_signal_id']} (no longer stored: the demo was reset)"
    else:
        trig = "manual run (no triggering signal)"
    st.markdown(
        f'<div class="alert">🚨 <b>{html.escape(run["scenario_label"])}</b> {rag} '
        f'simulated loss <b>{money(run["loss"])}</b> = <b>{run["loss_pct"]:.2f}%</b> of funded value '
        f'(risk appetite {run.get("risk_appetite_loss_pct", 2.0):.1f}%)<br>'
        f'<b>Trigger signal:</b> {trig}<br><b>Rule fired:</b> {html.escape(run["rule"])}<br>'
        f'<span style="color:#52514e">Scenario rationale: {html.escape(run.get("rationale", ""))} · '
        f'run {run["run_id"][:8]} at {fmt_ts(run["created_at"])}</span></div>', unsafe_allow_html=True)


SLIDERS = [  # (key, label, min, max, step, unit, to_api)
    ("rates_bp", "Rates (bp)", -300, 300, 5, "bp", 1.0),
    ("ig_spread_bp", "IG spread (bp)", -100, 500, 5, "bp", 1.0),
    ("hy_spread_bp", "HY spread (bp)", -200, 1200, 10, "bp", 1.0),
    ("equity_pct", "Equity (%)", -50, 20, 1, "%", 0.01),
    ("em_fx_pct", "EM FX (%)", -30, 10, 1, "%", 0.01),
    ("pd_multiplier", "PD multiplier (×)", 0.5, 5.0, 0.1, "×", 1.0),
]


def _load_scenario(scen: dict) -> None:
    name = st.session_state.get("wi_from")
    shocks = scen[name]["shocks"] if name in scen else {"pd_multiplier": 1.0}
    for key, _, lo, hi, _, unit, conv in SLIDERS:
        v = float(shocks.get(key, 1.0 if key == "pd_multiplier" else 0.0)) / conv
        st.session_state[f"wi_{key}"] = min(max(round(v, 2) if unit == "×" else round(v), lo), hi)


def what_if_panel(run: dict | None, scen: dict) -> None:
    """Interactive scenario builder: instant repricing through POST /portfolio/what-if (nothing is saved)."""
    st.subheader("What-if scenario builder")
    st.markdown('<div class="note">Move the shocks, or start from a named scenario. The portfolio is repriced '
                "instantly with the same pricers (no model, nothing saved to the audit log).</div>",
                unsafe_allow_html=True)
    systemic = {k: v for k, v in scen.items() if not v.get("issuer_only")}
    if "wi_rates_bp" not in st.session_state:
        st.session_state["wi_from"] = "geopolitical_severe" if "geopolitical_severe" in systemic else next(iter(
            systemic))
        _load_scenario(systemic)
    c0, c1 = st.columns([3, 2])
    c0.selectbox("Start from", list(systemic), key="wi_from", on_change=_load_scenario, args=(systemic,),
                 format_func=lambda k: systemic[k]["label"])
    compare = c1.toggle("Compare with the selected triggered run", value=run is not None, disabled=run is None)
    cols = st.columns(6)
    shocks = {}
    for col, (key, label, lo, hi, step, _unit, conv) in zip(cols, SLIDERS, strict=True):
        v = col.slider(label, lo, hi, step=step, key=f"wi_{key}")
        shocks[key] = v * conv
    res = guard(client.what_if, shocks)

    def tiles(r: dict, compact: bool = False) -> None:
        rows = [st.columns(2), st.columns(2)] if compact else [st.columns(4)]
        cols = [c for row in rows for c in row]
        kpi(cols[0], "Loss", f"{r['loss_pct']:.2f}%", money(r["loss"]), RAG_COLORS.get(r["rag"]),
            tip="Simulated loss as % of funded market value")
        kpi(cols[1], "RAG", r["rag"], f"appetite {r.get('risk_appetite_loss_pct', 2.0):.1f}%",
            RAG_COLORS.get(r["rag"]), tip="Green < 1% · amber 1% to appetite · red above appetite")
        kpi(cols[2], "Hedges", money(r["hedge_offset"]), "positive P&L", tip="Sum of positive position P&L")
        kpi(cols[3], "After", money(r["after_value"]), f"from {money(r['before_value'])}",
            tip="Funded value after the shock")

    if compare and run is not None:
        left, right = st.columns(2)
        with left:
            st.markdown(f"**Triggered:** {html.escape(run['scenario_label'])}")
            tiles(run, compact=True)
            st.plotly_chart(charts.waterfall(run), use_container_width=True, key="wi_wf_run")
        with right:
            st.markdown("**What-if:** custom shocks")
            tiles(res, compact=True)
            st.plotly_chart(charts.waterfall(res), use_container_width=True, key="wi_wf_custom")
    else:
        tiles(res)
        st.plotly_chart(charts.waterfall(res), use_container_width=True, key="wi_wf")
    a, b = st.columns(2)
    a.plotly_chart(charts.pnl_bar(res["by_asset_class"], "What-if P&L by asset class"), use_container_width=True,
                   key="wi_ac")
    b.plotly_chart(charts.pnl_bar(res["by_sector"], "What-if P&L by sector"), use_container_width=True, key="wi_sec")
    disclaimer()


def body() -> None:
    runs = guard(client.stress_runs, 100, as_of())
    if not runs["runs"]:
        st.info("No stress run yet. A high-impact signal triggers one automatically (try the **▶ Scenario demo** "
                "in the sidebar), or run a scenario manually below.")
    else:
        options = {f"{fmt_ts(r['created_at'])} · {r['scenario']}"
                   + (f" ({r['scope_issuer_id']})" if r.get("scope_issuer_id") else "")
                   + f" · {r['loss_pct']:.2f}% {r['rag']}": r["run_id"] for r in runs["runs"]}
        chosen = st.selectbox("Stress run (newest first)", list(options))
        run = guard(client.stress_run, options[chosen])
        trig = guard(client.signal, run["trigger_signal_id"]) if run.get("trigger_signal_id") else None
        signals = {trig["signal_id"]: trig} if trig else {}
        if run["run_id"].startswith("real-"):
            st.caption("This run was triggered by a CACHED_REAL signal while the REAL history was built: simulated "
                       "with the illustrative model on the synthetic portfolio, at the time the headline was captured.")
        trigger_banner(run, signals)

        c1, c2, c3, c4, c5 = st.columns(5)
        kpi(c1, "Before (funded)", money(run["before_value"]))
        kpi(c2, "After", money(run["after_value"]))
        kpi(c3, "Simulated loss", f"{run['loss_pct']:.2f}%", money(run["loss"]), RAG_COLORS.get(run["rag"]))
        kpi(c4, "Hedge offset", money(run["hedge_offset"]), "sum of positive P&L")
        kpi(c5, "Concentration (HHI)", f"{run['hhi_sector']:.3f}", f"sector · issuer {run['hhi_issuer']:.3f}")

        st.plotly_chart(charts.waterfall(run), use_container_width=True)
        left, right = st.columns(2)
        with left:
            st.plotly_chart(charts.top_positions(run), use_container_width=True)
        with right:
            st.plotly_chart(charts.heatmap(run), use_container_width=True)

        t1, t2, t3, t4 = st.tabs(["By issuer", "By sector", "By country", "Shocks applied"])
        t1.dataframe(pd.DataFrame(run["by_issuer"].items(), columns=["issuer_id", "P&L (USD)"]), hide_index=True,
                     use_container_width=True)
        t2.dataframe(pd.DataFrame(run["by_sector"].items(), columns=["sector", "P&L (USD)"]), hide_index=True,
                     use_container_width=True)
        t3.dataframe(pd.DataFrame(run["by_country"].items(), columns=["country", "P&L (USD)"]), hide_index=True,
                     use_container_width=True)
        t4.json({"scope_issuer_id": run.get("scope_issuer_id"), **run["shocks"]})

    st.divider()
    scen = guard(client.scenarios)
    what_if_panel(run if runs["runs"] else None, scen)

    st.divider()
    st.subheader("Run a scenario manually")
    port = guard(client.portfolio)
    issuers = sorted({(r["issuer_id"], r["issuer_name"]) for r in port["positions"] if r["issuer_id"]},
                     key=lambda x: x[1])
    c1, c2, c3 = st.columns([2, 2, 1])
    name = c1.selectbox("Scenario", list(scen), format_func=lambda k: f"{scen[k]['label']} ({k})")
    issuer = None
    if scen[name].get("issuer_only"):
        issuer = c2.selectbox("Issuer (held)", issuers, format_func=lambda x: f"{x[1]} ({x[0]})")[0]
    c2.caption(scen[name]["rationale"])
    if c3.button("Run stress test", type="primary", use_container_width=True):
        res = guard(client.run_stress, {"scenario": name, "issuer_id": issuer})
        st.success(f"{res['scenario_label']}: simulated loss {res['loss_pct']:.2f}% ({res['rag']}). "
                   "Select it in the run list above.")
        st.rerun()

    st.subheader("Audit log")
    if runs["runs"]:
        st.dataframe(pd.DataFrame(runs["runs"])[["created_at", "scenario", "scope_issuer_id", "trigger_signal_id",
                                                 "loss", "loss_pct", "rag", "rule"]],
                     hide_index=True, use_container_width=True)
    if runs["suppressed"]:
        st.caption("Suppressed triggers (cooldown)")
        st.dataframe(pd.DataFrame(runs["suppressed"])[["scenario", "scope_issuer_id", "signal_id",
                                                       "suppressed_reason"]], hide_index=True, use_container_width=True)


run_body(body)
