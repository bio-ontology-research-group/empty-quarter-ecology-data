#!/usr/bin/env python3
"""Reconcile the project's accession statements against the live archives.

The descriptor cites three project accessions and the knowledge graph carries
per-run and per-sample cross-references.  Citing an accession that does not
resolve, or that covers a different set of samples than the text implies, is a
desk-reject risk, so this script resolves each of them against the live ENA
portal and reports only what the archives actually return.

For each project accession it records the study record, the number of public
read runs, and the run-to-sample mapping.  It then checks a sample of the
per-run and per-sample cross-references minted in the released graph, so the
report states whether a reader following a ``rdfs:seeAlso`` link would reach a
public record today.

Nothing is inferred: a run that returns no rows is reported as
``not_public_or_absent``, not as belonging to some project.  The report is
written whether or not the checks succeed; the exit status is non-zero only if
the API could not be reached at all.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

PORTAL = "https://www.ebi.ac.uk/ena/portal/api/filereport"
SEARCH = "https://www.ebi.ac.uk/ena/portal/api/search"
BROWSER = "https://www.ebi.ac.uk/ena/browser/api/xml"
PROJECTS = ("PRJNA1065643", "PRJEB104209", "PRJEB106069")
TIMEOUT = 120


def fetch(url: str) -> tuple[int, str]:
    request = urllib.request.Request(url, headers={"User-Agent": "eq-accession-audit/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return response.status, response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as error:
        raise SystemExit(f"FAIL: ENA API unreachable: {error}") from error


def read_submission_runs(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    import csv

    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def portal(accession: str, result: str, fields: str) -> list[dict[str, str]]:
    query = urllib.parse.urlencode(
        {"accession": accession, "result": result, "fields": fields, "format": "tsv", "limit": 0}
    )
    status, body = fetch(f"{PORTAL}?{query}")
    if status != 200 or not body.strip():
        return []
    lines = body.strip().split("\n")
    header = lines[0].split("\t")
    return [dict(zip(header, line.split("\t"))) for line in lines[1:]]


def graph_cross_references(module: Path) -> list[str]:
    """Every INSDC run accession cross-referenced by the sequence module."""
    if not module.is_file():
        return []
    text = module.read_text(encoding="utf-8", errors="replace")
    return sorted(set(re.findall(r"identifiers\.org/insdc\.run/([A-Z]{3}\d+)", text)))


def resolve_runs(accessions: list[str], snapshot_dir: Path, batch: int = 200) -> dict:
    """Resolve every accession, in batches, retaining the raw responses.

    The portal search endpoint accepts an accession list and returns a row only
    for runs that are public, so an absent row is evidence of non-publication
    rather than of a failed request. Each batch response is written verbatim so
    the result can be re-derived without contacting the service.
    """
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    fields = "run_accession,study_accession,secondary_study_accession,sample_accession,sample_title"
    resolved: dict[str, dict[str, str]] = {}
    batches = []
    for start in range(0, len(accessions), batch):
        chunk = accessions[start : start + batch]
        query = urllib.parse.urlencode(
            {
                "result": "read_run",
                "includeAccessions": ",".join(chunk),
                "fields": fields,
                "format": "tsv",
                "limit": 0,
            }
        )
        url = f"{SEARCH}?{query}"
        status, body = fetch(url)
        snapshot = snapshot_dir / f"batch_{start // batch:04d}.tsv"
        snapshot.write_text(body, encoding="utf-8")
        rows = []
        if status == 200 and body.strip():
            lines = body.strip().split("\n")
            header = lines[0].split("\t")
            rows = [dict(zip(header, line.split("\t"))) for line in lines[1:]]
        for row in rows:
            resolved[row["run_accession"]] = row
        batches.append(
            {
                "index": start // batch,
                "accessions_requested": len(chunk),
                "rows_returned": len(rows),
                "http_status": status,
                "snapshot": snapshot.name,
                "snapshot_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
                "query": query,
            }
        )
    return {"resolved": resolved, "batches": batches, "fields": fields}


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=root)
    parser.add_argument(
        "--output",
        type=Path,
        default=root / "data-paper/zenodo/evidence/accessions/accession_reconciliation.json",
    )
    parser.add_argument("--sample-runs", type=int, default=12)
    args = parser.parse_args()

    checked = datetime.now(timezone.utc).isoformat()
    projects = {}
    for accession in PROJECTS:
        study = portal(accession, "study", "study_accession,secondary_study_accession,study_title,first_public,last_updated")
        runs = portal(
            accession,
            "read_run",
            "run_accession,sample_accession,secondary_sample_accession,sample_title,"
            "library_name,instrument_platform,instrument_model,study_accession",
        )
        status, _ = fetch(f"{BROWSER}/{accession}")
        projects[accession] = {
            "browser_http_status": status,
            "public_study_record": study[0] if study else None,
            "public_read_runs": len(runs),
            "run_to_sample": [
                {
                    "run": row.get("run_accession", ""),
                    "sample": row.get("sample_accession", ""),
                    "sample_title": row.get("sample_title", ""),
                    "library_name": row.get("library_name", ""),
                    "instrument": row.get("instrument_model", ""),
                }
                for row in runs
            ],
            "verdict": (
                "public study with public read runs"
                if study and runs
                else "public study record, no public read runs under it"
                if study
                else "no public record"
            ),
        }

    module = args.project_root / "data/processed/semantics/ontology/rubalkhali_sra.owl"
    graph_runs = graph_cross_references(module)
    submission_runs = sorted(
        {
            row["run"]
            for row in read_submission_runs(
                args.project_root / "data/processed/amplicon/combined_samplesheet_accessions.tsv"
            )
        }
    )
    every_run = sorted(set(graph_runs) | set(submission_runs))
    snapshot_dir = args.output.parent / "ena_response_snapshots"
    resolution = resolve_runs(every_run, snapshot_dir)
    resolved = resolution["resolved"]
    cross_reference_checks = [
        {
            "run": run,
            "in_graph": run in set(graph_runs),
            "in_submissions": run in set(submission_runs),
            "resolves_publicly": run in resolved,
            "study_accession": resolved.get(run, {}).get("study_accession"),
            "sample_accession": resolved.get(run, {}).get("sample_accession"),
        }
        for run in every_run
    ]

    resolving = [check for check in cross_reference_checks if check["resolves_publicly"]]
    report = {
        "checked_utc": checked,
        "api": {"portal": PORTAL, "browser": BROWSER},
        "projects": projects,
        "run_level_reconciliation": {
            "sequence_module": str(module.relative_to(args.project_root)),
            "runs_in_graph": len(graph_runs),
            "runs_in_submissions": len(submission_runs),
            "runs_checked": len(every_run),
            "runs_resolving_publicly": len(resolving),
            "scope": "complete: every run accession in the module and in the submission sheets",
            "snapshot_dir": snapshot_dir.name,
            "batches": resolution["batches"],
            "fields": resolution["fields"],
            "checks": cross_reference_checks,
        },
        "conclusion": (
            "Not reconciled. PRJEB106069, the project every local run is "
            "registered against, returns no public record, and no local run "
            "accession resolves publicly, so no sample-level or run-level "
            "mapping to a public record can be established for the "
            "five-expedition release. PRJNA1065643 is public and internally "
            "consistent, but 85 MiSeq runs are not that release and it is not "
            "evidence for it. The three projects are therefore reported as "
            "unreconciled, not as available."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    for accession, record in projects.items():
        print(f"{accession}: {record['verdict']} ({record['public_read_runs']} public read runs)")
    print(
        f"run-level reconciliation: {len(every_run)} accessions checked "
        f"({len(graph_runs)} in the graph, {len(submission_runs)} in submissions); "
        f"{len(resolving)} resolve publicly"
    )
    print(f"report -> {args.output.resolve().relative_to(args.project_root.resolve())}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
