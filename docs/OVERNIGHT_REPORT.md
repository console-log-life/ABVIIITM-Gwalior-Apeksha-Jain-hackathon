# Overnight report: 2026-10-03 → 04

All milestones M2–M8 are done and committed locally; nothing was pushed. The DoSelect answer passes its quality
check, but **it is not ready to submit** until you supply the 3 links.

## Milestones

| Milestone | Commit | Result |
|---|---|---|
| M0 Skeleton (confirmed by you) | `4736c1f` | config, schemas, probe, model setup |
| M1 Ingestion (confirmed by you) | `ca7bc1d` | adapters, dedup, capture, replay, scheduler |
| M2 NLP core | `e45da31` | resolver, FinBERT + lexicon fallback, event rules, impact scorer, pipeline CLI; privacy scrub |
| M3 Store / bus / API | `182f953` (+ `bc3f94d` stray-log removal) | SQLite, event bus, all §7.3 endpoints, SSE, JSONL, Swagger examples |
| M4 Stress engine | `e25a7cc` | synthetic portfolio, pricers, scenarios, triggers, end-to-end headline → stress |
| M5 Dashboard | `336f29b` | 12 sections, headline box, health panel, mode switch; 7/7 pages verified; screenshots |
| M6 Demo + drills | `387fffa` | one-command demo (deterministic, offline), outage drill 7/7, source-kill test |
| M7 Evaluation + docs | `b5f382b`, `4b39202` | PRELIMINARY metrics, latency benchmark, README and all docs; fresh-clone verified |
| M8 Submission pack | `8dac506` | answer md + paste-ready html; `build_submission.py` 19/19 PASS |

## Final state

- **Tests:** 142 passed (141 fast + 1 FinBERT model test).
- **Coverage:** 88%.
- **Lint:** ruff clean.
- **Fresh clone:** `git clone` → `tasks.ps1 setup` → `tasks.ps1 test`: 142 passed (clone deleted afterwards).
- **Real data:** 911 CACHED_REAL documents across 11 capture runs; the capture log is in `docs/PROGRESS.md`.

## Start the demo (one command)

```powershell
cd "E:\GT LAB\PROJECTS\risk-signal-engine"
powershell -ExecutionPolicy Bypass -File tasks.ps1 demo          # add -offline variant: tasks.ps1 demo-offline
```

Then open the **dashboard at http://127.0.0.1:8501** and the **API docs at http://127.0.0.1:8000/docs**.

The story plays four SYNTHETIC steps, 10 s apart:

| Step | Signal | Stress run (simulated) |
|---|---|---|
| 1. Nvidia product launch | 3.6 Low | none |
| 2. Tata Motors downgrade | 8.7 Critical | idiosyncratic 0.41% GREEN |
| 3. Invasion | 7.0 High | geopolitical moderate 1.32% AMBER |
| 4. Corroborating source | 9.1 Critical | geopolitical severe 2.45% RED |

Press Ctrl+C to stop. The script is in `docs/demo_script.md`.

## Decisions I made on your behalf

These are listed in full, with D-numbers, in `docs/PROGRESS.md` → "Blockers / decisions". The ones that matter most:

1. **D9:** the IRS sign typo in the spec was corrected, so pay-fixed gains when rates rise. Unit-tested.
2. **D8:** the portfolio mix is measured on gross exposure; loss % uses funded MV.
3. **D12:** I added a `systemic_credit_moderate` scenario, because the spec table has none.
4. **D16:** step 1 of the demo uses Nvidia via a social source. Under the spec weights, a positive launch at a *large*
   holding (Apple) scores 5.3 Medium, not Low. **I did not change any weights.**
5. **D4:** MARKET corroboration also requires a shared evidence phrase; otherwise any two geopolitical headlines would
   "corroborate" each other.
6. **D1–D3:** entity-resolution guards ("apple pie" ≠ AAPL; no subset false positives from fuzzy matching; macro
   headlines override a query's ticker hint).
7. **D13:** FX translation of INR holdings is not modelled; only FX forwards take the FX shock.
8. **Zero-shot:** stays **OFF**. It measured 0.770 macro-F1 versus 0.792 for rules alone.
9. **D17:** the dashboard uses a fixed light theme for the projector.
10. **Small extra endpoints:** `POST /mode`, `GET /demo/status`, `GET /methodology`, `GET /portfolio/scenarios` and
    `GET /stress-runs/{id}`. The dashboard and transparency views need them.
11. **Bugs found and fixed overnight:**
    - Reddit rotation skipping;
    - langdetect calling short English headlines French;
    - the token-bucket rounding that made Mastodon report RATE_LIMITED;
    - FinBERT batch padding (batched latency 532 → 279 ms/doc).

## What ONLY you can do (priority order)

1. **Review the 147 draft eval labels.** They are in `data/eval/labelled_headlines.csv` (`label_status=draft_agent`).
   For each row, fix the label if needed and set `label_status=human_reviewed`. Then run `tasks.ps1 evaluate` and
   `tasks.ps1 submission`. Until then, every accuracy number is PRELIMINARY.
2. **Create the GitHub repo and push.** Decide first on publishing cached social data. `data/cache/captures/` holds
   real Reddit and Mastodon posts with author handles removed; post URLs remain, and those URLs still contain handles.
   If you'd rather not publish them, exclude the social rows or the cache before pushing.
3. **Build the 7 slides** from `docs/slides_outline.md`, with screenshots from `docs/screenshots/`.
4. **Rehearse the demo twice** (≤ 5:00), including the backup path (`tasks.ps1 demo-offline` and REPLAY), and record
   it if a live demo link is needed.
5. **Supply the 3 links:** GitHub, live demo and presentation. I will then replace the placeholders, rerun
   `build_submission.py`, and confirm zero placeholders remain.
6. **Optional:** add `FINNHUB_API_KEY` and/or `BLUESKY_HANDLE` + `BLUESKY_APP_PASSWORD` to `.env`, then run
   `tasks.ps1 probe`. Only cite them if the probe passes.
7. **Keep capturing** 2–3× a day with `tasks.ps1 capture`. When the capture dates span more than one day,
   `build_submission.py` will fail until the answer says "captured between X and Y". That's intentional.

## Weaknesses a judge could attack, with honest answers

| Attack | Honest answer |
|---|---|
| "Your accuracy numbers are self-graded." | Correct: the labels were drafted by the AI that built the rules and the lexicon. They're marked PRELIMINARY everywhere and pending human review. |
| "The lexicon beats FinBERT; why use FinBERT?" | Same-author bias makes that comparison unreliable. FinBERT is an independent, domain-trained model. |
| "Keyword rules misfire." | Yes: figurative "war on data centres", and a fund newsletter that triggered a macro stress run in replay. Corroboration, cooldown and human review mitigate it; a fine-tuned classifier is future work. |
| "The impact weights are arbitrary." | They are expert priors, published at `/methodology`. Calibration against market moves is the first future-work item. |
| "Positive news gets a high 'risk' score." | The score measures materiality, not downside. It's documented, and it's a one-line weight change if a downside-only score is preferred. |
| "The portfolio and losses aren't real." | Correct: synthetic seed-42 book and an illustrative stress model, labelled on every view. |
| "Is it real-time?" | Yes in LIVE mode. The demo uses SYNTHETIC/CACHED_REAL data with visible badges, and nothing cached is presented as live. |
| "Social sources are flimsy." | Yes: unofficial RSS/APIs, StockTwits blocked, GDELT rate-limited. Health is shown, and REPLAY is the fallback. |
| "Does it scale?" | No: single process, SQLite. Kafka, Postgres and worker adapters are the path. |
| "Security?" | No authentication; it's a local prototype. Secrets come from `.env`, and keys go in headers. |
