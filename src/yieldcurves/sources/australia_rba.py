from __future__ import annotations

from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd
import requests
from dateutil.parser import parse as parse_date
from tenacity import retry, stop_after_attempt, wait_exponential

from yieldcurves.config import source_config
from yieldcurves.curves.tenors import parse_tenor_label
from yieldcurves.hashing import compute_data_hash
from yieldcurves.parsers.csv import read_csv_from_bytes
from yieldcurves.storage import build_row, ingestion_timestamp, save_raw

_CFG = source_config("AU")
_COUNTRY_CODE = "AU"
_CURRENCY = "AUD"
_SOURCE_ID = "au_rba_f17_zero_coupon_yields"
_SOURCE_NAME = "Reserve Bank of Australia - F17 Zero-coupon Interest Rates"
_RATE_TYPE = "zero_spot"
_CURVE_FAMILY = "nominal_government"
_FIT_METHOD = "official"

_HEADER_TENOR_MAP: dict[str, str] = {
    "3 MONTHS": "3M",
    "6 MONTHS": "6M",
    "1 YEAR": "1Y",
    "2 YEARS": "2Y",
    "3 YEARS": "3Y",
    "5 YEARS": "5Y",
    "7 YEARS": "7Y",
    "10 YEARS": "10Y",
    "15 YEARS": "15Y",
    "3M": "3M",
    "6M": "6M",
    "1Y": "1Y",
    "2Y": "2Y",
    "3Y": "3Y",
    "5Y": "5Y",
    "7Y": "7Y",
    "10Y": "10Y",
    "15Y": "15Y",
}


def _normalise_date(val: Any) -> str | None:
    if pd.isna(val):
        return None
    if isinstance(val, datetime):
        return val.strftime("%Y-%m-%d")
    try:
        dt = parse_date(str(val))
        return dt.strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return None


def _find_header_row(lines: list[str]) -> tuple[int, list[str], dict[int, str]]:
    date_col = 0
    col_map: dict[int, str] = {}
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        parts = [p.strip().strip('"') for p in line.split(",")]
        if not parts:
            continue
        first = parts[0].upper()
        if first in ("DATE", "DATETIME", "OBSERVATION_DATE"):
            for j, p in enumerate(parts[1:], 1):
                upper = p.upper().strip()
                if upper in _HEADER_TENOR_MAP:
                    col_map[j] = _HEADER_TENOR_MAP[upper]
            if col_map:
                return i, parts, col_map
    return -1, [], {}


def _parse_csv(data: bytes, source_url: str) -> list[dict[str, Any]]:
    text = data.decode("utf-8-sig", errors="replace")
    lines = text.splitlines()
    header_idx, headers, col_map = _find_header_row(lines)
    if header_idx < 0 or not col_map:
        return []

    h = compute_data_hash(data)
    ts = ingestion_timestamp()
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, float]] = set()

    for line in lines[header_idx + 1:]:
        if not line.strip():
            continue
        parts = [p.strip().strip('"') for p in line.split(",")]
        if len(parts) <= max(col_map.keys()):
            continue
        date_str = _normalise_date(parts[0])
        if date_str is None:
            continue

        for col_idx, std_label in col_map.items():
            if col_idx >= len(parts):
                continue
            raw = parts[col_idx].strip()
            if not raw or raw in ("", ".", "..", "na", "N/A", "-"):
                continue
            try:
                rate = float(raw)
            except (ValueError, TypeError):
                continue
            if not np.isfinite(rate):
                continue

            ty = parse_tenor_label(std_label)
            if ty is None:
                continue
            key = (date_str, ty)
            if key in seen:
                continue
            seen.add(key)

            rows.append(
                build_row(
                    country_code=_COUNTRY_CODE,
                    country_name="Australia",
                    currency=_CURRENCY,
                    source_id=_SOURCE_ID,
                    source_name=_SOURCE_NAME,
                    source_url=source_url,
                    observation_date=date_str,
                    publication_date=date_str,
                    tenor_label=std_label,
                    tenor_years=ty,
                    rate=rate,
                    rate_unit="percent",
                    rate_type=_RATE_TYPE,
                    curve_family=_CURVE_FAMILY,
                    compounding="source_native",
                    day_count="source_native",
                    source_native_tenor=std_label,
                    source_native_curve_name="F17 Zero-coupon Interest Rates",
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


def fetch_all() -> list[dict[str, Any]]:
    url = _CFG["raw_data_url"]
    data = _download(url)
    save_raw(data, "f17-yields.csv")
    return _parse_csv(data, url)
