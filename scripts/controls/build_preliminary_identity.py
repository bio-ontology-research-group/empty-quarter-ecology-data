#!/usr/bin/env python3
"""Build the complete preliminary control identity table.

"Preliminary" means every field the control audit needs is present and every
uncertain field is marked, not that the table is a summary.  One row per
control identifier, with the machine-derived columns joined from the inventory,
the per-profile loads, the dominant-taxon table, the MultiQC records and the
sequence submissions, and the judgement columns supplied by a curated map that
must cover every discovered identifier or the run aborts.

Nothing here is promoted.  Every row carries ``promoted=NO``, a competing
interpretation and a confidence grade, and
``revision/controls/control_ground_truth.tsv`` is neither written nor implied.

Two facts that the table records explicitly rather than smoothing over:

* the identifier ``EB1``-``EB5`` appears both in a July-era sequencing run
  (MultiQC records ``M-25-0770``-``M-25-0774``) and in the Trip-5-era
  submission block ``EB1``-``EB18``. The author confirmed that one EB was
  included per extraction day and that an extraction day could include
  samples from several trips. A single-trip assignment is therefore not
  applicable. Sequence indices can help distinguish libraries and resolve
  reused-label collisions, but the extraction-day/batch mapping and whether
  each collision is the same library or a reused label remain pending;
* ``Negative3`` exists in neither the submissions nor the feature table, and
  no record states why.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

UNKNOWN = "unknown"

# Judgement columns, keyed by identifier family. Every discovered control
# identifier must match exactly one family, or the build fails.
FAMILIES: tuple[tuple[re.Pattern, dict[str, str]], ...] = (
    (
        re.compile(r"^=?\+ Ctrl 1$"),
        {
            "family": "positive_sampling_trip",
            "control_stage": "sampling campaign (carried through collection)",
            "polarity": "positive",
            "commercial_or_custom_candidate": (
                "one of two mock communities used across trips; Trip 1 archive "
                "candidate: ZymoBIOMICS D6305"
            ),
            "candidate_organisms": (
                "composition and trip assignment pending from Marwa; the Trip 1 "
                "archive title names D6305 but does not establish other trips"
            ),
            "evidence": (
                "PRJNA1065643 run SRR27587622 / biosample SAMN39465916, "
                "library_name '+ Ctrl 1', sample_title 'Positive control - "
                "sampling trip (Zymo D6305)'; matches this master-sheet "
                "identifier once the leading '=' spreadsheet artifact is removed; "
                "Robert confirmed that the numbered positives are replicates and "
                "that different positive controls were used across trips"
            ),
            "competing_interpretation": (
                "the archive title is submission metadata for one campaign, not "
                "a laboratory record; it cannot assign either of the two mock "
                "communities to the remaining trips and states no lot"
            ),
            "confidence": (
                "high for the Trip 1 identifier and replicate status; composition "
                "and all other trip assignments pending"
            ),
        },
    ),
    (
        re.compile(r"^\+ Zymo$"),
        {
            "family": "positive_pcr",
            "control_stage": "PCR",
            "polarity": "positive",
            "commercial_or_custom_candidate": "commercial candidate: ZymoBIOMICS D6305",
            "candidate_organisms": (
                "composition pending from Marwa; the archive title names D6305 "
                "for this Trip 1 PCR control"
            ),
            "evidence": (
                "PRJNA1065643 run SRR27587611 / biosample SAMN39465917, "
                "library_name '+ Zymo', sample_title 'Positive control - PCR "
                "(Zymo D6305)'"
            ),
            "competing_interpretation": (
                "no master-sheet identifier matches it, so its relation to "
                "'=+ Ctrl 2' and '=+ Ctrl 3' is unresolved; it may be an "
                "additional PCR-stage positive rather than a numbered replicate"
            ),
            "confidence": "high for the archive record; unresolved as to which ledger row it is",
        },
    ),
    (
        re.compile(r"^=\+ Ctrl [23]$"),
        {
            "family": "positive_numbered_replicate",
            "control_stage": UNKNOWN,
            "polarity": "positive",
            "commercial_or_custom_candidate": (
                "one of two mock communities used across trips; exact assignment pending"
            ),
            "candidate_organisms": "composition and trip assignment pending from Marwa",
            "evidence": (
                "Robert confirmed that '=+ Ctrl 1', '=+ Ctrl 2' and '=+ Ctrl 3' "
                "are replicates; master-sheet rows do not identify which of the "
                "two mock communities or which preparation stage"
            ),
            "competing_interpretation": (
                "replicate status is confirmed, but replication may be within a "
                "trip-specific control set rather than across all trips"
            ),
            "confidence": "high for polarity and replicate status; composition, stage and trip assignment pending",
        },
    ),
    (
        re.compile(r"^- Ctrl 3$"),
        {
            "family": "negative_sampling_trip",
            "control_stage": "sampling campaign (carried through collection)",
            "polarity": "negative",
            "commercial_or_custom_candidate": "custom (matrix not recorded)",
            "candidate_organisms": "not applicable",
            "evidence": (
                "PRJNA1065643 run SRR27587623 / biosample SAMN39465915, "
                "library_name '- Ctrl 3', sample_title 'Negative control - "
                "sampling trip'; exact match to this master-sheet identifier; "
                "Robert confirmed that the numbered negatives are replicates"
            ),
            "competing_interpretation": (
                "Robert confirmed two distinct negative-control types, extraction "
                "controls and PCR blanks, but the numbered replicates have not "
                "been mapped to either type"
            ),
            "confidence": "high for identifier, polarity and replicate status; exact negative-control type unresolved",
        },
    ),
    (
        re.compile(r"^- Ctrl [12]$"),
        {
            "family": "negative_numbered_replicate",
            "control_stage": UNKNOWN,
            "polarity": "negative",
            "commercial_or_custom_candidate": "custom blank; extraction-versus-PCR type pending",
            "candidate_organisms": "not applicable",
            "evidence": (
                "Robert confirmed that '- Ctrl 1', '- Ctrl 2' and '- Ctrl 3' are "
                "replicates and that extraction controls and PCR blanks were two "
                "distinct negative-control types"
            ),
            "competing_interpretation": (
                "the numbered replicate group has not been assigned to the "
                "extraction-control or PCR-blank type"
            ),
            "confidence": "high for polarity and replicate status; exact type and batch unknown",
        },
    ),
    (
        re.compile(r"^(- Ctrl PCR( 2)?|PCR Ctrl|Neg Ctrl \(PCR\))$"),
        {
            "family": "negative_pcr",
            "control_stage": "PCR (no-template)",
            "polarity": "negative",
            "commercial_or_custom_candidate": "custom (no template)",
            "candidate_organisms": "not applicable",
            "evidence": (
                "PRJNA1065643 run SRR27587568, library_name 'Neg Ctrl (PCR)', "
                "sample_title 'Negative control - PCR'; MultiQC record "
                "M-25-0555_PCR-Ctrl-Trip1_UDP0374"
            ),
            "competing_interpretation": (
                "the master-sheet identifiers and the archive library name are "
                "not byte-identical, so the mapping is by role rather than by "
                "identifier"
            ),
            "confidence": "moderate-to-high for the role; identifier mapping inferred",
        },
    ),
    (
        re.compile(r"^Extraction Ctrl( 2)?$"),
        {
            "family": "extraction_blank_named",
            "control_stage": "DNA extraction",
            "polarity": "negative",
            "commercial_or_custom_candidate": "custom (extraction blank)",
            "candidate_organisms": "not applicable",
            "evidence": (
                "master-sheet rows; MultiQC record "
                "M-25-0929_Extraction-Ctrl-Pro-Trip1_UDP0384 names a Trip 1 "
                "PowerSoil Pro extraction control"
            ),
            "competing_interpretation": (
                "which extraction batch each blank accompanied is not recorded, "
                "and 'Ctrl 2' may be a second batch or a second replicate"
            ),
            "confidence": "moderate for the stage; batch unknown",
        },
    ),
    (
        re.compile(r"^EB\d+$"),
        {
            "family": "extraction_blank_eb",
            "control_stage": "DNA extraction",
            "polarity": "negative",
            "commercial_or_custom_candidate": "custom (extraction blank)",
            "candidate_organisms": "not applicable",
            "evidence": (
                "18 submission rows ERR16783283-ERR16783300 and 18 canonical "
                "feature-table profiles; MultiQC carries EB1-EB5 only, with "
                "distinct indices SU0216, SU0228, SU0240, SU0252, SU0264; Robert "
                "and Marwa confirmed that EB denotes extraction blank; Robert "
                "confirmed that one EB was included per extraction day and that "
                "samples from multiple trips could be extracted on the same day"
            ),
            "competing_interpretation": (
                "the MultiQC EB1-EB5 records belong to a July-era run "
                "(M-25-0770-M-25-0774), while EB1-EB5 also occur in the Trip-5-era "
                "submission block; sequence indices can help adjudicate library "
                "identity or label reuse, but cannot assign an extraction-day blank "
                "to one trip; exact extraction-day/batch membership and each "
                "collision's library identity remain pending"
            ),
            "confidence": (
                "high for extraction-blank stage and per-day design; trip is not "
                "applicable, while extraction-day/batch membership and cross-run "
                "label identity remain pending"
            ),
        },
    ),
    (
        re.compile(r"^Negative\d+$"),
        {
            "family": "negative_numbered",
            "control_stage": "DNA extraction",
            "polarity": "negative",
            "commercial_or_custom_candidate": "custom (extraction blank)",
            "candidate_organisms": "not applicable",
            "evidence": (
                "six submission rows ERR16783301-ERR16783307 and six canonical "
                "feature-table profiles; Negative3 is absent from both and no "
                "record states why; Robert confirmed that Negative1-Negative7 "
                "are extraction blanks"
            ),
            "competing_interpretation": (
                "the missing Negative3 may have failed QC, been withdrawn, or "
                "never existed; trip and extraction batch are not recorded"
            ),
            "confidence": "high for extraction-blank stage; trip, batch and missing-Negative3 disposition unknown",
        },
    ),
    (
        re.compile(r"^T_Neg_Ctrl\d+$"),
        {
            "family": "negative_trip_prefixed",
            "control_stage": UNKNOWN,
            "polarity": "negative",
            "commercial_or_custom_candidate": UNKNOWN,
            "candidate_organisms": "not applicable",
            "evidence": (
                "submission rows ERR16061177 and ERR16061178; MultiQC records "
                "M-25-0870_Neg-Ctrl-1-Trip2_SU0335 and "
                "M-25-0871_Neg-Ctrl-2-Trip2_SU0347 name Trip 2 negative controls"
            ),
            "competing_interpretation": (
                "the T prefix is the project's Trip 2 sample-naming convention, "
                "not a recorded campaign field on these rows; the MultiQC "
                "correspondence is by role and ordinal, not by identifier"
            ),
            "confidence": "moderate for Trip 2 and negative status; stage unknown",
        },
    ),
)

JUDGEMENT_COLUMNS = (
    "family",
    "control_stage",
    "polarity",
    "commercial_or_custom_candidate",
    "candidate_organisms",
    "evidence",
    "competing_interpretation",
    "confidence",
)

COLUMNS = (
    "control_id",
    "aliases",
    "raw_files_or_accessions",
    "trip",
    "extraction_batch",
    "pcr_batch",
    "library_batch",
    "index",
    "lane",
    "control_stage",
    "polarity",
    "commercial_or_custom_candidate",
    "candidate_organisms",
    "multiqc_join",
    "observed_dominant_taxa",
    "observed_asvs",
    "read_count",
    "evidence",
    "competing_interpretation",
    "confidence",
    "promoted",
    "family",
)

REQUIRED_AUTHOR_CONFIRMATION_IDS = {f"AC-{number:03d}" for number in range(1, 10)}

MULTIQC_NAME = re.compile(
    r"^(?P<library>M-\d+-\d+)_(?P<label>.+?)_(?P<index>[A-Z]+\d+)-[A-Z]+\d+_(?P<lane>L\d+)_R[12]_001$"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def judgement(control_id: str) -> dict[str, str] | None:
    for pattern, values in FAMILIES:
        if pattern.match(control_id):
            return values
    return None


def normalise(label: str) -> str:
    """Normalise a control label for joining, preserving polarity.

    MultiQC labels use hyphens where the ledger uses spaces, but the leading
    sign is the one character that distinguishes a positive control from a
    negative one, so it must survive normalisation. The leading '=' is the
    spreadsheet artifact and is dropped.
    """
    stripped = label.strip()
    sign = ""
    if stripped.startswith("=+") or stripped.startswith("+"):
        sign = "pos"
    elif stripped.startswith("-"):
        sign = "neg"
    return sign + re.sub(r"[^a-z0-9]", "", stripped.lower())


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=root)
    parser.add_argument("--controls-dir", type=Path, default=root / "revision/controls")
    args = parser.parse_args()
    project_root = args.project_root.resolve()
    controls = args.controls_dir

    inventory_path = controls / "control_inventory.tsv"
    loads_path = controls / "control_read_and_asv_load.tsv"
    dominant_path = controls / "control_profile_dominant_taxa.tsv"
    author_confirmation_path = controls / "author_control_confirmation_20260729.tsv"
    multiqc_path = project_root / "data-paper/zenodo/metadata/QC_reads/multiqc_general_stats.txt"
    ledger_path = project_root / "data/release/sample_ledger.tsv"
    for required in (
        inventory_path,
        loads_path,
        dominant_path,
        author_confirmation_path,
        multiqc_path,
        ledger_path,
    ):
        if not required.is_file():
            print(f"FAIL: required input is absent: {required}", file=sys.stderr)
            return 1

    inventory = read_tsv(inventory_path)
    author_confirmations = read_tsv(author_confirmation_path)
    confirmation_ids = {row["confirmation_id"] for row in author_confirmations}
    if confirmation_ids != REQUIRED_AUTHOR_CONFIRMATION_IDS:
        print(
            "FAIL: author confirmation ids differ from the required set: "
            f"{sorted(confirmation_ids)}",
            file=sys.stderr,
        )
        return 1
    allowed_confirmation_statuses = {"CONFIRMED", "PARTIALLY_CONFIRMED", "AMBIGUOUS"}
    invalid_confirmation_statuses = sorted(
        {
            row["status"]
            for row in author_confirmations
            if row["status"] not in allowed_confirmation_statuses
        }
    )
    if invalid_confirmation_statuses:
        print(
            f"FAIL: invalid author confirmation statuses: {invalid_confirmation_statuses}",
            file=sys.stderr,
        )
        return 1
    loads = {row["control_profile"]: row for row in read_tsv(loads_path)}
    dominant: dict[str, list[str]] = defaultdict(list)
    for row in read_tsv(dominant_path):
        dominant[row["control_profile"]].append(
            f"{row['taxon']} {row['share_of_profile']}"
        )

    multiqc: dict[str, dict[str, str]] = {}
    with multiqc_path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            match = MULTIQC_NAME.match(row["Sample"])
            if not match:
                continue
            key = normalise(match.group("label"))
            multiqc.setdefault(
                key,
                {
                    "library": match.group("library"),
                    "index": match.group("index"),
                    "lane": match.group("lane"),
                    "sample": row["Sample"],
                    "total_sequences_millions": row.get("fastqc-total_sequences", ""),
                },
            )

    trips: dict[str, set[str]] = defaultdict(set)
    for row in read_tsv(ledger_path):
        if row.get("is_control", "").lower() == "true":
            trips[row["sample_id"]].add(row["trip"])

    accessions: dict[str, set[str]] = defaultdict(set)
    aliases: dict[str, set[str]] = defaultdict(set)
    for row in inventory:
        identifier = row["identifier"]
        if row["source"] in {"sequence_submission", "public_archive"}:
            accessions[identifier].add(row["source_locator"])
            if row.get("biosample"):
                accessions[identifier].add(row["biosample"])
        if row.get("archive_title"):
            aliases[identifier].add(row["archive_title"])

    control_ids = sorted(
        {row["identifier"] for row in inventory if row["source"] != "multiqc"}
    )
    unmatched = [cid for cid in control_ids if judgement(cid) is None]
    if unmatched:
        print(
            f"FAIL: {len(unmatched)} control identifiers have no curated family: {unmatched}",
            file=sys.stderr,
        )
        return 1

    # A MultiQC record reachable from more than one control identifier cannot
    # be assigned to either.
    ambiguous_multiqc: dict[str, int] = defaultdict(int)
    for control_id in control_ids:
        record = multiqc.get(normalise(control_id))
        if record is not None:
            ambiguous_multiqc[record["sample"]] += 1

    rows = []
    for control_id in control_ids:
        values = judgement(control_id)
        # Join to MultiQC only when the correspondence is unambiguous. A
        # MultiQC label such as "Ctrl-1-Trip1" carries no polarity sign, so it
        # is reachable from both "- Ctrl 1" and "=+ Ctrl 1"; assigning its
        # index and lane to either would assert a library identity the records
        # do not establish.
        # Exact normalised equality only. A prefix match would attach, for
        # example, the Trip 2 record "Neg-Ctrl-1-Trip2" to the master-sheet
        # identifier "- Ctrl 1", which the records do not support. Near
        # matches are reported as candidates, never as a join.
        qc = {}
        exact = multiqc.get(normalise(control_id))
        if exact is not None and ambiguous_multiqc.get(exact["sample"], 0) == 1:
            qc = exact
        else:
            near = sorted(
                record["sample"]
                for key, record in multiqc.items()
                if key.startswith(normalise(control_id))
                or normalise(control_id).startswith(key)
            )
            if near:
                qc = {"ambiguous": "; ".join(near)}
        load = loads.get(control_id, {})
        row = {
            "control_id": control_id,
            "aliases": "; ".join(sorted(aliases.get(control_id, set()))) or UNKNOWN,
            "raw_files_or_accessions": "; ".join(sorted(accessions.get(control_id, set())))
            or qc.get("sample", UNKNOWN),
            "trip": "; ".join(sorted(trips.get(control_id, set()))) or UNKNOWN,
            "extraction_batch": UNKNOWN,
            "pcr_batch": UNKNOWN,
            "library_batch": qc.get("library", UNKNOWN),
            "index": qc.get("index", UNKNOWN),
            "lane": qc.get("lane", UNKNOWN),
            "multiqc_join": qc.get("sample")
            or (
                f"candidate only, not asserted: {qc['ambiguous']}"
                if qc.get("ambiguous")
                else "no unambiguous MultiQC record"
            ),
            "observed_dominant_taxa": "; ".join(dominant.get(control_id, [])[:3])
            or "not in the canonical feature table",
            "observed_asvs": load.get("observed_asvs", UNKNOWN),
            "read_count": load.get("total_counts")
            or (
                f"{qc['total_sequences_millions']}M (MultiQC)"
                if qc.get("total_sequences_millions")
                else UNKNOWN
            ),
            "promoted": "NO",
        }
        if re.fullmatch(r"EB\d+", control_id):
            row["trip"] = "not applicable (extraction day may include multiple trips)"
        row.update({column: values[column] for column in JUDGEMENT_COLUMNS})
        rows.append(row)

    output = controls / "preliminary_control_identity.tsv"
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=list(COLUMNS), delimiter="\t", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)

    ground_truth = controls / "control_ground_truth.tsv"
    if ground_truth.exists():
        print(f"FAIL: {ground_truth} exists; identities must not be promoted", file=sys.stderr)
        return 1

    summary = {
        "control_identifiers": len(rows),
        "with_a_canonical_profile": sum(1 for row in rows if row["observed_asvs"] != UNKNOWN),
        "with_an_index_and_lane": sum(1 for row in rows if row["index"] != UNKNOWN),
        "multiqc_candidate_only_rows": sum(
            1 for row in rows if row["multiqc_join"].startswith("candidate only")
        ),
        "unknown_stage": sum(1 for row in rows if row["control_stage"] == UNKNOWN),
        "families": sorted({row["family"] for row in rows}),
        "promoted": 0,
        "ground_truth_table_present": False,
        "author_confirmations": {
            "file": author_confirmation_path.name,
            "sha256": sha256(author_confirmation_path),
            "records": len(author_confirmations),
            "status_counts": {
                status: sum(1 for row in author_confirmations if row["status"] == status)
                for status in sorted(allowed_confirmation_statuses)
            },
            "positive_control_composition_confirmed": False,
            "two_mock_community_compositions_pending": True,
        },
        "known_collisions": [
            "EB1-EB5 appear both in a July-era MultiQC run (M-25-0770 to "
            "M-25-0774) and in the Trip-5-era submission block EB1-EB18. "
            "One EB was included per extraction day and extraction days could "
            "include samples from multiple trips, so a single-trip assignment is "
            "not applicable. Sequence indices may adjudicate each library-label "
            "collision, but the extraction-day/batch and library-identity mappings "
            "remain pending",
            "Negative3 is absent from the submissions and the feature table "
            "with no recorded reason",
        ],
    }
    (controls / "preliminary_control_identity_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    # Compute product custody only after writing the summary. Otherwise a
    # changed summary would be hashed in its pre-run state and then overwritten.
    products = sorted(
        path
        for path in controls.iterdir()
        if path.is_file() and path.name not in {"SHA256SUMS", "README.md"}
    )
    summary["checksummed_products"] = [path.name for path in products]
    (controls / "preliminary_control_identity_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (controls / "SHA256SUMS").write_text(
        "".join(f"{sha256(path)}  {path.name}\n" for path in products), encoding="utf-8"
    )

    print(f"control identifiers: {len(rows)}")
    print(f"  with a canonical-table profile: {summary['with_a_canonical_profile']}")
    print(f"  with an index and lane: {summary['with_an_index_and_lane']}")
    print(f"  stage unknown: {summary['unknown_stage']}")
    print(f"outputs -> {controls}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
