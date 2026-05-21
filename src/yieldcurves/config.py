from pathlib import Path
from typing import Any

import yaml


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def load_config(name: str) -> dict[str, Any]:
    path = _project_root() / "config" / name
    if not path.exists():
        msg = f"Config file not found: {path}"
        raise FileNotFoundError(msg)
    with open(path) as f:
        return yaml.safe_load(f)


def load_sources_config() -> dict[str, Any]:
    return load_config("sources.yaml")


def load_tenors_config() -> dict[str, Any]:
    return load_config("tenors.yaml")


def standard_tenors() -> list[dict[str, Any]]:
    return load_tenors_config()["standard_tenors"]


def standard_tenor_years() -> list[float]:
    return [t["years"] for t in standard_tenors()]


def standard_tenor_labels() -> list[str]:
    return [t["label"] for t in standard_tenors()]


def source_config(country_code: str) -> dict[str, Any]:
    sources = load_sources_config()["sources"]
    for key, cfg in sources.items():
        if cfg.get("country_code") == country_code:
            return cfg
    msg = f"No source config found for country: {country_code}"
    raise ValueError(msg)
