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
    as_of,
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


def trend(cur: float, prev: float, unit: str = "", good_when_down: bool = True) -> str:
    """Arrow + change vs the previous window; for risk counts, up is shown in red."""
    d = cur - prev
    if abs(d) < 1e-9:
        return f"→ flat vs previous 24 h{unit}"
    up_bad = good_when_down
    color = (RISK_COLORS["Critical"] if (d > 0) == up_bad else RISK_COLORS["Low"])
    arrow = "▲" if d > 0 else "▼"
    num = f"{d:+.1f}" if isinstance(d, float) and not float(d).is_integer() else f"{int(d):+d}"
    return f'<span style="color:{color}">{arrow} {num}{unit}</span> vs previous 24 h'


def body() -> None:
    t = as_of()
    health = guard(client.health)
    rows = guard(client.signals, limit=500, as_of=t)
    latest = guard(client.latest_stress, t)
    ov = guard(client.overview, t, 24)
    cur, prev = ov["current"], ov["previous"]
    df = signals_frame(rows)

    st.caption(f"Window: the 24 h of event time ending {'now' if t is None else fmt_ts(t)} · trend arrows compare "
               "with the previous 24 h · CACHED_REAL history + any LIVE / SYNTHETIC demo data, each row badged")
    c1, c2, c3, c4, c5 = st.columns(5)
    kpi(c1, "Signals (24 h)", f"{cur['signals']}", trend(cur["signals"], prev["signals"], good_when_down=False))
    kpi(c2, "Critical", f"{cur['critical']}", trend(cur["critical"], prev["critical"]),
        RISK_COLORS["Critical"] if cur["critical"] else None)
    kpi(c3, "Issuers on watch", f"{cur['issuers_on_watch']}", trend(cur["issuers_on_watch"], prev["issuers_on_watch"]))
    kpi(c4, "Sources active", f"{cur['sources_active']}", trend(cur["sources_active"], prev["sources_active"],
                                                                good_when_down=False))
    kpi(c5, "Social share", f"{cur['social_pct']:.0f}%", trend(cur["social_pct"], prev["social_pct"], " pts",
                                                                 good_when_down=False))
    st.write("")
    c1, c2, c3 = st.columns([2, 2, 1])
    if latest:
        kpi(c1, "Latest portfolio RAG", latest["rag"], f"{latest['loss_pct']:.2f}% simulated loss · "
            f"{html.escape(latest['scenario_label'])} · {fmt_ts(latest.get('created_at'))}",
            RAG_COLORS.get(latest["rag"]))
    else:
        kpi(c1, "Latest portfolio RAG", "—", "no stress run yet")
    if len(df):
        worst = df.sort_values(["impact_score", "seq"], ascending=False).iloc[0]
        kpi(c2, "Worst event", f"{worst['impact_score']:.1f}",
            f"{html.escape(worst['entity'])} · {worst['event_type']}", RISK_COLORS.get(worst["risk_level"]))
    else:
        kpi(c2, "Worst event", "—", "no signals yet")
    kpi(c3, "Mode", health["mode"], "same NLP pipeline")

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
