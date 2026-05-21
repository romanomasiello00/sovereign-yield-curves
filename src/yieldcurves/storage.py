from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from yieldcurves.hashing import compute_data_hash

_OUTPUT_SCHEMA: dict[str, type] | None = None


def output_schema() -> dict[str, type]:
    global _OUTPUT_SCHEMA
    if _OUTPUT_SCHEMA is None:
        _OUTPUT_SCHEMA = {
            "country_code": str,
            "country_name": str,
            "currency": str,
            "source_id": str,
            "source_name": str,
            "source_url": str,
            "observation_date": str,
            "publication_date": str,
            "tenor_label": str,
            "tenor_years": float,
            "rate": float,
            "rate_unit": str,
            "rate_type": str,
            "curve_family": str,
            "compounding": str,
            "day_count": str,
            "source_native_tenor": str,
            "source_native_curve_name": str,
            "instrument_count_used": float,
            "fit_method": str,
            "is_interpolated": bool,
            "is_extrapolated": bool,
            "data_quality_flag": str,
            "raw_file_hash": str,
            "ingestion_timestamp": str,
            "revision_id": str,
        }
    return _OUTPUT_SCHEMA


def _empty_dataframe() -> pd.DataFrame:
    return pd.DataFrame({k: pd.Series(dtype=v) for k, v in output_schema().items()})


def _base_dir() -> Path:
    return Path(__file__).resolve().parent.parent.parent / "data"


def raw_dir() -> Path:
    p = _base_dir() / "raw"
    p.mkdir(parents=True, exist_ok=True)
    return p


def processed_dir() -> Path:
    p = _base_dir() / "processed"
    p.mkdir(parents=True, exist_ok=True)
    return p


def metadata_dir() -> Path:
    p = _base_dir() / "metadata"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _generate_revision_id() -> str:
    return uuid.uuid4().hex[:16]


def ingestion_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def save_raw(data: bytes, filename: str) -> tuple[Path, str]:
    h = compute_data_hash(data)
    dest = raw_dir() / f"{h[:16]}_{filename}"
    dest.write_bytes(data)
    return dest, h


def _coerce_dtypes(df: pd.DataFrame) -> pd.DataFrame:
    schema = output_schema()
    for col, dtype in schema.items():
        if col not in df.columns:
            df[col] = pd.Series(dtype=dtype)
        elif dtype is float:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        elif dtype is bool:
            df[col] = df[col].astype(bool)
        else:
            df[col] = df[col].astype(str).where(df[col].notna(), None)
    return df[list(schema)]


def build_row(**kwargs: Any) -> dict[str, Any]:
    ts = kwargs.pop("ingestion_timestamp", ingestion_timestamp())
    rev = kwargs.pop("revision_id", _generate_revision_id())
    row = {
        "country_code": kwargs.get("country_code"),
        "country_name": kwargs.get("country_name"),
        "currency": kwargs.get("currency"),
        "source_id": kwargs.get("source_id"),
        "source_name": kwargs.get("source_name"),
        "source_url": kwargs.get("source_url"),
        "observation_date": str(kwargs.get("observation_date", "")),
        "publication_date": str(kwargs.get("publication_date", "")),
        "tenor_label": kwargs.get("tenor_label"),
        "tenor_years": float(kwargs.get("tenor_years", 0.0)),
            "rate": float(kwargs["rate"]) if kwargs.get("rate") is not None else float("nan"),
        "rate_unit": kwargs.get("rate_unit", "percent"),
        "rate_type": kwargs.get("rate_type"),
        "curve_family": kwargs.get("curve_family"),
        "compounding": kwargs.get("compounding", "source_native"),
        "day_count": kwargs.get("day_count", "source_native"),
        "source_native_tenor": kwargs.get("source_native_tenor"),
        "source_native_curve_name": kwargs.get("source_native_curve_name"),
        "instrument_count_used": (
            float(kwargs["instrument_count_used"])
            if kwargs.get("instrument_count_used") is not None
            else float("nan")
        ),
        "fit_method": kwargs.get("fit_method", "direct_source"),
        "is_interpolated": bool(kwargs.get("is_interpolated", False)),
        "is_extrapolated": bool(kwargs.get("is_extrapolated", False)),
        "data_quality_flag": kwargs.get("data_quality_flag", "ok"),
        "raw_file_hash": kwargs.get("raw_file_hash", ""),
        "ingestion_timestamp": ts,
        "revision_id": rev,
    }
    return row


def normalize_rows(rows: list[dict[str, Any]]) -> pd.DataFrame:
    if not rows:
        return _empty_dataframe()
    df = pd.DataFrame(rows)
    return _coerce_dtypes(df)


def write_parquet(
    df: pd.DataFrame,
    path: Path,
    partition_cols: list[str] | None = None,
) -> Path:
    table = pa.Table.from_pandas(df, preserve_index=False)
    if partition_cols:
        pq.write_to_dataset(table, root_path=str(path), partition_cols=partition_cols)
    else:
        pq.write_table(table, str(path))
    return path


def duckdb_path() -> Path:
    return processed_dir() / "yield_curves.duckdb"


def open_duckdb() -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(duckdb_path()))


def bds_dir() -> Path:
    p = _base_dir() / "bds"
    p.mkdir(parents=True, exist_ok=True)
    return p


def bds_raw_dir() -> Path:
    p = bds_dir() / "raw"
    p.mkdir(parents=True, exist_ok=True)
    return p


def bds_catalog_path() -> Path:
    return bds_dir() / "series_catalog.parquet"


def bds_data_path(tier: str) -> Path:
    p = bds_dir() / tier
    p.mkdir(parents=True, exist_ok=True)
    return p / "observations.parquet"


def bds_duckdb_path() -> Path:
    return bds_dir() / "bds.duckdb"


def open_bds_duckdb() -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(bds_duckdb_path()))


def _table_exists(con: duckdb.DuckDBPyConnection, name: str) -> bool:
    result = con.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_name = ?", [name]
    ).fetchone()
    return result[0] > 0 if result else False


def sync_duckdb_from_parquet(
    latest_path: Path | None = None,
    history_path: Path | None = None,
):
    if latest_path is None:
        latest_path = processed_dir() / "yield_curves_latest.parquet"
    if history_path is None:
        history_path = processed_dir() / "yield_curves_history.parquet"

    con = open_duckdb()
    try:
        if latest_path.exists():
            con.execute(
                f"CREATE OR REPLACE TABLE yield_curves_latest AS "
                f"SELECT * FROM read_parquet('{latest_path}')"
            )
        if history_path.exists():
            con.execute(
                f"CREATE OR REPLACE TABLE yield_curves_history AS "
                f"SELECT * FROM read_parquet('{history_path}')"
            )
        con.execute(
            "CREATE OR REPLACE VIEW yield_curves AS "
            "SELECT * FROM yield_curves_latest"
        )
    finally:
        con.close()


def write_duckdb(df: pd.DataFrame, table_name: str, connection: duckdb.DuckDBPyConnection):
    connection.execute(f"CREATE OR REPLACE TABLE {table_name} AS SELECT * FROM df")


def sync_duckdb_after_write():
    sync_duckdb_from_parquet()


def append_history(
    new_rows: pd.DataFrame,
    history_path: Path | None = None,
) -> Path:
    if history_path is None:
        history_path = processed_dir() / "yield_curves_history.parquet"
    if new_rows.empty:
        return history_path
    if history_path.exists():
        existing = pd.read_parquet(history_path)
        combined = pd.concat([existing, new_rows], ignore_index=True)
    else:
        combined = new_rows
    write_parquet(combined, history_path)
    return history_path


def update_latest(
    new_rows: pd.DataFrame,
    latest_path: Path | None = None,
) -> Path:
    if latest_path is None:
        latest_path = processed_dir() / "yield_curves_latest.parquet"
    if new_rows.empty:
        return latest_path
    existing = pd.read_parquet(latest_path) if latest_path.exists() else _empty_dataframe()
    key_cols = [
        "country_code",
        "source_id",
        "observation_date",
        "tenor_years",
        "curve_family",
        "rate_type",
    ]
    merged = existing[~existing.set_index(key_cols).index.isin(new_rows.set_index(key_cols).index)]
    combined = pd.concat([merged, new_rows], ignore_index=True)
    write_parquet(combined, latest_path)
    return latest_path


def load_source_registry() -> pd.DataFrame:
    path = metadata_dir() / "source_registry.parquet"
    if path.exists():
        return pd.read_parquet(path)
    return pd.DataFrame(columns=["source_id", "last_observation_date", "last_raw_file_hash"])


def save_source_registry(df: pd.DataFrame):
    path = metadata_dir() / "source_registry.parquet"
    write_parquet(df, path)


def load_ingestion_log() -> pd.DataFrame:
    path = metadata_dir() / "ingestion_log.parquet"
    if path.exists():
        return pd.read_parquet(path)
    return pd.DataFrame(
        columns=["source_id", "ingestion_timestamp", "status", "rows_added", "raw_file_hash"]
    )


def append_ingestion_log(entry: dict[str, Any]):
    path = metadata_dir() / "ingestion_log.parquet"
    entry["ingestion_timestamp"] = entry.get("ingestion_timestamp", ingestion_timestamp())
    new = pd.DataFrame([entry])
    if path.exists():
        existing = pd.read_parquet(path)
        combined = pd.concat([existing, new], ignore_index=True)
    else:
        combined = new
    write_parquet(combined, path)
