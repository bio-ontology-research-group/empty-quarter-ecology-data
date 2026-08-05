#!/usr/bin/env python3
"""Retrieve per-site monthly climate summaries from the Open-Meteo archive.

The retrieval is the upstream boundary of the climate layer, so it has to be
reproducible rather than convenient.  Three properties are enforced here:

* the date window is an explicit argument with a frozen default, never
  ``today()``, so a later run covers the same period;
* every raw API response is written to a snapshot directory, so the derived
  table can be rebuilt without contacting the service again;
* a provenance record captures the endpoint, the exact request parameters, the
  reported API metadata, the retrieval timestamp, and checksums of the inputs,
  the snapshots and the output.

The script fails closed: if any site cannot be retrieved after the configured
retries, nothing is written and the exit status is non-zero, because a
partially fetched table silently changes every downstream count.

``--from-snapshots`` rebuilds the table from a previous snapshot directory and
performs no network access at all.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
import time
from pathlib import Path

import pandas as pd

ENDPOINT = "https://archive-api.open-meteo.com/v1/archive"
DAILY_VARIABLES = [
    "temperature_2m_mean",
    "rain_sum",
    "precipitation_sum",
    "relative_humidity_2m_mean",
]
# Frozen window of the archived release. Change only with a new provenance record.
DEFAULT_START_DATE = "2022-01-01"
DEFAULT_END_DATE = "2026-01-20"
OUTPUT_HEADER = (
    "Site\tYear\tMonth\tAvg_Temp_C\tAvg_Total_Rain_mm\t"
    "Avg_Total_Precip_mm\tAvg_Humidity_Percent\n"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def request_params(lat: float, lon: float, start: str, end: str) -> dict:
    return {
        "latitude": lat,
        "longitude": lon,
        "start_date": start,
        "end_date": end,
        "daily": DAILY_VARIABLES,
        "timezone": "auto",
    }


def fetch(session, params: dict, retries: int, delay: int) -> dict | None:
    import requests  # imported lazily so --from-snapshots needs no network stack

    for attempt in range(retries):
        try:
            response = session.get(ENDPOINT, params=params, timeout=30)
            if response.status_code == 200:
                return response.json()
            if response.status_code == 429:
                wait = delay * (2**attempt)
                print(f"  rate limited (429); retrying in {wait}s")
                time.sleep(wait)
            else:
                print(f"  error {response.status_code}: {response.text[:200]}")
                time.sleep(delay)
        except requests.exceptions.RequestException as error:
            print(f"  request failed: {error}")
            time.sleep(delay)
    return None


def monthly_rows(site_id: str, payload: dict) -> list[str]:
    frame = pd.DataFrame(payload["daily"])
    frame["time"] = pd.to_datetime(frame["time"])
    frame["year"] = frame["time"].dt.year
    frame["month"] = frame["time"].dt.month
    stats = (
        frame.groupby(["year", "month"])
        .agg(
            {
                "temperature_2m_mean": "mean",
                "rain_sum": "sum",
                "precipitation_sum": "sum",
                "relative_humidity_2m_mean": "mean",
            }
        )
        .reset_index()
    )
    return [
        f"{site_id}\t{int(row['year'])}\t{int(row['month'])}\t"
        f"{row['temperature_2m_mean']:.2f}\t{row['rain_sum']:.2f}\t"
        f"{row['precipitation_sum']:.2f}\t{row['relative_humidity_2m_mean']:.2f}\n"
        for _, row in stats.iterrows()
    ]


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--sites", type=Path, default=root / "data/metadata/geodata/site_altitudes.tsv"
    )
    parser.add_argument(
        "--output", type=Path, default=root / "data/processed/climate/monthly_weather_averages.tsv"
    )
    parser.add_argument(
        "--snapshot-dir",
        type=Path,
        default=root / "data/processed/climate/openmeteo_snapshots/monthly",
    )
    parser.add_argument(
        "--provenance",
        type=Path,
        default=root / "data/processed/climate/climate_acquisition_provenance.json",
    )
    parser.add_argument("--start-date", default=DEFAULT_START_DATE)
    parser.add_argument("--end-date", default=DEFAULT_END_DATE)
    parser.add_argument("--retries", type=int, default=5)
    parser.add_argument("--delay", type=int, default=5)
    parser.add_argument("--from-snapshots", action="store_true")
    args = parser.parse_args()

    if not args.sites.is_file():
        print(f"FAIL: site table is absent: {args.sites}", file=sys.stderr)
        return 1
    sites = pd.read_csv(args.sites, sep="\t")
    for column in ("Site", "Latitude", "Longitude"):
        if column not in sites.columns:
            print(f"FAIL: site table lacks column {column}", file=sys.stderr)
            return 1

    args.snapshot_dir.mkdir(parents=True, exist_ok=True)
    session = None
    if not args.from_snapshots:
        import requests

        session = requests.Session()

    started = dt.datetime.now(dt.timezone.utc).isoformat()
    lines: list[str] = []
    snapshots: dict[str, str] = {}
    api_metadata: dict[str, dict] = {}
    failures: list[str] = []

    for _, row in sites.iterrows():
        site_id = str(row["Site"])
        safe = site_id.replace("/", "_").replace(" ", "_")
        snapshot = args.snapshot_dir / f"{safe}.json"
        params = request_params(row["Latitude"], row["Longitude"], args.start_date, args.end_date)

        if args.from_snapshots:
            if not snapshot.is_file():
                failures.append(f"{site_id}: no snapshot at {snapshot}")
                continue
            payload = json.loads(snapshot.read_text(encoding="utf-8"))
        else:
            payload = fetch(session, params, args.retries, args.delay)
            if payload is None or "daily" not in payload:
                failures.append(f"{site_id}: retrieval failed")
                continue
            snapshot.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
            time.sleep(1.5)

        snapshots[site_id] = sha256(snapshot)
        api_metadata[site_id] = {
            key: payload.get(key)
            for key in ("latitude", "longitude", "elevation", "timezone", "utc_offset_seconds")
        }
        lines.extend(monthly_rows(site_id, payload))
        print(f"  {site_id}: {len(payload['daily']['time'])} daily records")

    if failures:
        print(f"FAIL: {len(failures)} site(s) unresolved; no output written", file=sys.stderr)
        for failure in failures:
            print(f"  {failure}", file=sys.stderr)
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        handle.write(OUTPUT_HEADER)
        handle.writelines(lines)

    provenance = {
        "endpoint": ENDPOINT,
        "daily_variables": DAILY_VARIABLES,
        "timezone_parameter": "auto",
        "start_date": args.start_date,
        "end_date": args.end_date,
        "retrieval_started_utc": started,
        "retrieval_finished_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "network_access": not args.from_snapshots,
        "sites_requested": int(len(sites)),
        "output": {
            "path": str(args.output),
            "bytes": args.output.stat().st_size,
            "sha256": sha256(args.output),
            "data_rows": len(lines),
        },
        "site_table": {"path": str(args.sites), "sha256": sha256(args.sites)},
        "script": {"path": str(Path(__file__).resolve()), "sha256": sha256(Path(__file__).resolve())},
        "snapshot_dir": str(args.snapshot_dir),
        "snapshot_sha256": snapshots,
        "response_metadata": api_metadata,
        "limitation": (
            "Open-Meteo does not report a reanalysis model version in the archive "
            "response; the pinned evidence is therefore the endpoint, the request "
            "parameters, the retrieval timestamp and the stored raw responses."
        ),
    }
    args.provenance.parent.mkdir(parents=True, exist_ok=True)
    args.provenance.write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"PASS: {len(lines)} monthly rows for {len(sites)} sites -> {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
