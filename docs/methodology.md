# Methodology

Every weight, prior, threshold and scenario value below lives in a YAML or config file. None are hard-coded. **All of
them are expert-set priors for a hackathon prototype. None are learned or calibrated** against market reactions or
historical losses.

## 1. Ingestion and provenance

| Mode | What flows in | Provenance label |
|---|---|---|
| LIVE | Real sources polled now (Google News RSS, Reddit RSS, Mastodon; best-effort GDELT/StockTwits; optional Finnhub/Bluesky) | `LIVE` |
| REPLAY | Real documents captured earlier by `scripts/capture_cache.py` | `CACHED_REAL` + capture timestamp |
| SCENARIO / user text | Scripted demo story, headlines typed into the dashboard or `POST /analyze` | `SYNTHETIC` |

All modes call the same function, `risk_engine.pipeline.process_batch()`. Preprocessing does the following:
- strips HTML and URLs;
- checks the language (langdetect, overruled on short headlines by English function words);
- removes exact duplicates (SHA-1 `doc_id` and a per-source title hash);
- removes near-duplicates with rapidfuzz ratio ≥ 92 on normalised titles. Near-duplicates from the *same* source are
  dropped. Near-duplicates from *different* sources are kept, because they are the corroboration signal.

Social adapters never store author handles. The `publisher` field holds the channel, e.g. `r/stocks`, `#stocks`,
`$AAPL stream`.

## 2. Entity resolution (`risk_engine/entity_resolution/`)

The universe has 25 issuers: 15 US large caps, 6 Indian corporates, the US and Indian sovereigns, and HSBC. Each has
aliases, a sector, a country and an **illustrative** rating bucket. Resolution runs in this order:

1. Cashtags (`$AAPL`). Tickers outside the universe are kept as external tickers.
2. The alias dictionary. Ambiguous brand words (Apple, Amazon, Ford, Intel, Reliance, …) must be capitalised and need
   a context keyword (shares, CEO, earnings, iPhone, …) or a ticker hint. So "apple pie recipe" does not resolve.
3. spaCy `en_core_web_sm` ORG spans matched exactly to names and aliases.
4. rapidfuzz `token_set_ratio ≥ 88` on ORG spans. Because token_set_ratio scores 100 for any token subset, *every*
   distinctive (non-generic) token of the candidate name must also appear in the ORG span. So "SEC" no longer matches
   the alias "G-Sec" (Government of India).
5. The ticker hint from a ticker-specific search query, used only when the text names no company.
6. If nothing resolves: `MARKET` for Geopolitical/Macroeconomic events, otherwise `UNRESOLVED`.

The pattern "X's supplier" sets `relation = supplier`, which appears in the business implication.

## 3. Sentiment (`risk_engine/sentiment/finbert.py`)

- **Model:** `ProsusAI/finbert`, loaded once on CPU. Label order is read from `model.config.id2label`. On this model it
  is `{0: positive, 1: negative, 2: neutral}`, verified by `scripts/setup_models.py`.
- **Score:** `s = P(positive) − P(negative)`, rounded to 3 dp. Labels: s ≤ −0.25 Negative, s ≥ 0.25 Positive, otherwise
  Neutral.
- **Long text:** the title (weight 2) plus up to 8 sentences. Probabilities are averaged with weight × segment
  confidence, and inputs are truncated to 256 tokens. Batches are sorted by length to cut padding cost.
- **Fallback:** a curated finance lexicon with negation handling (a negator within 3 tokens flips polarity). It reports
  `model = "lexicon-fallback"` with confidence capped at 0.5, and `/health` reports when the fallback is active.

## 4. Event classification (`risk_engine/event_classifier/taxonomy.yaml`)

- **Classes:** 11, exactly as in the spec, each with weighted regex patterns. The score is the sum of distinct matched
  weights.
- **Primary / secondary:** the primary event is the argmax. Ties go to the more severe class (YAML order). A secondary
  event is reported when its score is ≥ 60% of the primary.
- **Evidence:** the matched phrases are returned as `event_evidence`.
- **Market evidence guard:** a MARKET-wide Geopolitical or Macroeconomic call needs at least 2 *distinct* matched
  patterns of that class (`market_min_distinct_patterns`). Otherwise the call is demoted to the secondary class, or to
  Other, and entity resolution is re-run (`risk_engine.pipeline.classify_and_resolve`, used by the pipeline and by
  `scripts/evaluate.py`). This trades some recall for far fewer false systemic triggers (see `docs/trigger_replay.md`).
- **Figurative-use guards:** "price war", "talent war", "culture war", "bidding war", "turf war", "streaming war",
  "console war" and "fare war", plus "war on <lowercase noun>" ("war on data centres", "war on drugs"), are not
  geopolitical. "War on Ukraine" (a proper noun) still is.
- **Intensifiers:** these adjust the severity factor E but not the class. Default/bankruptcy/invasion/collapse/fraud add
  +0.15, war/sanctions/halt +0.10. Rumour/considering/may/could/reportedly/talks subtract 0.10; "may" is
  case-sensitive, so the month is ignored. The total is clipped to [−0.20, +0.25].
- **Optional zero-shot tie-breaker** (`typeform/distilbert-base-uncased-mnli`): it stays **OFF** because
  `scripts/evaluate.py` measured macro-F1 0.751 with it versus 0.768 without (n=147, PRELIMINARY labels).

## 5. Impact score (`risk_engine/impact_scoring/weights.yaml`)

```
Impact = clip(1 + 9 × Q × (0.40·E + 0.25·M + 0.20·X + 0.15·R), 1, 10), rounded to 1 dp
```

| Factor | Definition |
|---|---|
| E, event severity | Base by class: Credit 0.90, Geopolitical 0.85, Macro 0.75, Regulatory 0.70, Litigation/M&A/Supply 0.60, Earnings 0.55, Management 0.45, Product 0.30, Other 0.20; plus intensifiers; clipped to [0, 1] |
| M, sentiment magnitude | \|s\| × 1.0 if s < 0, × 0.6 if s ≥ 0 |
| X, exposure | MARKET 1.0; held issuer 0.4 + 0.6 × exposure / max exposure (funded MV from the portfolio); non-held resolved 0.3; UNRESOLVED 0.1 |
| R, credibility | Source prior (Google News/Finnhub 0.85, GDELT 0.75, manual 0.60, Reddit/StockTwits/Mastodon/Bluesky 0.40; scenario = imitated source) + 0.10 per extra corroborating source, cap 1.0 |
| Q, confidence shrinkage | 0.6 + 0.4 × sentiment confidence |

- **Risk levels:** < 4 Low, 4–6.9 Medium, 7–8.4 High, ≥ 8.5 Critical.
- **Reason:** generated from the two largest weighted contributions.
- **Business implication:** a template keyed by event × (held / market / other).
- **Corroboration:** the same entity and primary event, from ≥ 2 distinct sources, within 6 h. MARKET signals also need
  one shared evidence phrase.

**Known property:** positive sentiment also raises the score (M uses 0.6 × |s|). The score measures materiality, i.e.
how much a story deserves attention, not downside alone. A positive product launch at a *large* holding reported by a
news wire scores Medium (5.3 in our test). A small holding seen on social media scores Low (3.6).

## 6. Module B: stress testing (`portfolio/`)

**Portfolio.** No transaction data was provided, so `generate_portfolio.py` (seed 42) builds 49 **SYNTHETIC**
positions with a funded MV of $830.0m.
- **Gross mix:** Loan 40%, Bond 35%, IRS 8%, Equity 8%, FX 5%, CDS 4%. This is measured on gross exposure: MV for
  cash instruments, notional for the derivative overlays. Loss % uses funded MV.
- **Hedges:** three CDS protection-bought positions on held HY issuers (Tata Motors, Adani, Ford).
- **Held issuers:** 23. Walmart and Pfizer are deliberately not held.

**Pricers.** All ΔV are in USD; positive means a gain.

| Instrument | ΔV |
|---|---|
| Bond | MV × (−D·Δr − SD·Δs + ½·C·Δy²). SD = D for corporates; US Treasuries have SD = 0 |
| Loan | −EAD × LGD × (PD_stressed − PD_base), PD_stressed = min(PD × m_bucket, 1), m_bucket = 1 + (PD× − 1) × sensitivity (AAA-AA 0.5 … B-or-below 1.5). Fixed-rate loans add −MV·D·Δr |
| IRS | DV01 stored positive: **pay-fixed ΔV = +DV01 × Δbp** (gains when rates rise); receive-fixed is the negative. This corrects a sign typo in the original spec, and unit tests cover it |
| CDS protection bought | +notional × spread duration × Δs (gains when spreads widen) |
| FX forward | notional × EM-FX shock × direction (+1 long / −1 short the EM currency) |
| Equity | MV × equity shock × β |

**Scenarios** (`scenarios.yaml`, each with a one-line rationale) are the spec values plus an added
`systemic_credit_moderate`, which is half of severe. Spread shocks scale by rating bucket: AAA-AA 0.5×IG, A 0.8×IG,
BBB 1.0×IG, BB 1.0×HY, B-or-below 1.3×HY.

**Triggers** (thresholds come from config):

| Trigger | Condition | Scenario run |
|---|---|---|
| Systemic | {Geopolitical, Macroeconomic, Credit Event} and (MARKET or ≥ 2 sources) and impact ≥ 7.0 and the signal comes from a **news source** (`SYSTEMIC_TRIGGER_SOURCES`: google_news, finnhub, gdelt; scenario docs count as the source they imitate). Social posts only add corroboration | moderate below 8.5, severe at 8.5 or above |
| Idiosyncratic | {Credit, Regulatory, Litigation} on a held issuer and impact ≥ 6.0 | issuer-only scenario |

A 30-minute cooldown applies per scenario and scope. Suppressed triggers are logged, and every run stores its
triggering `signal_id`.

**Outputs:**
- before/after value, absolute and % loss;
- loss by asset class, sector, issuer and country;
- top-10 positions, hedge offset, sector/issuer HHI;
- RAG against the 2% risk appetite (green < 1%, amber 1–2%, red > 2%).

**Sanity band (tests).** Severe scenarios on the default portfolio must lose 0.5–15% of funded MV. Measured
(`StressEngine.run`): geopolitical_severe 2.45%, macro_rate_shock_severe 8.06%, systemic_credit_severe 3.65%. No
recalibration was needed.

**Not modelled:**
- FX translation of INR-denominated holdings (only FX forwards take the FX shock);
- correlations between shocks;
- full revaluation;
- liquidity;
- time horizon.

*Simplified, illustrative hackathon stress model. Not a production or regulatory risk model.*
