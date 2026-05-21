from __future__ import annotations

from typing import Any

import pandas as pd


def detect_encoding(path: str) -> str:
    import chardet

    with open(path, "rb") as f:
        raw = f.read(10000)
    result = chardet.detect(raw)
    return result.get("encoding", "utf-8")


def read_csv_safe(
    path: str,
    encodings: list[str] | None = None,
    **kwargs: Any,
) -> pd.DataFrame:
    if encodings is None:
        encodings = ["utf-8-sig", "cp932", "shift_jis", "latin1"]
    for enc in encodings:
        try:
            return pd.read_csv(path, encoding=enc, **kwargs)
        except (UnicodeDecodeError, UnicodeError):
            continue
    detected = detect_encoding(path)
    return pd.read_csv(path, encoding=detected, **kwargs)


def read_csv_from_bytes(
    data: bytes,
    encodings: list[str] | None = None,
    **kwargs: Any,
) -> pd.DataFrame:
    import io

    if encodings is None:
        encodings = ["utf-8-sig", "cp932", "shift_jis", "latin1"]
    for enc in encodings:
        try:
            return pd.read_csv(io.BytesIO(data), encoding=enc, **kwargs)
        except (UnicodeDecodeError, UnicodeError):
            continue
    import chardet

    result = chardet.detect(data)
    enc = result.get("encoding", "utf-8")
    return pd.read_csv(io.BytesIO(data), encoding=enc, **kwargs)
