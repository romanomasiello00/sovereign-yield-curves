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

_CFG = source_config("SG")
_COUNTRY_CODE = "SG"
_CURRENCY = "SGD"
_SOURCE_ID = "sg_mas_sgs_benchmark_yields"
_SOURCE_NAME = "Monetary Authority of Singapore - SGS Benchmark Yields"
_RATE_TYPE = "benchmark_government_yield"
_CURVE_FAMILY = "benchmark_government"
_FIT_METHOD = "direct_source"

_TENOR_TEXT_MAP: dict[str, str] = {
    "3-MONTH": "3M",
    "3-MTH": "3M",
    "6-MONTH": "6M",
    "6-MTH": "6M",
    "1-YEAR": "1Y",
    "1-YR": "1Y",
    "2-YEAR": "2Y",
    "2-YR": "2Y",
    "5-YEAR": "5Y",
    "5-YR": "5Y",
    "7-YEAR": "7Y",
    "7-YR": "7Y",
    "10-YEAR": "10Y",
    "10-YR": "10Y",
    "15-YEAR": "15Y",
    "15-YR": "15Y",
    "20-YEAR": "20Y",
    "20-YR": "20Y",
    "30-YEAR": "30Y",
    "30-YR": "30Y",
    "50-YEAR": "50Y",
    "50-YR": "50Y",
    "3M": "3M",
    "6M": "6M",
    "1Y": "1Y",
    "2Y": "2Y",
    "5Y": "5Y",
    "7Y": "7Y",
    "10Y": "10Y",
    "15Y": "15Y",
    "20Y": "20Y",
    "30Y": "30Y",
    "50Y": "50Y",
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


def _extract_date(soup: BeautifulSoup) -> str:
    candidates = [
        soup.find("input", {"id": "ctl00_ContentPlaceHolder1_tbDate"}),
        soup.find("input", {"type": "text", "name": "tbDate"}),
        soup.find("span", {"id": "ctl00_ContentPlaceHolder1_lblDate"}),
        soup.find("span", {"class": "date"}),
    ]
    for el in candidates:
        if el:
            val = el.get("value") or el.get_text(strip=True)
            if val:
                result = _normalise_date(val)
                if result:
                    return result
    date_texts = soup.find_all(string=True)
    for t in date_texts:
        cleaned = t.strip()
        if cleaned and cleaned.replace("-", "").replace("/", "").isdigit() and len(cleaned) >= 8:
            result = _normalise_date(cleaned)
            if result:
                return result
    return datetime.now().strftime("%Y-%m-%d")


def _build_row_entry(
    obs_date: str,
    tenor_label: str,
    rate: float,
    source_url: str,
    h: str,
    ts: str,
) -> dict[str, Any]:
    ty = parse_tenor_label(tenor_label)
    if ty is None:
        return {}
    return build_row(
        country_code=_COUNTRY_CODE,
        country_name="Singapore",
        currency=_CURRENCY,
        source_id=_SOURCE_ID,
        source_name=_SOURCE_NAME,
        source_url=source_url,
        observation_date=obs_date,
        publication_date=obs_date,
        tenor_label=tenor_label,
        tenor_years=ty,
        rate=rate,
        rate_unit="percent",
        rate_type=_RATE_TYPE,
        curve_family=_CURVE_FAMILY,
        compounding="source_native",
        day_count="source_native",
        source_native_tenor=tenor_label,
        source_native_curve_name="SGS Benchmark Yields",
        instrument_count_used=None,
        fit_method=_FIT_METHOD,
        is_interpolated=False,
        is_extrapolated=False,
        data_quality_flag="ok",
        raw_file_hash=h,
        ingestion_timestamp=ts,
    )


def _safe_float(text: str) -> float | None:
    cleaned = text.strip().replace(",", "")
    try:
        v = float(cleaned)
        return v if v > 0 else None
    except (ValueError, TypeError):
        return None


def _detect_column_map(all_rows: list) -> tuple[dict[int, str], int]:
    """Detect tenor→column mapping and first data row index.

    MAS table structure (post-2020):
      Row 0: category headers (Treasury Bills / Bonds, with colspan)
      Row 1: tenor labels (6-Mth, 1-Year, 2-Year colspan=2, ...)
      Row 2: issue codes (rowspan=2 in col 0 occupies date slot in row 3)
      Row 3: Yield/Price sub-headers (16 cells, col 0 is Yield for 6M)
      Row 4+: data rows (17 cells: Date + 16 values)

    Because row 2 col 0 has rowspan=2, the actual data column layout is:
      col 0 = Date
      col 1 = 6M Yield (T-bill)
      col 2 = 1Y Yield (T-bill)
      col 3 = 2Y Price  (bond)
      col 4 = 2Y Yield  (bond)
      col 5 = 5Y Price  (bond)
      col 6 = 5Y Yield  (bond)
      col 7 = 10Y Price (bond)
      col 8 = 10Y Yield (bond)
      col 9 = 15Y Price (bond)
      col 10= 15Y Yield (bond)
      col 11= 20Y Price (bond)
      col 12= 20Y Yield (bond)
      col 13= 30Y Price (bond)
      col 14= 30Y Yield (bond)
      col 15= 50Y Price (bond)
      col 16= 50Y Yield (bond)
    """
    for i, tr in enumerate(all_rows):
        cells = tr.find_all(["th", "td"])
        raw_labels = [c.get_text(strip=True).upper() for c in cells]
        tenor_hits = [_TENOR_TEXT_MAP.get(lbl) for lbl in raw_labels if _TENOR_TEXT_MAP.get(lbl)]
        if len(tenor_hits) < 3:
            continue

        # Found tenor header row at index i; resolve column mapping by expanding colspan
        physical_col = 0
        tenor_col_map: dict[int, str] = {}
        for cell in cells:
            lbl = cell.get_text(strip=True).upper()
            std = _TENOR_TEXT_MAP.get(lbl)
            span = int(cell.get("colspan", 1))
            if std:
                # T-bills: no price column; bonds: Price col first, Yield col second
                if span == 1:
                    tenor_col_map[physical_col] = std
                else:
                    # The Yield is the second of the two colspan columns
                    tenor_col_map[physical_col + 1] = std
            physical_col += span

        # Scan forward to find first data row (date in col 0)
        for k in range(i + 1, len(all_rows)):
            candidate = all_rows[k].find_all(["td", "th"])
            if candidate and _normalise_date(candidate[0].get_text(strip=True)):
                return tenor_col_map, k

    return {}, -1


def _parse_html(html: bytes, source_url: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "lxml")
    tables = soup.find_all("table")
    if not tables:
        return []
    h = compute_data_hash(html)
    ts = ingestion_timestamp()
    rows: list[dict[str, Any]] = []

    for table in tables:
        all_rows = table.find_all("tr")
        if len(all_rows) < 3:
            continue

        tenor_col_map, data_start = _detect_column_map(all_rows)

        if not tenor_col_map or data_start < 0:
            # Fallback: old format where each row has a tenor name in first cell
            for tr in all_rows:
                cells = tr.find_all(["th", "td"])
                if len(cells) < 2:
                    continue
                header_text = cells[0].get_text(strip=True).upper()
                std_label = _TENOR_TEXT_MAP.get(header_text)
                if std_label is None:
                    continue
                for cell in cells[1:]:
                    v = _safe_float(cell.get_text(strip=True))
                    if v is not None:
                        obs_date = _extract_date(soup)
                        entry = _build_row_entry(obs_date, std_label, v, source_url, h, ts)
                        if entry:
                            rows.append(entry)
                        break
            continue

        for tr in all_rows[data_start:]:
            cells = tr.find_all(["td", "th"])
            if not cells:
                continue
            obs_date = _normalise_date(cells[0].get_text(strip=True))
            if obs_date is None:
                continue
            for col_idx, std_label in tenor_col_map.items():
                if col_idx >= len(cells):
                    continue
                v = _safe_float(cells[col_idx].get_text(strip=True))
                if v is None:
                    continue
                entry = _build_row_entry(obs_date, std_label, v, source_url, h, ts)
                if entry:
                    rows.append(entry)

    seen: set[tuple[str, float]] = set()
    deduped: list[dict[str, Any]] = []
    for row in rows:
        key = (str(row.get("observation_date")), float(row.get("tenor_years", 0)))
        if key not in seen:
            seen.add(key)
            deduped.append(row)
    return deduped


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def _download(url: str) -> bytes:
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    return resp.content


def fetch_all() -> list[dict[str, Any]]:
    url = _CFG.get("daily_page_url", _CFG["source_url"])
    data = _download(url)
    save_raw(data, "mas_benchmark_yields.html")
    return _parse_html(data, url)
