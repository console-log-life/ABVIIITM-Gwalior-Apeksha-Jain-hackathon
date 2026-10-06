"""Pre-demo checklist. Prints GO / NO-GO.

NO-GO (blocking):  models missing for offline use · database not writable · port 8000 or 8501 busy ·
                   demo story or portfolio missing.
WARN (non-blocking): free RAM < 2 GB · live sources failing (probe; the demo itself needs no network) ·
                   no local captures (REPLAY then uses the committed 50-headline sample).

Usage:  python scripts/preflight.py [--skip-probe]
Does NOT load FinBERT (checks files only), so it is cheap to run right before a demo.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import ctypes
import importlib.util
import socket
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import get_settings  # noqa: E402

MIN_FREE_GB = 2.0
PROBE_TIMEOUT_S = 60


def free_ram_gb() -> float | None:
    if sys.platform == "win32":
        class MemStatus(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        st = MemStatus()
        st.dwLength = ctypes.sizeof(MemStatus)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
            return st.ullAvailPhys / 1024**3
        return None
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) / 1024**2
    except OSError:
        return None
    return None


def finbert_files_ok(models_dir: Path, name: str) -> tuple[bool, str]:
    repo = models_dir / ("models--" + name.replace("/", "--")) / "snapshots"
    snaps = [p for p in repo.glob("*") if p.is_dir()] if repo.exists() else []
    for snap in snaps:
        has_cfg = (snap / "config.json").exists()
        has_weights = (snap / "pytorch_model.bin").exists() or (snap / "model.safetensors").exists()
        has_tok = (snap / "vocab.txt").exists() or (snap / "tokenizer.json").exists()
        if has_cfg and has_weights and has_tok:
            return True, str(snap.relative_to(ROOT) if snap.is_relative_to(ROOT) else snap)
    return False, f"no complete snapshot under {repo} — run: python scripts/setup_models.py"


def db_writable(db: Path) -> tuple[bool, str]:
    try:
        db.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(db, timeout=3)
        con.execute("BEGIN IMMEDIATE")  # takes the write lock without changing anything
        con.execute("ROLLBACK")
        con.close()
        return True, str(db)
    except sqlite3.Error as exc:
        return False, f"{db}: {exc}"


def port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) != 0


def run_probe() -> str:
    import probe_sources  # scripts/ is on sys.path when run as a script

    results = probe_sources.run("AAPL", "stocks")
    ok = sorted({r.source.split("[")[0] for r in results if r.status == "PASS"})
    bad = sorted({r.source.split("[")[0] for r in results if r.status == "FAIL"})
    return f"PASS {ok or '-'}; FAIL {bad or '-'}"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skip-probe", action="store_true")
    args = ap.parse_args()
    sys.path.insert(0, str(ROOT / "scripts"))
    s = get_settings()
    rows: list[tuple[str, str, str]] = []  # (status, check, detail); status in OK/WARN/FAIL

    gb = free_ram_gb()
    rows.append(("OK" if gb is None or gb >= MIN_FREE_GB else "WARN", "free RAM",
                 "unknown" if gb is None else f"{gb:.1f} GB free (want >= {MIN_FREE_GB:.0f} GB; close browsers/IDE "
                 "tabs if lower)"))
    ok, detail = finbert_files_ok(s.models_dir, s.finbert_model)
    rows.append(("OK" if ok else "FAIL", "FinBERT available offline", detail))
    spacy_ok = importlib.util.find_spec("en_core_web_sm") is not None
    rows.append(("OK" if spacy_ok else "FAIL", "spaCy en_core_web_sm installed",
                 "ok" if spacy_ok else "run: python scripts/setup_models.py"))
    ok, detail = db_writable(s.db_file)
    rows.append(("OK" if ok else "FAIL", "database writable", detail))
    for port, what in ((s.api_port, "API"), (8501, "dashboard")):
        free = port_free(port)
        rows.append(("OK" if free else "FAIL", f"port {port} free ({what})",
                     "free" if free else "in use — stop the running server first"))
    story = s.resolve(s.demo_story_path)
    rows.append(("OK" if story.exists() else "FAIL", "demo story present", str(story.relative_to(ROOT))))
    if story.exists():
        from risk_engine.ingestion.scenario import load_opening, load_scenario

        try:
            opening = load_scenario(story).real_opening
            if opening is not None:
                n = len(load_opening(opening, ROOT))
                rows.append(("OK" if n == len(opening.doc_ids) else "WARN", "demo step 0 real headlines",
                             f"{n}/{len(opening.doc_ids)} found (CACHED_REAL sample)"))
        except Exception as exc:  # a broken story file must show up here, not during the presentation
            rows.append(("FAIL", "demo story valid", f"{type(exc).__name__}: {exc}"[:120]))
    from risk_engine import history

    hp = history.history_path(s)
    if history.is_fresh(s):
        meta = history.read_meta(hp) or {}
        rows.append(("OK", "REAL history cache", f"{meta.get('signals')} signals, {meta.get('stress_runs')} simulated "
                     f"runs ({meta.get('source')})"))
    else:
        rows.append(("WARN", "REAL history cache", "missing or stale: run tasks.ps1 real-history before the demo "
                     "(otherwise the API builds it at start-up, which takes minutes)"))
    pf = s.resolve(s.portfolio_path)
    rows.append(("OK" if pf.exists() else "WARN", "portfolio file present",
                 str(pf.relative_to(ROOT)) if pf.exists() else "missing: it will be generated (seed 42) on start"))
    captures = list((s.cache_path / "captures").glob("capture_*.jsonl"))
    sample = list((s.cache_path / "sample").glob("*.jsonl"))
    rows.append(("OK" if captures else ("WARN" if sample else "FAIL"), "REPLAY data",
                 f"{len(captures)} local capture files" if captures else
                 ("no local captures; REPLAY uses the committed 50-headline sample" if sample else "no cache at all")))
    if args.skip_probe:
        rows.append(("WARN", "live source probe", "skipped (--skip-probe)"))
    else:
        with concurrent.futures.ThreadPoolExecutor(1) as ex:
            fut = ex.submit(run_probe)
            try:
                rows.append(("OK", "live source probe (non-blocking)", fut.result(timeout=PROBE_TIMEOUT_S)))
            except Exception as exc:  # timeout or network failure: the demo itself works offline
                rows.append(("WARN", "live source probe (non-blocking)",
                             f"{type(exc).__name__}: use demo-offline / REPLAY"))

    width = max(len(r[1]) for r in rows)
    print("\nPRE-FLIGHT")
    for status, check, detail in rows:
        print(f"  {status:<4}  {check:<{width}}  {detail}")
    fails = [r for r in rows if r[0] == "FAIL"]
    warns = [r for r in rows if r[0] == "WARN"]
    print("\n" + ("NO-GO: fix the FAIL lines above." if fails else
                  f"GO{' (with ' + str(len(warns)) + ' warning(s))' if warns else ''}: "
                  "tasks.ps1 demo  (or demo-offline)"))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
