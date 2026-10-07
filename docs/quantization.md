# FinBERT int8 dynamic quantisation: kept OFF

**Decision: `MODEL_QUANTIZE_INT8=false` (default).** Rule: int8 would become the default only if sentiment accuracy on
our evaluation set dropped by at most 1 point (0.01). It dropped by 4.8 points.

| variant | data set | n | sentiment accuracy | macro-F1 | source |
|---|---|---:|---:|---:|---|
| fp32 (default) | our evaluation set | 147 | 0.653 | 0.648 | `src/scripts/evaluate.py` (`docs/evaluation.md`) |
| int8 dynamic (Linear layers) | our evaluation set | 147 | 0.605 | 0.582 | `src/scripts/measure_quantization.py --worker int8`, 2026-10-07 |

Labels of our set are still preliminary (draft, not yet human reviewed). Measured on the development laptop (CPU, 2 torch
threads): int8 used 209 MB of model RAM in its process and 67.4 ms per document on our set. The int8 confusion matrix
shows the loss is mostly negative headlines predicted as neutral (30 of 50 negatives), the class that matters most for
credit risk.

What keeps memory low instead (all on by default):

- each model is loaded **once per process** and shared by every engine (`load_finbert` cache);
- `TORCH_THREADS=2`;
- models load with `low_cpu_mem_usage=True` (via `accelerate`), so the weights are not held twice in RAM during start-up;
- `src/scripts/preflight.py` says NO-GO below 1.5 GB free RAM and lists the processes using the most memory;
- `tasks.ps1 test` runs every test file in its own process (`src/scripts/run_tests.py`).

Pending: the full side-by-side run (`python src/scripts/measure_quantization.py`: fp32 and int8 in separate processes,
our set plus the 2,388-item public sentiment test split, RAM and latency) needs ~2 GB of free RAM; it will replace this
table with `data/eval/quantization_results.json`. `MODEL_QUANTIZE_INT8=true` in `.env` still enables int8 for a machine
that cannot load fp32 at all.
