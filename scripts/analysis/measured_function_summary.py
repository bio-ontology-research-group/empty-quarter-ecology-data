#!/usr/bin/env python3
"""Bounded summary of genome-derived encoded function and PICRUSt2 agreement.

This module consumes the compact measured-function outputs already generated
from genome annotations and abundance profiles.  It does not re-annotate
genomes and does not treat gene content as expression, activity, or flux.

The outputs are limited to:

* per-sample rank correlation between genome-derived and PICRUSt2 KO profiles;
* the community-mean KO-profile correlation;
* the across-sample correlation for the RuBisCO marker K01601;
* the number of genome records positive for the joint RuBisCO+PRK CBB screen;
  and
* a bounded summary of the supplied carbon-fixation marker screen.

Two normalized sample identifiers each map to two PICRUSt2 columns.  Those
columns are summed before within-sample normalization, rather than selecting
one duplicate arbitrarily.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import json
import math
import re
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd
from scipy import stats


SCHEMA_VERSION = "1.1"
BOOTSTRAP_SEED = 20260805
DEFAULT_BOOTSTRAPS = 9_999
RUBISCO_KO = "K01601"
PATHWAYS = ("CBB", "rTCA", "WL", "3HP", "HB")
PATHWAY_RULES = {
    "CBB": (
        "joint RuBisCO and phosphoribulokinase marker call encoded by the "
        "source screen"
    ),
    "rTCA": "ATP-citrate-lyase marker call encoded by the source screen",
    "WL": "ACS/CODH marker call encoded by the source screen",
    "3HP": (
        "malonyl-CoA-reductase or propionyl-CoA-synthase marker call encoded "
        "by the source screen"
    ),
    "HB": (
        "4-hydroxybutyryl-CoA-dehydratase marker call; this marker is not "
        "pathway-specific"
    ),
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def relative_path(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path.resolve())


def write_tsv(
    path: Path,
    rows: Iterable[Mapping[str, Any]],
    columns: Sequence[str],
) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(columns),
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        for row in rows:
            formatted: dict[str, Any] = {}
            for column in columns:
                value = row.get(column)
                if isinstance(value, float):
                    formatted[column] = (
                        f"{value:.12g}" if math.isfinite(value) else ""
                    )
                elif isinstance(value, bool):
                    formatted[column] = "true" if value else "false"
                elif value is None:
                    formatted[column] = ""
                else:
                    formatted[column] = value
            writer.writerow(formatted)


def normalize_columns(frame: pd.DataFrame) -> pd.DataFrame:
    numeric = frame.apply(pd.to_numeric, errors="raise")
    if np.any(~np.isfinite(numeric.to_numpy(dtype=float))):
        raise ValueError("Functional profile contains non-finite values")
    if np.any(numeric.to_numpy(dtype=float) < 0):
        raise ValueError("Functional profile contains negative values")
    totals = numeric.sum(axis=0)
    if np.any(totals <= 0):
        raise ValueError("Functional profile contains an empty sample column")
    return numeric.div(totals, axis=1)


def collapse_picrust_columns(
    frame: pd.DataFrame,
    metadata: pd.DataFrame,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    required = {"picrust2_col", "sample_id"}
    if not required.issubset(metadata.columns):
        raise ValueError(f"PICRUSt metadata lacks {sorted(required)}")
    mapping = metadata[["picrust2_col", "sample_id"]].copy()
    mapping["picrust2_col"] = mapping["picrust2_col"].astype(str)
    mapping["sample_id"] = mapping["sample_id"].astype(str)
    if mapping["picrust2_col"].duplicated().any():
        raise ValueError("PICRUSt source-column identifiers are not unique")
    missing = sorted(set(mapping["picrust2_col"]) - set(frame.columns))
    if missing:
        raise ValueError(
            f"{len(missing)} mapped PICRUSt columns are absent from the table"
        )
    selected = frame[mapping["picrust2_col"].tolist()].copy()
    selected.columns = mapping["sample_id"].tolist()
    # Transpose so duplicate normalized sample IDs can be summed by row label.
    collapsed = selected.T.groupby(level=0, sort=False).sum().T
    collapsed = normalize_columns(collapsed)
    audit_rows = []
    for sample_id, group in mapping.groupby("sample_id", sort=True):
        columns = group["picrust2_col"].tolist()
        audit_rows.append(
            {
                "sample_id": sample_id,
                "n_source_picrust_columns": len(columns),
                "source_picrust_columns": ";".join(columns),
                "aggregation_rule": (
                    "sum_then_within_sample_normalize"
                    if len(columns) > 1
                    else "within_sample_normalize"
                ),
            }
        )
    return collapsed, audit_rows


def load_profiles(
    measured_ko_path: Path,
    picrust_ko_path: Path,
    picrust_metadata_path: Path,
) -> tuple[pd.DataFrame, pd.DataFrame, list[dict[str, Any]], dict[str, Any]]:
    measured = pd.read_csv(measured_ko_path, sep="\t", index_col=0)
    measured.index = measured.index.astype(str)
    measured.columns = measured.columns.astype(str)
    if measured.index.duplicated().any() or measured.columns.duplicated().any():
        raise ValueError("Measured KO matrix has duplicate row or sample labels")
    measured = normalize_columns(measured)

    metadata = pd.read_csv(
        picrust_metadata_path,
        sep="\t",
        dtype=str,
        keep_default_na=False,
    )
    matched_metadata = metadata[
        metadata["sample_id"].isin(set(measured.columns))
    ].copy()
    usecols = ["function"] + matched_metadata["picrust2_col"].tolist()
    picrust_source = pd.read_csv(
        picrust_ko_path,
        sep="\t",
        usecols=usecols,
        index_col=0,
    )
    picrust_source.index = picrust_source.index.astype(str)
    if picrust_source.index.duplicated().any():
        raise ValueError("PICRUSt KO matrix has duplicate KO labels")
    picrust, mapping_rows = collapse_picrust_columns(
        picrust_source,
        matched_metadata,
    )
    sample_ids = sorted(set(measured.columns) & set(picrust.columns))
    shared_kos = sorted(set(measured.index) & set(picrust.index))
    if not sample_ids or not shared_kos:
        raise ValueError("No shared samples or KOs between functional profiles")
    measured_shared = measured.loc[shared_kos, sample_ids]
    picrust_shared = picrust.loc[shared_kos, sample_ids]
    accounting = {
        "measured_sample_columns": int(measured.shape[1]),
        "picrust_source_columns_matched": int(len(matched_metadata)),
        "picrust_normalized_sample_ids_matched": int(picrust.shape[1]),
        "duplicate_normalized_sample_ids": int(
            sum(row["n_source_picrust_columns"] > 1 for row in mapping_rows)
        ),
        "shared_samples": len(sample_ids),
        "shared_kos": len(shared_kos),
    }
    return measured_shared, picrust_shared, mapping_rows, accounting


def _sample_site_cluster(sample: str) -> str:
    """Return the site prefix used to keep same-site profiles together."""
    match = re.match(r"^(\d+)", str(sample))
    return match.group(1) if match is not None else str(sample)


def _rowwise_spearman(left: np.ndarray, right: np.ndarray) -> np.ndarray:
    left_ranks = stats.rankdata(left, axis=1, method="average")
    right_ranks = stats.rankdata(right, axis=1, method="average")
    left_centred = left_ranks - left_ranks.mean(axis=1, keepdims=True)
    right_centred = right_ranks - right_ranks.mean(axis=1, keepdims=True)
    denominator = np.sqrt(
        np.sum(left_centred**2, axis=1)
        * np.sum(right_centred**2, axis=1)
    )
    result = np.sum(left_centred * right_centred, axis=1) / denominator
    if np.any(~np.isfinite(result)):
        raise ValueError("A bootstrap KO-profile correlation is not estimable")
    return result


def site_block_bootstrap_profile_metrics(
    measured: pd.DataFrame,
    picrust: pd.DataFrame,
    per_sample_correlations: np.ndarray,
    n_bootstraps: int,
    seed: int,
) -> dict[str, Any]:
    """Resample whole sites and quantify profile-summary uncertainty."""
    if n_bootstraps < 999:
        raise ValueError("At least 999 bootstrap samples are required")
    samples = [str(sample) for sample in measured.columns]
    clusters = np.asarray([_sample_site_cluster(sample) for sample in samples])
    unique_clusters, inverse = np.unique(clusters, return_inverse=True)
    rng = np.random.default_rng(seed)
    cluster_counts = rng.multinomial(
        len(unique_clusters),
        np.full(len(unique_clusters), 1 / len(unique_clusters)),
        size=n_bootstraps,
    )
    sample_weights = cluster_counts[:, inverse].astype(float)
    totals = sample_weights.sum(axis=1)
    if np.any(totals <= 0):
        raise ValueError("A site bootstrap produced no sample profiles")

    mean_draws = (
        sample_weights @ np.asarray(per_sample_correlations, dtype=float)
    ) / totals
    order = np.argsort(per_sample_correlations)
    ordered_values = np.asarray(per_sample_correlations)[order]
    ordered_weights = sample_weights[:, order].astype(int)
    median_draws = np.empty(n_bootstraps, dtype=float)
    for index, weights in enumerate(ordered_weights):
        median_draws[index] = float(
            np.median(np.repeat(ordered_values, weights))
        )

    measured_values = measured.to_numpy(dtype=float).T
    picrust_values = picrust.to_numpy(dtype=float).T
    community_draws = np.empty(n_bootstraps, dtype=float)
    chunk_size = 128
    for start in range(0, n_bootstraps, chunk_size):
        stop = min(start + chunk_size, n_bootstraps)
        weights = sample_weights[start:stop]
        denominator = totals[start:stop, None]
        measured_means = (weights @ measured_values) / denominator
        picrust_means = (weights @ picrust_values) / denominator
        community_draws[start:stop] = _rowwise_spearman(
            measured_means,
            picrust_means,
        )

    def interval(draws: np.ndarray) -> list[float]:
        return [float(value) for value in np.quantile(draws, [0.025, 0.975])]

    return {
        "method": "whole-site percentile bootstrap",
        "independent_unit": "sampling site",
        "n_site_clusters": int(len(unique_clusters)),
        "n_bootstraps": int(n_bootstraps),
        "seed": int(seed),
        "interval_level": 0.95,
        "per_sample_median_interval": interval(median_draws),
        "per_sample_mean_interval": interval(mean_draws),
        "community_mean_profile_interval": interval(community_draws),
    }


def profile_correlations(
    measured: pd.DataFrame,
    picrust: pd.DataFrame,
    compartments: Mapping[str, str] | None = None,
    n_bootstraps: int = DEFAULT_BOOTSTRAPS,
    bootstrap_seed: int = BOOTSTRAP_SEED,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, float]]:
    if measured.shape != picrust.shape:
        raise ValueError("Measured and predicted shared matrices differ in shape")
    if list(measured.index) != list(picrust.index):
        raise ValueError("Measured and predicted shared KO orders differ")
    if list(measured.columns) != list(picrust.columns):
        raise ValueError("Measured and predicted shared sample orders differ")
    if RUBISCO_KO not in measured.index:
        raise ValueError(f"RuBisCO marker {RUBISCO_KO} is not shared")
    sample_rows = []
    for sample in measured.columns:
        result = stats.spearmanr(
            measured[sample].to_numpy(dtype=float),
            picrust[sample].to_numpy(dtype=float),
        )
        if not np.isfinite(result.statistic):
            raise ValueError(f"Non-estimable KO-profile correlation for {sample}")
        sample_rows.append(
            {
                "sample": sample,
                "compartment_source_label": (
                    compartments.get(sample, "")
                    if compartments is not None
                    else ""
                ),
                "n_shared_kos": measured.shape[0],
                "spearman_rho": float(result.statistic),
            }
        )
    values = np.asarray([row["spearman_rho"] for row in sample_rows])
    measured_mean = measured.mean(axis=1)
    picrust_mean = picrust.mean(axis=1)
    mean_result = stats.spearmanr(measured_mean, picrust_mean)
    marker_result = stats.spearmanr(
        measured.loc[RUBISCO_KO],
        picrust.loc[RUBISCO_KO],
    )
    if not np.isfinite(mean_result.statistic):
        raise ValueError("Community-mean KO-profile correlation is not estimable")
    if not np.isfinite(marker_result.statistic):
        raise ValueError(f"Marker correlation for {RUBISCO_KO} is not estimable")
    uncertainty = site_block_bootstrap_profile_metrics(
        measured,
        picrust,
        values,
        n_bootstraps,
        bootstrap_seed,
    )

    def sampling_fields(interval_key: str) -> dict[str, Any]:
        low, high = uncertainty[interval_key]
        return {
            "interval_level": uncertainty["interval_level"],
            "interval_low": low,
            "interval_high": high,
            "uncertainty_type": "sampling uncertainty",
            "uncertainty_method": uncertainty["method"],
            "independent_unit": uncertainty["independent_unit"],
            "n_bootstraps": uncertainty["n_bootstraps"],
            "bootstrap_seed": uncertainty["seed"],
        }

    no_interval = {
        "interval_level": None,
        "interval_low": None,
        "interval_high": None,
        "uncertainty_type": "none; descriptive endpoint or test only",
        "uncertainty_method": None,
        "independent_unit": None,
        "n_bootstraps": None,
        "bootstrap_seed": None,
    }
    metrics = [
        {
            "metric": "per_sample_ko_profile_spearman_median",
            "feature": "all_shared_KOs",
            "n_samples": measured.shape[1],
            "n_features": measured.shape[0],
            "estimate": float(np.median(values)),
            "p_value": None,
            "interpretation": "descriptive distribution across samples",
            **sampling_fields("per_sample_median_interval"),
        },
        {
            "metric": "per_sample_ko_profile_spearman_mean",
            "feature": "all_shared_KOs",
            "n_samples": measured.shape[1],
            "n_features": measured.shape[0],
            "estimate": float(np.mean(values)),
            "p_value": None,
            "interpretation": "descriptive distribution across samples",
            **sampling_fields("per_sample_mean_interval"),
        },
        {
            "metric": "per_sample_ko_profile_spearman_minimum",
            "feature": "all_shared_KOs",
            "n_samples": measured.shape[1],
            "n_features": measured.shape[0],
            "estimate": float(np.min(values)),
            "p_value": None,
            "interpretation": "descriptive distribution across samples",
            **no_interval,
        },
        {
            "metric": "per_sample_ko_profile_spearman_maximum",
            "feature": "all_shared_KOs",
            "n_samples": measured.shape[1],
            "n_features": measured.shape[0],
            "estimate": float(np.max(values)),
            "p_value": None,
            "interpretation": "descriptive distribution across samples",
            **no_interval,
        },
        {
            "metric": "community_mean_ko_profile_spearman",
            "feature": "all_shared_KOs",
            "n_samples": measured.shape[1],
            "n_features": measured.shape[0],
            "estimate": float(mean_result.statistic),
            "p_value": None,
            "interpretation": (
                "aggregate encoded-profile agreement; KO dependence makes "
                "a feature-level significance test inappropriate"
            ),
            **sampling_fields("community_mean_profile_interval"),
        },
        {
            "metric": "marker_across_sample_spearman",
            "feature": RUBISCO_KO,
            "n_samples": measured.shape[1],
            "n_features": 1,
            "estimate": float(marker_result.statistic),
            "p_value": float(marker_result.pvalue),
            "interpretation": (
                "weak marker-level agreement; does not validate RuBisCO "
                "prediction"
            ),
            **no_interval,
        },
    ]
    diagnostics = {
        "rubisco_measured_nonzero_samples": int(
            np.sum(measured.loc[RUBISCO_KO] > 0)
        ),
        "rubisco_picrust_nonzero_samples": int(
            np.sum(picrust.loc[RUBISCO_KO] > 0)
        ),
    }
    diagnostics["sampling_uncertainty"] = uncertainty
    return sample_rows, metrics, diagnostics


def pathway_screen_rows(frame: pd.DataFrame) -> list[dict[str, Any]]:
    required = {"genome", *PATHWAYS}
    if not required.issubset(frame.columns):
        raise ValueError(f"Pathway screen lacks {sorted(required)}")
    if frame["genome"].astype(str).duplicated().any():
        raise ValueError("Pathway screen contains duplicate genome labels")
    rows = []
    for pathway in PATHWAYS:
        values = pd.to_numeric(frame[pathway], errors="raise")
        if not values.isin([0, 1]).all():
            raise ValueError(f"Pathway {pathway} is not a binary screen")
        positive = int(values.sum())
        if pathway == "CBB":
            interpretation = (
                "candidate CBB encoded potential from the joint marker "
                "screen; not completeness, expression, or activity"
            )
        elif pathway == "HB":
            interpretation = (
                "single-marker hits only; the marker is not pathway-specific"
            )
        elif positive == 0:
            interpretation = (
                "no positive record in the supplied screen; this is not "
                "evidence of biological absence"
            )
        else:
            interpretation = (
                "marker-screen hits only; not a complete or active pathway"
            )
        rows.append(
            {
                "pathway": pathway,
                "source_screen_rule": PATHWAY_RULES[pathway],
                "positive_genome_records": positive,
                "interpretation": interpretation,
            }
        )
    return rows


def denominator_audit(
    pathway_frame: pd.DataFrame,
    filtered_genomes: pd.DataFrame,
) -> dict[str, Any]:
    if "genome" not in filtered_genomes.columns:
        raise ValueError("Filtered-genome table lacks a genome column")
    known = set(filtered_genomes["genome"].astype(str))

    def matches_known(genome: str) -> bool:
        return (
            genome in known
            or f"{genome}sta" in known
            or (genome.endswith("sta") and genome[:-3] in known)
        )

    pathway_genomes = pathway_frame["genome"].astype(str)
    matched = pathway_genomes.map(matches_known)
    return {
        "status": "total_screened_genome_denominator_not_reconstructable",
        "filtered_genomes_rows": int(len(filtered_genomes)),
        "filtered_genomes_unique_labels": int(
            filtered_genomes["genome"].astype(str).nunique()
        ),
        "pathway_positive_table_rows": int(len(pathway_frame)),
        "pathway_positive_unique_labels": int(pathway_genomes.nunique()),
        "pathway_positive_labels_matched_to_filtered_table": int(matched.sum()),
        "pathway_positive_labels_not_matched_to_filtered_table": int(
            (~matched).sum()
        ),
        "unmatched_pathway_positive_labels": sorted(
            pathway_genomes.loc[~matched].tolist()
        ),
        "total_screened_genomes": None,
        "genome_fraction_reportable": False,
        "reason": (
            "The supplied genome_cfix_taxonomy table contains positive "
            "pathway records only, while filtered_genomes is not a complete "
            "matching manifest for those records."
        ),
    }


def write_outputs(
    project_root: Path,
    measured_dir: Path,
    picrust_ko_path: Path,
    picrust_metadata_path: Path,
    output_dir: Path,
    n_bootstraps: int = DEFAULT_BOOTSTRAPS,
    bootstrap_seed: int = BOOTSTRAP_SEED,
) -> dict[str, Any]:
    measured_ko_path = measured_dir / "measured_ko_by_sample.tsv.gz"
    marker_path = measured_dir / "measured_marker_by_sample.tsv"
    pathway_path = measured_dir / "genome_cfix_taxonomy.tsv"
    filtered_path = measured_dir / "filtered_genomes.tsv"
    input_paths = [
        measured_ko_path,
        marker_path,
        pathway_path,
        filtered_path,
        picrust_ko_path,
        picrust_metadata_path,
    ]
    missing = [str(path) for path in input_paths if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Missing measured-function inputs: {missing}")

    measured, picrust, mapping_rows, accounting = load_profiles(
        measured_ko_path,
        picrust_ko_path,
        picrust_metadata_path,
    )
    marker_frame = pd.read_csv(marker_path, sep="\t", dtype={"sample": str})
    compartments = dict(
        zip(
            marker_frame["sample"].astype(str),
            marker_frame["compartment"].astype(str),
        )
    )
    sample_rows, metric_rows, marker_diagnostics = profile_correlations(
        measured,
        picrust,
        compartments,
        n_bootstraps,
        bootstrap_seed,
    )
    pathway_frame = pd.read_csv(pathway_path, sep="\t")
    pathway_rows = pathway_screen_rows(pathway_frame)
    filtered_frame = pd.read_csv(filtered_path, sep="\t")
    denominator = denominator_audit(pathway_frame, filtered_frame)
    cbb_count = next(
        row["positive_genome_records"]
        for row in pathway_rows
        if row["pathway"] == "CBB"
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    write_tsv(
        output_dir / "per_sample_ko_correlations.tsv",
        sample_rows,
        [
            "sample",
            "compartment_source_label",
            "n_shared_kos",
            "spearman_rho",
        ],
    )
    write_tsv(
        output_dir / "summary_metrics.tsv",
        metric_rows,
        [
            "metric",
            "feature",
            "n_samples",
            "n_features",
            "estimate",
            "p_value",
            "interval_level",
            "interval_low",
            "interval_high",
            "uncertainty_type",
            "uncertainty_method",
            "independent_unit",
            "n_bootstraps",
            "bootstrap_seed",
            "interpretation",
        ],
    )
    write_tsv(
        output_dir / "pathway_screen.tsv",
        pathway_rows,
        [
            "pathway",
            "source_screen_rule",
            "positive_genome_records",
            "interpretation",
        ],
    )
    write_tsv(
        output_dir / "picrust_sample_mapping.tsv",
        mapping_rows,
        [
            "sample_id",
            "n_source_picrust_columns",
            "source_picrust_columns",
            "aggregation_rule",
        ],
    )

    metric_lookup = {
        row["metric"]: row
        for row in metric_rows
    }
    summary: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": "encoded_potential_summary_only",
        "cohort": accounting,
        "ko_profile_correlations": {
            "per_sample_median_spearman": metric_lookup[
                "per_sample_ko_profile_spearman_median"
            ]["estimate"],
            "per_sample_mean_spearman": metric_lookup[
                "per_sample_ko_profile_spearman_mean"
            ]["estimate"],
            "per_sample_range": [
                metric_lookup[
                    "per_sample_ko_profile_spearman_minimum"
                ]["estimate"],
                metric_lookup[
                    "per_sample_ko_profile_spearman_maximum"
                ]["estimate"],
            ],
            "community_mean_profile_spearman": metric_lookup[
                "community_mean_ko_profile_spearman"
            ]["estimate"],
            "per_sample_median_95_interval": [
                metric_lookup[
                    "per_sample_ko_profile_spearman_median"
                ]["interval_low"],
                metric_lookup[
                    "per_sample_ko_profile_spearman_median"
                ]["interval_high"],
            ],
            "community_mean_profile_95_interval": [
                metric_lookup[
                    "community_mean_ko_profile_spearman"
                ]["interval_low"],
                metric_lookup[
                    "community_mean_ko_profile_spearman"
                ]["interval_high"],
            ],
        },
        "rubisco_marker": {
            "ko": RUBISCO_KO,
            "across_sample_spearman": metric_lookup[
                "marker_across_sample_spearman"
            ]["estimate"],
            "two_sided_p_value": metric_lookup[
                "marker_across_sample_spearman"
            ]["p_value"],
            **marker_diagnostics,
            "interpretation": (
                "weak marker-level agreement; the aggregate KO-profile "
                "correlation does not validate this rare marker"
            ),
        },
        "cbb_joint_marker_screen": {
            "positive_genome_records": cbb_count,
            "screen": (
                "joint RuBisCO and phosphoribulokinase source call"
            ),
            "interpretation": (
                "candidate encoded CBB potential only; no denominator, "
                "expression, activity, or flux inference"
            ),
        },
        "pathway_screen": {
            row["pathway"]: row["positive_genome_records"]
            for row in pathway_rows
        },
        "genome_denominator_audit": denominator,
        "permitted_wording": (
            f"Across {accounting['shared_samples']} matched normalized sample "
            f"IDs and {accounting['shared_kos']:,} shared KOs, genome-derived "
            "and PICRUSt2 KO profiles had median per-sample Spearman "
            f"correlation {metric_lookup['per_sample_ko_profile_spearman_median']['estimate']:.3f}. "
            f"Agreement for the RuBisCO marker {RUBISCO_KO} was weak "
            f"(rho {metric_lookup['marker_across_sample_spearman']['estimate']:.3f}). "
            "The supplied joint RuBisCO+PRK screen contained "
            f"{cbb_count} positive genome records, supporting candidate "
            "encoded CBB potential only."
        ),
        "not_supported": [
            "validation of PICRUSt2 for RuBisCO or another individual rare marker",
            "any genome fraction or a total screened denominator of 2,970 from the supplied local outputs",
            "a complete or active CBB pathway",
            "the sole carbon-fixation route",
            "biological absence from zero marker-screen hits",
            "chemolithoautotrophy, trace-gas oxidation, expression, activity, or flux",
        ],
    }
    script_path = Path(__file__).resolve()
    summary["provenance"] = {
        "script": relative_path(script_path, project_root),
        "script_sha256": sha256_file(script_path),
        "seed": bootstrap_seed,
        "random_operations": True,
        "duplicate_picrust_rule": (
            "sum source columns sharing a normalized sample ID, then "
            "normalize within sample"
        ),
        "software": {
            package: importlib.metadata.version(package)
            for package in ("numpy", "pandas", "scipy")
        },
    }
    (output_dir / "encoded_function_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    roles = {
        measured_ko_path: "genome-derived relative KO profiles",
        marker_path: "sample and source-compartment labels",
        pathway_path: "positive genome pathway-screen records",
        filtered_path: "incomplete local genome manifest for denominator audit",
        picrust_ko_path: "PICRUSt2 predicted KO counts",
        picrust_metadata_path: "PICRUSt2 column-to-sample mapping",
    }
    manifest_rows = [
        {
            "role": roles[path],
            "path": relative_path(path, project_root),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in input_paths
    ]
    write_tsv(
        output_dir / "input_manifest.tsv",
        manifest_rows,
        ["role", "path", "bytes", "sha256"],
    )

    ko_summary = summary["ko_profile_correlations"]
    rubisco = summary["rubisco_marker"]
    readme = [
        "# Bounded genome-derived encoded-function summary",
        "",
        str(summary["permitted_wording"]),
        "",
        f"- Matched normalized sample IDs: {accounting['shared_samples']}",
        f"- Shared KOs: {accounting['shared_kos']:,}",
        "- Per-sample KO-profile Spearman median: "
        f"{ko_summary['per_sample_median_spearman']:.3f} "
        f"(whole-site bootstrap 95% interval "
        f"[{ko_summary['per_sample_median_95_interval'][0]:.3f}, "
        f"{ko_summary['per_sample_median_95_interval'][1]:.3f}])",
        "- Per-sample KO-profile Spearman mean: "
        f"{ko_summary['per_sample_mean_spearman']:.3f}",
        "- Community-mean KO-profile Spearman: "
        f"{ko_summary['community_mean_profile_spearman']:.3f} "
        f"(whole-site bootstrap 95% interval "
        f"[{ko_summary['community_mean_profile_95_interval'][0]:.3f}, "
        f"{ko_summary['community_mean_profile_95_interval'][1]:.3f}])",
        f"- RuBisCO marker {RUBISCO_KO}: rho="
        f"{rubisco['across_sample_spearman']:.3f}, "
        f"p={rubisco['two_sided_p_value']:.3g}",
        f"- Joint RuBisCO+PRK screen-positive genome records: {cbb_count}",
        "",
        "Two normalized sample IDs each mapped to two PICRUSt2 source columns. "
        "Duplicate columns were summed before within-sample normalization.",
        "Whole-site bootstrap intervals resampled all profiles from a site "
        "together and used 9,999 samples with seed 20260805.",
        "",
        "The supplied local files do not reconstruct the total genome universe "
        "screened, so no CBB-positive genome fraction is reported. In "
        "particular, these files do not independently establish a "
        "2,970-genome screened denominator.",
        "",
        "All results concern genome-derived encoded potential. They do not "
        "establish pathway completeness, expression, activity, metabolic flux, "
        "chemolithoautotrophy, or biological absence after a zero screen.",
        "",
    ]
    (output_dir / "README.md").write_text(
        "\n".join(readme), encoding="utf-8"
    )
    checksum_lines = [
        f"{sha256_file(path)}  {path.name}"
        for path in sorted(output_dir.iterdir())
        if path.is_file() and path.name != "SHA256SUMS"
    ]
    (output_dir / "SHA256SUMS").write_text(
        "\n".join(checksum_lines) + "\n", encoding="utf-8"
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
    )
    parser.add_argument("--measured-dir", type=Path, default=None)
    parser.add_argument("--picrust-ko", type=Path, default=None)
    parser.add_argument("--picrust-metadata", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument(
        "--bootstraps", type=int, default=DEFAULT_BOOTSTRAPS
    )
    parser.add_argument(
        "--bootstrap-seed", type=int, default=BOOTSTRAP_SEED
    )
    args = parser.parse_args()

    project_root = args.project_root.resolve()
    measured_dir = (
        args.measured_dir.resolve()
        if args.measured_dir is not None
        else (
            project_root
            / "analysis"
            / "v2"
            / "review"
            / "measured_function"
        )
    )
    picrust_dir = (
        project_root
        / "data"
        / "processed"
        / "functional"
        / "picrust2"
        / "merged"
    )
    picrust_ko_path = (
        args.picrust_ko.resolve()
        if args.picrust_ko is not None
        else picrust_dir / "ko_metagenome_unstrat.tsv"
    )
    picrust_metadata_path = (
        args.picrust_metadata.resolve()
        if args.picrust_metadata is not None
        else picrust_dir / "sample_metadata.tsv"
    )
    output_dir = (
        args.output_dir.resolve()
        if args.output_dir is not None
        else (
            project_root
            / "analysis"
            / "v3"
            / "measured_function_summary_results"
        )
    )
    write_outputs(
        project_root,
        measured_dir,
        picrust_ko_path,
        picrust_metadata_path,
        output_dir,
        args.bootstraps,
        args.bootstrap_seed,
    )


if __name__ == "__main__":
    main()
