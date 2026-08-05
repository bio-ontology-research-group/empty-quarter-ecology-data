#!/usr/bin/env python3
"""Prevalence-based contaminant screen on the canonical feature table.

The QIIME 2 contaminant path (``analysis/scripts/2_control_filtering.sh``) runs
on an older branch whose output has 531 or 975 sample columns.  The canonical
Trips 1-5 table has 1,271 profiles, still carries the 24 negative-control
profiles, and has never been screened.  This script supplies the missing screen
directly on the canonical TSV, so no QIIME 2 installation is required and the
result is attributable to the table the manuscripts actually use.

Method: the prevalence test of the decontam package.  For each feature, a
two-by-two table of presence and absence in control versus biological profiles
is tested with Fisher's exact test, one-sided for enrichment in controls.  A
feature whose score falls below the threshold is called a contaminant.  Low
scores mean "more prevalent in controls than expected", which is the same
orientation as decontam's ``p`` score and as the ``p >= threshold`` retention
rule in the QIIME 2 script.

The screen is fail-closed: an absent input, an empty control set or an empty
biological set aborts the run.  Batch stratification is performed over whichever
grouping fields are resolvable from the profile identifiers, and the script
states explicitly which controls could not be assigned to a batch rather than
assigning them by guesswork.

Outputs (default ``analysis/v3/contaminant_screen/``):

* ``feature_scores.tsv`` - per-feature prevalence, score and call
* ``removal_fraction_by_sample.tsv`` - reads and features removed per profile
* ``removal_fraction_by_group.tsv`` - the same aggregated by campaign and compartment
* ``control_prevalent_features.tsv`` - the called contaminants, most prevalent first
* ``summary.json`` - parameters, counts, checksums and stated limitations

No result here is a claim about which taxa are truly contaminants. Author
confirmation establishes that the EB and numbered ``Negative`` profiles are
extraction blanks. One EB was included per extraction day, and an extraction
day could include samples from several trips, so assigning an EB to one
campaign would be scientifically wrong. Exact extraction-day/batch membership,
PCR-blank identifiers, two mock-community compositions and their trip
assignments remain unresolved (see ``revision/controls/``). This therefore
remains a screen with uncalibrated sensitivity.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from pathlib import Path

import numpy as np
from scipy.stats import fisher_exact

CONTROL_COLUMN = re.compile(r"^(EB\d+|Negative\d*|T_Neg\w*|.*[Cc]trl.*|.*[Cc]ontrol.*|.*[Zz]ymo.*)$")
PROFILE_ID = re.compile(r"^(?:e\d+_)?(?P<body>.+)$")
COMPARTMENT = re.compile(r"(?P<compartment>Dr|Sr|PRr)\d*$")
CAMPAIGN_PREFIX = {"T": "Trip2", "F": "Trip3", "S": "Trip4", "V": "Trip5"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def profile_body(column: str) -> str:
    match = PROFILE_ID.match(column)
    return match.group("body") if match else column


def campaign_of(column: str) -> str:
    body = profile_body(column)
    first = body[:1]
    if first in CAMPAIGN_PREFIX:
        return CAMPAIGN_PREFIX[first]
    if body[:1].isdigit():
        return "Trip1"
    return "unassigned"


def compartment_of(column: str) -> str:
    match = COMPARTMENT.search(profile_body(column))
    if not match:
        return "unassigned"
    return {"Dr": "deep", "Sr": "surface", "PRr": "root-adjacent"}[match.group("compartment")]


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--table",
        type=Path,
        default=root / "data/processed/taxonomy/taxon-tables/feature-table-trips1-5.tsv",
    )
    parser.add_argument("--output-dir", type=Path, default=root / "analysis/v3/contaminant_screen")
    parser.add_argument("--threshold", type=float, default=0.1)
    parser.add_argument(
        "--max-features",
        type=int,
        default=0,
        help="0 scores every feature; a positive value truncates for a smoke run",
    )
    args = parser.parse_args()

    if not args.table.is_file():
        print(f"FAIL: canonical feature table is absent: {args.table}", file=sys.stderr)
        return 1

    with args.table.open(encoding="utf-8") as handle:
        first = handle.readline()
        if not first.startswith("#"):
            print("FAIL: expected a biom provenance comment on line 1", file=sys.stderr)
            return 1
        header = handle.readline().rstrip("\n").split("\t")
        columns = header[1:]
        control_index = [i for i, name in enumerate(columns) if CONTROL_COLUMN.match(profile_body(name))]
        sample_index = [i for i in range(len(columns)) if i not in set(control_index)]
        if not control_index:
            print("FAIL: no control profiles identified in the table header", file=sys.stderr)
            return 1
        if not sample_index:
            print("FAIL: no biological profiles identified in the table header", file=sys.stderr)
            return 1

        n_control = len(control_index)
        n_sample = len(sample_index)
        feature_ids: list[str] = []
        control_presence: list[int] = []
        sample_presence: list[int] = []
        control_total: list[float] = []
        sample_total: list[float] = []

        # Pass 1: prevalence and per-role totals only. The full matrix is never
        # held in memory; the canonical table is 1.8 GB with 351k features.
        for line in handle:
            fields = line.rstrip("\n").split("\t")
            values = np.array(fields[1:], dtype=np.float64)
            present = values > 0
            feature_ids.append(fields[0])
            control_presence.append(int(present[control_index].sum()))
            sample_presence.append(int(present[sample_index].sum()))
            control_total.append(float(values[control_index].sum()))
            sample_total.append(float(values[sample_index].sum()))
            if args.max_features and len(feature_ids) >= args.max_features:
                break

    scores = np.ones(len(feature_ids), dtype=np.float64)
    for index in range(len(feature_ids)):
        a = control_presence[index]
        b = n_control - a
        c = sample_presence[index]
        d = n_sample - c
        if a == 0:
            continue
        _, p = fisher_exact([[a, b], [c, d]], alternative="greater")
        scores[index] = p

    called = scores < args.threshold
    called_ids = {feature_ids[index] for index in np.flatnonzero(called)}

    # Pass 2: per-profile totals and the reads carried by called features.
    per_sample_reads = np.zeros(len(columns), dtype=np.float64)
    per_sample_features = np.zeros(len(columns), dtype=np.int64)
    removed_reads = np.zeros(len(columns), dtype=np.float64)
    removed_features = np.zeros(len(columns), dtype=np.int64)
    with args.table.open(encoding="utf-8") as handle:
        handle.readline()
        handle.readline()
        seen = 0
        for line in handle:
            fields = line.rstrip("\n").split("\t")
            values = np.array(fields[1:], dtype=np.float64)
            present = values > 0
            per_sample_reads += values
            per_sample_features += present
            if fields[0] in called_ids:
                removed_reads += values
                removed_features += present
            seen += 1
            if args.max_features and seen >= args.max_features:
                break

    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)

    with (out / "feature_scores.tsv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(
            [
                "feature_id",
                "control_profiles_present",
                "control_profiles_total",
                "biological_profiles_present",
                "biological_profiles_total",
                "control_reads",
                "biological_reads",
                "prevalence_score",
                "call",
            ]
        )
        for index, feature in enumerate(feature_ids):
            writer.writerow(
                [
                    feature,
                    control_presence[index],
                    n_control,
                    sample_presence[index],
                    n_sample,
                    f"{control_total[index]:.0f}",
                    f"{sample_total[index]:.0f}",
                    f"{scores[index]:.6g}",
                    "contaminant" if called[index] else "retained",
                ]
            )

    order = np.argsort(scores)
    with (out / "control_prevalent_features.tsv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(
            ["feature_id", "control_profiles_present", "biological_profiles_present", "prevalence_score"]
        )
        for index in order:
            if not called[index]:
                break
            writer.writerow(
                [feature_ids[index], control_presence[index], sample_presence[index], f"{scores[index]:.6g}"]
            )

    sample_rows = []
    for position, column in enumerate(columns):
        total = per_sample_reads[position]
        sample_rows.append(
            {
                "profile": column,
                "role": "control" if position in set(control_index) else "biological",
                "campaign": campaign_of(column),
                "compartment": compartment_of(column),
                "total_reads": f"{total:.0f}",
                "removed_reads": f"{removed_reads[position]:.0f}",
                "removed_read_fraction": f"{(removed_reads[position] / total):.6f}" if total else "",
                "total_features": int(per_sample_features[position]),
                "removed_features": int(removed_features[position]),
            }
        )
    with (out / "removal_fraction_by_sample.tsv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(sample_rows[0]), delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(sample_rows)

    groups: dict[tuple[str, str, str], list[float]] = {}
    for row in sample_rows:
        key = (row["role"], row["campaign"], row["compartment"])
        groups.setdefault(key, []).append(
            float(row["removed_read_fraction"]) if row["removed_read_fraction"] else 0.0
        )
    with (out / "removal_fraction_by_group.tsv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(["role", "campaign", "compartment", "profiles", "mean_removed_read_fraction", "max"])
        for key in sorted(groups):
            values = groups[key]
            writer.writerow(
                [*key, len(values), f"{float(np.mean(values)):.6f}", f"{float(np.max(values)):.6f}"]
            )

    summary = {
        "table": str(args.table.resolve().relative_to(root)),
        "table_sha256": sha256(args.table),
        "method": "decontam prevalence (Fisher exact, one-sided for control enrichment)",
        "threshold": args.threshold,
        "features_scored": len(feature_ids),
        "features_called_contaminant": int(called.sum()),
        "control_profiles": n_control,
        "biological_profiles": n_sample,
        "control_profile_names": [columns[i] for i in control_index],
        "total_reads": float(per_sample_reads.sum()),
        "removed_reads": float(removed_reads.sum()),
        "removed_read_fraction_overall": float(removed_reads.sum() / per_sample_reads.sum()),
        "batch_stratification": {
            "available_fields": ["campaign (from identifier prefix)", "compartment (from identifier suffix)"],
            "controls_assignable_to_a_campaign": sum(
                1 for i in control_index if campaign_of(columns[i]) != "unassigned"
            ),
            "limitation": (
                "Extraction, plate and sequencing-run batch identifiers are not "
                "present in any local artifact. One EB was included per extraction "
                "day, and an extraction day could include samples from multiple "
                "trips, so assigning an EB to one campaign would be scientifically "
                "wrong. A batch-stratified screen in the strict sense could not be "
                "run. Stratification is reported over campaign and compartment for "
                "the biological profiles only."
            ),
        },
        "interpretation_limit": (
            "Author confirmation identifies the EB and numbered Negative profiles "
            "in this table as extraction blanks. One EB was included per extraction "
            "day, which could contain samples from multiple trips, so an EB campaign "
            "assignment is not applicable. Exact extraction-day/batch membership, "
            "PCR-blank identifiers, and the two mock-community compositions and trip "
            "assignments remain unresolved "
            "(revision/controls/author_control_confirmation_20260729.tsv). "
            "Positive controls are absent from this table, so the screen has no "
            "recovery check and its sensitivity remains uncalibrated."
        ),
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(
        f"scored {len(feature_ids)} features; {int(called.sum())} called contaminant "
        f"at p < {args.threshold}"
    )
    print(
        f"overall removed read fraction: {summary['removed_read_fraction_overall']:.6f} "
        f"({n_control} control profiles, {n_sample} biological profiles)"
    )
    print(f"outputs -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
