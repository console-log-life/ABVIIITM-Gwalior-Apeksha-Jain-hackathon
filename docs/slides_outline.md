# Slides outline: exactly 7 slides

Numbers on these slides must come only from `docs/evaluation.md` (PRELIMINARY until the labels are human-reviewed),
`docs/benchmark.md` and the stress engine's simulated outputs (always labelled "simulated, illustrative model").

The built deck is `docs/presentation/Risk_Signal_Engine.pptx` (`tasks.ps1 deck`). `scripts/build_presentation.py` reads
its numbers from the same JSON outputs, so rebuild it after any re-evaluation.

---

## Slide 1: Risk Signal Engine: from headlines to portfolio stress in seconds
- **Problem:** risk-relevant news and social chatter arrive as unstructured text; they're noisy, duplicated and not
  linked to holdings.
- **Solution:** an NLP engine scores every item for sentiment, event type and a transparent 1–10 impact, then triggers
  a portfolio stress test when it matters.
- Module B, Strategic Portfolio Stress Testing, is implemented.

**Visual:** one-line flow graphic, headline → signal card → RED stress banner.
**Don't include:** accuracy numbers, model jargon.
**Speaker notes:** "Every number you'll see is either measured by a script in the repo or clearly labelled as
simulated or synthetic."

## Slide 2: Business context
- Credit analysts and risk teams monitor hundreds of issuers. Downgrades, probes and sanctions hit the text before
  the data.
- Manual triage is slow, and nothing connects a headline to the portfolio's exposure.
- The need is early warning, prioritisation by materiality, and an immediate "what does this do to my book?".
- Users: risk managers, credit analysts, portfolio managers.

**Visual:** a timeline from news breaking, to the analyst reading it, to a manual stress run hours later; versus
seconds with the engine.
**Don't include:** market-size claims or ROI numbers (not measured).
**Speaker notes:** frame it as decision support, not trading signals.

## Slide 3: Architecture
- Sources: Google News RSS, Reddit RSS and Mastodon (probe-verified); GDELT and StockTwits best-effort; Finnhub and
  Bluesky optional.
- Adapters with rate limits, retries and backoff, then clean and dedup, then **one NLP pipeline** for LIVE, REPLAY,
  SCENARIO and the API.
- RiskSignal is stored in SQLite and published on the event bus; FastAPI serves REST, SSE and a JSONL export.
- The stress engine subscribes to `signal.created`; the Streamlit dashboard reads only from the API.
- Every record carries its provenance: LIVE, CACHED_REAL (with capture time) or SYNTHETIC.

**Visual:** the diagram from `docs/architecture.md`.
**Don't include:** a list of every file.
**Speaker notes:** mention the offline drill. The demo runs with the network unplugged.

## Slide 4: NLP risk engine
- **Entities:** cashtags → aliases (ambiguous names need context: "apple pie" ≠ AAPL) → spaCy ORG → guarded fuzzy
  match → MARKET.
- **Sentiment:** FinBERT, s = P(pos) − P(neg), with a lexicon fallback.
- **Events:** an 11-class rule taxonomy with evidence phrases and intensifiers. The zero-shot tie-breaker was tested
  and kept off.
- **Impact:** 1 + 9·Q·(0.40E + 0.25M + 0.20X + 0.15R), with expert priors that are not calibrated.
- **Explainability:** probabilities → evidence → weighted factors → reason → business implication.

**Visual:** screenshot `06_explain.png` (factor bar + formula).
**Don't include:** claims that the weights are learned or optimal.
**Speaker notes:** walk through the Tata Motors example. Downgrade + SEBI probe gives Credit Event with Regulatory as
secondary, impact 8.7.

## Slide 5: Stress testing (Module B)
- **Portfolio:** 49 synthetic positions (seed 42), including loans, bonds, IRS, CDS hedges, FX forwards and equity.
- **Systemic trigger:** a geopolitical, macro or credit event that is MARKET-wide or corroborated, with impact ≥ 7
  (severe at ≥ 8.5), and only when a news source reports it. Social posts only corroborate.
- **Idiosyncratic trigger:** a credit, regulatory or litigation event on a held issuer with impact ≥ 6. Each trigger
  has a 30-minute cooldown and an audit trail.
- **Outputs:** before/after waterfall, top-10 positions (hedges in green), sector × asset heatmap, HHI, RAG versus
  2% appetite.
- **Demo outcomes (simulated):** idiosyncratic 0.41% GREEN → geopolitical moderate 1.32% AMBER → severe 2.45% RED.

**Visual:** screenshot `05_stress.png`.
**Don't include:** any wording that sounds like a regulatory model. Keep the disclaimer visible on the slide.
**Speaker notes:** "Simplified, illustrative hackathon stress model. Not a production or regulatory risk model."

## Slide 6: Results, dashboard and business impact
- **PRELIMINARY evaluation** (n = 147 real headlines; labels AI-drafted, pending review): sentiment accuracy 0.653;
  event accuracy 0.81; entity accuracy 0.898.
- **False-trigger fixes, replayed on 911 locally captured real documents:** stress runs 84 → 50; triggered by social posts 11 → 0.
- **Latency on a CPU laptop** (n = 200): median 204.7 ms, p95 1085.2 ms per document.
- **Reliability:** 180 automated tests; offline/outage drill 7/7.
- **Dashboard:** 12 sections plus "analyse your own headline".
- **Impact:** faster triage, prioritisation by materiality, instant portfolio view. A decision-support tool, not
  investment advice.

**Visual:** `01_home.png` plus a small results table, with "PRELIMINARY" written on it.
**Don't include:** returns, alpha or "x% faster" claims (not measured).
**Speaker notes:** state the same-author caveat. The lexicon and rules were written by the labeller.

## Slide 7: Innovation, limitations, future scope, takeaway
- **Innovation:** provenance on every record; one pipeline for live, replay and demo; corroboration escalates
  severity; trigger audit trail.
- **Limitations:** uncalibrated weights; keyword false positives; headline-only news; small AI-labelled eval set;
  illustrative stress model.
- **Future:** Kafka streaming, impact calibration against market moves, licensed data, backtesting, full revaluation,
  access control.
- **Takeaway:** an honest, explainable bridge from text to portfolio risk that runs offline on a laptop.

**Visual:** two columns, "what works today" and "what's next".
**Don't include:** a long list of future ideas; stick to the top 4.
**Speaker notes:** invite the judges to type their own headline into the dashboard.
