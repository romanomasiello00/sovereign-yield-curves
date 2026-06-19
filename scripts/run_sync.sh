#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$ROOT/logs"
mkdir -p "$LOG_DIR"

if [[ -x "$ROOT/.venv/bin/python" ]]; then
  PYTHON_BIN="$ROOT/.venv/bin/python"
else
  PYTHON_BIN="${PYTHON_BIN:-python3}"
fi

export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

# Data store lives OFF the iCloud/Desktop volume for IO stability (avoids the
# intermittent "Operation timed out" + conflict-copy corruption on the large
# parquet files). Override with YIELDCURVES_DATA_DIR if needed.
export YIELDCURVES_DATA_DIR="${YIELDCURVES_DATA_DIR:-$HOME/yield_curves_store}"

cd "$ROOT"

"$PYTHON_BIN" -m yieldcurves.cli sync --all
