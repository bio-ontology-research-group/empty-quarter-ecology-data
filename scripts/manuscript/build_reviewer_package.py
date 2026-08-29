#!/usr/bin/env python3
"""Build a versioned, anonymously downloadable *candidate* package.

This is a candidate, not a deposit-ready release. Several gates are still open
(project and third-party licences, control identities, historic climate
acquisition provenance, accession mappings, administrative declarations), and
the package summary says so. Calling it deposit-ready before those close would
misrepresent it.

"Anonymous" here has the meaning the journal gives it: a referee can download
the archive without credentials. It does **not** mean the dataset has been
stripped of contributor names. Scientific and provenance content --- including
curator attribution in the correction ledgers --- is archived verbatim. Every
packaged payload is byte-identical to its staging-manifest entry, and the
package checksums are computed from the exact packaged bytes.

What is gated is machine-specific noise, not people: a file that leaks an
absolute machine path exposes the builder's filesystem layout and should be fixed
at its source. Such files fail the build unless they are named in
``--allow-absolute-paths``, which requires a stated reason.

Files above ``--bulk-threshold`` are listed in a bulk manifest with their sizes
and checksums instead of being placed in the archive, because an archive a
referee cannot download is not a reviewer archive. ``--include-bulk`` produces
the full tree.

The archive is written deterministically (sorted members, zeroed member
metadata, gzip without a timestamp), so two builds from the same tree are
byte-identical.
"""

from __future__ import annotations

import argparse
import csv
from collections import Counter
import gzip
import hashlib
import json
import re
import sys
import tarfile
from pathlib import Path

# Absolute machine paths are build noise and are gated. Scan every payload as
# bytes so extensionless caches and compiled artifacts cannot evade the gate.
# Contributor names are provenance and are not scanned for or removed.
ABSOLUTE_MACHINE_PATH = re.compile(
    rb"(?<![A-Za-z0-9._-])/(?:home|ibex|scratch|mnt)/",
    re.IGNORECASE,
)

# Workflow-generated provenance records that legitimately quote the absolute
# paths of the run that produced them. Rewriting them would break the checksums
# the authoritative run recorded, so they are gated with a stated reason.
DEFAULT_ALLOWED_ABSOLUTE_PATHS = {
    "evidence/competency-query/competency_query_validation.json":
        "workflow provenance: quotes the input paths of the 2026-07-24 run that "
        "the record checksums; rewriting it would invalidate that evidence",
    "evidence/xrf_chemical_mapping_audit/xrf_chemical_mapping_audit.json":
        "workflow provenance: quotes the pinned ChEBI and PubChem source paths "
        "of the run that produced the audit",
    "evidence/semantic-validation/semantic_validation_20260801.log":
        "workflow provenance: quotes the local generated-module and ontology "
        "cache paths used by the checksummed 2026-08-01 validation run",
    "evidence/primer-identity/source_paths.tsv":
        "scientific provenance: frozen access-controlled raw-read paths identify "
        "the exact files inspected by the primer audit",
    "evidence/taxonomy-abox/taxonomy_abox_streaming_validation.json":
        "workflow provenance: records the exact multi-gigabyte generated ABox "
        "path validated by the frozen full-file run",
    "evidence/taxonomy-abox/taxonomy_abox_streaming_validation.log":
        "workflow provenance: records the exact multi-gigabyte generated ABox "
        "path parsed by the independent full-file run",
    "metadata/controls/control_sequence_occurrences.tsv":
        "scientific provenance: frozen access-controlled FASTQ paths distinguish "
        "the exact control sequence occurrences",
    "ontology/rubalkhali_controls.owl":
        "scientific provenance: the control ABox preserves access-controlled "
        "FASTQ source paths without distributing the reads",
    "ontology/rubalkhali_controls.ttl":
        "scientific provenance: the control ABox preserves access-controlled "
        "FASTQ source paths without distributing the reads",
    "metadata/functional/PICRUST2.md":
        "historic workflow provenance: records the original controlled PICRUSt2 "
        "output locations while portable package paths are stated separately",
}


def scan_for_absolute_paths(path: Path, limit: int = 8 * 1024 * 1024) -> int:
    """Count absolute machine paths in any file, including binary payloads."""
    hits = 0
    tail = b""
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(limit)
            if not chunk:
                break
            combined = tail + chunk
            boundary = len(tail)
            hits += sum(
                match.end() > boundary
                for match in ABSOLUTE_MACHINE_PATH.finditer(combined)
            )
            tail = combined[-256:]
    return hits


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", type=Path, default=root / "zenodo")
    parser.add_argument("--output-dir", type=Path, default=root.parent / "dist")
    parser.add_argument("--version", required=True, help="package version, e.g. 0.6.0-rc2")
    parser.add_argument("--bulk-threshold", type=int, default=256 * 1024 * 1024)
    parser.add_argument("--include-bulk", action="store_true")
    parser.add_argument(
        "--allow-absolute-paths",
        action="append",
        default=None,
        help="staged path permitted to contain an absolute machine path (repeatable)",
    )
    args = parser.parse_args()

    allowed = dict(DEFAULT_ALLOWED_ABSOLUTE_PATHS)
    for extra in args.allow_absolute_paths or []:
        allowed.setdefault(extra, "allowed on the command line")

    stage = args.stage.resolve()
    manifest_path = stage / "PRE_RELEASE_MANIFEST.tsv"
    if not manifest_path.is_file():
        print(f"FAIL: manifest is absent: {manifest_path}", file=sys.stderr)
        return 1
    with manifest_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    licence_counts = Counter(row["license_status"] for row in rows)

    missing = [row["path"] for row in rows if not (stage / row["path"]).is_file()]
    if missing:
        print(f"FAIL: {len(missing)} declared artifacts are absent: {missing[:5]}", file=sys.stderr)
        return 1

    # Every member must match its manifest entry byte for byte before it is
    # packaged; the package must not be able to diverge from the manifest.
    drifted = []
    for row in rows:
        artifact = stage / row["path"]
        if artifact.stat().st_size != int(row["bytes"]) or sha256(artifact) != row["sha256"]:
            drifted.append(row["path"])
    if drifted:
        print(
            f"FAIL: {len(drifted)} staged files differ from the manifest: {drifted[:5]}",
            file=sys.stderr,
        )
        return 1

    included, bulk = [], []
    for row in rows:
        if not args.include_bulk and int(row["bytes"]) > args.bulk_threshold:
            bulk.append(row)
        else:
            included.append(row)

    problems: list[str] = []
    gated: list[dict] = []
    scanned = 0
    for row in included:
        path = stage / row["path"]
        if Path(row["path"]).is_absolute():
            problems.append(f"{row['path']}: the staged path itself is machine-specific")
        scanned += 1
        hits = scan_for_absolute_paths(path)
        if not hits:
            continue
        if row["path"] in allowed:
            gated.append({"path": row["path"], "occurrences": hits, "reason": allowed[row["path"]]})
        else:
            problems.append(
                f"{row['path']}: {hits} absolute machine path(s); fix the generator "
                "or gate the file with --allow-absolute-paths"
            )
    if problems:
        print(f"FAIL: {len(problems)} path-disclosure problems; no archive written", file=sys.stderr)
        for problem in problems[:20]:
            print(f"  {problem}", file=sys.stderr)
        return 1

    name = f"empty-quarter-kg-{args.version}"
    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)
    archive_path = out / f"{name}.tar.gz"
    temporary = archive_path.with_suffix(".tmp")

    def member(arcname: str, size: int) -> tarfile.TarInfo:
        info = tarfile.TarInfo(arcname)
        info.size = size
        info.mtime = 0
        info.mode = 0o644
        info.uid = info.gid = 0
        info.uname = info.gname = ""
        info.type = tarfile.REGTYPE
        return info

    with temporary.open("wb") as sink:
        with gzip.GzipFile(fileobj=sink, mode="wb", compresslevel=6, mtime=0) as gz:
            with tarfile.open(fileobj=gz, mode="w|", format=tarfile.GNU_FORMAT) as archive:
                # The manifest describes the tree, so it is not one of its own
                # rows; add it explicitly or the archive cannot be verified.
                with manifest_path.open("rb") as handle:
                    archive.addfile(
                        member(f"{name}/{manifest_path.name}", manifest_path.stat().st_size), handle
                    )
                for row in sorted(included, key=lambda item: item["path"]):
                    source = stage / row["path"]
                    with source.open("rb") as handle:
                        archive.addfile(
                            member(f"{name}/{row['path']}", source.stat().st_size), handle
                        )
    temporary.replace(archive_path)

    bulk_path = out / f"{name}-bulk.manifest.tsv"
    with bulk_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["path", "bytes", "sha256", "category", "release_status", "record_scope"],
            delimiter="\t",
            lineterminator="\n",
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(bulk)

    # Checksums are taken from the bytes actually written.
    archive_digest = sha256(archive_path)
    bulk_digest = sha256(bulk_path)
    checksums = out / f"{name}.SHA256SUMS"
    checksums.write_text(
        f"{archive_digest}  {archive_path.name}\n{bulk_digest}  {bulk_path.name}\n",
        encoding="utf-8",
    )

    summary = {
        "version": args.version,
        "status": "candidate",
        "deposit_ready": False,
        "open_gates_blocking_deposit": [
            (
                "per-file licences: "
                f"{licence_counts['AUTHOR_GATE_UNRESOLVED']} author gates and "
                f"{licence_counts['THIRD_PARTY_LICENCE_UNRECORDED']} "
                "third-party gates unresolved"
            ),
            "historic climate acquisition: raw responses, per-request timestamps and "
            "upstream model version were never captured",
            "accession mappings: none of the 1,268 local run accessions resolves publicly",
            "administrative declarations (contributions, funding, acknowledgements, "
            "competing interests, LLM-use disclosure) are author-controlled and unset",
        ],
        "documented_scientific_scope_limits": [
            (
                "archived-soil pH: 712 of 1,168 source rows are admitted; "
                "356 remain without a measurement, 45 are depleted, 36 have "
                "ambiguous dates and 19 lack complete recorded QC. Coverage is "
                "incomplete and non-random, and no value is imputed"
            ),
            (
                "control coverage: one Trip 4 extraction blank was not sequenced; "
                "Trip 5 has no 16S positive control; EB18 and Negative1/2/4-7 "
                "lack extraction-batch mappings; PCR-blank mappings, DNA "
                "concentrations and the sterile-bag inventory are incomplete"
            ),
            (
                "the canonical community table remains unfiltered; the released "
                "351-ASV removal is a bounded sensitivity for 217 mapped Trip 5 "
                "profiles, with all 25 headline verdicts stable"
            ),
        ],
        "archive": {
            "name": archive_path.name,
            "bytes": archive_path.stat().st_size,
            "sha256": archive_digest,
            "members": len(included) + 1,
        },
        "bulk_manifest": {
            "name": bulk_path.name,
            "sha256": bulk_digest,
            "entries": len(bulk),
            "bytes_total": sum(int(row["bytes"]) for row in bulk),
            "paths": [row["path"] for row in bulk],
        },
        "bulk_threshold_bytes": args.bulk_threshold,
        "include_bulk": args.include_bulk,
        "payload_integrity": {
            "members_verified_against_manifest": len(rows),
            "members_modified_during_packaging": 0,
            "note": (
                "No member is altered. Contributor names and other provenance are "
                "archived verbatim; anonymous download means access without "
                "credentials, not anonymised content."
            ),
        },
        "path_disclosure_scan": {
            "pattern": ABSOLUTE_MACHINE_PATH.pattern.decode("ascii"),
            "members_scanned": scanned,
            "unresolved": 0,
            "gated": gated,
        },
        "published": False,
        "note": (
            "Reviewer candidate package. Not uploaded, no DOI minted, no external "
            "deposition performed."
        ),
    }
    (out / f"{name}.package.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    print(f"archive : {archive_path} ({archive_path.stat().st_size} bytes, {len(included) + 1} members)")
    print(f"bulk    : {bulk_path} ({len(bulk)} entries, {summary['bulk_manifest']['bytes_total']} bytes)")
    print(f"gated   : {len(gated)} file(s) with workflow-provenance absolute paths")
    print(f"status  : candidate, not deposit-ready ({len(summary['open_gates_blocking_deposit'])} open gates)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
