# Night 2 report (autonomous mode, 2026-10-05 → 2026-10-06)

All seven tasks are done. Every commit had ruff clean and the fast suite green. No commit carries AI attribution.
Nothing was pushed: no `origin` remote exists and `GITHUB_REMOTE_URL` is not set (see "GitHub" below).

## Commits (pre-night HEAD `55e0efe`)

| Task | Work commit | Progress commit |
|---|---|---|
| 1. Restore classification, 2-cue rule only in triggers | `c1ced3e` | `88a61c9` |
| 2. Remaining false positives (sentiment gate, verdict guard, rate direction, `macro_rate_cut`) | `105b949` | `4294e5f` |
| 3. Demo stability (FinBERT singleton, 2 threads, warm-up, split tests, preflight) | `32b8c55` | `c36df3a` |
| 4. Label-review xlsx + import script | `704579d` | `e8decbd` |
| 5. 7-slide pptx | `173e674` | `f06e8dc` |
| 6. Silent demo video | `8d332b6` | `65dad87` |
| 7. Docs/submission consistency + this report | `2bbd666` + the report commit | |

## Tests

| | start of night | end of night |
|---|---:|---:|
| fast suite (`pytest -m "not model"`) | 157 | **177 passed** |
| model tests (`pytest -m model`, separate process) | 1 | **3 passed** |
| total | 158 | **180** |
| coverage (fast suite) | 87% | 87% |

`tasks.ps1 test` now runs the fast suite with coverage and then the model tests in a second process, so FinBERT is
never loaded twice in one process (the earlier full-suite segfault happened under memory pressure).

## Before / after

**Evaluation** (PRELIMINARY: same 147 AI-drafted labels; full history table in `docs/evaluation.md`)

| run | sentiment acc / F1 | event acc / F1 | entity acc |
|---|---|---|---|
| M7 baseline | 0.653 / 0.648 | 0.803 / 0.792 | 0.891 |
| night 1 (2-cue rule in classification) | 0.653 / 0.648 | 0.762 / 0.768 | 0.857 |
| night 2 task 1 (rule moved to triggers) | 0.653 / 0.648 | **0.81 / 0.795** | **0.898** |
| night 2 task 2 (gate, verdict guard, rate direction) | 0.653 / 0.648 | 0.81 / 0.795 | 0.898 |

Zero-shot tie-breaker: 0.78 vs 0.795 macro-F1 without it, so it stays OFF.

**Stress-trigger replay** (same 911 local real docs captured before 2026-10-04; `docs/trigger_replay.md`)

| | before fixes | night 1 | n2 task 1 | n2 task 2 |
|---|---:|---:|---:|---:|
| stress runs | 84 | 59 | 59 | **50** |
| systemic | 74 | 50 | 50 | 45 |
| idiosyncratic | 10 | 9 | 9 | 5 |
| triggered by social posts | 11 | 0 | 0 | 0 |

Latest scenarios: geopolitical_moderate 29, geopolitical_severe 5, macro_rate_shock_moderate 7,
macro_rate_shock_severe 2, macro_rate_cut 2, idiosyncratic_credit 5. Five issuer-only runs remain: Reliance SEBI
warning ×2 and Adani SEBI settlements ×3 (settlements are borderline; documented as a limitation).

## What changed in the demo numbers

**Nothing in the demo story.** Two full demo runs gave the same results as before: 3.6 Low (no trigger) → 8.7
idiosyncratic 0.41% GREEN → 7.0 geopolitical moderate 1.32% AMBER → 9.1 (2 sources) geopolitical severe 2.45% RED.
FinBERT loads once (6.8 s) and the warm-up takes 0.12 s.

Numbers that changed in the docs, the DoSelect answer and the deck: event accuracy 0.762 → 0.81, macro-F1 0.768 →
0.795, entity accuracy 0.857 → 0.898, zero-shot comparison 0.768/0.751 → 0.795/0.78, replay 84 → 59 became 84 → 50,
test count 158 → 180, and the cached-data phrase is now "captured between 2026-10-03 and 2026-10-05".
`build_submission.py`: 19/19 checks pass; only the 3 link placeholders remain.

## Files to open in the morning

| File | What to do |
|---|---|
| `data/eval/label_review.xlsx` | Review the 147 labels (dropdowns; the "How to review" sheet explains). Model predictions are deliberately not shown |
| `docs/presentation/Risk_Signal_Engine.pptx` | Check the 7 slides; previews in `docs/presentation/preview/slide-1..7.png` |
| `docs/demo/demo_walkthrough.webm` | Silent backup video, 3:30, 1600×900, 18.1 MB (committed). At about 0:20 the Feed page is still loading |
| `docs/submission/doselect_answer.md` | Final read; fill the 3 links |

## Morning checklist

1. **Label review** in Excel (~60–90 min for 147 rows), then
   `powershell -ExecutionPolicy Bypass -File tasks.ps1 import-labels` (~2 min). It validates the sheet, writes the
   CSV and re-runs `evaluate.py`. If every row is reviewed, the PRELIMINARY banner can drop.
2. **Rebuild the deck** after the re-evaluation: `tasks.ps1 deck` (~3 min), then check the previews (~10 min).
3. **Narrated video** (~30 min): `tasks.ps1 preflight`, then `tasks.ps1 demo`, and record with narration.
   Keep the silent one as a backup.
4. **GitHub** (~10 min): create an empty repository on github.com (no README), then run the commands below.
5. **Hosting / live demo link** (~30–60 min, optional): a link to the video is an acceptable fallback.
6. **Fill the 3 links** in `docs/submission/doselect_answer.md`, then run `tasks.ps1 submission` (~5 min) until it
   says READY.
7. **Final sanity** (~10 min): `tasks.ps1 test`, `tasks.ps1 preflight`, then one demo run.

### GitHub push commands (not run)

```powershell
cd "E:\GT LAB\PROJECTS\risk-signal-engine"
git remote add origin https://github.com/<user>/risk-signal-engine.git
git push -u origin main
# verify the remote copy
git ls-tree -r --name-only origin/main | findstr /i "captures"       # expect no output
git log origin/main --format=%B | findstr /i "co-authored"          # expect no output
git ls-tree -r --name-only origin/main | findstr /i "\.env$"         # expect no output (only .env.example)
```

## Decisions made on your behalf

1. **Sentiment gate value −0.25** for issuer-only stress (`TRIGGER_IDIOSYNCRATIC_MAX_SENTIMENT`, configurable). It
   removed the Adani court-relief and Jio SEBI-clearance runs. It kept the negative issuer stories.
2. **Verdict guard:** "verdict" after analyst/our/my/strong/final/market/investor/street, or followed by "on the
   stock/shares/…", is not Litigation. Court verdicts still are.
3. **`macro_rate_cut` scenario values**: rates −50 bp, IG −10, HY −25, equity +2%, EM FX 0, PD ×0.95. These are
   illustrative expert values like the other scenarios. A rate headline whose direction is unclear runs no systemic
   scenario (it was a rate shock before).
4. **Replay input fixed** to documents captured before 2026-10-04 (911 docs), so the before/after columns compare
   the same set. Newer captures are excluded on purpose.
5. **Video:** Playwright drives the installed Edge (no browser download). Its ffmpeg is in the git-ignored
   `.tmp/ms-playwright`, not the user profile. The video is under 20 MB, so it is committed rather than git-ignored.
6. **Dev-only dependencies** (openpyxl, python-pptx, playwright) went into `requirements-dev.txt` and the project venv
   only. The label-review test skips if openpyxl is missing.
7. **The deck reads its numbers from the JSON outputs** (`eval_results.json`, `benchmark_results.json`, replay JSON,
   `StressEngine`), so a rebuild after the label review updates it automatically.
8. **Evaluation history** keeps the two earlier runs as rows marked *(recorded)*, copied from git history and
   PROGRESS.md, because those code states no longer exist.
9. **Not pushed:** no remote and no `GITHUB_REMOTE_URL`, so per the brief no repository was created.

## Housekeeping

- `scripts/capture_cache.py` ran at the start of the night (+372 docs) and at the end (+42 docs; local cache now
  1325 docs, git-ignored).
- Every server started tonight (demo runs, screenshots, video) was shut down. No uvicorn, streamlit or Playwright
  process is left running.
- `.tmp/backup/pre-rewrite.bundle` was kept, and git history was not rewritten.
