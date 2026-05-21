from __future__ import annotations

from yieldcurves.sources.italy_borsa import (
    _compute_maturity_years,
    _is_valid_btp,
    _normalise_date,
    _safe_float,
)


def test_safe_float():
    assert _safe_float("3.5") == 3.5
    assert _safe_float("3,5") == 3.5
    assert _safe_float(None) is None


def test_normalise_date():
    assert _normalise_date("2024-01-15") == "2024-01-15"
    assert _normalise_date("") is None
    assert _normalise_date(None) is None


def test_is_valid_btp():
    valid = {
        "issuer": "REPUBLIC OF ITALY",
        "bond_structure": "Plain Vanilla",
        "annual_coupon_rate": 3.5,
        "gross_ytm": 2.5,
        "expiry_date": "2030-09-15",
    }
    assert _is_valid_btp(valid, description="BTP 3.5% 2030")

    invalid_issuer = dict(valid)
    invalid_issuer["issuer"] = "FRENCH REPUBLIC"
    assert not _is_valid_btp(invalid_issuer, description="BTP 3.5% 2030")

    invalid_btpi = dict(valid)
    assert not _is_valid_btp(invalid_btpi, description="BTP Italia 2028")

    invalid_no_ytm = dict(valid)
    invalid_no_ytm["gross_ytm"] = None
    assert not _is_valid_btp(invalid_no_ytm, description="BTP 3.5% 2030")


def test_compute_maturity_years():
    my = _compute_maturity_years("2030-06-15", "2024-01-15")
    assert my is not None
    assert my > 6.0
    assert my < 7.0

    my2 = _compute_maturity_years("2020-01-01", "2024-01-15")
    assert my2 is None
