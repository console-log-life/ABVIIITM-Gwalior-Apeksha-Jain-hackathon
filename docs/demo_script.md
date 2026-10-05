# 5-minute demo script

**Before you start (T−10 min):**
1. Run `powershell -ExecutionPolicy Bypass -File tasks.ps1 demo-offline`. It works without a network. Wait for
   "[5/5] done" and leave it running.
2. Open the dashboard at <http://127.0.0.1:8501> and Swagger at <http://127.0.0.1:8000/docs> in two tabs.
3. In the sidebar, click **⟲ Reset**.
4. Leave **Auto-refresh (5 s)** on.

The browser zoom is 125% for the projector.

| Time | Screen | What you say / do |
|---|---|---|
| **0:00 – 0:30** Problem | Home (empty) | "Risk shows up in text first: a downgrade on a wire, a sanctions headline, a probe. Analysts read it, then someone runs the numbers by hand. We connect the two automatically, and honestly. Everything you'll see is labelled live, cached-real or synthetic." |
| **0:30 – 1:15** Architecture | slide 3, or Swagger `/docs` | "Real sources: Google News, Reddit and Mastodon passed our source probe; GDELT and StockTwits are best-effort. One NLP pipeline serves live polling, replay of captured real data, this scripted demo and the API. Signals go to SQLite and an event bus; the stress engine subscribes to that bus." |
| **1:15 – 2:15** Ingestion + NLP | sidebar **▶ Demo story** → Feed page, then Signals | Step 1 arrives: "Nvidia unveils new GPU lineup", from a social source. "Positive product launch, small holding, low-credibility source: impact 3.6, Low, no trigger." Step 2: "Moody's downgrades Tata Motors to junk as SEBI opens probe". Point out the **SYNTHETIC** badge and the event column. |
| **2:15 – 3:15** Signal + explainability | Explainability → pick the Tata Motors signal | "FinBERT says negative: P(neg) 0.92. The rules found 'downgrades', 'junk', 'Moody's', 'probe', 'SEBI', so Credit Event with Regulatory as secondary. Impact 8.7: event severity and strong negative sentiment dominate, and Tata Motors is a held issuer. The weights are expert priors, shown openly at /methodology." Then the **Analyse your own headline** tab: type a judge's headline live. Typed text is source `manual`, so it shows the full explanation but cannot start a *systemic* stress run (news sources only). |
| **3:15 – 4:30** Stress test | Stress Test page | Banner: **Idiosyncratic credit, Tata Motors, 0.41% GREEN**. "Our CDS hedge offsets most of it; see the green bar." Steps 3 and 4 arrive (invasion headline, then a second independent source). "First source: moderate geopolitical stress, 1.32% AMBER. The second source corroborates, so severity escalates to severe: 2.45% RED, above our 2% risk appetite." Show the waterfall, the top-10 positions (hedges in green), the heatmap and the audit log with the triggering signal id and the suppressed-trigger cooldown. Read the disclaimer. |
| **4:30 – 5:00** Impact + close | Home | "Seconds from headline to portfolio view, every number explained and every record labelled. Preliminary evaluation on 147 real headlines is in the repo, with its caveats. It's decision support, not investment advice. Next steps: calibrate impact against market moves, use licensed full-text news, and stream on Kafka." |

## Backup plan

| Failure | Fallback |
|---|---|
| No internet / venue Wi-Fi down | Nothing to do: `tasks.ps1 demo-offline` needs no network (verified by `scripts/failure_drill.py`, 7/7). |
| Live sources failing | That's expected and fine. Show **Source Health**: sources marked DEGRADED/BACKOFF while the app keeps running. Switch to **REPLAY** for real cached data (CACHED_REAL badges with capture time). |
| FinBERT won't load | The sidebar badge shows `lexicon-fallback` and /health reports why. Continue the demo; scores are confidence-capped. |
| API or dashboard crashes | Rerun `tasks.ps1 demo-offline` (≈ 30 s to ready). Meanwhile show `docs/screenshots/01_home.png … 07_health.png`. |
| Laptop dies | Present from the slides; screenshots are embedded in slides 4–6. |
| Time overrun | Skip the "analyse your own headline" step (saves 30 s). |
