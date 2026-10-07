# On Windows without make, use the equivalent: powershell -File tasks.ps1 <target>
# Paths are relative to the project root, so a space in the parent path ("GT LAB") is safe.
ifeq ($(OS),Windows_NT)
PY := .venv/Scripts/python.exe
BOOT := py -3.11
else
PY := .venv/bin/python
BOOT := python3.11
endif

.PHONY: setup venv install models probe test test-fast lint capture replay ingest-once api dashboard demo demo-offline drill check-dashboard screenshots portfolio evaluate benchmark submission test-model preflight label-review import-labels

setup: venv install models

venv:
	$(BOOT) -m venv .venv

install:
	"$(PY)" -m pip install --upgrade pip
	"$(PY)" -m pip install -r requirements.txt

models:
	"$(PY)" src/scripts/setup_models.py

probe:
	"$(PY)" src/scripts/probe_sources.py

test:  # fast suite with coverage, then FinBERT tests in a separate process
	"$(PY)" -m pytest -q -m "not model" --cov=risk_engine --cov=portfolio --cov=app --cov-report=term-missing --cov-report=xml
	"$(PY)" -m pytest -q -m model

test-model:
	"$(PY)" -m pytest -q -m model

preflight:
	"$(PY)" src/scripts/preflight.py

test-fast:
	"$(PY)" -m pytest -q -m "not model"

lint:
	"$(PY)" -m ruff check .

capture:
	"$(PY)" src/scripts/capture_cache.py

replay:
	"$(PY)" -m risk_engine.ingestion.replay --limit 20

ingest-once:
	"$(PY)" -m risk_engine.ingestion.scheduler --once

api:
	"$(PY)" -m uvicorn --app-dir src app.main:app --host 127.0.0.1 --port 8000

dashboard:
	"$(PY)" -m streamlit run src/app/dashboard/Home.py --server.port 8501

demo:
	"$(PY)" src/scripts/run_demo.py

demo-offline:
	"$(PY)" src/scripts/run_demo.py --offline

drill:
	"$(PY)" src/scripts/failure_drill.py

check-dashboard:
	"$(PY)" src/scripts/check_dashboard.py

screenshots:
	"$(PY)" src/scripts/screenshot_dashboard.py

portfolio:
	"$(PY)" -m portfolio.generate_portfolio

evaluate:
	"$(PY)" src/scripts/evaluate.py

benchmark:
	"$(PY)" src/scripts/benchmark_latency.py

submission:
	"$(PY)" src/scripts/build_submission.py

label-review:
	"$(PY)" src/scripts/build_label_review.py

import-labels:
	"$(PY)" src/scripts/import_label_review.py
