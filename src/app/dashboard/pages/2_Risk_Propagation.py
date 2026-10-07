"""Risk propagation (contagion) view: direct vs propagated exposure of an issuer over CURATED links (universe.yaml),
and an interactive exposure graph (issuers, sectors, positions). GET /propagation."""

from __future__ import annotations

import html

import pandas as pd
import streamlit as st
from components import charts
from components.ui import RISK_COLORS, as_of, guard, kpi, money, run_body, setup

client = setup("Risk Propagation", "🕸️")
STATUS_COLORS = {"WATCH-NEGATIVE": RISK_COLORS["Critical"], "MONITOR": RISK_COLORS["Medium"],
                 "STABLE": RISK_COLORS["Low"]}


def body() -> None:
    t = as_of()
    wl = guard(client.watchlist, None, t)
    issuers = wl["issuers"]  # ranked: WATCH-NEGATIVE first
    ids = [r["issuer_id"] for r in issuers]
    names = {r["issuer_id"]: r["issuer_name"] for r in issuers}
    wanted = st.query_params.get("issuer_id")
    default = wanted if wanted in ids else ids[0]
    c0, c1 = st.columns([3, 2])
    status_of = {r["issuer_id"]: r["status"] for r in issuers}
    iid = c0.selectbox("Issuer (held; ranked by watch status)", ids, index=ids.index(default),
                       format_func=lambda i: f"{names[i]} · {status_of[i]}")
    c1.markdown('<div class="note" style="margin-top:30px">Links are <b>curated</b> (universe.yaml), not inferred '
                "from data. Decay: supplier/parent 0.5, peer 0.3 (config).</div>", unsafe_allow_html=True)
    p = guard(client.propagation, iid, t)
    row = next(r for r in issuers if r["issuer_id"] == iid)

    k = st.columns(4)
    kpi(k[0], "Direct exposure", money(p["direct_exposure"]), f"{p['direct_pct']:.2f}% of funded book",
        tip="Funded market value held in this issuer (loans, bonds, equity)")
    kpi(k[1], "Propagated", money(p["propagated_exposure"]), f"{p['propagated_pct']:.2f}% of book",
        tip="Σ decay weight × exposure of linked issuers (second order)")
    kpi(k[2], "Total at risk", f"{p['total_pct']:.2f}%", "direct + propagated, % of book",
        tip="Upper-bound attention measure, not a loss estimate")
    kpi(k[3], "Watch status", row["status"], html.escape(row["status_reason"])[:60],
        STATUS_COLORS.get(row["status"]), tip=row["status_reason"])

    left, right = st.columns([3, 2])
    with left:
        event = st.plotly_chart(charts.network(p["graph"], iid), use_container_width=True, key=f"net_{iid}",
                                on_select="rerun", selection_mode="points")
    picked = None
    try:
        pts = (event or {}).get("selection", {}).get("points", [])
        picked = next((pt.get("customdata") for pt in pts if pt.get("customdata")), None)
    except AttributeError:
        picked = None
    nodes = {n["id"]: n for n in p["graph"]["nodes"] if n["kind"] == "issuer"}
    with right:
        st.subheader("Second-order contributions")
        if p["contributions"]:
            contrib = {f"{names.get(c['issuer_id'], c['issuer_id'])} ({c['relation']} ×{c['weight']:g})":
                       c["weighted"] for c in p["contributions"]}
            st.plotly_chart(charts.exposure_bar(contrib, "Decay-weighted exposure of linked issuers"),
                            use_container_width=True)
        else:
            st.info("No curated links for this issuer: its propagated exposure is zero.")
        choice = st.selectbox("Show positions of", list(nodes), index=list(nodes).index(picked) if picked in nodes
                              else 0, format_func=lambda i: nodes[i]["name"],
                              help="Or click an issuer node in the graph.")
        n = nodes[choice]
        if n["positions"]:
            df = pd.DataFrame(n["positions"])
            st.dataframe(df, hide_index=True, use_container_width=True,
                         column_config={"market_value": st.column_config.NumberColumn("MV", format="$%.0f"),
                                        "notional": st.column_config.NumberColumn(format="$%.0f")})
        st.markdown(f'<div class="note">{html.escape(n["name"])} · {n["status"]} · exposure '
                    f'{money(n["exposure"])} ({n["exposure_pct"]:.2f}% of book) · hop {n["hop"]}</div>',
                    unsafe_allow_html=True)
    st.markdown(f'<div class="note">{html.escape(p["note"])} Statuses as of the time machine '
                f"({'latest' if t is None else t[:16]}).</div>", unsafe_allow_html=True)


run_body(body)
