from __future__ import annotations

from yieldcurves.sources.sweden_riksbank import _parse_riksbank_json


def test_parse_riksbank_json_dict_format():
    data = {
        "observations": [
            {"date": "2024-06-28", "value": "3.50"},
            {"date": "2024-07-01", "value": "3.55"},
        ]
    }
    rows = _parse_riksbank_json(data, "SETB3MBENCH", "https://api.riksbank.se/swea/v1")
    assert len(rows) == 2
    assert rows[0]["country_code"] == "SE"
    assert rows[0]["currency"] == "SEK"
    assert rows[0]["tenor_label"] == "3M"
    assert rows[0]["rate"] == 3.50
    assert rows[1]["rate"] == 3.55


def test_parse_riksbank_json_list_format():
    data = [
        {"date": "2024-06-28", "value": "2.10"},
        {"date": "2024-07-01", "value": "2.15"},
    ]
    rows = _parse_riksbank_json(data, "SEGVB10YC", "https://api.riksbank.se/swea/v1")
    assert len(rows) == 2
    assert rows[0]["tenor_label"] == "10Y"
    assert rows[0]["rate"] == 2.10


def test_parse_riksbank_json_unknown_series():
    rows = _parse_riksbank_json({"observations": []}, "UNKNOWN", "")
    assert rows == []


def test_parse_riksbank_json_empty():
    rows = _parse_riksbank_json({}, "SETB3MBENCH", "")
    assert rows == []
