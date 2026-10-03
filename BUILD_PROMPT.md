# BUILD PROMPT — AI/NLP Financial Risk Engine + Portfolio Stress Testing
### S&P Global × CRISIL "Code to Connect Hackathon 2026" — Phase 3

> Saved verbatim from the original chat prompt (2026-10-03) so the build can be resumed. Placeholders were
> resolved as: deadline unknown; team/laptop = Windows 11, 7.7 GB RAM, no GPU; transaction data = NONE;
> submission guidelines = NONE. Later overrides from the user are recorded in docs/PROGRESS.md.

---

## 0. ROLE AND OPERATING MODE

You are the lead engineer building a demo-ready, industry-grade MVP. You write complete, runnable code, not tutorials or pseudo-code. You work **milestone by milestone** and **STOP at every gate** for my confirmation. You optimise for **RELIABILITY > COMPLEXITY** and **HONESTY > IMPRESSIVENESS**.

Project facts to fill in:
- Deadline: `{{DEADLINE}}`
- Team size / skills: `{{TEAM}}`
- Laptop: `{{OS}}`, `{{RAM_GB}}` GB RAM, no GPU assumed
- Provided sample transaction data: `{{TRANSACTION_DATA_PATH or "NONE"}}`
- Submission guidelines text: `{{PASTE OR "NONE"}}`

---

## 1. NON-NEGOTIABLE RULES

Violating any of these is a failed deliverable.

1. **No fabricated numbers.** Never state an accuracy, F1, latency, or benchmark that was not produced by code in this repo and printed in a run you executed. Every metric in README/slides MUST cite the script that produced it (`scripts/evaluate.py`, `scripts/benchmark_latency.py`).
2. **No fake real-time.** Every document and signal MUST carry `provenance ∈ {LIVE, CACHED_REAL, SYNTHETIC}`. The dashboard MUST display it as a badge on every row. Cached data MUST show its capture timestamp. Synthetic data MUST say "SYNTHETIC".
3. **No unverified API claims.** Do not claim a source works until `scripts/probe_sources.py` has passed against it on my machine. If a source fails the probe, document it in `docs/data_sources.md` and fall back. Do not invent endpoints.
4. **No secrets in code.** All keys come from `.env` via `pydantic-settings`. `.env` is in `.gitignore`. `.env.example` lists every variable with a comment. The app MUST run with zero keys set (keyless sources + cache).
5. **One pipeline.** LIVE, REPLAY and SCENARIO modes MUST pass through the exact same `risk_engine.pipeline.process()` function. No demo-only shortcuts that bypass NLP.
6. **Offline demo.** After running `scripts/setup_models.py` once, the full demo MUST work with the network unplugged (`HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`).
7. **Label the finance model honestly.** Every stress output (UI, API, README) MUST state: *"Simplified, illustrative hackathon stress model. Not a production or regulatory risk model."*
8. **No silent failures.** Every external call has a timeout (≤10 s, GDELT ≤20 s), bounded retries (tenacity, max 2), and a logged, user-visible fallback. A source failure MUST NOT crash the app.
9. **Complete files only.** When you write a file, write all of it. No `...`, no `# TODO: implement`, no placeholder functions. Imports MUST resolve.
10. **Pin dependencies** with exact versions in `requirements.txt`. Use CPU-only torch.
11. **Do not expand scope.** No features beyond this spec until Milestone 6 is green. Propose extras in a "Stretch ideas" list instead of building them.
12. **Do not dump the whole project at once.** Build per milestone. Max ~600 lines of new code per response; continue in the next response if needed.

---

## 2. PROBLEM REQUIREMENTS (must all be visibly satisfied)

| ID | Requirement | Where it MUST be demonstrable |
|---|---|---|
| R1 | Ingest real-time unstructured text | Live feed page, LIVE badges, source health panel |
| R2 | ≥ 2 different source types (news + social) | Source column/filter; adapters in `risk_engine/ingestion/` |
| R3 | Sentiment score in [-1, 1] | Signal JSON + dashboard |
| R4 | Event classification (taxonomy below) | Signal JSON + event distribution chart |
| R5 | Impact score 1–10 (transparent) | Signal JSON + factor breakdown chart |
| R6 | Structured output consumable downstream | FastAPI + SQLite + JSONL export + SSE stream |
| R7 | Downstream Module B: stress testing | Stress page |
| R8 | Portfolio from provided sample transaction data (if provided) else seeded synthetic | Portfolio page shows which |
| R9 | Mix of loans, bonds, derivatives | Asset-class breakdown |
| R10 | High-impact event triggers stress test | Alert banner + stress run log |
| R11 | Before vs after visualisation | Stress page charts |
| R12 | Public repo, runnable | README quickstart works on a clean clone |
| R13 | ≤ 5-min demo | `DEMO.md` + `scripts/run_demo.py` |
| R14 | ≤ 7 slides | `docs/slides_outline.md` |

---

## 3. VERIFIED DATA-SOURCE FACTS (as of Oct 2026 — re-verify with the probe)

| Source | Access | Auth | Known constraints | Role |
|---|---|---|---|---|
| Google News RSS `https://news.google.com/rss/search?q=...&hl=en-US&gl=US&ceid=US:en` (also `gl=IN&hl=en-IN&ceid=IN:en`) | RSS (`feedparser`) | None | Headline + publisher + timestamp only, no body; ≤100 items/query; links are Google redirects (do NOT try to decode them); unofficial, no SLA | Primary news |
| Finnhub `GET https://finnhub.io/api/v1/company-news?symbol=&from=&to=&token=` | REST | Free key (`FINNHUB_API_KEY`) | ~60 req/min free; US equities; optional — skip cleanly if no key | Secondary news |
| GDELT DOC 2.0 `https://api.gdeltproject.org/api/v2/doc/doc?query=...&mode=artlist&format=json&maxrecords=50` | REST | None | ≥5 s between requests; often 10–15 s responses; may return plain-text errors with HTTP 200 — MUST validate JSON before parsing | Macro/geopolitical, background only |
| StockTwits `https://api.stocktwits.com/api/2/streams/symbol/{SYMBOL}.json` | REST (unofficial) | None | Latest 30 messages only; may be blocked; some messages carry user Bullish/Bearish tags | Primary social (best-effort) |
| Reddit subreddit RSS `https://www.reddit.com/r/{sub}/new/.rss` | RSS | None | Unverified — probe first; official API requires approval (do NOT use OAuth API) | Backup social |
| **Excluded:** X/Twitter API (no free tier since Feb 2026), Yahoo Finance RSS (reported 429s Sep 2026) | — | — | Document why in `docs/data_sources.md` | — |

Use a descriptive `User-Agent` header. Respect rate limits with a per-source token bucket.

---

## 4. ARCHITECTURE (implement exactly this flow)

```
Sources → Ingestion adapters (provenance, retries, rate limits)
       → Preprocess (clean, language check, SHA-1 exact dedup + rapidfuzz near-dup ≥ 92 on title)
       → Entity resolution → Sentiment (FinBERT) → Event classification (rules [+ optional zero-shot])
       → Corroboration (same entity + same primary event, ≥2 distinct sources, 6 h window)
       → Impact scoring → RiskSignal (Pydantic)
       → SQLite store + in-process pub/sub bus + FastAPI (REST + SSE)
       → Stress engine (subscribes to bus) → Streamlit dashboard
```

### 4.1 Tech stack (fixed)
Python 3.11 · FastAPI + Uvicorn · Pydantic v2 + pydantic-settings · SQLAlchemy 2 + SQLite · transformers + torch (CPU) · spaCy `en_core_web_sm` · rapidfuzz · httpx · feedparser · tenacity · PyYAML · Streamlit · Plotly · pandas/numpy · pytest + pytest-asyncio · ruff.

### 4.2 Repository layout (fixed)
```
risk-signal-engine/
├── README.md  DEMO.md  requirements.txt  .env.example  .gitignore  Makefile  LICENSE
├── app/
│   ├── config.py
│   ├── main.py                       # FastAPI app; lifespan starts ingestion loop + bus subscribers
│   ├── api/ routes_signals.py routes_portfolio.py routes_health.py routes_demo.py
│   └── dashboard/ Home.py  pages/  components/  api_client.py
├── risk_engine/
│   ├── schemas.py  pipeline.py  bus.py  store.py  logging_setup.py
│   ├── ingestion/ base.py google_news.py finnhub.py gdelt.py stocktwits.py reddit_rss.py replay.py scenario.py scheduler.py
│   ├── preprocessing/ clean.py dedup.py
│   ├── entity_resolution/ resolver.py universe.yaml
│   ├── sentiment/ finbert.py lexicon_fallback.py
│   ├── event_classifier/ rules.py taxonomy.yaml zero_shot.py
│   └── impact_scoring/ scorer.py weights.yaml corroboration.py
├── portfolio/
│   ├── generate_portfolio.py loader.py portfolio_data.csv
│   ├── pricers.py stress_engine.py triggers.py scenarios.yaml
├── data/ cache/  scenarios/demo_story.json  eval/labelled_headlines.csv
├── scripts/ probe_sources.py setup_models.py capture_cache.py evaluate.py benchmark_latency.py run_demo.py
├── tests/
└── docs/ architecture.md methodology.md data_sources.md evaluation.md slides_outline.md demo_script.md judge_qa.md
```

---

## 5. DATA CONTRACTS (exact)

### 5.1 `RawDocument`
```json
{
  "doc_id": "sha1 of source+url+title",
  "source": "google_news | finnhub | gdelt | stocktwits | reddit | manual | scenario",
  "source_type": "news | social",
  "provenance": "LIVE | CACHED_REAL | SYNTHETIC",
  "captured_at": "ISO-8601 UTC",
  "published_at": "ISO-8601 UTC | null",
  "title": "string",
  "text": "string (may equal title)",
  "url": "string | null",
  "publisher": "string | null",
  "hint_ticker": "string | null",
  "user_sentiment_tag": "Bullish | Bearish | null"
}
```

### 5.2 `RiskSignal`
```json
{
  "signal_id": "uuid",
  "doc_id": "string",
  "company": "Apple Inc. | MARKET | UNRESOLVED",
  "ticker": "AAPL | null",
  "issuer_id": "string | null",
  "sector": "string | null",
  "country": "string | null",
  "source": "string",
  "source_type": "news | social",
  "provenance": "LIVE | CACHED_REAL | SYNTHETIC",
  "timestamp": "ISO-8601 UTC",
  "text_excerpt": "≤ 280 chars",
  "sentiment_score": -0.81,
  "sentiment_label": "Negative | Neutral | Positive",
  "sentiment_probs": {"positive": 0.04, "negative": 0.85, "neutral": 0.11},
  "event_type": "Credit Event",
  "secondary_event_type": "Regulatory | null",
  "event_evidence": ["downgrade", "investigation"],
  "impact_score": 8.0,
  "impact_factors": {"E": 0.90, "M": 0.81, "X": 0.60, "R": 0.85, "Q": 0.94},
  "risk_level": "Low | Medium | High | Critical",
  "confidence": 0.85,
  "corroborating_sources": 2,
  "model": "finbert | lexicon-fallback",
  "reason": "Human-readable one-sentence explanation generated from the factors",
  "business_implication": "One sentence, template-generated, e.g. 'Credit deterioration at a held issuer; expect spread widening on its bonds and higher loan PD.'"
}
```
Validate with Pydantic. Reject malformed input with HTTP 422 and a clear message.

---

## 6. NLP ENGINE SPECIFICATION

### 6.1 Entity resolution (`resolver.py`)
Order: (1) cashtag regex `\$[A-Z]{1,5}(\.[A-Z])?` → (2) alias dictionary from `universe.yaml` (case-insensitive, word-boundary) → (3) spaCy ORG entities → (4) rapidfuzz `token_set_ratio ≥ 88` against names/aliases → (5) if event is Geopolitical/Macroeconomic → `MARKET`; else `UNRESOLVED`.
- Ambiguous aliases (e.g., "Apple", "Shell", "Amazon") MUST require a context keyword (stock, shares, company, CEO, earnings, supplier, Inc, etc.) or a ticker hint.
- Detect relation patterns: "`<X>` supplier", "`<X>`'s supplier" → `relation: supplier`.
- `universe.yaml`: ~25 issuers = ~15 US large caps (S&P 100) + ~6 Indian corporates + 2–3 sovereigns/banks, each with name, ticker, aliases, sector, country, rating bucket.

### 6.2 Sentiment (`finbert.py`)
- Model: `ProsusAI/finbert`. Load once (singleton). Read label order from `model.config.id2label` — do NOT hard-code index order.
- `s = P(positive) − P(negative)`, rounded to 3 dp. `confidence = max(probs)`.
- Labels: `s ≤ -0.25` Negative, `s ≥ 0.25` Positive, else Neutral (thresholds in config).
- Long text: split into sentences (max 8), score each, aggregate with confidence-weighted mean; title weight 2×. Truncate to 256 tokens.
- Batch inference for lists.
- Fallback `lexicon_fallback.py`: small curated finance keyword lexicon with negation handling ("not", "no", "fails to" within 3 tokens). `model="lexicon-fallback"`, confidence capped at 0.5. Fallback activates automatically if the model fails to load, and `/health` reports it.

### 6.3 Event classification (`rules.py`, `taxonomy.yaml`)
Taxonomy (exact names): Geopolitical, Macroeconomic, Credit Event, M&A, Product Launch, Regulatory, Earnings, Supply Chain, Litigation, Management, Other.
- Each class: weighted keyword/phrase patterns (regex, word-boundary), e.g. Credit Event: downgrade(3), default(3), bankruptcy(3), missed payment(3), rating cut(3), credit watch negative(2), debt restructuring(2), covenant breach(2).
- Score = sum of matched weights. Primary = argmax; if all zero → Other.
- Secondary = second-highest if ≥ 60% of primary score.
- Return `event_evidence` = matched phrases.
- Intensifiers (separate list): up (+0.10 to +0.15): default, bankruptcy, invasion, war, sanctions, collapse, fraud, halt; down (−0.10): rumour, considering, may, could, reportedly, talks.
- `zero_shot.py`: optional, behind `ENABLE_ZERO_SHOT=false` by default. Only use as tie-breaker when rule scores tie or all zero. Enable by default ONLY if `scripts/evaluate.py` shows it improves macro-F1 on our eval set.

### 6.4 Impact score (`scorer.py`, `weights.yaml`) — exact formula
```
Impact = clip(1 + 9 × Q × (wE·E + wM·M + wX·X + wR·R), 1, 10), rounded to 1 dp
wE=0.40, wM=0.25, wX=0.20, wR=0.15   (in weights.yaml)
```
- **E (event severity)** base: Credit Event 0.90, Geopolitical 0.85, Macroeconomic 0.75, Regulatory 0.70, Litigation 0.60, M&A 0.60, Supply Chain 0.60, Earnings 0.55, Management 0.45, Product Launch 0.30, Other 0.20; plus intensifier adjustment; clip [0,1].
- **M (sentiment magnitude)** = |s| × (1.0 if s < 0 else 0.6).
- **X (exposure/breadth)** = MARKET → 1.0; held issuer → 0.4 + 0.6 × (issuer exposure / max issuer exposure); non-held resolved → 0.3; UNRESOLVED → 0.1.
- **R (credibility)** = source prior (finnhub 0.85, google_news 0.85, gdelt 0.75, reddit 0.40, stocktwits 0.40, manual 0.60, scenario = prior of the source it imitates) + 0.10 per additional corroborating distinct source, cap 1.0.
- **Q (confidence shrinkage)** = 0.6 + 0.4 × confidence.
- Risk level: <4 Low, 4–6.9 Medium, 7–8.4 High, ≥8.5 Critical.
- `reason` is generated from the top two contributing factors. All weights live in YAML; never in code.
- Document clearly: weights are expert-set priors, NOT learned/calibrated.

---

## 7. STORE, BUS, API

### 7.1 SQLite tables
`documents`, `signals`, `stress_runs`, `stress_results` (per asset), `source_health`. Index `signals(ticker, timestamp)`, `signals(event_type)`. DB path from config.

### 7.2 Bus
`bus.py`: in-process async pub/sub with topics `signal.created`, `stress.completed`. Stress engine subscribes to `signal.created`.

### 7.3 Endpoints
| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | status, model loaded/fallback, DB ok, mode, per-source health |
| POST | `/analyze` | analyse one text (body: source, timestamp?, text, company?, ticker?) → RiskSignal; stored; published |
| POST | `/analyze/batch` | list → list (max 100) |
| GET | `/signals` | filters: ticker, event_type, min_impact, provenance, since_id, limit (default 50, max 500) |
| GET | `/signals/{ticker}` | signals for one ticker + aggregate (mean sentiment, max impact) |
| GET | `/signals/stream` | Server-Sent Events of new signals |
| GET | `/signals/export.jsonl` | machine-readable export |
| GET | `/portfolio` | positions + summary |
| GET | `/portfolio/stress-test` | latest stress run result |
| POST | `/portfolio/stress-test` | run a named scenario or custom shock vector manually |
| GET | `/stress-runs` | audit log: run_id, trigger signal_id, scenario, loss |
| POST | `/demo/start` | start scripted demo story (REPLAY/SCENARIO) |
| POST | `/demo/reset` | clear demo signals/runs |

Swagger at `/docs` MUST show examples for every endpoint.

---

## 8. MODULE B — STRESS ENGINE SPECIFICATION

### 8.1 Portfolio
- If `{{TRANSACTION_DATA_PATH}}` exists: write `loader.py` mapping its columns to our schema; document every assumption in `docs/methodology.md`. Show "Source: provided sample data" in UI.
- Else: `generate_portfolio.py` with fixed seed 42 producing 40–60 positions, labelled SYNTHETIC.
- Columns: asset_id, asset_type (Loan, Bond, IRS, CDS, FXForward, Equity), issuer_id, issuer_name, sector, country, rating_bucket (AAA-AA, A, BBB, BB, B-or-below), currency, notional, market_value, mod_duration, convexity, spread_duration, is_floating, pd_1y, lgd, dv01, side (pay_fixed/receive_fixed/protection_bought/long/short), beta.
- Target mix by market value: loans ~40%, bonds ~35%, derivatives (IRS/CDS/FX) as notional-based overlays, equity ≤10%. Include at least 2 CDS protection-bought hedges on held issuers.

### 8.2 Pricers (`pricers.py`) — simplified, documented
- Bond: ΔV = MV × (−D·Δy + ½·C·Δy²), Δy = Δrate + Δspread[rating_bucket] (decimal).
- Loan: ΔV = −EAD × LGD × (PD_stressed − PD_base), PD_stressed = min(PD_base × multiplier[rating_bucket], 1). Fixed-rate loans also get rate effect via duration; floating ≈ 0 rate effect.
- IRS: ΔV = −DV01 × Δrate_bp for pay_fixed... sign convention MUST be documented and unit-tested (pay-fixed gains when rates rise).
- CDS protection bought: ΔV = + notional × spread_duration × Δspread (gains when spreads widen).
- FX forward: ΔV = notional × FX shock × direction.
- Equity: ΔV = MV × equity_shock × beta.

### 8.3 Scenarios (`scenarios.yaml`) — starting values, ILLUSTRATIVE, each with a one-line rationale
| Scenario | Δrates (bp) | IG Δspread (bp) | HY Δspread (bp) | Equity | EM FX | PD × |
|---|---|---|---|---|---|---|
| geopolitical_severe | −25 | +100 | +300 | −12% | −5% | 1.5 |
| geopolitical_moderate | −10 | +50 | +150 | −6% | −2.5% | 1.2 |
| macro_rate_shock_severe | +200 | +75 | +250 | −10% | −3% | 1.3 |
| macro_rate_shock_moderate | +100 | +40 | +120 | −5% | −1.5% | 1.15 |
| systemic_credit_severe | 0 | +150 | +500 | −8% | −2% | 2.0 |
| idiosyncratic_credit (issuer only) | 0 | issuer +300 | issuer +600 | issuer −25% | 0 | issuer 3.0 |
Rating-bucket spread scaling: AAA-AA 0.5×IG, A 0.8×IG, BBB 1.0×IG, BB 1.0×HY, B-or-below 1.3×HY.

### 8.4 Triggers (`triggers.py`, thresholds in config)
- **Systemic:** primary event ∈ {Geopolitical, Macroeconomic, Credit Event} with entity MARKET (or ≥2 corroborating sources) AND impact ≥ 7.0 → moderate if < 8.5, severe if ≥ 8.5.
- **Idiosyncratic:** primary event ∈ {Credit Event, Regulatory, Litigation} on a HELD issuer AND impact ≥ 6.0 → idiosyncratic_credit for that issuer only.
- Cooldown: same scenario + same issuer not re-triggered within 30 min (configurable) — log suppressed triggers.
- Every run stores the triggering signal_id (audit trail).

### 8.5 Outputs
Before/after value, absolute and % loss, loss by asset class / sector / issuer / country, top-10 contributing positions, hedge offset (sum of positive ΔV), sector and issuer HHI before stress, RAG vs risk-appetite limit (`RISK_APPETITE_LOSS_PCT`, default 2.0: green <1%, amber 1–2%, red >2%).
**Sanity test:** severe scenarios MUST produce total loss between 0.5% and 15% of portfolio MV on the default portfolio; fail the test otherwise and recalibrate (document).

---

## 9. DASHBOARD SPECIFICATION (Streamlit + Plotly)

Pages/sections (all required):
1. Executive Risk Overview — KPI cards: signals today, critical count, latest portfolio RAG, worst event, mode badge.
2. News/Social Feed — table with provenance badge, source, time, entity, excerpt.
3. NLP Risk Signals — sortable table, colour by risk level.
4. Sentiment Trend — per ticker over time.
5. Event Distribution — bar chart by event_type.
6. Impact Score — distribution + top-10 signals.
7. Portfolio Overview — composition by asset class/sector/rating.
8. Stress Trigger — alert banner showing trigger signal + scenario + rule that fired.
9. Before vs After — waterfall chart.
10. Asset-Level Loss — top-10 bar chart, hedges shown in green.
11. Risk Heatmap — sector × asset class loss.
12. Explainability — select a signal: text → sentiment probs → event + evidence phrases → impact factor bar (weighted contributions) → final score → business implication.

Plus: **"Analyse your own headline"** text box (calls `/analyze`, shows full explainability), **source health panel**, **mode switch** (LIVE / REPLAY / SCENARIO), and the simplified-model disclaimer on every stress view.
Design: clean, consistent colour scale (Low green, Medium amber, High orange, Critical red), no animations, readable on a projector (large fonts on KPI cards). Dashboard talks to the API via `api_client.py`; if the API is unreachable show a clear error, not a stack trace.

---

## 10. DEMO MODE

`data/scenarios/demo_story.json` (SYNTHETIC, labelled) — deterministic sequence, ~10 s apart:
1. Low-risk: positive product launch for a held US issuer → low impact, no trigger.
2. Negative company event: credit downgrade + regulatory probe at a held issuer → idiosyncratic trigger.
3. High-impact geopolitical event (MARKET), corroborated by 2 sources → systemic severe stress.
Plus a REPLAY mode using `data/cache/` real captured articles (`scripts/capture_cache.py` saves them with capture timestamps).
`scripts/run_demo.py` starts API + dashboard, resets demo state, and runs the story. Same seed → same outputs every time.

---

## 11. TESTING (pytest; all MUST pass; no network in unit tests — mock httpx)

Required cases: positive news, negative news, neutral news, geopolitical, credit event, M&A, regulatory, high-impact, low-impact, unknown company → UNRESOLVED, malformed input → 422, source API failure → fallback without crash, empty text → 422, duplicate article → deduped. Plus: impact score bounded [1,10] and monotonic in each factor; FinBERT label mapping uses `id2label`; IRS/CDS sign conventions; stress loss sanity band; trigger cooldown; entity ambiguity ("apple pie recipe" must NOT resolve to AAPL).
Mark FinBERT-dependent tests `@pytest.mark.model` so a fast suite runs without the model.

---

## 12. EVALUATION (honest metrics)

- `data/eval/labelled_headlines.csv`: ~150 headlines I will help label (columns: text, source_type, gold_sentiment, gold_event, gold_ticker). You draft candidates from cached real data; I confirm labels. Never auto-label with the model being evaluated.
- `scripts/evaluate.py` prints: sentiment accuracy + macro-F1, event accuracy + macro-F1 + confusion matrix, entity resolution accuracy; writes `docs/evaluation.md`.
- Optional: FinBERT agreement with StockTwits user Bullish/Bearish tags (report n and agreement; state it is a weak label).
- `scripts/benchmark_latency.py`: median/p95 per-document latency on my laptop.
- Only these outputs may appear as numbers in README/slides.

---

## 13. MILESTONES AND STOP GATES

After each milestone, respond with exactly: **(a)** files created/changed, **(b)** how to run, **(c)** expected output, **(d)** how to test, **(e)** known issues/risks, **(f)** "GATE: awaiting confirmation". Then STOP.

| # | Milestone | Acceptance criteria |
|---|---|---|
| M0 | Skeleton, config, schemas, logging, `probe_sources.py`, `setup_models.py` | `pip install -r requirements.txt` works; probe prints PASS/FAIL table per source; schemas validate sample JSON |
| M1 | Ingestion adapters, dedup, cache capture, replay, scheduler | Each adapter returns `RawDocument`s or a logged fallback; replay streams cached docs with CACHED_REAL |
| M2 | Entity resolver, FinBERT + fallback, event rules | Unit tests pass; CLI `python -m risk_engine.pipeline "text"` prints a full RiskSignal |
| M3 | Impact scorer, corroboration, store, bus, FastAPI + SSE | All endpoints work in Swagger; signals persist; SSE emits |
| M4 | Portfolio, pricers, scenarios, triggers, stress engine | Thin end-to-end slice: headline → signal → trigger → stress result via API; sanity test passes |
| M5 | Dashboard (all 12 sections + headline box + health panel) | Runs against API; every chart populated in SCENARIO mode |
| M6 | Demo story, run_demo, full test suite, failure drills | `run_demo.py` works offline; all tests green; killing a source mid-run shows fallback |
| M7 | Evaluation, docs, README, slides outline, demo script, judge Q&A | Metrics generated by scripts; README quickstart verified from clean clone |
| M8 | DoSelect final answer + final submission pack (section 16) | Quality check passes; answer pastes cleanly into the rich-text box; only link placeholders remain until I supply the links |

---

## 14. DOCUMENTATION DELIVERABLES (M7)

- **README.md:** title, one-line value proposition, problem, solution, architecture diagram, features, tech stack, data sources (with provenance policy), NLP methodology, impact formula, Module B, screenshot placeholders, install, env vars, run locally, API examples (curl), demo instructions, testing, measured results (from scripts only), limitations, future work, responsible-AI disclaimer.
- **docs/slides_outline.md:** EXACTLY 7 slides — (1) title + problem + one-line solution, (2) business context, (3) architecture, (4) NLP risk engine, (5) stress testing, (6) results + dashboard + business impact, (7) innovation + limitations + future scope + takeaway. For each: title, ≤5 bullets, recommended visual, what NOT to include, speaker notes.
- **docs/demo_script.md:** 5:00 timed script (0:00 problem · 0:30 architecture · 1:15 ingestion + NLP · 2:15 signal + explainability · 3:15 stress test · 4:30 impact + close) as a story, plus a backup plan if network/API fails.
- **docs/judge_qa.md:** ≥25 questions across technical, NLP, finance, architecture, data, impact score, accuracy, real-time, scalability, explainability, business value, security, false positives/negatives, limitations — concise honest answers, with weakness-exposing questions flagged.
- **Final audit table:** requirement · implemented? · where · how demonstrated · potential issue · fix — and harsh scores /100 for technical quality, NLP, financial reasoning, business relevance, innovation, UI/UX, reliability, presentation, demo, overall.

---

## 16. DOSELECT FINAL ANSWER SUBMISSION (M8)

The assessment has a rich-text "Answer" box (toolbar: headings, bold, italic, lists, quote, code, superscript, colours). The project is NOT complete until you produce the exact content I paste there.

### 16.1 Files to produce
- `docs/submission/doselect_answer.md` — the source text.
- `docs/submission/doselect_answer.html` — the same content as simple HTML (`<h2>`, `<h3>`, `<p>`, `<ul>`, `<li>`, `<strong>`, `<a>` only; no CSS, no scripts). I open it in a browser, select all, copy and paste, so headings and bullets survive. Pasting raw Markdown would show literal `#` and `*` characters, so the HTML version is the one to paste.
- `scripts/build_submission.py` — renders the HTML from the Markdown, then runs the quality check in 16.4 and prints PASS/FAIL per item.

### 16.2 Required sections, in this order
1. **Project title**
2. **Executive summary** (≤80 words): the problem, what we built, why it matters.
3. **Solution overview:** the AI/NLP risk engine; ingestion from ≥2 sources; sentiment score; event classification; impact score 1–10; structured output (API + JSONL + SSE).
4. **Downstream module:** state explicitly "Module B: Strategic Portfolio Stress Testing was implemented." Say how it subscribes to event type + impact score, the trigger rules, and the business use case.
5. **Technical architecture:** one line, Data sources → ingestion → NLP → risk signals → store/API → stress engine → dashboard; then ≤5 bullets.
6. **AI/NLP methodology:** FinBERT with s = P(pos) − P(neg); rule-based event classification with evidence phrases (and zero-shot only if it was enabled after evaluation); entity resolution steps; the impact formula with its factors in one line; explainability.
7. **Data sources:** list ONLY the sources that passed `probe_sources.py` and were actually used. Include a provenance table with four rows: real live, real cached (with capture date), synthetic (demo story, portfolio if generated), simulated (stress scenarios).
8. **Key features:** ≤7 bullets, the strongest only.
9. **Results:** copy numbers ONLY from `docs/evaluation.md` and `benchmark_latency.py` output, each with its sample size (n). Any metric not measured MUST be stated as "not measured". No accuracy, returns, alpha or benchmark claims beyond that. The stress loss shown is a simulated output of the illustrative model and MUST be labelled so.
10. **Business impact:** how it helps risk teams, credit analysts, portfolio managers. Must state: "This prototype is a decision-support tool, not investment advice."
11. **Limitations:** ≥5 honest bullets, at least covering: impact weights are expert priors, not calibrated; the stress model is simplified and illustrative; social sources are unofficial and best-effort; headline-only text from Google News; the small labelled evaluation set.
12. **Future scope:** production streaming ingestion (Kafka); calibrating impact against market reactions; more and licensed datasets; historical backtesting; production-grade risk models (full revaluation, correlated scenarios); scalability, security and access control.
13. **Deliverables:** exactly these three lines:
    - GitHub repository: [GITHUB REPOSITORY LINK]
    - Live demonstration: [LIVE DEMO LINK]
    - Presentation (7 slides): [PRESENTATION LINK]

### 16.3 Formatting and content rules
- Target 700–1,100 words. Short paragraphs, bullets, clean headings. Do NOT wrap the answer in a code block.
- No code, no internal development discussion, no "we will" for features that are not built, no invented URLs.
- The ONLY placeholders allowed are the three link placeholders in 16.2 item 13. When I give you the real links, replace them, re-run `build_submission.py`, and confirm zero placeholders remain. Do not tell me the answer is ready to submit while any placeholder remains.
- Every feature named in the answer MUST exist in the repo and be visible in the demo.

### 16.4 Quality check (all must pass; `build_submission.py` checks the mechanical items, you check the rest and report)
- [ ] ≥2 data sources addressed, and they match the probe results
- [ ] NLP risk engine, sentiment score, event classification, impact score 1–10 present
- [ ] Structured machine-readable output present
- [ ] Downstream module named and explained
- [ ] Dashboard addressed
- [ ] GitHub, live demo and 7-slide presentation addressed
- [ ] Every number traces to a script output; nothing fabricated
- [ ] No fabricated links; only the three allowed placeholders (or none, after links are supplied)
- [ ] Synthetic, cached and simulated data clearly identified
- [ ] Business value explained; "not investment advice" present
- [ ] Limitations honestly stated

### 16.5 Final output of M8
Present, in this order:
- **A. FINAL DOSELECT ANSWER**: the exact text for the Answer box, plus the path to the HTML file to copy from.
- **B. GITHUB README**: confirm `README.md` is final and consistent with the answer (same numbers, same source list). Don't reprint it.
- **C. 7-SLIDE PRESENTATION CONTENT**: point to `docs/slides_outline.md`, updated with final measured results.
- **D. 5-MINUTE DEMO SCRIPT**: point to `docs/demo_script.md`.
- **E. JUDGE Q&A**: point to `docs/judge_qa.md`.
- The quality-check table with PASS/FAIL per item.

If any item fails, fix it before presenting, or report it as a blocker. Never present a failing answer as final.

---

## 17. DEFINITION OF DONE

- [ ] Fresh clone → `make setup && make demo` works on my laptop, offline after setup.
- [ ] All tests pass; coverage report generated.
- [ ] Every signal shows provenance; no unlabelled synthetic or cached data anywhere.
- [ ] Every number in README/slides traces to a script output.
- [ ] Stress views carry the simplified-model disclaimer.
- [ ] No secrets in git history; `.env.example` complete.
- [ ] Demo rehearsed end-to-end in ≤ 5 minutes, both live and backup paths.
- [ ] DoSelect answer passes the section 16 quality check, with real links filled in and zero placeholders left.
