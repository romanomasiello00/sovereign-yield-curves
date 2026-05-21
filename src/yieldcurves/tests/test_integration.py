from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import duckdb
import pandas as pd

import yieldcurves.storage as st
from yieldcurves.storage import (
    append_history,
    build_row,
    normalize_rows,
    sync_duckdb_after_write,
    update_latest,
)


def test_duckdb_persistence():
    tmpdir = Path(tempfile.mkdtemp())
    data_dir = tmpdir / "data"
    original_base = st._base_dir
    st._base_dir = lambda: data_dir

    try:
        rows = [
            build_row(
                country_code="JP", observation_date="2024-01-15",
                tenor_years=1.0, rate=0.1, source_id="japan_mof",
                rate_type="constant_maturity_yield",
                curve_family="nominal_government",
            ),
            build_row(
                country_code="JP", observation_date="2024-01-15",
                tenor_years=10.0, rate=1.5, source_id="japan_mof",
                rate_type="constant_maturity_yield",
                curve_family="nominal_government",
            ),
            build_row(
                country_code="GB", observation_date="2024-01-15",
                tenor_years=5.0, rate=3.2, source_id="uk_boe",
                rate_type="zero_spot",
                curve_family="nominal_government",
            ),
        ]
        df = normalize_rows(rows)
        df["country_name"] = "test"
        df["source_id"] = "test"

        append_history(df)
        update_latest(df)
        sync_duckdb_after_write()

        latest = pd.read_parquet(
            st.processed_dir() / "yield_curves_latest.parquet"
        )
        assert len(latest) == 3

        con = duckdb.connect(
            str(st.processed_dir() / "yield_curves.duckdb")
        )
        assert con.execute(
            "SELECT count(*) FROM yield_curves_latest"
        ).fetchone()[0] == 3
        assert con.execute(
            "SELECT count(*) FROM yield_curves_history"
        ).fetchone()[0] == 3
        assert con.execute(
            "SELECT count(*) FROM yield_curves"
        ).fetchone()[0] == 3
        con.close()

        rows2 = [
            build_row(
                country_code="JP", observation_date="2024-01-16",
                tenor_years=1.0, rate=0.11, source_id="japan_mof",
                rate_type="constant_maturity_yield",
                curve_family="nominal_government",
            ),
        ]
        df2 = normalize_rows(rows2)
        df2["country_name"] = "test"
        df2["source_id"] = "test"

        append_history(df2)
        update_latest(df2)
        sync_duckdb_after_write()

        con2 = duckdb.connect(
            str(st.processed_dir() / "yield_curves.duckdb")
        )
        assert con2.execute(
            "SELECT count(*) FROM yield_curves_latest"
        ).fetchone()[0] == 4
        assert con2.execute(
            "SELECT count(*) FROM yield_curves_history"
        ).fetchone()[0] == 4
        con2.close()

    finally:
        st._base_dir = original_base
        shutil.rmtree(tmpdir)
