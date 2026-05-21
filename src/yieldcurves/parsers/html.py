from __future__ import annotations

from typing import Any

import pandas as pd
from bs4 import BeautifulSoup


def parse_html_tables(html: str, **kwargs: Any) -> list[pd.DataFrame]:
    tables = pd.read_html(html, **kwargs)
    return tables


def extract_table_by_id(html: str, table_id: str, **kwargs: Any) -> pd.DataFrame | None:
    soup = BeautifulSoup(html, "lxml")
    table_tag = soup.find("table", {"id": table_id})
    if table_tag is None:
        return None
    tables = pd.read_html(str(table_tag), **kwargs)
    return tables[0] if tables else None


def extract_table_by_class(html: str, class_name: str, **kwargs: Any) -> pd.DataFrame | None:
    soup = BeautifulSoup(html, "lxml")
    table_tag = soup.find("table", {"class": class_name})
    if table_tag is None:
        return None
    tables = pd.read_html(str(table_tag), **kwargs)
    return tables[0] if tables else None
