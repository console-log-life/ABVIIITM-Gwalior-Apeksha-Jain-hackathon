# Methodology

Every weight, prior, threshold and scenario value below lives in a YAML or config file. None are hard-coded. **All of
them are expert-set priors for a hackathon prototype. None are learned or calibrated** against market reactions or
historical losses.

## 1. Ingestion and provenance

| Mode | What flows in | Provenance label |
|---|---|---|
| LIVE | Real sources polled now (Google News RSS, Reddit RSS, Mastodon; best-effort GDELT/StockTwits; optional Finnhub/Bluesky) | `LIVE` |
| REPLAY | Real documents captured earlier by `src/scripts/capture_cache.py` | `CACHED_REAL` + capture timestamp |
| SCENARIO / user text | Scripted demo story, headlines typed into the dashboard or `POST /analyze` | `SYNTHETIC` |

All modes call the same function, `risk_engine.pipeline.process_batch()`. Preprocessing does the following:
- strips HTML and URLs;
- checks the language (langdetect, overruled on short headlines by English function words);
- removes exact duplicates (SHA-1 `doc_id` and a per-source title hash);
- removes near-duplicates with rapidfuzz ratio ≥ 92 on normalised titles. Near-duplicates from the *same* source are
  dropped. Near-duplicates from *different* sources are kept, because they are the corroboration signal.

The local capture cache (`data/cache/captures/`) is git-ignored. Only a 50-headline Google News sample
(`data/cache/sample/`) is published, and REPLAY uses it when the local cache is empty. Social adapters never store
author handles. The `publisher` field holds the channel, e.g. `r/stocks`, `#stocks`,
`$AAPL stream`.

## 2. Entity resolution (`src/risk_engine/entity_resolution/`)

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

## 3. Sentiment (`src/risk_engine/sentiment/finbert.py`)

- **Model:** `ProsusAI/finbert`, loaded once on CPU. Label order is read from `model.config.id2label`. On this model it
  is `{0: positive, 1: negative, 2: neutral}`, verified by `src/scripts/setup_models.py`.
- **Score:** `s = P(positive) − P(negative)`, rounded to 3 dp. Labels: s ≤ −0.25 Negative, s ≥ 0.25 Positive, otherwise
  Neutral.
- **Long text:** the title (weight 2) plus up to 8 sentences. Probabilities are averaged with weight × segment
  confidence, and inputs are truncated to 256 tokens. Batches are sorted by length to cut padding cost.
- **Fallback:** a curated finance lexicon with negation handling (a negator within 3 tokens flips polarity). It reports
  `model = "lexicon-fallback"` with confidence capped at 0.5, and `/health` reports when the fallback is active.

## 4. Event classification (`src/risk_engine/event_classifier/taxonomy.yaml`)

- **Classes:** 11, exactly as in the spec, each with weighted regex patterns. The score is the sum of distinct matched
  weights.
- **Primary / secondary:** the primary event is the argmax. Ties go to the more severe class (YAML order). A secondary
  event is reported when its score is ≥ 60% of the primary.
- **Evidence:** the matched phrases are returned as `event_evidence`.
- **Market evidence guard (trigger only):** classification is not changed. A MARKET-wide Geopolitical or
  Macroeconomic signal needs at least 2 *distinct* matched patterns of that class (`market_min_distinct_patterns`,
  counted by `rules.class_evidence_count`) before it may start a **systemic stress run** (`src/portfolio/triggers.py`).
  Applying the guard in classification cost event accuracy (0.803 → 0.762 on the PRELIMINARY labels), so it was moved
  (see `docs/evaluation.md` history and `docs/trigger_replay.md`).
- **Opinion "verdicts":** "analyst verdict", "our verdict", "verdict on the stock" and similar are not Litigation.
- **Figurative-use guards:** "price war", "talent war", "culture war", "bidding war", "turf war", "streaming war",
  "console war" and "fare war", plus "war on <lowercase noun>" ("war on data centres", "war on drugs"), are not
  geopolitical. "War on Ukraine" (a proper noun) still is.
- **Intensifiers:** these adjust the severity factor E but not the class. Default/bankruptcy/invasion/collapse/fraud add
  +0.15, war/sanctions/halt +0.10. Rumour/considering/may/could/reportedly/talks subtract 0.10; "may" is
  case-sensitive, so the month is ignored. The total is clipped to [−0.20, +0.25].
- **Optional zero-shot tie-breaker** (`typeform/distilbert-base-uncased-mnli`): it stays **OFF** because
  `src/scripts/evaluate.py` measured macro-F1 0.78 with it versus 0.795 without (n=147, PRELIMINARY labels).

## 5. Impact score (`src/risk_engine/impact_scoring/weights.yaml`)

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
| Systemic | {Geopolitical, Macroeconomic, Credit Event} and (MARKET or ≥ 2 sources) and impact ≥ 7.0 and the signal comes from a **news source** (`SYSTEMIC_TRIGGER_SOURCES`: google_news, finnhub, gdelt; scenario docs count as the source they imitate). Social posts only add corroboration. A MARKET-wide Geopolitical/Macro signal needs ≥ 2 distinct evidence cues | moderate below 8.5, severe at 8.5 or above |
| Systemic, rates | Macroeconomic rate headline: direction read by `event_classifier/rate_direction.py` | hike → `macro_rate_shock_<severity>`; cut → `macro_rate_cut` (rates −50 bp, IG −10, HY −25, equity +2%, PD ×0.95); unclear → no run |
| Idiosyncratic | {Credit, Regulatory, Litigation} on a held issuer, impact ≥ 6.0 and sentiment ≤ −0.25 (`TRIGGER_IDIOSYNCRATIC_MAX_SENTIMENT`) | issuer-only scenario |

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

## 7. Early warning watchlist (`src/portfolio/watchlist.py`, `GET /watchlist`)

A credit-risk view of recent signals: one row per **held** issuer (every issuer_id in the portfolio), including
issuers with no signals.

**Window.** Signals whose event `timestamp` falls within the `hours` (query parameter, 1–720; default
`WATCHLIST_WINDOW_H` = 24) before `as_of` (the time machine, §9; default: now via the API, the latest data time in
the dashboard). The watchlist answers "what happened recently" at any point of the REAL history.

**Watch status** (thresholds in config, `WATCHLIST_*`; a signal is *negative* when sentiment ≤ −0.25):

| Status | Rule (first match wins) | Config |
|---|---|---|
| WATCH-NEGATIVE | any negative signal with impact ≥ 7.0, **or** ≥ 2 negative signals with impact ≥ 5.0 | `WATCHLIST_WATCH_IMPACT`, `WATCHLIST_WATCH_COUNT`, `WATCHLIST_WATCH_COUNT_IMPACT` |
| MONITOR | any negative signal with impact ≥ 4.0 | `WATCHLIST_MONITOR_IMPACT` |
| MONITOR (propagated, ⇄) | a STABLE issuer linked by a curated link with weight ≥ 0.3 to a WATCH-NEGATIVE issuer (§10) | `WATCHLIST_PROPAGATION_MIN_WEIGHT` (0 disables) |
| STABLE | otherwise, including no signals | n/a |

The negative-sentiment cut-off is the same −0.25 used by the idiosyncratic stress trigger, so strong positive news
(a beat, a court win) never puts an issuer on watch. Every row carries `status_reason`, naming the rule and the signal
that fired it.

**Per issuer:** signal count and negative count, worst impact, mean sentiment, event-type counts, distinct sources
(the imitated source for SYNTHETIC scenario documents), the maximum corroborating-source count, the top-3 signals
(highest impact, then newest) with their `reason` text, and the impact series for the sparkline. Exposure is the
funded market value (loans, bonds, equity) and its % of the funded book. The rating bucket is that of the issuer's
largest funded position. CDS protection bought is shown as notional.

**Ranking:** status (WATCH-NEGATIVE, then MONITOR, then STABLE), then the strongest negative signal, then exposure.

**What it is not:** the status is a rules-based flag for analyst attention. It is not a credit rating, a PD
estimate or investment advice, and the thresholds are expert-set, not calibrated. In the demo story, step 2
(the Tata Motors downgrade, impact 8.7, sentiment −0.90) makes Tata Motors WATCH-NEGATIVE (`tests/test_watchlist.py`).

## 8. Learned models: public training data (`src/risk_engine/training/`, `src/scripts/datasets/`)

Two **public, human-labelled** datasets (both MIT-licensed; provenance in `data/external/DATASETS.md`):
- `zeroshot/twitter-financial-news-sentiment` (Bearish / Bullish / Neutral → Negative / Positive / Neutral) to
  fine-tune FinBERT;
- `zeroshot/twitter-financial-news-topic` (20 topics) to train an event classifier.

**Splits (seed 42, `src/risk_engine/training/public_data.py`):** test = each dataset's own `validation` split, held out
and used only for the final evaluation. Train rows that duplicate a test row after link removal, or nearly duplicate
one (rapidfuzz ratio ≥ 92), are removed from train (sentiment: 227 rows, topic: 1,270). Dev = a stratified 10% of
the remaining train rows. The split ids and sha256 checksums are committed in `data/splits/`. Financial PhraseBank
is not used to evaluate FinBERT, because FinBERT was trained on it.

**Topic → event mapping** (`topic_map` in `taxonomy.yaml`, curated by hand):

| Public topic | Our class |
|---|---|
| Fed / Central Banks, Macro, Currencies, Energy / Oil, Gold / Metals / Materials | Macroeconomic |
| Politics | Geopolitical |
| Legal / Regulation | Regulatory (litigation is not separable in this dataset) |
| M&A / Investments | M&A |
| Earnings, Dividend | Earnings |
| Personnel Change | Management |
| Company / Product News | Product Launch (noisy: includes general company news) |
| Treasuries / Corporate Debt | Credit Event (broader than defaults and downgrades) |
| IPO | Other (a listing is not a change of control) |
| Analyst Update, Financials, General News / Opinion, Markets, Stock Commentary, Stock Movement | Other |

Credit events in the strict sense (defaults, downgrades), Supply Chain and Litigation have no clean public labels.
For those three classes the rule engine stays authoritative (hybrid classifier, below).

## 9. REAL history and the time machine (`src/risk_engine/history.py`, `GET /history`, `as_of` everywhere)

The whole local CACHED_REAL capture cache is processed **once** through the same pipeline (FinBERT, events, entities,
corroboration, impact) and the same stress trigger rules, in event-time order, with the trigger clock set to each
signal's event time (the convention of `src/scripts/replay_trigger_report.py`). Triggered stress runs are simulated with
the illustrative model on the synthetic portfolio, stored at the event time with ids `real-…`. The result is cached in
`data/real_history.db` (git-ignored) with a fingerprint of the capture files, taxonomy, weights, scenarios, portfolio,
issuer universe and active models; the API loads it at start-up in about a second, or rebuilds it (minutes, reusing
its own FinBERT) when an input changed. On a fresh clone the committed 50-headline sample is used.

**Time machine:** every view can be shown "as of" a time T on the **event (publication) time** axis: signals with
`timestamp ≤ T`, watch status over the 24 h before T, the latest stress run at or before T. We chose event time
because our captures are bursts (3 Oct and 5 Oct) while publication times are continuous; the time machine therefore
replays the real news timeline as published. The documents were collected at their capture times, which every
CACHED_REAL badge shows: an "as of" view is a reconstruction, not what a live system saw at T.

Demo resets keep the REAL history. The corroboration window ignores it, so the scripted SYNTHETIC story always gives
the same results.

## 10. Risk propagation (`src/portfolio/propagation.py`, `GET /propagation`)

16 issuer links in `universe.yaml` (`supplier_of`, `parent_of`, `peer_of`), **curated by hand** from well-known public
relationships, not inferred from data and not exhaustive. Examples: Nvidia supplier of Microsoft, Meta, Amazon and
Alphabet (data-centre GPUs); Government of India parent of SBI (majority owner); Tata Motors, Ford and Tesla peers;
HDFC Bank and SBI peers. "Jaguar Land Rover" and "Adani Group" are aliases of Tata Motors and Adani Enterprises, so
their news already lands on those issuers.

For an issuer i: **direct exposure** = funded MV held in i; **propagated exposure** = Σ_j w_ij × exposure_j over the
linked issuers j, with w = decay of the relation (`PROPAGATION_DECAY`: supplier/parent 0.5, peer 0.3) and products of
decays along longer paths when `PROPAGATION_MAX_HOPS` > 1 (default 1 = second order). Links are two-way for contagion.
Each issuer is counted once, at its strongest path; the start issuer is never counted, so cycles cannot inflate the
total (`tests/test_propagation.py`). The figure is an attention measure, not a loss estimate: there are no
correlations or default-contagion probabilities behind it.

## 11. What-if scenario builder (`POST /portfolio/what-if`)

Six shocks (rates, IG and HY spreads, equity, EM FX, PD multiplier) priced instantly with the same pricers as the
named scenarios. Nothing is saved: no audit-log entry, no "latest run", no bus event. Starting from a named scenario
reproduces it exactly (e.g. geopolitical severe = 2.45%). Tests check monotonic responses: wider spreads lose more on
bonds and loans and gain more on bought CDS protection; higher PD multipliers lose more; higher rates lose on bonds.

## 12. Credit brief (`src/portfolio/credit_brief.py`, `GET /credit-brief/{issuer}?format=json|html|pdf`)

A one-page issuer brief built from **templates** (no language model): issuer and illustrative rating bucket; watch
status and the rule that fired; direct and propagated exposure; the last six signals with their reason text; the
issuer-only shock priced now (not saved) and the latest systemic run's P&L on this issuer; CDS hedges; the stress
disclaimer. Every sentence is filled from stored data. The PDF (`credit_brief_<ticker>_<date>.pdf`) uses fpdf2's
core fonts, so non-Latin symbols are replaced (→ becomes ->, ₹ becomes Rs).
