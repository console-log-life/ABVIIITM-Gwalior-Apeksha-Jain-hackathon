"""Round trip: labelled_headlines.csv -> label_review.xlsx -> (human edits) -> import -> CSV. Runs on a COPY."""

from __future__ import annotations

import csv
import shutil
import sys
from pathlib import Path

import pytest

load_workbook = pytest.importorskip("openpyxl").load_workbook  # dev dependency (requirements-dev.txt)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "scripts"))
import build_label_review  # noqa: E402
import import_label_review  # noqa: E402

CSV = ROOT / "data" / "eval" / "labelled_headlines.csv"


@pytest.fixture
def copies(tmp_path):
    csv_copy = tmp_path / "labels.csv"
    shutil.copy(CSV, csv_copy)
    xlsx = tmp_path / "review.xlsx"
    n = build_label_review.build(csv_copy, xlsx)
    return csv_copy, xlsx, n


def _col(ws, name):
    return [c.value for c in ws[1]].index(name) + 1


def test_sheet_has_no_predictions_and_has_dropdowns(copies):
    _, xlsx, n = copies
    wb = load_workbook(xlsx)
    ws = wb["Review"]
    headers = [c.value for c in ws[1]]
    assert ws.max_row == n + 1 and ws.freeze_panes == "C2"
    assert not any("pred" in h for h in headers)  # no model outputs to anchor the reviewer
    lists = {str(dv.sqref).split(":")[0].rstrip("0123456789"): dv.formula1
             for dv in ws.data_validations.dataValidation}
    letter = {h: ws.cell(row=1, column=_col(ws, h)).column_letter for h in
              ("sentiment_corrected", "event_corrected", "label_status")}
    assert lists[letter["sentiment_corrected"]] == '"Negative,Neutral,Positive"'
    assert lists[letter["label_status"]] == '"draft_agent,human_reviewed"'
    assert lists[letter["event_corrected"]].count(",") == 10  # exactly the 11 classes
    assert "How to review" in wb.sheetnames


def test_round_trip_applies_corrections_and_status(copies):
    csv_copy, xlsx, n = copies
    unchanged = import_label_review.import_review(xlsx, csv_copy)
    assert unchanged["labels_changed"] == 0 and unchanged["human_reviewed"] == 0 and unchanged["rows"] == n

    wb = load_workbook(xlsx)
    ws = wb["Review"]
    ws.cell(row=2, column=_col(ws, "sentiment_corrected")).value = "Positive"
    ws.cell(row=2, column=_col(ws, "event_corrected")).value = "M&A"
    ws.cell(row=2, column=_col(ws, "ticker_corrected")).value = "aapl"
    ws.cell(row=2, column=_col(ws, "label_status")).value = "human_reviewed"
    ws.cell(row=2, column=_col(ws, "reviewer_notes")).value = "checked"
    ws.cell(row=3, column=_col(ws, "label_status")).value = "human_reviewed"  # accepted draft
    first_id = str(ws.cell(row=2, column=1).value)
    wb.save(xlsx)

    stats = import_label_review.import_review(xlsx, csv_copy)
    assert stats["labels_changed"] == 1 and stats["human_reviewed"] == 2
    rows = {r["id"]: r for r in csv.DictReader(open(csv_copy, encoding="utf-8"))}
    r = rows[first_id]
    assert (r["gold_sentiment"], r["gold_event"], r["gold_ticker"], r["label_status"]) == \
        ("Positive", "M&A", "AAPL", "human_reviewed")
    assert r["notes"].startswith("reviewer: checked")
    assert sum(x["label_status"] == "human_reviewed" for x in rows.values()) == 2


def test_invalid_values_write_nothing(copies):
    csv_copy, xlsx, _ = copies
    before = csv_copy.read_text(encoding="utf-8")
    wb = load_workbook(xlsx)
    ws = wb["Review"]
    ws.cell(row=2, column=_col(ws, "event_corrected")).value = "Weather"
    ws.cell(row=3, column=_col(ws, "label_status")).value = "done"
    wb.save(xlsx)
    with pytest.raises(import_label_review.ReviewError) as exc:
        import_label_review.import_review(xlsx, csv_copy)
    assert "Weather" in str(exc.value) and "done" in str(exc.value)
    assert csv_copy.read_text(encoding="utf-8") == before
