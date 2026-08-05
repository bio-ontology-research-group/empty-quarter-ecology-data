#!/usr/bin/env python3
"""Conservative compositional network sensitivity analysis for Empty Quarter data.

The command aggregates sequencing replicates to campaign x site x compartment,
restricts sites to 1--60, uses the exact campaign/site intersection shared by
all compartments, and infers regularized conditional-association networks from
campaign-centered CLR values.

Regularization is calibrated against independently permuted taxa. Edges are
retained only when they are selected in the full data, stable under site-cluster
bootstrap, sign-consistent, and uncommon in permuted null networks. All random
seeds and output paths are explicit. No manuscript files are read or written.

Example
-------
uv run --with numpy --with pandas --with scikit-learn \
  python analysis/v3/network_rescue/run_network_rescue.py \
  --project-root . \
  --output-dir analysis/v3/network_rescue/results
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import warnings
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd
import sklearn
from sklearn.covariance import GraphicalLasso
from sklearn.exceptions import ConvergenceWarning


SCHEMA_VERSION = "1.0"
COMPARTMENTS = ("Surface", "Deep", "Rhizosphere")
DEFAULT_INPUT = Path("analysis/v2/review/cache/genus_counts.tsv")
SAMPLE_RE = re.compile(
    r"^(?:e\d+_)?(?P<prefix>[TFSV])?(?P<site>\d+)"
    r"(?P<compartment>PR|P|D|S)r(?P<replicate>\d+)"
)
PREFIX_CAMPAIGN = {"": 1, "T": 2, "F": 3, "S": 4, "V": 5}
CODE_COMPARTMENT = {
    "D": "Deep",
    "S": "Surface",
    "P": "Rhizosphere",
    "PR": "Rhizosphere",
}


@dataclass(frozen=True)
class FitResult:
    partial: np.ndarray
    selected: np.ndarray
    convergence_warnings: int


def parse_csv_numbers(value: str, cast=float) -> list:
    parsed = [cast(part.strip()) for part in value.split(",") if part.strip()]
    if not parsed:
        raise ValueError("Expected at least one comma-separated value")
    return parsed


def sample_metadata(sample_id: str) -> dict[str, Any] | None:
    match = SAMPLE_RE.match(str(sample_id).replace(" ", ""))
    if match is None:
        return None
    prefix = match.group("prefix") or ""
    return {
        "sample_id": sample_id,
        "campaign": PREFIX_CAMPAIGN[prefix],
        "site": int(match.group("site")),
        "compartment": CODE_COMPARTMENT[match.group("compartment")],
        "replicate": int(match.group("replicate")),
    }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def format_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (float, np.floating)):
        if not math.isfinite(float(value)):
            return ""
        return f"{float(value):.10g}"
    if isinstance(value, (int, np.integer)):
        return str(int(value))
    return str(value)


def write_tsv(
    path: Path,
    rows: Iterable[Mapping[str, Any]],
    columns: Sequence[str],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(columns),
            delimiter="\t",
            lineterminator="\n",
            extrasaction="ignore",
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {column: format_cell(row.get(column)) for column in columns}
            )


def quantile(values: Sequence[float], probability: float) -> float | None:
    if len(values) == 0:
        return None
    return float(np.quantile(np.asarray(values, dtype=float), probability))


def load_aggregated_counts(
    path: Path,
    minimum_group_reads: float,
) -> tuple[
    dict[str, pd.DataFrame],
    list[tuple[int, int]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, Any],
]:
    """Load genus counts and aggregate replicates by campaign/site/compartment."""
    genus = pd.read_csv(path, sep="\t", index_col=0)
    input_genera = int(genus.shape[0])
    missing_genus_labels = int(genus.index.isna().sum())
    genus = genus.loc[~genus.index.isna()].copy()
    genus.index = genus.index.astype(str)
    metadata_rows = [
        parsed
        for sample_id in genus.columns
        if (parsed := sample_metadata(sample_id)) is not None
    ]
    metadata = pd.DataFrame(metadata_rows)
    metadata = metadata[
        metadata["site"].between(1, 60)
        & metadata["campaign"].between(1, 5)
        & metadata["compartment"].isin(COMPARTMENTS)
    ].copy()

    grouped: dict[str, pd.DataFrame] = {}
    valid_keys: dict[str, set[tuple[int, int]]] = {}
    cohort_rows: list[dict[str, Any]] = []
    cohort_group_rows: list[dict[str, Any]] = []
    for compartment in COMPARTMENTS:
        submeta = metadata[metadata["compartment"] == compartment].copy()
        sample_order = list(submeta["sample_id"])
        values = genus[sample_order].T
        values["campaign"] = list(submeta["campaign"])
        values["site"] = list(submeta["site"])
        aggregate = values.groupby(["campaign", "site"], sort=True).sum().T
        library_sizes = aggregate.sum(axis=0)
        replicate_counts = submeta.groupby(
            ["campaign", "site"], sort=True
        ).size()
        valid = {
            (int(campaign), int(site))
            for campaign, site in library_sizes[
                library_sizes >= minimum_group_reads
            ].index
        }
        grouped[compartment] = aggregate
        valid_keys[compartment] = valid
        for (campaign, site), library_size in library_sizes.items():
            cohort_group_rows.append(
                {
                    "campaign": int(campaign),
                    "site": int(site),
                    "compartment": compartment,
                    "sequencing_replicates": int(
                        replicate_counts.loc[(campaign, site)]
                    ),
                    "aggregate_library_size": float(library_size),
                    "passes_read_qc": (
                        float(library_size) >= minimum_group_reads
                    ),
                    "in_exact_matched_cohort": False,
                }
            )

        for campaign in range(1, 6):
            campaign_samples = submeta[submeta["campaign"] == campaign]
            pre_qc = {
                (int(row.campaign), int(row.site))
                for row in campaign_samples.itertuples()
            }
            cohort_rows.append(
                {
                    "stage": "before_matched_intersection",
                    "campaign": campaign,
                    "compartment": compartment,
                    "sample_columns": len(campaign_samples),
                    "site_campaign_groups": len(pre_qc),
                    "groups_passing_read_qc": len(pre_qc & valid),
                    "groups_in_final_matched_cohort": 0,
                }
            )

    matched_keys = sorted(set.intersection(*valid_keys.values()))
    if not matched_keys:
        raise ValueError("No campaign/site groups are shared by all compartments")
    matched_columns = pd.MultiIndex.from_tuples(
        matched_keys, names=["campaign", "site"]
    )
    for compartment in COMPARTMENTS:
        grouped[compartment] = grouped[compartment].reindex(
            columns=matched_columns
        )

    matched_counts = Counter(campaign for campaign, _ in matched_keys)
    matched_key_set = set(matched_keys)
    for row in cohort_group_rows:
        row["in_exact_matched_cohort"] = (
            (row["campaign"], row["site"]) in matched_key_set
            and row["passes_read_qc"]
        )
    for row in cohort_rows:
        row["groups_in_final_matched_cohort"] = matched_counts[row["campaign"]]
    for campaign in range(1, 6):
        cohort_rows.append(
            {
                "stage": "final_exact_match",
                "campaign": campaign,
                "compartment": "ALL_EXACTLY_MATCHED",
                "sample_columns": "",
                "site_campaign_groups": matched_counts[campaign],
                "groups_passing_read_qc": matched_counts[campaign],
                "groups_in_final_matched_cohort": matched_counts[campaign],
            }
        )

    info = {
        "input_genera": input_genera,
        "excluded_missing_genus_labels": missing_genus_labels,
        "analysis_genera": int(genus.shape[0]),
        "input_sample_columns": int(genus.shape[1]),
        "parsed_core_sample_columns": int(len(metadata)),
        "matched_observations_per_compartment": int(len(matched_keys)),
        "matched_unique_sites": int(len({site for _, site in matched_keys})),
        "matched_campaign_counts": {
            str(campaign): int(matched_counts[campaign])
            for campaign in range(1, 6)
        },
    }
    return grouped, matched_keys, cohort_rows, cohort_group_rows, info


def select_taxa(
    grouped: Mapping[str, pd.DataFrame],
    prevalence_threshold: float,
    maximum_taxa: int,
    primary_taxa_count: int,
) -> tuple[list[str], list[dict[str, Any]]]:
    prevalence = {
        compartment: (table > 0).mean(axis=1)
        for compartment, table in grouped.items()
    }
    eligible = np.logical_and.reduce(
        [
            prevalence[compartment].values >= prevalence_threshold
            for compartment in COMPARTMENTS
        ]
    )
    eligible_names = grouped[COMPARTMENTS[0]].index[eligible]

    relative = {
        compartment: table.div(table.sum(axis=0), axis=1)
        for compartment, table in grouped.items()
    }
    pooled_mean = sum(relative.values()) / len(relative)
    ranking = (
        pooled_mean.mean(axis=1)
        .loc[eligible_names]
        .sort_values(ascending=False, kind="mergesort")
    )
    all_ranked = list(ranking.index)
    selected = all_ranked[:maximum_taxa]

    rows: list[dict[str, Any]] = []
    rank_lookup = {name: index + 1 for index, name in enumerate(ranking.index)}
    for genus in sorted(grouped[COMPARTMENTS[0]].index):
        rows.append(
            {
                "genus": genus,
                "prevalence_surface": prevalence["Surface"].loc[genus],
                "prevalence_deep": prevalence["Deep"].loc[genus],
                "prevalence_rhizosphere": prevalence["Rhizosphere"].loc[genus],
                "mean_relative_abundance": pooled_mean.mean(axis=1).loc[genus],
                "passes_common_prevalence": genus in ranking.index,
                "abundance_rank_among_eligible": rank_lookup.get(genus),
                "selected_primary": genus in selected[:primary_taxa_count],
                "selected_sensitivity_pool": genus in selected,
            }
        )
    return all_ranked, rows


def campaign_centered_clr(
    table: pd.DataFrame,
    taxa: Sequence[str],
    campaigns: np.ndarray,
    pseudocount: float,
) -> np.ndarray:
    counts = table.loc[list(taxa)].T.to_numpy(dtype=float)
    log_counts = np.log(counts + pseudocount)
    clr = log_counts - log_counts.mean(axis=1, keepdims=True)
    for campaign in np.unique(campaigns):
        indices = np.where(campaigns == campaign)[0]
        clr[indices] -= clr[indices].mean(axis=0, keepdims=True)
    return standardize(clr)


def standardize(matrix: np.ndarray) -> np.ndarray:
    centered = matrix - matrix.mean(axis=0, keepdims=True)
    scale = centered.std(axis=0, ddof=1)
    if np.any(scale <= 1e-10):
        bad = np.where(scale <= 1e-10)[0]
        raise ValueError(f"Invariant selected taxa at column indices {bad.tolist()}")
    return centered / scale


def partial_correlation(precision: np.ndarray) -> np.ndarray:
    diagonal = np.diag(precision)
    denominator = np.sqrt(np.outer(diagonal, diagonal))
    result = -precision / denominator
    np.fill_diagonal(result, 0.0)
    return result


def fit_network(
    matrix: np.ndarray,
    alpha: float,
    edge_tolerance: float,
    maximum_iterations: int,
    convergence_tolerance: float,
) -> FitResult:
    values = standardize(matrix)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", ConvergenceWarning)
        model = GraphicalLasso(
            alpha=alpha,
            max_iter=maximum_iterations,
            tol=convergence_tolerance,
            assume_centered=True,
        ).fit(values)
    partial = partial_correlation(model.precision_)
    selected = np.abs(partial) > edge_tolerance
    np.fill_diagonal(selected, False)
    return FitResult(
        partial=partial,
        selected=selected,
        convergence_warnings=sum(
            issubclass(item.category, ConvergenceWarning) for item in caught
        ),
    )


def independent_taxon_permutation(
    matrix: np.ndarray,
    campaigns: np.ndarray,
    rng: np.random.Generator,
) -> np.ndarray:
    """Independently permute every taxon within each campaign."""
    permuted = matrix.copy()
    for column in range(matrix.shape[1]):
        for campaign in np.unique(campaigns):
            indices = np.where(campaigns == campaign)[0]
            permuted[indices, column] = matrix[
                rng.permutation(indices), column
            ]
    return permuted


def edge_summary(
    result: FitResult,
    upper: tuple[np.ndarray, np.ndarray],
) -> dict[str, Any]:
    selected = result.selected[upper]
    values = result.partial[upper][selected]
    edge_count = int(selected.sum())
    possible = len(upper[0])
    return {
        "edge_count": edge_count,
        "density": edge_count / possible,
        "positive_fraction": (
            float((values > 0).mean()) if edge_count else None
        ),
        "median_absolute_partial_correlation": (
            float(np.median(np.abs(values))) if edge_count else None
        ),
        "convergence_warnings": result.convergence_warnings,
    }


def calibrate_alpha(
    matrices: Mapping[str, np.ndarray],
    campaigns: np.ndarray,
    alpha_grid: Sequence[float],
    null_replicates: int,
    seed: int,
    edge_tolerance: float,
    maximum_iterations: int,
    convergence_tolerance: float,
    maximum_null_edge_ratio: float,
    minimum_observed_edges_per_compartment: int,
) -> tuple[float, list[dict[str, Any]], dict[str, Any]]:
    taxa_count = next(iter(matrices.values())).shape[1]
    upper = np.triu_indices(taxa_count, 1)
    observed: dict[tuple[float, str], dict[str, Any]] = {}
    null_counts: dict[tuple[float, str], list[int]] = defaultdict(list)
    warning_counts: Counter[tuple[float, str, str]] = Counter()

    for alpha in alpha_grid:
        for compartment in COMPARTMENTS:
            result = fit_network(
                matrices[compartment],
                alpha,
                edge_tolerance,
                maximum_iterations,
                convergence_tolerance,
            )
            observed[(alpha, compartment)] = edge_summary(result, upper)
            warning_counts[(alpha, compartment, "observed")] += (
                result.convergence_warnings
            )

    rng = np.random.default_rng(seed)
    for _ in range(null_replicates):
        for compartment in COMPARTMENTS:
            permuted = independent_taxon_permutation(
                matrices[compartment], campaigns, rng
            )
            for alpha in alpha_grid:
                result = fit_network(
                    permuted,
                    alpha,
                    edge_tolerance,
                    maximum_iterations,
                    convergence_tolerance,
                )
                null_counts[(alpha, compartment)].append(
                    int(result.selected[upper].sum())
                )
                warning_counts[(alpha, compartment, "null")] += (
                    result.convergence_warnings
                )

    rows: list[dict[str, Any]] = []
    combined_by_alpha: dict[float, dict[str, Any]] = {}
    for alpha in alpha_grid:
        observed_total = 0
        null_total = 0.0
        each_has_minimum = True
        for compartment in COMPARTMENTS:
            obs = observed[(alpha, compartment)]
            null = null_counts[(alpha, compartment)]
            observed_total += obs["edge_count"]
            null_total += float(np.mean(null))
            each_has_minimum &= (
                obs["edge_count"] >= minimum_observed_edges_per_compartment
            )
            rows.append(
                {
                    "alpha": alpha,
                    "scope": compartment,
                    "observed_edges": obs["edge_count"],
                    "observed_density": obs["density"],
                    "null_replicates": len(null),
                    "null_mean_edges": float(np.mean(null)),
                    "null_median_edges": float(np.median(null)),
                    "null_q95_edges": float(np.quantile(null, 0.95)),
                    "null_to_observed_edge_ratio": (
                        float(np.mean(null)) / obs["edge_count"]
                        if obs["edge_count"]
                        else None
                    ),
                    "observed_convergence_warnings": warning_counts[
                        (alpha, compartment, "observed")
                    ],
                    "null_convergence_warnings": warning_counts[
                        (alpha, compartment, "null")
                    ],
                    "passes_global_selection_rule": False,
                }
            )
        ratio = null_total / observed_total if observed_total else math.inf
        combined_by_alpha[alpha] = {
            "observed_edges": observed_total,
            "null_mean_edges": null_total,
            "ratio": ratio,
            "each_has_minimum": each_has_minimum,
        }
        rows.append(
            {
                "alpha": alpha,
                "scope": "ALL_COMPARTMENTS",
                "observed_edges": observed_total,
                "observed_density": None,
                "null_replicates": null_replicates,
                "null_mean_edges": null_total,
                "null_median_edges": None,
                "null_q95_edges": None,
                "null_to_observed_edge_ratio": ratio,
                "observed_convergence_warnings": sum(
                    warning_counts[(alpha, compartment, "observed")]
                    for compartment in COMPARTMENTS
                ),
                "null_convergence_warnings": sum(
                    warning_counts[(alpha, compartment, "null")]
                    for compartment in COMPARTMENTS
                ),
                "passes_global_selection_rule": (
                    ratio <= maximum_null_edge_ratio and each_has_minimum
                ),
            }
        )

    passing = [
        alpha
        for alpha in sorted(alpha_grid)
        if combined_by_alpha[alpha]["ratio"] <= maximum_null_edge_ratio
        and combined_by_alpha[alpha]["each_has_minimum"]
    ]
    if passing:
        selected_alpha = passing[0]
        selection_status = "calibrated"
    else:
        selected_alpha = max(alpha_grid)
        selection_status = "no_alpha_met_null_calibration"
    for row in rows:
        if math.isclose(float(row["alpha"]), selected_alpha):
            row["selected_alpha"] = True
        else:
            row["selected_alpha"] = False
    return selected_alpha, rows, {
        "status": selection_status,
        "selected_alpha": selected_alpha,
        "selected_combined_null_edge_ratio": combined_by_alpha[selected_alpha][
            "ratio"
        ],
    }


def final_null_selection(
    matrices: Mapping[str, np.ndarray],
    campaigns: np.ndarray,
    alpha: float,
    replicates: int,
    seed: int,
    edge_tolerance: float,
    maximum_iterations: int,
    convergence_tolerance: float,
) -> tuple[dict[str, np.ndarray], dict[str, list[int]], int]:
    taxa_count = next(iter(matrices.values())).shape[1]
    counts = {
        compartment: np.zeros((taxa_count, taxa_count), dtype=int)
        for compartment in COMPARTMENTS
    }
    edge_counts = {compartment: [] for compartment in COMPARTMENTS}
    warnings_total = 0
    rng = np.random.default_rng(seed)
    upper = np.triu_indices(taxa_count, 1)
    for _ in range(replicates):
        for compartment in COMPARTMENTS:
            permuted = independent_taxon_permutation(
                matrices[compartment], campaigns, rng
            )
            result = fit_network(
                permuted,
                alpha,
                edge_tolerance,
                maximum_iterations,
                convergence_tolerance,
            )
            counts[compartment] += result.selected.astype(int)
            edge_counts[compartment].append(
                int(result.selected[upper].sum())
            )
            warnings_total += result.convergence_warnings
    frequencies = {
        compartment: counts[compartment] / replicates
        for compartment in COMPARTMENTS
    }
    return frequencies, edge_counts, warnings_total


def site_cluster_bootstrap(
    matrices: Mapping[str, np.ndarray],
    sites: np.ndarray,
    alpha: float,
    replicates: int,
    seed: int,
    edge_tolerance: float,
    maximum_iterations: int,
    convergence_tolerance: float,
) -> tuple[
    dict[str, np.ndarray],
    dict[str, np.ndarray],
    list[dict[str, Any]],
    int,
]:
    taxa_count = next(iter(matrices.values())).shape[1]
    selection = {
        compartment: np.zeros((taxa_count, taxa_count), dtype=int)
        for compartment in COMPARTMENTS
    }
    positive = {
        compartment: np.zeros((taxa_count, taxa_count), dtype=int)
        for compartment in COMPARTMENTS
    }
    rows: list[dict[str, Any]] = []
    warnings_total = 0
    rng = np.random.default_rng(seed)
    unique_sites = np.unique(sites)
    upper = np.triu_indices(taxa_count, 1)
    for replicate in range(replicates):
        drawn_sites = rng.choice(
            unique_sites, size=len(unique_sites), replace=True
        )
        indices = np.concatenate(
            [np.where(sites == site)[0] for site in drawn_sites]
        )
        for compartment in COMPARTMENTS:
            result = fit_network(
                matrices[compartment][indices],
                alpha,
                edge_tolerance,
                maximum_iterations,
                convergence_tolerance,
            )
            selection[compartment] += result.selected.astype(int)
            positive[compartment] += (
                result.selected & (result.partial > 0)
            ).astype(int)
            summary = edge_summary(result, upper)
            rows.append(
                {
                    "bootstrap_replicate": replicate,
                    "compartment": compartment,
                    "drawn_site_clusters": len(drawn_sites),
                    "bootstrap_observations": len(indices),
                    **summary,
                }
            )
            warnings_total += result.convergence_warnings
    stability = {
        compartment: selection[compartment] / replicates
        for compartment in COMPARTMENTS
    }
    return stability, positive, rows, warnings_total


def build_edge_and_metric_tables(
    taxa: Sequence[str],
    full_results: Mapping[str, FitResult],
    bootstrap_stability: Mapping[str, np.ndarray],
    bootstrap_positive: Mapping[str, np.ndarray],
    null_frequency: Mapping[str, np.ndarray],
    bootstrap_replicates: int,
    stability_threshold: float,
    sign_consistency_threshold: float,
    maximum_edge_null_frequency: float,
    alpha: float,
    observation_count: int,
    site_count: int,
    null_edge_counts: Mapping[str, Sequence[int]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, np.ndarray]]:
    upper = np.triu_indices(len(taxa), 1)
    edge_rows: list[dict[str, Any]] = []
    metric_rows: list[dict[str, Any]] = []
    stable_masks: dict[str, np.ndarray] = {}
    for compartment in COMPARTMENTS:
        result = full_results[compartment]
        selected_count = np.rint(
            bootstrap_stability[compartment] * bootstrap_replicates
        ).astype(int)
        positive_count = bootstrap_positive[compartment]
        full_positive = result.partial > 0
        same_sign_count = np.where(
            full_positive,
            positive_count,
            selected_count - positive_count,
        )
        sign_consistency = np.divide(
            same_sign_count,
            selected_count,
            out=np.zeros_like(same_sign_count, dtype=float),
            where=selected_count > 0,
        )
        stable = (
            result.selected
            & (bootstrap_stability[compartment] >= stability_threshold)
            & (sign_consistency >= sign_consistency_threshold)
            & (null_frequency[compartment] <= maximum_edge_null_frequency)
        )
        stable_masks[compartment] = stable
        for left, right in zip(*upper):
            edge_rows.append(
                {
                    "compartment": compartment,
                    "taxon_a": taxa[left],
                    "taxon_b": taxa[right],
                    "partial_correlation": result.partial[left, right],
                    "absolute_partial_correlation": abs(
                        result.partial[left, right]
                    ),
                    "full_data_selected": bool(result.selected[left, right]),
                    "bootstrap_selection_probability": bootstrap_stability[
                        compartment
                    ][left, right],
                    "bootstrap_sign_consistency_with_full": sign_consistency[
                        left, right
                    ],
                    "null_selection_probability": null_frequency[compartment][
                        left, right
                    ],
                    "stable_edge": bool(stable[left, right]),
                }
            )

        raw_summary = edge_summary(result, upper)
        stable_values = result.partial[upper][stable[upper]]
        stable_count = int(stable[upper].sum())
        expected_false = float(
            null_frequency[compartment][upper][stable[upper]].sum()
        )
        possible = len(upper[0])
        metric_rows.append(
            {
                "compartment": compartment,
                "observations": observation_count,
                "unique_sites": site_count,
                "taxa": len(taxa),
                "alpha": alpha,
                "raw_edges": raw_summary["edge_count"],
                "raw_density": raw_summary["density"],
                "raw_positive_fraction": raw_summary["positive_fraction"],
                "null_mean_edges": float(
                    np.mean(null_edge_counts[compartment])
                ),
                "null_q95_edges": float(
                    np.quantile(null_edge_counts[compartment], 0.95)
                ),
                "null_to_raw_edge_ratio": (
                    float(np.mean(null_edge_counts[compartment]))
                    / raw_summary["edge_count"]
                    if raw_summary["edge_count"]
                    else None
                ),
                "stable_edges": stable_count,
                "stable_density": stable_count / possible,
                "stable_positive_fraction": (
                    float((stable_values > 0).mean())
                    if stable_count
                    else None
                ),
                "stable_median_absolute_partial_correlation": (
                    float(np.median(np.abs(stable_values)))
                    if stable_count
                    else None
                ),
                "expected_false_stable_edges": expected_false,
                "expected_false_fraction_among_stable": (
                    expected_false / stable_count if stable_count else None
                ),
                "full_fit_convergence_warnings": (
                    result.convergence_warnings
                ),
            }
        )
    return edge_rows, metric_rows, stable_masks


def sensitivity_analysis(
    grouped: Mapping[str, pd.DataFrame],
    ranking: Sequence[str],
    campaigns: np.ndarray,
    selected_alpha: float,
    taxa_counts: Sequence[int],
    alpha_multipliers: Sequence[float],
    null_replicates: int,
    seed: int,
    pseudocount: float,
    edge_tolerance: float,
    maximum_iterations: int,
    convergence_tolerance: float,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    rng = np.random.default_rng(seed)
    for taxa_count_requested in sorted(set(taxa_counts)):
        taxa_count = min(taxa_count_requested, len(ranking))
        taxa = list(ranking[:taxa_count])
        matrices = {
            compartment: campaign_centered_clr(
                grouped[compartment], taxa, campaigns, pseudocount
            )
            for compartment in COMPARTMENTS
        }
        upper = np.triu_indices(taxa_count, 1)
        for multiplier in sorted(set(alpha_multipliers)):
            alpha = selected_alpha * multiplier
            observed: dict[str, int] = {}
            for compartment in COMPARTMENTS:
                result = fit_network(
                    matrices[compartment],
                    alpha,
                    edge_tolerance,
                    maximum_iterations,
                    convergence_tolerance,
                )
                observed[compartment] = int(result.selected[upper].sum())
            null_counts = {
                compartment: [] for compartment in COMPARTMENTS
            }
            for _ in range(null_replicates):
                for compartment in COMPARTMENTS:
                    permuted = independent_taxon_permutation(
                        matrices[compartment], campaigns, rng
                    )
                    result = fit_network(
                        permuted,
                        alpha,
                        edge_tolerance,
                        maximum_iterations,
                        convergence_tolerance,
                    )
                    null_counts[compartment].append(
                        int(result.selected[upper].sum())
                    )
            possible = len(upper[0])
            for compartment in COMPARTMENTS:
                null_mean = float(np.mean(null_counts[compartment]))
                rows.append(
                    {
                        "requested_taxa": taxa_count_requested,
                        "taxa": taxa_count,
                        "alpha_multiplier": multiplier,
                        "alpha": alpha,
                        "compartment": compartment,
                        "observed_edges": observed[compartment],
                        "observed_density": observed[compartment] / possible,
                        "null_replicates": null_replicates,
                        "null_mean_edges": null_mean,
                        "null_to_observed_edge_ratio": (
                            null_mean / observed[compartment]
                            if observed[compartment]
                            else None
                        ),
                    }
                )
    return rows


def compartment_comparisons(
    metrics: Sequence[Mapping[str, Any]],
    bootstrap_rows: Sequence[Mapping[str, Any]],
    stable_masks: Mapping[str, np.ndarray],
    sensitivity_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    metric = {row["compartment"]: row for row in metrics}
    bootstrap = pd.DataFrame(bootstrap_rows)
    sensitivity = pd.DataFrame(sensitivity_rows)
    pairs = (
        ("Surface", "Deep"),
        ("Surface", "Rhizosphere"),
        ("Deep", "Rhizosphere"),
    )
    rows: list[dict[str, Any]] = []
    for left, right in pairs:
        left_boot = (
            bootstrap[bootstrap["compartment"] == left]
            .sort_values("bootstrap_replicate")["density"]
            .to_numpy()
        )
        right_boot = (
            bootstrap[bootstrap["compartment"] == right]
            .sort_values("bootstrap_replicate")["density"]
            .to_numpy()
        )
        differences = left_boot - right_boot
        left_edges = stable_masks[left][np.triu_indices_from(stable_masks[left], 1)]
        right_edges = stable_masks[right][
            np.triu_indices_from(stable_masks[right], 1)
        ]
        union = int((left_edges | right_edges).sum())
        intersection = int((left_edges & right_edges).sum())

        config_directions: list[int] = []
        for _, config in sensitivity.groupby(
            ["requested_taxa", "alpha_multiplier"], sort=True
        ):
            density = {
                row.compartment: float(row.observed_density)
                for row in config.itertuples()
            }
            delta = density[left] - density[right]
            config_directions.append(int(np.sign(delta)))
        primary_delta = (
            float(metric[left]["raw_density"])
            - float(metric[right]["raw_density"])
        )
        primary_sign = int(np.sign(primary_delta))
        same_direction = (
            sum(direction == primary_sign for direction in config_directions)
            / len(config_directions)
            if primary_sign and config_directions
            else 0.0
        )
        ci_low, ci_high = np.quantile(differences, [0.025, 0.975])
        ci_excludes_zero = bool(ci_low > 0 or ci_high < 0)
        robust_direction = same_direction >= 0.8
        supported = ci_excludes_zero and robust_direction
        rows.append(
            {
                "compartment_a": left,
                "compartment_b": right,
                "raw_density_difference_a_minus_b": primary_delta,
                "bootstrap_median_density_difference": float(
                    np.median(differences)
                ),
                "bootstrap_ci_low": float(ci_low),
                "bootstrap_ci_high": float(ci_high),
                "bootstrap_probability_a_greater_b": float(
                    np.mean(differences > 0)
                ),
                "stable_edges_a": metric[left]["stable_edges"],
                "stable_edges_b": metric[right]["stable_edges"],
                "stable_edge_intersection": intersection,
                "stable_edge_union": union,
                "stable_edge_jaccard": (
                    intersection / union if union else None
                ),
                "sensitivity_configurations": len(config_directions),
                "fraction_same_density_direction_as_primary": same_direction,
                "bootstrap_ci_excludes_zero": ci_excludes_zero,
                "direction_robust_across_sensitivity": robust_direction,
                "comparative_density_supported": supported,
            }
        )
    return rows


def campaign_feasibility_rows(
    matched_keys: Sequence[tuple[int, int]],
    taxa_count: int,
) -> list[dict[str, Any]]:
    counts = Counter(campaign for campaign, _ in matched_keys)
    minimum = max(50, taxa_count)
    rows: list[dict[str, Any]] = []
    for campaign in range(1, 6):
        count = counts[campaign]
        eligible = count >= minimum
        rows.append(
            {
                "campaign": campaign,
                "matched_observations_per_compartment": count,
                "primary_taxa": taxa_count,
                "minimum_observations_rule": minimum,
                "network_estimated": False,
                "reason": (
                    "Not estimated: all five campaigns must meet the same "
                    "predeclared observation rule for a campaign comparison."
                    if not eligible
                    else "Individually eligible, but comparison not estimated "
                    "because other campaigns fail the common rule."
                ),
            }
        )
    return rows


def build_verdict(
    calibration: Mapping[str, Any],
    metrics: Sequence[Mapping[str, Any]],
    comparisons: Sequence[Mapping[str, Any]],
    campaign_counts: Mapping[int, int],
    minimum_stable_edges: int,
    maximum_false_fraction: float,
) -> dict[str, Any]:
    calibrated = calibration["status"] == "calibrated"

    def false_fraction_passes(row: Mapping[str, Any]) -> bool:
        value = row["expected_false_fraction_among_stable"]
        return (
            value is not None
            and math.isfinite(float(value))
            and float(value) <= maximum_false_fraction
        )

    stable_supported = all(
        int(row["stable_edges"]) >= minimum_stable_edges
        and false_fraction_passes(row)
        for row in metrics
    )
    supported_comparisons = [
        row
        for row in comparisons
        if row["comparative_density_supported"]
    ]
    if calibrated and stable_supported and supported_comparisons:
        descriptive_status = "limited_compartment_density_difference"
        permitted = (
            "Null-calibrated conditional-association networks contained stable "
            "edges in each compartment, and a matched compartment density "
            "contrast passed bootstrap and sensitivity gates. Report only the "
            "specific contrast and its uncertainty."
        )
    elif calibrated and stable_supported:
        descriptive_status = "stable_associations_without_robust_density_ordering"
        permitted = (
            "Stable null-calibrated conditional associations were recoverable "
            "within each compartment, but comparative network density ordering "
            "was not robust."
        )
    else:
        descriptive_status = "network_not_recoverable"
        permitted = (
            "No network result passed the combined null-calibration and stability "
            "criteria."
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "original_claim": (
            "Compartment/season network complexity, resilience, and hub-taxon "
            "interpretation from thresholded Spearman correlations"
        ),
        "original_claim_status": "retire",
        "descriptive_association_status": descriptive_status,
        "permitted_wording": permitted,
        "campaign_comparison_status": "not_estimable",
        "campaign_reason": (
            "Matched campaign sizes are "
            + ", ".join(
                str(int(campaign_counts.get(campaign, 0)))
                for campaign in range(1, 6)
            )
            + "; no common "
            "campaign-specific network comparison meets the predeclared "
            "observation rule. Campaigns were not pooled into wet/dry labels."
        ),
        "mechanistic_interpretation_permitted": False,
        "comparative_density_contrasts_passing": len(supported_comparisons),
        "calibration_status": calibration["status"],
        "selected_alpha": calibration["selected_alpha"],
        "selected_combined_null_edge_ratio": calibration[
            "selected_combined_null_edge_ratio"
        ],
        "minimum_stable_edges_gate": minimum_stable_edges,
        "maximum_expected_false_fraction_gate": maximum_false_fraction,
        "stable_network_gate_passed": stable_supported,
        "reason": (
            "The original near-all-positive pattern and comparative density "
            "ordering were not supported by the matched compositional analysis, "
            "and a campaign/season comparison was not estimable. Only "
            "null-calibrated, site-cluster-stable conditional associations are "
            "retained descriptively."
        ),
    }


def render_readme(
    parameters: Mapping[str, Any],
    info: Mapping[str, Any],
    metrics: Sequence[Mapping[str, Any]],
    comparisons: Sequence[Mapping[str, Any]],
    verdict: Mapping[str, Any],
) -> str:
    lines = [
        "# Network-claim rescue",
        "",
        "## Verdict",
        "",
        f"**Original claim: {verdict['original_claim_status'].upper()}.** "
        f"{verdict['permitted_wording']}",
        "",
        "Campaign-specific networks were not estimated, and campaigns were not "
        "collapsed into wet/dry labels. Conditional associations are descriptive "
        "and do not establish a biological mechanism.",
        "",
        "## Cohort and method",
        "",
        f"- Input: `{parameters['input_table']}` "
        f"(SHA-256 `{parameters['input_sha256']}`).",
        f"- Core sites: 1--60; sequencing replicates summed within "
        "campaign × site × compartment.",
        f"- Read-depth QC: aggregate library size ≥"
        f"{parameters['minimum_group_reads']:.0f}; unnamed genus rows excluded: "
        f"{info['excluded_missing_genus_labels']}.",
        f"- Exact matched cohort: "
        f"{info['matched_observations_per_compartment']} observations in each "
        f"compartment across {info['matched_unique_sites']} sites.",
        f"- Campaign counts: {info['matched_campaign_counts']}.",
        f"- Common prevalence threshold: "
        f"{parameters['prevalence_threshold']}; primary taxa: "
        f"{parameters['taxa_count']}.",
        "- Transform: CLR with a fixed pseudocount, followed by within-campaign "
        "centering and taxon standardization.",
        "- Model: a common-alpha GraphicalLasso conditional-dependence network.",
        f"- Numerical nonzero threshold: absolute partial correlation >"
        f"{parameters['edge_tolerance']:.4g}; solver tolerance "
        f"{parameters['convergence_tolerance']:.4g}.",
        f"- Alpha: {verdict['selected_alpha']}; combined permuted-null/raw edge "
        f"ratio: {verdict['selected_combined_null_edge_ratio']:.3f}.",
        f"- Stability: {parameters['bootstrap_replicates']} site-cluster "
        f"bootstraps; edge threshold ≥{parameters['stability_threshold']:.2f}, "
        f"sign consistency ≥{parameters['sign_consistency_threshold']:.2f}, "
        f"null selection frequency ≤"
        f"{parameters['maximum_edge_null_frequency']:.2f}.",
        "",
        "## Primary compartment results",
        "",
        "| Compartment | Raw edges | Null mean | Stable edges | Stable density | "
        "Positive stable fraction | Expected false fraction |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in metrics:
        lines.append(
            f"| {row['compartment']} | {row['raw_edges']} | "
            f"{row['null_mean_edges']:.1f} | {row['stable_edges']} | "
            f"{row['stable_density']:.4f} | "
            f"{format_cell(row['stable_positive_fraction'])} | "
            f"{format_cell(row['expected_false_fraction_among_stable'])} |"
        )
    lines.extend(
        [
            "",
            "## Matched compartment contrasts",
            "",
            "| A | B | Raw density Δ | Bootstrap 95% interval | "
            "Sensitivity direction | Pass |",
            "|---|---|---:|---:|---:|---|",
        ]
    )
    for row in comparisons:
        lines.append(
            f"| {row['compartment_a']} | {row['compartment_b']} | "
            f"{row['raw_density_difference_a_minus_b']:.4f} | "
            f"[{row['bootstrap_ci_low']:.4f}, "
            f"{row['bootstrap_ci_high']:.4f}] | "
            f"{row['fraction_same_density_direction_as_primary']:.2f} | "
            f"{format_cell(row['comparative_density_supported'])} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation boundary",
            "",
            "Edge signs and selection frequencies describe regularized conditional "
            "associations under this dataset and model. Node-degree labels, "
            "resilience claims, mutual-dependence claims, and environmental "
            "mechanisms are outside the evidence.",
            "Permuted-null selection probabilities are stability diagnostics, "
            "not a formal false-discovery-rate estimate.",
            "",
            "## Reproduction",
            "",
            "```bash",
            f"uv run --with 'numpy=="
            f"{parameters['software_versions']['numpy']}' \\",
            f"  --with 'pandas=="
            f"{parameters['software_versions']['pandas']}' \\",
            f"  --with 'scikit-learn=="
            f"{parameters['software_versions']['scikit_learn']}' \\",
            "  python analysis/v3/network_rescue/run_network_rescue.py \\",
            "  --project-root . \\",
            "  --output-dir analysis/v3/network_rescue/results",
            "```",
            "",
            "All seeds, thresholds, and counts are recorded in `parameters.json`. "
            "Outputs contain no run timestamp and are byte-deterministic for fixed "
            "inputs and dependency versions.",
            "",
        ]
    )
    return "\n".join(lines)


def run_analysis(
    project_root: Path,
    input_table: Path,
    output_dir: Path,
    *,
    seed: int = 20260723,
    minimum_group_reads: float = 2000.0,
    prevalence_threshold: float = 0.20,
    taxa_count: int = 80,
    pseudocount: float = 0.5,
    alpha_grid: Sequence[float] = (
        0.05,
        0.075,
        0.10,
        0.125,
        0.15,
        0.175,
        0.20,
        0.25,
        0.30,
    ),
    calibration_null_replicates: int = 25,
    null_replicates: int = 100,
    bootstrap_replicates: int = 200,
    sensitivity_taxa: Sequence[int] = (50, 80, 100),
    sensitivity_alpha_multipliers: Sequence[float] = (0.8, 1.0, 1.25),
    sensitivity_null_replicates: int = 30,
    maximum_null_edge_ratio: float = 0.10,
    stability_threshold: float = 0.80,
    sign_consistency_threshold: float = 0.90,
    maximum_edge_null_frequency: float = 0.05,
    minimum_stable_edges: int = 10,
    maximum_expected_false_fraction: float = 0.10,
    edge_tolerance: float = 1e-3,
    maximum_iterations: int = 2000,
    convergence_tolerance: float = 2e-4,
) -> dict[str, Any]:
    project_root = project_root.resolve()
    input_path = (
        input_table.resolve()
        if input_table.is_absolute()
        else (project_root / input_table).resolve()
    )
    output_path = (
        output_dir.resolve()
        if output_dir.is_absolute()
        else (project_root / output_dir).resolve()
    )
    output_path.mkdir(parents=True, exist_ok=True)

    if not 0 < prevalence_threshold <= 1:
        raise ValueError("prevalence_threshold must be in (0, 1]")
    if taxa_count < 2:
        raise ValueError("taxa_count must be at least 2")
    if any(count < 2 for count in sensitivity_taxa):
        raise ValueError("sensitivity_taxa values must be at least 2")
    if pseudocount <= 0:
        raise ValueError("pseudocount must be positive")
    if any(alpha <= 0 for alpha in alpha_grid):
        raise ValueError("alpha_grid values must be positive")
    if calibration_null_replicates < 1:
        raise ValueError("calibration_null_replicates must be positive")
    if null_replicates < 1 or bootstrap_replicates < 1:
        raise ValueError("null and bootstrap replicate counts must be positive")
    if sensitivity_null_replicates < 1:
        raise ValueError("sensitivity_null_replicates must be positive")
    if convergence_tolerance <= 0:
        raise ValueError("convergence_tolerance must be positive")

    (
        grouped,
        matched_keys,
        cohort_rows,
        cohort_group_rows,
        cohort_info,
    ) = load_aggregated_counts(input_path, minimum_group_reads)
    maximum_requested_taxa = max([taxa_count, *sensitivity_taxa])
    ranking, taxa_rows = select_taxa(
        grouped,
        prevalence_threshold,
        maximum_requested_taxa,
        taxa_count,
    )
    if len(ranking) < taxa_count:
        raise ValueError(
            f"Only {len(ranking)} taxa passed filtering; requested {taxa_count}"
        )
    if len(ranking) < maximum_requested_taxa:
        raise ValueError(
            f"Only {len(ranking)} taxa passed filtering; sensitivity analysis "
            f"requests {maximum_requested_taxa}"
        )
    primary_taxa = ranking[:taxa_count]
    campaigns = np.array([campaign for campaign, _ in matched_keys], dtype=int)
    sites = np.array([site for _, site in matched_keys], dtype=int)
    matrices = {
        compartment: campaign_centered_clr(
            grouped[compartment],
            primary_taxa,
            campaigns,
            pseudocount,
        )
        for compartment in COMPARTMENTS
    }

    selected_alpha, calibration_rows, calibration = calibrate_alpha(
        matrices,
        campaigns,
        sorted(set(alpha_grid)),
        calibration_null_replicates,
        seed + 101,
        edge_tolerance,
        maximum_iterations,
        convergence_tolerance,
        maximum_null_edge_ratio,
        minimum_stable_edges,
    )
    full_results = {
        compartment: fit_network(
            matrices[compartment],
            selected_alpha,
            edge_tolerance,
            maximum_iterations,
            convergence_tolerance,
        )
        for compartment in COMPARTMENTS
    }
    null_frequency, null_edge_counts, final_null_warnings = final_null_selection(
        matrices,
        campaigns,
        selected_alpha,
        null_replicates,
        seed + 202,
        edge_tolerance,
        maximum_iterations,
        convergence_tolerance,
    )
    (
        bootstrap_stability,
        bootstrap_positive,
        bootstrap_rows,
        bootstrap_warnings,
    ) = site_cluster_bootstrap(
        matrices,
        sites,
        selected_alpha,
        bootstrap_replicates,
        seed + 303,
        edge_tolerance,
        maximum_iterations,
        convergence_tolerance,
    )
    edge_rows, metric_rows, stable_masks = build_edge_and_metric_tables(
        primary_taxa,
        full_results,
        bootstrap_stability,
        bootstrap_positive,
        null_frequency,
        bootstrap_replicates,
        stability_threshold,
        sign_consistency_threshold,
        maximum_edge_null_frequency,
        selected_alpha,
        len(matched_keys),
        len(np.unique(sites)),
        null_edge_counts,
    )
    sensitivity_rows = sensitivity_analysis(
        grouped,
        ranking,
        campaigns,
        selected_alpha,
        sensitivity_taxa,
        sensitivity_alpha_multipliers,
        sensitivity_null_replicates,
        seed + 404,
        pseudocount,
        edge_tolerance,
        maximum_iterations,
        convergence_tolerance,
    )
    comparison_rows = compartment_comparisons(
        metric_rows,
        bootstrap_rows,
        stable_masks,
        sensitivity_rows,
    )
    campaign_rows = campaign_feasibility_rows(matched_keys, taxa_count)
    campaign_counts = Counter(campaign for campaign, _ in matched_keys)
    verdict = build_verdict(
        calibration,
        metric_rows,
        comparison_rows,
        campaign_counts,
        minimum_stable_edges,
        maximum_expected_false_fraction,
    )

    parameters = {
        "schema_version": SCHEMA_VERSION,
        "software_versions": {
            "numpy": np.__version__,
            "pandas": pd.__version__,
            "scikit_learn": sklearn.__version__,
        },
        "input_table": (
            str(input_path.relative_to(project_root))
            if input_path.is_relative_to(project_root)
            else str(input_path)
        ),
        "input_sha256": sha256_file(input_path),
        "seed": seed,
        "phase_seeds": {
            "alpha_calibration": seed + 101,
            "final_null": seed + 202,
            "site_cluster_bootstrap": seed + 303,
            "sensitivity": seed + 404,
        },
        "minimum_group_reads": minimum_group_reads,
        "prevalence_threshold": prevalence_threshold,
        "taxa_count": taxa_count,
        "eligible_taxa_ranked": len(ranking),
        "pseudocount": pseudocount,
        "alpha_grid": list(sorted(set(alpha_grid))),
        "selected_alpha": selected_alpha,
        "calibration_null_replicates": calibration_null_replicates,
        "null_replicates": null_replicates,
        "bootstrap_replicates": bootstrap_replicates,
        "sensitivity_taxa": list(sensitivity_taxa),
        "sensitivity_alpha_multipliers": list(
            sensitivity_alpha_multipliers
        ),
        "sensitivity_null_replicates": sensitivity_null_replicates,
        "maximum_null_edge_ratio": maximum_null_edge_ratio,
        "stability_threshold": stability_threshold,
        "sign_consistency_threshold": sign_consistency_threshold,
        "maximum_edge_null_frequency": maximum_edge_null_frequency,
        "minimum_stable_edges": minimum_stable_edges,
        "maximum_expected_false_fraction": maximum_expected_false_fraction,
        "edge_tolerance": edge_tolerance,
        "maximum_iterations": maximum_iterations,
        "convergence_tolerance": convergence_tolerance,
        "final_null_convergence_warnings": final_null_warnings,
        "bootstrap_convergence_warnings": bootstrap_warnings,
        "cohort": cohort_info,
    }

    write_tsv(
        output_path / "cohort_accounting.tsv",
        cohort_rows,
        [
            "stage",
            "campaign",
            "compartment",
            "sample_columns",
            "site_campaign_groups",
            "groups_passing_read_qc",
            "groups_in_final_matched_cohort",
        ],
    )
    write_tsv(
        output_path / "cohort_groups.tsv",
        cohort_group_rows,
        [
            "campaign",
            "site",
            "compartment",
            "sequencing_replicates",
            "aggregate_library_size",
            "passes_read_qc",
            "in_exact_matched_cohort",
        ],
    )
    write_tsv(
        output_path / "taxa_selection.tsv",
        taxa_rows,
        [
            "genus",
            "prevalence_surface",
            "prevalence_deep",
            "prevalence_rhizosphere",
            "mean_relative_abundance",
            "passes_common_prevalence",
            "abundance_rank_among_eligible",
            "selected_primary",
            "selected_sensitivity_pool",
        ],
    )
    write_tsv(
        output_path / "alpha_calibration.tsv",
        calibration_rows,
        [
            "alpha",
            "scope",
            "observed_edges",
            "observed_density",
            "null_replicates",
            "null_mean_edges",
            "null_median_edges",
            "null_q95_edges",
            "null_to_observed_edge_ratio",
            "observed_convergence_warnings",
            "null_convergence_warnings",
            "passes_global_selection_rule",
            "selected_alpha",
        ],
    )
    write_tsv(
        output_path / "network_edges.tsv",
        edge_rows,
        [
            "compartment",
            "taxon_a",
            "taxon_b",
            "partial_correlation",
            "absolute_partial_correlation",
            "full_data_selected",
            "bootstrap_selection_probability",
            "bootstrap_sign_consistency_with_full",
            "null_selection_probability",
            "stable_edge",
        ],
    )
    write_tsv(
        output_path / "network_metrics.tsv",
        metric_rows,
        [
            "compartment",
            "observations",
            "unique_sites",
            "taxa",
            "alpha",
            "raw_edges",
            "raw_density",
            "raw_positive_fraction",
            "null_mean_edges",
            "null_q95_edges",
            "null_to_raw_edge_ratio",
            "stable_edges",
            "stable_density",
            "stable_positive_fraction",
            "stable_median_absolute_partial_correlation",
            "expected_false_stable_edges",
            "expected_false_fraction_among_stable",
            "full_fit_convergence_warnings",
        ],
    )
    write_tsv(
        output_path / "bootstrap_metrics.tsv",
        bootstrap_rows,
        [
            "bootstrap_replicate",
            "compartment",
            "drawn_site_clusters",
            "bootstrap_observations",
            "edge_count",
            "density",
            "positive_fraction",
            "median_absolute_partial_correlation",
            "convergence_warnings",
        ],
    )
    write_tsv(
        output_path / "sensitivity_metrics.tsv",
        sensitivity_rows,
        [
            "requested_taxa",
            "taxa",
            "alpha_multiplier",
            "alpha",
            "compartment",
            "observed_edges",
            "observed_density",
            "null_replicates",
            "null_mean_edges",
            "null_to_observed_edge_ratio",
        ],
    )
    write_tsv(
        output_path / "compartment_comparisons.tsv",
        comparison_rows,
        [
            "compartment_a",
            "compartment_b",
            "raw_density_difference_a_minus_b",
            "bootstrap_median_density_difference",
            "bootstrap_ci_low",
            "bootstrap_ci_high",
            "bootstrap_probability_a_greater_b",
            "stable_edges_a",
            "stable_edges_b",
            "stable_edge_intersection",
            "stable_edge_union",
            "stable_edge_jaccard",
            "sensitivity_configurations",
            "fraction_same_density_direction_as_primary",
            "bootstrap_ci_excludes_zero",
            "direction_robust_across_sensitivity",
            "comparative_density_supported",
        ],
    )
    write_tsv(
        output_path / "campaign_feasibility.tsv",
        campaign_rows,
        [
            "campaign",
            "matched_observations_per_compartment",
            "primary_taxa",
            "minimum_observations_rule",
            "network_estimated",
            "reason",
        ],
    )
    rescue_row = {
        "claim": "comparative_network_complexity_and_restructuring",
        "original_claim_status": verdict["original_claim_status"],
        "descriptive_association_status": verdict[
            "descriptive_association_status"
        ],
        "campaign_comparison_status": verdict["campaign_comparison_status"],
        "selected_alpha": verdict["selected_alpha"],
        "combined_null_edge_ratio": verdict[
            "selected_combined_null_edge_ratio"
        ],
        "stable_edges_surface": next(
            row["stable_edges"]
            for row in metric_rows
            if row["compartment"] == "Surface"
        ),
        "stable_edges_deep": next(
            row["stable_edges"]
            for row in metric_rows
            if row["compartment"] == "Deep"
        ),
        "stable_edges_rhizosphere": next(
            row["stable_edges"]
            for row in metric_rows
            if row["compartment"] == "Rhizosphere"
        ),
        "comparative_density_contrasts_passing": verdict[
            "comparative_density_contrasts_passing"
        ],
        "permitted_wording": verdict["permitted_wording"],
    }
    write_tsv(
        output_path / "network_rescue.tsv",
        [rescue_row],
        list(rescue_row),
    )
    with (output_path / "parameters.json").open(
        "w", encoding="utf-8"
    ) as handle:
        json.dump(parameters, handle, indent=2, sort_keys=True)
        handle.write("\n")
    with (output_path / "claim_verdict.json").open(
        "w", encoding="utf-8"
    ) as handle:
        json.dump(verdict, handle, indent=2, sort_keys=True)
        handle.write("\n")
    readme = render_readme(
        parameters, cohort_info, metric_rows, comparison_rows, verdict
    )
    (output_path / "README.md").write_text(readme, encoding="utf-8")
    return {
        "parameters": parameters,
        "cohort": cohort_info,
        "metrics": metric_rows,
        "comparisons": comparison_rows,
        "verdict": verdict,
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path("."))
    parser.add_argument("--input-table", type=Path, default=DEFAULT_INPUT)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("analysis/v3/network_rescue/results"),
    )
    parser.add_argument("--seed", type=int, default=20260723)
    parser.add_argument("--minimum-group-reads", type=float, default=2000.0)
    parser.add_argument("--prevalence-threshold", type=float, default=0.20)
    parser.add_argument("--taxa-count", type=int, default=80)
    parser.add_argument("--pseudocount", type=float, default=0.5)
    parser.add_argument(
        "--alpha-grid",
        default="0.05,0.075,0.10,0.125,0.15,0.175,0.20,0.25,0.30",
    )
    parser.add_argument("--calibration-null-replicates", type=int, default=25)
    parser.add_argument("--null-replicates", type=int, default=100)
    parser.add_argument("--bootstrap-replicates", type=int, default=200)
    parser.add_argument("--sensitivity-taxa", default="50,80,100")
    parser.add_argument(
        "--sensitivity-alpha-multipliers", default="0.8,1.0,1.25"
    )
    parser.add_argument("--sensitivity-null-replicates", type=int, default=30)
    parser.add_argument("--maximum-null-edge-ratio", type=float, default=0.10)
    parser.add_argument("--stability-threshold", type=float, default=0.80)
    parser.add_argument(
        "--sign-consistency-threshold", type=float, default=0.90
    )
    parser.add_argument(
        "--maximum-edge-null-frequency", type=float, default=0.05
    )
    parser.add_argument("--minimum-stable-edges", type=int, default=10)
    parser.add_argument(
        "--maximum-expected-false-fraction", type=float, default=0.10
    )
    parser.add_argument("--edge-tolerance", type=float, default=1e-3)
    parser.add_argument("--maximum-iterations", type=int, default=2000)
    parser.add_argument("--convergence-tolerance", type=float, default=2e-4)
    args = parser.parse_args(argv)
    args.alpha_grid = parse_csv_numbers(args.alpha_grid, float)
    args.sensitivity_taxa = parse_csv_numbers(args.sensitivity_taxa, int)
    args.sensitivity_alpha_multipliers = parse_csv_numbers(
        args.sensitivity_alpha_multipliers, float
    )
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    result = run_analysis(
        args.project_root,
        args.input_table,
        args.output_dir,
        seed=args.seed,
        minimum_group_reads=args.minimum_group_reads,
        prevalence_threshold=args.prevalence_threshold,
        taxa_count=args.taxa_count,
        pseudocount=args.pseudocount,
        alpha_grid=args.alpha_grid,
        calibration_null_replicates=args.calibration_null_replicates,
        null_replicates=args.null_replicates,
        bootstrap_replicates=args.bootstrap_replicates,
        sensitivity_taxa=args.sensitivity_taxa,
        sensitivity_alpha_multipliers=args.sensitivity_alpha_multipliers,
        sensitivity_null_replicates=args.sensitivity_null_replicates,
        maximum_null_edge_ratio=args.maximum_null_edge_ratio,
        stability_threshold=args.stability_threshold,
        sign_consistency_threshold=args.sign_consistency_threshold,
        maximum_edge_null_frequency=args.maximum_edge_null_frequency,
        minimum_stable_edges=args.minimum_stable_edges,
        maximum_expected_false_fraction=args.maximum_expected_false_fraction,
        edge_tolerance=args.edge_tolerance,
        maximum_iterations=args.maximum_iterations,
        convergence_tolerance=args.convergence_tolerance,
    )
    print(
        "Network rescue complete: "
        f"n={result['cohort']['matched_observations_per_compartment']} per "
        f"compartment; alpha={result['parameters']['selected_alpha']}; "
        f"original claim={result['verdict']['original_claim_status']}; "
        f"descriptive status="
        f"{result['verdict']['descriptive_association_status']}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
