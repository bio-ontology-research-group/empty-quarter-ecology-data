#!/usr/bin/env python3
"""Audit non-standard species fields in the combined taxonomy table.

The Trips 1--5 taxonomy table contains legacy seven-field lineages and
Trip-5 records encoded as seven standard ranks, an additional species-like
field, and a numeric confidence.  This script reports every record for which
the additional field is populated but is not an exact duplicate of the
standard species field.  It also joins those records to the combined feature
table so a normalization decision can be based on records that actually
carry reads.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path


NUMERIC = re.compile(r"(?:0(?:\.\d+)?|1(?:\.0+)?)\Z")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass
class SourceAnomaly:
    feature_id: str
    raw_taxon: str
    standard_species: str
    extra_species: str
    confidence: str
    anomaly: str
    feature_table_present: bool = False
    total_count: float = 0.0
    nonzero_profile_count: int = 0


def read_source_anomalies(path: Path) -> dict[str, SourceAnomaly]:
    anomalies: dict[str, SourceAnomaly] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        required = {"Feature ID", "Taxon"}
        if not required.issubset(reader.fieldnames or ()):
            raise ValueError(
                f"{path}: expected at least {sorted(required)}, "
                f"found {reader.fieldnames}"
            )
        for row in reader:
            raw_taxon = row["Taxon"]
            parts = [part.strip() for part in raw_taxon.split(";")]
            if (
                len(parts) != 9
                or not NUMERIC.fullmatch(parts[8])
                or not parts[7]
                or parts[7] == parts[6]
            ):
                continue
            feature_id = row["Feature ID"].strip()
            if feature_id in anomalies:
                raise ValueError(f"{path}: duplicate feature ID {feature_id!r}")
            anomalies[feature_id] = SourceAnomaly(
                feature_id=feature_id,
                raw_taxon=raw_taxon,
                standard_species=parts[6],
                extra_species=parts[7],
                confidence=parts[8],
                anomaly="conflict" if parts[6] else "extra_only",
            )
    return anomalies


def join_feature_counts(
    path: Path, anomalies: dict[str, SourceAnomaly]
) -> tuple[int, int]:
    with path.open(encoding="utf-8") as handle:
        first = handle.readline()
        if first.startswith("# Constructed"):
            header = handle.readline()
        else:
            header = first
        columns = header.rstrip("\r\n").split("\t")
        if not columns or columns[0] != "#OTU ID":
            raise ValueError(f"{path}: expected #OTU ID as first column")
        profile_count = len(columns) - 1
        matched = 0
        for line in handle:
            fields = line.rstrip("\r\n").split("\t")
            if not fields:
                continue
            anomaly = anomalies.get(fields[0])
            if anomaly is None:
                continue
            if len(fields) != len(columns):
                raise ValueError(
                    f"{path}: feature {fields[0]!r} has {len(fields)} fields, "
                    f"expected {len(columns)}"
                )
            values = [float(value) if value else 0.0 for value in fields[1:]]
            anomaly.feature_table_present = True
            anomaly.total_count = sum(values)
            anomaly.nonzero_profile_count = sum(value > 0 for value in values)
            matched += 1
    return profile_count, matched


def write_tsv(path: Path, anomalies: dict[str, SourceAnomaly]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = (
        "feature_id",
        "raw_taxon",
        "first7_species",
        "extra_species",
        "confidence",
        "anomaly",
        "feature_table_present",
        "total_count",
        "nonzero_profile_count",
    )
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, delimiter="\t")
        writer.writeheader()
        for feature_id in sorted(anomalies):
            item = anomalies[feature_id]
            writer.writerow(
                {
                    "feature_id": item.feature_id,
                    "raw_taxon": item.raw_taxon,
                    "first7_species": item.standard_species,
                    "extra_species": item.extra_species,
                    "confidence": item.confidence,
                    "anomaly": item.anomaly,
                    "feature_table_present": str(
                        item.feature_table_present
                    ).lower(),
                    "total_count": format(item.total_count, ".15g"),
                    "nonzero_profile_count": item.nonzero_profile_count,
                }
            )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source-taxonomy",
        type=Path,
        default=Path(
            "data/processed/taxonomy/taxon-tables/"
            "taxonomy-trips1-5.tsv"
        ),
    )
    parser.add_argument(
        "--feature-table",
        type=Path,
        default=Path(
            "data/processed/taxonomy/taxon-tables/"
            "feature-table-trips1-5.tsv"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "data/release/taxonomy_mapping_audit/"
            "taxonomy_source_supplementary_species.tsv"
        ),
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path(
            "data/release/taxonomy_mapping_audit/"
            "taxonomy_source_schema_audit.json"
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    anomalies = read_source_anomalies(args.source_taxonomy)
    profile_count, matched = join_feature_counts(
        args.feature_table, anomalies
    )
    write_tsv(args.output, anomalies)
    by_type = {
        kind: sum(item.anomaly == kind for item in anomalies.values())
        for kind in ("extra_only", "conflict")
    }
    report = {
        "status": (
            "passed" if matched == len(anomalies) else "failed"
        ),
        "inputs": {
            "source_taxonomy": {
                "path": str(args.source_taxonomy),
                "sha256": sha256(args.source_taxonomy),
                "bytes": args.source_taxonomy.stat().st_size,
            },
            "feature_table": {
                "path": str(args.feature_table),
                "sha256": sha256(args.feature_table),
                "bytes": args.feature_table.stat().st_size,
            },
        },
        "counts": {
            "anomalous_records": len(anomalies),
            "extra_only": by_type["extra_only"],
            "conflict": by_type["conflict"],
            "feature_table_matches": matched,
            "feature_table_missing": len(anomalies) - matched,
            "profiles": profile_count,
            "records_with_nonzero_counts": sum(
                item.nonzero_profile_count > 0 for item in anomalies.values()
            ),
            "total_reads": sum(
                item.total_count for item in anomalies.values()
            ),
        },
        "output": str(args.output),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
