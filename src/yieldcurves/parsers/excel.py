from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

SUPPORTED_EXTENSIONS = frozenset({".xls", ".xlsx", ".ods"})


def read_excel_safe(
    path: str | Path,
    sheet_name: str | int | None = 0,
    **kwargs: Any,
) -> pd.DataFrame:
    ext = Path(path).suffix.lower()
    if ext == ".ods":
        kwargs.setdefault("engine", "odf")
    elif ext in (".xls", ".xlsx"):
        kwargs.setdefault("engine", "openpyxl" if ext == ".xlsx" else "xlrd")
    return pd.read_excel(path, sheet_name=sheet_name, **kwargs)


def read_excel_sheets(
    path: str | Path,
    **kwargs: Any,
) -> dict[str, pd.DataFrame]:
    ext = Path(path).suffix.lower()
    if ext == ".ods":
        kwargs.setdefault("engine", "odf")
    elif ext in (".xls", ".xlsx"):
        kwargs.setdefault("engine", "openpyxl" if ext == ".xlsx" else "xlrd")
    return pd.read_excel(path, sheet_name=None, **kwargs)
