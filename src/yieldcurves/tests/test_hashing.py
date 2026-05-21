from __future__ import annotations

from yieldcurves.hashing import compute_data_hash, compute_row_hash


def test_compute_data_hash():
    h1 = compute_data_hash(b"hello")
    h2 = compute_data_hash(b"hello")
    h3 = compute_data_hash(b"world")
    assert h1 == h2
    assert h1 != h3
    assert len(h1) == 64


BASE_ROW = {
    "country_code": "JP", "source_id": "japan_mof",
    "observation_date": "2024-01-15", "tenor_years": 10.0,
    "curve_family": "nominal_government", "rate_type": "constant_maturity_yield",
}


def test_compute_row_hash():
    row1 = {**BASE_ROW}
    row2 = {**BASE_ROW}
    row3 = {**BASE_ROW, "country_code": "GB", "source_id": "uk_boe", "rate_type": "zero_spot"}
    assert compute_row_hash(row1) == compute_row_hash(row2)
    assert compute_row_hash(row1) != compute_row_hash(row3)
