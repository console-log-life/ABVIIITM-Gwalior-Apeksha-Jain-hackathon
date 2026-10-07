# FinBERT int8 dynamic quantisation

Measured by `src/scripts/measure_quantization.py` on 2026-10-07 (CPU, 2 torch threads; each variant in its own process). Our evaluation labels are still preliminary (draft, not yet human reviewed).

| data set | n | accuracy fp32 | accuracy int8 | macro-F1 fp32 | macro-F1 int8 | ms/doc fp32 | ms/doc int8 |
|---|---:|---:|---:|---:|---:|---:|---:|
| our evaluation set | 147 | 0.653 | 0.605 | 0.648 | 0.582 | 87.9 | 88.4 |
| public test split (twitter-financial-news-sentiment) | 2388 | 0.687 | 0.724 | 0.639 | 0.605 | 108.5 | 64.6 |

| memory | fp32 | int8 |
|---|---:|---:|
| model RAM (process RSS after load minus before) | 645 MB | 936 MB |
| peak process working set | 867 MB | 1318 MB |
| load time | 4.6 s | 10.3 s |

Same label for 72.1% of our 147 items. Accuracy change on our set: -0.048. Rule: int8 is the default only if accuracy drops by at most 0.01. **Decision: int8 stays OFF by default** (`MODEL_QUANTIZE_INT8` in `.env` overrides it).

Notes:

- On the larger public split int8 is mixed: accuracy +0.037, macro-F1 -0.034. The rule uses our set because it is the domain the app serves (credit headlines and posts).
- Dynamic quantisation does NOT save RAM here: the int8 copy is built while the fp32 weights are still loaded, so model RAM and the peak are higher. It only speeds up longer texts.

What keeps memory low instead (all on by default): each model is loaded once per process and shared; `TORCH_THREADS=2`; models load with `low_cpu_mem_usage=True` (no second weight copy during start-up); `src/scripts/preflight.py` says NO-GO below 1.5 GB free RAM and lists the processes using the most memory; `tasks.ps1 test` runs every test file in its own process (`src/scripts/run_tests.py`).
