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


def _parse_date_dmy(val: Any) -> datetime | None:
    if pd.isna(val):
        return None
    if isinstance(val, datetime):
        return val
    try:
        parts = str(val).strip().split("-")
        if len(parts) == 3 and len(parts[2]) == 4:
            return datetime(int(parts[2]), int(parts[1]), int(parts[0]))
        return parse_date(str(val))
    except (ValueError, TypeError):
        return None


def _safe_float(val: Any) -> float | None:
    if pd.isna(val):
        return None
    try:
        s = str(val).strip().replace(",", "")
        is_pct = "%" in s
        s = s.replace("%", "").strip()
        if not s:
            return None
        f = float(s)
        if not np.isfinite(f):
            return None
        return f / 100.0 if is_pct else f
    except (ValueError, TypeError):
        return None


def _parse_sheet(
    df: pd.DataFrame,
    source_url: str,
    raw_file_hash: str,
    sheet_name: str,
) -> list[dict[str, Any]]:
    """Parse a DSTA sheet with metadata rows, finding the header row dynamically."""
    header_row = None
    col_map: dict[str, int] = {}

    for i in range(min(20, len(df))):
        row = df.iloc[i]
        vals = [str(v).strip().lower() for v in row if pd.notna(v)]
        if any("date" in v for v in vals) and any("isin" in v for v in vals):
            header_row = i
            for j, v in enumerate(row):
                raw = str(v).strip().lower()
                if raw == "date" or raw == "refdate":
                    col_map["date"] = j
                elif "maturity" in raw and "year" not in raw:
                    col_map["maturity"] = j
                elif "yield" in raw:
                    col_map["yield"] = j
                elif "isin" in raw:
                    col_map["isin"] = j
            break

    if header_row is None or "date" not in col_map or "yield" not in col_map:
        return []

    data_start = header_row + 1
    rows: list[dict[str, Any]] = []
    ts = ingestion_timestamp()
    date_col = col_map["date"]
    yield_col = col_map["yield"]
    isin_col = col_map.get("isin")
    maturity_col = col_map.get("maturity")

    for idx in range(data_start, len(df)):
        obs_date_val = df.iloc[idx, date_col]
        obs_date = _normalise_date(obs_date_val)
        if obs_date is None:
            continue

        yield_val = _safe_float(df.iloc[idx, yield_col])
        if yield_val is None:
            continue

        isin = str(df.iloc[idx, isin_col]) if isin_col is not None else ""
        isin = isin.strip() if isin else sheet_name

        maturity_date = None
        if maturity_col is not None:
            maturity_date = _parse_date_dmy(df.iloc[idx, maturity_col])

        if maturity_date is not None and isinstance(parse_date(obs_date), datetime):
            obs_dt = parse_date(obs_date)
            delta = (maturity_date - obs_dt).days
            tenor_years = delta / 365.25 if delta > 0 else 0.0
        else:
            tenor_years = 0.0

        if tenor_years <= 0:
            continue

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
                tenor_label=(
                    f"{int(tenor_years * 12)}M" if tenor_years < 1 else f"{int(tenor_years)}Y"
                ),
                tenor_years=tenor_years,
                rate=round(yield_val * 100, 6),
                rate_unit="percent",
                rate_type=_RATE_TYPE,
                curve_family=_CURVE_FAMILY,
                compounding="annual",
                day_count="ACT/ACT",
                source_native_tenor=isin,
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


def _parse(data: bytes, ext: str, source_url: str, raw_file_hash: str) -> list[dict[str, Any]]:
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp.write(data)
        tmp_path = tmp.name
    try:
        rows: list[dict[str, Any]] = []
        if ext == ".ods":
            from odf.namespaces import OFFICENS
            from odf.opendocument import load as ods_load
            from odf.table import Table, TableCell, TableRow
            from odf.text import P

            doc = ods_load(tmp_path)
            for table in doc.getElementsByType(Table):
                sheet_name = table.getAttribute("name")
                odf_rows = table.getElementsByType(TableRow)
                sheet_data: list[list[Any]] = []
                for odf_row in odf_rows:
                    cells = odf_row.getElementsByType(TableCell)
                    row_vals: list[Any] = []
                    for cell in cells:
                        val = None
                        text_parts = []
                        for p in cell.getElementsByType(P):
                            for child in p.childNodes:
                                if hasattr(child, "data"):
                                    text_parts.append(child.data)
                        if text_parts:
                            val = "".join(text_parts)
                        office_val = cell.getAttrNS(OFFICENS, "value")
                        if office_val is not None:
                            try:
                                val = float(office_val)
                            except (ValueError, TypeError):
                                pass
                        date_val = cell.getAttrNS(OFFICENS, "date-value")
                        if date_val is not None:
                            try:
                                from datetime import datetime
                                val = datetime.strptime(date_val.split("T")[0], "%Y-%m-%d")
                            except (ValueError, TypeError):
                                val = str(date_val)
                        row_vals.append(val)
                    while row_vals and row_vals[-1] is None:
                        row_vals.pop()
                    if row_vals:
                        sheet_data.append(row_vals)
                if sheet_data:
                    max_cols = max(len(r) for r in sheet_data)
                    padded = [r + [None] * (max_cols - len(r)) for r in sheet_data]
                    df = pd.DataFrame(padded)
                    rows.extend(_parse_sheet(df, source_url, raw_file_hash, sheet_name))
        else:
            xls = pd.ExcelFile(tmp_path, engine="openpyxl")
            for sheet_name in xls.sheet_names:
                df = pd.read_excel(tmp_path, sheet_name=sheet_name, engine="openpyxl", header=None)
                rows.extend(_parse_sheet(df, source_url, raw_file_hash, sheet_name))
        return rows
    finally:
        import os
        os.unlink(tmp_path)


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
    return _parse(data, ".ods", url, h)


def fetch_2002_to_2009() -> list[dict[str, Any]]:
    url = _CFG["urls"]["from_2002_to_2009"]
    data = _download(url)
    save_raw(data, "mts-fixings-van-2002-tot-en-met-2009.xlsx")
    h = compute_data_hash(data)
    return _parse(data, ".xlsx", url, h)


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
