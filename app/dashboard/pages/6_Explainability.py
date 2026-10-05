"""Section 12: Explainability — text → sentiment probabilities → event + evidence → weighted impact factors →
final score → business implication. Includes the "Analyse your own headline" box (POST /analyze)."""

from __future__ import annotations

import html

import streamlit as st
from components import charts
from components.ui import fmt_ts, guard, provenance_badge, risk_badge, setup

client = setup("Explainability", "🔍")
method = guard(client.methodology)


def explain(sig: dict) -> None:
    st.markdown(f"{risk_badge(sig['risk_level'])}{provenance_badge(sig)} **{html.escape(sig['company'])}**"
                + (f" ({sig['ticker']})" if sig.get("ticker") else "")
                + f" · {sig['source']} · {fmt_ts(sig['timestamp'])}", unsafe_allow_html=True)
    st.markdown(f"> {html.escape(sig['text_excerpt'])}")

    st.markdown("**1 · Sentiment**")
    c1, c2 = st.columns([2, 3])
    c1.plotly_chart(charts.sentiment_probs(sig["sentiment_probs"]), use_container_width=True)
    p = sig["sentiment_probs"]
    c2.markdown(f"s = P(positive) − P(negative) = {p['positive']:.3f} − {p['negative']:.3f} = "
                f"**{sig['sentiment_score']:+.3f}** → **{sig['sentiment_label']}**  \n"
                f"confidence = max(probabilities) = **{sig['confidence']:.3f}** · model: `{sig['model']}`")
    if sig["model"] != "finbert":
        c2.warning("Lexicon fallback was used (FinBERT unavailable); confidence is capped at 0.5.")

    st.markdown("**2 · Event classification** (rule-based, evidence phrases shown)")
    chips = "".join(f'<span class="chip">{html.escape(e)}</span>' for e in sig["event_evidence"]) or "<i>none</i>"
    st.markdown(f"Primary **{sig['event_type']}**"
                + (f" · secondary **{sig['secondary_event_type']}**" if sig.get("secondary_event_type") else "")
                + f"<br>Evidence: {chips}", unsafe_allow_html=True)

    st.markdown("**3 · Impact score**")
    f = sig["impact_factors"]
    w = method["weights"]
    c1, c2 = st.columns([3, 2])
    c1.plotly_chart(charts.factor_contributions(f, w), use_container_width=True)
    total = sum(w[k] * f[k] for k in "EMXR")
    c2.markdown(f"Impact = 1 + 9 × Q × Σ(w·factor)  \n= 1 + 9 × {f['Q']:.3f} × {total:.3f}  \n"
                f"= **{sig['impact_score']:.1f}** → {sig['risk_level']}  \n\n"
                f"Q = 0.6 + 0.4 × confidence = {f['Q']:.3f} (confidence shrinkage)  \n"
                f"Corroborating distinct sources: **{sig['corroborating_sources']}**")
    c2.caption(method["note"])
    st.markdown(f"**Reason:** {html.escape(sig['reason'])}")
    st.markdown(f"**4 · Business implication:** {html.escape(sig['business_implication'])}")


tab_stored, tab_own = st.tabs(["Explain a stored signal", "Analyse your own headline"])
with tab_stored:
    rows = guard(client.signals, limit=500)
    wanted = st.query_params.get("signal_id")  # click-through from the Early Warning Watchlist
    if wanted and not any(r["signal_id"] == wanted for r in rows):
        extra = guard(client.signal, wanted)
        if extra:
            rows.append(extra)
        else:
            st.warning("The signal linked from the watchlist is no longer stored (the demo may have been reset).")
    if not rows:
        st.info("No stored signals yet.")
    else:
        rows = sorted(rows, key=lambda r: (-r["impact_score"], -r["seq"]))
        start = next((i for i, r in enumerate(rows) if r["signal_id"] == wanted), 0)
        if wanted and rows[start]["signal_id"] == wanted:
            st.caption("Opened from the Early Warning Watchlist.")
        pick = st.selectbox("Signal (highest impact first)", range(len(rows)), index=start,
                            format_func=lambda i: f"{rows[i]['impact_score']:.1f} · {rows[i]['company']} · "
                                                  f"{rows[i]['event_type']} · {rows[i]['text_excerpt'][:70]}")
        explain(rows[pick])
with tab_own:
    with st.form("analyze"):
        text = st.text_area("Headline or post", height=90,
                            placeholder="e.g. Moody's downgrades Tata Motors to junk as SEBI opens probe")
        ticker = st.text_input("Optional ticker hint", placeholder="e.g. TATAMOTORS.NS")
        submitted = st.form_submit_button("Analyse", type="primary")
    st.caption("Your text is labelled SYNTHETIC (user-supplied), stored like any signal, and can trigger a stress "
               "test if it is high-impact.")
    if submitted:
        if not text.strip():
            st.warning("Please enter some text.")
        else:
            res = guard(client.analyze, text.strip(), ticker.strip() or None)
            if res.get("duplicate"):
                st.info("This exact text was analysed before — showing the stored signal.")
            explain(res)
