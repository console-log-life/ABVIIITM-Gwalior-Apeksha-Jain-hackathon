"""Shared dashboard UI: page setup, sidebar (mode switch, demo control, source health), badges, colours."""

from __future__ import annotations

import html
from collections.abc import Callable
from datetime import datetime

import pandas as pd
import streamlit as st
from api_client import ApiClient, ApiError

from app.config import STRESS_DISCLAIMER, get_settings

# Status palette (reference dataviz palette) — always shown together with a text label, never colour alone.
RISK_COLORS = {"Low": "#0ca30c", "Medium": "#fab219", "High": "#ec835a", "Critical": "#d03b3b"}
RISK_ORDER = ["Low", "Medium", "High", "Critical"]
RAG_COLORS = {"GREEN": "#0ca30c", "AMBER": "#fab219", "RED": "#d03b3b"}
PROV_STYLE = {
    "LIVE": ("#2a78d6", "LIVE"),
    "CACHED_REAL": ("#4a3aa7", "CACHED_REAL"),
    "SYNTHETIC": ("#52514e", "SYNTHETIC"),
}
PROV_ICON = {"LIVE": "🔵 LIVE", "CACHED_REAL": "🟣 CACHED_REAL", "SYNTHETIC": "⚪ SYNTHETIC"}
TEXT, MUTED, SURFACE = "#0b0b0b", "#52514e", "#fcfcfb"

CSS = f"""
<style>
  html, body, [class*="css"] {{ font-size: 17px; }}
  .kpi {{ background:{SURFACE}; border:1px solid #e3e2de; border-radius:10px; padding:14px 18px; height:100%; }}
  .kpi .label {{ color:{MUTED}; font-size:0.95rem; margin-bottom:4px; }}
  .kpi .value {{ color:{TEXT}; font-size:2.1rem; font-weight:700; line-height:1.15; }}
  .kpi .sub {{ color:{MUTED}; font-size:0.9rem; margin-top:4px; }}
  .badge {{ display:inline-block; padding:2px 10px; border-radius:999px; font-size:0.85rem; font-weight:600;
           color:#fff; margin-right:6px; white-space:nowrap; }}
  .chip {{ display:inline-block; padding:2px 10px; border-radius:6px; background:#eceae4; color:{TEXT};
          margin:2px 4px 2px 0; font-size:0.9rem; }}
  .disclaimer {{ border-left:4px solid #d03b3b; background:#fbf1f0; padding:8px 12px; color:{TEXT};
                border-radius:4px; font-size:0.95rem; margin:6px 0 12px 0; }}
  .alert {{ border:2px solid #d03b3b; background:#fdf3f2; padding:12px 16px; border-radius:8px; margin-bottom:10px; }}
</style>
"""


def setup(title: str, icon: str = "📊") -> ApiClient:
    st.set_page_config(page_title=f"{title} · Risk Signal Engine", page_icon=icon, layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)
    client = ApiClient()
    sidebar(client)
    st.title(title)
    return client


def guard(fn: Callable, *args, **kwargs):
    """Call the API; on failure show a clear message (not a stack trace) and stop the page."""
    try:
        return fn(*args, **kwargs)
    except ApiError as exc:
        st.error(f"⚠️ {exc}")
        st.stop()


def badge(text: str, color: str) -> str:
    return f'<span class="badge" style="background:{color}">{html.escape(text)}</span>'


def risk_badge(level: str) -> str:
    return badge(level, RISK_COLORS.get(level, MUTED))


def provenance_badge(row: dict) -> str:
    color, label = PROV_STYLE.get(row.get("provenance", ""), (MUTED, row.get("provenance", "?")))
    if row.get("provenance") == "CACHED_REAL" and row.get("captured_at"):
        label = f"CACHED_REAL · captured {fmt_ts(row['captured_at'])}"
    return badge(label, color)


def provenance_text(row: dict) -> str:
    """Plain-text provenance for tables: CACHED_REAL always carries its capture timestamp."""
    p = row.get("provenance", "?")
    if p == "CACHED_REAL" and row.get("captured_at"):
        return f"{PROV_ICON[p]} · captured {fmt_ts(row['captured_at'])}"
    return PROV_ICON.get(p, p)


def fmt_ts(value) -> str:
    if not value:
        return "—"
    try:
        ts = pd.Timestamp(value)
        ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
        return ts.strftime("%Y-%m-%d %H:%M UTC")
    except (ValueError, TypeError):
        return str(value)


def money(x: float) -> str:
    sign = "-" if x < 0 else ""
    x = abs(x)
    return f"{sign}${x / 1e9:,.2f}bn" if x >= 1e9 else f"{sign}${x / 1e6:,.1f}m"


def kpi(col, label: str, value: str, sub: str = "", color: str | None = None) -> None:
    style = f' style="color:{color}"' if color else ""
    col.markdown(f'<div class="kpi"><div class="label">{html.escape(label)}</div>'
                 f'<div class="value"{style}>{value}</div><div class="sub">{sub}</div></div>',
                 unsafe_allow_html=True)


def disclaimer() -> None:
    st.markdown(f'<div class="disclaimer">⚠️ <b>{html.escape(STRESS_DISCLAIMER)}</b> '
                "Decision-support prototype, not investment advice.</div>", unsafe_allow_html=True)


def signals_frame(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["time"] = pd.to_datetime(df["timestamp"], utc=True, format="ISO8601")
    df["provenance_label"] = [provenance_text(r) for r in rows]
    df["entity"] = df.apply(lambda r: f"{r['company']} ({r['ticker']})" if r.get("ticker") else r["company"], axis=1)
    df["source_label"] = df.apply(
        lambda r: f"{r['source']} → {r['imitated_source']}" if r.get("imitated_source") else r["source"], axis=1)
    return df


def style_risk(df: pd.DataFrame, column: str = "risk_level"):
    def color(v):
        c = RISK_COLORS.get(v)
        return f"background-color:{c}; color:{'#0b0b0b' if v in ('Medium', 'High') else '#ffffff'}; font-weight:600" \
            if c else ""
    return df.style.map(color, subset=[column])


# ---------------------------------------------------------------- sidebar
def sidebar(client: ApiClient) -> None:
    sb = st.sidebar
    sb.markdown("### Risk Signal Engine")
    try:
        h = client.health()
    except ApiError as exc:
        sb.error(f"API offline\n\n{exc}")
        return
    mode = h.get("mode", "?")
    model = h.get("model", {})
    sb.markdown(badge(f"MODE: {mode}", "#2a78d6") + badge(model.get("backend", "?"),
                "#0ca30c" if model.get("backend") == "finbert" else "#ec835a"), unsafe_allow_html=True)
    if model.get("backend") != "finbert":
        sb.caption(f"Sentiment fallback active: {model.get('fallback_reason') or model.get('backend')}")

    with sb.expander("Mode & demo control", expanded=False):
        new_mode = st.radio("Mode", ["LIVE", "REPLAY", "SCENARIO"], index=["LIVE", "REPLAY", "SCENARIO"].index(mode)
                            if mode in ("LIVE", "REPLAY", "SCENARIO") else 2, horizontal=True,
                            help="LIVE polls real sources; REPLAY streams cached real captures; SCENARIO plays the "
                                 "SYNTHETIC demo story. All three use the same NLP pipeline.")
        if st.button("Apply mode", use_container_width=True):
            res = guard(client.set_mode, new_mode)
            st.success(f"Mode → {res.get('mode')}")
        c1, c2 = st.columns(2)
        if c1.button("▶ Demo story", use_container_width=True):
            guard(client.demo_start, "SCENARIO", get_settings().demo_step_seconds)
            st.success("Demo story started")
        if c2.button("⟲ Reset", use_container_width=True):
            res = guard(client.demo_reset)
            st.success(f"Cleared {res['signals_deleted']} signals, {res['stress_runs_deleted']} runs")
        demo = h.get("demo") or {}
        if demo.get("running"):
            st.info(f"{demo.get('mode')} playback running…")

    sb.toggle("Auto-refresh (5 s)", key="autorefresh", value=False)
    sb.markdown("**Source health**")
    rows = h.get("sources") or []
    if not rows:
        sb.caption("No live polling yet (LIVE mode not started this session).")
    for s in rows:
        icon = {"OK": "🟢", "EMPTY": "🟢", "DISABLED": "⚪", "BACKOFF": "🟠", "RATE_LIMITED": "🟡",
                "DEGRADED": "🟠", "DOWN": "🔴"}.get(s.get("status"), "⚪")
        sb.caption(f"{icon} **{s['source']}** — {s.get('status')}"
                   + (f" · {html.escape(str(s.get('last_error'))[:60])}" if s.get("last_error") else ""))
    sb.caption(f"DB {'ok' if h.get('db_ok') else 'DOWN'} · {h.get('signals_stored')} signals stored")


def run_body(body: Callable[[], None]) -> None:
    """Run the page body, re-running it every 5 s when auto-refresh is on (no animations)."""
    if st.session_state.get("autorefresh"):
        st.fragment(body, run_every=5)()
    else:
        body()


def now_utc() -> datetime:
    return pd.Timestamp.now(tz="UTC").to_pydatetime()
