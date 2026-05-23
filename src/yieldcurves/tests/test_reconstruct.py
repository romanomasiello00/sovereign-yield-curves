from __future__ import annotations

import numpy as np

from yieldcurves.curves.reconstruct import (
    build_standard_grid,
    clean_curve_points,
    fit_linear_curve,
    fit_nelson_siegel_svensson,
    fit_pchip_curve,
    reconstruct_country_curve,
)
from yieldcurves.storage import build_row


def test_clean_curve_points():
    points = [(0.0, 1.0), (1.0, 2.0), (2.0, 3.0), (-1.0, 4.0)]
    cleaned = clean_curve_points(points)
    assert len(cleaned) == 2
    assert cleaned[0] == (1.0, 2.0)
    assert cleaned[1] == (2.0, 3.0)


def test_clean_curve_points_outliers():
    points = [(1.0, 100.0), (2.0, 2.0), (3.0, -10.0)]
    cleaned = clean_curve_points(points, min_rate=-5.0, max_rate=50.0)
    assert len(cleaned) == 1
    assert cleaned[0] == (2.0, 2.0)


def test_fit_linear_curve():
    points = [(1.0, 2.0), (5.0, 4.0), (10.0, 5.0)]
    target = [2.0, 3.0, 7.0]
    _, rates = fit_linear_curve(points, target)
    assert not np.any(np.isnan(rates))
    assert rates[0] > 2.0
    assert rates[0] < 4.0


def test_fit_linear_curve_too_few():
    import pytest

    with pytest.raises(ValueError, match="at least 2"):
        fit_linear_curve([(1.0, 2.0)], [2.0])


def test_fit_pchip_curve():
    points = [(1.0, 2.0), (3.0, 3.0), (5.0, 4.0), (10.0, 5.0)]
    target = [2.0, 4.0, 7.0]
    _, rates = fit_pchip_curve(points, target)
    assert not np.any(np.isnan(rates))
    assert rates[0] > 2.0


def test_fit_pchip_curve_too_few():
    import pytest

    with pytest.raises(ValueError, match="at least 2"):
        fit_pchip_curve([(1.0, 2.0)], [2.0])


def test_nelson_siegel_svensson():
    np.random.seed(42)
    ts = np.array([1.0, 2.0, 3.0, 5.0, 7.0, 10.0, 15.0, 20.0, 30.0])
    beta0, beta1, beta2, beta3, tau1, tau2 = 3.0, -1.0, 2.0, -1.0, 2.0, 5.0
    from yieldcurves.curves.reconstruct import _nss_yield

    ys = np.array([_nss_yield(T, beta0, beta1, beta2, beta3, tau1, tau2) for T in ts])
    points = list(zip(ts, ys))
    target = [2.0, 5.0, 10.0]
    _, rates, params = fit_nelson_siegel_svensson(points, target)
    assert params is not None
    assert not np.any(np.isnan(rates))


def test_reconstruct_country_curve_pchip():
    points = [(1.0, 2.0), (3.0, 3.0), (5.0, 4.0), (10.0, 5.0)]
    rows = reconstruct_country_curve(
        "NL", "2024-01-15", points,
        method_priority=["pchip", "linear"],
        extrapolation_limits=(0.5, 2.0),
    )
    assert len(rows) == 15  # 15 standard tenors
    valid = [r for r in rows if r["rate"] is not None]
    assert len(valid) > 0


def test_reconstruct_country_curve_too_few():
    rows = reconstruct_country_curve("NL", "2024-01-15", [(1.0, 2.0)])
    assert rows == []


def test_reconstruct_country_curve_linear_fallback():
    points = [(1.0, 2.0), (10.0, 5.0)]
    rows = reconstruct_country_curve(
        "NL", "2024-01-15", points,
        method_priority=["pchip", "linear"],
        extrapolation_limits=(0.5, 2.0),
    )
    assert len(rows) == 15


def test_extrapolation_limits():
    points = [(1.0, 2.0), (5.0, 4.0)]
    rows = reconstruct_country_curve(
        "NL", "2024-01-15", points,
        method_priority=["linear"],
        extrapolation_limits=(0.1, 0.5),
    )
    short_tenors = [r for r in rows if r["tenor_years"] < 1.0]
    long_tenors = [r for r in rows if r["tenor_years"] > 5.0]
    for r in short_tenors + long_tenors:
        if 0.5 - r["tenor_years"] > 0.1 or r["tenor_years"] - 5.0 > 0.5:
            is_bad = r["rate"] is None
            is_bad = is_bad or (isinstance(r["rate"], float) and np.isnan(r["rate"]))
            assert is_bad
