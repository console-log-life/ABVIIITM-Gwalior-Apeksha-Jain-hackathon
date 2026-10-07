# 5-minute demo script

**Before you start (T−10 min):**
1. `powershell -ExecutionPolicy Bypass -File tasks.ps1 preflight` → GO (the REAL history cache must be fresh; if not,
   run `tasks.ps1 real-history` first, ~7 min).
2. `powershell -ExecutionPolicy Bypass -File tasks.ps1 demo-offline`. Wait for "ready on REAL data" and leave it
   running.
3. Open <http://127.0.0.1:8501>. Browser zoom 110–125% for the projector. Auto-refresh (sidebar) **on** before 2:30.

What is real: everything until 2:30 is CACHED_REAL (real captured news, badged with capture time); the portfolio and
all stress results are SYNTHETIC / simulated. The Tata Motors and invasion headlines are SYNTHETIC.

| Time | Screen | What you say / do |
|---|---|---|
| **0:00 – 0:45** Real data | Home | "This is 1,325 real headlines and posts we captured, run through our pipeline: in the last 24 hours of that news, 326 signals and 18 of our 23 held issuers need a look; 7 are WATCH-NEGATIVE. Every row says LIVE, CACHED_REAL or SYNTHETIC." Drag the **time machine** back a day: "the same dashboard a day earlier, replayed by publication time"; click **Latest**. Point at the latest stress run: "this RED rate-shock run came from an opinion piece about a past hike; a false positive we show rather than hide." |
| **0:45 – 1:45** Watchlist → why | Early Warning Watchlist, then **Explain →** | "The credit analyst's view: HDFC Bank is WATCH-NEGATIVE, worst impact 8.1, sentiment −0.95; the rule that fired is in the row; the sparkline is impact over 24 hours with a 6-hour rolling max." Click **Explain →**: "FinBERT probabilities, the evidence words, the weighted factors and the formula with the actual numbers." |
| **1:45 – 2:30** Contagion | Risk Propagation (HDFC Bank) | "What else in the book is connected? Direct exposure versus propagated exposure over hand-curated links (HDFC's peer SBI). Node size is exposure, colour is watch status; click a node to see its positions. The links are curated, not inferred, and the weights are attention weights, not default correlations." |
| **2:30 – 3:45** Stress climax | sidebar **▶ Scenario demo**, then Watchlist and Stress Test | "Now a scripted, SYNTHETIC story." Tata Motors downgrade (8.7) → Stress: "issuer-only shock, 0.41% GREEN; our CDS hedge offsets most of it." The story pauses 20 s → Watchlist: "Tata Motors WATCH-NEGATIVE, and its peers Ford and Tesla are flagged by propagation." Invasion headline → "moderate geopolitical, 1.32% AMBER"; second source → "corroborated: severe, 2.45% RED, above our 2% appetite." Show the waterfall and the audit log. Read the disclaimer. |
| **3:45 – 4:20** What-if | Stress Test → What-if builder | "Your shock: start from geopolitical severe and widen high-yield spreads." Let a judge pick; the comparison with the triggered run updates instantly; nothing is saved. |
| **4:20 – 5:00** Brief + close | Watchlist → Tata Motors → **Credit brief** → Download PDF | "One click: a one-page brief from templates, no language model; every sentence comes from stored data." Close: "Real news to an explainable portfolio view in seconds, every record labelled. Decision support, not investment advice." |

## Backup plan

| Failure | Fallback |
|---|---|
| No internet / venue Wi-Fi down | Nothing to do: `tasks.ps1 demo-offline` needs no network (verified by `src/scripts/failure_drill.py`). |
| REAL history still building at start | The sidebar shows the progress; start the **Scenario demo** first (it is independent), then return to the real-data part. |
| Live sources failing | Expected and fine: Source Health shows them DEGRADED/BACKOFF while the app keeps running. |
| FinBERT won't load | The sidebar badge shows the lexicon fallback and /health says why. Continue; scores are confidence-capped. |
| API or dashboard crashes | Rerun `tasks.ps1 demo-offline` (the cached history loads in seconds). Meanwhile show `docs/screenshots/1920x1080/`. |
| Laptop dies | Present from the slides, then play `docs/demo/demo_walkthrough.webm` (silent backup recording) from another machine. |
| Time overrun | Skip the time-machine drag (15 s) and the what-if (35 s). |
