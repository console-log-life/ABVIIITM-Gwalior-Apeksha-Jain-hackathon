"""Run the test suite one file per pytest process and print a PASS/FAIL table (low-RAM safe).

  python src/scripts/run_tests.py                 # fast tests per file (with coverage), then the FinBERT tests
  python src/scripts/run_tests.py --no-model      # fast tests only
  python src/scripts/run_tests.py --no-cov

Why: on a laptop with < 1 GB free, one long pytest process can die with a MemoryError half-way, and its summary line
then hides how many tests never ran. Here every file gets a fresh process, results come from a JUnit XML report per
file, a file whose process crashed before reporting is run once more (marked "retried"), and a file that still has no
report, or any failing test, is reported as FAIL. Exit code 0 only if every file passed.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / ".tmp" / "run_tests"
COV = ["--cov=app", "--cov=risk_engine", "--cov=portfolio", "--cov-append", "--cov-report="]


def run_file(path: Path, marker: str, cov: bool) -> dict:
    xml = WORK / f"{path.stem}_{'model' if marker == 'model' else 'fast'}.xml"
    xml.unlink(missing_ok=True)
    cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-m", marker, str(path),
           f"--junitxml={xml}"] + (COV if cov else [])
    t0 = time.perf_counter()
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    res = {"file": path.name, "rc": p.returncode, "s": round(time.perf_counter() - t0, 1), "passed": 0, "failed": 0,
           "skipped": 0, "output": p.stdout[-3000:] + p.stderr[-2000:]}
    if xml.exists():
        suite = ET.parse(xml).getroot()
        suite = suite if suite.tag == "testsuite" else suite.find("testsuite")
        total, fail, err, skip = (int(suite.get(k, 0)) for k in ("tests", "failures", "errors", "skipped"))
        res.update(failed=fail + err, skipped=skip, passed=total - fail - err - skip)
    # 0 = all passed, 5 = every test in the file deselected by the marker; anything else (incl. a crash) is a FAIL
    res["ok"] = p.returncode in (0, 5) and res["failed"] == 0 and xml.exists()
    res["crashed"] = not xml.exists()  # the process died before writing its report (e.g. out of memory)
    return res


def run_file_retry(path: Path, marker: str, cov: bool) -> dict:
    """A file whose process CRASHED (no report written) is run once more; a test FAILURE is never retried."""
    res = run_file(path, marker, cov)
    if res["crashed"]:
        res = run_file(path, marker, cov)
        res["file"] += " (retried)"
    return res


def table(title: str, rows: list[dict]) -> bool:
    print(f"\n{title}")
    print(f"  {'result':<6} {'file':<34} {'passed':>6} {'failed':>6} {'skipped':>7} {'secs':>6}")
    for r in rows:
        if r["passed"] or r["failed"] or r["skipped"] or not r["ok"]:
            print(f"  {'PASS' if r['ok'] else 'FAIL':<6} {r['file']:<34} {r['passed']:>6} {r['failed']:>6} "
                  f"{r['skipped']:>7} {r['s']:>6}")
    tot = {k: sum(r[k] for r in rows) for k in ("passed", "failed", "skipped")}
    ok = all(r["ok"] for r in rows)
    print(f"  {'PASS' if ok else 'FAIL':<6} {'TOTAL':<34} {tot['passed']:>6} {tot['failed']:>6} {tot['skipped']:>7}")
    for r in rows:
        if not r["ok"]:
            print(f"\n--- {r['file']} (exit code {r['rc']}) ---\n{r['output']}")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-model", action="store_true", help="skip the FinBERT (@pytest.mark.model) tests")
    ap.add_argument("--no-cov", action="store_true", help="no coverage")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    WORK.mkdir(parents=True, exist_ok=True)
    files = sorted((ROOT / "tests").glob("test_*.py"))
    cov = not args.no_cov
    if cov:
        subprocess.run([sys.executable, "-m", "coverage", "erase"], cwd=ROOT)
    fast = []
    for f in files:
        fast.append(run_file_retry(f, "not model", cov))
        print(f"  {'.' if fast[-1]['ok'] else 'F'} {f.name}", flush=True)
    ok = table("Fast tests (one pytest process per file)", fast)
    if cov:
        rep = subprocess.run([sys.executable, "-m", "coverage", "report"], cwd=ROOT, capture_output=True, text=True)
        total = [ln for ln in rep.stdout.splitlines() if ln.startswith("TOTAL")]
        print(f"  coverage: {total[0].split()[-1] if total else 'n/a'}")
        subprocess.run([sys.executable, "-m", "coverage", "xml", "-q"], cwd=ROOT)
    if not args.no_model:
        model = [r for f in files if (r := run_file_retry(f, "model", False))["passed"] or r["failed"]
                 or not r["ok"]]
        ok = table("FinBERT model tests (one process per file)", model) and ok
    print(f"\n{'PASS' if ok else 'FAIL'}: test suite")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
