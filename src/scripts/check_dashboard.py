"""Headless dashboard check: run every Streamlit page with streamlit.testing.AppTest against the RUNNING API and
report exceptions, errors and how many charts/tables each page rendered.

Usage (API must be running):  python src/scripts/check_dashboard.py
Exit code 1 if any page raised an exception or showed an error box.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DASH = ROOT / "src" / "app" / "dashboard"
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(DASH))

from streamlit.testing.v1 import AppTest  # noqa: E402


def check(page: Path) -> tuple[bool, str]:
    at = AppTest.from_file(str(page), default_timeout=60)
    at.run()
    charts = len(at.get("plotly_chart"))
    tables = len(at.dataframe)
    errors = [e.value for e in at.error]
    exc = [str(e.value)[:200] for e in at.exception]
    ok = not errors and not exc
    detail = f"charts={charts} tables={tables} metrics/kpis={len(at.markdown)} md blocks"
    if errors:
        detail += f" ERRORS={errors}"
    if exc:
        detail += f" EXCEPTIONS={exc}"
    return ok, detail


def main() -> int:
    argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    pages = [DASH / "Home.py", *sorted((DASH / "pages").glob("*.py"))]
    failed = 0
    for p in pages:
        ok, detail = check(p)
        failed += not ok
        print(f"{'PASS' if ok else 'FAIL'}  {p.name:<28} {detail}")
    print(f"\n{len(pages) - failed}/{len(pages)} pages rendered without errors")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
