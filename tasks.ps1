# Windows equivalent of the Makefile.  Usage: powershell -ExecutionPolicy Bypass -File tasks.ps1 <target>
param([Parameter(Mandatory = $true)][ValidateSet(
        "setup", "install", "models", "probe", "test", "test-fast", "lint", "capture", "replay", "ingest-once",
        "api", "dashboard", "demo", "demo-offline", "drill", "check-dashboard", "screenshots", "portfolio",
        "evaluate", "benchmark", "test-model", "preflight", "label-review", "import-labels", "deck", "video", "real-history")]
    [string]$Target)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot  # path may contain spaces ("GT LAB")
$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$env:PYTHONPATH = Join-Path $PSScriptRoot "src"  # packages live in src/ (python -m risk_engine..., portfolio...)

function Invoke-Install { & $py -m pip install --upgrade pip; & $py -m pip install -r requirements.txt }

switch ($Target) {
    "setup" {
        if (-not (Test-Path $py)) { py -3.11 -m venv .venv }
        Invoke-Install
        & $py src/scripts/setup_models.py
    }
    "install" { Invoke-Install }
    "models" { & $py src/scripts/setup_models.py }
    "probe" { & $py src/scripts/probe_sources.py }
    "test" {
        # one pytest process per test file (a MemoryError cannot hide failures), coverage, then the FinBERT tests;
        # prints a PASS/FAIL table and exits non-zero if any file failed
        & $py src/scripts/run_tests.py
        exit $LASTEXITCODE
    }
    "test-model" { & $py -m pytest -q -m model }
    "preflight" { & $py src/scripts/preflight.py }
    "label-review" { & $py src/scripts/build_label_review.py }
    "import-labels" { & $py src/scripts/import_label_review.py }
    "real-history" { & $py src/scripts/build_real_history.py }
    "video" { & $py src/scripts/record_demo_video.py }
    "deck" {
        & $py src/scripts/crop_screenshots.py
        & $py src/scripts/build_presentation.py
        if ($LASTEXITCODE -eq 0) { & powershell -NoProfile -ExecutionPolicy Bypass -File src/scripts/render_slides.ps1 }
    }
    "test-fast" { & $py src/scripts/run_tests.py --no-model --no-cov; exit $LASTEXITCODE }
    "lint" { & $py -m ruff check . }
    "capture" { & $py src/scripts/capture_cache.py }
    "replay" { & $py -m risk_engine.ingestion.replay --limit 20 }
    "ingest-once" { & $py -m risk_engine.ingestion.scheduler --once }
    "api" { & $py -m uvicorn --app-dir src app.main:app --host 127.0.0.1 --port 8000 }
    "dashboard" { & $py -m streamlit run src/app/dashboard/Home.py --server.port 8501 }
    "demo" { & $py src/scripts/run_demo.py }
    "demo-offline" { & $py src/scripts/run_demo.py --offline }
    "drill" { & $py src/scripts/failure_drill.py }
    "check-dashboard" { & $py src/scripts/check_dashboard.py }
    "screenshots" { & $py src/scripts/screenshot_dashboard.py }
    "portfolio" { & $py -m portfolio.generate_portfolio }
    "evaluate" { & $py src/scripts/evaluate.py }
    "benchmark" { & $py src/scripts/benchmark_latency.py }
}
exit $LASTEXITCODE
