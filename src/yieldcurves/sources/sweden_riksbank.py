from __future__ import annotations

import time
from datetime import datetime
from typing import Any

import pandas as pd
import requests
from dateutil.parser import parse as parse_date
from tenacity import retry, stop_after_attempt, wait_exponential

from yieldcurves.config import source_config
from yieldcurves.curves.tenors import parse_tenor_label
from yieldcurves.hashing import compute_data_hash
from yieldcurves.storage import build_row, ingestion_timestamp, save_raw

_CFG = source_config("SE")
_COUNTRY_CODE = "SE"
_CURRENCY = "SEK"
_SOURCE_ID = "se_riksbank_market_rates"
_SOURCE_NAME = "Sveriges Riksbank - Swedish market rates API"
_RATE_TYPE = "constant_maturity_yield"
_CURVE_FAMILY = "benchmark_government"
_FIT_METHOD = "direct_source"
_API_BASE = _CFG["api_base"]


def _normalise_date(val: Any) -> str | None:
    if pd.isna(val):
        return None
    if isinstance(val, datetime):
        return val.strftime("%Y-%m-%d")
    try:
        return parse_date(str(val)).strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return None


def _parse_riksbank_json(data: dict, series_id: str, source_url: str) -> list[dict[str, Any]]:
    raw_bytes = str(data).encode("utf-8")
    h = compute_data_hash(raw_bytes)
    ts = ingestion_timestamp()

    series_cfg = None
    for label, s in _CFG.get("source_native_series", {}).items():
        if s["series_id"] == series_id:
            series_cfg = {"label": label, **s}
            break
    if series_cfg is None:
        return []

    std_label = series_cfg["label"]
    ty = parse_tenor_label(std_label)
    if ty is None:
        return []

    rows: list[dict[str, Any]] = []
    observations = data.get("observations", []) if isinstance(data, dict) else data

    for obs in observations:
        obs_date_str = obs.get("date") or obs.get("period") or obs.get("day")
        if not obs_date_str:
            continue
        obs_date = _normalise_date(obs_date_str)
        if obs_date is None:
            continue

        value_raw = obs.get("value") or obs.get("val")
        if value_raw is None:
            continue
        try:
            rate = float(str(value_raw).replace(",", "."))
        except (ValueError, TypeError):
            continue

        rows.append(
            build_row(
                country_code=_COUNTRY_CODE,
                country_name="Sweden",
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
                source_native_curve_name=f"Riksbank series {series_id}",
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


@retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=2, min=4, max=30))
def _fetch_series(series_id: str, from_date: str = "1990-01-01", to_date: str | None = None) -> tuple[bytes, str]:
    if to_date is None:
        to_date = datetime.now().strftime("%Y-%m-%d")
    url = f"{_API_BASE}/Observations/{series_id}/{from_date}/{to_date}"
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    raw = resp.content
    return raw, url


def fetch_all(from_date: str = "1990-01-01") -> list[dict[str, Any]]:
    """Fetch all series from the Riksbank API.

    Pass from_date for incremental syncs to avoid re-fetching full history.
    """
    rows: list[dict[str, Any]] = []
    series_map: dict[str, dict] = _CFG.get("source_native_series", {})
    for label_info in series_map.values():
        try:
            import json
            raw_data, url = _fetch_series(label_info["series_id"], from_date=from_date)
            save_raw(raw_data, f"riksbank_{label_info['series_id']}.json")
            data = json.loads(raw_data)
            rows.extend(_parse_riksbank_json(data, label_info["series_id"], url))
            time.sleep(1)
        except Exception:
            continue

    seen: set[tuple[str, float]] = set()
    deduped: list[dict[str, Any]] = []
    for row in rows:
        key = (row["observation_date"], row["tenor_years"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped
