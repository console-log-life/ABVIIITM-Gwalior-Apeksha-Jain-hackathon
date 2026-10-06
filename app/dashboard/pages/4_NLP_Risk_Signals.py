"""Sections 3–6: NLP risk signals table, sentiment trend, event distribution, impact score distribution."""

from __future__ import annotations

import streamlit as st
from components import charts
from components.ui import RISK_ORDER, as_of, guard, run_body, setup, signals_frame, style_risk

client = setup("NLP Risk Signals", "🧠")


def body() -> None:
    df = signals_frame(guard(client.signals, limit=500, as_of=as_of()))
    if df.empty:
        st.info("No signals yet — start the demo story, REPLAY or LIVE mode from the sidebar.")
        return
    c1, c2, c3 = st.columns([3, 2, 2])
    levels = c1.pills("Risk level", RISK_ORDER, selection_mode="multi", default=RISK_ORDER) or RISK_ORDER
    event = c2.selectbox("Event type", ["All"] + sorted(df["event_type"].unique()))
    min_imp = c3.slider("Minimum impact", 1.0, 10.0, 1.0, 0.5)
    view = df[df["risk_level"].isin(levels) & ((df["event_type"] == event) if event != "All" else True)
              & (df["impact_score"] >= min_imp)]

    st.subheader("Risk signals")
    cols = ["time", "risk_level", "impact_score", "entity", "event_type", "secondary_event_type", "sentiment_score",
            "sentiment_label", "corroborating_sources", "provenance_label", "source_label", "text_excerpt"]
    table = view[cols].rename(columns={"provenance_label": "provenance", "source_label": "source",
                                       "secondary_event_type": "secondary", "corroborating_sources": "sources",
                                       "text_excerpt": "excerpt"})
    st.dataframe(style_risk(table), hide_index=True, use_container_width=True, height=420,
                 column_config={"time": st.column_config.DatetimeColumn("event time (UTC)", format="MM-DD HH:mm"),
                                "impact_score": st.column_config.NumberColumn("impact", format="%.1f"),
                                "sentiment_score": st.column_config.NumberColumn("sentiment", format="%+.2f")})
    st.caption("Click a column header to sort. Colours: Low green · Medium amber · High orange · Critical red "
               "(the level is always written in the cell).")

    left, right = st.columns(2)
    with left:
        st.plotly_chart(charts.event_distribution(view), use_container_width=True)
    with right:
        st.plotly_chart(charts.impact_distribution(view), use_container_width=True)

    if len(view) > 3:
        st.plotly_chart(charts.sentiment_band(view), use_container_width=True)
    tick = view.dropna(subset=["ticker"])
    if len(tick):
        top = tick["ticker"].value_counts().index.tolist()
        chosen = st.multiselect("Tickers for the sentiment trend (max 8)", top, default=top[:4], max_selections=8)
        if chosen:
            st.plotly_chart(charts.sentiment_trend(tick, chosen), use_container_width=True)
    else:
        st.caption("Sentiment trend: no ticker-resolved signals in the current filter.")

    st.subheader("Top-10 signals by impact")
    top10 = view.sort_values(["impact_score", "seq"], ascending=False).head(10)
    st.dataframe(style_risk(top10[["impact_score", "risk_level", "entity", "event_type", "reason",
                                   "business_implication"]]), hide_index=True, use_container_width=True)


run_body(body)
