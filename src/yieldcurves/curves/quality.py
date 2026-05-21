from __future__ import annotations

from typing import Any


def assess_data_quality(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "sparse_curve"
    tenors = sorted({r.get("tenor_years", 0.0) for r in rows if r.get("rate") is not None})
    if len(tenors) < 2:
        return "sparse_curve"
    max_t = max(tenors)
    min_t = min(tenors)
    flags: list[str] = []
    if min_t > 0.5:
        flags.append("missing_short_end")
    if max_t < 20.0:
        flags.append("missing_long_end")
    if len(tenors) < 5:
        flags.append("sparse_curve")
    return "_".join(flags) if flags else "ok"


def has_revision(
    existing_row: dict[str, Any],
    new_row: dict[str, Any],
    compare_fields: tuple[str, ...] = ("rate", "fit_method", "data_quality_flag"),
) -> bool:
    for field in compare_fields:
        if existing_row.get(field) != new_row.get(field):
            return True
    return False
