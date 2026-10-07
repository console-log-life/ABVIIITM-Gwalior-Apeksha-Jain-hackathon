"""Risk Signal Engine dashboard — Executive Risk Overview (section 1).

Run:  python -m streamlit run src/app/dashboard/Home.py   (the API must be running; see README)
"""

from __future__ import annotations

import html

import streamlit as st
from components import charts
from components.ui import (
    RAG_COLORS,
    RISK_COLORS,
    as_of,
    delta,
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
    t = as_of()
    ov = guard(client.overview, t, 24)
    cur, prev = ov["current"], ov["previous"]
    latest = ov.get("latest_stress")
    window = signals_frame(guard(client.signals, limit=500, as_of=t, hours=24))
    trend72 = signals_frame(guard(client.signals, limit=500, as_of=t, hours=72))

    st.markdown(f'<div class="note">24 h window of event time ending <b>{"now" if t is None else fmt_ts(t)}</b> · '
                "arrows compare with the previous 24 h · REAL (CACHED_REAL) history plus any LIVE or SYNTHETIC demo "
                "data, every row badged</div>", unsafe_allow_html=True)
    c = st.columns(6)
    kpi(c[0], "Signals 24h", f"{cur['signals']}", delta(cur["signals"], prev["signals"], up_is_bad=False),
        tip="Risk signals with event time in the 24 h window")
    kpi(c[1], "Critical", f"{cur['critical']}", delta(cur["critical"], prev["critical"]),
        RISK_COLORS["Critical"] if cur["critical"] else None, tip="Signals with impact ≥ 8.5")
    kpi(c[2], "On watch", f"{cur['issuers_on_watch']}", delta(cur["issuers_on_watch"], prev["issuers_on_watch"]),
        RISK_COLORS["High"] if cur["watch_negative"] else None,
        tip=f"Held issuers WATCH-NEGATIVE or MONITOR (WATCH-NEGATIVE: {cur['watch_negative']})")
    kpi(c[3], "Sources", f"{cur['sources_active']}", delta(cur["sources_active"], prev["sources_active"],
                                                          up_is_bad=False), tip="Distinct sources in the window")
    kpi(c[4], "Social", f"{cur['social_pct']:.0f}%", delta(cur["social_pct"], prev["social_pct"], " pt",
                                                           up_is_bad=False), tip="Share of signals from social media")
    if latest:
        kpi(c[5], "Portfolio RAG", latest["rag"], f"{latest['loss_pct']:.2f}% · {fmt_ts(latest['created_at'], True)}",
            RAG_COLORS.get(latest["rag"]), tip=f"Latest simulated stress run: {latest['scenario_label']}")
    else:
        kpi(c[5], "Portfolio RAG", "—", "no stress run yet")

    if latest:
        cls = {"RED": "", "AMBER": " amber", "GREEN": " green"}.get(latest["rag"], "")
        st.markdown(
            f'<div class="alert{cls}" style="margin-top:12px">▲ <b>Latest stress test</b> · '
            f'{html.escape(latest["scenario_label"])} · simulated loss <b>{latest["loss_pct"]:.2f}%</b> of funded '
            f'value · {fmt_ts(latest["created_at"])}<br><span class="note">Rule: {html.escape(latest["rule"] or "")}'
            '</span></div>', unsafe_allow_html=True)
        disclaimer()

    left, right = st.columns([3, 2])
    with left:
        st.subheader("Highest impact · 24 h")
        if not len(window):
            st.info("No signals in this window. Move the time machine in the sidebar, or start the **Scenario demo**.")
        top = window.sort_values(["impact_score", "seq"], ascending=False).head(7) if len(window) else window
        for _, r in top.iterrows():
            st.markdown(
                f"{risk_badge(r['risk_level'])}{provenance_badge(r.to_dict())} <b class='mono'>"
                f"{r['impact_score']:.1f}</b> · {html.escape(r['entity'])} · <i>{r['event_type']}</i> · "
                f"<span class='note'>{fmt_ts(r['timestamp'], True)}</span><br>"
                f"<span class='note'>{html.escape(r['text_excerpt'][:170])}</span>", unsafe_allow_html=True)
    with right:
        if len(window):
            mix = window["provenance"].value_counts().to_dict()
            st.plotly_chart(charts.data_mix(mix, "Data mix · provenance"), use_container_width=True)
            src = window["source_label"].value_counts().to_dict()
            st.plotly_chart(charts.data_mix(src, "Data mix · source"), use_container_width=True)
    if len(trend72) > 3:
        st.plotly_chart(charts.sentiment_band(trend72), use_container_width=True)


run_body(body)
