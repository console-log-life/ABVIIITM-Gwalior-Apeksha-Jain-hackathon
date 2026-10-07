## Risk Signal Engine: AI/NLP Financial Risk Signals with Event-Driven Portfolio Stress Testing

### Executive summary

Downgrades, regulatory probes, sanctions and rate shocks surface first in unstructured news and social text, and their portfolio impact is worked out later by hand. We built an NLP risk engine that turns this text into explainable, machine-readable risk signals in real time. A high-impact signal automatically triggers a stress test of a loans, bonds and derivatives portfolio. Risk teams get earlier warning, prioritisation by materiality and an immediate view of portfolio impact.

### Solution overview

- **AI/NLP risk engine:** every news item or social post becomes a structured RiskSignal with provenance, entity, sentiment, event type, impact score, a one-line reason and a business implication.
- **Ingestion from multiple sources:** news (Google News RSS) and social (Reddit RSS, Mastodon), with rate limits, retries, backoff and deduplication.
- **Sentiment score:** a score in [−1, 1] from FinBERT, with class probabilities and confidence.
- **Event classification:** an 11-class taxonomy (from Geopolitical, Macroeconomic and Credit Event to Management and Other), with the evidence phrases behind each class.
- **Impact score from 1 to 10:** a transparent weighted formula, explained factor by factor.
- **Structured output:** REST API with Swagger, a Server-Sent Events stream, JSONL export, SQLite.

### Downstream module

Module B: Strategic Portfolio Stress Testing was implemented. The stress engine subscribes to every new signal on an internal event bus.

- **Systemic trigger:** a Geopolitical, Macroeconomic or Credit Event that is market-wide or confirmed by at least two independent sources, with impact of at least 7.0, reported by a news source; social posts only add corroboration. It runs a moderate scenario, or a severe one from 8.5.
- **Idiosyncratic trigger:** a Credit, Regulatory or Litigation event on a held issuer with impact of at least 6.0 and negative sentiment. It shocks only that issuer's bonds, loans, equity and credit protection.

A cooldown prevents repeated runs and every run stores its triggering signal. Outputs show the value before and after the shock, losses by asset class, sector and issuer, the top-10 positions, hedge offset, concentration and a red/amber/green status against a 2% risk appetite.

**Credit-risk views:** an early warning watchlist gives every held issuer a rules-based status (WATCH-NEGATIVE, MONITOR or STABLE) from its recent signals; risk propagation adds the decay-weighted exposure of 16 hand-curated linked issuers; a what-if builder reprices the book instantly for any shock; and a one-click, template-based credit brief (HTML or PDF) summarises an issuer.

### Technical architecture

Data sources → ingestion → NLP → risk signals → store/API → stress engine → dashboard

- Live polling, replay of captured real data, the scripted demo and direct API calls all pass through one shared NLP pipeline.
- Adapters handle retries, rate limits and source health; a failing source never stops the system.
- Signals are stored in SQLite and published on an in-process event bus; FastAPI serves REST, streaming and export.
- The stress engine is a bus subscriber with simplified pricers for bonds, loans, IRS, CDS, FX forwards and equity.
- A Streamlit dashboard covers all twelve required views and runs offline after setup.

### AI/NLP methodology

- **Sentiment:** FinBERT (ProsusAI/finbert) with s = P(positive) − P(negative). Labels are read from the model configuration; a finance lexicon is the fallback.
- **Event classification:** rule-based with weighted patterns, evidence phrases and intensifiers; a zero-shot tie-breaker lowered macro-F1 and stays off.
- **Entity resolution:** cashtags, aliases with context checks, spaCy entities and guarded fuzzy matching.
- **Impact formula:** Impact = 1 + 9 × Q × (0.40 E + 0.25 M + 0.20 X + 0.15 R), clipped to 1–10. E is event severity, M sentiment magnitude, X portfolio exposure, R source credibility plus corroboration, and Q model confidence.
- **Explainability:** every signal shows probabilities, evidence phrases, weighted factor contributions, a reason and a business implication.

### Data sources

Sources used (each passed our source probe): Google News RSS (news), Reddit subreddit RSS (social), Mastodon hashtag timelines (social).

- **Real, live:** fetched during a session (label: LIVE).
- **Real, cached:** real items captured between 2026-10-03 and 2026-10-05, shown with capture time (label: CACHED_REAL). The dashboard opens on all 1,325 of them, with a time machine that replays them by publication time. The public repository ships only a news-headline sample.
- **Synthetic:** the demo story, user-typed text and the generated portfolio (seed 42, 49 positions), labelled SYNTHETIC.
- **Simulated:** every stress-test result, produced by an illustrative model.

### Key features

- Provenance badge on every record: LIVE, CACHED_REAL or SYNTHETIC.
- One NLP pipeline for live, replay, demo and API input.
- Explainable 1–10 impact score with visible weights.
- Real-data time machine over every captured document.
- Event-driven stress tests with an audit trail and cooldown.
- Watchlist, risk propagation, what-if builder and one-click credit brief.
- Runs offline with graceful fallback when sources fail.

### Results

PRELIMINARY: the gold labels were drafted by an AI assistant and are pending human review. The same assistant wrote the event rules, which likely flatters them.

- Sentiment accuracy (FinBERT, headline text): 0.653, macro-F1 0.648 (n = 147 real headlines).
- Event classification accuracy: 0.81, macro-F1 0.795 (n = 147).
- Entity resolution accuracy: 0.898 (n = 147).
- Replaying 911 locally captured real documents, the false-trigger fixes cut simulated stress runs from 84 to 50 (n = 911).
- Processing latency on a CPU-only laptop: median 204.7 ms and p95 1085.2 ms per document (n = 200).
- Simulated stress output (illustrative model, synthetic portfolio): the severe geopolitical scenario loses 2.45% of portfolio value.
- Agreement with user-tagged social sentiment, and any trading or return impact: not measured.

### Business impact

Risk teams get earlier warning and materiality-based triage; credit analysts see which held names need attention and why; portfolio managers get an immediate, audited view of how an event could move their book. This prototype is a decision-support tool, not investment advice.

### Limitations

- The impact weights are expert priors, not calibrated against market reactions.
- The stress model is simplified and illustrative: no correlations, no full revaluation, and the portfolio is synthetic.
- The social sources are unofficial and best-effort; some candidates were blocked.
- Google News provides headline-only text, so the models see short inputs.
- The labelled evaluation set is small (147 items, AI-drafted labels), and the keyword rules produce some false positives on real data.

### Future scope

- Kafka streaming ingestion.
- Calibrating impact against market reactions.
- Licensed full-text news.
- Backtesting triggers and signals.
- Full revaluation with correlated scenarios.
- Scalability, security and access control.

### Deliverables

This is an individual submission.

- GitHub repository: [GITHUB REPOSITORY LINK]
- Demo video (YouTube, unlisted): [DEMO VIDEO LINK]
- Presentation (7 slides, PDF): [GITHUB REPOSITORY LINK]/blob/main/docs/presentation.pdf
