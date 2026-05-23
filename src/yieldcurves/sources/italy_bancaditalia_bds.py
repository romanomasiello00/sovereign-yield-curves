from __future__ import annotations

import io
import zipfile
from typing import Any

import requests

from yieldcurves.config import source_config
from yieldcurves.storage import build_row, ingestion_timestamp

_CFG = source_config("IT")
_COUNTRY_CODE = "IT"
_CURRENCY = "EUR"
_SOURCE_ID = "italy_bancaditalia"
_SOURCE_NAME = "Banca d'Italia"
_CURVE_FAMILY = "benchmark_government"
_RATE_TYPE = "benchmark_government_yield"
_FIT_METHOD = "direct_source"

_A2A_BASE = "https://a2a.bancaditalia.it/infostat/dataservices"

# BMK0200 column code -> (label, tenor_years)
_TENOR_MAP: dict[str, tuple[str, float | None]] = {
    "MFN_BMK.D.020.922.0.EUR.203": ("3Y", 3.0),
    "MFN_BMK.D.020.922.0.EUR.205": ("5Y", 5.0),
    "MFN_BMK.D.020.922.0.EUR.210": ("10Y", 10.0),
    "MFN_BMK.D.020.922.0.EUR.230": ("30Y", 30.0),
}


def _a2a_download(table_id: str) -> str:
    url = f"{_A2A_BASE}/export/EN/CSV/DATA/CUBE/BANKITALIA/DIFF/{table_id}"
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
        csv_name = [f for f in z.namelist() if f.endswith(".csv")][0]
        return z.read(csv_name).decode("latin1")


def _parse_bmk0200_csv(csv_text: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    ts = ingestion_timestamp()
    lines = csv_text.strip().split("\n")
    if not lines:
        return []

    headers = [h.strip().strip('"') for h in lines[0].split(";")]
    data_cols: list[tuple[int, str, float]] = []
    for i, h in enumerate(headers[1:], 1):
        if h in _TENOR_MAP:
            label, ty = _TENOR_MAP[h]
            if ty is not None:
                data_cols.append((i, label, ty))

    for line in lines[1:]:
        parts = [p.strip().strip('"') for p in line.split(";")]
        if len(parts) != len(headers):
            continue
        date_str = parts[0]
        if not date_str:
            continue
        obs_date = date_str.replace("/", "-")

        for col_idx, label, ty in data_cols:
            raw = parts[col_idx] if col_idx < len(parts) else ""
            if not raw:
                continue
            try:
                rate = float(raw)
            except (ValueError, TypeError):
                continue

            rows.append(
                build_row(
                    country_code=_COUNTRY_CODE,
                    country_name="Italy",
                    currency=_CURRENCY,
                    source_id=_SOURCE_ID,
                    source_name=_SOURCE_NAME,
                    source_url=f"{_A2A_BASE}/export/EN/CSV/DATA/CUBE/BANKITALIA/DIFF/BMK0200",
                    observation_date=obs_date,
                    publication_date=obs_date,
                    tenor_label=label,
                    tenor_years=ty,
                    rate=rate,
                    rate_unit="percent",
                    rate_type=_RATE_TYPE,
                    curve_family=_CURVE_FAMILY,
                    compounding="annual",
                    day_count="ACT/ACT",
                    source_native_tenor=label,
                    source_native_curve_name="BMK0200 Benchmark BTP Yields",
                    instrument_count_used=None,
                    fit_method=_FIT_METHOD,
                    is_interpolated=False,
                    is_extrapolated=False,
                    data_quality_flag="ok",
                    raw_file_hash="",
                    ingestion_timestamp=ts,
                )
            )
    return rows


def fetch_bmk0200() -> list[dict[str, Any]]:
    csv_text = _a2a_download("BMK0200")
    return _parse_bmk0200_csv(csv_text)


def fetch_all() -> list[dict[str, Any]]:
    try:
        return fetch_bmk0200()
    except Exception:
        return []
