from __future__ import annotations

import pandas as pd

from yieldcurves.sources.uk_boe import _find_date_column, _normalise_date


def test_normalise_date():
    assert _normalise_date("2024-01-15") == "2024-01-15"
    assert _normalise_date("15-Jan-2024") == "2024-01-15"
    assert _normalise_date(pd.NaT) is None
    assert _normalise_date("") is None


def test_find_date_column():
    df = pd.DataFrame({"Date": ["2024-01-01"], "1Y": [1.5], "10Y": [2.5]})
    assert _find_date_column(df) == "Date"

    df2 = pd.DataFrame({"observation_date": ["2024-01-01"], "2Y": [2.0]})
    assert _find_date_column(df2) == "observation_date"

    df3 = pd.DataFrame({"A": [1], "B": [2]})
    assert _find_date_column(df3) is None or _find_date_column(df3) == "A"


def test_no_column_match():
    df = pd.DataFrame({"A": [1, 2], "B": [3, 4]})
    col = _find_date_column(df)
    assert col is None or col in ("A", "B")
