from __future__ import annotations

from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd
import requests
from dateutil.parser import parse as parse_date
from tenacity import retry, stop_after_attempt, wait_exponential

from yieldcurves.config import source_config
from yieldcurves.hashing import compute_data_hash
from yieldcurves.parsers.excel import read_excel_sheets
from yieldcurves.storage import build_row, ingestion_timestamp, save_raw

_CFG = source_config("NL")
_COUNTRY_CODE = "NL"
_CURRENCY = "EUR"
_SOURCE_ID = "netherlands_dsta"
_SOURCE_NAME = "Dutch State Treasury Agency"
_RATE_TYPE = "bond_ytm"
_CURVE_FAMILY = "nominal_government"
_FIT_METHOD = "direct_source"


def _normalise_date(val: Any) -> str | None:
    if pd.isna(val):
        return None
    if isinstance(val, datetime):
        return val.strftime("%Y-%m-%d")
    try:
        return parse_date(str(val)).strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return None


def _safe_float(val: Any) -> float | None:
    if pd.isna(val):
        return None
    try:
        f = float(val)
        if np.isfinite(f):
            return f
        return None
    except (ValueError, TypeError):
        return None


def _parse_yield_column_name(col: str) -> dict[str, Any] | None:
    col = str(col).strip()
    if col.lower() in ("date", "datum", "observation date", "unnamed: 0", ""):
        return None
    return {"bond_name": col}


def _compute_maturity_years(
    observation_date: Any,
    maturity_date: Any,
) -> float | None:
    obs = pd.to_datetime(observation_date, errors="coerce")
    mat = pd.to_datetime(maturity_date, errors="coerce")
    if pd.isna(obs) or pd.isna(mat):
        return None
    years = (mat - obs).days / 365.25
    if years <= 0:
        return None
    return float(years)


def _format_tenor_label(years: float) -> str:
    return f"{int(years * 12)}M" if years < 1 else f"{int(years)}Y"


def _find_header_row(df: pd.DataFrame) -> int | None:
    for idx in range(len(df)):
        row = [str(v).strip().lower() for v in df.iloc[idx].tolist() if pd.notna(v)]
        if not row:
            continue
        if row[0] not in {"date", "refdate"}:
            continue
        if "maturity" not in row:
            continue
        if "isin code" not in row:
            continue
        if "mid yield" in row or "yield" in row:
            return idx
    return None


def _parse_sheet_dataframe(
    df: pd.DataFrame,
    sheet_name: str,
    source_url: str,
    raw_file_hash: str,
) -> list[dict[str, Any]]:
    header_row = _find_header_row(df)
    if header_row is None:
        return []

    headers = [str(v).strip() if pd.notna(v) else "" for v in df.iloc[header_row].tolist()]
    data = df.iloc[header_row + 1 :].copy()
    data.columns = headers
    data = data.dropna(how="all")

    normalized_columns = {str(col).strip().lower(): col for col in data.columns}
    date_col = normalized_columns.get("date") or normalized_columns.get("refdate")
    maturity_col = normalized_columns.get("maturity")
    isin_col = normalized_columns.get("isin code")
    description_col = normalized_columns.get("description")
    rate_col = normalized_columns.get("mid yield") or normalized_columns.get("yield")

    if rate_col is None or date_col is None or maturity_col is None:
        return []

    rows: list[dict[str, Any]] = []
    ts = ingestion_timestamp()
    for _, row in data.iterrows():
        obs_date = _normalise_date(row.get(date_col))
        if obs_date is None:
            continue

        maturity_raw = row.get(maturity_col)
        maturity_date = _normalise_date(maturity_raw)
        tenor_years = _compute_maturity_years(row.get(date_col), maturity_raw)
        if maturity_date is None or tenor_years is None:
            continue

        rate_val = _safe_float(row.get(rate_col))
        if rate_val is None:
            continue

        isin = str(row.get(isin_col) or "").strip() if isin_col else ""
        source_curve_name = str(row.get(description_col) or sheet_name).strip() if description_col else sheet_name
        rows.append(
            build_row(
                country_code=_COUNTRY_CODE,
                country_name="Netherlands",
                currency=_CURRENCY,
                source_id=_SOURCE_ID,
                source_name=_SOURCE_NAME,
                source_url=source_url,
                observation_date=obs_date,
                publication_date=obs_date,
                tenor_label=_format_tenor_label(tenor_years),
                tenor_years=tenor_years,
                rate=rate_val,
                rate_unit="percent",
                rate_type=_RATE_TYPE,
                curve_family=_CURVE_FAMILY,
                compounding="annual",
                day_count="ACT/ACT",
                source_native_tenor=isin or maturity_date,
                source_native_curve_name=source_curve_name,
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


def _parse_ods_xlsx(
    data: bytes,
    ext: str,
    source_url: str,
    raw_file_hash: str,
) -> list[dict[str, Any]]:
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp.write(data)
        tmp_path = tmp.name
    try:
        sheets = read_excel_sheets(tmp_path)
    finally:
        import os
        os.unlink(tmp_path)
    rows: list[dict[str, Any]] = []
    for sheet_name, df in sheets.items():
        rows.extend(_parse_sheet_dataframe(df, sheet_name, source_url, raw_file_hash))
    return rows


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def _download(url: str) -> bytes:
    resp = requests.get(url, timeout=120)
    resp.raise_for_status()
    return resp.content


def fetch_from_2010() -> list[dict[str, Any]]:
    url = _CFG["urls"]["from_2010"]
    data = _download(url)
    save_raw(data, "mts-fixings-publicatie.ods")
    h = compute_data_hash(data)
    return _parse_ods_xlsx(data, ".ods", url, h)


def fetch_2002_to_2009() -> list[dict[str, Any]]:
    url = _CFG["urls"]["from_2002_to_2009"]
    data = _download(url)
    save_raw(data, "mts-fixings-van-2002-tot-en-met-2009.xlsx")
    h = compute_data_hash(data)
    return _parse_ods_xlsx(data, ".xlsx", url, h)


def fetch_all() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        rows.extend(fetch_from_2010())
    except Exception:
        pass
    try:
        rows.extend(fetch_2002_to_2009())
    except Exception:
        pass
    seen: set[tuple[str, float, str]] = set()
    deduped: list[dict[str, Any]] = []
    for row in rows:
        key = (row["observation_date"], row["tenor_years"], row.get("source_native_tenor", ""))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped
