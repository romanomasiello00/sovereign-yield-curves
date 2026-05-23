from __future__ import annotations

from yieldcurves.sources.australia_rba import _find_header_row, _parse_csv


def test_find_header_row():
    lines = [
        '"Zero-coupon Interest Rates - F17"',
        '"Series ID","F17Y3MTH","F17Y10YR"',
        '"Series Name","3 months","10 years"',
        '"Unit","%","%"',
        "",
        "Date,3 months,10 years",
        "2024-06-28,4.12,3.80",
        "2024-07-01,4.15,3.75",
    ]
    idx, headers, col_map = _find_header_row(lines)
    assert idx == 5
    assert col_map[1] == "3M"
    assert col_map[2] == "10Y"


def test_parse_csv_simple():
    csv_data = b"Date,3 months,10 years\n2024-06-28,4.12,3.80\n2024-07-01,4.15,3.75\n"
    rows = _parse_csv(csv_data, "https://www.rba.gov.au/statistics/tables/csv/f17-yields.csv")
    assert len(rows) == 4
    assert rows[0]["country_code"] == "AU"
    assert rows[0]["currency"] == "AUD"
    assert rows[0]["rate_type"] == "zero_spot"
    assert rows[0]["tenor_label"] == "3M"
    assert rows[0]["rate"] == 4.12
    assert rows[3]["tenor_label"] == "10Y"
    assert rows[3]["rate"] == 3.75


def test_parse_csv_with_metadata():
    csv_data = (
        b'"Some metadata row"\n'
        b'"Another row"\n'
        b"Date,3 months,10 years\n"
        b"2024-06-28,4.12,3.80\n"
    )
    rows = _parse_csv(csv_data, "https://example.com")
    assert len(rows) == 2
    assert rows[0]["rate"] == 4.12


def test_parse_csv_empty_rate():
    csv_data = b"Date,3 months,10 years\n2024-06-28,,3.80\n"
    rows = _parse_csv(csv_data, "https://example.com")
    assert len(rows) == 1
    assert rows[0]["tenor_label"] == "10Y"


def test_parse_csv_no_header():
    csv_data = b"random,data\n1,2\n"
    rows = _parse_csv(csv_data, "https://example.com")
    assert rows == []
