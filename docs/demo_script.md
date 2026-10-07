# Demo scripts

- **(a) Recorded video, 6–7 minutes** (YouTube, unlisted): intro → setup from the README → walkthrough from data input
  to output → results → close. Exact words for each scene, and which page or button to click.
- **(b) Live jury pitch, 5 minutes** (slides + live demo), plus a **60-second backup** if the laptop fails (slides only).
- One-page Q&A and numbers: [JURY_CHEATSHEET.md](JURY_CHEATSHEET.md).

What is real: every page before the scenario shows CACHED_REAL data (real captured news, badged with its capture time);
the Tata Motors and invasion headlines are SYNTHETIC; the portfolio is SYNTHETIC and every stress result is simulated
with an illustrative model. Say this; never call cached data "live".

## (a) Recorded video (6–7 min)

**Before recording**

1. Close everything you can (Docker can stay). Run `powershell -ExecutionPolicy Bypass -File tasks.ps1 preflight`: it
   must say **GO** (it is NO-GO below 1.5 GB free RAM and lists what to close).
2. Start the app once so the models are warm: `powershell -ExecutionPolicy Bypass -File tasks.ps1 demo-offline`. Wait
   for `ready on REAL data`, open <http://127.0.0.1:8501>, click through every page once, then leave it running.
3. Recorder: OBS or the Windows Game Bar (`Win+Alt+R`), 1920×1080, microphone on, browser zoom 110%.
4. Have open: `docs/presentation.pdf` (slide 1), the GitHub README at **Quickstart**, a PowerShell window in the repo
   folder, and the dashboard.

| Time | Screen and clicks | Say exactly |
|---|---|---|
| **0:00–0:30** Intro | `docs/presentation.pdf`, slide 1 | "Hello, I am Apeksha Jain from ABV-IIITM Gwalior. This is Risk Signal Engine, my individual submission for Module B, strategic portfolio stress testing. It reads news and social posts, turns each item into an explainable risk signal, and stress-tests a portfolio the moment something material happens. Everything on screen is labelled LIVE, CACHED_REAL or SYNTHETIC, and every stress result is simulated." |
| **0:30–1:00** Setup | GitHub README → **Quickstart**; then the PowerShell window | "Setup is three commands from the README: clone, `tasks.ps1 setup`, which creates the virtual environment, installs the pinned packages and downloads FinBERT and spaCy, and `tasks.ps1 demo-offline`. I installed it before recording, so you won't watch a ten-minute download. No API keys and no network are needed during the demo." Show the running window with `ready on REAL data`. |
| **1:00–1:30** Data input | **News Social Feed** | "This is the input: real headlines and posts captured from Google News, Reddit and Mastodon. Each row shows the source, the provenance badge CACHED_REAL, and when it was captured." Remove one **Source type** filter tag to show only news, then add it back. |
| **1:30–2:15** NLP output | **NLP Risk Signals**; then **Explainability** → tab **Analyse your own headline** | "Every item becomes a RiskSignal: the company, sentiment from FinBERT, one of eleven event types, and an impact score from one to ten." Switch page. Type `Moody's downgrades Reliance Industries as SEBI opens probe into accounts`, ticker hint `RELIANCE.NS`, click **Analyse**. "Here is why: negative probability 0.93, the evidence words, the weighted factors, and the impact formula with the actual numbers." |
| **2:15–3:00** Credit view | **Home**; drag the **time machine** slider left, then click **Latest**; **Early Warning Watchlist** → **Explain →** | "As of the latest captured news, 326 signals in 24 hours and 18 of our 23 held issuers need a look. The time machine replays the same dashboard a day earlier, by publication time." Click Latest. "The watchlist: HDFC Bank is WATCH-NEGATIVE, and the rule that fired is in the row." Click **Explain →**: "one click to the reason." |
| **3:00–3:30** Linked exposure | **Risk Propagation** | "What else in the book is connected? Direct versus propagated exposure over hand-curated links. They are curated, not inferred, and this is an attention measure, not a contagion model." Pick another issuer in **Issuer (held)**. |
| **3:30–4:45** Output: stress test | sidebar **Mode & demo control** → **▶ Scenario demo**; then **Stress Test**, **Early Warning Watchlist**, **Stress Test** again | "Now a scripted, SYNTHETIC story. A Moody's downgrade of Tata Motors, a held issuer, triggers an issuer-only stress test: 0.41 percent, GREEN, because our CDS hedge offsets most of it. On the watchlist, Tata Motors is WATCH-NEGATIVE and its peers Ford and Tesla are flagged through propagation. Then an invasion headline: a moderate geopolitical scenario, 1.32 percent, AMBER. A second, independent source corroborates it: severe, 2.45 percent, RED, above our 2 percent appetite." Scroll to the waterfall and the audit log. "Every run is logged with the headline that triggered it. This is a simplified, illustrative model, not a production risk model." |
| **4:45–5:15** What-if and brief | **Stress Test** → what-if: **Start from**, move **HY spread**; **Early Warning Watchlist** → Tata Motors → **Credit brief** → **⬇ Download PDF** | "Analysts can test their own shock: start from the severe scenario and widen high-yield spreads; it reprices instantly and saves nothing. And one click gives a one-page credit brief, from templates, with no language model." |
| **5:15–6:15** Results | README **Key Results & Domain Impact**; then slide 5 | "The numbers, all measured by scripts in the repository, with n. On 147 real headlines and posts: sentiment accuracy 0.653, event classification 0.81, entity resolution 0.898. The labels are still preliminary, so treat these as a smoke test. Median latency is 204.7 milliseconds per document on a CPU laptop, over 200 documents. Replaying 911 real captured documents, our false-trigger fixes cut simulated stress runs from 84 to 50. And everything is verified: 275 tests, every API endpoint and every dashboard control." |
| **6:15–6:35** Close | slide 7 | "Risk Signal Engine is an honest, explainable bridge from text to portfolio risk that runs offline on a laptop. It is decision support, not investment advice. The code, the deck and this video are linked in the README. Thank you." |

After recording: upload to YouTube as **Unlisted**, open the link in a private window to check it plays, then send it
to be filled into the README (`Demo Video Link`) and the DoSelect answer.

## (b) Live jury pitch (5 min)

**T−10 min:** `tasks.ps1 preflight` → GO; `tasks.ps1 demo-offline` → `ready on REAL data`; dashboard open at zoom
110–125%; `docs/presentation.pdf` open in a second window. The speaker notes in the deck are a slides-only 5-minute
version if the jury asks for slides without a demo.

| Time | Screen | Say / do |
|---|---|---|
| **0:00–0:40** | Slides 1–2 | "Risk Signal Engine, Module B, individual submission. Credit risk shows up in text before it shows up in data: downgrades, probes, sanctions, rate surprises. Today an analyst reads the headline and a stress test runs later, by hand. Here, every item is scored and explained, and a material one reprices the book." |
| **0:40–1:05** | Slide 3 | "One pipeline for live, replayed, scripted and API input: entities, FinBERT sentiment, event rules with evidence, a 1-to-10 impact score; the stress engine subscribes to the signals. Every record is labelled, and it runs offline." |
| **1:05–1:45** | Dashboard: **Home**, **Early Warning Watchlist**, **Explain →** | "This is real captured news, 1,325 items: 18 of 23 held issuers need a look. HDFC Bank is WATCH-NEGATIVE; the rule is in the row." Click **Explain →**: "sentiment probabilities, evidence words, and the formula with the numbers." |
| **1:45–3:15** | sidebar **▶ Scenario demo**; **Stress Test**; **Watchlist** | "A scripted, SYNTHETIC story. Tata Motors downgrade: issuer stress 0.41% GREEN, hedged by CDS; Tata and its peers flagged on the watchlist. Invasion headline: 1.32% AMBER. A second source corroborates: 2.45% RED, above our 2% appetite." Show the waterfall and the audit log. "Simulated, illustrative model, synthetic portfolio." |
| **3:15–3:45** | **Stress Test** → what-if | Let a judge choose a shock (e.g. HY spreads +300 bp): "it reprices instantly; nothing is saved." |
| **3:45–4:30** | Slide 5 | "Measured, with n: sentiment 0.653, events 0.81, entities 0.898 on 147 items, labels preliminary. Median 204.7 ms per document. Our false-trigger fixes cut stress runs on 911 real documents from 84 to 50." |
| **4:30–5:00** | Slide 7 | "Limits: uncalibrated weights, headline-only news, a small AI-labelled eval set, an illustrative stress model. Next: calibration, full-text news, fine-tuned models. Decision support, not investment advice. Thank you." |

### 60-second backup (laptop fails; slides only, from any machine)

Open `docs/presentation.pdf` from the GitHub repository (`…/blob/main/docs/presentation.pdf`).

> (Slide 1) "Risk Signal Engine turns news and social posts into explainable risk signals and stress-tests a portfolio
> when something material happens. (Slide 3) One pipeline: entities, FinBERT sentiment, eleven event types with
> evidence, an impact score from one to ten, and an event-driven stress engine. (Slide 5) In our scripted demo a Tata
> Motors downgrade gives 0.41% GREEN thanks to a CDS hedge; a corroborated invasion gives 2.45% RED. Measured on 147
> items: sentiment 0.653, events 0.81, entities 0.898, preliminary labels; median 204.7 ms per document. (Slide 7)
> It is illustrative decision support that runs offline on a laptop, and the README has a recorded walkthrough. Thank
> you."

## Backup plan

| Failure | Fallback |
|---|---|
| Preflight NO-GO (RAM) | Close the apps it lists; Docker can stay. Re-run preflight. |
| No internet / venue Wi-Fi down | Nothing to do: `tasks.ps1 demo-offline` needs no network (verified by `src/scripts/failure_drill.py`). |
| REAL history still building at start | The sidebar shows the progress; start the **Scenario demo** first (it is independent), then return to the real-data part. |
| Live sources failing | Expected and fine: Source Health shows them DEGRADED/BACKOFF while the app keeps running. |
| FinBERT won't load | The sidebar badge shows the lexicon fallback and /health says why. Continue; scores are confidence-capped. |
| API or dashboard crashes | Rerun `tasks.ps1 demo-offline` (the cached history loads in seconds). Meanwhile show `docs/screenshots/1920x1080/`. |
| Laptop dies | The 60-second backup above, then play `docs/demo/demo_walkthrough.webm` or the YouTube video from another machine. |
| Time overrun | Skip the what-if (30 s) and the propagation page. |
