#!/usr/bin/env python3
"""Freeze the NASA POWER precipitation column used by the ecology analysis.

The historical source CSV is preserved in the linked ecology-paper repository.
This script extracts only site, date and PRECTOTCORR, validates a complete
60-site daily panel, writes deterministic gzip bytes, and records both source
and output hashes. It does not claim undocumented original request parameters.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import platform
from pathlib import Path

import pandas as pd


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=(
            root
            / "empty-quarter-amplicon/repository/data/climate/daily_weather_full.csv"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=(
            root
            / "data/processed/climate/nasa_power_daily_precipitation.tsv.gz"
        ),
    )
    args = parser.parse_args()

    frame = pd.read_csv(
        args.source,
        usecols=["site", "date", "PRECTOTCORR"],
        dtype={"site": int, "date": str, "PRECTOTCORR": float},
    )
    frame = frame.rename(
        columns={"site": "Site", "date": "Date", "PRECTOTCORR": "Precip_mm"}
    )
    frame["Date"] = pd.to_datetime(
        frame["Date"], format="%Y%m%d", errors="raise"
    ).dt.strftime("%Y-%m-%d")
    frame = frame.sort_values(["Site", "Date"]).reset_index(drop=True)
    if frame.duplicated(["Site", "Date"]).any():
        raise ValueError("Duplicate NASA POWER site-date rows")
    if sorted(frame["Site"].unique()) != list(range(1, 61)):
        raise ValueError("NASA POWER source must contain exactly sites 1-60")
    counts = frame.groupby("Site").size()
    if counts.nunique() != 1 or int(counts.iloc[0]) != 1_461:
        raise ValueError(f"Unexpected daily coverage by site: {counts.to_dict()}")
    if frame["Precip_mm"].isna().any() or (frame["Precip_mm"] < 0).any():
        raise ValueError("NASA POWER precipitation must be finite and nonnegative")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("wb") as raw_handle:
        with gzip.GzipFile(
            filename="",
            mode="wb",
            fileobj=raw_handle,
            mtime=0,
        ) as gzip_handle:
            text_handle = io.TextIOWrapper(
                gzip_handle, encoding="utf-8", newline=""
            )
            writer = csv.writer(text_handle, delimiter="\t", lineterminator="\n")
            writer.writerow(["Site", "Date", "Precip_mm"])
            for row in frame.itertuples(index=False):
                writer.writerow([row.Site, row.Date, f"{row.Precip_mm:.12g}"])
            text_handle.flush()
            text_handle.detach()

    manifest_path = args.output.with_suffix("").with_suffix(".manifest.json")
    manifest = {
        "schema_version": "1.0",
        "dataset": "NASA POWER daily corrected precipitation snapshot",
        "parameter": "PRECTOTCORR",
        "units": "mm/day",
        "site_range": [1, 60],
        "date_range": [frame["Date"].min(), frame["Date"].max()],
        "rows": len(frame),
        "source": {
            "path": args.source.absolute().relative_to(root.absolute()).as_posix(),
            "sha256": sha256(args.source),
            "original_request_metadata_status": "not_preserved_with_source_csv",
        },
        "output": {
            "path": args.output.absolute().relative_to(root.absolute()).as_posix(),
            "sha256": sha256(args.output),
        },
        "software": {"python": platform.python_version(), "pandas": pd.__version__},
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
