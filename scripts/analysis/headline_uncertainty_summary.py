#!/usr/bin/env python3
"""Collect headline estimates and their explicitly typed uncertainty.

The table produced here is a reporting aid.  It keeps sampling intervals,
peak-selection intervals, model-sensitivity ranges and descriptive spreads
separate because they answer different questions and are not interchangeable.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


SCHEMA_VERSION = "1.0"
ANALYSIS_DATE = "2026-08-05"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def one(frame: pd.DataFrame, **conditions: Any) -> pd.Series:
    selected = frame
    for column, value in conditions.items():
        if value is None:
            selected = selected[selected[column].isna()]
        else:
            selected = selected[selected[column].eq(value)]
    if len(selected) != 1:
        raise ValueError(
            f"Expected one result for {conditions}; found {len(selected)}"
        )
    return selected.iloc[0]


def result_row(
    section: str,
    estimand: str,
    estimate: float,
    low: float,
    high: float,
    interval_label: str,
    uncertainty_type: str,
    method: str,
    independent_unit: str,
    n_units: int | str,
    source: str,
) -> dict[str, Any]:
    values = np.asarray([estimate, low, high], dtype=float)
    if np.any(~np.isfinite(values)):
        raise ValueError(f"Non-finite estimate or interval for {estimand}")
    if low > high:
        raise ValueError(f"Reversed interval for {estimand}")
    if not low - 1e-12 <= estimate <= high + 1e-12:
        raise ValueError(f"Interval does not contain estimate for {estimand}")
    return {
        "section": section,
        "estimand": estimand,
        "estimate": float(estimate),
        "interval_low": float(low),
        "interval_high": float(high),
        "interval_label": interval_label,
        "uncertainty_type": uncertainty_type,
        "method": method,
        "independent_unit": independent_unit,
        "n_units": n_units,
        "source": source,
    }


def collect(root: Path) -> tuple[pd.DataFrame, list[Path]]:
    rows: list[dict[str, Any]] = []
    inputs: list[Path] = []

    def table(relative: str) -> pd.DataFrame:
        path = root / relative
        inputs.append(path)
        return pd.read_csv(path, sep="\t")

    spatial_path = "analysis/v3/spatial_turnover_rescue/results/spatial_model_results.tsv"
    spatial = table(spatial_path)
    value = one(
        spatial,
        analysis="primary",
        omitted_campaign=None,
        taxon_count=200,
        trend_degree=2,
    )
    rows.append(result_row(
        "Geography", "Quadratic transect partial R2", value.partial_r2,
        value.partial_r2_ci_low, value.partial_r2_ci_high,
        "95% confidence interval", "sampling uncertainty",
        "delete-one-site jackknife with t critical value", "sampling site",
        int(value.n_sites), spatial_path,
    ))

    distance_path = "analysis/v3/distance_decay_turnover/distance_decay_slopes.tsv"
    distance = table(distance_path)
    for compartment in ("Surface", "Deep", "Rhizosphere"):
        value = one(distance, family="aitchison", response=compartment)
        rows.append(result_row(
            "Geography", f"Aitchison distance-decay slope, {compartment}, per 100 km",
            value.slope_per_100km, value.jackknife_ci_low_per_100km,
            value.jackknife_ci_high_per_100km, "95% confidence interval",
            "sampling uncertainty", "delete-one-site jackknife with t critical value",
            "sampling site", 60, distance_path,
        ))

    turnover_path = (
        "analysis/v3/distance_decay_turnover/turnover_nestedness_components.tsv"
    )
    turnover = table(turnover_path)
    for compartment in ("Surface", "Deep", "Rhizosphere"):
        value = one(turnover, compartment=compartment)
        rows.append(result_row(
            "Geography", f"Replacement share of Sorensen dissimilarity, {compartment}",
            value.turnover_share_of_sorensen, value.turnover_share_ci_low,
            value.turnover_share_ci_high, "95% confidence interval",
            "sampling uncertainty", "delete-one-site jackknife with t critical value",
            "sampling site", int(value.n_sites), turnover_path,
        ))

    composition_path = (
        "analysis/v3/compartment_composition/compartment_location_results.tsv"
    )
    composition = table(composition_path)
    for contrast in ("Deep-Surface", "Rhizosphere-Surface", "Rhizosphere-Deep"):
        value = one(
            composition, analysis="primary", omitted_campaign=None,
            contrast=contrast, taxon_count=200, zero_treatment="pseudocount_0.5",
        )
        rows.append(result_row(
            "Soil position", f"Standardized compositional displacement, {contrast}",
            value.standardized_displacement,
            value.standardized_displacement_ci_low,
            value.standardized_displacement_ci_high,
            "95% percentile bootstrap interval", "sampling uncertainty",
            "paired whole-site bootstrap", "sampling site", int(value.n_sites),
            composition_path,
        ))

    paired_path = "analysis/v3/results/paired_compartment_effects.tsv"
    paired = table(paired_path)
    for contrast in ("Deep-Surface", "Rhizosphere-Surface", "Rhizosphere-Deep"):
        value = one(paired, trip="all", metric="shannon", comparison=contrast)
        rows.append(result_row(
            "Soil position", f"Mean paired Shannon difference, {contrast}",
            value.mean_difference, value.ci_low, value.ci_high,
            "95% percentile bootstrap interval", "sampling uncertainty",
            "paired whole-site bootstrap", "sampling site", int(value.n_sites),
            paired_path,
        ))

    evenness_path = "analysis/v3/evenness_decomposition/paired_contrasts.tsv"
    evenness = table(evenness_path)
    for contrast in ("Deep-Surface", "Rhizosphere-Surface", "Rhizosphere-Deep"):
        value = one(
            evenness, metric="evenness_h_over_log_hurlbert", contrast=contrast
        )
        rows.append(result_row(
            "Soil position", f"Mean paired normalized-evenness difference, {contrast}",
            value.mean_difference, value.bootstrap_ci_low,
            value.bootstrap_ci_high, "95% percentile bootstrap interval",
            "sampling uncertainty", "paired whole-site bootstrap", "sampling site",
            int(value.n_sites), evenness_path,
        ))

    climate_path = (
        "analysis/v3/environment_associations/climate_alpha_correlations.tsv"
    )
    climate = table(climate_path)
    for value in climate.itertuples(index=False):
        climate_name = {
            "mean_air_temperature_c": "temperature",
            "mean_monthly_rain_mm": "long-term monthly rain",
            "mean_relative_humidity_pct": "relative humidity",
        }[value.climate_variable]
        rows.append(result_row(
            "Climate", f"Spearman rho, {climate_name} vs {value.response_label}",
            value.spearman_rho, value.bootstrap_ci_low, value.bootstrap_ci_high,
            "95% percentile bootstrap interval", "sampling uncertainty",
            "paired whole-site bootstrap", "sampling site", int(value.n_sites),
            climate_path,
        ))

    ph_path = "analysis/v3/ph_shared_v1/ecology/ph_influence_sensitivity.tsv"
    ph = table(ph_path)
    baseline = one(ph, scenario="baseline")
    for column, label in (
        ("geography_before_partial_r2", "Geographic partial R2 before pH adjustment"),
        ("geography_after_partial_r2", "Geographic partial R2 after pH adjustment"),
        ("ph_transect_partial_r2", "pH transect partial R2"),
    ):
        rows.append(result_row(
            "pH and elements", label, baseline[column], ph[column].min(),
            ph[column].max(), "prespecified influence range",
            "case-influence sensitivity, not a confidence interval",
            "baseline, maximum-pH group excluded, and its whole site excluded",
            "pH-linked group or sampling site", int(baseline.n_sites), ph_path,
        ))

    xrf_path = "analysis/v3/xrf_community_clr/clr_elemental_axis_models.tsv"
    xrf = table(xrf_path)
    xrf_primary = one(xrf, analysis="primary")
    rows.append(result_row(
        "pH and elements", "Elemental-axis partial R2 for bacterial composition",
        xrf_primary.partial_r2, xrf.partial_r2.min(), xrf.partial_r2.max(),
        "prespecified model-sensitivity range",
        "model sensitivity, not a confidence interval",
        "taxon-set, zero-treatment and standardisation sensitivity",
        "sampling site", int(xrf_primary.n_sites), xrf_path,
    ))

    rain_suite_path = "analysis/v3/rain_pulse_sensitivities/summary.tsv"
    rain = table(rain_suite_path)
    for run_id, product in (
        ("primary_nasa_power", "NASA POWER"),
        ("open_meteo_product", "Open-Meteo"),
    ):
        value = one(rain, run_id=run_id)
        rows.append(result_row(
            "Recent rain", f"Expected-richness change per mm at fitted peak, {product}",
            value.estimate_per_mm_at_peak, value.site_clustered_ci_low,
            value.site_clustered_ci_high, "95% confidence interval",
            "effect-size sampling uncertainty conditional on selected curve",
            "site-clustered sandwich covariance", "sampling site", int(value.n_sites),
            rain_suite_path,
        ))
        rows.append(result_row(
            "Recent rain", f"Partial R2 at fitted peak, {product}", value.partial_r2,
            value.site_bootstrap_partial_r2_ci_low,
            value.site_bootstrap_partial_r2_ci_high,
            "95% percentile bootstrap interval", "sampling uncertainty",
            "whole-site bootstrap at the fitted peak", "sampling site",
            int(value.n_sites), rain_suite_path,
        ))
        rows.append(result_row(
            "Recent rain", f"Selected richness peak time in complete days, {product}",
            value.selected_peak_complete_days, value.site_bootstrap_peak_ci_low,
            value.site_bootstrap_peak_ci_high,
            "95% percentile peak-selection interval", "timing-selection uncertainty",
            "whole-site bootstrap with peak reselected in every sample",
            "sampling site", int(value.n_sites), rain_suite_path,
        ))

    pic_geography_path = "analysis/v3/picrust2_ecology/geographic_profile_tests.tsv"
    pic_geography = table(pic_geography_path)
    value = one(
        pic_geography, analysis="primary", omitted_campaign=None,
        pathway_count=200, pseudocount=0.5,
    )
    rows.append(result_row(
        "Predicted function", "PICRUSt2 pathway-composition transect R2",
        value.quadratic_transect_r2, value.quadratic_transect_r2_ci_low,
        value.quadratic_transect_r2_ci_high, "95% confidence interval",
        "sampling uncertainty", "delete-one-site jackknife with t critical value",
        "sampling site", int(value.n_sites), pic_geography_path,
    ))

    pic_position_path = "analysis/v3/picrust2_ecology/position_profile_tests.tsv"
    pic_position = table(pic_position_path)
    for contrast in ("Deep-Surface", "Rhizosphere-Surface", "Rhizosphere-Deep"):
        value = one(
            pic_position, analysis="primary", omitted_campaign=None,
            pathway_count=200, pseudocount=0.5, contrast=contrast,
        )
        rows.append(result_row(
            "Predicted function", f"PICRUSt2 standardized displacement, {contrast}",
            value.standardized_displacement, value.standardized_ci_low,
            value.standardized_ci_high, "95% percentile bootstrap interval",
            "sampling uncertainty", "paired whole-site bootstrap", "sampling site",
            int(value.n_sites), pic_position_path,
        ))

    measured_path = "analysis/v3/measured_function_summary_results/summary_metrics.tsv"
    measured = table(measured_path)
    for metric, label in (
        ("per_sample_ko_profile_spearman_median", "Median within-sample PICRUSt2-shotgun KO rho"),
        ("community_mean_ko_profile_spearman", "Community-mean PICRUSt2-shotgun KO rho"),
    ):
        value = one(measured, metric=metric)
        rows.append(result_row(
            "Predicted function", label, value.estimate, value.interval_low,
            value.interval_high, "95% percentile bootstrap interval",
            "sampling uncertainty", value.uncertainty_method,
            value.independent_unit, int(value.n_samples), measured_path,
        ))

    pma_path = root / "analysis/v3/pma_endpoint_results/pma_summary.json"
    inputs.append(pma_path)
    pma = json.loads(pma_path.read_text(encoding="utf-8"))
    for endpoint, label in (
        ("richness_endpoint", "PMA treated-minus-untreated expected-richness difference"),
        ("shannon_endpoint", "PMA treated-minus-untreated Shannon difference"),
    ):
        value = pma[endpoint]
        uncertainty = value["mean_difference_uncertainty"]
        rows.append(result_row(
            "Assay controls", label,
            value["mean_difference_treated_minus_untreated"],
            uncertainty["interval_low"], uncertainty["interval_high"],
            "95% percentile bootstrap interval", "sampling uncertainty",
            uncertainty["method"], uncertainty["independent_unit"],
            int(pma["n_pairs"]), "analysis/v3/pma_endpoint_results/pma_summary.json",
        ))

    controls_path = "analysis/v3/control_audit/trip5_removal_fraction_by_profile.tsv"
    controls = table(controls_path)
    values = controls.loc[
        controls["role"].eq("compatible_biological_profile"),
        "candidate_contaminant_read_fraction",
    ].astype(float)
    if len(values) != 217:
        raise ValueError(f"Expected 217 linked Trip-5 profiles; found {len(values)}")
    low, estimate, high = values.quantile([0.25, 0.5, 0.75])
    rows.append(result_row(
        "Assay controls", "Candidate contaminant-read fraction per linked profile",
        estimate, low, high, "interquartile range",
        "between-profile dispersion, not sampling uncertainty",
        "empirical 25th, 50th and 75th percentiles", "linked biological profile",
        len(values), controls_path,
    ))

    frame = pd.DataFrame(rows)
    if frame["estimand"].duplicated().any():
        raise ValueError("Headline estimands are not unique")
    return frame, inputs


def write_outputs(root: Path, output: Path) -> None:
    frame, inputs = collect(root)
    output.mkdir(parents=True, exist_ok=True)
    result_path = output / "headline_uncertainty.tsv"
    frame.to_csv(result_path, sep="\t", index=False, lineterminator="\n")
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "analysis_date": ANALYSIS_DATE,
        "purpose": "typed uncertainty summary for manuscript reporting",
        "n_estimates": int(len(frame)),
        "input_files": [
            {
                "path": path.relative_to(root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            for path in inputs
        ],
        "output": {
            "path": result_path.name,
            "sha256": sha256_file(result_path),
        },
    }
    (output / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output / "README.md").write_text(
        """# Headline uncertainty summary

`headline_uncertainty.tsv` lists the main numerical estimates with their
uncertainty or sensitivity range. Sampling intervals, peak-selection
intervals, model-sensitivity ranges and descriptive interquartile ranges are
labelled separately and must not be interpreted as interchangeable confidence
intervals. The independent unit and calculation method accompany every value.
""",
        encoding="utf-8",
    )
    checksum_lines = [
        f"{sha256_file(path)}  {path.name}"
        for path in sorted(output.iterdir())
        if path.is_file() and path.name != "SHA256SUMS"
    ]
    (output / "SHA256SUMS").write_text(
        "\n".join(checksum_lines) + "\n", encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[2]
    )
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    root = args.root.resolve()
    output = (
        args.output.resolve()
        if args.output is not None
        else root / "analysis/v3/headline_uncertainty"
    )
    write_outputs(root, output)


if __name__ == "__main__":
    main()
