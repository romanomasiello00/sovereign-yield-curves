from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

import pandas as pd

_FREQ_LABELS: dict[str, str] = {
    "D": "Daily",
    "M": "Monthly",
    "Q": "Quarterly",
    "S": "Semi-annual",
    "A": "Annual",
    "W": "Weekly",
    "B": "Business_daily",
}


def parse_structure_csv(text: str) -> pd.DataFrame:
    raw_lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not raw_lines:
        return pd.DataFrame()

    headers = [h.strip().strip('"') for h in raw_lines[0].split(";")]
    records: list[dict[str, str]] = []
    for line in raw_lines[1:]:
        parts = [p.strip().strip('"') for p in line.split(";")]
        if len(parts) < 2:
            continue
        record = dict(zip(headers, parts[: len(headers)]))
        records.append(record)

    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records)

    pivot = df.pivot_table(
        index="Cube",
        columns="Variable",
        values="Domain values",
        aggfunc="first",
    )
    pivot = pivot.reset_index()
    pivot.columns.name = None

    col_rename = {
        "Cube": "series_id",
        "DESCRIPTION": "series_name",
        "FREQ": "frequency_code",
        "FONTE": "source",
        "SCALA": "scale",
        "STATUS": "status_domain",
        "UNMIS": "unit",
        "NOTE": "notes",
    }
    available = {k: v for k, v in col_rename.items() if k in pivot.columns}
    pivot = pivot.rename(columns=available)

    bool_cols = [c for c in pivot.columns if c not in available.values()]
    meta_cols = [c for c in available.values() if c in pivot.columns]
    extra_cols = [c for c in bool_cols]

    out = pivot[meta_cols + extra_cols].copy()
    out["series_id"] = out["series_id"].astype(str).str.strip()
    if "series_name" in out.columns:
        out["series_name"] = out["series_name"].astype(str).str.strip()
    if "frequency_code" in out.columns:
        out["frequency_code"] = out["frequency_code"].astype(str).str.strip()
    else:
        out["frequency_code"] = "unknown"

    return out


def parse_structure_csv_raw(text: str) -> pd.DataFrame:
    """Return unpivoted structure data (Cube, Variable, Domain values)."""
    raw_lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not raw_lines:
        return pd.DataFrame()

    headers = [h.strip().strip('"') for h in raw_lines[0].split(";")]
    records: list[dict[str, str]] = []
    for line in raw_lines[1:]:
        parts = [p.strip().strip('"') for p in line.split(";")]
        if len(parts) < 2:
            continue
        record = dict(zip(headers, parts[: len(headers)]))
        records.append(record)

    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records)
    keep = {"Cube", "Variable", "Domain values"}
    return df[[c for c in df.columns if c in keep]]


def parse_domain_csv(text: str) -> dict[str, dict[str, str]]:
    raw_lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not raw_lines:
        return {}

    domain_map: dict[str, dict[str, str]] = defaultdict(dict)
    for line in raw_lines[1:]:
        parts = [p.strip().strip('"') for p in line.split(";")]
        if len(parts) >= 3:
            domain = parts[0]
            code = parts[1]
            desc = parts[2]
            domain_map[domain][code] = desc

    return dict(domain_map)


def parse_legend_csv(text: str) -> dict[str, str]:
    raw_lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    result: dict[str, str] = {}

    for line in raw_lines[1:]:
        parts = [p.strip().strip('"') for p in line.split(";")]
        if len(parts) < 3:
            continue
        obj_type = parts[0]
        code = parts[1]
        desc = parts[2]
        if obj_type in ("Time series", "Cube", "Statistical table"):
            result[code] = desc

    return result


def decode_frequencies(
    catalog: pd.DataFrame,
    domain_map: dict[str, dict[str, str]],
) -> pd.DataFrame:
    freq_domain = domain_map.get("FREQUENZA", {})
    catalog["frequency_label"] = catalog["frequency_code"].map(
        lambda c: freq_domain.get(c, _FREQ_LABELS.get(c, "Unknown"))
    )
    return catalog


def compute_frequency_score(freq_code: str, config: dict) -> float:
    freq_scores = config.get("scoring", {}).get("frequency_scores", {})
    return freq_scores.get(freq_code, freq_scores.get("unknown", 0.10))


def compute_importance_score(series_name: str, config: dict) -> float:
    categories = config.get("scoring", {}).get("category_keywords", {})
    name_lower = series_name.lower()

    for cat_key in ("high", "medium", "low"):
        cat = categories.get(cat_key)
        if not cat:
            continue
        for kw in cat.get("keywords", []):
            if kw in name_lower:
                return cat["score"]

    default_score = categories.get("default", 0.60)
    if isinstance(default_score, dict):
        return default_score.get("score", 0.60)
    return default_score


def compute_recency_score(
    series_id: str,
    series_data: pd.DataFrame,
    config: dict,
) -> float:
    recency_cfg = config.get("scoring", {}).get("recency", {})
    stale_days = recency_cfg.get("stale_days", 365)
    max_score_days = recency_cfg.get("max_score_days", 7)

    series_obs = series_data[series_data["series_id"] == series_id]
    if series_obs.empty:
        return 0.0

    try:
        last_date = pd.to_datetime(series_obs["observation_date"]).max()
    except Exception:
        return 0.0

    now = datetime.now(timezone.utc)
    if last_date.tzinfo is None:
        last_date = last_date.tz_localize("UTC")
    days_since = (now - last_date).days

    if days_since <= max_score_days:
        return 1.0
    if days_since >= stale_days:
        return 0.0

    return 1.0 - (days_since - max_score_days) / (stale_days - max_score_days)


def compute_history_length_score(
    series_id: str,
    series_data: pd.DataFrame,
) -> float:
    series_obs = series_data[series_data["series_id"] == series_id]
    if series_obs.empty:
        return 0.0

    count = len(series_obs)
    if count >= 1000:
        return 1.0
    if count >= 500:
        return 0.9
    if count >= 200:
        return 0.75
    if count >= 50:
        return 0.5
    if count >= 10:
        return 0.3
    return 0.1


def compute_metadata_quality_score(row: pd.Series) -> float:
    score = 0.0
    checks = 0

    if row.get("series_name") and str(row["series_name"]).strip():
        score += 1.0
    checks += 1

    freq = row.get("frequency_code", "")
    if freq and str(freq).strip() and str(freq).strip() != "unknown":
        score += 1.0
    checks += 1

    if row.get("unit") and str(row["unit"]).strip():
        score += 1.0
    checks += 1

    if row.get("source") and str(row["source"]).strip():
        score += 1.0
    checks += 1

    return score / checks if checks > 0 else 0.0


def compute_stale_penalty(
    series_id: str,
    series_data: pd.DataFrame,
    config: dict,
) -> float:
    stale_days = config.get("scoring", {}).get("recency", {}).get("stale_days", 365)
    series_obs = series_data[series_data["series_id"] == series_id]
    if series_obs.empty:
        return 1.0

    try:
        last_date = pd.to_datetime(series_obs["observation_date"]).max()
    except Exception:
        return 0.0

    now = datetime.now(timezone.utc)
    if last_date.tzinfo is None:
        last_date = last_date.tz_localize("UTC")
    days_since = (now - last_date).days

    if days_since >= stale_days:
        return 1.0
    if days_since <= 30:
        return 0.0
    return (days_since - 30) / (stale_days - 30)


def build_and_score_catalog(
    structure_df: pd.DataFrame,
    domain_map: dict[str, dict[str, str]],
    legend_map: dict[str, str],
    series_data: pd.DataFrame,
    publication_code: str,
    config: dict,
    priority: int = 1,
    theme: str = "general",
) -> pd.DataFrame:
    catalog = structure_df.copy()
    catalog = decode_frequencies(catalog, domain_map)

    if "series_name" in catalog.columns:
        catalog["series_name"] = catalog.apply(
            lambda r: legend_map.get(
                r["series_id"],
                r.get("series_name", ""),
            ),
            axis=1,
        )
    else:
        catalog["series_name"] = catalog["series_id"].map(
            lambda sid: legend_map.get(sid, "")
        )

    catalog["publication_code"] = publication_code
    catalog["priority"] = priority
    catalog["theme"] = theme

    weights = config.get("scoring", {}).get("weights", {})
    w_freq = weights.get("frequency", 30)
    w_recency = weights.get("recency", 25)
    w_importance = weights.get("importance", 25)
    w_history = weights.get("history_length", 10)
    w_quality = weights.get("metadata_quality", 10)
    stale_penalty_weight = weights.get("stale_penalty", -50)

    scores: list[float] = []

    for _, row in catalog.iterrows():
        sid = row["series_id"]

        freq_score = compute_frequency_score(row["frequency_code"], config)
        imp_score = compute_importance_score(
            row.get("series_name", ""), config
        )
        rec_score = compute_recency_score(sid, series_data, config)
        hist_score = compute_history_length_score(sid, series_data)
        qual_score = compute_metadata_quality_score(row)
        stale_penalty = compute_stale_penalty(sid, series_data, config)

        total = (
            w_freq * freq_score
            + w_recency * rec_score
            + w_importance * imp_score
            + w_history * hist_score
            + w_quality * qual_score
            + stale_penalty_weight * stale_penalty
        )

        scores.append(round(total, 2))

    catalog["score"] = scores
    catalog = catalog.sort_values("score", ascending=False).reset_index(drop=True)

    return catalog


def assign_tiers(
    catalog: pd.DataFrame,
    config: dict,
) -> pd.DataFrame:
    thresholds = config.get("scoring", {}).get("tier_thresholds", {})
    core_5k_count = thresholds.get("core_5k", 5000)
    core_20k_count = thresholds.get("core_20k", 20000)

    catalog = catalog.copy()
    catalog["tier"] = "archive"

    sorted_idx = catalog["score"].argsort()[::-1]
    catalog["rank"] = 0
    catalog.loc[sorted_idx, "rank"] = range(1, len(catalog) + 1)

    catalog.loc[catalog["rank"] <= core_5k_count, "tier"] = "core_5k"
    mask = (catalog["rank"] > core_5k_count) & (catalog["rank"] <= core_20k_count)
    catalog.loc[mask, "tier"] = "core_20k"

    catalog["is_active"] = catalog["tier"].isin(("core_5k", "core_20k"))

    return catalog.drop(columns=["rank"])


def build_series_catalog(
    publication_code: str,
    priority: int,
    theme: str,
    structure_text: str,
    domain_text: str,
    legend_text: str,
    data_texts: list[str],
    config: dict,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    structure_df = parse_structure_csv(structure_text)
    if structure_df.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    structure_raw = parse_structure_csv_raw(structure_text)

    domain_map = parse_domain_csv(domain_text)
    legend_map = parse_legend_csv(legend_text)

    known_ids = structure_df["series_id"].tolist()
    all_data: list[pd.DataFrame] = []
    for dt in data_texts:
        if dt.strip():
            part = parse_data_csv(dt, known_ids, structure_raw)
            if not part.empty:
                all_data.append(part)

    data_df = pd.concat(all_data, ignore_index=True) if all_data else pd.DataFrame()

    catalog = build_and_score_catalog(
        structure_df=structure_df,
        domain_map=domain_map,
        legend_map=legend_map,
        series_data=data_df,
        publication_code=publication_code,
        config=config,
        priority=priority,
        theme=theme,
    )

    catalog = assign_tiers(catalog, config)

    catalog_cols = [
        "series_id",
        "publication_code",
        "series_name",
        "frequency_code",
        "frequency_label",
        "theme",
        "priority",
        "score",
        "tier",
        "is_active",
        "unit",
        "source",
        "notes",
    ]
    available = [c for c in catalog_cols if c in catalog.columns]
    catalog_out = catalog[available].copy()

    data_meta = data_df[["series_id", "observation_date", "value", "status_code"]].copy()
    data_meta["publication_code"] = publication_code

    tier_map = catalog_out[["series_id", "tier"]].set_index("series_id")["tier"].to_dict()
    data_meta["tier"] = data_meta["series_id"].map(tier_map)

    core_5k = data_meta[data_meta["tier"] == "core_5k"].copy()
    core_20k = data_meta[data_meta["tier"] == "core_20k"].copy()
    archive = data_meta[data_meta["tier"] == "archive"].copy()

    return catalog_out, core_5k, core_20k, archive


def _detect_format(
    headers: list[str],
    known_series_ids: set[str] | None,
) -> str:
    """Detect if CSV is wide format (series IDs as columns) or long format (dimension columns)."""
    if not known_series_ids:
        return "wide"
    count_in_known = sum(1 for h in headers[1:] if h in known_series_ids)
    if count_in_known > 0:
        return "wide"
    return "long"


def _parse_data_wide(
    headers: list[str],
    raw_lines: list[str],
    known_series_ids: set[str] | None,
) -> list[dict[str, Any]]:
    series_cols = headers[1:]
    records: list[dict[str, Any]] = []
    for line in raw_lines[1:]:
        parts = [p.strip().strip('"') for p in line.split(";")]
        if len(parts) != len(headers):
            continue
        date_str = parts[0]
        if not date_str:
            continue
        obs_date = date_str.replace("/", "-")

        for i, sid in enumerate(series_cols, start=1):
            if known_series_ids and sid not in known_series_ids:
                continue
            if i >= len(parts):
                continue
            raw_val = parts[i]
            if not raw_val:
                continue
            try:
                value = float(raw_val)
            except (ValueError, TypeError):
                continue
            records.append(
                {
                    "series_id": sid,
                    "observation_date": obs_date,
                    "value": value,
                    "status_code": "",
                }
            )
    return records


def _is_fixed_value(val: str) -> bool:
    lowered = val.lower().strip()
    return lowered not in (
        "enumerated domain",
        "range of values",
        "number",
        "",
    )


def _parse_data_long(
    headers: list[str],
    raw_lines: list[str],
    structure_df: pd.DataFrame,
) -> list[dict[str, Any]]:
    """Parse long-format data where rows are identified by fixed dimension values."""
    var_cols = [c for c in headers if c != "DATA_OSS"]
    date_col = "DATA_OSS"
    if date_col not in headers:
        date_col = headers[0]

    value_col = "VALORE"
    if value_col not in var_cols:
        value_col = headers[-1]

    dim_cols = [c for c in var_cols if c != value_col]
    sid_col = "series_id" if "series_id" in structure_df.columns else "Cube"

    # Build series_fixed: series_id -> [(dim_name, dim_value)] for FIXED dimensions only
    # These are dimension values that are constant for each series_id
    series_fixed: dict[str, list[tuple[str, str]]] = {}
    for sid in structure_df[sid_col].unique():
        sid_vars = structure_df[structure_df[sid_col] == sid]
        fixed_pairs: list[tuple[str, str]] = []
        for _, row in sid_vars.iterrows():
            var = str(row.get("Variable", row.get("variable_name", "")))
            val = str(row.get("Domain values", row.get("domain_value", "")))
            if var in dim_cols and _is_fixed_value(val):
                fixed_pairs.append((var, val))
        if fixed_pairs:
            series_fixed[sid] = fixed_pairs

    if not series_fixed:
        return []

    records: list[dict[str, Any]] = []
    for line in raw_lines[1:]:
        parts = [p.strip().strip('"') for p in line.split(";")]
        if len(parts) != len(headers):
            continue

        val_idx = headers.index(value_col)
        raw_val = parts[val_idx] if val_idx < len(parts) else ""
        if not raw_val:
            continue
        try:
            value = float(raw_val)
        except (ValueError, TypeError):
            continue

        date_idx = headers.index(date_col)
        date_str = parts[date_idx] if date_idx < len(parts) else ""
        if not date_str:
            continue
        obs_date = date_str.replace("/", "-")

        row_dict = dict(zip(headers, parts))
        matched_sid: str | None = None
        for sid, fixed_pairs in series_fixed.items():
            match = True
            for dim_name, dim_value in fixed_pairs:
                if row_dict.get(dim_name) != dim_value:
                    match = False
                    break
            if match:
                matched_sid = sid
                break

        if matched_sid is None:
            continue

        records.append(
            {
                "series_id": matched_sid,
                "observation_date": obs_date,
                "value": value,
                "status_code": "",
            }
        )

    return records


def parse_data_csv(
    text: str,
    known_series_ids: list[str] | None = None,
    structure_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    raw_lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not raw_lines:
        return pd.DataFrame()

    headers = [h.strip().strip('"') for h in raw_lines[0].split(";")]
    if not headers:
        return pd.DataFrame()

    known_set = set(known_series_ids) if known_series_ids else None
    fmt = _detect_format(headers, known_set)

    if fmt == "wide":
        records = _parse_data_wide(headers, raw_lines, known_set)
    elif structure_df is not None and not structure_df.empty:
        records = _parse_data_long(headers, raw_lines, structure_df)
    else:
        records = _parse_data_wide(headers, raw_lines, known_set)

    return pd.DataFrame(records)
