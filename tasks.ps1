# Windows equivalent of the Makefile.  Usage: powershell -ExecutionPolicy Bypass -File tasks.ps1 <target>
param([Parameter(Mandatory = $true)][ValidateSet(
        "setup", "install", "models", "probe", "test", "test-fast", "lint", "capture", "replay", "ingest-once",
        "api", "dashboard", "demo", "demo-offline", "drill", "check-dashboard", "screenshots", "portfolio",
        "evaluate", "benchmark", "submission", "test-model", "preflight", "label-review", "import-labels")]
    [string]$Target)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot  # path may contain spaces ("GT LAB")
$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

function Invoke-Install { & $py -m pip install --upgrade pip; & $py -m pip install -r requirements.txt }

switch ($Target) {
    "setup" {
        if (-not (Test-Path $py)) { py -3.11 -m venv .venv }
        Invoke-Install
        & $py scripts/setup_models.py
    }
    "install" { Invoke-Install }
    "models" { & $py scripts/setup_models.py }
    "probe" { & $py scripts/probe_sources.py }
    "test" {
        # fast suite first (with coverage), then the FinBERT tests in a SEPARATE process (one model load, less RAM)
        & $py -m pytest -q -m "not model" --cov=risk_engine --cov=portfolio --cov=app --cov-report=term-missing --cov-report=xml
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        & $py -m pytest -q -m model
    }
    "test-model" { & $py -m pytest -q -m model }
    "preflight" { & $py scripts/preflight.py }
    "label-review" { & $py scripts/build_label_review.py }
    "import-labels" { & $py scripts/import_label_review.py }
    "test-fast" { & $py -m pytest -q -m "not model" }
    "lint" { & $py -m ruff check . }
    "capture" { & $py scripts/capture_cache.py }
    "replay" { & $py -m risk_engine.ingestion.replay --limit 20 }
    "ingest-once" { & $py -m risk_engine.ingestion.scheduler --once }
    "api" { & $py -m uvicorn app.main:app --host 127.0.0.1 --port 8000 }
    "dashboard" { & $py -m streamlit run app/dashboard/Home.py --server.port 8501 }
    "demo" { & $py scripts/run_demo.py }
    "demo-offline" { & $py scripts/run_demo.py --offline }
    "drill" { & $py scripts/failure_drill.py }
    "check-dashboard" { & $py scripts/check_dashboard.py }
    "screenshots" { & $py scripts/screenshot_dashboard.py }
    "portfolio" { & $py -m portfolio.generate_portfolio }
    "evaluate" { & $py scripts/evaluate.py }
    "benchmark" { & $py scripts/benchmark_latency.py }
    "submission" { & $py scripts/build_submission.py }
}
exit $LASTEXITCODE
