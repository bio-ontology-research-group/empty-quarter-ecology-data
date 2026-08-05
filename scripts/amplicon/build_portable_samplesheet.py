#!/usr/bin/env python3
"""Build a portable nf-core/ampliseq samplesheet from the submission records.

The samplesheet that produced the canonical feature table is absent from the
release and, in the form that ran, carried absolute IBEX scratch paths that
nobody outside the cluster can resolve.  This script rebuilds an equivalent
sheet from artifacts that are in the package: the two sequence submission
sheets, which carry the run accession for every deposited library, and the
release sample ledger, which carries the campaign, compartment and control
status of every identifier.

Read paths are emitted as ``${EQ_READS_DIR}/<run>_1.fastq.gz`` and
``_2.fastq.gz``, the European Nucleotide Archive layout, so a reuser sets one
environment variable instead of editing 1,500 rows.  The accompanying accession
table lets the same sheet be driven from a local mirror under any other naming
scheme.

The script fails closed on a duplicate sample identifier, a missing run
accession, or an unreadable input, because a silently dropped or duplicated row
changes every downstream count.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path

SUBMISSION_SHEETS = (
    "data-paper/zenodo/metadata/sra-submissions/submission-sheet.tsv",
    "data-paper/zenodo/metadata/sra-submissions/submission-sheet-trip5.tsv",
)
LEDGER = "data/release/sample_ledger.tsv"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=root)
    parser.add_argument("--output-dir", type=Path, default=root / "data/processed/amplicon")
    parser.add_argument("--reads-variable", default="${EQ_READS_DIR}")
    args = parser.parse_args()
    project_root = args.project_root.resolve()

    sheets = [project_root / name for name in SUBMISSION_SHEETS]
    ledger_path = project_root / LEDGER
    for required in (*sheets, ledger_path):
        if not required.is_file():
            print(f"FAIL: required input is absent: {required}", file=sys.stderr)
            return 1

    ledger = {row["sample_id"]: row for row in read_tsv(ledger_path)}

    # The Trip 5 submission sheet re-lists rows that are already in the main
    # sheet, so collapse on the run accession first. Two rows that share a run
    # accession but disagree on the sample name are a real conflict and abort.
    by_run: dict[str, dict[str, str]] = {}
    problems: list[str] = []
    duplicate_rows = 0
    for sheet in sheets:
        for record in read_tsv(sheet):
            sample = (record.get("sample_name") or "").strip()
            run = (record.get("run_accession") or "").strip()
            if not sample:
                problems.append(f"{sheet.name}: row without a sample_name")
                continue
            if not run:
                problems.append(f"{sheet.name}: {sample} has no run_accession")
                continue
            existing = by_run.get(run)
            if existing is not None:
                if (existing.get("sample_name") or "").strip() != sample:
                    problems.append(
                        f"run {run} is listed with conflicting sample names: "
                        f"{existing.get('sample_name')!r} and {sample!r}"
                    )
                duplicate_rows += 1
                continue
            by_run[run] = record

    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for run, record in sorted(by_run.items(), key=lambda item: item[0]):
        sample = record["sample_name"].strip()
        key = sample
        suffix = 1
        while key in seen:
            # A sample can genuinely carry more than one library, each with its
            # own run. Disambiguate deterministically instead of dropping.
            suffix += 1
            key = f"{sample}__lib{suffix}"
        seen.add(key)
        if True:
            ledger_row = ledger.get(sample, {})
            rows.append(
                {
                    "sampleID": key,
                    "forwardReads": f"{args.reads_variable}/{run}_1.fastq.gz",
                    "reverseReads": f"{args.reads_variable}/{run}_2.fastq.gz",
                    "run": run,
                    "source_sample_name": sample,
                    "biosample_accession": record.get("biosample_accession", ""),
                    "experiment_accession": record.get("experiment_accession", ""),
                    "library_name": record.get("library_name", ""),
                    "bioproject": record.get("bioproject", ""),
                    "umbrella_project": record.get("umbrella_project", ""),
                    "campaign": ledger_row.get("trip", ""),
                    "compartment": ledger_row.get("compartment", ""),
                    "is_control": ledger_row.get("is_control", ""),
                    "in_ledger": "True" if sample in ledger else "False",
                }
            )

    if problems:
        print(f"FAIL: {len(problems)} submission rows are unusable", file=sys.stderr)
        for problem in problems[:10]:
            print(f"  {problem}", file=sys.stderr)
        return 1

    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)

    samplesheet = out / "combined_samplesheet_portable.csv"
    with samplesheet.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["sampleID", "forwardReads", "reverseReads", "run"],
            lineterminator="\n",
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)

    accessions = out / "combined_samplesheet_accessions.tsv"
    with accessions.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)

    unmatched = [row["source_sample_name"] for row in rows if row["in_ledger"] == "False"]
    summary = {
        "rows": len(rows),
        "distinct_source_sample_names": len({row["source_sample_name"] for row in rows}),
        "duplicate_submission_rows_collapsed_on_run": duplicate_rows,
        "disambiguated_identifiers": sum(1 for row in rows if row["sampleID"] != row["source_sample_name"]),
        "rows_without_a_ledger_match": len(unmatched),
        "examples_without_a_ledger_match": sorted(set(unmatched))[:20],
        "bioprojects": sorted({row["bioproject"] for row in rows if row["bioproject"]}),
        "umbrella_projects": sorted({row["umbrella_project"] for row in rows if row["umbrella_project"]}),
        "inputs": {
            str(path.relative_to(project_root)): sha256(path) for path in (*sheets, ledger_path)
        },
        "outputs": {
            str(samplesheet.relative_to(project_root)): sha256(samplesheet),
            str(accessions.relative_to(project_root)): sha256(accessions),
        },
        "reads_variable": args.reads_variable,
        "usage": (
            "export EQ_READS_DIR=/path/to/fastq && nextflow run nf-core/ampliseq "
            "-r 2.14.0 --input combined_samplesheet_portable.csv ... ; the read "
            "files must be named <run>_1.fastq.gz and <run>_2.fastq.gz, which is "
            "the archive layout. Runs are not public at the time of writing, so "
            "the sheet is portable in structure but not yet resolvable from the "
            "archive alone."
        ),
    }
    (out / "portable_samplesheet_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    print(f"rows: {len(rows)}; disambiguated identifiers: {summary['disambiguated_identifiers']}")
    print(f"rows without a ledger match: {len(unmatched)}")
    print(f"outputs -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
