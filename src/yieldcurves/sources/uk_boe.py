from __future__ import annotations

import io
import zipfile
from datetime import datetime
from typing import Any

import pandas as pd
import requests
from tenacity import retry, stop_after_attempt, wait_exponential

from yieldcurves.config import source_config
from yieldcurves.hashing import compute_data_hash
from yieldcurves.storage import build_row, save_raw

_CFG = source_config("GB")
_COUNTRY_CODE = "GB"
_CURRENCY = "GBP"
_SOURCE_ID = "uk_boe"
_SOURCE_NAME = "Bank of England"
_RATE_TYPES = {
    "nominal": ("zero_spot", "nominal_government"),
    "real": ("zero_spot", "real_government"),
    "inflation": ("zero_spot", "inflation"),
    "ois": ("ois_zero_spot", "ois"),
}
_COMPOUNDING = "continuous"
_FIT_METHOD = "official"

_CURVE_SHEET_MAP: dict[str, str] = {
    "spot curve": "spot",
    "spot, short end": "spot_short",
    "fwd curve": "forward",
    "fwds, short end": "forward_short",
}


def _normalise_date(val: Any) -> str | None:
    if pd.isna(val):
        return None
    if isinstance(val, datetime):
        return val.strftime("%Y-%m-%d")
    s = str(val).strip()
    if s and s != "nan":
        try:
            from dateutil.parser import parse as parse_date
            return parse_date(s).strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            return None
    return None


def _parse_boe_sheet(
    df_raw: pd.DataFrame,
    source_url: str,
    curve_family: str,
    rate_type: str,
    sheet_name: str,
    raw_file_hash: str,
) -> list[dict[str, Any]]:
    if df_raw.shape[1] < 2:
        return []
    tenor_row_idx = None
    data_start = None
    for i in range(min(6, len(df_raw))):
        first_cell = str(df_raw.iloc[i, 0]).strip().lower()
        if first_cell == "years:" or first_cell == "year:":
            tenor_row_idx = i
        elif not tenor_row_idx and first_cell == "maturity":
            continue
        if i > 0:
            try:
                pd.to_datetime(str(df_raw.iloc[i, 0]), errors="raise")
                data_start = i
                break
            except (ValueError, TypeError):
                pass
    if tenor_row_idx is None:
        return []
    tenor_map: dict[int, float] = {}
    for j in range(1, df_raw.shape[1]):
        val = df_raw.iloc[tenor_row_idx, j]
        if pd.notna(val):
            try:
                ty = float(val)
                if ty > 0:
                    tenor_map[j] = ty
            except (ValueError, TypeError):
                pass
    rows: list[dict[str, Any]] = []
    ts = datetime.now().isoformat()
    for i in range(data_start, len(df_raw)):
        obs_date = _normalise_date(df_raw.iloc[i, 0])
        if obs_date is None:
            continue
        for col_idx, ty in tenor_map.items():
            rate_val = df_raw.iloc[i, col_idx]
            if pd.isna(rate_val):
                continue
            try:
                rate = float(rate_val)
            except (ValueError, TypeError):
                continue
            rows.append(
                build_row(
                    country_code=_COUNTRY_CODE,
                    country_name="United Kingdom",
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
                    rate_type=rate_type,
                    curve_family=curve_family,
                    compounding=_COMPOUNDING,
                    day_count="ACT/365",
                    source_native_tenor=str(ty),
                    source_native_curve_name=sheet_name,
                    instrument_count_used=None,
                    fit_method=_FIT_METHOD,
                    is_interpolated=False,
                    is_extrapolated=False,
                    data_quality_flag="ok",
                    raw_file_hash=raw_file_hash,
                    ingestion_timestamp=ts,
                )
            )
    return rows


def _process_zip(data: bytes, source_url: str, label: str) -> list[dict[str, Any]]:
    h = compute_data_hash(data)
    rows: list[dict[str, Any]] = []
    rate_type, curve_family = _RATE_TYPES.get(label, ("zero_spot", "nominal_government"))
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for name in zf.namelist():
            if name.startswith("__MACOSX") or not (
                name.endswith(".xls") or name.endswith(".xlsx")
            ):
                continue
            try:
                content = zf.read(name)
                xls_data = io.BytesIO(content)
                sheets = pd.read_excel(xls_data, sheet_name=None, header=None)
            except Exception:
                continue
            for sheet_name, df in sheets.items():
                sheet_rows = _parse_boe_sheet(
                    df,
                    source_url,
                    curve_family,
                    rate_type,
                    f"{name}/{sheet_name}",
                    h,
                )
                rows.extend(sheet_rows)
    return rows


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def _download(url: str) -> bytes:
    headers = {"User-Agent": "Mozilla/5.0 (compatible; YieldCurveBot/1.0)"}
    resp = requests.get(url, headers=headers, timeout=120)
    resp.raise_for_status()
    return resp.content


def fetch_latest() -> list[dict[str, Any]]:
    url = _CFG["latest_url"]
    data = _download(url)
    save_raw(data, "latest-yield-curve-data.zip")
    return _process_zip(data, url, "nominal")


def fetch_nominal_archive() -> list[dict[str, Any]]:
    url = _CFG["archives"]["nominal"]
    data = _download(url)
    save_raw(data, "glcnominalddata.zip")
    return _process_zip(data, url, "nominal")


def fetch_real_archive() -> list[dict[str, Any]]:
    url = _CFG["archives"]["real"]
    data = _download(url)
    save_raw(data, "glcrealddata.zip")
    return _process_zip(data, url, "real")


def fetch_inflation_archive() -> list[dict[str, Any]]:
    url = _CFG["archives"]["inflation"]
    data = _download(url)
    save_raw(data, "glcinflationddata.zip")
    return _process_zip(data, url, "inflation")


def fetch_ois_archive() -> list[dict[str, Any]]:
    url = _CFG["archives"]["ois"]
    data = _download(url)
    save_raw(data, "oisddata.zip")
    return _process_zip(data, url, "ois")


def fetch_all() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for fetcher in (
        fetch_latest,
        fetch_nominal_archive,
        fetch_real_archive,
        fetch_inflation_archive,
        fetch_ois_archive,
    ):
        try:
            rows.extend(fetcher())
        except Exception:
            continue
    seen: set[tuple[str, float, str, str]] = set()
    deduped: list[dict[str, Any]] = []
    for row in rows:
        key = (
            row["observation_date"],
            row["tenor_years"],
            row["curve_family"],
            row["rate_type"],
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped
