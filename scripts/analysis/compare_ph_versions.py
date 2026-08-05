#!/usr/bin/env python3
"""Compare the frozen ecology pH view with a successor pH version."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


ECOLOGY_VERSION = "EQ-PH-ECOLOGY-v1.0.0"
ECOLOGY_SOURCE_SHA256 = (
    "0986fdde4af4635252ead8f601e8725749228c0adf4f906e08b364801ab08398"
)


def load_version(directory: Path) -> tuple[dict, pd.DataFrame]:
    summary = json.loads((directory / "summary.json").read_text(encoding="utf-8"))
    accepted = pd.read_csv(
        directory / "normalized/ph_accepted_measurements.tsv", sep="\t"
    )
    registry = pd.read_csv(
        directory / "normalized/ph_entity_registry.tsv", sep="\t"
    )
    values = registry[registry["entity_role"] == "value"][
        ["entity_iri", "sample_id"]
    ]
    if values["sample_id"].duplicated().any():
        raise ValueError(f"Duplicate value IRIs by sample in {directory}")
    accepted = accepted.merge(values, on="sample_id", how="left", validate="one_to_one")
    if accepted["entity_iri"].isna().any():
        raise ValueError(f"Accepted row without value IRI in {directory}")
    return summary, accepted


def compare(ecology_dir: Path, successor_dir: Path, output_dir: Path) -> dict:
    ecology_summary, ecology = load_version(ecology_dir)
    successor_summary, successor = load_version(successor_dir)
    if ecology_summary["dataset_version"] != ECOLOGY_VERSION:
        raise ValueError("The reference directory is not the frozen ecology version")
    if ecology_summary["source"]["sha256"] != ECOLOGY_SOURCE_SHA256:
        raise ValueError("The frozen ecology source hash has changed")
    if successor_summary["dataset_purpose"] not in {
        "data-paper",
        "shared-manuscripts",
    }:
        raise ValueError(
            "The successor must be generated for the data paper or both manuscripts"
        )
    if successor_summary["dataset_version"] == ECOLOGY_VERSION:
        raise ValueError("The successor must have a new dataset version")

    fields = [
        "entity_iri",
        "sample_id",
        "trip",
        "site",
        "compartment",
        "measurement_date",
        "ph_value",
        "slope_percent",
        "ph10_check",
    ]
    merged = ecology[fields].merge(
        successor[fields],
        on="entity_iri",
        how="outer",
        suffixes=("_ecology", "_successor"),
        indicator=True,
        validate="one_to_one",
    )
    merged["disposition"] = np.select(
        [merged["_merge"] == "left_only", merged["_merge"] == "right_only"],
        ["ABSENT_FROM_SUCCESSOR", "ADDED_IN_SUCCESSOR"],
        default="SHARED_PENDING_COMPARISON",
    )
    shared = merged["_merge"] == "both"
    value_equal = np.isclose(
        merged["ph_value_ecology"],
        merged["ph_value_successor"],
        rtol=0,
        atol=1e-12,
        equal_nan=True,
    )
    text_metadata_fields = [
        "sample_id",
        "compartment",
        "measurement_date",
    ]
    metadata_equal = np.ones(len(merged), dtype=bool)
    for field in text_metadata_fields:
        left = merged[f"{field}_ecology"].fillna("<NA>").astype(str)
        right = merged[f"{field}_successor"].fillna("<NA>").astype(str)
        metadata_equal &= left.eq(right).to_numpy()
    for field in ("trip", "site", "slope_percent", "ph10_check"):
        metadata_equal &= np.isclose(
            merged[f"{field}_ecology"],
            merged[f"{field}_successor"],
            rtol=0,
            atol=1e-12,
            equal_nan=True,
        )
    merged.loc[shared & value_equal & metadata_equal, "disposition"] = "UNCHANGED"
    merged.loc[shared & ~value_equal, "disposition"] = "REVISED_VALUE"
    merged.loc[shared & value_equal & ~metadata_equal, "disposition"] = (
        "REVISED_METADATA"
    )
    merged = merged.drop(columns="_merge").sort_values(
        ["disposition", "trip_successor", "site_successor", "sample_id_successor"],
        na_position="last",
    )

    counts = merged["disposition"].value_counts().sort_index().to_dict()
    report = {
        "ecology_dataset_version": ECOLOGY_VERSION,
        "successor_dataset_version": successor_summary["dataset_version"],
        "successor_dataset_purpose": successor_summary["dataset_purpose"],
        "ecology_source_sha256_verified": True,
        "counts": {key: int(value) for key, value in counts.items()},
        "material_review_required": bool(
            counts.get("REVISED_VALUE", 0)
            or counts.get("REVISED_METADATA", 0)
            or counts.get("ABSENT_FROM_SUCCESSOR", 0)
        ),
        "policy": (
            "Any revision or absence in the successor requires explicit author "
            "review. A frozen shared-manuscripts successor replaces the "
            "predecessor in both current manuscripts while retaining the "
            "predecessor as immutable provenance."
        ),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    merged.to_csv(output_dir / "measurement_version_comparison.tsv", sep="\t", index=False)
    (output_dir / "summary.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ecology-dir", type=Path, required=True)
    parser.add_argument("--successor-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    report = compare(
        args.ecology_dir.resolve(),
        args.successor_dir.resolve(),
        args.output_dir.resolve(),
    )
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
