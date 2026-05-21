from __future__ import annotations

from pathlib import Path
from typing import Optional

import click
import pandas as pd

from yieldcurves import storage
from yieldcurves.config import source_config
from yieldcurves.curves.tenors import standard_tenor_grid
from yieldcurves.hashing import compute_data_hash

_SOURCES: dict[str, str] = {
    "JP": "yieldcurves.sources.japan_mof",
    "GB": "yieldcurves.sources.uk_boe",
    "DE": "yieldcurves.sources.germany_bundesbank",
    "NL": "yieldcurves.sources.netherlands_dsta",
    "IT": "yieldcurves.sources.italy_borsa",
}

_COUNTRY_NAMES: dict[str, str] = {
    "JP": "Japan",
    "GB": "United Kingdom",
    "DE": "Germany",
    "NL": "Netherlands",
    "IT": "Italy",
}


def _import_source(country: str):
    import importlib

    module_path = _SOURCES.get(country)
    if module_path is None:
        msg = f"Unknown country code: {country}"
        raise click.BadParameter(msg)
    return importlib.import_module(module_path)


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
def backfill(country: Optional[str], all_flag: bool):
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
            df = storage.normalize_rows(rows)
            cfg = source_config(c)
            df["country_name"] = _COUNTRY_NAMES.get(c, c)
            df["source_id"] = f"{c.lower()}_{cfg.get('source_id', c.lower())}"
            storage.append_history(df)
            storage.update_latest(df)
            storage.sync_duckdb_after_write()
            storage.append_ingestion_log(
                {
                    "source_id": c,
                    "status": "success",
                    "rows_added": len(df),
                    "raw_file_hash": "",
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
    for c in countries:
        click.echo(f"Syncing {_COUNTRY_NAMES.get(c, c)}...")
        try:
            registry = storage.load_source_registry()
            last_row = registry[registry["source_id"] == c]
            last_hash = last_row["last_raw_file_hash"].iloc[0] if not last_row.empty else ""
            mod = _import_source(c)
            new_rows = mod.fetch_all()
            if not new_rows:
                click.echo(f"  No changes for {c}")
                continue
            df = storage.normalize_rows(new_rows)
            cfg = source_config(c)
            df["country_name"] = _COUNTRY_NAMES.get(c, c)
            df["source_id"] = f"{c.lower()}_{cfg.get('source_id', c.lower())}"
            current_hash = compute_data_hash(df.to_csv(index=False).encode())
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
            storage.append_history(df)
            storage.update_latest(df)
            storage.sync_duckdb_after_write()
            new_registry = pd.DataFrame(
                [{
                    "source_id": c,
                    "last_observation_date": df["observation_date"].max(),
                    "last_raw_file_hash": current_hash,
                }]
            )
            if not registry[registry["source_id"] == c].empty:
                registry.loc[registry["source_id"] == c, "last_raw_file_hash"] = current_hash
                max_date = df["observation_date"].max()
                registry.loc[registry["source_id"] == c, "last_observation_date"] = max_date
                storage.save_source_registry(registry)
            else:
                combined = pd.concat([registry, new_registry], ignore_index=True)
                storage.save_source_registry(combined)
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
            borsa_rows = latest[latest["country_code"] == "IT"].to_dict("records")
            bdi_rows = fetch_bmk0200()
            if not bdi_rows.empty:
                from yieldcurves.sources.italy_bancaditalia_bds import parse_bmk0200

                bdi_parsed = parse_bmk0200(bdi_rows)
                report = validate_btp_curve(borsa_rows, bdi_parsed)
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


if __name__ == "__main__":
    cli()
