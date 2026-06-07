from __future__ import annotations

from pathlib import Path

from yieldcurves.storage import (
    append_history,
    build_row,
    load_latest,
    normalize_rows,
    output_schema,
    replace_country_history,
    replace_country_latest,
    update_latest,
)

_ROW_KW = dict(
    country_code="JP",
    observation_date="2024-01-15",
    tenor_years=10.0,
    rate=1.5,
    rate_type="constant_maturity_yield",
    curve_family="nominal_government",
)


def test_output_schema():
    schema = output_schema()
    assert "country_code" in schema
    assert "observation_date" in schema
    assert "tenor_years" in schema
    assert "rate" in schema
    assert "rate_type" in schema
    assert "curve_family" in schema
    assert "fit_method" in schema
    assert "revision_id" in schema
    assert len(schema) > 20


def test_build_row_defaults():
    row = build_row(**_ROW_KW)
    assert row["country_code"] == "JP"
    assert row["tenor_years"] == 10.0
    assert row["rate"] == 1.5
    assert row["rate_unit"] == "percent"
    assert row["compounding"] == "source_native"
    assert row["fit_method"] == "direct_source"
    assert row["data_quality_flag"] == "ok"
    assert row["revision_id"] is not None
    assert len(row["revision_id"]) == 16


def test_normalize_rows():
    rows = [
        build_row(**_ROW_KW),
        build_row(**{**_ROW_KW, "tenor_years": 2.0, "rate": 0.5}),
    ]
    df = normalize_rows(rows)
    assert len(df) == 2
    assert list(df.columns) == list(output_schema())


def test_normalize_rows_empty():
    df = normalize_rows([])
    assert len(df) == 0
    assert list(df.columns) == list(output_schema())


def test_append_history(tmp_path: Path):
    df = normalize_rows([build_row(**_ROW_KW)])
    history_path = tmp_path / "history.parquet"
    result = append_history(df, history_path)
    assert result.exists()

    result2 = append_history(df, history_path)
    df2 = __import__("pandas").read_parquet(result2)
    assert len(df2) == 2


def test_update_latest(tmp_path: Path):
    df = normalize_rows([build_row(**_ROW_KW)])
    latest_path = tmp_path / "latest.parquet"
    result = update_latest(df, latest_path)
    assert result.exists()

    new_row = build_row(**{
        **_ROW_KW,
        "observation_date": "2024-01-16",
        "rate": 1.6,
    })
    df2 = normalize_rows([new_row])
    result2 = update_latest(df2, latest_path)
    df_combined = __import__("pandas").read_parquet(result2)
    assert len(df_combined) == 2


def test_load_latest_returns_empty_schema_when_missing(tmp_path: Path):
    df = load_latest(tmp_path / "missing.parquet")

    assert len(df) == 0
    assert list(df.columns) == list(output_schema())


def test_load_latest_quarantines_corrupt_parquet(tmp_path: Path):
    latest_path = tmp_path / "latest.parquet"
    latest_path.write_bytes(b"not parquet")

    df = load_latest(latest_path)

    assert len(df) == 0
    assert list(df.columns) == list(output_schema())
    assert not latest_path.exists()
    assert list(tmp_path.glob("latest.corrupt.*.parquet"))


def test_replace_country_history_and_latest(tmp_path: Path):
    jp = normalize_rows([build_row(**_ROW_KW)])
    it = normalize_rows([build_row(**{**_ROW_KW, "country_code": "IT", "rate": 2.5})])
    history_path = tmp_path / "history.parquet"
    latest_path = tmp_path / "latest.parquet"

    append_history(jp, history_path)
    append_history(it, history_path)
    update_latest(jp, latest_path)
    update_latest(it, latest_path)

    it_new = normalize_rows(
        [build_row(**{**_ROW_KW, "country_code": "IT", "observation_date": "2024-01-16", "rate": 3.0})]
    )
    replace_country_history("IT", it_new, history_path)
    replace_country_latest("IT", it_new, latest_path)

    history_df = __import__("pandas").read_parquet(history_path)
    latest_df = __import__("pandas").read_parquet(latest_path)

    assert sorted(history_df["country_code"].tolist()) == ["IT", "JP"]
    assert sorted(latest_df["country_code"].tolist()) == ["IT", "JP"]
    assert history_df[history_df["country_code"] == "IT"]["observation_date"].tolist() == ["2024-01-16"]
    assert latest_df[latest_df["country_code"] == "IT"]["observation_date"].tolist() == ["2024-01-16"]
