#!/usr/bin/env python3
"""Freeze what is recoverable about the archived climate acquisition.

The monthly and daily tables in the release predate the reproducible retrieval
path in ``scripts/utils/fetch_monthly_weather.py``: no raw API responses were
kept and no provenance record was written at retrieval time.  Rather than
assert a retrieval date or a model version that was never captured, this script
records exactly what the surviving artifacts support and marks the rest as
unrecoverable.

Recoverable: the endpoint and request parameters (read out of the acquisition
code), the requested date window, the observed date range of each derived
table, the byte size and SHA-256 of every input and output, and an upper bound
on the retrieval date from the output file modification time.

Not recoverable and reported as such: raw response bodies, the per-request
timestamps, and any Open-Meteo model or dataset version.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ENDPOINT = "https://archive-api.open-meteo.com/v1/archive"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def artifact(path: Path, project_root: Path) -> dict:
    stat = path.stat()
    return {
        "path": str(path.relative_to(project_root)),
        "bytes": stat.st_size,
        "sha256": sha256(path),
        "mtime_utc": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
    }


def date_range(path: Path, column: str) -> dict:
    values = []
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            value = (row.get(column) or "").strip()
            if value:
                values.append(value)
    return {"column": column, "min": min(values), "max": max(values), "rows": len(values)}


def declared_window(script: Path) -> dict:
    source = script.read_text(encoding="utf-8")
    start = re.search(r'START_DATE\s*=\s*(?:os\.environ\.get\([^,]+,\s*)?"([0-9-]+)"', source)
    end = re.search(r'END_DATE\s*=\s*(?:os\.environ\.get\([^,]+,\s*)?"([0-9-]+)"', source)
    variables = re.search(r'"daily":\s*\[(.*?)\]', source, re.S) or re.search(
        r"DAILY_VARIABLES\s*=\s*\[(.*?)\]", source, re.S
    )
    return {
        "start_date": start.group(1) if start else None,
        "end_date": end.group(1) if end else None,
        "daily_variables": (
            [item.strip().strip('"') for item in variables.group(1).split(",") if item.strip()]
            if variables
            else None
        ),
    }


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=root)
    parser.add_argument(
        "--output",
        type=Path,
        default=root / "data/processed/climate/climate_acquisition_frozen.json",
    )
    args = parser.parse_args()
    project_root = args.project_root.resolve()

    monthly = project_root / "data/processed/climate/monthly_weather_averages.tsv"
    daily = project_root / "data/processed/climate/daily_weather.tsv"
    monthly_script = project_root / "scripts/utils/fetch_monthly_weather.py"
    daily_script = project_root / "scripts/utils/fetch_daily_weather.py"
    sites = project_root / "data/metadata/geodata/site_altitudes.tsv"
    for required in (monthly, daily, monthly_script, daily_script, sites):
        if not required.is_file():
            print(f"FAIL: required artifact is absent: {required}", file=sys.stderr)
            return 1

    record = {
        "endpoint": ENDPOINT,
        "monthly": {
            "output": artifact(monthly, project_root),
            "acquisition_code": artifact(monthly_script, project_root),
            "declared_window": declared_window(monthly_script),
            "observed_period": {
                "min_year_month": min(
                    (row["Year"], row["Month"])
                    for row in csv.DictReader(monthly.open(encoding="utf-8"), delimiter="\t")
                ),
            },
        },
        "daily": {
            "output": artifact(daily, project_root),
            "acquisition_code": artifact(daily_script, project_root),
            "declared_window": declared_window(daily_script),
            "observed_period": date_range(daily, "Date"),
        },
        "site_table": artifact(sites, project_root),
        "retrieval_date_evidence": (
            "No retrieval timestamp was captured. The output file modification "
            "times bound it from above; the monthly acquisition code additionally "
            "records the intended archive cut-off in its frozen end date."
        ),
        "unrecoverable": [
            "raw Open-Meteo response bodies for the archived tables",
            "per-request retrieval timestamps",
            "an Open-Meteo model or dataset version (not reported by the archive API)",
        ],
        "reproducibility_note": (
            "scripts/utils/fetch_monthly_weather.py now writes raw response "
            "snapshots and a provenance record, and both acquisition scripts use "
            "an explicit frozen end date instead of today(); a future retrieval "
            "is therefore reproducible from snapshots without network access."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(record, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    print(f"PASS: frozen climate acquisition provenance -> {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
