"""Source health panel: per-source status, last success/error, backoffs; model, DB and bus status."""

from __future__ import annotations

import pandas as pd
import streamlit as st
from components.ui import fmt_ts, guard, kpi, run_body, setup

client = setup("Source & System Health", "🩺")


def body() -> None:
    h = guard(client.health)
    c1, c2, c3, c4 = st.columns(4)
    model = h["model"]
    kpi(c1, "Service status", h["status"].upper(), "degraded = DB down or sentiment fallback",
        "#0ca30c" if h["status"] == "ok" else "#ec835a")
    kpi(c2, "Sentiment model", model.get("backend", "?"), model.get("fallback_reason") or (model.get("model") or ""))
    kpi(c3, "Signals stored", str(h.get("signals_stored")), f"DB {'ok' if h['db_ok'] else 'DOWN'}")
    kpi(c4, "Bus events", str(h["bus"]["signal.created"]), f"{h['bus']['stress.completed']} stress runs published")

    st.subheader("Data sources")
    rows = h.get("sources") or []
    if not rows:
        st.info("No source has been polled in this API session. Switch to LIVE mode (sidebar) to poll real sources; "
                "REPLAY and SCENARIO do not contact external sources.")
        return
    icon = {"OK": "🟢 OK", "EMPTY": "🟢 OK (nothing new)", "DISABLED": "⚪ DISABLED", "BACKOFF": "🟠 BACKOFF",
            "RATE_LIMITED": "🟡 RATE_LIMITED", "DEGRADED": "🟠 DEGRADED", "DOWN": "🔴 DOWN"}
    if rows and rows[0].get("observed_in"):
        st.warning("Not polling live in this session — showing source health from the **last capture_cache.py run** "
                   "(see 'last attempt' times). Switch to LIVE to poll now.")
    df = pd.DataFrame([{
        "source": r["source"], "status": icon.get(r["status"], r["status"]),
        "last success": fmt_ts(r.get("last_success")), "last attempt": fmt_ts(r.get("last_attempt")),
        "docs last cycle": r.get("last_count"), "docs total": r.get("total_docs"),
        "failures in a row": r.get("consecutive_failures"), "backoff until": fmt_ts(r.get("backoff_until")),
        "last error / reason": r.get("last_error") or "",
    } for r in rows])
    st.dataframe(df, hide_index=True, use_container_width=True)
    st.caption("A failing source never stops the app: it is parked (backoff) or marked DEGRADED/DOWN and the other "
               "sources plus cached data keep the feed alive. DISABLED = optional key not configured.")


run_body(body)
