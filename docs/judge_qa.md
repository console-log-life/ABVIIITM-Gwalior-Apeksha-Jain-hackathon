# Judge Q&A prep

⚠️ marks a question that exposes a real weakness. Answer it plainly; don't spin it.

## Technical / architecture

1. **Why one pipeline for live, replay and demo?**
   So the demo can't cheat. The scripted story goes through exactly the code that live data does
   (`risk_engine.pipeline`), which is enforced by design.
2. **How does a signal reach the stress engine?**
   An in-process async bus publishes `signal.created`. The stress engine subscribes, evaluates the trigger rules,
   runs, stores the result with the trigger `signal_id`, and publishes `stress.completed`.
3. **What happens when a source dies?**
   The source gets a timeout of ≤ 10 s and at most 2 retries; HTTP 429 and 403 park it in backoff. It is marked
   DEGRADED, then DOWN after 3 failures, and the other sources keep flowing. This is tested in
   `tests/test_failure_drills.py` and in the process-level drill (7/7).
4. **⚠️ Does it scale?**
   Not as built: it's a single process with SQLite and an in-process bus. The path is Kafka or Redis Streams,
   Postgres, separate adapter workers and a batched inference server. The interfaces (bus topics, the RiskSignal
   schema) are already message-shaped.
5. **How is it consumed downstream?**
   Through REST, Server-Sent Events, a JSONL export and the SQLite tables. Swagger has examples for every endpoint.

## NLP

6. **Why FinBERT?**
   It's a finance-domain model that runs on a CPU and offline. Labels are read from `id2label` (positive, negative,
   neutral on this model) rather than by index position.
7. **⚠️ Your lexicon beat FinBERT in your own eval?**
   On 147 AI-drafted labels, yes: 0.68 versus 0.653 accuracy. But the same assistant wrote the lexicon and the
   labels, so that's shared bias, not evidence. FinBERT stays the primary model, and human review of the labels is
   the next step.
8. **Why rules for event classification, not a classifier?**
   Rules give transparent evidence phrases and need no training data. We tested a zero-shot tie-breaker and it
   lowered macro-F1 (0.795 → 0.78), so it's off.
9. **⚠️ False positives?**
   Yes, and we measured them. Replaying all 911 real documents in our local capture cache produced 84 stress runs. Misfires included
   "The war on data centres" (read as Geopolitical), a fund newsletter and a Cyprus fund story from Mastodon (read as
   market-wide macro), and "SEC" resolving to the Government of India.

   We fixed these with regression tests: news-only systemic triggers (social posts only corroborate), ≥ 2 distinct
   cues before a market-wide call can start systemic stress, figurative-"war" guards, a stricter fuzzy entity match,
   negative sentiment (≤ −0.25) for issuer-only stress, an analyst-"verdict" guard, and rate direction (cuts run a
   separate rate-cut scenario). The same replay now gives 50 runs (`docs/trigger_replay.md`).

   The cost: some genuine single-cue market stories, like "RBI repo rate could head towards 6.5%", no longer start
   systemic stress. Classification itself is unchanged (event accuracy 0.81). Regulatory settlement headlines can
   still fire issuer-only stress.
10. **⚠️ False negatives?**
    Supply-chain stories are untested: our sample had no examples. Headline-only text misses events buried in
    article bodies.
11. **How do you resolve ambiguous names like Apple?**
    Ambiguous aliases must be capitalised and need a context keyword or ticker hint. "Apple pie recipe" does not
    resolve, and that's a unit test.

## Impact score

12. **Where do the weights come from?**
    They are expert priors (E 0.40, M 0.25, X 0.20, R 0.15), held in YAML and exposed at `/methodology`. They are
    not calibrated.
13. **⚠️ Why does positive news increase impact?**
    The score measures materiality, i.e. how much a story deserves attention. Positive news about a big holding is
    material, but down-weighted (M = 0.6 × |s|). A pure downside score is a one-line weight change; calibration
    should decide.
14. **What is corroboration?**
    The same entity and event from ≥ 2 distinct sources within 6 h. It raises R and can fire the systemic trigger.
    MARKET signals also need a shared evidence phrase.

## Finance / Module B

15. **Is this a real risk model?**
    No. It is a simplified, illustrative hackathon stress model: no correlations, no full revaluation, and no FX
    translation of INR holdings.
16. **Why these scenario values?**
    They are the spec's illustrative starting values, each with a one-line rationale in `scenarios.yaml`. Severe
    scenarios land at 2.45–8.06% loss, inside our 0.5–15% sanity band.
17. **Sign conventions?**
    Pay-fixed IRS gains when rates rise; bought CDS protection gains when spreads widen. Both are unit-tested. (The
    original spec had a sign typo here, which we corrected and documented.)
18. **⚠️ Is the portfolio real?**
    No. It's synthetic, generated with seed 42 because no transaction data was provided, and labelled SYNTHETIC
    everywhere.
19. **Why did the Tata Motors downgrade only lose 0.41%?**
    It's an issuer-only shock on a diversified book, and the CDS hedge on Tata Motors offsets part of it. The waterfall
    shows the CDS gain in green.

20. **What is the Early Warning Watchlist? Isn't it just a rating?**
    No. It is a rules-based attention flag per held issuer, not a rating or a PD. Within the last 24 h, an
    issuer is WATCH-NEGATIVE if one negative signal (sentiment ≤ −0.25) has impact ≥ 7, or two have impact ≥ 5;
    MONITOR if one has impact ≥ 4; otherwise STABLE. Thresholds are in config and documented. Each row shows
    the rule that fired, exposure, rating bucket and the top three signals with reasons, and links to the
    explanation. The thresholds are expert-set; we have not backtested them against rating actions.

## Data

21. **Is the data real-time?**
    In LIVE mode, yes. The demo uses SYNTHETIC headlines and REPLAY uses CACHED_REAL captures, and every record shows
    which it is. We never present cached data as live.
22. **⚠️ Why no Twitter / StockTwits?**
    X has had no free API tier since Feb 2026. StockTwits returns HTTP 403 on our network, so the adapter exists but
    skips cleanly.
23. **Privacy?**
    Author handles are never stored. The full capture cache, including social posts, is git-ignored and was
    never published. The repository ships only 50 Google News headlines for REPLAY.

## Accuracy / evaluation

24. **⚠️ How accurate is it?**
    PRELIMINARY on n = 147 real headlines with AI-drafted labels: sentiment 0.653, events 0.81, entities 0.898. It's
    a small set, labelled by one annotator with same-author bias. Not a benchmark.
25. **Did you measure trading performance?**
    No, and we make no return or alpha claims.

## Real-time / performance

26. **How fast is it?**
    On a CPU laptop: median 204.7 ms and p95 1085.2 ms per document over n = 200 real documents; 278.9 ms per
    document batched. The model loads in about 6 s.

## Explainability / business

27. **Can an analyst see why a score is high?**
    Yes: sentiment probabilities, evidence phrases, the weighted factor bar, the formula with the actual numbers, a
    reason sentence and a business implication.
28. **What's the business value?**
    Faster triage and prioritisation by materiality, plus an immediate portfolio view with an audit trail. It's a
    decision-support tool, not investment advice.

## Security

29. **⚠️ Security?**
    It's a prototype: no authentication on the API, local only. Secrets come from `.env`, which is git-ignored, and
    API keys are sent in headers, never URLs. Authentication and role-based access are future work.
