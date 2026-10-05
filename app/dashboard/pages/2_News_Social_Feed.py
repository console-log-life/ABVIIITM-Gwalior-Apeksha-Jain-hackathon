"""Section 2: News / social feed with provenance badges (CACHED_REAL rows carry their capture time)."""

from __future__ import annotations

import streamlit as st
from components.ui import guard, run_body, setup, signals_frame

client = setup("News & Social Feed", "📰")


def body() -> None:
    df = signals_frame(guard(client.signals, limit=500))
    if df.empty:
        st.info("No documents yet — start the demo story, REPLAY or LIVE mode from the sidebar.")
        return
    c1, c2, c3 = st.columns(3)
    all_types = sorted(df["source_type"].unique())
    types = c1.multiselect("Source type", all_types, default=all_types)
    provs = c2.multiselect("Provenance", sorted(df["provenance"].unique()), default=sorted(df["provenance"].unique()))
    sources = c3.multiselect("Source", sorted(df["source_label"].unique()), default=sorted(df["source_label"].unique()))
    view = df[df["source_type"].isin(types) & df["provenance"].isin(provs) & df["source_label"].isin(sources)]
    st.caption(f"{len(view)} of {len(df)} documents · newest first · every row shows its provenance "
               "(LIVE = fetched now, CACHED_REAL = real data captured earlier, SYNTHETIC = scripted demo / user text)")
    table = view[["provenance_label", "source_type", "source_label", "time", "entity", "text_excerpt", "url"]].rename(
        columns={"provenance_label": "provenance", "source_label": "source", "text_excerpt": "excerpt"})
    st.dataframe(
        table, hide_index=True, use_container_width=True, height=620,
        column_config={
            "time": st.column_config.DatetimeColumn("event time (UTC)", format="YYYY-MM-DD HH:mm"),
            "url": st.column_config.LinkColumn("link", display_text="open"),
            "excerpt": st.column_config.TextColumn("excerpt", width="large"),
            "provenance": st.column_config.TextColumn("provenance", width="medium"),
        })


run_body(body)
