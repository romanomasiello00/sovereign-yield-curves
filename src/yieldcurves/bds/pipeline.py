from __future__ import annotations

import io
import logging
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
import requests
from dateutil.relativedelta import relativedelta
from tenacity import retry, stop_after_attempt, wait_exponential

from yieldcurves.bds.catalog import build_series_catalog
from yieldcurves.config import load_config
from yieldcurves.hashing import compute_data_hash
from yieldcurves.storage import (
    bds_catalog_path,
    bds_data_path,
    bds_dir,
    bds_duckdb_path,
    bds_raw_dir,
)

log = logging.getLogger(__name__)

_A2A_BASE = "https://a2a.bancaditalia.it/infostat/dataservices"
_PUBLICATION_CONFIG = "bds_publications.yaml"


def _publication_url(pub_code: str) -> str:
    return f"{_A2A_BASE}/export/EN/CSV/ALL/PUBLICATION/BANKITALIA/DIFF/{pub_code}"


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=30))
def _download(url: str, timeout: int = 300) -> bytes:
    log.info("Downloading %s", url)
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    return resp.content


def _read_csv_from_zip(z: zipfile.ZipFile, name: str) -> str:
    raw = z.read(name)
    for enc in ("latin1", "utf-8", "cp1252"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, UnicodeError):
            continue
    return raw.decode("latin1", errors="replace")


def _extract_inner_zip_text(data: bytes) -> str | None:
    if data[:2] != b"PK":
        return None
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for name in z.namelist():
                if name.endswith(".csv"):
                    return _read_csv_from_zip(z, name)
    except zipfile.BadZipFile:
        return None
    return None


def _extract_csvs(data: bytes) -> dict[str, str]:
    result: dict[str, str] = {}

    with zipfile.ZipFile(io.BytesIO(data)) as outer_z:
        for outer_name in outer_z.namelist():
            if not outer_name.endswith(".zip"):
                continue

            inner_zip_data = outer_z.read(outer_name)
            upper = outer_name.upper()

            if "_STRUCTURE" in upper:
                text = _extract_inner_zip_text(inner_zip_data)
                if text:
                    result["structure"] = text
            elif "_DOMAIN" in upper:
                text = _extract_inner_zip_text(inner_zip_data)
                if text:
                    result["domain"] = text
            elif "_LEGEND" in upper:
                text = _extract_inner_zip_text(inner_zip_data)
                if text:
                    result["legend"] = text
            elif "_DATA" in upper:
                data_parts: list[str] = []
                try:
                    with zipfile.ZipFile(io.BytesIO(inner_zip_data)) as data_z:
                        for data_name in data_z.namelist():
                            if data_name.endswith(".zip"):
                                per_cube_data = data_z.read(data_name)
                                csv_text = _extract_inner_zip_text(per_cube_data)
                                if csv_text:
                                    data_parts.append(csv_text)
                except zipfile.BadZipFile:
                    csv_text = _extract_inner_zip_text(inner_zip_data)
                    if csv_text:
                        data_parts.append(csv_text)

                if data_parts:
                    result["data_parts"] = data_parts

    return result


def process_publication(
    target: dict[str, Any],
    config: dict[str, Any],
    skip_download: bool = False,
) -> dict[str, Any]:
    pub_code = target["object_id"]
    priority = target.get("priority", 1)
    theme = target.get("theme", "general")
    preserve_raw = True

    result: dict[str, Any] = {
        "publication_code": pub_code,
        "status": "error",
        "error": None,
        "catalog_count": 0,
        "core_5k_count": 0,
        "core_20k_count": 0,
        "archive_count": 0,
        "raw_hash": "",
    }

    try:
        if skip_download:
            candidates = sorted(bds_raw_dir().glob(f"{pub_code}_*.zip"))
            if not candidates:
                candidates = sorted(bds_raw_dir().glob(f"{pub_code}.zip"))
            if not candidates:
                result["error"] = f"No cached ZIP for {pub_code}"
                return result
            raw_path = candidates[0]
            data = raw_path.read_bytes()
            raw_hash = compute_data_hash(data) if preserve_raw else ""
        else:
            url = _publication_url(pub_code)
            data = _download(url)
            raw_hash = compute_data_hash(data) if preserve_raw else ""

            if preserve_raw:
                raw_path = bds_raw_dir() / f"{pub_code}_{raw_hash[:16]}.zip"
                raw_path.write_bytes(data)
                result["raw_hash"] = raw_hash

        csvs = _extract_csvs(data)

        missing = [k for k in ("structure",) if k not in csvs]
        if missing:
            result["error"] = f"Missing CSV files: {missing}"
            return result

        data_texts = csvs.get("data_parts", [csvs.get("data", "")])
        data_texts = [t for t in data_texts if t.strip()]

        if not data_texts:
            result["error"] = "No data found in publication"
            return result

        catalog, core_5k, core_20k, archive = build_series_catalog(
            publication_code=pub_code,
            priority=priority,
            theme=theme,
            structure_text=csvs.get("structure", ""),
            domain_text=csvs.get("domain", ""),
            legend_text=csvs.get("legend", ""),
            data_texts=data_texts,
            config=config,
        )

        if catalog.empty:
            result["error"] = "Empty catalog after processing"
            return result

        ts = datetime.now(timezone.utc).isoformat()
        catalog["last_ingested"] = ts
        for tier_df in (core_5k, core_20k, archive):
            if not tier_df.empty:
                tier_df["ingestion_timestamp"] = ts

        result["catalog"] = catalog
        result["core_5k"] = core_5k
        result["core_20k"] = core_20k
        result["archive"] = archive
        result["catalog_count"] = len(catalog)
        result["core_5k_count"] = len(core_5k)
        result["core_20k_count"] = len(core_20k)
        result["archive_count"] = len(archive)

        result["status"] = "success"

    except Exception as e:
        log.exception("Error processing %s: %s", pub_code, e)
        result["error"] = str(e)

    return result


def sync_all(
    skip_download: bool = False,
    max_workers: int = 3,
    publication: str | None = None,
) -> list[dict[str, Any]]:
    config = load_config(_PUBLICATION_CONFIG)
    targets = config.get("targets", [])
    excluded = {e["object_id"] for e in config.get("exclude", [])}
    active = [t for t in targets if t["object_id"] not in excluded]

    if publication:
        pub_upper = publication.upper()
        active = [t for t in active if t["object_id"] == pub_upper]
        if not active:
            log.warning("Unknown or excluded publication: %s", publication)
            return []

    bds_dir().mkdir(parents=True, exist_ok=True)
    bds_raw_dir().mkdir(parents=True, exist_ok=True)

    results: list[dict[str, Any]] = []

    log.info("Processing %d BDS publications (%d workers)", len(active), max_workers)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(process_publication, t, config, skip_download): t
            for t in active
        }
        for future in as_completed(futures):
            target = futures[future]
            try:
                r = future.result()
                results.append(r)
                pub_code = r["publication_code"]
                if r["status"] == "success":
                    log.info(
                        "%s: %d series (%d core_5k, %d core_20k, %d archive)",
                        pub_code,
                        r["catalog_count"],
                        r["core_5k_count"],
                        r["core_20k_count"],
                        r["archive_count"],
                    )
                else:
                    log.error("%s failed: %s", pub_code, r.get("error"))
            except Exception as e:
                log.error("%s exception: %s", target["object_id"], e)
                results.append(
                    {
                        "publication_code": target["object_id"],
                        "status": "error",
                        "error": str(e),
                    }
                )

    _merge_and_persist(results, config)
    return results


def _merge_and_persist(results: list[dict[str, Any]], config: dict[str, Any] | None = None) -> None:
    all_catalogs: list[pd.DataFrame] = []
    all_core_5k: list[pd.DataFrame] = []
    all_core_20k: list[pd.DataFrame] = []
    all_archive: list[pd.DataFrame] = []

    for r in results:
        if r["status"] != "success":
            continue
        if "catalog" in r and not r["catalog"].empty:
            all_catalogs.append(r["catalog"])
        if "core_5k" in r and not r["core_5k"].empty:
            all_core_5k.append(r["core_5k"])
        if "core_20k" in r and not r["core_20k"].empty:
            all_core_20k.append(r["core_20k"])
        if "archive" in r and not r["archive"].empty:
            all_archive.append(r["archive"])

    def _merge_new_with_existing(
        new_dfs: list[pd.DataFrame],
        existing_path: Path,
        dedup_cols: list[str] | None = None,
    ) -> pd.DataFrame:
        if not new_dfs:
            if existing_path.exists():
                return pd.read_parquet(existing_path)
            return pd.DataFrame()

        merged = pd.concat(new_dfs, ignore_index=True)

        if existing_path.exists():
            existing = pd.read_parquet(existing_path)
            if dedup_cols and not merged.empty and not existing.empty:
                existing_ids = existing[dedup_cols].astype(str).apply(
                    lambda r: "|".join(r), axis=1
                )
                merged_ids = merged[dedup_cols].astype(str).apply(
                    lambda r: "|".join(r), axis=1
                )
                new = merged[~merged_ids.isin(existing_ids)]
                merged = pd.concat([existing, new], ignore_index=True)
            else:
                merged = pd.concat([existing, merged], ignore_index=True)

        return merged

    cat_dedup = ["series_id"]
    merged_catalog = _merge_new_with_existing(all_catalogs, bds_catalog_path(), cat_dedup)
    if not merged_catalog.empty:
        merged_catalog.to_parquet(bds_catalog_path(), index=False)
        log.info("Wrote catalog: %d series to %s", len(merged_catalog), bds_catalog_path())
    else:
        log.warning("No catalog data to persist")

    tier_config = [
        ("core_5k", all_core_5k),
        ("core_20k", all_core_20k),
        ("archive", all_archive),
    ]
    data_dedup = ["series_id", "observation_date"]
    total_obs = 0
    for tier_name, dfs in tier_config:
        if dfs or bds_data_path(tier_name).exists():
            merged = _merge_new_with_existing(dfs, bds_data_path(tier_name), data_dedup)
            if not merged.empty:
                merged.to_parquet(bds_data_path(tier_name), index=False)
                total_obs += len(merged)
                data_path = bds_data_path(tier_name)
                log.info("Wrote %s: %d observations to %s", tier_name, len(merged), data_path)

    log.info("Total observations stored: %d", total_obs)

    _merge_and_persist_duckdb(merged_catalog, config)


def _compute_next_release(
    schedule: dict[str, Any],
) -> str:
    freq = schedule.get("frequency", "monthly")
    lag_days = schedule.get("reference_lag_days", 30)
    base_date = datetime.now(timezone.utc).replace(day=1)

    if freq == "monthly":
        ref_end = base_date - relativedelta(months=1)
    elif freq == "quarterly":
        quarter_start_month = ((base_date.month - 1) // 3) * 3 + 1
        ref_end = base_date.replace(month=quarter_start_month) - relativedelta(days=1)
    elif freq == "semi_annual":
        if base_date.month >= 7:
            ref_end = base_date.replace(month=6, day=30)
        else:
            ref_end = base_date.replace(month=12, day=31) - relativedelta(years=1)
    elif freq == "annual":
        ref_end = base_date.replace(month=12, day=31) - relativedelta(years=1)
    else:
        ref_end = base_date - relativedelta(months=1)

    next_release = ref_end + relativedelta(days=lag_days)
    return next_release.strftime("%Y-%m-%d")


def _merge_and_persist_duckdb(
    merged_catalog: pd.DataFrame,
    config: dict[str, Any],
) -> None:
    con = duckdb.connect(str(bds_duckdb_path()))
    try:
        # Series catalog
        if not merged_catalog.empty:
            con.execute("CREATE OR REPLACE TABLE series_catalog AS SELECT * FROM merged_catalog")

        # Observations per tier
        obs_cols_str = (
            "series_id VARCHAR, observation_date VARCHAR, value VARCHAR, "
            "status_code VARCHAR, publication_code VARCHAR, "
            "tier VARCHAR, ingestion_timestamp VARCHAR"
        )
        for tier_name in ("core_5k", "core_20k", "archive"):
            parquet_path = bds_data_path(tier_name)
            tbl = f"{tier_name}_observations"
            # Create table with schema (empty by default)
            con.execute(
                f"CREATE OR REPLACE TABLE {tbl} ({obs_cols_str})"
            )
            if parquet_path.exists():
                con.execute(
                    f"INSERT INTO {tbl} SELECT * FROM read_parquet('{parquet_path}')"
                )

        # All-observations view (explicit column names for safety)
        con.execute(
            "CREATE OR REPLACE VIEW all_observations AS "
            "SELECT 'core_5k' AS _tier, series_id, observation_date, "
            "  value, status_code, publication_code, tier AS source_tier, "
            "  ingestion_timestamp "
            "FROM core_5k_observations "
            "UNION ALL "
            "SELECT 'core_20k' AS _tier, series_id, observation_date, "
            "  value, status_code, publication_code, tier AS source_tier, "
            "  ingestion_timestamp "
            "FROM core_20k_observations "
            "UNION ALL "
            "SELECT 'archive' AS _tier, series_id, observation_date, "
            "  value, status_code, publication_code, tier AS source_tier, "
            "  ingestion_timestamp "
            "FROM archive_observations"
        )

        # Publication metadata with release schedule
        pub_rows: list[dict[str, Any]] = []
        for t in config.get("targets", []):
            schedule = t.get("release_schedule", {})
            pub_rows.append(
                {
                    "publication_code": t["object_id"],
                    "description": t.get("description", ""),
                    "theme": t.get("theme", ""),
                    "priority": t.get("priority", 1),
                    "release_frequency": schedule.get("frequency", "unknown"),
                    "reference_lag_days": schedule.get("reference_lag_days", 0),
                    "typical_release_day": schedule.get("typical_release_day", 1),
                    "next_expected_release": _compute_next_release(schedule),
                    "is_excluded": False,
                    "exclusion_reason": "",
                }
            )
        for e in config.get("exclude", []):
            pub_rows.append(
                {
                    "publication_code": e["object_id"],
                    "description": e.get("description", ""),
                    "theme": "",
                    "priority": 99,
                    "release_frequency": "unknown",
                    "reference_lag_days": 0,
                    "typical_release_day": 1,
                    "next_expected_release": "",
                    "is_excluded": True,
                    "exclusion_reason": e.get("reason", ""),
                }
            )
        pub_df = pd.DataFrame(pub_rows)
        con.execute("CREATE OR REPLACE TABLE publication_metadata AS SELECT * FROM pub_df")
        _ = pub_df  # used by DuckDB SQL magic variable resolution above

        # Series summary view (catalog + latest observation date + obs count)
        con.execute(
            "CREATE OR REPLACE VIEW series_summary AS "
            "SELECT "
            "  sc.series_id, sc.publication_code, sc.series_name, "
            "  sc.frequency_code, sc.frequency_label, sc.theme, "
            "  sc.score, sc.tier, sc.is_active, sc.last_ingested, "
            "  MAX(obs.observation_date) AS last_observation_date, "
            "  COUNT(obs.value) AS observation_count "
            "FROM series_catalog sc "
            "LEFT JOIN all_observations obs ON sc.series_id = obs.series_id "
            "GROUP BY ALL"
        )

        log.info("DuckDB synced: %s", bds_duckdb_path())

    finally:
        con.close()
