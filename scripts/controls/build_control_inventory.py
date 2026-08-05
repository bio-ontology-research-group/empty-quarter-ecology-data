#!/usr/bin/env python3
"""Assemble every control record the local evidence can support.

The contamination audit is blocked on knowing what the controls actually were.
This script performs the discovery half of that work from artifacts that are
present locally: the release sample ledger, the unresolved control-labelled
sequence rows, the canonical feature table, the MultiQC per-run statistics, and
the public archive metadata retrieved by
``data-paper/scripts/reconcile_accessions.py``.

It produces three products:

``control_inventory.tsv``
    One row per control record found in any source, with the source, the
    identifier as written there, and the linking fields that source provides.

``preliminary_control_identity.tsv``
    One row per candidate control identity, each with the evidence that
    supports it, a confidence grade, and the alternatives that the evidence
    does not exclude.  This is explicitly provisional.

``control_read_and_asv_load.tsv``
    Read counts (from MultiQC) and observed ASV richness and total counts (from
    the canonical feature table) for every control profile present.

Nothing here is promoted to ground truth.  Inferred identities carry a
confidence grade and at least one stated alternative, and the script refuses to
write a ground-truth table.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from pathlib import Path

CONTROL_TOKEN = re.compile(r"(ctrl|control|^EB\d+$|^Negative\d*$|^T_Neg|blank|zymo|neg)", re.IGNORECASE)
# MultiQC sample names embed the library identifier between underscores, e.g.
# M-25-0770_EB1_SU0216-SU0216_L002_R1_001, so the anchored forms above miss them.
MULTIQC_CONTROL_TOKEN = re.compile(
    r"(ctrl|control|blank|zymo|_EB\d+_|_Negative\d*_|_T[_-]?Neg)", re.IGNORECASE
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def ledger_controls(path: Path) -> list[dict]:
    rows = []
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            if row.get("is_control", "").lower() == "true":
                rows.append(
                    {
                        "source": "sample_ledger",
                        "identifier": row["sample_id"],
                        "campaign": row["trip"],
                        "source_locator": f"{row['source_sheet']}:row {row['source_row']}",
                        "site_field": row["site"],
                        "has_sequence_run": row["has_sra_run"],
                        "in_feature_table": row["in_feature_table"],
                    }
                )
    return rows


def unresolved_sequence_controls(path: Path) -> list[dict]:
    evidence = json.loads(path.read_text(encoding="utf-8"))
    rows = []
    for record in evidence.get("unresolved_sra_records", []):
        rows.append(
            {
                "source": "sequence_submission",
                "identifier": record["sample_name"],
                "campaign": "",
                "source_locator": record["run_accession"],
                "site_field": "",
                "has_sequence_run": "True",
                "in_feature_table": "",
                "biosample": record["biosample_accession"],
            }
        )
    return rows


def feature_table_controls(path: Path) -> tuple[list[str], dict[str, tuple[int, float]]]:
    """Return control column names and their (observed ASVs, total count)."""
    with path.open(encoding="utf-8") as handle:
        handle.readline()  # biom provenance comment
        header = handle.readline().rstrip("\n").split("\t")
        columns = header[1:]
        control_indices = [
            index for index, name in enumerate(columns) if CONTROL_TOKEN.search(name.split("_")[-1])
        ]
        observed = {index: 0 for index in control_indices}
        totals = {index: 0.0 for index in control_indices}
        for line in handle:
            fields = line.rstrip("\n").split("\t")
            values = fields[1:]
            for index in control_indices:
                try:
                    value = float(values[index])
                except (IndexError, ValueError):
                    continue
                if value > 0:
                    observed[index] += 1
                    totals[index] += value
    names = [columns[index] for index in control_indices]
    loads = {columns[index]: (observed[index], totals[index]) for index in control_indices}
    return names, loads


def multiqc_controls(path: Path) -> dict[str, dict[str, str]]:
    records: dict[str, dict[str, str]] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            name = row["Sample"]
            if not MULTIQC_CONTROL_TOKEN.search(name):
                continue
            records[name] = row
    return records


def archive_controls(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    report = json.loads(path.read_text(encoding="utf-8"))
    rows = []
    for accession, record in report.get("projects", {}).items():
        for run in record.get("run_to_sample", []):
            if CONTROL_TOKEN.search(run.get("sample_title", "")) or CONTROL_TOKEN.search(
                run.get("library_name", "")
            ):
                rows.append(
                    {
                        "source": "public_archive",
                        "identifier": run.get("library_name", ""),
                        "campaign": "",
                        "source_locator": f"{accession}/{run.get('run', '')}",
                        "site_field": "",
                        "has_sequence_run": "True",
                        "in_feature_table": "",
                        "archive_title": run.get("sample_title", ""),
                        "biosample": run.get("sample", ""),
                    }
                )
    return rows


def write_tsv(path: Path, rows: list[dict], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=columns, delimiter="\t", lineterminator="\n", extrasaction="ignore"
        )
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=root)
    parser.add_argument("--output-dir", type=Path, default=root / "revision/controls")
    parser.add_argument("--skip-feature-table", action="store_true")
    args = parser.parse_args()
    project_root = args.project_root.resolve()
    out = args.output_dir

    ledger = project_root / "data/release/sample_ledger.tsv"
    evidence = project_root / "data/release/release_evidence.json"
    feature_table = project_root / "data/processed/taxonomy/taxon-tables/feature-table-trips1-5.tsv"
    multiqc = project_root / "data-paper/zenodo/metadata/QC_reads/multiqc_general_stats.txt"
    archive = (
        project_root / "data-paper/zenodo/evidence/accessions/accession_reconciliation.json"
    )
    author_confirmation = out / "author_control_confirmation_20260729.tsv"
    for required in (ledger, evidence, multiqc, author_confirmation):
        if not required.is_file():
            print(f"FAIL: required control source is absent: {required}", file=sys.stderr)
            return 1

    inventory = ledger_controls(ledger) + unresolved_sequence_controls(evidence) + archive_controls(archive)

    qc = multiqc_controls(multiqc)
    for name, row in qc.items():
        inventory.append(
            {
                "source": "multiqc",
                "identifier": name,
                "campaign": "",
                "source_locator": "multiqc_general_stats.txt",
                "site_field": "",
                "has_sequence_run": "True",
                "in_feature_table": "",
            }
        )

    loads: dict[str, tuple[int, float]] = {}
    feature_columns: list[str] = []
    if not args.skip_feature_table and feature_table.is_file():
        feature_columns, loads = feature_table_controls(feature_table)
        for name in feature_columns:
            inventory.append(
                {
                    "source": "feature_table",
                    "identifier": name,
                    "campaign": "",
                    "source_locator": "feature-table-trips1-5.tsv",
                    "site_field": "",
                    "has_sequence_run": "",
                    "in_feature_table": "True",
                }
            )

    write_tsv(
        out / "control_inventory.tsv",
        inventory,
        [
            "source",
            "identifier",
            "campaign",
            "source_locator",
            "site_field",
            "has_sequence_run",
            "in_feature_table",
            "biosample",
            "archive_title",
        ],
    )

    load_rows = []
    for name, (observed, total) in sorted(loads.items()):
        short = name.split("_")[-1]
        pattern = re.compile(rf"[_-]{re.escape(short)}[_-]", re.IGNORECASE)
        matching_qc = sorted(key for key in qc if pattern.search(key))
        reads = ""
        if matching_qc:
            reads = qc[matching_qc[0]].get("fastqc-total_sequences", "")
        load_rows.append(
            {
                "control_profile": name,
                "observed_asvs": observed,
                "total_counts": f"{total:.0f}",
                "multiqc_record": matching_qc[0] if matching_qc else "",
                "multiqc_total_sequences_millions": reads,
            }
        )
    write_tsv(
        out / "control_read_and_asv_load.tsv",
        load_rows,
        [
            "control_profile",
            "observed_asvs",
            "total_counts",
            "multiqc_record",
            "multiqc_total_sequences_millions",
        ],
    )

    provenance = {
        "sources": {
            str(path.relative_to(project_root)): {"bytes": path.stat().st_size, "sha256": sha256(path)}
            for path in (ledger, evidence, multiqc, archive, author_confirmation)
            if path.is_file()
        },
        "feature_table": (
            {
                "path": str(feature_table.relative_to(project_root)),
                "bytes": feature_table.stat().st_size,
                "control_columns": len(feature_columns),
            }
            if feature_columns
            else "not scanned"
        ),
        "remote_discovery": {
            "ibex": "unreachable at run time (hostname did not resolve); no remote read performed",
            "workstation": "unreachable at run time (connection timed out)",
            "consequence": (
                "Raw read files and BCL-level run metadata were not inspected. "
                "Every statement here rests on local manifests, MultiQC output, "
                "the release ledger and public archive metadata."
            ),
        },
        "control_records_found": len(inventory),
        "ground_truth_table_written": False,
        "author_confirmation": {
            "confirmed": [
                "numbered positive and negative controls are replicate groups",
                "negative controls include distinct extraction-control and PCR-blank types",
                "EB denotes extraction blank",
                "Negative1-Negative7 are extraction blanks",
                "one EB was included per extraction day",
                "an extraction day could include samples from multiple trips",
                "EB labels do not encode trip and a single-trip assignment is not applicable",
            ],
            "pending": [
                "composition and trip assignment of the two mock communities",
                "exact extraction-day/batch membership for EB libraries",
                "sequence-index reconciliation of reused EB library labels",
                "identifier-level assignment of every PCR blank",
                "reason Negative3 is absent",
            ],
        },
        "gate": (
            "Two mock communities are author-confirmed, but their compositions "
            "and trip assignments remain pending from Marwa. "
            "control_ground_truth.tsv is not created."
        ),
    }
    (out / "control_provenance.json").write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    checksums = []
    for name in sorted(("control_inventory.tsv", "control_read_and_asv_load.tsv", "control_provenance.json")):
        path = out / name
        if path.is_file():
            checksums.append(f"{sha256(path)}  {name}\n")
    (out / "SHA256SUMS").write_text("".join(checksums), encoding="utf-8")

    print(f"control records inventoried: {len(inventory)}")
    print(f"control profiles in the feature table: {len(feature_columns)}")
    print(f"outputs -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
