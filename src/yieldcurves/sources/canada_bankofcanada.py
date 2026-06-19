from __future__ import annotations

import json
from typing import Any

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

from yieldcurves.config import source_config
from yieldcurves.curves.tenors import parse_tenor_label
from yieldcurves.hashing import compute_data_hash
from yieldcurves.storage import build_row, ingestion_timestamp, save_raw

_CFG = source_config("CA")
_COUNTRY_CODE = "CA"
_CURRENCY = "CAD"
_SOURCE_ID = "ca_boc_benchmark_bond_yields"
_SOURCE_NAME = "Bank of Canada - Selected benchmark bond yields (Valet)"
_RATE_TYPE = "bond_ytm"
_CURVE_FAMILY = "benchmark_government"
_FIT_METHOD = "direct_source"

# Bank of Canada Valet series id -> standard tenor label.
# RRB (real return bond) is excluded; LONG is the long-term benchmark (~30Y).
_SERIES_TENOR_MAP: dict[str, str] = {
    "BD.CDN.2YR.DQ.YLD": "2Y",
    "BD.CDN.3YR.DQ.YLD": "3Y",
    "BD.CDN.5YR.DQ.YLD": "5Y",
    "BD.CDN.7YR.DQ.YLD": "7Y",
    "BD.CDN.10YR.DQ.YLD": "10Y",
    "BD.CDN.LONG.DQ.YLD": "30Y",
}


def _parse_observations(data: bytes, source_url: str) -> list[dict[str, Any]]:
    """Parse Valet group observations JSON into normalised rows."""
    payload = json.loads(data.decode("utf-8", errors="replace"))
    observations = payload.get("observations", [])
    h = compute_data_hash(data)
    ts = ingestion_timestamp()
    rows: list[dict[str, Any]] = []

    for obs in observations:
        obs_date = obs.get("d")
        if not obs_date:
            continue
        for series_id, std_label in _SERIES_TENOR_MAP.items():
            cell = obs.get(series_id)
            if not cell or cell.get("v") in (None, ""):
                continue
            try:
                rate = float(cell["v"])
            except (ValueError, TypeError):
                continue
            ty = parse_tenor_label(std_label)
            if ty is None:
                continue
            rows.append(
                build_row(
                    country_code=_COUNTRY_CODE,
                    country_name="Canada",
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
                    source_native_tenor=series_id,
                    source_native_curve_name="bond_yields_benchmark",
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


def fetch_all(from_date: str = "1990-01-01") -> list[dict[str, Any]]:
    """Fetch Canada benchmark bond yields via the Bank of Canada Valet API.

    Pass from_date for incremental syncs.
    """
    base = _CFG["api_url"].rstrip("/")
    url = f"{base}/observations/group/bond_yields_benchmark/json?start_date={from_date}"
    data = _download(url)
    save_raw(data, "boc_bond_yields_benchmark.json")
    return _parse_observations(data, url)
