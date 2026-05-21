from __future__ import annotations

from typing import Any

import pandas as pd
import requests
from tenacity import retry, stop_after_attempt, wait_exponential

from yieldcurves.config import source_config
from yieldcurves.storage import build_row

_CFG = source_config("IT")  # shares IT in config
_COUNTRY_CODE = "IT"
_CURRENCY = "EUR"
_SOURCE_ID = "italy_bancaditalia"
_SOURCE_NAME = "Banca d'Italia"
_CURVE_FAMILY = "benchmark_government"
_RATE_TYPE = "benchmark_government_yield"
_FIT_METHOD = "direct_source"

_BDS_BASE = "https://bds.infostat.it/bds"


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def fetch_bmk0200() -> pd.DataFrame:
    url = f"{_BDS_BASE}/api/v1/dataset/BMK0200/data"
    params = {"format": "csv", "lang": "en"}
    resp = requests.get(url, params=params, timeout=60)
    resp.raise_for_status()
    from io import StringIO

    df = pd.read_csv(StringIO(resp.text))
    return df


def parse_bmk0200(df: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        obs_date = str(row.get("date", row.get("DATA", "")))
        tenor_cols = [c for c in df.columns if c not in ("date", "DATA", "time", "TEMPO")]
        for col in tenor_cols:
            rate_val = row.get(col)
            if pd.isna(rate_val):
                continue
            try:
                tenor_years = float(col.replace("Y", "").replace("y", ""))
            except (ValueError, TypeError):
                continue
            rows.append(
                build_row(
                    country_code=_COUNTRY_CODE,
                    country_name="Italy",
                    currency=_CURRENCY,
                    source_id=_SOURCE_ID,
                    source_name=_SOURCE_NAME,
                    source_url=f"{_BDS_BASE}/dataset/BMK0200",
                    observation_date=obs_date,
                    publication_date=obs_date,
                    tenor_label=col,
                    tenor_years=tenor_years,
                    rate=float(rate_val),
                    rate_unit="percent",
                    rate_type=_RATE_TYPE,
                    curve_family=_CURVE_FAMILY,
                    compounding="annual",
                    day_count="ACT/ACT",
                    source_native_tenor=col,
                    source_native_curve_name="BMK0200 Benchmark Yields",
                    instrument_count_used=None,
                    fit_method=_FIT_METHOD,
                    is_interpolated=False,
                    is_extrapolated=False,
                    data_quality_flag="ok",
                    raw_file_hash="",
                    ingestion_timestamp=pd.Timestamp.utcnow().isoformat(),
                )
            )
    return rows


def validate_btp_curve(
    borsa_rows: list[dict[str, Any]],
    bdi_rows: list[dict[str, Any]],
) -> pd.DataFrame:
    borsa_df = pd.DataFrame(borsa_rows)
    bdi_df = pd.DataFrame(bdi_rows)
    results: list[dict[str, Any]] = []
    for _, bdi_row in bdi_df.iterrows():
        mask = (
            (borsa_df["observation_date"] == bdi_row["observation_date"])
            & (borsa_df["tenor_years"] == bdi_row["tenor_years"])
            & (borsa_df["rate_type"] == "reconstructed_curve_yield")
        )
        match = borsa_df[mask]
        if match.empty:
            continue
        borsa_rate = match.iloc[0]["rate"]
        bdi_rate = bdi_row["rate"]
        results.append(
            {
                "date": bdi_row["observation_date"],
                "tenor": bdi_row["tenor_years"],
                "reconstructed_rate": borsa_rate,
                "official_benchmark_rate": bdi_rate,
                "difference_bp": (borsa_rate - bdi_rate) * 100,
            }
        )
    return pd.DataFrame(results)


def fetch_all() -> list[dict[str, Any]]:
    try:
        df = fetch_bmk0200()
        return parse_bmk0200(df)
    except Exception:
        return []
