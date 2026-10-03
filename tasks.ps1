# Windows equivalent of the Makefile.  Usage: powershell -ExecutionPolicy Bypass -File tasks.ps1 <target>
param([Parameter(Mandatory = $true)][ValidateSet("setup", "install", "models", "probe", "test", "test-fast", "lint")][string]$Target)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
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
    "test" { & $py -m pytest -q --cov=risk_engine --cov=portfolio --cov=app --cov-report=term-missing }
    "test-fast" { & $py -m pytest -q -m "not model" }
    "lint" { & $py -m ruff check . }
}
exit $LASTEXITCODE
