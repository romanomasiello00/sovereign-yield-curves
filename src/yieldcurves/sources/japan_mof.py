from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd
import requests
from dateutil.parser import parse as parse_date
from tenacity import retry, stop_after_attempt, wait_exponential

from yieldcurves.config import source_config
from yieldcurves.curves.tenors import parse_tenor_label
from yieldcurves.hashing import compute_data_hash
from yieldcurves.parsers.csv import read_csv_from_bytes
from yieldcurves.storage import (
    build_row,
    ingestion_timestamp,
    save_raw,
)

_CFG = source_config("JP")
_COUNTRY_CODE = "JP"
_CURRENCY = "JPY"
_SOURCE_ID = "japan_mof"
_SOURCE_NAME = "Japan Ministry of Finance"
_RATE_TYPE = "constant_maturity_yield"
_CURVE_FAMILY = "nominal_government"
_COMPOUNDING = "semiannual"
_FIT_METHOD = "official"


def _normalise_date(val: Any) -> str | None:
    if pd.isna(val):
        return None
    if isinstance(val, datetime):
        return val.strftime("%Y-%m-%d")
    try:
        return parse_date(str(val)).strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return None


def _parse_tenor_from_header(header: str) -> float | None:
    header_clean = header.strip().upper()
    if header_clean in ("", "DATE", "YEAR", "MONTH"):
        return None
    return parse_tenor_label(header_clean)


def _parse_csv(data: bytes, source_url: str) -> list[dict[str, Any]]:
    df = read_csv_from_bytes(data)
    if df.empty:
        return []
    df.columns = [str(c).strip() for c in df.columns]
    date_col = None
    for candidate in ("DATE", "date", "Date", "年月日"):
        if candidate in df.columns:
            date_col = candidate
            break
    if date_col is None:
        date_col = df.columns[0]
    tenor_map: dict[int, float] = {}
    for i, col in enumerate(df.columns):
        if col == date_col:
            continue
        ty = _parse_tenor_from_header(col)
        if ty is not None:
            tenor_map[i] = ty
    rows: list[dict[str, Any]] = []
    h = compute_data_hash(data)
    ts = ingestion_timestamp()
    for _, row in df.iterrows():
        obs_date = _normalise_date(row[date_col])
        if obs_date is None:
            continue
        for col_idx, ty in tenor_map.items():
            rate_val = row.iloc[col_idx]
            if pd.isna(rate_val):
                continue
            try:
                rate = float(rate_val)
            except (ValueError, TypeError):
                continue
            if ty <= 0:
                continue
            rows.append(
                build_row(
                    country_code=_COUNTRY_CODE,
                    country_name="Japan",
                    currency=_CURRENCY,
                    source_id=_SOURCE_ID,
                    source_name=_SOURCE_NAME,
                    source_url=source_url,
                    observation_date=obs_date,
                    publication_date=obs_date,
                    tenor_label=f"{int(ty * 12)}M" if ty < 1 else f"{int(ty)}Y",
                    tenor_years=ty,
                    rate=rate,
                    rate_unit="percent",
                    rate_type=_RATE_TYPE,
                    curve_family=_CURVE_FAMILY,
                    compounding=_COMPOUNDING,
                    day_count="source_native",
                    source_native_tenor=str(row.index[col_idx]) if col_idx < len(row) else "",
                    source_native_curve_name="JGB Constant Maturity",
                    instrument_count_used=None,
                    fit_method=_FIT_METHOD,
                    is_interpolated=False,
                    is_extrapolated=False,
                    data_quality_flag="ok",
                    raw_file_hash=h,
                    ingestion_timestamp=ts,
                )
            )
    return rows


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def _download(url: str) -> bytes:
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    return resp.content


def fetch_historical() -> list[dict[str, Any]]:
    url = _CFG["historical_url"]
    data = _download(url)
    save_raw(data, "jgbcme_all.csv")
    return _parse_csv(data, url)


def fetch_current() -> list[dict[str, Any]]:
    url = _CFG["current_url"]
    data = _download(url)
    save_raw(data, "jgbcme.csv")
    return _parse_csv(data, url)


def fetch_all() -> list[dict[str, Any]]:
    try:
        current = fetch_current()
    except Exception:
        current = []
    try:
        historical = fetch_historical()
    except Exception:
        historical = []
    seen = set()
    merged: list[dict[str, Any]] = []
    for row in current + historical:
        key = (row["observation_date"], row["tenor_years"])
        if key in seen:
            continue
        seen.add(key)
        merged.append(row)
    return merged
