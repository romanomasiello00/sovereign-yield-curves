"""Validate yield curve outputs after a sync run."""
from pathlib import Path

import duckdb
import pandas as pd

BASE = Path(__file__).resolve().parent.parent / "data" / "processed"
LATEST_PQ = BASE / "yield_curves_latest.parquet"
DUCKDB_FILE = BASE / "yield_curves.duckdb"
BDS_BASE = Path(__file__).resolve().parent.parent / "data" / "bds"
BDS_CATALOG = BDS_BASE / "series_catalog.parquet"


def print_latest_summary() -> None:
    if not LATEST_PQ.exists():
        print("No latest yield-curve parquet yet")
        return

    try:
        df = pd.read_parquet(LATEST_PQ)
    except Exception as exc:
        print(f"Skip latest parquet validation: {exc}")
        return

    print(f"Total rows: {len(df)}")
    print(f"Countries: {sorted(df['country_code'].unique())}")
    print(f"Date range: {df['observation_date'].min()} to {df['observation_date'].max()}")
    print(f"Rate types: {df['rate_type'].unique()}")
    print(f"Curve families: {df['curve_family'].unique()}")


def print_bds_summary() -> None:
    if not BDS_CATALOG.exists():
        return

    catalog = pd.read_parquet(BDS_CATALOG)
    print(f"BDS catalog rows: {len(catalog)}")
    for tier_path in sorted(BDS_BASE.glob("*/observations.parquet")):
        tier_df = pd.read_parquet(tier_path, columns=["series_id"])
        print(f"BDS {tier_path.parent.name} rows: {len(tier_df)}")


if not LATEST_PQ.exists() and not BDS_CATALOG.exists():
    print("No data yet -- first sync may be empty until sources are backfilled")
    raise SystemExit(0)

print_latest_summary()
print_bds_summary()

if DUCKDB_FILE.exists():
    con = duckdb.connect(str(DUCKDB_FILE))
    tables = con.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema='main'"
    ).fetchall()
    print(f"DuckDB tables: {[t[0] for t in tables]}")
    if any(t[0] == "yield_curves_latest" for t in tables):
        row_count = con.execute("SELECT count(*) FROM yield_curves_latest").fetchone()[0]
        print(f"DuckDB latest rows: {row_count}")
    con.close()
