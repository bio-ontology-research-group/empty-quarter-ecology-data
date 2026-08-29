#!/usr/bin/env python3
"""Render manuscript macros from frozen pH result tables."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tex_number(value: float, digits: int) -> str:
    return f"{float(value):.{digits}f}"


def tex_scientific(value: float, significant_digits: int = 3) -> str:
    coefficient, exponent = f"{float(value):.{significant_digits - 1}e}".split("e")
    return f"{coefficient}\\times10^{{{int(exponent)}}}"


def render(
    ph_dir: Path,
    output: Path,
    expected_dataset_version: str | None = None,
) -> None:
    project_root = Path(__file__).resolve().parents[2]
    summary = json.loads((ph_dir / "ecology/summary.json").read_text(encoding="utf-8"))
    ingest = json.loads((ph_dir / "summary.json").read_text(encoding="utf-8"))
    paired = pd.read_csv(
        ph_dir / "ecology/ph_paired_position_contrasts.tsv", sep="\t"
    ).set_index("comparison")
    composition = pd.read_csv(
        ph_dir / "ecology/ph_composition_models.tsv", sep="\t"
    ).set_index(["representation", "configuration"])
    geographic = pd.read_csv(
        ph_dir / "ecology/ph_geographic_adjustment.tsv", sep="\t"
    ).set_index("model")
    influence = pd.read_csv(
        ph_dir / "ecology/ph_influence_sensitivity.tsv", sep="\t"
    ).set_index("scenario")
    coverage = pd.read_csv(ph_dir / "ecology/ph_coverage.tsv", sep="\t")

    dataset_version = summary["dataset_version"]
    if expected_dataset_version and dataset_version != expected_dataset_version:
        raise ValueError("Refusing to render macros from a different pH dataset version")
    if summary["status"] != "FROZEN_ECOLOGY_ANALYSIS":
        raise ValueError("Refusing to render macros from a non-frozen analysis")

    alpha = summary["alpha_primary"]
    ph_dist = summary["ph_distribution_group_means"]
    geo_without = geographic.loc["same_cohort_without_ph_adjustment"]
    geo_with = geographic.loc["same_cohort_with_ph_adjustment"]
    ph_spatial = geographic.loc["ph_transect_pattern_after_campaign_position"]
    exclude_maximum = influence.loc["exclude_singleton_maximum_group"]
    exclude_maximum_site = influence.loc["exclude_maximum_site"]
    bray80 = composition.loc[("Bray-Curtis PCoA", "retain_80pct")]
    bray95 = composition.loc[("Bray-Curtis PCoA", "retain_95pct")]
    clr = composition.loc["Aitchison CLR"]
    primary_clr = clr.loc["top_200_pseudocount_0.5"]
    trip_groups = coverage.groupby("trip")["site_campaign_position_groups"].sum()
    dispositions = ingest["counts"]["dispositions"]

    values = {
        "PHDatasetVersion": dataset_version,
        "PHSourceSHA": summary["source_workbook_sha256"],
        "PHSourceRows": ingest["counts"]["source_rows"],
        "PHDeclaredRows": sum(
            row["declared_target_samples"] for row in ingest["per_trip"].values()
        ),
        "PHAdmitted": ingest["counts"]["admitted_rows"],
        "PHPending": dispositions.get("PENDING_MEASUREMENT", 0),
        "PHDepleted": dispositions.get("NOT_MEASURED_DEPLETED", 0),
        "PHDateQuarantine": dispositions.get("QUARANTINED_DATE", 0),
        "PHColumnQuarantine": dispositions.get(
            "QUARANTINED_COLUMN_SHIFT_CANDIDATE", 0
        ),
        "PHQCQuarantine": dispositions.get("QUARANTINED_QC", 0),
        "PHTotalQuarantine": sum(
            value
            for key, value in dispositions.items()
            if key.startswith("QUARANTINED")
        ),
        "PHMeasurementSessions": ingest["counts"]["sessions"],
        "PHMatchedSpecimens": summary["counts"]["accepted_specimens_with_ecology_profile"],
        "PHAlphaGroups": summary["counts"]["site_campaign_position_groups"],
        "PHCompositionGroups": summary["counts"]["composition_groups"],
        "PHTripOneGroups": int(trip_groups.loc[1]),
        "PHTripTwoGroups": int(trip_groups.loc[2]),
        "PHTripThreeGroups": int(trip_groups.loc[3]),
        "PHTripFourGroups": int(trip_groups.loc[4]),
        "PHTripFiveGroups": int(trip_groups.loc[5]),
        "PHMinimum": tex_number(ph_dist["min"], 2),
        "PHMaximum": tex_number(ph_dist["max"], 2),
        "PHMean": tex_number(ph_dist["mean"], 3),
        "PHSD": tex_number(ph_dist["sd"], 3),
        "PHAlphaEstimate": tex_number(alpha["estimate_per_ph_unit"], 3),
        "PHAlphaCILow": tex_number(alpha["ci_low"], 3),
        "PHAlphaCIHigh": tex_number(alpha["ci_high"], 3),
        "PHAlphaP": tex_number(alpha["p"], 3),
        "PHDeepSurfaceDifference": tex_number(
            paired.loc["Deep-Surface", "mean_difference_ph_units"], 3
        ),
        "PHDeepSurfaceSites": int(paired.loc["Deep-Surface", "n_sites"]),
        "PHDeepSurfaceNonzeroSites": int(
            paired.loc["Deep-Surface", "n_nonzero_sites"]
        ),
        "PHDeepSurfaceQ": tex_number(
            paired.loc["Deep-Surface", "q_bh_three_position_contrasts"], 3
        ),
        "PHRootSurfaceDifference": tex_number(
            paired.loc["Rhizosphere-Surface", "mean_difference_ph_units"], 3
        ),
        "PHRootSurfaceSites": int(
            paired.loc["Rhizosphere-Surface", "n_sites"]
        ),
        "PHRootSurfaceNonzeroSites": int(
            paired.loc["Rhizosphere-Surface", "n_nonzero_sites"]
        ),
        "PHRootSurfaceQ": tex_number(
            paired.loc["Rhizosphere-Surface", "q_bh_three_position_contrasts"], 6
        ),
        "PHRootDeepDifference": tex_number(
            paired.loc["Rhizosphere-Deep", "mean_difference_ph_units"], 3
        ),
        "PHRootDeepSites": int(paired.loc["Rhizosphere-Deep", "n_sites"]),
        "PHRootDeepNonzeroSites": int(
            paired.loc["Rhizosphere-Deep", "n_nonzero_sites"]
        ),
        "PHRootDeepQ": tex_scientific(
            paired.loc[
                "Rhizosphere-Deep", "q_bh_three_position_contrasts"
            ]
        ),
        "PHBrayEightyRtwo": tex_number(bray80["partial_r2"], 5),
        "PHBrayEightyP": tex_number(bray80["p"], 3),
        "PHBrayNinetyFiveRtwo": tex_number(bray95["partial_r2"], 5),
        "PHBrayNinetyFiveP": tex_number(bray95["p"], 3),
        "PHCLRMinimumRtwo": tex_number(clr["partial_r2"].min(), 5),
        "PHCLRMaximumRtwo": tex_number(clr["partial_r2"].max(), 5),
        "PHCLRMinimumP": tex_number(clr["p"].min(), 3),
        "PHCLRMaximumP": tex_number(clr["p"].max(), 3),
        "PHPrimaryCLRRtwo": tex_number(primary_clr["partial_r2"], 5),
        "PHPrimaryCLRP": tex_number(primary_clr["p"], 3),
        "PHGeographyBeforeRtwo": tex_number(geo_without["partial_r2"], 3),
        "PHGeographyAfterRtwo": tex_number(geo_with["partial_r2"], 3),
        "PHGeographyP": tex_number(geo_with["p"], 3),
        "PHGeographySites": int(geo_with["n_sites"]),
        "PHGeographyResidualDf": int(geo_with["residual_df"]),
        "PHGeographyAttenuation": tex_number(
            100 * (geo_without["partial_r2"] - geo_with["partial_r2"])
            / geo_without["partial_r2"],
            1,
        ),
        "PHSpatialRtwo": tex_number(ph_spatial["partial_r2"], 3),
        "PHSpatialP": tex_number(ph_spatial["p"], 3),
        "PHMaximumGroupTrip": int(exclude_maximum["excluded_trip"]),
        "PHMaximumGroupSite": int(exclude_maximum["excluded_site"]),
        "PHMaximumGroupPosition": exclude_maximum["excluded_compartment"],
        "PHMaximumGroupSpecimens": int(
            exclude_maximum["excluded_group_n_ph_specimens"]
        ),
        "PHExcludeMaximumSpatialRtwo": tex_number(
            exclude_maximum["ph_transect_partial_r2"], 3
        ),
        "PHExcludeMaximumSpatialP": tex_number(
            exclude_maximum["ph_transect_p"], 3
        ),
        "PHExcludeMaximumGeographyRtwo": tex_number(
            exclude_maximum["geography_after_partial_r2"], 3
        ),
        "PHExcludeMaximumSiteSpatialRtwo": tex_number(
            exclude_maximum_site["ph_transect_partial_r2"], 3
        ),
        "PHExcludeMaximumSiteGeographyRtwo": tex_number(
            exclude_maximum_site["geography_after_partial_r2"], 3
        ),
        "PHCompleteTripSiteBlocks": summary["paired_position_omnibus"][
            "complete_three_position_site_campaign_blocks"
        ],
        "PHCompleteSites": summary["paired_position_omnibus"][
            "complete_three_position_sites"
        ],
        "PHFriedmanChiSquare": tex_number(
            summary["paired_position_omnibus"]["friedman_chi_square"], 3
        ),
        "PHFriedmanP": tex_scientific(
            summary["paired_position_omnibus"]["friedman_p"]
        ),
    }

    lines = [
        "% Generated by scripts/analysis/render_ph_ecology_tex.py.",
        "% Do not edit values by hand.",
    ]
    lines.extend(f"\\newcommand{{\\{name}}}{{{value}}}" for name, value in values.items())
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")

    input_paths = [
        ph_dir / "summary.json",
        ph_dir / "ecology/summary.json",
        ph_dir / "ecology/ph_paired_position_contrasts.tsv",
        ph_dir / "ecology/ph_composition_models.tsv",
        ph_dir / "ecology/ph_geographic_adjustment.tsv",
        ph_dir / "ecology/ph_influence_sensitivity.tsv",
        ph_dir / "ecology/ph_coverage.tsv",
        Path(__file__).resolve(),
    ]
    def input_label(path: Path) -> str:
        return (
            str(path.relative_to(project_root))
            if path.is_relative_to(project_root)
            else path.name
        )

    manifest = {
        "dataset_version": dataset_version,
        "status": "GENERATED_FROM_FROZEN_ANALYSIS",
        "inputs": [
            {
                "path": input_label(path),
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
            }
            for path in input_paths
        ],
        "output": {
            "path": f"generated/{output.name}",
            "sha256": sha256_file(output),
            "bytes": output.stat().st_size,
        },
    }
    manifest_path = output.with_suffix(".manifest.json")
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ph-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-dataset-version")
    args = parser.parse_args()
    render(
        args.ph_dir.resolve(),
        args.output.resolve(),
        args.expected_dataset_version,
    )


if __name__ == "__main__":
    main()
