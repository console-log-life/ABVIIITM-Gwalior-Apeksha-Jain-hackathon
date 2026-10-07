"""List public functions/methods in src/ whose body never ran during the test suite (from a coverage JSON report).

  python -m pytest -m "not model" --cov=app --cov=risk_engine --cov=portfolio --cov-report=json:.tmp/coverage.json
  python -m pytest -m model --cov=app --cov=risk_engine --cov=portfolio --cov-report=json:.tmp/coverage_model.json
  python src/scripts/list_untested.py --coverage .tmp/coverage.json .tmp/coverage_model.json [--out FILE.md]

"Public" = no leading underscore, in src/app, src/risk_engine or src/portfolio (Streamlit pages are exercised by
src/scripts/verify_dashboard.py instead). A function counts as tested when at least one line of its body (after the
signature and docstring) was executed.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGES = ["src/app", "src/risk_engine", "src/portfolio"]


def body_lines(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[int]:
    body = node.body
    if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant) \
            and isinstance(body[0].value.value, str):
        body = body[1:]
    lines: set[int] = set()
    for stmt in body:
        lines.update(range(stmt.lineno, (stmt.end_lineno or stmt.lineno) + 1))
    return lines


def public_functions(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name.startswith("_"):
            continue
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and not node.name.startswith("_"):
            yield node


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--coverage", nargs="+", default=[str(ROOT / ".tmp" / "coverage.json")],
                    help="one or more coverage JSON reports (the fast and model runs are separate processes)")
    ap.add_argument("--out", default=None, help="also write the list as Markdown")
    args = ap.parse_args()
    executed: dict[Path, set[int]] = {}
    for report in args.coverage:
        cov = json.loads(Path(report).read_text(encoding="utf-8"))
        for k, v in cov["files"].items():
            executed.setdefault(Path(k).resolve(), set()).update(v["executed_lines"])
    rows, total = [], 0
    for pkg in PACKAGES:
        for f in sorted((ROOT / pkg).rglob("*.py")):
            if "dashboard" in f.parts:
                continue
            ran = executed.get(f.resolve(), set())
            for fn in public_functions(f):
                lines = body_lines(fn)
                if not lines:
                    continue
                total += 1
                if not (lines & ran):
                    rows.append((f.relative_to(ROOT).as_posix(), fn.lineno, fn.name))
    print(f"{len(rows)} of {total} public functions never executed by the tests")
    for path, line, name in rows:
        print(f"  {path}:{line}  {name}")
    if args.out:
        md = [f"{len(rows)} of {total} public functions in {', '.join(PACKAGES)} were never executed by the test "
              f"suite (coverage reports: {', '.join(Path(r).name for r in args.coverage)}).",
              "", "| file | line | function |", "|---|---:|---|"]
        md += [f"| `{p}` | {ln} | `{n}` |" for p, ln, n in rows]
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text("\n".join(md) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
