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


def body() -> None:
    runs = guard(client.stress_runs, 100, as_of())
    if not runs["runs"]:
        st.info("No stress run yet. A high-impact signal triggers one automatically (try **▶ Demo story** in the "
                "sidebar), or run a scenario manually below.")
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
    st.subheader("Run a scenario manually")
    scen = guard(client.scenarios)
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
