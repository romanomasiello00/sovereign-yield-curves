from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd
import requests
from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_date
from tenacity import retry, stop_after_attempt, wait_exponential

from yieldcurves.config import source_config
from yieldcurves.curves.tenors import parse_tenor_label
from yieldcurves.hashing import compute_data_hash
from yieldcurves.storage import build_row, ingestion_timestamp, save_raw

_CFG = source_config("NO")
_COUNTRY_CODE = "NO"
_CURRENCY = "NOK"
_SOURCE_ID = "no_norgesbank_generic_yields"
_SOURCE_NAME = "Norges Bank - Generic yields"
_RATE_TYPE = "bond_ytm"
_CURVE_FAMILY = "benchmark_government"
_FIT_METHOD = "direct_source"

_TENOR_COLUMN_MAP: dict[str, str] = {
    "3 MONTHS": "3M",
    "3 MND": "3M",
    "3M": "3M",
    "6 MONTHS": "6M",
    "6 MND": "6M",
    "6M": "6M",
    "12 MONTHS": "12M",
    "12 MND": "12M",
    "12M": "12M",
    "3 YEARS": "3Y",
    "3 ÅR": "3Y",
    "3Y": "3Y",
    "5 YEARS": "5Y",
    "5 ÅR": "5Y",
    "5Y": "5Y",
    "7 YEARS": "7Y",
    "7 ÅR": "7Y",
    "7Y": "7Y",
    "10 YEARS": "10Y",
    "10 ÅR": "10Y",
    "10Y": "10Y",
}


def _normalise_date(val: Any) -> str | None:
    if pd.isna(val):
        return None
    if isinstance(val, datetime):
        return val.strftime("%Y-%m-%d")
    try:
        return parse_date(str(val)).strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return None


def _parse_html(html: bytes, source_url: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "lxml")
    tables = soup.find_all("table")
    if not tables:
        return []

    rows: list[dict[str, Any]] = []
    h = compute_data_hash(html)
    ts = ingestion_timestamp()

    for table in tables:
        headers = []
        header_row = table.find("tr")
        if header_row:
            for th in header_row.find_all(["th", "td"]):
                headers.append(th.get_text(strip=True).upper())

        col_map: dict[int, str] = {}
        date_col = -1
        for i, hdr in enumerate(headers):
            if hdr in ("DATE", "DATO", "DAY", "DAG"):
                date_col = i
            elif hdr in _TENOR_COLUMN_MAP:
                col_map[i] = _TENOR_COLUMN_MAP[hdr]

        if date_col < 0 or not col_map:
            continue

        for tr in table.find_all("tr")[1:]:
            cells = tr.find_all(["td", "th"])
            if len(cells) <= max(date_col, min(col_map.keys()) if col_map else 0):
                continue
            date_text = cells[date_col].get_text(strip=True)
            obs_date = _normalise_date(date_text)
            if obs_date is None:
                continue

            for col_idx, std_label in col_map.items():
                if col_idx >= len(cells):
                    continue
                cell_text = cells[col_idx].get_text(strip=True).replace(",", ".")
                if not cell_text or cell_text in ("", ".", "-", "N/A"):
                    continue
                try:
                    rate = float(cell_text)
                except (ValueError, TypeError):
                    continue
                ty = parse_tenor_label(std_label)
                if ty is None:
                    continue

                rows.append(
                    build_row(
                        country_code=_COUNTRY_CODE,
                        country_name="Norway",
                        currency=_CURRENCY,
                        source_id=_SOURCE_ID,
                        source_name=_SOURCE_NAME,
                        source_url=source_url,
                        observation_date=obs_date,
                        publication_date=obs_date,
                        tenor_label=std_label,
                        tenor_years=ty,
                        rate=rate,
                        rate_unit="percent",
                        rate_type=_RATE_TYPE,
                        curve_family=_CURVE_FAMILY,
                        compounding="source_native",
                        day_count="source_native",
                        source_native_tenor=std_label,
                        source_native_curve_name="Generic yields",
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
    data = _download(_CFG["source_url"])
    save_raw(data, "norgesbank_generic_yields.html")
    return _parse_html(data, _CFG["source_url"])
