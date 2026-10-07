"""Shared dashboard UI: dark risk-terminal theme (components/theme.css), sidebar (brand, mode, time machine, demo
control, source health), ticker tape, KPI tiles, badges and colours."""

from __future__ import annotations

import html
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path

import pandas as pd
import streamlit as st
from api_client import ApiClient, ApiError

from app.config import STRESS_DISCLAIMER, get_settings

# Risk colours are used ONLY for risk levels (always next to a text label, never colour alone).
RISK_COLORS = {"Low": "#22c55e", "Medium": "#f5b841", "High": "#f97316", "Critical": "#ef4444"}
RISK_ORDER = ["Low", "Medium", "High", "Critical"]
RAG_COLORS = {"GREEN": "#22c55e", "AMBER": "#f5b841", "RED": "#ef4444"}
PROV_STYLE = {"LIVE": ("#38bdf8", "LIVE"), "CACHED_REAL": ("#a78bfa", "CACHED_REAL"),
              "SYNTHETIC": ("#94a3b8", "SYNTHETIC")}
PROV_ICON = {"LIVE": "🔵 LIVE", "CACHED_REAL": "🟣 CACHED_REAL", "SYNTHETIC": "⚪ SYNTHETIC"}
TEXT, MUTED, SURFACE, BG, LINE, ACCENT = "#e6edf7", "#8b9bb8", "#111a2e", "#0b1220", "#22304d", "#22d3ee"
THEME_CSS = Path(__file__).with_name("theme.css")


@lru_cache(maxsize=1)
def _css() -> str:
    return f"<style>{THEME_CSS.read_text(encoding='utf-8')}</style>"


def setup(title: str, icon: str = "📊", tape: bool = True) -> ApiClient:
    st.set_page_config(page_title=f"{title} · Risk Signal Engine", page_icon=icon, layout="wide",
                       initial_sidebar_state="expanded")
    st.markdown(_css(), unsafe_allow_html=True)
    client = ApiClient()
    sidebar(client)
    if tape:
        ticker_tape(client)
    st.title(title)
    return client


def guard(fn: Callable, *args, **kwargs):
    """Call the API; on failure show a clear message (not a stack trace) and stop the page."""
    try:
        return fn(*args, **kwargs)
    except ApiError as exc:
        st.error(f"⚠️ {exc}")
        st.stop()


def badge(text: str, color: str, title: str | None = None) -> str:
    t = f' title="{html.escape(title)}"' if title else ""
    return f'<span class="badge" style="background:{color}"{t}>{html.escape(text)}</span>'


def risk_badge(level: str) -> str:
    return badge(level.upper(), RISK_COLORS.get(level, MUTED))


def provenance_badge(row: dict) -> str:
    p = row.get("provenance", "")
    color, label = PROV_STYLE.get(p, (MUTED, p or "?"))
    title = None
    if p == "CACHED_REAL" and row.get("captured_at"):
        label = f"CACHED_REAL · cap. {fmt_ts(row['captured_at'], short=True)}"
        title = f"Real data captured {fmt_ts(row['captured_at'])}"
    return badge(label, color, title)


def provenance_text(row: dict) -> str:
    """Plain-text provenance for tables: CACHED_REAL always carries its capture timestamp."""
    p = row.get("provenance", "?")
    if p == "CACHED_REAL" and row.get("captured_at"):
        return f"{PROV_ICON[p]} · captured {fmt_ts(row['captured_at'])}"
    return PROV_ICON.get(p, p)


def fmt_ts(value, short: bool = False) -> str:
    if not value:
        return "—"
    try:
        ts = pd.Timestamp(value)
        ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
        return ts.strftime("%b %d %H:%M") if short else ts.strftime("%Y-%m-%d %H:%M UTC")
    except (ValueError, TypeError):
        return str(value)


def money(x: float) -> str:
    sign = "-" if x < 0 else ""
    x = abs(x)
    return f"{sign}${x / 1e9:,.2f}bn" if x >= 1e9 else f"{sign}${x / 1e6:,.1f}m"


def kpi(col, label: str, value: str, sub: str = "", color: str | None = None, tip: str | None = None) -> None:
    """Compact tile: small-caps label, big mono number, one delta/detail line. Details go in the tooltip."""
    style = f' style="color:{color}"' if color else ""
    t = f' title="{html.escape(tip)}"' if tip else ""
    col.markdown(f'<div class="kpi"{t}><div class="label">{html.escape(label)}</div>'
                 f'<div class="value"{style}>{value}</div><div class="sub">{sub}</div></div>',
                 unsafe_allow_html=True)


def delta(cur: float, prev: float, unit: str = "", up_is_bad: bool = True, label: str = "vs prev. 24 h") -> str:
    """Trend line for a KPI tile: arrow + change vs the previous window (red when the move is adverse)."""
    d = cur - prev
    if abs(d) < 1e-9:
        return f'<span class="flat">■ flat</span> {label}'
    cls = ("up-bad" if up_is_bad else "up-good") if d > 0 else ("down-good" if up_is_bad else "down-bad")
    num = f"{d:+.1f}" if not float(d).is_integer() else f"{int(d):+d}"
    return f'<span class="{cls}">{"▲" if d > 0 else "▼"} {num}{unit}</span> {label}'


def disclaimer() -> None:
    st.markdown(f'<div class="disclaimer">⚠ <b>{html.escape(STRESS_DISCLAIMER)}</b> '
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
        return f"color:{c}; font-weight:600" if c else ""
    return df.style.map(color, subset=[column])


# ---------------------------------------------------------------- credit brief
def credit_brief_panel(client: ApiClient, issuer_id: str, key: str) -> None:
    """One-click issuer credit brief (template-based, no LLM): HTML preview + PDF download."""
    if not st.toggle("Credit brief", key=f"brief_{key}_{issuer_id}",
                     help="One-page, template-based brief: status and rule, exposure (direct + propagated), last "
                          "signals with reasons, stress impact on this issuer's positions, hedges."):
        return
    try:
        meta = client.credit_brief(issuer_id, as_of())
    except ApiError as exc:
        st.caption(f"No credit brief: {exc}")
        return
    st.html(guard(client.credit_brief_html, issuer_id, as_of()))
    st.download_button("⬇ Download PDF", data=guard(client.credit_brief_pdf, issuer_id, as_of()),
                       file_name=meta["file_name"], mime="application/pdf", key=f"pdf_{key}_{issuer_id}")


# ---------------------------------------------------------------- ticker tape
def ticker_tape(client: ApiClient, n: int = 10) -> None:
    """Latest signals (as of the time machine) scrolling across the top; pauses on hover; static when the user
    prefers reduced motion."""
    try:
        rows = client.signals(limit=n, as_of=as_of())
    except ApiError:
        return
    if not rows:
        return
    items = []
    for r in rows:
        c = RISK_COLORS.get(r["risk_level"], MUTED)
        ent = r["company"] if r["company"] not in ("UNRESOLVED",) else (r.get("ticker") or "—")
        items.append(f'<span class="tape-item"><span class="lvl" style="color:{c}">■ {r["impact_score"]:.1f}</span>'
                     f'<span class="ent">{html.escape(ent[:24])}</span>{html.escape(r["text_excerpt"][:90])}'
                     f' <span class="ent">· {r["provenance"]}</span></span>')
    st.markdown(f'<div class="tape" aria-label="latest signals"><div class="tape-track">{"".join(items)}</div></div>',
                unsafe_allow_html=True)


# ---------------------------------------------------------------- sidebar
HEALTH_CLASS = {"OK": "ok", "EMPTY": "ok", "BACKOFF": "warn", "RATE_LIMITED": "warn", "DEGRADED": "warn",
                "DOWN": "down", "DISABLED": "off"}


def sidebar(client: ApiClient) -> None:
    sb = st.sidebar
    sb.markdown('<div class="brand"><div class="name">RISK <b>SIGNAL</b> ENGINE</div>'
                '<div class="sub">news &amp; social → risk signals → portfolio stress</div></div>',
                unsafe_allow_html=True)
    try:
        h = client.health()
    except ApiError as exc:
        sb.error(f"API offline\n\n{exc}")
        return
    mode = h.get("mode", "?")
    model = h.get("model", {})
    ev = model.get("event") or {}
    sent = "FinBERT" + (" fine-tuned" if model.get("variant") == "fine-tuned" else "")
    if model.get("backend") != "finbert":
        sent = "lexicon fallback"
    sb.markdown(badge(f"MODE {mode}", ACCENT)
                + badge(sent, "#22c55e" if model.get("backend") == "finbert" else "#f97316",
                        model.get("fallback_reason") or model.get("model"))
                + badge("events hybrid" if ev.get("backend") == "hybrid" else "events rules", "#94a3b8",
                        ev.get("model") or "rule engine"), unsafe_allow_html=True)

    time_machine(client, sb)

    with sb.expander("Mode & demo control", expanded=False):
        new_mode = st.radio("Mode", ["LIVE", "REPLAY", "SCENARIO"], index=["LIVE", "REPLAY", "SCENARIO"].index(mode)
                            if mode in ("LIVE", "REPLAY", "SCENARIO") else 2, horizontal=True,
                            help="LIVE polls real sources; REPLAY streams cached real captures; SCENARIO plays the "
                                 "SYNTHETIC demo story. All three use the same NLP pipeline. The REAL history "
                                 "(CACHED_REAL) stays loaded in every mode.")
        if st.button("Apply mode", use_container_width=True):
            res = guard(client.set_mode, new_mode)
            st.success(f"Mode → {res.get('mode')}")
        c1, c2 = st.columns(2)
        if c1.button("▶ Scenario demo", use_container_width=True,
                     help="Plays the scripted SYNTHETIC story (Tata Motors downgrade → geopolitical shock)."):
            st.session_state["tm_follow"] = True
            guard(client.demo_start, "SCENARIO", get_settings().demo_step_seconds)
            st.success("SYNTHETIC scenario started")
        if c2.button("⟲ Reset", use_container_width=True, help="Clears demo/API signals and their stress runs; "
                                                               "the REAL history is kept."):
            res = guard(client.demo_reset)
            st.success(f"Cleared {res['signals_deleted']} signals, {res['stress_runs_deleted']} runs")
        demo = h.get("demo") or {}
        if demo.get("running"):
            st.info(f"{demo.get('mode')} playback running…")

    sb.toggle("Auto-refresh (5 s)", key="autorefresh", value=False)
    rows = h.get("sources") or []
    active = [s for s in rows if s.get("status") != "DISABLED"]
    off = [s for s in rows if s.get("status") == "DISABLED"]
    lines = "".join(
        f'<div class="health" title="{html.escape(str(s.get("last_error") or s.get("status")))}">'
        f'<span class="dot {HEALTH_CLASS.get(s.get("status"), "off")}"></span>{html.escape(s["source"])}'
        f'<span style="margin-left:auto">{html.escape(str(s.get("status")).lower())}</span></div>' for s in active)
    sb.markdown("**Sources**" + (lines or '<div class="note">no polling this session</div>'), unsafe_allow_html=True)
    if off:
        with sb.expander(f"Not configured ({len(off)})"):
            for s in off:
                st.caption(f"{s['source']}: {str(s.get('last_error') or 'optional')[:70]}")
    sb.caption(f"DB {'ok' if h.get('db_ok') else 'DOWN'} · {h.get('signals_stored')} signals stored")


# ---------------------------------------------------------------- time machine
def _naive_utc(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(UTC).replace(tzinfo=None)


def time_machine(client: ApiClient, sb) -> None:
    """Global "as of" slider over EVENT time (publication time). Default: follow the latest data. The choice is kept
    in session_state, so it persists across pages; every page reads it with as_of(). The slider spans the last 14 days
    of the data; older items stay included in every "as of" view."""
    ss = st.session_state
    try:
        h = client.history()
    except ApiError:
        ss["as_of"] = None
        return
    status = h.get("status") or {}
    if status.get("state") == "building":
        done, total = (status.get("progress") or [0, 0])
        sb.info(f"Building the REAL history from the capture cache: {done}/{total} documents")
    elif status.get("state") == "error":
        sb.warning(f"REAL history unavailable: {status.get('error')}")
    if not h.get("event_from") or not h.get("event_to"):
        ss["as_of"] = None
        return
    hi = _naive_utc(h["event_to"])
    lo = max(_naive_utc(h["event_from"]), hi - timedelta(days=14))
    if hi - lo < timedelta(hours=1):
        ss["as_of"] = None
        return
    follow = ss.get("tm_follow", True)
    cur = hi if follow or "tm_value" not in ss else min(max(ss["tm_value"], lo), hi)
    sb.markdown("**Time machine** · event time, UTC")
    val = sb.slider("As of", min_value=lo, max_value=hi, value=cur, step=timedelta(minutes=30),
                    format="MMM D, HH:mm", label_visibility="collapsed",
                    help="Every page shows the signals published up to this time and their stress runs. The REAL "
                         "history is the captured real news replayed by publication time (it was collected at the "
                         "capture times on each CACHED_REAL badge). Default: the latest data.")
    if val != cur:
        ss["tm_follow"], ss["tm_value"] = False, val
        follow = False
    c1, c2 = sb.columns([3, 2])
    c1.markdown(f'<div class="note">{f"● latest data · {hi:%b %d, %H:%M}" if follow else f"◷ as of {val:%b %d, %H:%M}"}'
                '</div>',
                unsafe_allow_html=True)
    if not follow and c2.button("Latest", use_container_width=True):
        ss["tm_follow"] = True
        ss.pop("tm_value", None)
        st.rerun()
    # "latest" = the newest event time in the data (not the wall clock), so the windows stay full of real data on
    # any day after the last capture; new LIVE/SYNTHETIC signals move it forward automatically.
    ss["as_of"] = (hi if follow else val).replace(tzinfo=UTC).isoformat()


def as_of() -> str | None:
    """The time-machine cut-off (ISO, UTC) chosen in the sidebar, or None for the latest data."""
    return st.session_state.get("as_of")


def run_body(body: Callable[[], None]) -> None:
    """Run the page body, re-running it every 5 s when auto-refresh is on (no animations)."""
    if st.session_state.get("autorefresh"):
        st.fragment(body, run_every=5)()
    else:
        body()


def now_utc() -> datetime:
    return pd.Timestamp.now(tz="UTC").to_pydatetime()
