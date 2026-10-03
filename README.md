# Risk Signal Engine

AI/NLP financial risk signals from news and social text, plus downstream portfolio stress testing.
S&P Global × CRISIL "Code to Connect Hackathon 2026" — Phase 3.

> Status: Milestone M0 (skeleton). The full README is written in M7.

## Quickstart (M0)

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env                       # optional; app runs with zero keys
.\.venv\Scripts\python.exe scripts\probe_sources.py
.\.venv\Scripts\python.exe scripts\setup_models.py
.\.venv\Scripts\python.exe -m pytest -q
```

On Linux/macOS, or with GNU make: `make setup`, `make probe`, `make test`.
On Windows without make: `powershell -ExecutionPolicy Bypass -File tasks.ps1 setup`.

*Simplified, illustrative hackathon stress model. Not a production or regulatory risk model.*
