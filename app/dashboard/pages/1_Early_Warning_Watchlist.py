"""Early Warning Watchlist (credit-risk view): one ranked row per HELD issuer, with a rules-based watch status,
exposure, rating bucket, an impact sparkline and the top-3 signals with their reasons (GET /watchlist)."""

from __future__ import annotations

import html
from datetime import datetime

import streamlit as st
from components.ui import MUTED, fmt_ts, guard, kpi, money, provenance_badge, risk_badge, run_body, setup

client = setup("Early Warning Watchlist", "🚩")

STATUS_COLORS = {"WATCH-NEGATIVE": "#d03b3b", "MONITOR": "#fab219", "STABLE": "#0ca30c"}
TABLE_CSS = """
<style>
  table.wl { width:100%; border-collapse:collapse; font-size:0.95rem; }
  table.wl th { text-align:left; color:#52514e; font-weight:600; border-bottom:2px solid #e3e2de; padding:6px 8px; }
  table.wl td { border-bottom:1px solid #eceae4; padding:7px 8px; vertical-align:middle; }
  table.wl td.num { text-align:right; font-variant-numeric:tabular-nums; }
  table.wl a { color:#2a78d6; font-weight:600; text-decoration:none; white-space:nowrap; }
</style>
"""


def pill(status: str) -> str:
    color = STATUS_COLORS.get(status, MUTED)
    text_color = "#0b0b0b" if status == "MONITOR" else "#ffffff"
    return (f'<span class="badge" style="background:{color};color:{text_color}">'
            f'{"⚑ " if status == "WATCH-NEGATIVE" else ""}{html.escape(status)}</span>')


def sparkline(series: list[dict], color: str, w: int = 130, h: int = 30) -> str:
    """Inline SVG: impact (1-10) over time; dots are signals."""
    if not series:
        return f'<span style="color:{MUTED}">no signals</span>'
    ts = [datetime.fromisoformat(p["timestamp"].replace("Z", "+00:00")).timestamp() for p in series]
    t0, t1 = min(ts), max(ts)
    pad = 4

    def xy(t: float, v: float) -> tuple[float, float]:
        x = pad + (w - 2 * pad) * ((t - t0) / (t1 - t0) if t1 > t0 else 0.5)
        y = h - pad - (h - 2 * pad) * (v - 1) / 9
        return round(x, 1), round(y, 1)

    pts = [xy(t, p["impact_score"]) for t, p in zip(ts, series, strict=True)]
    y7 = xy(t0, 7)[1]
    line = " ".join(f"{x},{y}" for x, y in pts)
    dots = "".join(f'<circle cx="{x}" cy="{y}" r="2.6" fill="{color}"/>' for x, y in pts)
    title = " · ".join(f"{p['impact_score']:.1f}" for p in series)
    return (f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" aria-label="impact over time: {title}">'
            f'<title>impact over time: {title}</title>'
            f'<line x1="{pad}" x2="{w - pad}" y1="{y7}" y2="{y7}" stroke="#d6d4ce" stroke-dasharray="3 3"/>'
            f'<polyline points="{line}" fill="none" stroke="{color}" stroke-width="2"/>{dots}</svg>')


def explain_link(signal_id: str, label: str = "Explain →") -> str:
    return f'<a href="Explainability?signal_id={html.escape(signal_id)}" target="_self">{html.escape(label)}</a>'


def md_money(x: float) -> str:
    return money(x).replace("$", "\$")  # Streamlit markdown would read "$...$" as LaTeX


def body() -> None:
    hours = st.session_state.get("wl_hours", 24)
    w = guard(client.watchlist, hours)
    counts = w["counts"]
    c1, c2, c3, c4 = st.columns(4)
    kpi(c1, "WATCH-NEGATIVE", f"{counts['WATCH-NEGATIVE']}", "held issuers needing attention",
        STATUS_COLORS["WATCH-NEGATIVE"] if counts["WATCH-NEGATIVE"] else None)
    kpi(c2, "MONITOR", f"{counts['MONITOR']}", "held issuers with negative news")
    kpi(c3, "STABLE", f"{counts['STABLE']}", "no negative signal of note")
    kpi(c4, "Signals in window", f"{w['signals_in_window']}", f"on held issuers · last {w['window_hours']} h "
        "(event time)")

    rows = w["issuers"]
    show_all = st.session_state.get("wl_all", False)
    shown = rows if show_all else [r for r in rows if r["signal_count"] or r["status"] != "STABLE"]
    st.write("")
    if not shown:
        st.info(f"No signals on held issuers in the last {w['window_hours']} h. Start the demo story from the sidebar "
                "(after step 2, Tata Motors moves to WATCH-NEGATIVE), or tick **Show all held issuers**.")
    else:
        head = ("<tr><th>#</th><th>Status</th><th>Issuer</th><th>Rating</th><th class='num'>Exposure</th>"
                "<th class='num'>% book</th><th class='num'>Signals (neg.)</th><th class='num'>Worst impact</th>"
                "<th class='num'>Mean sent.</th><th>Events · sources</th><th>Impact over time</th><th></th></tr>")
        body_rows = []
        for r in shown:
            name = html.escape(r["issuer_name"]) + (f" <span style='color:{MUTED}'>({html.escape(r['ticker'])})"
                                                     "</span>" if r.get("ticker") else "")
            events = ", ".join(f"{html.escape(k)} ×{v}" for k, v in r["event_types"].items()) or "—"
            srcs = ", ".join(html.escape(s) for s in r["sources"])
            link = explain_link(r["top_signals"][0]["signal_id"]) if r["top_signals"] else ""
            worst = "—" if r["worst_impact"] is None else f"{r['worst_impact']:.1f}"
            mean = "—" if r["mean_sentiment"] is None else f"{r['mean_sentiment']:+.2f}"
            body_rows.append(
                f"<tr><td>{r['rank']}</td><td>{pill(r['status'])}</td><td><b>{name}</b><br>"
                f"<span style='color:{MUTED};font-size:0.85rem'>{html.escape(r['status_reason'])}</span></td>"
                f"<td>{html.escape(r['rating_bucket'])}</td><td class='num'>{money(r['exposure_mv'])}</td>"
                f"<td class='num'>{r['exposure_pct']:.2f}%</td>"
                f"<td class='num'>{r['signal_count']} ({r['negative_count']})</td>"
                f"<td class='num'>{worst}</td><td class='num'>{mean}</td>"
                f"<td>{events}<br><span style='color:{MUTED};font-size:0.85rem'>{srcs}</span></td>"
                f"<td>{sparkline(r['impact_series'], STATUS_COLORS[r['status']])}</td><td>{link}</td></tr>")
        st.markdown(TABLE_CSS + f"<table class='wl'>{head}{''.join(body_rows)}</table>", unsafe_allow_html=True)

    c1, c2 = st.columns([1, 3])
    c1.selectbox("Window (hours, by event time)", [6, 24, 72, 168], index=[6, 24, 72, 168].index(hours)
                 if hours in (6, 24, 72, 168) else 1, key="wl_hours")
    c2.checkbox("Show all held issuers (including STABLE issuers without signals)", key="wl_all")

    flagged = [r for r in shown if r["top_signals"]]
    if flagged:
        st.subheader("Top signals per issuer")
        for r in flagged:
            with st.expander(f"{r['rank']}. {r['issuer_name']} · {r['status']} · {r['signal_count']} signal(s)",
                             expanded=r["status"] == "WATCH-NEGATIVE"):
                st.markdown(f"{pill(r['status'])} {html.escape(r['status_reason'])} · exposure "
                            f"**{md_money(r['exposure_mv'])}** ({r['exposure_pct']:.2f}% of funded book) · rating "
                            f"bucket **{html.escape(r['rating_bucket'])}**"
                            + (f" · CDS protection bought {md_money(r['cds_protection_notional'])}"
                               if r["cds_protection_notional"] else ""), unsafe_allow_html=True)
                for t in r["top_signals"]:
                    st.markdown(
                        f"{risk_badge(t['risk_level'])}{provenance_badge(t)} <b>{t['impact_score']:.1f}</b> · "
                        f"<i>{html.escape(t['event_type'])}</i> · sentiment {t['sentiment_score']:+.2f} · "
                        f"{html.escape(t['source'])} · {fmt_ts(t['timestamp'])} · {explain_link(t['signal_id'])}<br>"
                        f"<span style='color:{MUTED}'>{html.escape(t['reason'])}</span>", unsafe_allow_html=True)

    rules = w["rules"]
    st.caption(f"**Rules** (config, see docs/methodology.md): **WATCH-NEGATIVE**: "
               f"{html.escape(rules['WATCH-NEGATIVE'])}; **MONITOR**: {html.escape(rules['MONITOR'])}; "
               f"**STABLE**: otherwise. Ranked by status, then the strongest negative signal, then exposure. "
               f"Portfolio: {html.escape(w['portfolio_source'])}. {html.escape(w['note'])}", unsafe_allow_html=True)


run_body(body)
