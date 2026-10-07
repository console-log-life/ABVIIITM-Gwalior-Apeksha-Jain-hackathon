# Jury cheatsheet (one page)

## Key numbers (all from scripts in this repository)

| | | |
|---|---|---|
| Sentiment accuracy (FinBERT) | **0.653** | n = 147, labels preliminary (AI-drafted) |
| Event accuracy (rules) / entity accuracy | **0.81 / 0.898** | n = 147 |
| Median / p95 latency per document | **204.7 / 1085.2 ms** | n = 200, CPU laptop |
| Simulated stress runs on real captured news, before → after false-trigger fixes | **84 → 50** | n = 911 documents |
| Scenario demo (simulated, synthetic portfolio) | **0.41% GREEN → 1.32% AMBER → 2.45% RED** | appetite 2% |
| REAL history | **1,325** documents → 54 simulated runs | captured 3–5 Oct 2026 |
| Impact weights | **E 0.40 · M 0.25 · X 0.20 · R 0.15** | expert priors, not calibrated |
| Tests | **275** (270 fast + 5 FinBERT), 93% coverage | API 87/87, dashboard 55/55 |
| int8 quantisation | **off**: 0.605 vs 0.653 | n = 147 |

## 10 likely questions

1. **Is the data real?** Pages before the scenario show 1,325 real captured headlines and posts (CACHED_REAL, with
   capture time). The Tata Motors / invasion story and the portfolio are SYNTHETIC, labelled everywhere.
2. **How accurate is it?** Preliminary, n = 147: sentiment 0.653, events 0.81, entities 0.898. The labels were drafted
   by an AI assistant and are pending human review, so it is a smoke test, not a benchmark.
3. **Why FinBERT and rules?** FinBERT is finance-specific and runs offline on a CPU. Rules give evidence phrases and
   need no training data; a zero-shot tie-breaker lowered macro-F1 (0.795 → 0.78), so it is off.
4. **False positives?** Measured: replaying 911 real documents gave 84 stress runs; regression-tested fixes (news-only
   systemic triggers, two cues, figurative-"war" guards) cut that to 50. Some real single-cue stories no longer fire.
5. **Where do the impact weights come from?** Expert priors (0.40/0.25/0.20/0.15) in YAML, shown at `/methodology`.
   Calibrating them on market moves is the first item of future work.
6. **Is this a real risk model?** No: a simplified, illustrative stress model, no correlations or full revaluation,
   on a synthetic portfolio (seed 42). Decision support, not investment advice.
7. **Why only 0.41% for a downgrade?** It is an issuer-only shock on a diversified book, and the CDS protection on
   Tata Motors offsets most of it; the waterfall shows the hedge gain.
8. **Is propagation a contagion model?** No. 16 hand-curated public links with decay weights tell an analyst what else
   in the book is connected; no correlations or default probabilities.
9. **Does it scale?** Not as built (one process, SQLite, in-process bus). The path is Kafka/Redis Streams, Postgres
   and separate inference workers; the bus topics and RiskSignal schema are already message-shaped.
10. **Does the credit brief use an LLM?** No. It is a template filled from stored data; every sentence traces to an API
    field.

## If something breaks live

| Problem | Do this |
|---|---|
| Preflight NO-GO | Close the apps it lists (Docker can stay), re-run `tasks.ps1 preflight`. |
| App will not start / crashes | Re-run `tasks.ps1 demo-offline`; meanwhile show `docs/screenshots/1920x1080/`. |
| History still building | Start **▶ Scenario demo** first; return to the real data after. |
| Sources failing / no Wi-Fi | Fine: the demo is offline; Source Health shows the failures. |
| FinBERT fails to load | Continue on the lexicon fallback (sidebar badge says so). |
| Laptop dies | 60-second slides-only pitch (`docs/demo_script.md`), then the YouTube video from another machine. |
