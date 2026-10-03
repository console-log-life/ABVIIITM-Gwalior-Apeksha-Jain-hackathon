# On Windows without make, use the equivalent: powershell -File tasks.ps1 <target>
# Paths are relative to the project root, so a space in the parent path ("GT LAB") is safe.
ifeq ($(OS),Windows_NT)
PY := .venv/Scripts/python.exe
BOOT := py -3.11
else
PY := .venv/bin/python
BOOT := python3.11
endif

.PHONY: setup venv install models probe test test-fast lint

setup: venv install models

venv:
	$(BOOT) -m venv .venv

install:
	"$(PY)" -m pip install --upgrade pip
	"$(PY)" -m pip install -r requirements.txt

models:
	"$(PY)" scripts/setup_models.py

probe:
	"$(PY)" scripts/probe_sources.py

test:
	"$(PY)" -m pytest -q --cov=risk_engine --cov=portfolio --cov=app --cov-report=term-missing

test-fast:
	"$(PY)" -m pytest -q -m "not model"

lint:
	"$(PY)" -m ruff check .
