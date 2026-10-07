# Upgrade report (6–7 Oct 2026; code freeze end of 8 Oct)

Two briefs: the UI upgrade (tasks A–F) and real model training (T1–T6). Done: T1–T3 and A, B, C, D, E, F, except the
items under "Not finished". Every commit had ruff clean and the fast suite green; no commit carries AI attribution.

## Commits

| Task | Commit |
|---|---|
| T1 public datasets, leakage-free checksummed splits, topic map | `304a5c4` |
| T2 GPU training notebook (Kaggle/Colab), smoke-tested locally, docs/TRAINING.md | `c8b12e3` |
| T3 fine-tuned model integration (hybrid events, int8 flag, verified import script) | `e8873f1` |
| A real data: history backend + time machine API | `89eb31c` |
| A real data: UI (time machine, KPIs with trends, sparklines) | `b164ec6` |
| B dark risk-terminal theme | `1b9f94d` |
| D what-if scenario builder | `3f1c51d` |
| C risk propagation | `bd74aae` |
| E credit brief (HTML + PDF) | `dac4a3d` |
| F demo flow, docs, recorder | `13a11a7` |
| F screenshots, deck, README, DoSelect answer | `424921c` |
| F final counts, this report | see `git log` |

## Tests

| | before (6 Oct) | now |
|---|---:|---:|
| fast suite | 196 | **259 passed** |
| FinBERT model tests (separate process) | 4 | **4 passed** |
| coverage (fast suite, risk_engine + portfolio + app) | 88% | **90%** |

New test files: `test_public_data.py`, `test_learned_models.py` (tiny random models, no downloads), `test_history.py`,
`test_whatif.py`, `test_propagation.py`, `test_credit_brief.py` (all 23 held issuers × JSON/HTML/PDF).

## Numbers (all from code)

- REAL history: **1,325** captured documents (3 Oct 17:22 → 5 Oct 20:14 UTC) → 1,325 signals, **54** simulated stress
  runs (event-time clock, like the trigger replay). Built in 7.3 min on this laptop; loads in about 1 s afterwards.
- As of the latest data (5 Oct 20:03 UTC): 326 signals in 24 h (34 in the previous 24 h), 18 of 23 held issuers on
  watch, 7 WATCH-NEGATIVE; top issuer HDFC Bank (worst impact 8.1, sentiment −0.95).
- Scenario story unchanged with the history loaded (two demo runs + one API-only run): 0.41% GREEN → 1.32% AMBER →
  2.45% RED; Tata Motors WATCH-NEGATIVE; Ford, Bank of America, HSBC, Goldman MONITOR by propagation.
- Public datasets (MIT): sentiment 8,384 / 932 / 2,388 (train/dev/test), topic 14,149 / 1,571 / 4,117; leakage removed
  from train 227 and 1,270 rows.
- DoSelect answer: 1,088 words, `build_submission.py` 19/19 (only the 3 link placeholders remain).

## Screenshots: before / after

| Before (light theme, 6 Oct) | After (dark theme, real data) |
|---|---|
| git history of `docs/screenshots/01_home.png` … `08_watchlist.png` (commit `1ec4203`) | `docs/screenshots/01_home.png` … `09_propagation.png`, `10_credit_brief.png` (full pages) |
| — | `docs/screenshots/1366x768/*.png`, `docs/screenshots/1920x1080/*.png` (projector viewports, checked for overflow) |
| `docs/screenshots/readme/1_watchlist.png`, `2_stress.png`, `3_explain.png` | `docs/screenshots/readme/1_home.png`, `2_propagation.png`, `3_stress.png` |
| deck previews at `1ec4203` | `docs/presentation/preview/slide-1..7.png` (slide 5: propagation graph; slide 6: watchlist + credit brief) |

## Decisions made on your behalf

1. **Time machine on event (publication) time, not capture time.** The captures are two bursts (3 and 5 Oct, 48 h
   apart), so a capture-time window would be empty most of the time. Stated on screen and in methodology §9: it is a
   reconstruction, not what a live system saw.
2. **"Latest" = the newest data time, not the wall clock**, so the real-data windows stay full on 9–10 Oct.
3. **REAL-history stress runs use the trigger engine's cooldown on event time** → 54 runs (the earlier capture-time
   attempt gave 14).
4. **Corroboration ignores the loaded history**, so the scripted story's numbers never change.
5. **Propagation links**: 16 curated links among universe issuers only (JLR and Adani Group are aliases, Apple has no
   supplier link); decay 0.5 supplier/parent, 0.3 peer; 1 hop; MONITOR by propagation at weight ≥ 0.3.
6. **Credit brief PDF** with fpdf2 (LGPL-3.0, pure Python) and core fonts (symbols mapped to Latin-1).
7. **Optional datasets skipped**: SEntFiN (Kaggle login; the HF copy mixes in PhraseBank, licence unclear) and EDT (no
   licence). The rule engine is evaluated on the public topic test split locally, not in the notebook (it needs the
   repository code).
8. **Bug found and fixed**: a module-scoped test fixture could rebuild `data/real_history.db` with the lexicon backend;
   tests now can never autoload the history, and `universe.yaml` is part of the cache fingerprint.

## Not finished

- **Silent backup video** not re-recorded. Two attempts failed because the laptop had under 1 GB of free RAM (other
  applications held ~1.5 GB); the API did not start within 3 minutes. The recorder is updated for the new flow; run
  `tasks.ps1 video` with browsers closed. The committed video still shows the previous flow (DEMO.md says so).
- **T4–T6** wait for `trained_models.zip` from the Kaggle run (docs/TRAINING.md). Then: `python
  scripts/import_trained_models.py trained_models.zip`, public benchmark in `evaluate.py`, ship/no-ship decision,
  end-to-end re-check, model card, deck slide 4, DoSelect Results.
- GitHub repository not created yet (needs you: github.com/new → `risk-signal-engine`, then `git push -u origin main`).
- Narrated demo recording (a person).
