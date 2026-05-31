from __future__ import annotations

import pandas as pd

from yieldcurves.cli import _filter_new_observations, _preserve_row_source_ids, _stable_frame_hash
from yieldcurves.config import source_config_by_name


def test_source_config_by_name_resolves_italy_sources():
    bancaditalia = source_config_by_name("italy_bancaditalia")

    assert bancaditalia["curve_family"] == "benchmark_government"


def test_preserve_row_source_ids_keeps_existing_values():
    df = pd.DataFrame(
        [
            {"source_id": "italy_bancaditalia", "rate": 3.1},
            {"source_id": None, "rate": 3.2},
            {"source_id": "", "rate": 3.3},
        ]
    )

    result = _preserve_row_source_ids(df, "it_default")

    assert result["source_id"].tolist() == ["italy_bancaditalia", "it_default", "it_default"]


def test_stable_frame_hash_ignores_runtime_fields():
    left = pd.DataFrame(
        [
            {
                "country_code": "IT",
                "source_id": "italy_bancaditalia",
                "observation_date": "2026-05-21",
                "tenor_years": 3.0,
                "curve_family": "nominal_government",
                "rate_type": "bond_ytm",
                "rate": 3.25,
                "ingestion_timestamp": "2026-05-23T10:00:00+00:00",
                "revision_id": "aaa",
            }
        ]
    )
    right = pd.DataFrame(
        [
            {
                "country_code": "IT",
                "source_id": "italy_bancaditalia",
                "observation_date": "2026-05-21",
                "tenor_years": 3.0,
                "curve_family": "nominal_government",
                "rate_type": "bond_ytm",
                "rate": 3.25,
                "ingestion_timestamp": "2026-05-23T11:00:00+00:00",
                "revision_id": "bbb",
            }
        ]
    )

    assert _stable_frame_hash(left) == _stable_frame_hash(right)


def test_filter_new_observations_keeps_only_rows_after_existing_cutoff():
    existing = pd.DataFrame(
        [
            {
                "country_code": "JP",
                "source_id": "japan_mof",
                "curve_family": "nominal_government",
                "rate_type": "constant_maturity_yield",
                "observation_date": "2026-05-27",
            }
        ]
    )
    fetched = pd.DataFrame(
        [
            {
                "country_code": "JP",
                "source_id": "japan_mof",
                "curve_family": "nominal_government",
                "rate_type": "constant_maturity_yield",
                "observation_date": "2026-05-27",
                "rate": 1.0,
            },
            {
                "country_code": "JP",
                "source_id": "japan_mof",
                "curve_family": "nominal_government",
                "rate_type": "constant_maturity_yield",
                "observation_date": "2026-05-28",
                "rate": 1.1,
            },
        ]
    )

    result = _filter_new_observations(fetched, existing)

    assert result["observation_date"].tolist() == ["2026-05-28"]
