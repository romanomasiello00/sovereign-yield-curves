from __future__ import annotations

import re
from typing import Any

import pandas as pd
import requests
from tenacity import retry, stop_after_attempt, wait_exponential

_BUNDESBANK_BASE = "https://api.statistiken.bundesbank.de/rest"


def fetch_dataflow(dataflow: str) -> list[dict[str, Any]]:
    url = f"{_BUNDESBANK_BASE}/dataflow/{dataflow}/all"
    resp = requests.get(url, headers={"Accept": "application/vnd.sdmx.structure+json"})
    resp.raise_for_status()
    data = resp.json()
    flows: list[dict[str, Any]] = []
    for item in data.get("data", {}).get("dataflows", []):
        flows.append(item)
    return flows


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def fetch_series_csv(flow_ref: str, key: str, params: dict[str, str] | None = None) -> pd.DataFrame:
    url = f"{_BUNDESBANK_BASE}/data/{flow_ref}/{key}"
    req_params: dict[str, str] = {"format": "csv"}
    if params:
        req_params.update(params)
    resp = requests.get(url, params=req_params)
    resp.raise_for_status()
    return pd.read_csv(resp.text)


def fetch_series_sdmx_csv(
    flow_ref: str,
    key: str,
    params: dict[str, str] | None = None,
) -> str:
    url = f"{_BUNDESBANK_BASE}/data/{flow_ref}/{key}"
    req_params: dict[str, str] = {"format": "csv"}
    if params:
        req_params.update(params)
    resp = requests.get(url, params=req_params)
    resp.raise_for_status()
    return resp.text


def parse_maturity_code(code: str) -> float | None:
    mapping = {
        "R1XX": 1.0,
        "R2XX": 2.0,
        "R3XX": 3.0,
        "R5XX": 5.0,
        "R7XX": 7.0,
        "R10X": 10.0,
        "R15X": 15.0,
        "R20X": 20.0,
        "R25X": 25.0,
        "R30X": 30.0,
    }
    for pattern, years in mapping.items():
        if code.startswith(pattern[:3]):
            return years
    match = re.search(r"R(\d{2})X", code)
    if match:
        return float(match.group(1))
    return None
