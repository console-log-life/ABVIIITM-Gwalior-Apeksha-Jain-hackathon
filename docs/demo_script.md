# Demo scripts

Two versions of the same demo:

- **(a) Recorded video, about 6.5 minutes** (YouTube, unlisted), following the submission guideline flow: intro,
  setup from the README commands, walkthrough from data input to output, results.
- **(b) Live jury demo, 5 minutes** (the problem statement caps the live demonstration at 5 minutes).

What is real in both: every page before the scenario shows CACHED_REAL data (real captured news, badged with its
capture time); the Tata Motors and invasion headlines are SYNTHETIC; the portfolio is SYNTHETIC and every stress result
is simulated with an illustrative model.

## (a) Recorded video (~6.5 min)

**Recording setup:** 1920×1080 screen recording (OBS or the Windows Game Bar, `Win+Alt+R`), microphone on, browser
zoom 110%, other apps closed (the demo needs ~2 GB of free RAM). Before recording, run the setup once so the models are
downloaded (the video shows the commands, not the 10-minute download).

| Time | Screen | What you say / do |
|---|---|---|
| **0:00 – 0:30** Intro | Slide 1, then slide 2 of `docs/presentation.pdf` | "Risk Signal Engine turns news and social posts into explainable risk signals and stress-tests a portfolio the moment something material happens. It is an individual submission for Module B, strategic portfolio stress testing. Everything on screen is labelled LIVE, CACHED_REAL or SYNTHETIC." |
| **0:30 – 1:15** Setup from the README | README **Quickstart** on GitHub, then a PowerShell window in the cloned folder | Show the Quickstart section. Run `powershell -ExecutionPolicy Bypass -File tasks.ps1 setup` (already done: it only checks the packages and models, a few seconds), then `tasks.ps1 preflight` (GO), then `tasks.ps1 demo-offline`. "No API keys and no network needed: the models are local." Wait for "ready on REAL data". |
| **1:15 – 1:45** Data input | News & Social Feed | "The input: real headlines and posts captured from Google News, Reddit and Mastodon; each row shows its source, provenance and capture time." Filter to social. |
| **1:45 – 2:30** NLP output | NLP Risk Signals, then Explainability → **Analyse your own headline** | "Every item becomes a RiskSignal: entity, sentiment, event type and a 1–10 impact." Type a headline, e.g. "Moody's downgrades Reliance Industries as SEBI opens probe", click **Analyse**: probabilities, evidence words, the impact formula with the actual numbers. Optionally show the same call in Swagger (`POST /analyze`) to show the JSON output. |
| **2:30 – 3:15** Credit view | Home (time machine), Early Warning Watchlist, **Explain →** | "As of the latest captured news: 326 signals in 24 hours, 18 of 23 held issuers on watch." Drag the time machine back a day and return. "HDFC Bank is WATCH-NEGATIVE; the rule that fired is in the row." Click **Explain →**. |
| **3:15 – 3:45** Contagion | Risk Propagation | "Direct versus second-order exposure over hand-curated links; click a node for its positions. Curated, not inferred; an attention measure, not a contagion model." |
| **3:45 – 5:00** Output: stress test | sidebar **▶ Scenario demo**, Stress Test, Watchlist | "A scripted, SYNTHETIC story for the climax." Tata Motors downgrade → issuer stress 0.41% GREEN (CDS hedge). Watchlist: Tata Motors WATCH-NEGATIVE, peers flagged by propagation. Invasion → 1.32% AMBER; second source → 2.45% RED. Show the waterfall, top-10 positions, heatmap and audit log; read the disclaimer. |
| **5:00 – 5:30** What-if + brief | Stress Test → What-if; Watchlist → **Credit brief** → Download PDF | Move the HY spread slider and compare with the triggered run. Open the credit brief and download the PDF. |
| **5:30 – 6:30** Results | README **Key Results & Domain Impact**, `docs/evaluation.md`, slide 5 | "Measured by scripts, with n: sentiment accuracy 0.653, event 0.81, entity 0.898 on 147 headlines, labels still preliminary; median latency 204.7 ms per document; on 911 real documents our false-trigger fixes cut simulated stress runs from 84 to 50." Close: "Decision support, not investment advice. Thank you." |

Upload to YouTube as **Unlisted**, then put the link in the README (`Demo Video Link`) and in the DoSelect answer.

## (b) Live jury demo (5 min)

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
