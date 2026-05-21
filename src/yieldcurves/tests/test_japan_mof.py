from __future__ import annotations

from yieldcurves.curves.tenors import parse_tenor_label
from yieldcurves.sources.japan_mof import _parse_csv, _parse_tenor_from_header


def test_parse_tenor_from_header():
    assert _parse_tenor_from_header("1Y") == 1.0
    assert _parse_tenor_from_header("10Y") == 10.0
    assert _parse_tenor_from_header("3M") == 0.25
    assert _parse_tenor_from_header("DATE") is None
    assert _parse_tenor_from_header("") is None


def test_parse_tenor_label():
    assert parse_tenor_label("1Y") == 1.0
    assert parse_tenor_label("10Y") == 10.0
    assert parse_tenor_label("3M") == 0.25
    assert parse_tenor_label("6M") == 0.5
    assert parse_tenor_label("50Y") == 50.0


def test_parse_csv_simple():
    csv_data = b"DATE,1Y,10Y\n2024-01-05,0.10,1.50\n2024-01-06,0.11,1.51\n"
    rows = _parse_csv(csv_data, "https://example.com/test.csv")
    assert len(rows) == 4
    assert rows[0]["country_code"] == "JP"
    assert rows[0]["currency"] == "JPY"
    assert rows[0]["rate_type"] == "constant_maturity_yield"
    assert rows[0]["curve_family"] == "nominal_government"
    assert rows[0]["compounding"] == "semiannual"
    assert rows[0]["fit_method"] == "official"


def test_parse_csv_with_bom():
    csv_data = b"\xef\xbb\xbfDATE,1Y,10Y\n2024-01-05,0.10,1.50\n"
    rows = _parse_csv(csv_data, "https://example.com/test.csv")
    assert len(rows) == 2


def test_parse_csv_skips_empty_rate():
    csv_data = b"DATE,1Y,10Y\n2024-01-05,,1.50\n"
    rows = _parse_csv(csv_data, "https://example.com/test.csv")
    assert len(rows) == 1
    assert rows[0]["tenor_years"] == 10.0
