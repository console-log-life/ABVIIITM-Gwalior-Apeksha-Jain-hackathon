"""Early Warning Watchlist (credit-risk view): one ranked row per HELD issuer, with a rules-based watch status,
exposure, rating bucket, an impact sparkline and the top-3 signals with their reasons (GET /watchlist)."""

from __future__ import annotations

import html
from datetime import datetime

import streamlit as st
from components.ui import (
    MUTED,
    as_of,
    credit_brief_panel,
    fmt_ts,
    guard,
    kpi,
    money,
    provenance_badge,
    risk_badge,
    run_body,
    setup,
)

client = setup("Early Warning Watchlist", "🚩")

STATUS_COLORS = {"WATCH-NEGATIVE": "#ef4444", "MONITOR": "#f5b841", "STABLE": "#22c55e"}


def pill(status: str) -> str:
    color = STATUS_COLORS.get(status, MUTED)
    text_color = "#0b1220"
    return (f'<span class="badge" style="background:{color};color:{text_color}">'
            f'{"⚑ " if status == "WATCH-NEGATIVE" else ""}{html.escape(status)}</span>')


def rolling_max(ts: list[float], vals: list[float], window_s: float = 6 * 3600) -> list[float]:
    """For each point, the highest impact seen in the preceding 6 h (inclusive)."""
    return [max(v for t2, v in zip(ts, vals, strict=True) if t - window_s <= t2 <= t) for t in ts]


def sparkline(series: list[dict], color: str, t_end: float | None = None, hours: int = 24, w: int = 150,
              h: int = 34) -> str:
    """Inline SVG over the whole window: one dot per signal (impact 1-10) and a 6 h rolling-max step line.
    The dashed line marks impact 7 (WATCH threshold)."""
    if not series:
        return f'<span style="color:{MUTED}">no signals</span>'
    ts = [datetime.fromisoformat(p["timestamp"].replace("Z", "+00:00")).timestamp() for p in series]
    vals = [p["impact_score"] for p in series]
    t1 = t_end or max(ts)
    t0 = t1 - hours * 3600
    pad = 4

    def xy(t: float, v: float) -> tuple[float, float]:
        x = pad + (w - 2 * pad) * min(max((t - t0) / (t1 - t0), 0.0), 1.0)
        y = h - pad - (h - 2 * pad) * (v - 1) / 9
        return round(x, 1), round(y, 1)

    rm = rolling_max(ts, vals)
    step = []
    for i, (t, v) in enumerate(zip(ts, rm, strict=True)):
        x, y = xy(t, v)
        if i:
            step.append(f"{x},{step[-1].split(',')[1]}")
        step.append(f"{x},{y}")
    xe, _ = xy(t1, rm[-1])
    step.append(f"{xe},{step[-1].split(',')[1]}")
    y7 = xy(t0, 7)[1]
    dots = "".join(f'<circle cx="{x}" cy="{y}" r="2.4" fill="{color}" fill-opacity="0.75"/>'
                   for x, y in (xy(t, v) for t, v in zip(ts, vals, strict=True)))
    label = f"{len(vals)} signals, max impact {max(vals):.1f}"
    return (f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" aria-label="{label}">'
            f'<title>{label}; line = 6 h rolling max</title>'
            f'<line x1="{pad}" x2="{w - pad}" y1="{y7}" y2="{y7}" stroke="#2b3b5c" stroke-dasharray="3 3"/>'
            f'<polyline points="{" ".join(step)}" fill="none" stroke="{color}" stroke-width="1.6"/>{dots}</svg>')


def explain_link(signal_id: str, label: str = "Explain →") -> str:
    return f'<a href="Explainability?signal_id={html.escape(signal_id)}" target="_self">{html.escape(label)}</a>'


def md_money(x: float) -> str:
    return money(x).replace("$", "\$")  # Streamlit markdown would read "$...$" as LaTeX


def body() -> None:
    hours = st.session_state.get("wl_hours", 24)
    w = guard(client.watchlist, hours, as_of())
    t_end = datetime.fromisoformat(w["as_of"]).timestamp()
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
                "<th class='num'>% book</th>"
                "<th class='num' title='Decay-weighted exposure of issuers linked to this one "
                "(curated links)'>Propagated</th><th class='num'>Signals (neg.)</th><th class='num'>Worst impact</th>"
                "<th class='num'>Mean sent.</th><th>Events · sources</th><th>Impact over time</th><th></th></tr>")
        body_rows = []
        for r in shown:
            name = html.escape(r["issuer_name"]) + (f" <span style='color:{MUTED}'>({html.escape(r['ticker'])})"
                                                     "</span>" if r.get("ticker") else "")
            events = ", ".join(f"{html.escape(k)} ×{v}" for k, v in r["event_types"].items()) or "—"
            srcs = ", ".join(html.escape(s) for s in r["sources"])
            link = explain_link(r["top_signals"][0]["signal_id"]) if r["top_signals"] else ""
            worst = "—" if r["worst_impact"] is None else f"{r['worst_impact']:.1f}"
            prop = (f"<a href='Risk_Propagation?issuer_id={html.escape(r['issuer_id'])}' target='_self' "
                    f"title='open the exposure graph'>{money(r['propagated_exposure'])}</a>"
                    if r.get("propagated_exposure") else "—")
            mean = "—" if r["mean_sentiment"] is None else f"{r['mean_sentiment']:+.2f}"
            body_rows.append(
                f"<tr><td>{r['rank']}</td><td>{pill(r['status'])}</td><td><b>{name}</b><br>"
                f"<span style='color:{MUTED};font-size:0.85rem'>{'⇄ ' if r.get('via_propagation') else ''}"
                f"{html.escape(r['status_reason'])}</span></td>"
                f"<td>{html.escape(r['rating_bucket'])}</td><td class='num'>{money(r['exposure_mv'])}</td>"
                f"<td class='num'>{r['exposure_pct']:.2f}%</td>"
                f"<td class='num'>{prop}</td>"
                f"<td class='num'>{r['signal_count']} ({r['negative_count']})</td>"
                f"<td class='num'>{worst}</td><td class='num'>{mean}</td>"
                f"<td>{events}<br><span style='color:{MUTED};font-size:0.85rem'>{srcs}</span></td>"
                f"<td>{sparkline(r['impact_series'], STATUS_COLORS[r['status']], t_end, w['window_hours'])}</td>"
                f"<td>{link}</td></tr>")
        st.markdown(f"<table class='wl'>{head}{''.join(body_rows)}</table>", unsafe_allow_html=True)

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
                credit_brief_panel(client, r["issuer_id"], "wl")

    rules = w["rules"]
    st.caption(f"**Rules** (config, see docs/methodology.md): **WATCH-NEGATIVE**: "
               f"{html.escape(rules['WATCH-NEGATIVE'])}; **MONITOR**: {html.escape(rules['MONITOR'])}; "
               f"**STABLE**: otherwise. Ranked by status, then the strongest negative signal, then exposure. "
               f"Portfolio: {html.escape(w['portfolio_source'])}. {html.escape(w['note'])}", unsafe_allow_html=True)


run_body(body)
