"""Risk Signal Engine dashboard — Executive Risk Overview (section 1).

Run:  python -m streamlit run app/dashboard/Home.py   (the API must be running; see README)
"""

from __future__ import annotations

import html

import pandas as pd
import streamlit as st
from components.ui import (
    RAG_COLORS,
    RISK_COLORS,
    badge,
    disclaimer,
    fmt_ts,
    guard,
    kpi,
    provenance_badge,
    risk_badge,
    run_body,
    setup,
    signals_frame,
)

client = setup("Executive Risk Overview", "🛡️")


def body() -> None:
    health = guard(client.health)
    rows = guard(client.signals, limit=500)
    latest = guard(client.latest_stress)
    df = signals_frame(rows)

    today = pd.Timestamp.now(tz="UTC").normalize()
    n_today = int((df["time"] >= today).sum()) if len(df) else 0
    n_crit = int((df["risk_level"] == "Critical").sum()) if len(df) else 0
    c1, c2, c3, c4, c5 = st.columns(5)
    kpi(c1, "Signals today (event time, UTC)", f"{n_today}", f"{len(df)} loaded in total")
    kpi(c2, "Critical signals", f"{n_crit}", "impact ≥ 8.5", RISK_COLORS["Critical"] if n_crit else None)
    if latest:
        kpi(c3, "Latest portfolio RAG", latest["rag"], f"{latest['loss_pct']:.2f}% simulated loss · "
            f"{html.escape(latest['scenario_label'])}", RAG_COLORS.get(latest["rag"]))
    else:
        kpi(c3, "Latest portfolio RAG", "—", "no stress run yet")
    if len(df):
        worst = df.sort_values(["impact_score", "seq"], ascending=False).iloc[0]
        kpi(c4, "Worst event", f"{worst['impact_score']:.1f}",
            f"{html.escape(worst['entity'])} · {worst['event_type']}", RISK_COLORS.get(worst["risk_level"]))
    else:
        kpi(c4, "Worst event", "—", "no signals yet")
    kpi(c5, "Mode", health["mode"], "LIVE / REPLAY / SCENARIO — same NLP pipeline")

    st.write("")
    if latest:
        st.markdown(
            f'<div class="alert">🚨 <b>Stress test triggered</b> — {html.escape(latest["scenario_label"])} · '
            f'{badge(latest["rag"], RAG_COLORS.get(latest["rag"], "#52514e"))} '
            f'simulated loss <b>{latest["loss_pct"]:.2f}%</b> of funded value<br>'
            f'<span style="color:#52514e">Rule: {html.escape(latest["rule"])}</span></div>',
            unsafe_allow_html=True)
        disclaimer()

    left, right = st.columns([3, 2])
    with left:
        st.subheader("Highest-impact signals")
        if not len(df):
            st.info("No signals yet. Use the sidebar: **▶ Demo story** (SYNTHETIC scenario), switch to **REPLAY** "
                    "(cached real data) or **LIVE**.")
        top = df.sort_values(["impact_score", "seq"], ascending=False).head(6) if len(df) else df
        for _, r in top.iterrows():
            st.markdown(
                f"{risk_badge(r['risk_level'])}{provenance_badge(r.to_dict())} <b>{r['impact_score']:.1f}</b> · "
                f"{html.escape(r['entity'])} · <i>{r['event_type']}</i> · {fmt_ts(r['timestamp'])}<br>"
                f"<span style='color:#52514e'>{html.escape(r['text_excerpt'][:180])}</span>",
                unsafe_allow_html=True)
    with right:
        st.subheader("Data mix")
        if len(df):
            mix = df["provenance"].value_counts()
            st.dataframe(pd.DataFrame({"provenance": mix.index, "signals": mix.values}), hide_index=True,
                         use_container_width=True)
            src = df.groupby(["source_type", "source_label"]).size().reset_index(name="signals")
            st.dataframe(src, hide_index=True, use_container_width=True)
        model = health["model"]
        st.caption(f"Sentiment model: **{model.get('backend')}** · DB {'ok' if health['db_ok'] else 'DOWN'} · "
                   f"portfolio: {(health.get('portfolio') or {}).get('source', 'unavailable')}")


run_body(body)
