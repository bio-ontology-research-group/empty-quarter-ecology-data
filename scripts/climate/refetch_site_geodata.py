#!/usr/bin/env python3
"""Re-derive per-campaign geodata rows for ledger-corrected site coordinates.

``metadata/geodata/trip<N>_geodata.tsv`` stores, per campaign and site, the
field-sheet coordinates and the Open-Meteo archive summaries over the twelve
months centred on the visit (``AnnualMeanTemp``, ``AnnualTotalPrecip``,
``AnnualTotalRain``).  When the environmental correction ledger moves a
coordinate cell, the affected geodata rows must be re-derived at the corrected
point with the same request shape as the original acquisition
(``src/utils/extract_geodata.py`` in the working repository: daily
``temperature_2m_mean``, ``precipitation_sum`` and ``rain_sum`` between
``StartDate`` and ``EndDate``, mean and sums over the window).

The script fails closed: a geodata row is only rewritten when its current
coordinates equal the ledger's original value, and every ledger coordinate
correction for a numbered site must find its geodata row.  Raw API responses,
request parameters, retrieval time and output checksums are written to the
evidence file so the re-derivation is auditable.
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

import requests

ENDPOINT = "https://archive-api.open-meteo.com/v1/archive"
DAILY = ("temperature_2m_mean", "precipitation_sum", "rain_sum")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_coordinates(text: str) -> tuple[float, float]:
    match = re.match(
        r"\s*([-+]?\d+\.\d+)\s*°?\s*N?\s*,\s*([-+]?\d+\.\d+)\s*°?\s*E?\s*$", text
    )
    if not match:
        raise ValueError(f"cannot parse coordinates {text!r}")
    return float(match.group(1)), float(match.group(2))


def format_number(value: float) -> str:
    text = f"{value:.6f}".rstrip("0").rstrip(".")
    return text if "." in text else f"{text}.0"


def read_tsv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        return list(reader.fieldnames or []), list(reader)


def write_tsv(path: Path, header: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=header, delimiter="\t", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)


def fetch(session: requests.Session, latitude: float, longitude: float,
          start: str, end: str, retries: int, timeout: int) -> dict:
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "start_date": start,
        "end_date": end,
        "daily": ",".join(DAILY),
    }
    last_error: Exception | None = None
    for _ in range(retries):
        try:
            response = session.get(ENDPOINT, params=params, timeout=timeout)
            response.raise_for_status()
            payload = response.json()
            break
        except (requests.RequestException, ValueError) as error:
            last_error = error
    else:
        raise SystemExit(f"Open-Meteo request failed: {last_error}")
    daily = payload["daily"]
    expected = (end and start) and len(daily["time"])
    for name in DAILY:
        if len(daily[name]) != expected or any(v is None for v in daily[name]):
            raise SystemExit(f"incomplete {name} series for {params}")
    temperature = daily["temperature_2m_mean"]
    summary = {
        "days": len(daily["time"]),
        "AnnualMeanTemp": sum(temperature) / len(temperature),
        "AnnualTotalPrecip": sum(daily["precipitation_sum"]),
        "AnnualTotalRain": sum(daily["rain_sum"]),
    }
    return {"request": params, "response": payload, "summary": summary}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path("."))
    parser.add_argument(
        "--evidence",
        type=Path,
        default=Path("evidence/environmental/site52_coordinate_correction.json"),
    )
    parser.add_argument("--retries", type=int, default=5)
    parser.add_argument("--timeout", type=int, default=90)
    args = parser.parse_args()
    root = args.project_root.resolve()
    ledger = root / "metadata/samples/environmental_measurement_corrections.tsv"
    geodata_dir = root / "metadata/geodata"

    _header, ledger_rows = read_tsv(ledger)
    corrections = [
        row for row in ledger_rows
        if row["original_field"] == "coordinates"
        and row["corrected_field"] == "coordinates"
        and row["status"].startswith("confirmed_")
    ]
    if not corrections:
        raise SystemExit("no confirmed coordinate corrections in the ledger")

    session = requests.Session()
    retrieved_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    records: list[dict] = []
    touched: dict[Path, tuple[list[str], list[dict[str, str]]]] = {}
    for correction in corrections:
        if not re.fullmatch(r"\d+", correction["site"]):
            records.append({
                "ledger_key": f"{correction['source_file']}|{correction['source_row']}|coordinates",
                "site": correction["site"],
                "geodata": "no per-campaign geodata row exists for this label",
            })
            continue
        trip = correction["source_file"].split("-")[0]
        path = geodata_dir / f"{trip}_geodata.tsv"
        header, rows = touched.get(path) or read_tsv(path)
        touched[path] = (header, rows)
        matches = [row for row in rows if row["Site"] == correction["site"]]
        if len(matches) != 1:
            raise SystemExit(f"{path}: expected one row for site {correction['site']}")
        row = matches[0]
        original = parse_coordinates(correction["original_value"])
        corrected = parse_coordinates(correction["corrected_value"])
        current = (float(row["Latitude"]), float(row["Longitude"]))
        if current == corrected:
            records.append({
                "ledger_key": f"{correction['source_file']}|{correction['source_row']}|coordinates",
                "site": correction["site"],
                "geodata": str(path.relative_to(root)),
                "status": "already corrected; not refetched",
            })
            continue
        if any(abs(a - b) > 1e-9 for a, b in zip(current, original)):
            raise SystemExit(
                f"{path}: site {correction['site']} coordinates {current} do not "
                f"match the ledger original {original}"
            )
        before = dict(row)
        result = fetch(session, corrected[0], corrected[1],
                       row["StartDate"], row["EndDate"], args.retries, args.timeout)
        row["Latitude"] = format_number(corrected[0])
        row["Longitude"] = format_number(corrected[1])
        for key in ("AnnualMeanTemp", "AnnualTotalPrecip", "AnnualTotalRain"):
            if key in row:
                row[key] = format_number(result["summary"][key])
        records.append({
            "ledger_key": f"{correction['source_file']}|{correction['source_row']}|coordinates",
            "site": correction["site"],
            "geodata": str(path.relative_to(root)),
            "before": before,
            "after": dict(row),
            "endpoint": ENDPOINT,
            "request": result["request"],
            "api_metadata": {
                key: result["response"].get(key)
                for key in ("latitude", "longitude", "elevation", "timezone",
                            "utc_offset_seconds", "generationtime_ms")
            },
            "daily": result["response"]["daily"],
            "summary": result["summary"],
        })

    for path, (header, rows) in touched.items():
        write_tsv(path, header, rows)

    evidence = {
        "schema_version": "1.0",
        "status": "passed",
        "purpose": (
            "Re-derivation of per-campaign geodata rows whose coordinates were "
            "moved by confirmed entries of the environmental correction ledger."
        ),
        "method": (
            "Same request shape as the original acquisition: Open-Meteo archive "
            "daily temperature_2m_mean, precipitation_sum and rain_sum between "
            "StartDate and EndDate; AnnualMeanTemp is the window mean and the "
            "totals are window sums. Values from the earlier frozen retrieval "
            "are not byte-comparable with a later retrieval because the archive "
            "model is revised over time; the retrieval time is recorded here."
        ),
        "retrieved_at_utc": retrieved_at,
        "ledger": {
            "path": str(ledger.relative_to(root)),
            "sha256": sha256(ledger),
        },
        "records": records,
        "outputs": {
            str(path.relative_to(root)): {"bytes": path.stat().st_size, "sha256": sha256(path)}
            for path in sorted(touched)
        },
        "known_downstream_consumers_not_regenerated": [
            "metadata/climate/daily_weather.tsv (site 52 series was retrieved at the mean of the four campaign coordinates)",
            "metadata/climate/rain_event_product_exposures.tsv",
            "metadata/functional/picrust2/merged/sample_metadata.tsv",
            "evidence/ecology-canonical/* analysis cohorts and site_coordinates.tsv",
        ],
    }
    evidence_path = (root / args.evidence)
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    for record in records:
        print(record["ledger_key"], record.get("status") or record.get("geodata"),
              record.get("summary", ""))
    print(f"wrote {evidence_path.relative_to(root)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
