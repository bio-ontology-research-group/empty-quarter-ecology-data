#!/usr/bin/env python3
"""Search every XRF source artifact for a declared concentration unit.

The released XRF module asserts ``sio:000221 uo:0000187`` (percent) on every
analyte value.  The descriptor simultaneously states that concentration units
are not machine-readable.  Both cannot be right, so this audit establishes
which one the sources support: it scans the field log, the processed
laboratory table and every raw instrument export for a unit declaration
attached to the concentration column, and reports what it finds.

It does not guess.  A unit token found in a *different* column (the instrument
writes lower limits of detection as ``30.8 PPM``) is reported as evidence about
that column only, and is explicitly not treated as a concentration unit.

Exit status is 0 when the scan completes; the ``documented_concentration_unit``
field of the report carries the verdict.  The companion regression test asserts
that the manuscript does not claim a documented unit while this field is null.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from pathlib import Path

UNIT_TOKEN = re.compile(
    r"\b(?:wt\s*%|weight\s*percent|percent|%|ppm|ppb|mg\s*/\s*kg|g\s*/\s*kg|µg/g|ug/g)\b",
    re.IGNORECASE,
)
CONCENTRATION_HEADER = re.compile(r"conc(?:entration)?", re.IGNORECASE)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def scan_tabular(path: Path) -> dict:
    """Report unit evidence in the header and in concentration-column cells."""
    try:
        with path.open(newline="", encoding="utf-8", errors="replace") as handle:
            rows = list(csv.reader(handle, delimiter="\t"))
    except OSError as error:
        return {"path": str(path), "error": str(error)}
    if not rows:
        return {"path": str(path), "error": "empty file"}

    header = rows[0]
    concentration_columns = [
        index for index, name in enumerate(header) if CONCENTRATION_HEADER.search(name or "")
    ]
    header_units = sorted({match.group(0) for name in header for match in UNIT_TOKEN.finditer(name or "")})

    cell_units: dict[str, list[str]] = {}
    for row in rows[1:]:
        for index, cell in enumerate(row):
            for match in UNIT_TOKEN.finditer(cell or ""):
                column = header[index] if index < len(header) else f"column_{index}"
                cell_units.setdefault(column, [])
                if match.group(0) not in cell_units[column]:
                    cell_units[column].append(match.group(0))
    return {
        "path": str(path),
        "sha256": sha256(path),
        "header_columns": len(header),
        "concentration_columns": [header[i] for i in concentration_columns],
        "unit_tokens_in_header": header_units,
        "unit_tokens_in_cells_by_column": {k: sorted(v) for k, v in sorted(cell_units.items())},
    }


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=root)
    parser.add_argument(
        "--output", type=Path, default=root / "analysis/xrf_audit/xrf_unit_evidence.json"
    )
    args = parser.parse_args()
    project_root = args.project_root.resolve()

    targets = [
        project_root / "data/processed/geochemistry/xrf_lab_table_filtered.tsv",
        project_root / "data/metadata/xrf/xrf-measurements.tsv",
        project_root / "data/metadata/xrf/xrf_field_table.tsv",
    ]
    targets = [path for path in targets if path.is_file()]
    exports = sorted((project_root / "data/metadata/xrf/trip-5-lab").glob("*.tsv"))
    if not targets and not exports:
        print("FAIL: no XRF source artifacts found", file=sys.stderr)
        return 1

    scans = [scan_tabular(path) for path in targets]
    export_scans = [scan_tabular(path) for path in exports]

    concentration_header_units = sorted(
        {
            token
            for scan in scans + export_scans
            for column in scan.get("concentration_columns", [])
            for token in UNIT_TOKEN.findall(column)
        }
    )
    concentration_cell_units = sorted(
        {
            token
            for scan in scans + export_scans
            for column, tokens in scan.get("unit_tokens_in_cells_by_column", {}).items()
            if CONCENTRATION_HEADER.search(column)
            for token in tokens
        }
    )
    other_column_units = sorted(
        {
            f"{column}={token}"
            for scan in scans + export_scans
            for column, tokens in scan.get("unit_tokens_in_cells_by_column", {}).items()
            if not CONCENTRATION_HEADER.search(column)
            for token in tokens
        }
    )

    documented = None
    if concentration_header_units or concentration_cell_units:
        documented = sorted(set(concentration_header_units) | set(concentration_cell_units))

    report = {
        "processed_tables_scanned": len(scans),
        "instrument_exports_scanned": len(export_scans),
        "concentration_column_names": sorted(
            {
                column
                for scan in scans + export_scans
                for column in scan.get("concentration_columns", [])
            }
        ),
        "documented_concentration_unit": documented,
        "unit_tokens_in_other_columns": other_column_units[:40],
        "graph_assertion": "sio:000221 uo:0000187 (percent) on every analyte value",
        "verdict": (
            "No source artifact declares a unit for the concentration column. The "
            "percent assertion in the released graph is a generator default and is "
            "not supported by the acquisition metadata."
            if documented is None
            else "A concentration unit is declared in the sources; see documented_concentration_unit."
        ),
        "processed_tables": scans,
        "instrument_exports": export_scans[:5],
        "instrument_exports_note": (
            f"{len(export_scans)} exports scanned; the first five are listed in full."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"documented_concentration_unit: {documented}")
    print(f"unit tokens seen in other columns: {other_column_units[:10]}")
    print(f"PASS: unit evidence written to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
