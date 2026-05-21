from __future__ import annotations

import re
import time
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd
import requests
from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_date
from tenacity import retry, stop_after_attempt, wait_exponential

from yieldcurves.config import source_config
from yieldcurves.storage import build_row

_CFG = source_config("IT")
_COUNTRY_CODE = "IT"
_CURRENCY = "EUR"
_SOURCE_ID = "italy_borsa"
_SOURCE_NAME = "Borsa Italiana MOT"
_RATE_TYPE = "bond_ytm"
_CURVE_FAMILY = "nominal_government"
_FIT_METHOD = "direct_source"
_BTP_EXCLUDE_PATTERNS = re.compile(
    r"(BTP[\s_]?I|BTP\s+Italia|BTP\s+Valore|CCT|Strip|ZC|inflation.linked|indicizzato)",
    re.IGNORECASE,
)


class BTPBond:
    isin: str
    description: str
    last_price: float | None
    coupon: float | None
    expiry_date: str | None
    gross_ytm: float | None
    net_ytm: float | None
    modified_duration: float | None
    reference_price: float | None
    reference_price_date: str | None
    issuer: str | None
    bond_structure: str | None
    outstanding_amount: float | None
    coupon_frequency: str | None
    day_count: str | None
    annual_coupon_rate: float | None

    def __init__(self, isin: str, description: str):
        self.isin = isin
        self.description = description
        self.last_price = None
        self.coupon = None
        self.expiry_date = None
        self.gross_ytm = None
        self.net_ytm = None
        self.modified_duration = None
        self.reference_price = None
        self.reference_price_date = None
        self.issuer = None
        self.bond_structure = None
        self.outstanding_amount = None
        self.coupon_frequency = None
        self.day_count = None
        self.annual_coupon_rate = None


def _normalise_date(val: Any) -> str | None:
    if pd.isna(val) or val is None:
        return None
    if isinstance(val, datetime):
        return val.strftime("%Y-%m-%d")
    try:
        return parse_date(str(val)).strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return None


def _safe_float(val: Any) -> float | None:
    if val is None:
        return None
    try:
        f = float(str(val).replace(",", ".").replace("%", "").strip())
        if np.isfinite(f):
            return f
        return None
    except (ValueError, TypeError):
        return None


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def _fetch_page(url: str) -> str:
    headers = {"User-Agent": _CFG["scraper"]["user_agent"]}
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.text


def _scrape_list_page(page: int) -> list[dict[str, Any]]:
    url = _CFG["list_url"].format(page=page)
    html = _fetch_page(url)
    soup = BeautifulSoup(html, "lxml")
    bonds: list[dict[str, Any]] = []
    table = soup.find("table", class_="m-table")
    if table is None:
        return bonds
    rows = table.find_all("tr")
    for tr in rows:
        cells = tr.find_all("td")
        if len(cells) < 5:
            continue
        a_tag = cells[0].find("a")
        href = a_tag.get("href", "") if a_tag else ""
        isin = href.split("/scheda/")[-1].split("-MOTX")[0] if "/scheda/" in href else ""
        if not isin:
            continue
        desc = cells[1].get_text(strip=True) if len(cells) > 1 else ""
        price = _safe_float(cells[2].get_text(strip=True)) if len(cells) > 2 else None
        coupon = _safe_float(cells[3].get_text(strip=True)) if len(cells) > 3 else None
        expiry = cells[4].get_text(strip=True) if len(cells) > 4 else None
        bonds.append({
            "isin": isin, "description": desc,
            "last_price": price, "coupon": coupon, "expiry": expiry,
        })
    return bonds


def _scrape_detail_page(isin: str) -> dict[str, Any]:
    url = _CFG["detail_url"].format(isin=isin)
    html = _fetch_page(url)
    soup = BeautifulSoup(html, "lxml")
    detail: dict[str, Any] = {"isin": isin}
    tables = soup.find_all("table")
    for table in tables:
        rows = table.find_all("tr")
        for row in rows:
            cells = row.find_all("td")
            if len(cells) < 2:
                continue
            label = cells[0].get_text(strip=True).lower()
            value = cells[1].get_text(strip=True)
            if "gross yield" in label:
                detail["gross_ytm"] = _safe_float(value)
            elif "net yield" in label:
                detail["net_ytm"] = _safe_float(value)
            elif "modified duration" in label:
                detail["modified_duration"] = _safe_float(value)
            elif "reference price" in label:
                detail["reference_price"] = _safe_float(value)
            elif "issuer" in label:
                detail["issuer"] = value
            elif "bond structure" in label:
                detail["bond_structure"] = value
            elif "outstanding amount" in label:
                detail["outstanding_amount"] = _safe_float(value)
            elif "coupon frequency" in label:
                detail["coupon_frequency"] = value
            elif "day count" in label:
                detail["day_count"] = value
            elif "annual coupon rate" in label:
                detail["annual_coupon_rate"] = _safe_float(value)
            elif "periodic coupon rate" in label:
                detail["periodic_coupon_rate"] = _safe_float(value)
            elif "expiry" in label or "maturity" in label:
                detail["expiry_date"] = _normalise_date(value)
            elif "reference price date" in label:
                detail["reference_price_date"] = _normalise_date(value)
    return detail


def _is_valid_btp(detail: dict[str, Any], description: str = "", list_expiry: str = "") -> bool:
    issuer = str(detail.get("issuer", "")).upper()
    if "REPUBLIC OF ITALY" not in issuer and "ITALIAN REPUBLIC" not in issuer:
        return False
    desc = str(description) if description else detail.get("isin", "")
    if _BTP_EXCLUDE_PATTERNS.search(desc):
        return False
    structure = str(detail.get("bond_structure", ""))
    if structure and "plain vanilla" not in structure.lower():
        return False
    annual = detail.get("annual_coupon_rate")
    if annual is None:
        periodic = detail.get("periodic_coupon_rate")
        freq = str(detail.get("coupon_frequency", "")).lower()
        if periodic is not None and freq:
            mult = 2 if "semi" in freq else 4 if "quarter" in freq else 12 if "month" in freq else 1
            annual = round(periodic * mult, 6)
            detail["annual_coupon_rate"] = annual
    if annual is None:
        return False
    if detail.get("gross_ytm") is None:
        return False
    expiry = _normalise_date(list_expiry) or detail.get("expiry_date")
    if expiry is None:
        return False
    detail["expiry_date"] = expiry
    return True


def _compute_maturity_years(expiry_date_str: str, observation_date_str: str) -> float | None:
    try:
        exp = parse_date(expiry_date_str)
        obs = parse_date(observation_date_str)
        delta = (exp - obs).days
        if delta <= 0:
            return None
        return delta / 365.25
    except (ValueError, TypeError):
        return None


def fetch_current_snapshot() -> list[dict[str, Any]]:
    all_bonds: list[dict[str, Any]] = []
    page = 1
    while True:
        bonds = _scrape_list_page(page)
        if not bonds:
            break
        all_bonds.extend(bonds)
        page += 1
        time.sleep(_CFG["scraper"].get("min_delay_seconds", 1.0))
    detail_bonds: list[BTPBond] = []
    for bond in all_bonds:
        try:
            detail = _scrape_detail_page(bond["isin"])
            time.sleep(_CFG["scraper"].get("min_delay_seconds", 1.0))
        except Exception:
            continue
        if not _is_valid_btp(
            detail,
            description=bond.get("description", ""),
            list_expiry=bond.get("expiry", ""),
        ):
            continue
        b = BTPBond(isin=bond["isin"], description=bond.get("description", ""))
        b.last_price = bond.get("last_price")
        b.coupon = bond.get("coupon")
        b.expiry_date = detail.get("expiry_date")
        b.gross_ytm = detail.get("gross_ytm")
        b.net_ytm = detail.get("net_ytm")
        b.modified_duration = detail.get("modified_duration")
        b.reference_price = detail.get("reference_price")
        b.reference_price_date = detail.get("reference_price_date")
        b.issuer = detail.get("issuer")
        b.bond_structure = detail.get("bond_structure")
        b.outstanding_amount = detail.get("outstanding_amount")
        b.coupon_frequency = detail.get("coupon_frequency")
        b.day_count = detail.get("day_count")
        b.annual_coupon_rate = detail.get("annual_coupon_rate")
        detail_bonds.append(b)
    obs_date = datetime.now().strftime("%Y-%m-%d")
    rows: list[dict[str, Any]] = []
    for b in detail_bonds:
        my = _compute_maturity_years(str(b.expiry_date), obs_date)
        if my is None or my <= 0:
            continue
        rows.append(
            build_row(
                country_code=_COUNTRY_CODE,
                country_name="Italy",
                currency=_CURRENCY,
                source_id=_SOURCE_ID,
                source_name=_SOURCE_NAME,
                source_url=_CFG["list_url"].format(page=1),
                observation_date=obs_date,
                publication_date=obs_date,
                tenor_label=f"{int(my * 12)}M" if my < 1 else f"{int(my)}Y",
                tenor_years=my,
                rate=b.gross_ytm,
                rate_unit="percent",
                rate_type=_RATE_TYPE,
                curve_family=_CURVE_FAMILY,
                compounding="annual",
                day_count=str(b.day_count or "ACT/ACT"),
                source_native_tenor=b.isin,
                source_native_curve_name=f"BTP {b.description}",
                instrument_count_used=None,
                fit_method=_FIT_METHOD,
                is_interpolated=False,
                is_extrapolated=False,
                data_quality_flag="ok",
                raw_file_hash="",
                ingestion_timestamp=datetime.utcnow().isoformat(),
            )
        )
    return rows


def fetch_all() -> list[dict[str, Any]]:
    return fetch_current_snapshot()
