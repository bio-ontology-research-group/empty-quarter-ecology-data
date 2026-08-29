#!/usr/bin/env python3
"""Audit the two XRF workflows described by the Data Descriptor.

The script is intentionally read-only.  It counts rows in the authoritative
processed tables and, when present, counts XRF process/value individuals in the
development and staged OWL files.  It does not endorse the current laboratory
aggregation rule; that requires the separate run/mode audit described in the
manuscript.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import xml.etree.ElementTree as ET

RDF_TYPE = "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}type"
RDF_RESOURCE = "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}resource"
XRF_PROCESS = "https://rubalkhali.science/kb/RAK_0000025"
SIO_VALUE_TO_QUALITY = (
    "{http://semanticscience.org/resource/}SIO_000215"
)


def tsv_inventory(path: Path) -> dict[str, object]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.reader(handle, delimiter="\t")
        header = next(reader)
        rows = sum(1 for _ in reader)
    return {"path": str(path), "rows": rows, "columns": len(header)}


def owl_inventory(path: Path) -> dict[str, object]:
    processes = 0
    values = 0
    for _event, element in ET.iterparse(path, events=("end",)):
        if element.tag == RDF_TYPE and element.attrib.get(RDF_RESOURCE) == XRF_PROCESS:
            processes += 1
        elif element.tag == SIO_VALUE_TO_QUALITY:
            values += 1
        element.clear()
    return {
        "path": str(path),
        "xrf_processes": processes,
        "measurement_values": values,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--data-root",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "data",
        help="Root data directory (default: the parent project's data/)",
    )
    parser.add_argument(
        "--paper-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Data-paper directory",
    )
    args = parser.parse_args()

    processed = args.data_root / "processed" / "geochemistry"
    tables = {
        "field_trip5": processed / "xrf_field_table.tsv",
        "lab_trip5_processed_records": (
            processed / "xrf_lab_table_filtered.tsv"
        ),
        "lab_trips1_4_processed_records": (
            processed / "xrf_lab_table_trips1-4.tsv"
        ),
        "lab_trip5_legacy_retired_subset": (
            processed / "xrf_lab_combined.tsv"
        ),
    }
    missing = [str(path) for path in tables.values() if not path.exists()]
    if missing:
        parser.error("missing required input(s): " + ", ".join(missing))

    report: dict[str, object] = {
        "tables": {name: tsv_inventory(path) for name, path in tables.items()}
    }
    rows = {name: entry["rows"] for name, entry in report["tables"].items()}
    report["derived_counts"] = {
        "field_sessions": rows["field_trip5"],
        "canonical_lab_analytical_records": (
            rows["lab_trips1_4_processed_records"]
            + rows["lab_trip5_processed_records"]
        ),
        "legacy_retired_lab_analytical_records": (
            rows["lab_trips1_4_processed_records"]
            + rows["lab_trip5_legacy_retired_subset"]
        ),
        "legacy_retired_trip5_subset_records": (
            rows["lab_trip5_legacy_retired_subset"]
        ),
        "records_restored_in_canonical_release": (
            rows["lab_trip5_processed_records"]
            - rows["lab_trip5_legacy_retired_subset"]
        ),
    }

    owl_paths = {
        "development_kg": (
            args.data_root
            / "processed"
            / "semantics"
            / "ontology"
            / "rubalkhali_xrf.owl"
        ),
        "staged_archive": (
            args.paper_root / "zenodo" / "ontology" / "rubalkhali_xrf.owl"
        ),
    }
    report["owl"] = {
        name: owl_inventory(path)
        for name, path in owl_paths.items()
        if path.exists()
    }

    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
