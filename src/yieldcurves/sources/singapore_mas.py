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
    "6-MONTH": "6M",
    "1-YEAR": "1Y",
    "2-YEAR": "2Y",
    "5-YEAR": "5Y",
    "7-YEAR": "7Y",
    "10-YEAR": "10Y",
    "15-YEAR": "15Y",
    "20-YEAR": "20Y",
    "30-YEAR": "30Y",
    "50-YEAR": "50Y",
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


def _parse_html(html: bytes, source_url: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "lxml")
    tables = soup.find_all("table")
    if not tables:
        return []
    h = compute_data_hash(html)
    ts = ingestion_timestamp()
    date_str = _extract_date(soup)

    rows: list[dict[str, Any]] = []
    for table in tables:
        for tr in table.find_all("tr"):
            cells = tr.find_all(["th", "td"])
            if len(cells) < 2:
                continue
            header_text = cells[0].get_text(strip=True).upper()
            std_label = _TENOR_TEXT_MAP.get(header_text)
            if std_label is None:
                continue
            ty = parse_tenor_label(std_label)
            if ty is None:
                continue
            for cell in cells[1:]:
                text = cell.get_text(strip=True)
                if text and text.replace(".", "").replace("-", "").replace(",", "").isdigit():
                    try:
                        rate = float(text.replace(",", ""))
                    except (ValueError, TypeError):
                        continue
                    rows.append(
                        build_row(
                            country_code=_COUNTRY_CODE,
                            country_name="Singapore",
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
                            source_native_curve_name="SGS Benchmark Yields",
                            instrument_count_used=None,
                            fit_method=_FIT_METHOD,
                            is_interpolated=False,
                            is_extrapolated=False,
                            data_quality_flag="ok",
                            raw_file_hash=h,
                            ingestion_timestamp=ts,
                        )
                    )
                    break
    return rows


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
