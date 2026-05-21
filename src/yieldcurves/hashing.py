import hashlib
from pathlib import Path


def compute_file_hash(path: Path | str) -> str:
    sha = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha.update(chunk)
    return sha.hexdigest()


def compute_data_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def compute_row_hash(row: dict) -> str:
    serialised = "|".join(
        str(row.get(k, ""))
        for k in [
            "country_code",
            "source_id",
            "observation_date",
            "tenor_years",
            "curve_family",
            "rate_type",
        ]
    )
    return hashlib.sha256(serialised.encode("utf-8")).hexdigest()
