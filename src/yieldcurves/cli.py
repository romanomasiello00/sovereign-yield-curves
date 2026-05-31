from __future__ import annotations

from pathlib import Path
from typing import Optional

import click
import numpy as np
import pandas as pd

from yieldcurves import storage
from yieldcurves.bds import pipeline as bds_pipeline
from yieldcurves.config import source_config
from yieldcurves.curves.reconstruct import build_standard_grid
from yieldcurves.curves.tenors import standard_tenor_grid
from yieldcurves.hashing import compute_data_hash

_SOURCES: dict[str, str] = {
    "JP": "yieldcurves.sources.japan_mof",
    "GB": "yieldcurves.sources.uk_boe",
    "DE": "yieldcurves.sources.germany_bundesbank",
    "NL": "yieldcurves.sources.netherlands_dsta",
    "IT": "yieldcurves.sources.italy_bancaditalia_bds",
    "SG": "yieldcurves.sources.singapore_mas",
    "SE": "yieldcurves.sources.sweden_riksbank",
    "NO": "yieldcurves.sources.norway_norgesbank",
    "AU": "yieldcurves.sources.australia_rba",
}

_COUNTRY_NAMES: dict[str, str] = {
    "JP": "Japan",
    "GB": "United Kingdom",
    "DE": "Germany",
    "NL": "Netherlands",
    "IT": "Italy",
    "SG": "Singapore",
    "SE": "Sweden",
    "NO": "Norway",
    "AU": "Australia",
}


def _import_source(country: str):
    import importlib

    module_path = _SOURCES.get(country)
    if module_path is None:
        msg = f"Unknown country code: {country}"
        raise click.BadParameter(msg)
    return importlib.import_module(module_path)


def _build_standard_grid_rows(rows: list[dict], country: str, cfg: dict) -> list[dict]:
    if cfg.get("fit_method_standard_grid") == "pchip_interpolation":
        standard_rows = build_standard_grid(
            rows,
            country_code=country,
            country_name=_COUNTRY_NAMES.get(country, country),
            currency=cfg.get("currency", ""),
            source_id=f"{country.lower()}_{cfg.get('source_id', country.lower())}",
            source_name=cfg.get("source_name", ""),
            source_url=cfg.get("source_url", ""),
            rate_type=cfg.get("rate_type", ""),
            curve_family=cfg.get("curve_family", ""),
            compounding=cfg.get("compounding", "source_native"),
            day_count=cfg.get("day_count", "source_native"),
        )
        return rows + standard_rows
    return rows


def _default_source_id(country: str, cfg: dict) -> str:
    return f"{country.lower()}_{cfg.get('source_id', country.lower())}"


def _preserve_row_source_ids(df: pd.DataFrame, fallback_source_id: str) -> pd.DataFrame:
    df = df.copy()
    if "source_id" not in df.columns:
        df["source_id"] = fallback_source_id
        return df
    source_ids = df["source_id"].replace({"": None, "nan": None, "None": None})
    df["source_id"] = source_ids.fillna(fallback_source_id)
    return df


def _stable_frame_hash(df: pd.DataFrame) -> str:
    stable = df.copy()
    for col in ("ingestion_timestamp", "revision_id"):
        if col in stable.columns:
            stable = stable.drop(columns=col)
    stable = stable.replace({np.nan: None})
    sort_cols = [c for c in stable.columns if c in ("country_code", "source_id", "observation_date", "tenor_years", "curve_family", "rate_type")]
    if sort_cols:
        stable = stable.sort_values(sort_cols).reset_index(drop=True)
    return compute_data_hash(stable.to_csv(index=False).encode())


def _save_registry_snapshot(country: str, df: pd.DataFrame, current_hash: str) -> None:
    registry = storage.load_source_registry()
    max_date = df["observation_date"].max() if not df.empty else ""
    new_registry = pd.DataFrame(
        [{
            "source_id": country,
            "last_observation_date": max_date,
            "last_raw_file_hash": current_hash,
        }]
    )
    if not registry[registry["source_id"] == country].empty:
        registry.loc[registry["source_id"] == country, "last_raw_file_hash"] = current_hash
        registry.loc[registry["source_id"] == country, "last_observation_date"] = max_date
        storage.save_source_registry(registry)
    else:
        combined = pd.concat([registry, new_registry], ignore_index=True)
        storage.save_source_registry(combined)


def _latest_observation_cutoffs(existing: pd.DataFrame) -> dict[tuple[str, str, str, str], str]:
    if existing.empty:
        return {}
    key_cols = ["country_code", "source_id", "curve_family", "rate_type"]
    required = key_cols + ["observation_date"]
    if any(col not in existing.columns for col in required):
        return {}
    grouped = existing.dropna(subset=["observation_date"]).groupby(key_cols, dropna=False)["observation_date"].max()
    return {tuple(str(part) for part in key): str(value) for key, value in grouped.items()}


def _filter_new_observations(df: pd.DataFrame, existing_latest: pd.DataFrame) -> pd.DataFrame:
    """Keep only observations newer than the stored latest date for the same source stream."""
    if df.empty or existing_latest.empty:
        return df
    cutoffs = _latest_observation_cutoffs(existing_latest)
    if not cutoffs:
        return df

    def is_new(row: pd.Series) -> bool:
        key = (
            str(row["country_code"]),
            str(row["source_id"]),
            str(row["curve_family"]),
            str(row["rate_type"]),
        )
        cutoff = cutoffs.get(key)
        return cutoff is None or str(row["observation_date"]) > cutoff

    return df[df.apply(is_new, axis=1)].copy()


def _validate_country(ctx, param, value):
    if value is not None and value.upper() not in _SOURCES:
        available = ", ".join(sorted(_SOURCES))
        raise click.BadParameter(f"Unknown country. Available: {available}")
    return value.upper() if value else None


@click.group()
def cli():
    """Sovereign yield curve ingestion pipeline."""


@cli.command()
@click.option("--country", "-c", default=None, callback=_validate_country,
              help="Country code (JP, GB, DE, NL, IT)")
@click.option("--all", "all_flag", is_flag=True, help="Backfill all countries")
@click.option(
    "--replace-existing",
    is_flag=True,
    help="Replace existing rows for the selected country in latest/history instead of appending",
)
def backfill(country: Optional[str], all_flag: bool, replace_existing: bool):
    """Backfill historical yield curve data for a country."""
    countries = list(_SOURCES) if all_flag or country is None else [country]
    for c in countries:
        click.echo(f"Backfilling {_COUNTRY_NAMES.get(c, c)}...")
        try:
            mod = _import_source(c)
            rows = mod.fetch_all()
            if not rows:
                click.echo(f"  No data fetched for {c}")
                continue
            cfg = source_config(c)
            rows = _build_standard_grid_rows(rows, c, cfg)
            df = storage.normalize_rows(rows)
            df["country_name"] = _COUNTRY_NAMES.get(c, c)
            df = _preserve_row_source_ids(df, _default_source_id(c, cfg))
            current_hash = _stable_frame_hash(df)
            if replace_existing:
                storage.replace_country_history(c, df)
                storage.replace_country_latest(c, df)
            else:
                storage.append_history(df)
                storage.update_latest(df)
            storage.sync_duckdb_after_write()
            _save_registry_snapshot(c, df, current_hash)
            storage.append_ingestion_log(
                {
                    "source_id": c,
                    "status": "replaced" if replace_existing else "success",
                    "rows_added": len(df),
                    "raw_file_hash": current_hash,
                }
            )
            click.echo(f"  Added {len(df)} rows for {c}")
        except Exception as e:
            click.echo(f"  Error backfilling {c}: {e}", err=True)


@cli.command()
@click.option("--country", "-c", default=None, callback=_validate_country, help="Country code")
@click.option("--all", "all_flag", is_flag=True, help="Sync all countries")
def sync(country: Optional[str], all_flag: bool):
    """Incremental sync of yield curve data."""
    countries = list(_SOURCES) if all_flag else [country] if country else list(_SOURCES)
    existing_latest = storage.load_latest()
    for c in countries:
        click.echo(f"Syncing {_COUNTRY_NAMES.get(c, c)}...")
        try:
            registry = storage.load_source_registry()
            last_row = registry[registry["source_id"] == c]
            last_hash = last_row["last_raw_file_hash"].iloc[0] if not last_row.empty else ""
            last_obs_date = (
                last_row["last_observation_date"].iloc[0]
                if not last_row.empty and "last_observation_date" in last_row.columns
                else None
            )
            mod = _import_source(c)
            import inspect
            fetch_kwargs: dict = {}
            if last_obs_date and "from_date" in inspect.signature(mod.fetch_all).parameters:
                fetch_kwargs["from_date"] = str(last_obs_date)
            new_rows = mod.fetch_all(**fetch_kwargs)
            if not new_rows:
                click.echo(f"  No changes for {c}")
                continue
            cfg = source_config(c)
            new_rows = _build_standard_grid_rows(new_rows, c, cfg)
            df = storage.normalize_rows(new_rows)
            df["country_name"] = _COUNTRY_NAMES.get(c, c)
            df = _preserve_row_source_ids(df, _default_source_id(c, cfg))
            current_hash = _stable_frame_hash(df)
            fetched_df = df
            if current_hash == last_hash:
                click.echo(f"  No changes for {c} (hash unchanged)")
                storage.append_ingestion_log(
                    {
                        "source_id": c,
                        "status": "no_change",
                        "rows_added": 0,
                        "raw_file_hash": current_hash,
                    }
                )
                continue
            df = _filter_new_observations(df, existing_latest)
            if df.empty:
                click.echo(f"  No new observations for {c}")
                _save_registry_snapshot(c, fetched_df, current_hash)
                storage.append_ingestion_log(
                    {
                        "source_id": c,
                        "status": "no_new_observations",
                        "rows_added": 0,
                        "raw_file_hash": current_hash,
                    }
                )
                continue
            storage.update_latest(df)
            storage.update_duckdb_latest(df)
            _save_registry_snapshot(c, fetched_df, current_hash)
            existing_latest = storage.load_latest()
            storage.append_ingestion_log(
                {
                    "source_id": c,
                    "status": "success",
                    "rows_added": len(df),
                    "raw_file_hash": current_hash,
                }
            )
            click.echo(f"  Synced {len(df)} rows for {c}")
        except Exception as e:
            click.echo(f"  Error syncing {c}: {e}", err=True)


@cli.command()
@click.option("--country", "-c", default=None, help="Country to validate (IT or NL)")
def validate(country: Optional[str]):
    """Validate reconstructed curves against official benchmarks."""
    if country and country.upper() not in ("IT", "NL"):
        click.echo("Validation only supported for IT and NL")
        return
    if country is None or country.upper() == "IT":
        click.echo("Validating Italy BTP curve...")
        try:
            from yieldcurves.sources.italy_bancaditalia_bds import fetch_bmk0200, validate_btp_curve

            latest = storage._empty_dataframe()
            latest_path = storage.processed_dir() / "yield_curves_latest.parquet"
            if latest_path.exists():
                latest = pd.read_parquet(latest_path)
            italy_rows = latest[latest["country_code"] == "IT"].to_dict("records")
            bdi_rows = fetch_bmk0200()
            if not bdi_rows.empty:
                from yieldcurves.sources.italy_bancaditalia_bds import parse_bmk0200

                bdi_parsed = parse_bmk0200(bdi_rows)
                report = validate_btp_curve(italy_rows, bdi_parsed)
                if not report.empty:
                    click.echo(f"  Validation report: {len(report)} matching observations")
                    click.echo(f"  Mean difference (bp): {report['difference_bp'].mean():.2f}")
                    click.echo(f"  Max difference (bp): {report['difference_bp'].abs().max():.2f}")
                    output_path = storage.processed_dir() / "validation_report_it.parquet"
                    storage.write_parquet(report, output_path)
                    click.echo(f"  Report saved to {output_path}")
                else:
                    click.echo("  No overlapping observations found for validation")
            else:
                click.echo("  Could not fetch Banca d'Italia data")
        except Exception as e:
            click.echo(f"  Validation error: {e}", err=True)


@cli.command()
@click.option("--format", "-f", "output_format",
              type=click.Choice(["parquet", "csv", "duckdb"]), default="parquet")
@click.option("--output", "-o", default=None, help="Output path")
def export(output_format: str, output: Optional[str]):
    """Export processed yield curve data."""
    latest_path = storage.processed_dir() / "yield_curves_latest.parquet"
    if not latest_path.exists():
        click.echo("No data found. Run backfill or sync first.")
        return
    df = pd.read_parquet(latest_path)
    if output is None:
        output = str(storage.processed_dir() / f"yield_curves_export.{output_format}")
    out_path = Path(output)
    if output_format == "parquet":
        storage.write_parquet(df, out_path)
    elif output_format == "csv":
        df.to_csv(out_path, index=False)
    elif output_format == "duckdb":
        con = storage.open_duckdb()
        storage.write_duckdb(df, "yield_curves_export", con)
        con.close()
    click.echo(f"Exported {len(df)} rows to {out_path}")


@cli.command()
def tenors():
    """Display the standard tenor grid."""
    grid = standard_tenor_grid()
    click.echo("Standard tenor grid:")
    for t in grid:
        click.echo(f"  {t['label']:>5s} = {t['years']:>8.6f} years")


@cli.group()
def bds():
    """Banca d'Italia BDS publications management."""


@bds.command(name="sync")
@click.option("--workers", "-w", default=3, help="Parallel download workers")
@click.option("--skip-download", is_flag=True, help="Use cached ZIPs only")
@click.option("--publication", "-p", default=None, help="Single publication code (e.g. SDDS)")
def bds_sync(workers: int, skip_download: bool, publication: Optional[str]):
    """Download and process BDS publications.

    Downloads publication-level ZIPs from the A2A API, parses metadata,
    scores series, and stores into tiers (core_5k, core_20k, archive).
    """
    click.echo("Syncing BDS publications...")
    try:
        results = bds_pipeline.sync_all(
            skip_download=skip_download,
            max_workers=workers,
            publication=publication,
        )
        success = [r for r in results if r["status"] == "success"]
        failed = [r for r in results if r["status"] != "success"]

        click.echo("\nResults:")
        click.echo(f"  Success: {len(success)} publications")
        click.echo(f"  Failed:  {len(failed)} publications")

        total_catalog = 0
        total_core_5k = 0
        total_core_20k = 0
        total_archive = 0
        for r in success:
            total_catalog += r.get("catalog_count", 0)
            total_core_5k += r.get("core_5k_count", 0)
            total_core_20k += r.get("core_20k_count", 0)
            total_archive += r.get("archive_count", 0)
            click.echo(
                f"  {r['publication_code']}: "
                f"{r['catalog_count']} series "
                f"({r['core_5k_count']} core_5k, "
                f"{r['core_20k_count']} core_20k, "
                f"{r['archive_count']} archive)"
            )

        click.echo("\nTotals:")
        click.echo(f"  Catalog series: {total_catalog}")
        click.echo(f"  Core 5k obs:    {total_core_5k}")
        click.echo(f"  Core 20k obs:   {total_core_20k}")
        click.echo(f"  Archive obs:    {total_archive}")

        if failed:
            click.echo("\nFailed publications:")
            for r in failed:
                click.echo(f"  {r['publication_code']}: {r.get('error')}")

    except Exception as e:
        click.echo(f"Error syncing BDS: {e}", err=True)


@bds.command()
def catalog():
    """Show BDS series catalog summary."""
    cat_path = storage.bds_catalog_path()
    if not cat_path.exists():
        click.echo("No catalog found. Run 'yieldcurves bds sync' first.")
        return

    df = pd.read_parquet(cat_path)
    click.echo(f"Series catalog: {len(df)} series")

    click.echo("\nBy publication:")
    pub_counts = df["publication_code"].value_counts().sort_index()
    for pub, count in pub_counts.items():
        click.echo(f"  {pub}: {count}")

    click.echo("\nBy tier:")
    tier_counts = df["tier"].value_counts()
    for tier, count in tier_counts.items():
        click.echo(f"  {tier}: {count}")

    click.echo("\nBy frequency:")
    freq_counts = df["frequency_label"].value_counts()
    for freq, count in freq_counts.items():
        click.echo(f"  {freq}: {count}")

    click.echo("\nTop 10 series by score:")
    top = df.nlargest(10, "score")[
        ["series_id", "publication_code", "series_name", "score", "tier"]
    ]
    for _, row in top.iterrows():
        click.echo(
            f"  {row['series_id'][:50]:50s} "
            f"{row['publication_code']:4s} "
            f"{row['score']:8.2f} "
            f"{row['tier']:8s}"
        )


@bds.command()
@click.option("--tier", "-t", type=click.Choice(["core_5k", "core_20k", "archive"]),
              help="Filter by tier")
def stats(tier: Optional[str]):
    """Show BDS data statistics."""
    tiers = ["core_5k", "core_20k", "archive"] if tier is None else [tier]
    for t in tiers:
        path = storage.bds_data_path(t)
        if not path.exists():
            click.echo(f"No data for tier: {t}")
            continue
        df = pd.read_parquet(path)
        click.echo(f"\n{t}:")
        click.echo(f"  Observations: {len(df)}")
        click.echo(f"  Series:       {df['series_id'].nunique()}")
        click.echo(f"  Publications: {df['publication_code'].nunique()}")
        if "observation_date" in df.columns:
            dr = f"{df['observation_date'].min()} to {df['observation_date'].max()}"
            click.echo(f"  Date range:   {dr}")
        if "value" in df.columns:
            click.echo(f"  Value range:  {df['value'].min():.4f} to {df['value'].max():.4f}")


@bds.command()
@click.argument("sql", required=False)
@click.option("--tables", is_flag=True, help="List available tables")
@click.option("--csv", is_flag=True, help="Output as CSV")
def query(sql: Optional[str], tables: bool, csv: bool):
    """Run an ad-hoc SQL query against the BDS DuckDB database.

    Use --tables to list available tables and views.
    """
    import duckdb

    db_path = storage.bds_duckdb_path()
    if not db_path.exists():
        click.echo("No DuckDB database found. Run 'yieldcurves bds sync' first.")
        return

    con = duckdb.connect(str(db_path))
    try:
        if tables:
            result = con.execute(
                "SELECT table_name, table_type FROM information_schema.tables "
                "WHERE table_schema = 'main' ORDER BY table_type, table_name"
            ).fetchdf()
            click.echo("Available tables/views:")
            for _, row in result.iterrows():
                click.echo(f"  {row['table_type']:5s} {row['table_name']}")
            return

        if not sql:
            click.echo("Provide a SQL query or use --tables to list tables.")
            return

        result = con.execute(sql).fetchdf()
        if result.empty:
            click.echo("Query returned no rows.")
            return

        if csv:
            click.echo(result.to_csv(index=False))
        else:
            click.echo(result.to_string(index=False))
    finally:
        con.close()


@bds.command()
@click.argument("publication", required=False)
def download(publication: Optional[str]):
    """Download a single publication ZIP for inspection.

    If PUBLICATION is not specified, downloads all targets.
    """
    config = __import__("yaml").safe_load(
        open(Path(__file__).resolve().parent.parent.parent / "config" / "bds_publications.yaml")
    )
    if publication:
        targets = [t for t in config.get("targets", []) if t["object_id"] == publication.upper()]
        if not targets:
            click.echo(f"Unknown publication: {publication}")
            return
    else:
        excluded = {e["object_id"] for e in config.get("exclude", [])}
        targets = [t for t in config.get("targets", []) if t["object_id"] not in excluded]

    storage.bds_raw_dir().mkdir(parents=True, exist_ok=True)

    for t in targets:
        code = t["object_id"]
        url = bds_pipeline._publication_url(code)
        click.echo(f"Downloading {code}...")
        try:
            data = bds_pipeline._download(url)
            h = compute_data_hash(data)
            path = storage.bds_raw_dir() / f"{code}_{h[:16]}.zip"
            path.write_bytes(data)
            click.echo(f"  Saved to {path} ({len(data)} bytes)")
        except Exception as e:
            click.echo(f"  Error: {e}", err=True)


if __name__ == "__main__":
    cli()
