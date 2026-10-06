"""Section 7: Portfolio overview — composition by asset class, sector and rating; data source shown."""

from __future__ import annotations

import streamlit as st
from components import charts
from components.ui import badge, guard, kpi, money, setup

client = setup("Portfolio Overview", "💼")

p = guard(client.portfolio)
label_color = "#94a3b8" if p["provenance"] == "SYNTHETIC" else "#38bdf8"
st.markdown(badge(p["source"], label_color) + " every position below is generated for the demo — not real holdings"
            if p["provenance"] == "SYNTHETIC" else badge(p["source"], label_color), unsafe_allow_html=True)
st.write("")
c1, c2, c3, c4 = st.columns(4)
kpi(c1, "Positions", str(p["positions_count"]))
kpi(c2, "Funded market value", money(p["funded_mv"]), "loans + bonds + equity")
kpi(c3, "Gross exposure", money(p["gross_exposure"]), "MV + derivative notionals")
derivs = sum(v for k, v in p["by_asset_class_gross"].items() if k in ("IRS", "CDS", "FXForward"))
kpi(c4, "Derivative overlays", f"{derivs * 100:.0f}%", "IRS · CDS · FX forwards (notional)")
st.caption(p["note"])

left, right = st.columns(2)
with left:
    st.plotly_chart(charts.share_bar(p["by_asset_class_gross"], "Composition by asset class (gross exposure)"),
                    use_container_width=True)
    st.plotly_chart(charts.share_bar(p["by_rating_funded"], "Funded value by rating bucket (illustrative ratings)",
                                     order=["AAA-AA", "A", "BBB", "BB", "B-or-below"]), use_container_width=True)
with right:
    st.plotly_chart(charts.share_bar(p["by_sector_funded"], "Funded value by sector"), use_container_width=True)
    st.plotly_chart(charts.share_bar(p["by_country_funded"], "Funded value by country"), use_container_width=True)

st.subheader("Positions")
cols = ["asset_id", "asset_type", "issuer_name", "sector", "country", "rating_bucket", "currency", "side", "notional",
        "market_value", "mod_duration", "spread_duration", "pd_1y", "lgd", "dv01", "beta", "is_floating"]
st.dataframe([{k: r[k] for k in cols} for r in p["positions"]], hide_index=True, use_container_width=True, height=480,
             column_config={"notional": st.column_config.NumberColumn(format="$%.0f"),
                            "market_value": st.column_config.NumberColumn(format="$%.0f"),
                            "pd_1y": st.column_config.NumberColumn(format="%.4f")})
