#!/usr/bin/env python3
"""Describe exact-ASV overlap from positive controls into other libraries.

This is a cross-contamination diagnostic, not an index-hopping classifier.
Only ASVs assigned to an expected bacterial genus and represented by at least
five reads in a positive-control profile are traced.  Exact-ASV occurrence is
reported in negative controls, biological libraries, and the two numerically
nearest index identifiers in the same index family and lane.  Natural
occurrence of an expected genus, source-library mislabelling, and
cross-contamination cannot be separated by this overlap alone.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from pathlib import Path

import numpy as np
from biom import load_table


POSITIVE_PRODUCTS = {
    "e0553_Ctrl_2": ("Trip1", "D6322"),
    "e0554_Ctrl_3": ("Trip1", "D6322"),
    "e0872_TMC1": ("Trip2", "D6322"),
    "e0874_Positive": ("Trip2", "D6322"),
    "e8294_FPosCtrl1": ("Trip3", "D6300"),
    "e8661_FPosCtrl2": ("Trip3", "D6300"),
    "e8665_FPosCtrl3": ("Trip3", "D6300"),
}
EXPECTED_GENERA = {
    "D6322": {
        "Pseudomonas",
        "Escherichia",
        "Escherichia-Shigella",
        "Salmonella",
        "Enterococcus",
        "Staphylococcus",
        "Listeria",
        "Bacillus",
    },
    "D6300": {
        "Pseudomonas",
        "Escherichia",
        "Escherichia-Shigella",
        "Salmonella",
        "Lactobacillus",
        "Limosilactobacillus",
        "Enterococcus",
        "Staphylococcus",
        "Listeria",
        "Bacillus",
    },
}
INDEX_RE = re.compile(
    r"(?:(?P<short>UDP|SU)0*(?P<short_number>\d+)|"
    r"xGen-10nt-UDI-Index-Pair-(?P<xgen_number>\d+))"
)
LANE_RE = re.compile(r"_L(?P<lane>\d{3})_")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_tsv(
    path: Path, fieldnames: list[str], rows: list[dict[str, object]]
) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames,
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


def parse_index(path: str) -> tuple[str, int, str] | None:
    match = INDEX_RE.search(path)
    lane_match = LANE_RE.search(path)
    if match is None or lane_match is None:
        return None
    if match.group("short"):
        family = match.group("short")
        number = int(match.group("short_number"))
    else:
        family = "xGen-10nt-UDI-Index-Pair"
        number = int(match.group("xgen_number"))
    return family, number, lane_match.group("lane")


def genus(lineage: str) -> str:
    fields = lineage.split(";")
    return fields[5].strip() if len(fields) > 5 else ""


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--biom",
        type=Path,
        default=root
        / "data/metadata/samples/controls/source_snapshots/"
        "ibex_20250714_qiime2/extracted/feature-table.biom",
    )
    parser.add_argument(
        "--taxonomy",
        type=Path,
        default=root
        / "data/metadata/samples/controls/source_snapshots/"
        "ibex_20250714_qiime2/extracted/taxonomy.tsv",
    )
    parser.add_argument(
        "--samplesheet",
        type=Path,
        default=root
        / "data/metadata/samples/controls/source_snapshots/"
        "ibex_20250714_16s_samplesheet.tsv",
    )
    parser.add_argument(
        "--control-metadata",
        type=Path,
        default=root
        / "data/metadata/samples/controls/source_snapshots/"
        "ibex_20250714_qiime2/controls-metadata.tsv",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=root / "analysis/v3/control_audit",
    )
    parser.add_argument("--minimum-source-reads", type=int, default=5)
    args = parser.parse_args()
    inputs = [args.biom, args.taxonomy, args.samplesheet, args.control_metadata]
    missing = [str(path) for path in inputs if not path.is_file()]
    if missing:
        raise FileNotFoundError("missing required input(s): " + ", ".join(missing))
    args.output_dir.mkdir(parents=True, exist_ok=True)

    table = load_table(str(args.biom))
    observations = list(table.ids(axis="observation"))
    samples = list(table.ids(axis="sample"))
    sample_position = {sample: index for index, sample in enumerate(samples)}
    observation_position = {
        feature: index for index, feature in enumerate(observations)
    }
    totals = np.asarray(table.sum(axis="sample"), dtype=float)

    taxonomy_rows = read_tsv(args.taxonomy)
    id_field = list(taxonomy_rows[0])[0]
    taxonomy = {
        row[id_field]: row.get("Taxon", row[list(row)[1]])
        for row in taxonomy_rows
    }
    metadata = read_tsv(args.control_metadata)
    control_ids = {row["sampleID"] for row in metadata}
    control_ids.update(POSITIVE_PRODUCTS)
    negative_ids = sorted(
        (control_ids - set(POSITIVE_PRODUCTS)) & set(sample_position)
    )
    biological_ids = sorted(set(samples) - control_ids)
    negative_positions = np.asarray(
        [sample_position[sample] for sample in negative_ids], dtype=int
    )
    biological_positions = np.asarray(
        [sample_position[sample] for sample in biological_ids], dtype=int
    )

    samplesheet = {row["sampleID"]: row for row in read_tsv(args.samplesheet)}
    index_by_sample = {
        sample: parsed
        for sample, row in samplesheet.items()
        if (parsed := parse_index(row["forwardReads"])) is not None
    }
    neighbour_rows: list[dict[str, object]] = []
    neighbours: dict[str, list[str]] = {}
    for positive in POSITIVE_PRODUCTS:
        source_index = index_by_sample.get(positive)
        if source_index is None:
            neighbours[positive] = []
            continue
        family, number, lane = source_index
        candidates = [
            (abs(other_number - number), other_number, sample)
            for sample, (other_family, other_number, other_lane) in index_by_sample.items()
            if sample != positive
            and other_family == family
            and other_lane == lane
            and sample in sample_position
        ]
        selected = sorted(candidates)[:2]
        neighbours[positive] = [item[2] for item in selected]
        for distance, other_number, sample in selected:
            neighbour_rows.append(
                {
                    "positive_profile_id": positive,
                    "index_family": family,
                    "positive_index_number": number,
                    "lane": lane,
                    "neighbour_profile_id": sample,
                    "neighbour_index_number": other_number,
                    "absolute_numeric_index_distance": distance,
                    "neighbour_control_class": (
                        "positive"
                        if sample in POSITIVE_PRODUCTS
                        else "negative"
                        if sample in negative_ids
                        else "biological"
                    ),
                }
            )

    occurrence_rows: list[dict[str, object]] = []
    summary_rows: list[dict[str, object]] = []
    for positive, (trip, product) in POSITIVE_PRODUCTS.items():
        if positive not in sample_position:
            raise ValueError(f"positive control absent from BIOM table: {positive}")
        source_col = sample_position[positive]
        source_vector = np.asarray(
            table.data(positive, axis="sample", dense=True), dtype=float
        )
        source_total = float(totals[source_col])
        selected_features = []
        for feature, count in zip(observations, source_vector, strict=True):
            if count < args.minimum_source_reads:
                continue
            lineage = taxonomy.get(feature, "")
            if genus(lineage) in EXPECTED_GENERA[product]:
                selected_features.append((feature, lineage, int(count)))

        negative_profiles_seen: set[str] = set()
        biological_profiles_seen: set[str] = set()
        neighbour_profiles_seen: set[str] = set()
        features_in_negative = 0
        features_in_biological = 0
        features_in_neighbour = 0
        negative_reads_all = 0
        biological_reads_all = 0
        neighbour_reads_all = 0
        for feature, lineage, source_reads in selected_features:
            row_index = observation_position[feature]
            vector = np.asarray(
                table.data(feature, axis="observation", dense=True), dtype=float
            )
            negative_values = vector[negative_positions]
            biological_values = vector[biological_positions]
            neighbour_ids = neighbours[positive]
            neighbour_positions = np.asarray(
                [sample_position[sample] for sample in neighbour_ids], dtype=int
            )
            neighbour_values = (
                vector[neighbour_positions]
                if neighbour_positions.size
                else np.asarray([], dtype=float)
            )
            negative_present = [
                negative_ids[index]
                for index in np.flatnonzero(negative_values > 0)
            ]
            biological_present = [
                biological_ids[index]
                for index in np.flatnonzero(biological_values > 0)
            ]
            neighbour_present = [
                neighbour_ids[index]
                for index in np.flatnonzero(neighbour_values > 0)
            ]
            negative_profiles_seen.update(negative_present)
            biological_profiles_seen.update(biological_present)
            neighbour_profiles_seen.update(neighbour_present)
            features_in_negative += bool(negative_present)
            features_in_biological += bool(biological_present)
            features_in_neighbour += bool(neighbour_present)
            negative_reads = int(negative_values.sum())
            biological_reads = int(biological_values.sum())
            neighbour_reads = int(neighbour_values.sum())
            negative_reads_all += negative_reads
            biological_reads_all += biological_reads
            neighbour_reads_all += neighbour_reads
            negative_fraction_max = max(
                (
                    vector[sample_position[sample]]
                    / totals[sample_position[sample]]
                    for sample in negative_present
                    if totals[sample_position[sample]] > 0
                ),
                default=0.0,
            )
            biological_fraction_max = max(
                (
                    vector[sample_position[sample]]
                    / totals[sample_position[sample]]
                    for sample in biological_present
                    if totals[sample_position[sample]] > 0
                ),
                default=0.0,
            )
            neighbour_fraction_max = max(
                (
                    vector[sample_position[sample]]
                    / totals[sample_position[sample]]
                    for sample in neighbour_present
                    if totals[sample_position[sample]] > 0
                ),
                default=0.0,
            )
            occurrence_rows.append(
                {
                    "positive_profile_id": positive,
                    "trip": trip,
                    "product": product,
                    "feature_id": feature,
                    "taxonomy": lineage,
                    "source_reads": source_reads,
                    "source_read_fraction": (
                        f"{source_reads / source_total:.10g}" if source_total else ""
                    ),
                    "negative_profiles_present": len(negative_present),
                    "negative_profile_ids": ";".join(negative_present),
                    "negative_reads": negative_reads,
                    "maximum_negative_profile_fraction": f"{negative_fraction_max:.10g}",
                    "biological_profiles_present": len(biological_present),
                    "biological_reads": biological_reads,
                    "maximum_biological_profile_fraction": f"{biological_fraction_max:.10g}",
                    "nearest_index_profiles_present": len(neighbour_present),
                    "nearest_index_profile_ids": ";".join(neighbour_present),
                    "nearest_index_reads": neighbour_reads,
                    "maximum_nearest_index_profile_fraction": f"{neighbour_fraction_max:.10g}",
                    "interpretation": (
                        "exact_ASV_overlap_descriptive_only_not_proof_of_index_hopping"
                    ),
                }
            )
        summary_rows.append(
            {
                "positive_profile_id": positive,
                "trip": trip,
                "product": product,
                "source_reads": int(source_total),
                "expected_genus_asvs_traced": len(selected_features),
                "expected_genus_reads_in_source": sum(
                    source_reads for _, _, source_reads in selected_features
                ),
                "traced_asvs_detected_in_negative_controls": features_in_negative,
                "negative_control_profiles_with_traced_asv": len(
                    negative_profiles_seen
                ),
                "traced_asv_reads_in_negative_controls": negative_reads_all,
                "traced_asvs_detected_in_biological_profiles": features_in_biological,
                "biological_profiles_with_traced_asv": len(
                    biological_profiles_seen
                ),
                "traced_asv_reads_in_biological_profiles": biological_reads_all,
                "nearest_index_profiles": ";".join(neighbours[positive]),
                "traced_asvs_detected_in_nearest_indices": features_in_neighbour,
                "nearest_index_profiles_with_traced_asv": len(
                    neighbour_profiles_seen
                ),
                "traced_asv_reads_in_nearest_indices": neighbour_reads_all,
                "interpretation": (
                    "overlap_requires_library_identity_and_natural_occurrence_context"
                ),
            }
        )

    occurrence_fields = [
        "positive_profile_id",
        "trip",
        "product",
        "feature_id",
        "taxonomy",
        "source_reads",
        "source_read_fraction",
        "negative_profiles_present",
        "negative_profile_ids",
        "negative_reads",
        "maximum_negative_profile_fraction",
        "biological_profiles_present",
        "biological_reads",
        "maximum_biological_profile_fraction",
        "nearest_index_profiles_present",
        "nearest_index_profile_ids",
        "nearest_index_reads",
        "maximum_nearest_index_profile_fraction",
        "interpretation",
    ]
    write_tsv(
        args.output_dir / "positive_control_expected_asv_occurrences.tsv",
        occurrence_fields,
        occurrence_rows,
    )
    write_tsv(
        args.output_dir / "positive_control_spillover_summary.tsv",
        list(summary_rows[0]),
        summary_rows,
    )
    write_tsv(
        args.output_dir / "positive_control_index_neighbours.tsv",
        list(neighbour_rows[0]),
        neighbour_rows,
    )
    summary = {
        "method": (
            "exact ASVs assigned to an expected bacterial genus and represented "
            f"by at least {args.minimum_source_reads} reads in each positive profile"
        ),
        "positive_profiles": len(POSITIVE_PRODUCTS),
        "negative_profiles": len(negative_ids),
        "biological_profiles": len(biological_ids),
        "occurrence_rows": len(occurrence_rows),
        "interpretation_limit": (
            "Exact-ASV overlap does not distinguish natural occurrence, "
            "cross-contamination, index hopping, or a mislabelled source library."
        ),
        "input_sha256": {
            str(path.relative_to(root)): sha256(path) for path in inputs
        },
    }
    (args.output_dir / "positive_control_spillover_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
