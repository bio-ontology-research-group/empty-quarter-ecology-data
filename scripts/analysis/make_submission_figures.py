#!/usr/bin/env python3
"""Build evidence-bounded ecology-paper figures from canonical TSV outputs.

This script performs no statistical fitting. It reads the exact outputs of the
grouped ecology, spatial, climate, predicted-function, PMA and control analyses;
validates the expected records; and renders only results whose wording is
permitted by the claim verdicts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


COLORS = {
    "surface": "#E69F00",
    "deep": "#0072B2",
    "root": "#009E73",
    "positive": "#0072B2",
    "negative": "#D55E00",
    "null": "#777777",
    "observed": "#CC3311",
}
PDF_METADATA = {
    "Title": "Empty Quarter ecology manuscript evidence figure",
    "Creator": "analysis/v3/make_submission_figures.py",
    "CreationDate": None,
    "ModDate": None,
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_columns(frame: pd.DataFrame, required: set[str], source: Path) -> None:
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"{source} is missing columns: {sorted(missing)}")


def setup_style() -> None:
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 10.5,
            "axes.titlesize": 11.5,
            "axes.labelsize": 10.5,
            "xtick.labelsize": 9.5,
            "ytick.labelsize": 9.5,
            "legend.fontsize": 9.0,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.linewidth": 0.7,
            "pdf.fonttype": 42,
            "savefig.transparent": False,
        }
    )


def asymmetric_errors(frame: pd.DataFrame, estimate: str) -> np.ndarray:
    return np.vstack(
        [
            frame[estimate].to_numpy() - frame["ci_low"].to_numpy(),
            frame["ci_high"].to_numpy() - frame[estimate].to_numpy(),
        ]
    )


def read_kml_polygon(path: Path) -> np.ndarray:
    """Read the first polygon ring from the project orientation boundary."""
    root = ET.parse(path).getroot()
    namespace = {"kml": "http://www.opengis.net/kml/2.2"}
    node = root.find(".//kml:LinearRing/kml:coordinates", namespace)
    if node is None or not node.text:
        raise ValueError(f"No polygon coordinates found in {path}")
    coordinates = []
    for token in node.text.split():
        longitude, latitude, *_ = token.split(",")
        coordinates.append((float(longitude), float(latitude)))
    if len(coordinates) < 4:
        raise ValueError(f"Boundary in {path} has fewer than four vertices")
    return np.asarray(coordinates, dtype=float)


def make_landscape_figure(
    alpha: pd.DataFrame,
    coordinates: pd.DataFrame,
    boundary_path: Path,
    distance_pairs: pd.DataFrame,
    site: pd.DataFrame,
    alpha_correlations: pd.DataFrame,
    genus_correlations: pd.DataFrame,
    output: Path,
) -> None:
    """Combine design, geography and climate into one landscape-scale figure."""
    fig, axes = plt.subplots(2, 3, figsize=(10.8, 7.2))
    map_ax, coverage_ax, climate_ax = axes[0]
    distance_ax, diversity_ax, genus_ax = axes[1]

    coordinates = coordinates.sort_values("transect_km")
    boundary = read_kml_polygon(boundary_path)
    map_ax.fill(
        boundary[:, 0],
        boundary[:, 1],
        facecolor="#F2E2C4",
        edgecolor="#9C7A4E",
        linewidth=0.8,
        zorder=0,
    )
    map_ax.text(
        51.1,
        22.7,
        "Rub' al-Khali",
        color="#7A5B36",
        fontsize=8.0,
        ha="center",
    )
    map_ax.plot(
        coordinates["longitude"],
        coordinates["latitude"],
        color="#BBBBBB",
        linewidth=0.9,
        zorder=1,
    )
    map_ax.scatter(
        coordinates["longitude"],
        coordinates["latitude"],
        color="#B56A2D",
        s=25,
        edgecolor="#333333",
        linewidth=0.35,
        zorder=2,
    )
    for site_number, horizontal, vertical in ((1, "left", "top"), (30, "left", "bottom"), (60, "right", "top")):
        row = coordinates.loc[coordinates["site"] == site_number]
        if len(row) != 1:
            raise ValueError(f"Expected one coordinate for site {site_number}")
        map_ax.annotate(
            f"Site {site_number}",
            (float(row.iloc[0]["longitude"]), float(row.iloc[0]["latitude"])),
            xytext=(4 if horizontal == "left" else -4, 4 if vertical == "bottom" else -4),
            textcoords="offset points",
            ha=horizontal,
            va=vertical,
            fontsize=7.3,
        )
    map_ax.set_aspect(1 / np.cos(np.deg2rad(coordinates["latitude"].mean())))
    map_ax.set_xlim(boundary[:, 0].min() - 0.2, boundary[:, 0].max() + 0.2)
    map_ax.set_ylim(boundary[:, 1].min() - 0.2, boundary[:, 1].max() + 0.2)
    map_ax.set(
        xlabel="Longitude",
        ylabel="Latitude",
        title="(a) Repeated 60-site desert transect",
    )

    type_order = ["Surface", "Deep", "Rhizosphere"]
    type_labels = ["Surface", "Shallow subsurface", "Root-adjacent"]
    type_colours = [COLORS["surface"], COLORS["deep"], COLORS["root"]]
    profile_counts = alpha.groupby(["Trip", "Type"]).size().unstack(fill_value=0)
    profile_counts = profile_counts.reindex(
        index=range(1, 6), columns=type_order, fill_value=0
    )
    bottom = np.zeros(len(profile_counts), dtype=float)
    for sample_type, label, colour in zip(type_order, type_labels, type_colours):
        values = profile_counts[sample_type].to_numpy()
        bars = coverage_ax.bar(
            profile_counts.index,
            values,
            bottom=bottom,
            color=colour,
            label=label,
            width=0.72,
        )
        for bar, value, base in zip(bars, values, bottom):
            if value >= 20:
                coverage_ax.text(
                    bar.get_x() + bar.get_width() / 2,
                    base + value / 2,
                    f"{int(value)}",
                    ha="center",
                    va="center",
                    fontsize=7.0,
                    color="white",
                )
        bottom += values
    for campaign, total in zip(profile_counts.index, bottom):
        coverage_ax.text(
            campaign,
            total + 7,
            f"{int(total)}",
            ha="center",
            va="bottom",
            fontsize=7.4,
        )
    coverage_ax.set(
        xlabel="Expedition",
        ylabel="Quality-controlled profiles",
        title="(b) Repeated coverage across soil positions",
        xticks=range(1, 6),
        xticklabels=[
            "T1\nMar\n2023",
            "T2\nJul\n2023",
            "T3\nFeb\n2024",
            "T4\nAug\n2024",
            "T5\nOct\n2025",
        ],
    )
    coverage_ax.tick_params(axis="x", labelsize=7.0)
    coverage_ax.legend(frameon=False, fontsize=7.0, loc="upper left")

    climate_order = [
        "mean_air_temperature_c",
        "mean_monthly_rain_mm",
        "mean_relative_humidity_pct",
    ]
    climate_labels = ["Temperature", "Rain", "Humidity"]
    climate_colours = ["#D55E00", "#0072B2", "#009E73"]
    ordered = site.sort_values("transect_km")
    for variable, label, colour in zip(
        climate_order, climate_labels, climate_colours
    ):
        values = ordered[variable]
        standardized = (values - values.mean()) / values.std(ddof=1)
        climate_ax.plot(
            ordered["transect_km"],
            standardized,
            color=colour,
            linewidth=1.4,
            alpha=0.9,
            label=label,
        )
    climate_ax.axhline(0, color="#999999", linewidth=0.6)
    climate_ax.set(
        xlabel="West--east coordinate (km)",
        ylabel="Standardized 49-month mean",
        title="(c) Climate changes along the route",
    )
    climate_ax.legend(frameon=False, fontsize=7.4)

    distance_pairs = distance_pairs.copy()
    upper = float(distance_pairs["geographic_distance_km"].max())
    edges = np.linspace(0.0, upper + np.finfo(float).eps, 11)
    distance_pairs["distance_bin"] = pd.cut(
        distance_pairs["geographic_distance_km"],
        bins=edges,
        labels=False,
        include_lowest=True,
    )
    distance_order = [
        ("Surface", "Surface", COLORS["surface"], "o"),
        ("Deep", "Shallow subsurface", COLORS["deep"], "s"),
        ("Rhizosphere", "Root-adjacent", COLORS["root"], "^"),
    ]
    for compartment, label, color, marker in distance_order:
        part = distance_pairs[distance_pairs["compartment"] == compartment]
        summary = (
            part.groupby("distance_bin", observed=True)
            .agg(
                distance_km=("geographic_distance_km", "mean"),
                dissimilarity=("aitchison_dissimilarity", "mean"),
            )
            .reset_index()
        )
        distance_ax.plot(
            summary["distance_km"],
            summary["dissimilarity"],
            marker=marker,
            color=color,
            label=label,
            linewidth=1.5,
            markersize=4.2,
        )
    distance_ax.set(
        xlabel="Distance between sites (km)",
        ylabel="Mean Aitchison dissimilarity",
        title="(d) Communities diverge with distance",
    )
    distance_ax.legend(frameon=False, fontsize=7.3)

    response_order = ["shannon", "expected_richness_25k", "normalized_evenness"]
    response_labels = ["Shannon", "Expected\nrichness", "Normalized\nevenness"]
    matrix = (
        alpha_correlations.pivot(
            index="climate_variable", columns="response", values="spearman_rho"
        )
        .loc[climate_order, response_order]
        .to_numpy(dtype=float)
    )
    image_plot = diversity_ax.imshow(
        matrix, cmap="RdBu_r", vmin=-1, vmax=1, aspect="auto"
    )
    for row in range(matrix.shape[0]):
        for column in range(matrix.shape[1]):
            diversity_ax.text(
                column,
                row,
                f"{matrix[row, column]:.2f}",
                ha="center",
                va="center",
                color="white" if abs(matrix[row, column]) > 0.55 else "#222222",
                fontsize=8.2,
            )
    diversity_ax.set(
        xticks=np.arange(3),
        xticklabels=response_labels,
        yticks=np.arange(3),
        yticklabels=climate_labels,
        title="(e) Diversity follows the climate gradient",
    )
    diversity_ax.tick_params(axis="x", labelsize=7.3)
    colourbar = fig.colorbar(image_plot, ax=diversity_ax, fraction=0.05, pad=0.04)
    colourbar.set_label("Spearman $\\rho$")

    supported = genus_correlations[
        genus_correlations["supported_q_lt_0_05"]
    ].copy()
    selected_genera: set[str] = set()
    for variable in climate_order:
        part = supported[supported["climate_variable"] == variable]
        selected_genera.update(part.nlargest(2, "spearman_rho")["genus"])
        selected_genera.update(part.nsmallest(2, "spearman_rho")["genus"])
    selected = supported[supported["genus"].isin(selected_genera)].pivot(
        index="genus", columns="climate_variable", values="spearman_rho"
    )
    if selected.shape != (10, 3) or selected.isna().any().any():
        raise ValueError(
            "Expected ten fully supported genera from the two-tail selection rule"
        )
    selected["mean_rho"] = selected[climate_order].mean(axis=1)
    selected = selected.sort_values("mean_rho")
    genus_y = np.arange(len(selected))
    offsets = [-0.18, 0.0, 0.18]
    for variable, label, colour, offset in zip(
        climate_order, climate_labels, climate_colours, offsets
    ):
        genus_ax.scatter(
            selected[variable],
            genus_y + offset,
            color=colour,
            s=23,
            label=label,
            edgecolor="white",
            linewidth=0.35,
            zorder=3,
        )
    genus_ax.axvline(0, color="#777777", linewidth=0.8)
    genus_ax.set(
        xlabel="Genus CLR abundance (Spearman $\\rho$)",
        yticks=genus_y,
        yticklabels=[rf"$\it{{{name}}}$" for name in selected.index],
        xlim=(-0.9, 0.9),
        title="(f) Leading genera track the gradients",
    )
    genus_ax.legend(frameon=False, fontsize=6.8, loc="upper left")

    fig.tight_layout(h_pad=2.0, w_pad=1.8)
    fig.savefig(output, bbox_inches="tight", metadata=PDF_METADATA)
    plt.close(fig)


def make_soil_position_figure(
    paired: pd.DataFrame,
    evenness: pd.DataFrame,
    location: pd.DataFrame,
    loadings: pd.DataFrame,
    output: Path,
) -> None:
    """Plot paired soil-position effects and their leading taxon contrasts."""
    fig = plt.figure(figsize=(10.6, 6.1))
    grid = fig.add_gridspec(2, 3, height_ratios=(1.0, 1.15))
    axes = [fig.add_subplot(grid[0, column]) for column in range(3)]
    loading_ax = fig.add_subplot(grid[1, :])

    comparison_order = [
        "Rhizosphere-Deep",
        "Rhizosphere-Surface",
        "Deep-Surface",
    ]
    labels = [
        "Root-adjacent − shallow",
        "Root-adjacent − surface",
        "Shallow − surface",
    ]
    y = np.arange(len(comparison_order))

    primary_location = location[
        (location["analysis"] == "primary")
        & (location["contrast"].isin(comparison_order))
    ].copy()
    primary_location["contrast"] = pd.Categorical(
        primary_location["contrast"], comparison_order, ordered=True
    )
    primary_location = primary_location.sort_values("contrast")
    if primary_location["contrast"].astype(str).tolist() != comparison_order:
        raise ValueError("Missing a primary paired composition contrast")
    location_scale = (
        primary_location["displacement"]
        / primary_location["standardized_displacement"]
    )
    location_low = primary_location["displacement_ci_low"] / location_scale
    location_high = primary_location["displacement_ci_high"] / location_scale
    axes[0].errorbar(
        primary_location["standardized_displacement"],
        y,
        xerr=np.vstack(
            [
                primary_location["standardized_displacement"] - location_low,
                location_high - primary_location["standardized_displacement"],
            ]
        ),
        fmt="o",
        color=COLORS["root"],
        capsize=3,
    )
    axes[0].axvline(0, color="#777777", linewidth=0.8)
    axes[0].set(
        yticks=y,
        yticklabels=labels,
        xlabel="Standardized Aitchison displacement",
        title="(a) Paired composition",
    )

    all_shannon = paired[
        (paired["trip"].astype(str) == "all")
        & (paired["metric"] == "shannon")
    ].copy()
    all_shannon["comparison"] = pd.Categorical(
        all_shannon["comparison"], comparison_order, ordered=True
    )
    all_shannon = all_shannon.sort_values("comparison")
    if all_shannon["comparison"].astype(str).tolist() != comparison_order:
        raise ValueError("Missing an all-campaign Shannon comparison")
    axes[1].errorbar(
        all_shannon["mean_difference"],
        y,
        xerr=asymmetric_errors(all_shannon, "mean_difference"),
        fmt="o",
        color="#333333",
        capsize=3,
    )
    axes[1].axvline(0, color="#777777", linewidth=0.8)
    axes[1].set(
        yticks=y,
        xlabel="Paired Shannon difference",
        title="(b) Shannon diversity",
    )
    axes[1].tick_params(axis="y", labelleft=False)

    normalized = evenness[
        evenness["metric"] == "evenness_h_over_log_hurlbert"
    ].copy()
    normalized["contrast"] = pd.Categorical(
        normalized["contrast"], comparison_order, ordered=True
    )
    normalized = normalized.sort_values("contrast")
    if normalized["contrast"].astype(str).tolist() != comparison_order:
        raise ValueError("Missing a normalized-evenness contrast")
    errors = np.vstack(
        [
            normalized["mean_difference"].to_numpy()
            - normalized["bootstrap_ci_low"].to_numpy(),
            normalized["bootstrap_ci_high"].to_numpy()
            - normalized["mean_difference"].to_numpy(),
        ]
    )
    axes[2].errorbar(
        normalized["mean_difference"],
        y,
        xerr=errors,
        fmt="o",
        color=COLORS["root"],
        capsize=3,
    )
    axes[2].axvline(0, color="#777777", linewidth=0.8)
    axes[2].set(
        yticks=y,
        xlabel=r"Paired $H/\log(E[S_{25k}])$ difference",
        title="(c) Normalized evenness",
    )
    axes[2].tick_params(axis="y", labelleft=False)

    axes[0].invert_yaxis()

    # This panel is descriptive: it names the genera contributing most to the
    # three paired CLR displacement vectors without turning their loadings into
    # univariate differential-abundance tests.
    loadings = loadings[loadings["contrast"].isin(comparison_order)].copy()
    selected_genera: list[str] = []
    for comparison in comparison_order:
        ranked = (
            loadings[loadings["contrast"] == comparison]
            .assign(abs_loading=lambda frame: frame["mean_clr_difference"].abs())
            .nlargest(4, "abs_loading")
        )
        for genus in ranked["genus"]:
            if genus not in selected_genera:
                selected_genera.append(genus)
    if len(selected_genera) < 6:
        raise ValueError("Too few genera selected for the position-loading panel")
    loading_matrix = (
        loadings[loadings["genus"].isin(selected_genera)]
        .pivot(index="contrast", columns="genus", values="mean_clr_difference")
        .reindex(index=comparison_order, columns=selected_genera)
    )
    if loading_matrix.isna().any().any():
        raise ValueError("Position-loading panel has missing contrast values")
    maximum = max(2.5, float(np.abs(loading_matrix.to_numpy()).max()))
    image_plot = loading_ax.imshow(
        loading_matrix.to_numpy(),
        cmap="RdBu_r",
        vmin=-maximum,
        vmax=maximum,
        aspect="auto",
    )
    for row in range(loading_matrix.shape[0]):
        for column in range(loading_matrix.shape[1]):
            value = float(loading_matrix.iloc[row, column])
            loading_ax.text(
                column,
                row,
                f"{value:.1f}",
                ha="center",
                va="center",
                fontsize=7.3,
                color="white" if abs(value) > maximum * 0.58 else "#222222",
            )
    loading_ax.set(
        xticks=np.arange(len(selected_genera)),
        xticklabels=[rf"$\it{{{name}}}$" for name in selected_genera],
        yticks=np.arange(len(comparison_order)),
        yticklabels=labels,
        title="(d) Leading genera in paired composition contrasts",
    )
    loading_ax.tick_params(axis="x", rotation=28, labelsize=8.0)
    loading_ax.tick_params(axis="y", labelsize=8.3)
    colourbar = fig.colorbar(
        image_plot, ax=loading_ax, fraction=0.025, pad=0.02
    )
    colourbar.set_label("Mean paired CLR difference")

    fig.tight_layout(h_pad=2.0, w_pad=1.6)
    fig.savefig(output, bbox_inches="tight", metadata=PDF_METADATA)
    plt.close(fig)


def make_function_control_figure(
    position: pd.DataFrame,
    ko_validation: pd.DataFrame,
    pma_pairs: pd.DataFrame,
    removal: pd.DataFrame,
    output: Path,
) -> None:
    """Show predicted pathway structure and the two assay checks."""
    fig, axes = plt.subplots(2, 2, figsize=(8.4, 6.6))

    primary = position[
        position["analysis"].eq("primary")
        & ~position["contrast"].eq("omnibus_three_positions")
    ].copy()
    contrast_order = [
        "Rhizosphere-Deep",
        "Rhizosphere-Surface",
        "Deep-Surface",
    ]
    contrast_labels = [
        "Root-adjacent − shallow",
        "Root-adjacent − surface",
        "Shallow − surface",
    ]
    primary["contrast"] = pd.Categorical(
        primary["contrast"], contrast_order, ordered=True
    )
    primary = primary.sort_values("contrast")
    if primary["contrast"].astype(str).tolist() != contrast_order:
        raise ValueError("Missing a primary PICRUSt2 position contrast")
    y = np.arange(3)
    pathway_scale = primary["displacement"] / primary["standardized_displacement"]
    pathway_low = primary["ci_low"] / pathway_scale
    pathway_high = primary["ci_high"] / pathway_scale
    axes[0, 0].errorbar(
        primary["standardized_displacement"],
        y,
        xerr=np.vstack(
            [
                primary["standardized_displacement"] - pathway_low,
                pathway_high - primary["standardized_displacement"],
            ]
        ),
        fmt="o",
        color=COLORS["root"],
        capsize=3,
    )
    axes[0, 0].axvline(0, color="#777777", linewidth=0.8)
    axes[0, 0].set(
        yticks=y,
        yticklabels=contrast_labels,
        xlabel="Standardized Aitchison displacement",
        title="(a) Predicted pathway profiles\ndiffer by soil position",
    )
    axes[0, 0].invert_yaxis()

    validation_values = ko_validation["spearman_rho"].to_numpy(dtype=float)
    axes[0, 1].hist(
        validation_values,
        bins=np.linspace(0.4, 0.85, 16),
        color="#0072B2",
        edgecolor="white",
        linewidth=0.5,
    )
    median = float(np.median(validation_values))
    axes[0, 1].axvline(median, color="#CC3311", linewidth=1.5)
    axes[0, 1].text(
        median - 0.008,
        axes[0, 1].get_ylim()[1] * 0.92,
        f"median {median:.2f}",
        ha="right",
        va="top",
        color="#CC3311",
        fontsize=8.5,
    )
    axes[0, 1].set(
        xlabel="PICRUSt2--shotgun KO Spearman $\\rho$",
        ylabel="Matched samples",
        title="(b) Broad predictions agree\nwith shotgun ($n=125$)",
    )

    for row in pma_pairs.itertuples():
        axes[1, 0].plot(
            [0, 1],
            [
                row.untreated_expected_rarefied_richness,
                row.treated_expected_rarefied_richness,
            ],
            color="#888888",
            linewidth=0.9,
            alpha=0.8,
            marker="o",
            markersize=3.4,
        )
    untreated_mean = float(
        pma_pairs["untreated_expected_rarefied_richness"].mean()
    )
    treated_mean = float(pma_pairs["treated_expected_rarefied_richness"].mean())
    axes[1, 0].plot(
        [0, 1],
        [untreated_mean, treated_mean],
        color="#CC3311",
        linewidth=2.2,
        marker="D",
        markersize=5,
        label="Mean",
        zorder=4,
    )
    axes[1, 0].set(
        xticks=[0, 1],
        xticklabels=["Untreated", "PMA treated"],
        ylabel="Expected richness",
        title="(c) PMA lowers richness in 8 of 9 pairs",
    )
    axes[1, 0].legend(frameon=False, fontsize=8.0)

    biological = removal[
        removal["role"].eq("compatible_biological_profile")
    ].copy()
    fractions = np.sort(
        biological["candidate_contaminant_read_fraction"].to_numpy(dtype=float)
        * 100
    )
    axes[1, 1].scatter(
        np.arange(1, len(fractions) + 1),
        np.maximum(fractions, 0.0001),
        s=10,
        color="#009E73",
        alpha=0.75,
        edgecolor="none",
    )
    axes[1, 1].axhline(
        np.median(fractions), color="#CC3311", linewidth=1.2, linestyle="--"
    )
    axes[1, 1].set_yscale("log")
    axes[1, 1].set(
        xlabel="Trip 5 profiles, ordered by fraction",
        ylabel="Candidate reads removed (%)",
        title="(d) Removal is below 1% in 75% of profiles",
    )
    axes[1, 1].text(
        0.03,
        0.95,
        f"median {np.median(fractions):.2f}%\nmaximum {np.max(fractions):.1f}%",
        transform=axes[1, 1].transAxes,
        ha="left",
        va="top",
        fontsize=8.0,
    )

    fig.tight_layout(h_pad=2.0, w_pad=2.2)
    fig.savefig(output, bbox_inches="tight", metadata=PDF_METADATA)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--core-dir", type=Path, required=True)
    # Retained as optional compatibility arguments for older workflow calls.
    parser.add_argument("--network-dir", type=Path, default=None)
    parser.add_argument("--functional-dir", type=Path, default=None)
    parser.add_argument("--environment-dir", type=Path, default=None)
    parser.add_argument("--picrust-dir", type=Path, default=None)
    parser.add_argument("--control-dir", type=Path, default=None)
    parser.add_argument("--pma-dir", type=Path, default=None)
    parser.add_argument("--measured-function-dir", type=Path, default=None)
    parser.add_argument("--boundary-file", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    core = args.core_dir.resolve()
    local_v3 = Path(__file__).resolve().parent
    environment_dir = (
        args.environment_dir.resolve()
        if args.environment_dir is not None
        else local_v3 / "environment_associations"
    )
    picrust_dir = (
        args.picrust_dir.resolve()
        if args.picrust_dir is not None
        else local_v3 / "picrust2_ecology"
    )
    control_dir = (
        args.control_dir.resolve()
        if args.control_dir is not None
        else local_v3 / "control_audit"
    )
    pma_dir = (
        args.pma_dir.resolve()
        if args.pma_dir is not None
        else local_v3 / "pma_endpoint_results"
    )
    measured_function_dir = (
        args.measured_function_dir.resolve()
        if args.measured_function_dir is not None
        else local_v3 / "measured_function_summary_results"
    )
    project_root = Path(__file__).resolve().parents[2]
    if args.boundary_file is not None:
        boundary_file = args.boundary_file.resolve()
    else:
        boundary_candidates = (
            project_root / "data/metadata/misc/boundary.kml",
            project_root / "metadata/geodata/empty_quarter_boundary.kml",
        )
        boundary_file = next(
            (candidate for candidate in boundary_candidates if candidate.is_file()),
            boundary_candidates[0],
        )
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)

    rain_response_dir = core / "rain_response_window"
    if not (rain_response_dir / "analysis_decision.json").is_file():
        rain_response_dir = core.parent / "rain_response_window"
    if not (rain_response_dir / "analysis_decision.json").is_file():
        rain_response_dir = local_v3 / "rain_response_window"
    distance_decay_dir = core / "distance_decay_turnover"
    if not (distance_decay_dir / "distance_decay_pairs.tsv").is_file():
        distance_decay_dir = core.parent / "distance_decay_turnover"
    if not (distance_decay_dir / "distance_decay_pairs.tsv").is_file():
        distance_decay_dir = local_v3 / "distance_decay_turnover"

    input_paths = {
        "alpha_table": core / "cache/alpha.tsv",
        "empty_quarter_orientation_boundary": boundary_file,
        "spatial_site_coordinates": (
            core
            / "spatial_turnover_rescue/results/site_coordinates.tsv"
        ),
        "pma_summary": core / "pma_endpoints/pma_summary.json",
        "paired_compartment_effects": (
            core / "claim_rescue/paired_compartment_effects.tsv"
        ),
        "paired_evenness_effects": (
            core / "evenness_decomposition/paired_contrasts.tsv"
        ),
        "paired_composition_location": (
            core
            / "compartment_composition/compartment_location_results.tsv"
        ),
        "paired_composition_loadings": (
            core
            / "compartment_composition/paired_displacement_loadings.tsv"
        ),
        "rain_response_figure": rain_response_dir / "rain_response_window.pdf",
        "rain_response_decision": rain_response_dir / "analysis_decision.json",
        "spatial_claim_verdict": (
            core / "spatial_turnover_rescue/results/claim_verdict.json"
        ),
        "distance_decay_pairs": (
            distance_decay_dir / "distance_decay_pairs.tsv"
        ),
        "climate_site_summary": (
            environment_dir / "climate_site_summary.tsv"
        ),
        "climate_alpha_correlations": (
            environment_dir / "climate_alpha_correlations.tsv"
        ),
        "climate_genus_correlations": (
            environment_dir / "climate_genus_correlations.tsv"
        ),
        "environment_decision": (
            environment_dir / "analysis_decision.json"
        ),
        "picrust_position_tests": (
            picrust_dir / "position_profile_tests.tsv"
        ),
        "picrust_decision": picrust_dir / "analysis_decision.json",
        "ko_validation": (
            measured_function_dir / "per_sample_ko_correlations.tsv"
        ),
        "pma_pairs": pma_dir / "pma_pair_endpoints.tsv",
        "control_removal": (
            control_dir / "trip5_removal_fraction_by_profile.tsv"
        ),
        "control_sensitivity_summary": (
            control_dir / "sensitivity_inputs/summary.json"
        ),
    }
    missing = [str(path) for path in input_paths.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError("Missing canonical figure inputs:\n" + "\n".join(missing))

    alpha = pd.read_csv(input_paths["alpha_table"], sep="\t", index_col=0)
    coordinates = pd.read_csv(
        input_paths["spatial_site_coordinates"], sep="\t"
    )
    paired = pd.read_csv(input_paths["paired_compartment_effects"], sep="\t")
    evenness = pd.read_csv(input_paths["paired_evenness_effects"], sep="\t")
    location = pd.read_csv(
        input_paths["paired_composition_location"], sep="\t"
    )
    loadings = pd.read_csv(
        input_paths["paired_composition_loadings"], sep="\t"
    )
    distance_pairs = pd.read_csv(
        input_paths["distance_decay_pairs"], sep="\t"
    )
    climate_site = pd.read_csv(
        input_paths["climate_site_summary"], sep="\t"
    )
    climate_alpha = pd.read_csv(
        input_paths["climate_alpha_correlations"], sep="\t"
    )
    climate_genus = pd.read_csv(
        input_paths["climate_genus_correlations"], sep="\t"
    )
    picrust_position = pd.read_csv(
        input_paths["picrust_position_tests"], sep="\t"
    )
    ko_validation = pd.read_csv(input_paths["ko_validation"], sep="\t")
    pma_pairs = pd.read_csv(input_paths["pma_pairs"], sep="\t")
    control_removal = pd.read_csv(
        input_paths["control_removal"], sep="\t"
    )
    spatial_verdict = json.loads(input_paths["spatial_claim_verdict"].read_text())
    pma_summary = json.loads(input_paths["pma_summary"].read_text())
    rain_response_verdict = json.loads(
        input_paths["rain_response_decision"].read_text()
    )
    environment_verdict = json.loads(
        input_paths["environment_decision"].read_text()
    )
    picrust_verdict = json.loads(input_paths["picrust_decision"].read_text())
    control_sensitivity = json.loads(
        input_paths["control_sensitivity_summary"].read_text()
    )

    require_columns(
        alpha,
        {"Trip", "Site", "Type"},
        input_paths["alpha_table"],
    )
    require_columns(
        coordinates,
        {"site", "latitude", "longitude", "transect_km"},
        input_paths["spatial_site_coordinates"],
    )
    require_columns(
        paired,
        {
            "trip",
            "metric",
            "comparison",
            "mean_difference",
            "ci_low",
            "ci_high",
        },
        input_paths["paired_compartment_effects"],
    )
    require_columns(
        evenness,
        {
            "metric",
            "contrast",
            "mean_difference",
            "bootstrap_ci_low",
            "bootstrap_ci_high",
        },
        input_paths["paired_evenness_effects"],
    )
    require_columns(
        location,
        {
            "analysis",
            "contrast",
            "displacement",
            "displacement_ci_low",
            "displacement_ci_high",
            "standardized_displacement",
            "permutation_p",
        },
        input_paths["paired_composition_location"],
    )
    require_columns(
        loadings,
        {"contrast", "genus", "mean_clr_difference"},
        input_paths["paired_composition_loadings"],
    )
    require_columns(
        distance_pairs,
        {
            "site_a",
            "site_b",
            "geographic_distance_km",
            "compartment",
            "compartment_label",
            "aitchison_dissimilarity",
        },
        input_paths["distance_decay_pairs"],
    )
    require_columns(
        climate_site,
        {
            "site",
            "transect_km",
            "mean_air_temperature_c",
            "mean_monthly_rain_mm",
            "mean_relative_humidity_pct",
        },
        input_paths["climate_site_summary"],
    )
    require_columns(
        climate_alpha,
        {
            "climate_variable",
            "response",
            "spearman_rho",
            "q_global_9",
        },
        input_paths["climate_alpha_correlations"],
    )
    require_columns(
        climate_genus,
        {
            "climate_variable",
            "genus",
            "spearman_rho",
            "q_global_600",
            "supported_q_lt_0_05",
        },
        input_paths["climate_genus_correlations"],
    )
    require_columns(
        picrust_position,
        {
            "analysis",
            "contrast",
            "displacement",
            "ci_low",
            "ci_high",
            "standardized_displacement",
            "permutation_p",
        },
        input_paths["picrust_position_tests"],
    )
    require_columns(
        ko_validation,
        {"sample", "n_shared_kos", "spearman_rho"},
        input_paths["ko_validation"],
    )
    require_columns(
        pma_pairs,
        {
            "pair_id",
            "treated_expected_rarefied_richness",
            "untreated_expected_rarefied_richness",
        },
        input_paths["pma_pairs"],
    )
    require_columns(
        control_removal,
        {"profile_id", "role", "candidate_contaminant_read_fraction"},
        input_paths["control_removal"],
    )

    # Fail closed if a verdict changes: the plot captions and manuscript text
    # would then require scientific review rather than automatic reuse.
    expected_verdicts = {
        "spatial": (
            spatial_verdict["status"],
            "broad_geographic_structure_supported",
        ),
        "pma": (pma_summary["status"], "paired_endpoints_only"),
        "rain_response": (
            rain_response_verdict["analysis_status"],
            "response_window_not_identified",
        ),
        "environment": (
            environment_verdict["status"],
            "observational_climate_associations_supported",
        ),
        "picrust2": (
            picrust_verdict["status"],
            "predicted_functional_structure_supported",
        ),
        "control_sensitivity": (
            control_sensitivity["profiles_below_rarefaction_depth_after_filter"],
            0,
        ),
    }
    changed = {
        name: observed
        for name, (observed, expected) in expected_verdicts.items()
        if observed != expected
    }
    if changed:
        raise ValueError(f"Claim verdict changed; review figures first: {changed}")

    setup_style()
    output_paths = {
        "landscape": output / "fig1_landscape.pdf",
        "soil_position": output / "fig2_soil_position.pdf",
        "campaign_rainfall_supplement": (
            output / "figS_campaign_rainfall.pdf"
        ),
        "function_controls": output / "fig3_function_controls.pdf",
    }
    make_landscape_figure(
        alpha,
        coordinates,
        boundary_file,
        distance_pairs,
        climate_site,
        climate_alpha,
        climate_genus,
        output_paths["landscape"],
    )
    make_soil_position_figure(
        paired,
        evenness,
        location,
        loadings,
        output_paths["soil_position"],
    )
    shutil.copyfile(
        input_paths["rain_response_figure"],
        output_paths["campaign_rainfall_supplement"],
    )
    make_function_control_figure(
        picrust_position,
        ko_validation,
        pma_pairs,
        control_removal,
        output_paths["function_controls"],
    )

    rows = []
    for name, path in sorted(input_paths.items()):
        rows.append(
            {
                "role": "input",
                "name": name,
                "file": path.name,
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
        )
    for name, path in sorted(output_paths.items()):
        rows.append(
            {
                "role": "output",
                "name": name,
                "file": path.name,
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
        )
    pd.DataFrame(rows).to_csv(
        output / "figure_manifest.tsv", sep="\t", index=False
    )


if __name__ == "__main__":
    main()
