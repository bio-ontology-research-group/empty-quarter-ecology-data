#!/usr/bin/env python3
"""Package the Open-Meteo daily input with the Site 52 series at the corrected position.

The pinned data repository (commit 5a17782) corrected the Site 52 coordinates
of the Trip 1 and Trip 3 field sheets (a3f1c21) but did not refetch the daily
Open-Meteo series. Its own correction record
(evidence/environmental/site52_coordinate_correction.json,
``known_downstream_consumers_not_regenerated``) states that the Site 52 series
of metadata/climate/daily_weather.tsv "was retrieved at the mean of the four
campaign coordinates". metadata/climate/daily_weather_canonical.tsv inherits
that series.

This script

1. (``--fetch``) requests the archive API with the request shape of the
   original acquisition (data repository scripts/utils/fetch_daily_weather.py:
   temperature_2m_mean, rain_sum, precipitation_sum, 2022-01-01..2026-02-01,
   timezone auto) at the corrected position and, as a provenance check, at the
   averaged position the original series was fetched at; raw responses,
   request URLs and retrieval times are stored next to this script;
2. verifies that the averaged-position response reproduces the pinned Site 52
   precipitation series exactly;
3. writes ``daily_weather_canonical_site52_corrected.tsv``: the pinned
   canonical table with the three Site 52 value columns replaced by the
   corrected-position response, every other byte-level row unchanged;
4. writes ``manifest.json`` with input/output SHA-256 and the comparison.

The rainfall analyses consume the packaged table as their Open-Meteo input.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENDPOINT = "https://archive-api.open-meteo.com/v1/archive"
DAILY = "temperature_2m_mean,rain_sum,precipitation_sum"
START, END = "2022-01-01", "2026-02-01"
CORRECTED = (20.82784, 53.57835)
# Mean of the Site 52 rows of the four campaign geodata files before a3f1c21:
# Trips 1 and 3 (20.851514166666668, 53.75788444444444; the Site 53 position)
# and Trips 4 and 5 (20.82784, 53.57835).
AVERAGED = (
    (2 * 20.851514166666668 + 2 * 20.82784) / 4,
    (2 * 53.75788444444444 + 2 * 53.57835) / 4,
)
PINNED_CANONICAL_SHA256 = (
    "6cb570e7a8a85a9508fdc910ae0a11bf7db614ef05e0d22fd6fd6a599966581a"
)
OUTPUT = "daily_weather_canonical_site52_corrected.tsv"
COLUMNS = {
    "temperature_2m_mean": "Mean_Temp_C",
    "rain_sum": "Rain_mm",
    "precipitation_sum": "Precip_mm",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def request_url(lat: float, lon: float) -> str:
    query = urllib.parse.urlencode(
        {
            "latitude": repr(lat),
            "longitude": repr(lon),
            "start_date": START,
            "end_date": END,
            "daily": DAILY,
            "timezone": "auto",
        }
    )
    return f"{ENDPOINT}?{query}"


def fetch(name: str, lat: float, lon: float) -> None:
    url = request_url(lat, lon)
    retrieved = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with urllib.request.urlopen(url, timeout=120) as response:
        body = response.read()
    (HERE / f"open_meteo_site52_{name}_response.json").write_bytes(body)
    (HERE / f"open_meteo_site52_{name}_request.json").write_text(
        json.dumps(
            {
                "url": url,
                "endpoint": ENDPOINT,
                "latitude": lat,
                "longitude": lon,
                "start_date": START,
                "end_date": END,
                "daily": DAILY.split(","),
                "timezone": "auto",
                "retrieved_at_utc": retrieved,
                "response_sha256": hashlib.sha256(body).hexdigest(),
            },
            indent=2,
        )
        + "\n"
    )


def load_response(name: str) -> dict[str, tuple[str, str, str]]:
    daily = json.loads(
        (HERE / f"open_meteo_site52_{name}_response.json").read_text()
    )["daily"]
    return {
        day: tuple(
            "" if daily[key][i] is None else str(daily[key][i])
            for key in ("temperature_2m_mean", "rain_sum", "precipitation_sum")
        )
        for i, day in enumerate(daily["time"])
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--canonical", type=Path, required=True,
                        help="pinned metadata/climate/daily_weather_canonical.tsv")
    parser.add_argument("--fetch", action="store_true",
                        help="query the archive API (otherwise reuse stored responses)")
    args = parser.parse_args()

    source_sha = sha256(args.canonical)
    if source_sha != PINNED_CANONICAL_SHA256:
        sys.exit(f"canonical input {source_sha} is not the pinned file")
    if args.fetch:
        fetch("corrected", *CORRECTED)
        fetch("averaged", *AVERAGED)
    corrected = load_response("corrected")
    averaged = load_response("averaged")

    lines = args.canonical.read_text(encoding="utf-8").splitlines(keepends=True)
    header = lines[0].rstrip("\n").split("\t")
    if header != ["Site", "Date", "Mean_Temp_C", "Rain_mm", "Precip_mm"]:
        sys.exit(f"unexpected header {header}")
    out, replaced, precip_changed, averaged_mismatch = [lines[0]], 0, [], []
    for line in lines[1:]:
        fields = line.rstrip("\n").split("\t")
        if fields[0] == "52":
            day = fields[1]
            if float(averaged[day][2]) != float(fields[4]):
                averaged_mismatch.append(day)
            new = corrected[day]
            if float(new[2]) != float(fields[4]):
                precip_changed.append(
                    {"date": day, "pinned_mm": float(fields[4]),
                     "corrected_mm": float(new[2])}
                )
            fields[2:5] = new
            replaced += 1
            line = "\t".join(fields) + "\n"
        out.append(line)
    if replaced != len(corrected):
        sys.exit(f"replaced {replaced} rows, response has {len(corrected)} days")
    if averaged_mismatch:
        sys.exit(f"averaged-position response does not reproduce the pinned "
                 f"series on {len(averaged_mismatch)} days")
    (HERE / OUTPUT).write_text("".join(out), encoding="utf-8")

    requests = {
        name: json.loads((HERE / f"open_meteo_site52_{name}_request.json").read_text())
        for name in ("corrected", "averaged")
    }
    responses = {
        name: {k: v for k, v in json.loads(
            (HERE / f"open_meteo_site52_{name}_response.json").read_text()
        ).items() if k not in ("daily", "daily_units")}
        for name in ("corrected", "averaged")
    }
    manifest = {
        "purpose": "Open-Meteo daily input with the Site 52 series at the corrected position",
        "data_repository_commit": "5a17782c1ec3c7d511bf5f8ae934086b950f6ae1",
        "source": {"path": "metadata/climate/daily_weather_canonical.tsv",
                   "sha256": source_sha},
        "site52_corrected_position": CORRECTED,
        "site52_original_fetch_position": AVERAGED,
        "requests": requests,
        "response_grid_cells": responses,
        "verification": {
            "averaged_position_reproduces_pinned_precipitation": True,
            "rows_replaced": replaced,
            "other_rows_unchanged": True,
            "precipitation_days_changed": len(precip_changed),
            "precipitation_total_pinned_mm": round(
                sum(float(averaged[d][2]) for d in averaged), 2),
            "precipitation_total_corrected_mm": round(
                sum(float(corrected[d][2]) for d in corrected), 2),
        },
        "precipitation_changes": precip_changed,
        "output": {"path": OUTPUT, "sha256": sha256(HERE / OUTPUT)},
    }
    (HERE / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest["verification"], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
