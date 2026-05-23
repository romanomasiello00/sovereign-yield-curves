from __future__ import annotations

from yieldcurves.sources.netherlands_dsta import _normalise_date, _safe_float


def test_safe_float():
    assert _safe_float(3.5) == 3.5
    assert _safe_float("3.5") == 3.5
    assert _safe_float(None) is None
    assert _safe_float(float("nan")) is None


def test_normalise_date():
    assert _normalise_date("2024-01-15") == "2024-01-15"
    assert _normalise_date("") is None
