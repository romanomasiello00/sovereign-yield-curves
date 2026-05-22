from __future__ import annotations

import pandas as pd

from yieldcurves.sources.netherlands_dsta import (
    _compute_maturity_years,
    _find_header_row,
    _normalise_date,
    _parse_sheet_dataframe,
    _parse_yield_column_name,
    _safe_float,
)


def test_safe_float():
    assert _safe_float(3.5) == 3.5
    assert _safe_float("3.5") == 3.5
    assert _safe_float(None) is None
    assert _safe_float(float("nan")) is None


def test_normalise_date():
    assert _normalise_date("2024-01-15") == "2024-01-15"
    assert _normalise_date("") is None


def test_parse_yield_column_name():
    assert _parse_yield_column_name("DSL 3.5% 2025") is not None
    assert _parse_yield_column_name("date") is None
    assert _parse_yield_column_name("Date") is None
    assert _parse_yield_column_name("") is None


def test_compute_maturity_years():
    years = _compute_maturity_years("2014-01-02", "2015-01-15")
    assert years is not None
    assert 1.0 < years < 1.1


def test_find_header_row():
    df = pd.DataFrame(
        [
            ["Qutation of sources:", None, None],
            ["Disclaimer", None, None],
            ["Date", "Maturity", "Yield"],
            ["2005-01-03", "2005-07-15", 0.02],
        ]
    )
    assert _find_header_row(df) is None

    df = pd.DataFrame(
        [
            ["Qutation of sources:", None, None, None],
            ["Disclaimer", None, None, None],
            ["Date", "Maturity", "ISIN code", "Yield"],
            ["2005-01-03", "2005-07-15", "NL0000102663", 0.02],
        ]
    )
    assert _find_header_row(df) == 2


def test_parse_sheet_dataframe_row_based_layout():
    df = pd.DataFrame(
        [
            ["Qutation of sources:", None, None, None, None],
            ["Disclaimer", None, None, None, None],
            [None, None, None, None, None],
            ["Date", "Maturity", "ISIN code", "Yield", "Description"],
            ["2005-01-03", "2005-07-15", "NL0000102663", 0.0214, "DSL test"],
            ["2005-01-03", "2010-01-15", "NL0000102309", 0.0307, "DSL test 2"],
        ]
    )
    rows = _parse_sheet_dataframe(df, "Daily Fixing 2005", "https://example.com", "hash")
    assert len(rows) == 2
    assert rows[0]["country_code"] == "NL"
    assert rows[0]["tenor_label"] == "6M"
    assert rows[0]["source_native_tenor"] == "NL0000102663"
    assert rows[1]["tenor_label"] == "5Y"
    assert rows[1]["curve_family"] == "nominal_government"
