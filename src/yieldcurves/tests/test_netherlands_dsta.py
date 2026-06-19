from __future__ import annotations

from yieldcurves.sources.netherlands_dsta import (
    _extract_doc_page_url,
    _extract_ods_url,
    _normalise_date,
    _safe_float,
)

_LANDING = """
<ul>
  <li><a href="/documents/2026/06/02/yields-on-dsls-from-2010-onwards">2010 onwards</a></li>
  <li><a href="/documents/2010/09/01/yields-on-dsls-from-2002-to-2009">2002-2009</a></li>
</ul>
"""

_DOC = """
<a href="https://english.dsta.nl/site/binaries/site-content/collections/documents/2026/06/02/yields-on-dsls-from-2010-onwards/mts-fixings-publicatie.ods">download</a>
"""


def test_extract_doc_page_url():
    url = _extract_doc_page_url(_LANDING, "https://english.dsta.nl")
    assert url == "https://english.dsta.nl/documents/2026/06/02/yields-on-dsls-from-2010-onwards"


def test_extract_doc_page_url_missing():
    assert _extract_doc_page_url("<a href='/foo'>x</a>", "https://english.dsta.nl") is None


def test_extract_ods_url():
    url = _extract_ods_url(_DOC, "https://english.dsta.nl")
    assert url.endswith("/mts-fixings-publicatie.ods")
    assert url.startswith("https://english.dsta.nl/site/binaries/")


def test_extract_ods_url_relative():
    html = '<a href="/site/binaries/x/mts-fixings-publicatie.ods">d</a>'
    assert _extract_ods_url(html, "https://english.dsta.nl") == (
        "https://english.dsta.nl/site/binaries/x/mts-fixings-publicatie.ods"
    )


def test_safe_float():
    assert _safe_float(3.5) == 3.5
    assert _safe_float("3.5") == 3.5
    assert _safe_float(None) is None
    assert _safe_float(float("nan")) is None


def test_normalise_date():
    assert _normalise_date("2024-01-15") == "2024-01-15"
    assert _normalise_date("") is None
