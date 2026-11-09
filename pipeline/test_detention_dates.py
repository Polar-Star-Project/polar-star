"""A past year's ICE workbook is dated by the end of that fiscal year, never by the day it was read."""
import csv
from pathlib import Path
from detention_stats import table_day


def test_past_workbook_dated_by_fiscal_year_end():
    assert table_day("FY19", "FY26", "2026-10-26") == "2019-09-30"
    assert table_day("FY26", "FY26", "2026-10-26") == "2026-10-26"


def test_no_snapshot_dated_after_its_fiscal_year():
    p = Path(__file__).resolve().parent.parent / "data" / "reference" / "ice_stats_snapshots.csv"
    for r in csv.DictReader(open(p, encoding="utf-8"), delimiter="|"):
        assert r["as_of"] <= f"20{int(r['fy'][2:4]) + 1}-12-31", r
