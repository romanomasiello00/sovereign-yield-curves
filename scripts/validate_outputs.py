"""Validate yield curve outputs after a sync run."""
from pathlib import Path

import duckdb
import pandas as pd

BASE = Path(__file__).resolve().parent.parent / "data" / "processed"
LATEST_PQ = BASE / "yield_curves_latest.parquet"
DUCKDB_FILE = BASE / "yield_curves.duckdb"

if not LATEST_PQ.exists():
    print("No data yet -- first sync may be empty until sources are backfilled")
    raise SystemExit(0)

df = pd.read_parquet(LATEST_PQ)
print(f"Total rows: {len(df)}")
print(f"Countries: {sorted(df['country_code'].unique())}")
print(f"Date range: {df['observation_date'].min()} to {df['observation_date'].max()}")
print(f"Rate types: {df['rate_type'].unique()}")
print(f"Curve families: {df['curve_family'].unique()}")

if DUCKDB_FILE.exists():
    con = duckdb.connect(str(DUCKDB_FILE))
    tables = con.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema='main'"
    ).fetchall()
    print(f"DuckDB tables: {[t[0] for t in tables]}")
    row_count = con.execute("SELECT count(*) FROM yield_curves_latest").fetchone()[0]
    print(f"DuckDB latest rows: {row_count}")
    con.close()
