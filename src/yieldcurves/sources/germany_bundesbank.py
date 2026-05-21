from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd
import requests
from tenacity import retry, stop_after_attempt, wait_exponential

from yieldcurves.config import source_config
from yieldcurves.hashing import compute_data_hash
from yieldcurves.parsers.sdmx import parse_maturity_code
from yieldcurves.storage import build_row, save_raw

_CFG = source_config("DE")
_BASE = _CFG["api_base"]
_DATAFLOW = _CFG["dataflow"]
_COUNTRY_CODE = "DE"
_CURRENCY = "EUR"
_SOURCE_ID = "germany_bundesbank"
_SOURCE_NAME = "Deutsche Bundesbank"
_CURVE_FAMILY = "nominal_government"
_RATE_TYPE = "par_yield"
_COMPOUNDING = "annual"
_FIT_METHOD = "official"

_MATURITY_CODE_MAP: dict[str, float] = {
    "R01XX": 1.0,
    "R02XX": 2.0,
    "R03XX": 3.0,
    "R05XX": 5.0,
    "R07XX": 7.0,
    "R10XX": 10.0,
    "R15XX": 15.0,
    "R20XX": 20.0,
    "R25XX": 25.0,
    "R30XX": 30.0,
}


def discover_series() -> list[dict[str, Any]]:
    url = f"{_BASE}/dataflow/{_DATAFLOW}/all"
    params = {"format": "json", "detail": "full"}
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    series_list: list[dict[str, Any]] = []
    flows = data.get("data", {}).get("dataflows", [])
    dataflow_id = None
    for flow in flows:
        ref = flow.get("dataflow", {}).get("id", "") or flow.get("id", "")
        if ref == _DATAFLOW:
            dataflow_id = ref
            break
    if dataflow_id:
        series_list.append({"dataflow": dataflow_id, "name": _DATAFLOW})
    return series_list


def _download_series(key: str, start_date: str | None = None) -> tuple[bytes, str]:
    url = f"{_BASE}/data/{_DATAFLOW}/{key}"
    params: dict[str, str] = {"format": "bbk_csv"}
    if start_date:
        params["startPeriod"] = start_date
    resp = requests.get(url, params=params, timeout=60)
    resp.raise_for_status()
    csv_text = resp.text
    csv_bytes = csv_text.encode("utf-8")
    return csv_bytes, csv_text


def _parse_bbk_csv(csv_text: str, source_url: str) -> list[dict[str, Any]]:
    from io import StringIO

    df = pd.read_csv(StringIO(csv_text), encoding="utf-8-sig")
    if df.empty:
        return []
    date_col = None
    for candidate in ("DATE", "date", "Date", "TIME_PERIOD", "time_period"):
        if candidate in df.columns:
            date_col = candidate
            break
    if date_col is None:
        date_col = df.columns[0]
    obs_col = None
    for candidate in ("OBS_VALUE", "obs_value", "VALUE", "value"):
        if candidate in df.columns:
            obs_col = candidate
            break
    if obs_col is None:
        obs_col = df.columns[1] if len(df.columns) > 1 else None
    if obs_col is None:
        return []
    tenor_key_cols = [c for c in df.columns if c.startswith("R") and "X" in c]
    key_col = None
    if tenor_key_cols:
        key_col = tenor_key_cols[0]
    rows: list[dict[str, Any]] = []
    h = compute_data_hash(csv_text.encode("utf-8"))
    ts = datetime.utcnow().isoformat()
    for _, row in df.iterrows():
        obs_date = str(row.get(date_col, ""))
        if not obs_date:
            continue
        rate_val = row.get(obs_col)
        if pd.isna(rate_val):
            continue
        try:
            rate = float(rate_val)
        except (ValueError, TypeError):
            continue
        if key_col:
            raw_key = str(row.get(key_col, ""))
        elif "STRUCTURE" in df.columns:
            raw_key = str(row.get("STRUCTURE", ""))
        else:
            raw_key = ""
        ty = _MATURITY_CODE_MAP.get(raw_key, parse_maturity_code(raw_key) or 0.0)
        if ty <= 0:
            continue
        rows.append(
            build_row(
                country_code=_COUNTRY_CODE,
                country_name="Germany",
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
                day_count="ACT/ACT",
                source_native_tenor=raw_key,
                source_native_curve_name="Term Structure of Interest Rates",
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
def fetch_series(key: str, start_date: str | None = None) -> list[dict[str, Any]]:
    csv_bytes, csv_text = _download_series(key, start_date)
    save_raw(csv_bytes, f"bundesbank_{key}.csv")
    url = f"{_BASE}/data/{_DATAFLOW}/{key}"
    return _parse_bbk_csv(csv_text, url)


def discover_and_fetch() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for maturity_code in _MATURITY_CODE_MAP:
        key = f"D.I.ZAR.ZI.EUR.S1311.B.A604.{maturity_code}.R.A.A._Z._Z.A"
        try:
            rows.extend(fetch_series(key))
        except Exception:
            continue
    return rows


def fetch_all() -> list[dict[str, Any]]:
    return discover_and_fetch()
