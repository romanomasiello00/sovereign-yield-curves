from __future__ import annotations

from yieldcurves.sources.norway_norgesbank import _parse_html


def test_parse_html_simple():
    html = """
    <html><body>
    <table>
      <tr><th>Date</th><th>3M</th><th>10Y</th></tr>
      <tr><td>2024-06-28</td><td>4.50</td><td>3.80</td></tr>
      <tr><td>2024-07-01</td><td>4.45</td><td>3.75</td></tr>
    </table>
    </body></html>
    """.encode("utf-8")
    rows = _parse_html(html, "https://www.norges-bank.no")
    assert len(rows) == 4
    assert rows[0]["country_code"] == "NO"
    assert rows[0]["currency"] == "NOK"
    assert rows[0]["rate_type"] == "bond_ytm"
    assert rows[0]["tenor_label"] == "3M"
    assert rows[0]["rate"] == 4.50
    assert rows[2]["tenor_label"] == "3M"
    assert rows[2]["rate"] == 4.45


def test_parse_html_norwegian_headers():
    html = """
    <html><body>
    <table>
      <tr><th>Dato</th><th>3 MND</th><th>10 ÅR</th></tr>
      <tr><td>2024-06-28</td><td>4.50</td><td>3.80</td></tr>
    </table>
    </body></html>
    """.encode("utf-8")
    rows = _parse_html(html, "https://www.norges-bank.no")
    assert len(rows) == 2
    assert rows[0]["tenor_label"] == "3M"
    assert rows[1]["tenor_label"] == "10Y"


def test_parse_html_no_table():
    rows = _parse_html(b"<html><body>No data</body></html>", "https://www.norges-bank.no")
    assert rows == []


def test_parse_html_empty_cells():
    html = """
    <html><body>
    <table>
      <tr><th>Date</th><th>3M</th><th>10Y</th></tr>
      <tr><td>2024-06-28</td><td>-</td><td></td></tr>
    </table>
    </body></html>
    """.encode("utf-8")
    rows = _parse_html(html, "https://www.norges-bank.no")
    assert len(rows) == 0
