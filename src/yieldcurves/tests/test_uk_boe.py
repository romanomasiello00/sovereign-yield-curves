from __future__ import annotations

import pandas as pd

from yieldcurves.sources.uk_boe import _normalise_date, _parse_boe_sheet


def test_normalise_date():
    assert _normalise_date("2024-01-15") == "2024-01-15"
    assert _normalise_date("15-Jan-2024") == "2024-01-15"
    assert _normalise_date(pd.NaT) is None
    assert _normalise_date("") is None


def test_parse_boe_sheet_mock():
    df = pd.DataFrame({
        0: ["Maturity", "months:", "years:", None, "2024-01-15", "2024-01-16"],
        1: [None, "1.0", "0.08333333", None, None, 3.5],
        2: [None, "2.0", "0.16666667", None, 4.0, 4.1],
        3: [None, "3.0", "0.25", None, 4.5, 4.6],
    })
    rows = _parse_boe_sheet(df, "https://example.com", "nominal_government",
                            "zero_spot", "test_sheet", "abc123")
    assert len(rows) == 5
    assert rows[0]["country_code"] == "GB"
    assert rows[0]["tenor_years"] == 0.16666667
    assert rows[0]["rate"] == 4.0
    assert rows[0]["rate_type"] == "zero_spot"
    assert rows[-1]["rate"] == 4.6


def test_empty_sheet():
    df = pd.DataFrame({0: []})
    rows = _parse_boe_sheet(df, "", "nominal_government",
                            "zero_spot", "empty", "x")
    assert rows == []


def test_no_date_column():
    df = pd.DataFrame({"A": [1, 2], "B": [3, 4]})
    rows = _parse_boe_sheet(df, "", "nominal_government",
                            "zero_spot", "no_date", "x")
    assert rows == []
