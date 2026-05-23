from __future__ import annotations

from yieldcurves.sources.singapore_mas import _parse_html, _TENOR_TEXT_MAP


def test_tenor_text_map():
    assert _TENOR_TEXT_MAP["3-MONTH"] == "3M"
    assert _TENOR_TEXT_MAP["10-YEAR"] == "10Y"
    assert _TENOR_TEXT_MAP["50-YEAR"] == "50Y"


def test_parse_html_simple():
    html = b"""
    <html><body>
    <input id="ctl00_ContentPlaceHolder1_tbDate" value="2024-06-28" />
    <table>
      <tr><th>Tenor</th><th>Yield (%)</th></tr>
      <tr><td>3-MONTH</td><td>3.50</td></tr>
      <tr><td>10-YEAR</td><td>3.80</td></tr>
    </table>
    </body></html>
    """
    rows = _parse_html(html, "https://example.com")
    assert len(rows) == 2
    assert rows[0]["country_code"] == "SG"
    assert rows[0]["currency"] == "SGD"
    assert rows[0]["rate_type"] == "benchmark_government_yield"
    assert rows[0]["tenor_label"] == "3M"
    assert rows[0]["rate"] == 3.50
    assert rows[1]["tenor_label"] == "10Y"
    assert rows[1]["rate"] == 3.80


def test_parse_html_no_table():
    rows = _parse_html(b"<html><body>No table here</body></html>", "https://example.com")
    assert rows == []


def test_parse_html_empty_cells():
    html = b"""
    <html><body>
    <input id="ctl00_ContentPlaceHolder1_tbDate" value="2024-06-28" />
    <table>
      <tr><td>3-MONTH</td><td></td></tr>
      <tr><td>10-YEAR</td><td>--</td></tr>
    </table>
    </body></html>
    """
    rows = _parse_html(html, "https://example.com")
    assert len(rows) == 0
