from __future__ import annotations

from typing import Any

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

from yieldcurves.config import source_config
from yieldcurves.curves.tenors import parse_tenor_label
from yieldcurves.hashing import compute_data_hash
from yieldcurves.storage import build_row, ingestion_timestamp, save_raw

_CFG = source_config("CH")
_COUNTRY_CODE = "CH"
_CURRENCY = "CHF"
_SOURCE_ID = "ch_snb_confederation_spot_rates"
_SOURCE_NAME = "Swiss National Bank - Confederation bond spot interest rates"
_RATE_TYPE = "zero_spot"
_CURVE_FAMILY = "nominal_government"
_FIT_METHOD = "official"


def _tenor_label(code: str) -> str | None:
    """SNB tenor codes are like '1J'..'30J' (J = Jahre/years)."""
    code = code.strip().upper()
    if code.endswith("J") and code[:-1].isdigit():
        return f"{int(code[:-1])}Y"
    return None


def _parse_csv(data: bytes, source_url: str, from_date: str = "1900-01") -> list[dict[str, Any]]:
    """Parse the SNB rendoblim CSV (monthly Confederation spot rates).

    Layout: metadata lines, then a header row '"Date";"D0";"Value"', then
    rows of 'YYYY-MM';'<n>J';'<rate>'. Observation date set to the 1st of month.
    """
    text = data.decode("utf-8-sig", errors="replace")
    h = compute_data_hash(data)
    ts = ingestion_timestamp()
    rows: list[dict[str, Any]] = []
    in_data = False

    for line in text.splitlines():
        parts = [p.strip().strip('"') for p in line.split(";")]
        if not in_data:
            if parts[:1] == ["Date"]:
                in_data = True
            continue
        if len(parts) < 3:
            continue
        ym, code, value = parts[0], parts[1], parts[2]
        if not ym or not value:
            continue
        if ym < from_date:
            continue
        std_label = _tenor_label(code)
        if std_label is None:
            continue
        try:
            rate = float(value)
        except (ValueError, TypeError):
            continue
        ty = parse_tenor_label(std_label)
        if ty is None:
            continue
        obs_date = f"{ym}-01"
        rows.append(
            build_row(
                country_code=_COUNTRY_CODE,
                country_name="Switzerland",
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
                compounding="annual",
                day_count="source_native",
                source_native_tenor=code,
                source_native_curve_name="rendoblim",
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
    resp = requests.get(url, timeout=60, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    return resp.content


def fetch_all(from_date: str = "1988-01") -> list[dict[str, Any]]:
    """Fetch Swiss Confederation spot rates via the SNB data portal (monthly).

    from_date is a 'YYYY-MM' (or 'YYYY-MM-DD') prefix used to filter months.
    """
    url = _CFG["api_url"]
    data = _download(url)
    save_raw(data, "snb_rendoblim.csv")
    return _parse_csv(data, url, from_date=from_date[:7])
