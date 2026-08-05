#!/usr/bin/env python3
"""Reproduce the pH sensitivity analysis for a frozen dataset version.

The analysis uses only admitted measurements and exact specimen identifiers
shared with the ecology cache. The expected dataset and analysis versions are
explicit command-line inputs so a successor can be rerun without mutating an
archived predecessor analysis.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import platform
import re
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
from scipy import stats
from scipy.spatial.distance import pdist, squareform


SEED = 20260802
DEFAULT_ANALYSIS_VERSION = "ph-ecology-v1.0.0"
DEFAULT_DATASET_VERSION = "EQ-PH-ECOLOGY-v1.0.0"
ADMITTED = "ADMITTED_MEASUREMENT"
SAMPLE_PREFIX_RE = re.compile(r"^e\d+_")
CORE_SITES = set(range(1, 61))
COMPARTMENTS = ("Surface", "Deep", "Rhizosphere")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def json_safe(value: Any) -> Any:
    """Convert NumPy scalars and non-finite floats to strict JSON values."""
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def normalize_profile_id(value: object) -> str:
    return SAMPLE_PREFIX_RE.sub("", str(value).strip())


def bh_fdr(values: pd.Series) -> np.ndarray:
    raw = values.to_numpy(dtype=float)
    order = np.argsort(raw)
    ranked = raw[order]
    adjusted = np.minimum.accumulate(
        (ranked * len(ranked) / np.arange(1, len(ranked) + 1))[::-1]
    )[::-1]
    result = np.empty_like(adjusted)
    result[order] = np.minimum(adjusted, 1.0)
    return result


def load_sample_level_join(root: Path, accepted_path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    ph = pd.read_csv(accepted_path, sep="\t")
    if set(ph["disposition"]) != {ADMITTED}:
        raise ValueError("Admitted pH table contains a non-admitted disposition")
    if ph["sample_id"].duplicated().any():
        raise ValueError("Frozen pH table contains duplicate specimen identifiers")

    alpha = pd.read_csv(
        root / "analysis/v2/review/cache/alpha.tsv",
        sep="\t",
        index_col=0,
    )
    alpha = alpha.assign(
        profile_id=alpha.index.astype(str),
        sample_id=[normalize_profile_id(value) for value in alpha.index],
    )
    alpha = alpha[alpha["sample_id"].isin(set(ph["sample_id"]))].copy()
    alpha_by_sample = (
        alpha.groupby("sample_id", as_index=False)
        .agg(
            alpha_trip=("Trip", "first"),
            alpha_site=("Site", "first"),
            alpha_compartment=("Type", "first"),
            shannon=("shannon", "mean"),
            sequencing_depth=("depth", "sum"),
            n_profiles=("shannon", "size"),
        )
    )
    joined = ph.merge(alpha_by_sample, on="sample_id", how="inner", validate="one_to_one")
    mismatch = joined[
        (joined["trip"].astype(int) != joined["alpha_trip"].astype(int))
        | (joined["site"].astype(int) != joined["alpha_site"].astype(int))
        | (joined["compartment"] != joined["alpha_compartment"])
    ]
    if not mismatch.empty:
        raise ValueError(
            "pH/ecology metadata disagree for: "
            + ", ".join(mismatch["sample_id"].head(10))
        )
    joined["trip"] = joined["trip"].astype(int)
    joined["site"] = joined["site"].astype(int)
    joined = joined[joined["site"].isin(CORE_SITES)].copy()

    grouped = (
        joined.groupby(["trip", "site", "compartment"], as_index=False)
        .agg(
            ph=("ph_value", "mean"),
            ph_sd=("ph_value", "std"),
            n_ph_specimens=("sample_id", "size"),
            shannon=("shannon", "mean"),
            sequencing_depth=("sequencing_depth", "sum"),
            n_profiles=("n_profiles", "sum"),
        )
        .sort_values(["trip", "site", "compartment"])
    )
    grouped["log_sequencing_depth"] = np.log1p(grouped["sequencing_depth"])
    return joined, grouped


def load_grouped_counts(
    root: Path,
    accepted_path: Path,
    group_table: pd.DataFrame,
    minimum_group_reads: int,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, int]]:
    ph = pd.read_csv(accepted_path, sep="\t").set_index("sample_id")
    counts = pd.read_csv(
        root / "analysis/v2/review/cache/genus_counts.tsv",
        sep="\t",
        index_col=0,
    )
    counts = counts.loc[~counts.index.isna()].copy()
    counts.index = counts.index.astype(str)
    selected_columns = [
        column
        for column in counts.columns
        if normalize_profile_id(column) in ph.index
    ]
    selected = counts[selected_columns].T.copy()
    selected["sample_id"] = [normalize_profile_id(value) for value in selected.index]
    metadata = ph.loc[selected["sample_id"], ["trip", "site", "compartment"]].reset_index(drop=True)
    selected["trip"] = metadata["trip"].astype(int).to_numpy()
    selected["site"] = metadata["site"].astype(int).to_numpy()
    selected["compartment"] = metadata["compartment"].to_numpy()
    feature_columns = counts.index.astype(str).tolist()
    grouped = selected.groupby(["trip", "site", "compartment"], sort=True)[feature_columns].sum()
    library_size = grouped.sum(axis=1)
    grouped = grouped.loc[library_size >= minimum_group_reads]
    keys = grouped.index.to_frame(index=False)
    eligible_keys = set(map(tuple, group_table[["trip", "site", "compartment"]].to_numpy()))
    keep = np.array([tuple(row) in eligible_keys for row in keys.to_numpy()])
    grouped = grouped.loc[keep]
    keys = grouped.index.to_frame(index=False)
    matrix = grouped.T
    matrix.columns = pd.MultiIndex.from_frame(keys)
    return matrix, keys, {
        "selected_profile_columns": len(selected_columns),
        "selected_unique_specimens": int(selected["sample_id"].nunique()),
        "retained_groups": len(keys),
        "retained_sites": int(keys["site"].nunique()),
        "minimum_group_reads": minimum_group_reads,
    }


def rank_taxa(counts: pd.DataFrame, prevalence: float) -> list[str]:
    detected = (counts > 0).mean(axis=1)
    eligible = detected[detected >= prevalence].index
    relative = counts.div(counts.sum(axis=0), axis=1)
    return (
        relative.loc[eligible]
        .mean(axis=1)
        .sort_values(ascending=False, kind="mergesort")
        .index.astype(str)
        .tolist()
    )


def categorical_design(frame: pd.DataFrame, include_site: bool = True) -> np.ndarray:
    fields = ["trip", "compartment"] + (["site"] if include_site else [])
    encoded = pd.get_dummies(frame[fields].astype(str), drop_first=True, dtype=float)
    return np.column_stack([np.ones(len(frame)), encoded.to_numpy()])


def pcoa_coordinates(distance: np.ndarray, variance_fraction: float) -> tuple[np.ndarray, float]:
    n = distance.shape[0]
    center = np.eye(n) - np.ones((n, n)) / n
    gram = -0.5 * center @ np.square(distance) @ center
    eigenvalues, eigenvectors = np.linalg.eigh(gram)
    order = np.argsort(eigenvalues)[::-1]
    eigenvalues = eigenvalues[order]
    eigenvectors = eigenvectors[:, order]
    positive = eigenvalues > max(1e-12, eigenvalues[0] * 1e-10)
    eigenvalues = eigenvalues[positive]
    eigenvectors = eigenvectors[:, positive]
    cumulative = np.cumsum(eigenvalues) / eigenvalues.sum()
    axes = int(np.searchsorted(cumulative, variance_fraction) + 1)
    return eigenvectors[:, :axes] * np.sqrt(eigenvalues[:axes]), float(cumulative[axes - 1])


def nested_multivariate_test(
    response: np.ndarray,
    reduced: np.ndarray,
    predictor: np.ndarray,
    sites: np.ndarray,
    permutations: int,
    seed: int,
) -> dict[str, float | int]:
    """Freedman-Lane-style residual permutation of one predictor within site."""
    response = np.asarray(response, dtype=float)
    predictor = np.asarray(predictor, dtype=float)
    reduced_pinv = np.linalg.pinv(reduced)
    response_residual = response - reduced @ (reduced_pinv @ response)
    predictor_fit = reduced @ (reduced_pinv @ predictor)
    predictor_residual = predictor - predictor_fit
    sse_reduced = float(np.square(response_residual).sum())

    def effect_for(candidate_residual: np.ndarray) -> float:
        candidate_residual = candidate_residual - reduced @ (reduced_pinv @ candidate_residual)
        denominator = float(candidate_residual @ candidate_residual)
        if denominator <= 1e-12:
            return 0.0
        projection = candidate_residual @ response_residual
        return float(np.square(projection).sum() / denominator)

    effect = effect_for(predictor_residual)
    sse_full = max(1e-12, sse_reduced - effect)
    residual_df = len(predictor) - np.linalg.matrix_rank(reduced) - 1
    observed_f = effect / (sse_full / residual_df)
    groups = {site: np.flatnonzero(sites == site) for site in np.unique(sites)}
    rng = np.random.default_rng(seed)
    exceed = 0
    for _ in range(permutations):
        candidate = predictor_residual.copy()
        for indices in groups.values():
            candidate[indices] = rng.permutation(candidate[indices])
        candidate_effect = effect_for(candidate)
        candidate_sse = max(1e-12, sse_reduced - candidate_effect)
        candidate_f = candidate_effect / (candidate_sse / residual_df)
        exceed += candidate_f >= observed_f
    return {
        "pseudo_f": observed_f,
        "p": (exceed + 1) / (permutations + 1),
        "partial_r2": effect / sse_reduced,
        "residual_df": int(residual_df),
        "permutations": permutations,
    }


def fit_alpha_models(grouped: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    specifications = [
        (
            "site_fixed_primary",
            grouped,
            "shannon ~ ph + log_sequencing_depth + C(trip) + C(compartment) + C(site)",
        ),
        (
            "geographic_trend_sensitivity",
            grouped,
            "shannon ~ ph + log_sequencing_depth + C(trip) + C(compartment) + "
            "transect_km + I(transect_km ** 2)",
        ),
        (
            "two_or_more_ph_specimens_sensitivity",
            grouped[grouped["n_ph_specimens"] >= 2],
            "shannon ~ ph + log_sequencing_depth + C(trip) + C(compartment) + C(site)",
        ),
    ]
    for name, data, formula in specifications:
        fit = smf.ols(formula, data=data).fit(
            cov_type="cluster", cov_kwds={"groups": data["site"]}
        )
        interval = fit.conf_int().loc["ph"]
        rows.append(
            {
                "model": name,
                "n_observations": int(fit.nobs),
                "n_sites": int(data["site"].nunique()),
                "estimate_per_ph_unit": float(fit.params["ph"]),
                "std_error": float(fit.bse["ph"]),
                "ci_low": float(interval.iloc[0]),
                "ci_high": float(interval.iloc[1]),
                "p": float(fit.pvalues["ph"]),
                "formula": formula,
            }
        )
    return pd.DataFrame(rows)


def fit_paired_ph(grouped: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, float | int]]:
    wide = grouped.pivot_table(
        index=["trip", "site"], columns="compartment", values="ph", aggfunc="mean"
    )
    complete_blocks = wide.dropna(subset=list(COMPARTMENTS))
    complete_sites = complete_blocks.groupby("site")[list(COMPARTMENTS)].mean()
    omnibus: dict[str, float | int] = {
        "complete_three_position_site_campaign_blocks": len(complete_blocks),
        "complete_three_position_sites": len(complete_sites),
        "friedman_chi_square": math.nan,
        "friedman_p": math.nan,
    }
    if len(complete_sites) >= 3:
        result = stats.friedmanchisquare(
            *(complete_sites[column] for column in COMPARTMENTS)
        )
        omnibus.update(
            {
                "friedman_chi_square": float(result.statistic),
                "friedman_p": float(result.pvalue),
            }
        )
    rows = []
    for first, second in (
        ("Deep", "Surface"),
        ("Rhizosphere", "Surface"),
        ("Rhizosphere", "Deep"),
    ):
        pair = wide[[first, second]].dropna()
        block_difference = pair[first] - pair[second]
        site_difference = block_difference.groupby("site").mean().round(12)
        nonzero_site_difference = site_difference[site_difference != 0]
        test = stats.wilcoxon(
            site_difference,
            alternative="two-sided",
            zero_method="wilcox",
            correction=False,
            method="approx",
        )
        rows.append(
            {
                "comparison": f"{first}-{second}",
                "n_site_campaign_blocks": len(pair),
                "n_sites": len(site_difference),
                "n_nonzero_sites": len(nonzero_site_difference),
                "n_zero_sites": len(site_difference) - len(nonzero_site_difference),
                "mean_difference_ph_units": float(site_difference.mean()),
                "median_difference_ph_units": float(site_difference.median()),
                "wilcoxon_w": float(test.statistic),
                "p": float(test.pvalue),
            }
        )
    result = pd.DataFrame(rows)
    result["q_bh_three_position_contrasts"] = bh_fdr(result["p"])
    return result, omnibus


def spatial_design(transect: np.ndarray) -> np.ndarray:
    standardized = (transect - transect.mean()) / transect.std(ddof=1)
    quadratic = np.square(standardized)
    quadratic -= quadratic.mean()
    return np.column_stack([np.ones(len(standardized)), standardized, quadratic])


def fit_spatial_response(
    response: np.ndarray,
    transect: np.ndarray,
    permutations: int,
    seed: int,
) -> dict[str, float | int]:
    design = spatial_design(transect)
    centered = response - response.mean(axis=0, keepdims=True)

    def fit(candidate: np.ndarray) -> tuple[float, float]:
        fitted = design @ np.linalg.lstsq(design, candidate, rcond=None)[0]
        residual = candidate - fitted
        tss = float(np.square(candidate).sum())
        sse = float(np.square(residual).sum())
        q = 2
        residual_df = len(candidate) - design.shape[1]
        r2 = 1.0 - sse / tss
        pseudo_f = ((tss - sse) / q) / (sse / residual_df)
        return r2, pseudo_f

    r2, observed_f = fit(centered)
    rng = np.random.default_rng(seed)
    exceed = 0
    for _ in range(permutations):
        _, candidate_f = fit(centered[rng.permutation(len(centered))])
        exceed += candidate_f >= observed_f
    return {
        "partial_r2": r2,
        "pseudo_f": observed_f,
        "p": (exceed + 1) / (permutations + 1),
        "n_observations": len(centered),
        "residual_df": len(centered) - design.shape[1],
        "permutations": permutations,
    }


def fit_geographic_adjustment(
    counts: pd.DataFrame,
    keys: pd.DataFrame,
    group_table: pd.DataFrame,
    coordinates: pd.DataFrame,
    taxa: list[str],
    permutations: int,
    pseudocount: float,
) -> pd.DataFrame:
    keyed = keys.merge(group_table, on=["trip", "site", "compartment"], how="left", validate="one_to_one")
    if keyed["ph"].isna().any():
        raise ValueError("Composition group lacks a pH value")
    matrix = counts.loc[taxa].T.to_numpy(dtype=float)
    logged = np.log(matrix + pseudocount)
    clr = logged - logged.mean(axis=1, keepdims=True)
    category = pd.get_dummies(
        (keyed["trip"].astype(str) + "|" + keyed["compartment"]),
        drop_first=True,
        dtype=float,
    )
    reduced = np.column_stack([np.ones(len(keyed)), category.to_numpy()])
    reduced_pinv = np.linalg.pinv(reduced)
    residual_without_ph = clr - reduced @ (reduced_pinv @ clr)
    full = np.column_stack([reduced, keyed["ph"].to_numpy(dtype=float)])
    residual_with_ph = clr - full @ (np.linalg.pinv(full) @ clr)

    rows: list[dict[str, Any]] = []
    site_order = sorted(keyed["site"].unique())
    coordinate_index = coordinates.set_index("site")
    transect = coordinate_index.loc[site_order, "transect_km"].to_numpy(dtype=float)
    for name, response in (
        ("same_cohort_without_ph_adjustment", residual_without_ph),
        ("same_cohort_with_ph_adjustment", residual_with_ph),
    ):
        site_response = np.vstack(
            [response[keyed["site"].to_numpy() == site].mean(axis=0) for site in site_order]
        )
        result = fit_spatial_response(
            site_response,
            transect,
            permutations,
            SEED + (0 if "without" in name else 1),
        )
        rows.append(
            {
                "model": name,
                "n_groups": len(keyed),
                "n_sites": len(site_order),
                "taxon_count": len(taxa),
                "pseudocount": pseudocount,
                **result,
            }
        )

    ph_residual = keyed["ph"].to_numpy(dtype=float) - reduced @ (
        reduced_pinv @ keyed["ph"].to_numpy(dtype=float)
    )
    site_ph = np.array(
        [ph_residual[keyed["site"].to_numpy() == site].mean() for site in site_order]
    )[:, None]
    ph_spatial = fit_spatial_response(site_ph, transect, permutations, SEED + 2)
    rows.append(
        {
            "model": "ph_transect_pattern_after_campaign_position",
            "n_groups": len(keyed),
            "n_sites": len(site_order),
            "taxon_count": 0,
            "pseudocount": math.nan,
            **ph_spatial,
        }
    )
    return pd.DataFrame(rows)


def summarize_geographic_scenario(
    scenario: str,
    geographic: pd.DataFrame,
    excluded: pd.Series | None = None,
    exclusion_scope: str = "none",
) -> dict[str, Any]:
    indexed = geographic.set_index("model")
    before = indexed.loc["same_cohort_without_ph_adjustment"]
    after = indexed.loc["same_cohort_with_ph_adjustment"]
    ph_spatial = indexed.loc["ph_transect_pattern_after_campaign_position"]
    return {
        "scenario": scenario,
        "exclusion_scope": exclusion_scope,
        "excluded_trip": "" if excluded is None else int(excluded["trip"]),
        "excluded_site": "" if excluded is None else int(excluded["site"]),
        "excluded_compartment": "" if excluded is None else excluded["compartment"],
        "excluded_group_ph": math.nan if excluded is None else float(excluded["ph"]),
        "excluded_group_n_ph_specimens": (
            math.nan if excluded is None else int(excluded["n_ph_specimens"])
        ),
        "n_groups": int(after["n_groups"]),
        "n_sites": int(after["n_sites"]),
        "residual_df": int(after["residual_df"]),
        "geography_before_partial_r2": float(before["partial_r2"]),
        "geography_before_p": float(before["p"]),
        "geography_after_partial_r2": float(after["partial_r2"]),
        "geography_after_p": float(after["p"]),
        "geography_descriptive_relative_change": float(
            (after["partial_r2"] - before["partial_r2"])
            / before["partial_r2"]
        ),
        "ph_transect_partial_r2": float(ph_spatial["partial_r2"]),
        "ph_transect_p": float(ph_spatial["p"]),
    }


def fit_geographic_influence_sensitivity(
    counts: pd.DataFrame,
    keys: pd.DataFrame,
    group_table: pd.DataFrame,
    coordinates: pd.DataFrame,
    taxa: list[str],
    permutations: int,
    pseudocount: float,
    baseline: pd.DataFrame,
) -> pd.DataFrame:
    """Re-fit the site-level spatial endpoints around the maximum pH group.

    The maximum group is selected deterministically from the composition cohort.
    We report both deletion of that group and deletion of its whole site. Taxa
    stay fixed to the primary full-cohort ranking so the diagnostic isolates
    observation influence rather than changing the response feature set.
    """
    keyed = keys.merge(
        group_table,
        on=["trip", "site", "compartment"],
        how="left",
        validate="one_to_one",
    )
    maximum = keyed.sort_values(
        ["ph", "trip", "site", "compartment"],
        ascending=[False, True, True, True],
        kind="mergesort",
    ).iloc[0]
    maximum_key = (
        int(maximum["trip"]),
        int(maximum["site"]),
        maximum["compartment"],
    )
    key_tuples = [tuple(row) for row in keys[["trip", "site", "compartment"]].to_numpy()]
    keep_maximum_group = np.array([key != maximum_key for key in key_tuples])
    keep_maximum_site = keys["site"].to_numpy(dtype=int) != int(maximum["site"])

    rows = [summarize_geographic_scenario("baseline", baseline)]
    for scenario, scope, keep in (
        ("exclude_singleton_maximum_group", "group", keep_maximum_group),
        ("exclude_maximum_site", "site", keep_maximum_site),
    ):
        scenario_keys = keys.loc[keep].reset_index(drop=True)
        scenario_counts = counts.iloc[:, np.flatnonzero(keep)].copy()
        scenario_counts.columns = pd.MultiIndex.from_frame(scenario_keys)
        result = fit_geographic_adjustment(
            scenario_counts,
            scenario_keys,
            group_table,
            coordinates,
            taxa,
            permutations,
            pseudocount,
        )
        rows.append(
            summarize_geographic_scenario(
                scenario,
                result,
                maximum,
                exclusion_scope=scope,
            )
        )
    return pd.DataFrame(rows)


def fit_xrf_relation(root: Path, grouped: pd.DataFrame) -> pd.DataFrame:
    axis_path = root / "analysis/v3/xrf_community_rescue/laboratory_xrf_axis.tsv"
    axis = pd.read_csv(axis_path, sep="\t").rename(
        columns={"Trip": "trip", "Site": "site", "Type": "compartment"}
    )
    joined = grouped.merge(axis, on=["trip", "site", "compartment"], how="inner")
    formula = "ph ~ elemental_pc1 + C(trip) + C(compartment) + C(site)"
    fit = smf.ols(formula, data=joined).fit(
        cov_type="cluster", cov_kwds={"groups": joined["site"]}
    )
    interval = fit.conf_int().loc["elemental_pc1"]
    return pd.DataFrame(
        [
            {
                "model": "site_fixed_ph_vs_xrf_axis",
                "n_observations": int(fit.nobs),
                "n_sites": int(joined["site"].nunique()),
                "estimate_ph_units_per_pc1": float(fit.params["elemental_pc1"]),
                "std_error": float(fit.bse["elemental_pc1"]),
                "ci_low": float(interval.iloc[0]),
                "ci_high": float(interval.iloc[1]),
                "p": float(fit.pvalues["elemental_pc1"]),
                "formula": formula,
            }
        ]
    )


def analyse(
    root: Path,
    ph_dir: Path,
    permutations: int,
    minimum_group_reads: int,
    dataset_version: str,
    analysis_version: str,
) -> dict[str, Any]:
    accepted_path = ph_dir / "normalized/ph_accepted_measurements.tsv"
    ingest_summary_path = ph_dir / "summary.json"
    ingest_summary = json.loads(ingest_summary_path.read_text(encoding="utf-8"))
    if ingest_summary["dataset_version"] != dataset_version:
        raise ValueError(
            f"Expected {dataset_version}, found {ingest_summary['dataset_version']}"
        )
    if not ingest_summary["release_gate"]["ecology_analysis_frozen"]:
        raise ValueError("The pH source is not frozen for the ecology manuscript")
    output = ph_dir / "ecology"
    output.mkdir(parents=True, exist_ok=True)

    sample_join, grouped = load_sample_level_join(root, accepted_path)
    coordinates = pd.read_csv(
        root / "analysis/v3/spatial_turnover_rescue/results/site_coordinates.tsv",
        sep="\t",
    )
    grouped = grouped.merge(
        coordinates[["site", "transect_km"]], on="site", how="left", validate="many_to_one"
    )
    if grouped["transect_km"].isna().any():
        raise ValueError("Missing canonical transect coordinate in pH cohort")

    alpha_models = fit_alpha_models(grouped)
    paired, paired_omnibus = fit_paired_ph(grouped)
    xrf_relation = fit_xrf_relation(root, grouped)
    counts, count_keys, count_info = load_grouped_counts(
        root, accepted_path, grouped, minimum_group_reads
    )
    keyed = count_keys.merge(grouped, on=["trip", "site", "compartment"], how="left", validate="one_to_one")
    ranked_taxa = rank_taxa(counts, prevalence=0.20)
    if len(ranked_taxa) < 80:
        raise ValueError("Fewer than 80 eligible genera in the frozen pH cohort")

    response_counts = counts.T.to_numpy(dtype=float)
    relative = response_counts / response_counts.sum(axis=1, keepdims=True)
    distance = squareform(pdist(relative, metric="braycurtis"))
    reduced = categorical_design(keyed, include_site=True)
    beta_rows: list[dict[str, Any]] = []
    for target in (0.80, 0.95):
        pcoa, retained = pcoa_coordinates(distance, target)
        result = nested_multivariate_test(
            pcoa,
            reduced,
            keyed["ph"].to_numpy(),
            keyed["site"].to_numpy(),
            permutations,
            SEED + int(target * 100),
        )
        beta_rows.append(
            {
                "representation": "Bray-Curtis PCoA",
                "configuration": f"retain_{int(target * 100)}pct",
                "n_observations": len(keyed),
                "n_sites": int(keyed["site"].nunique()),
                "feature_count": counts.shape[0],
                "retained_axes": pcoa.shape[1],
                "retained_variance_fraction": retained,
                **result,
            }
        )

    eligible_counts = list(dict.fromkeys([min(80, len(ranked_taxa)), min(200, len(ranked_taxa)), len(ranked_taxa)]))
    configurations = [(count, 0.5) for count in eligible_counts]
    if min(200, len(ranked_taxa)) >= 80:
        configurations.append((min(200, len(ranked_taxa)), 1.0))
    for index, (taxon_count, pseudocount) in enumerate(configurations):
        taxa = ranked_taxa[:taxon_count]
        values = counts.loc[taxa].T.to_numpy(dtype=float)
        logged = np.log(values + pseudocount)
        clr = logged - logged.mean(axis=1, keepdims=True)
        result = nested_multivariate_test(
            clr,
            reduced,
            keyed["ph"].to_numpy(),
            keyed["site"].to_numpy(),
            permutations,
            SEED + 200 + index,
        )
        beta_rows.append(
            {
                "representation": "Aitchison CLR",
                "configuration": f"top_{taxon_count}_pseudocount_{pseudocount:g}",
                "n_observations": len(keyed),
                "n_sites": int(keyed["site"].nunique()),
                "feature_count": taxon_count,
                "retained_axes": math.nan,
                "retained_variance_fraction": math.nan,
                **result,
            }
        )
    beta_models = pd.DataFrame(beta_rows)

    geographic = fit_geographic_adjustment(
        counts,
        count_keys,
        grouped,
        coordinates,
        ranked_taxa[: min(200, len(ranked_taxa))],
        permutations,
        pseudocount=0.5,
    )
    influence = fit_geographic_influence_sensitivity(
        counts,
        count_keys,
        grouped,
        coordinates,
        ranked_taxa[: min(200, len(ranked_taxa))],
        permutations,
        pseudocount=0.5,
        baseline=geographic,
    )

    coverage = (
        grouped.groupby(["trip", "compartment"], as_index=False)
        .agg(
            site_campaign_position_groups=("ph", "size"),
            sites=("site", "nunique"),
            pH_specimens=("n_ph_specimens", "sum"),
            ph_mean=("ph", "mean"),
            ph_sd=("ph", "std"),
            ph_min=("ph", "min"),
            ph_max=("ph", "max"),
        )
    )

    sample_join.to_csv(output / "ph_sample_profile_join.tsv", sep="\t", index=False)
    grouped.to_csv(output / "ph_group_analysis_table.tsv", sep="\t", index=False)
    coverage.to_csv(output / "ph_coverage.tsv", sep="\t", index=False)
    alpha_models.to_csv(output / "ph_alpha_models.tsv", sep="\t", index=False)
    paired.to_csv(output / "ph_paired_position_contrasts.tsv", sep="\t", index=False)
    beta_models.to_csv(output / "ph_composition_models.tsv", sep="\t", index=False)
    geographic.to_csv(output / "ph_geographic_adjustment.tsv", sep="\t", index=False)
    influence.to_csv(output / "ph_influence_sensitivity.tsv", sep="\t", index=False)
    xrf_relation.to_csv(output / "ph_xrf_relation.tsv", sep="\t", index=False)

    primary_alpha = alpha_models.set_index("model").loc["site_fixed_primary"]
    primary_beta = beta_models[
        (beta_models["representation"] == "Aitchison CLR")
        & (beta_models["configuration"] == "top_200_pseudocount_0.5")
    ].iloc[0]
    geo_index = geographic.set_index("model")
    geo_without = geo_index.loc["same_cohort_without_ph_adjustment"]
    geo_with = geo_index.loc["same_cohort_with_ph_adjustment"]
    influence_index = influence.set_index("scenario")
    influence_maximum = influence_index.loc["exclude_singleton_maximum_group"]
    influence_site = influence_index.loc["exclude_maximum_site"]
    summary: dict[str, Any] = {
        "schema_version": analysis_version,
        "status": "FROZEN_ECOLOGY_ANALYSIS",
        "dataset_version": dataset_version,
        "source_workbook_sha256": ingest_summary["source"]["sha256"],
        "ingest_dispositions": ingest_summary["counts"]["dispositions"],
        "counts": {
            "accepted_ph_specimens": ingest_summary["counts"]["admitted_rows"],
            "accepted_specimens_with_ecology_profile": len(sample_join),
            "site_campaign_position_groups": len(grouped),
            "composition_groups": len(count_keys),
            "sites": int(grouped["site"].nunique()),
            "eligible_genera": len(ranked_taxa),
            **count_info,
        },
        "ph_distribution_group_means": {
            "mean": float(grouped["ph"].mean()),
            "sd": float(grouped["ph"].std()),
            "min": float(grouped["ph"].min()),
            "max": float(grouped["ph"].max()),
        },
        "alpha_primary": primary_alpha.to_dict(),
        "composition_primary": primary_beta.to_dict(),
        "paired_position_omnibus": paired_omnibus,
        "geographic_same_cohort": {
            "without_ph_adjustment_partial_r2": float(geo_without["partial_r2"]),
            "without_ph_adjustment_p": float(geo_without["p"]),
            "with_ph_adjustment_partial_r2": float(geo_with["partial_r2"]),
            "with_ph_adjustment_p": float(geo_with["p"]),
            "descriptive_relative_change": float(
                (geo_with["partial_r2"] - geo_without["partial_r2"])
                / geo_without["partial_r2"]
            ),
        },
        "maximum_group_influence": {
            "trip": int(influence_maximum["excluded_trip"]),
            "site": int(influence_maximum["excluded_site"]),
            "compartment": influence_maximum["excluded_compartment"],
            "ph": float(influence_maximum["excluded_group_ph"]),
            "n_ph_specimens": int(
                influence_maximum["excluded_group_n_ph_specimens"]
            ),
            "exclude_group_ph_transect_partial_r2": float(
                influence_maximum["ph_transect_partial_r2"]
            ),
            "exclude_group_geography_after_partial_r2": float(
                influence_maximum["geography_after_partial_r2"]
            ),
            "exclude_site_ph_transect_partial_r2": float(
                influence_site["ph_transect_partial_r2"]
            ),
            "exclude_site_geography_after_partial_r2": float(
                influence_site["geography_after_partial_r2"]
            ),
            "all_refit_p_values_at_permutation_floor": bool(
                (influence["ph_transect_p"] == 1 / (permutations + 1)).all()
                and (
                    influence["geography_after_p"]
                    == 1 / (permutations + 1)
                ).all()
            ),
        },
        "release_gate": {
            "ecology_analysis_frozen": True,
            "ecology_manuscript_claim_allowed": True,
            "canonical_kg_import_allowed": ingest_summary["release_gate"].get(
                "canonical_kg_import_allowed", False
            ),
            "shared_with_data_paper": (
                ingest_summary["dataset_purpose"] == "shared-manuscripts"
            ),
            "future_versions_may_add_measurements": True,
        },
        "interpretation_boundary": (
            "pH availability is incomplete and non-random across trips and "
            "specimens. These estimates describe the admitted measurements in "
            "the frozen shared cohort and do not represent a complete pH "
            "survey. Future corrections require a new dataset version."
        ),
    }
    summary = json_safe(summary)
    (output / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    readme = [
        "# Frozen pH ecology sensitivity",
        "",
        f"Dataset version: `{dataset_version}`. Analysis version: `{analysis_version}`.",
        "",
        f"The immutable, incomplete workbook contributed {len(sample_join)} exact pH/specimen/ecology joins and {len(grouped)} site-campaign-position groups.",
        f"Group-mean pH ranged from {grouped['ph'].min():.3f} to {grouped['ph'].max():.3f}.",
        "",
        "The pipeline tests exact specimen reconciliation, site-fixed alpha models, paired position contrasts, Bray-Curtis and Aitchison composition models, a same-cohort geographic model before and after pH adjustment, and deletion diagnostics for the singleton maximum-pH group and its site.",
        "",
        "Rows that are pending, depleted, date-quarantined, or quality-control-quarantined are absent from every model. Availability is non-random, so results are bounded to this fixed cohort.",
        "",
        "The ecology and data papers use this same frozen source. Future corrections or recovered measurements require a successor version and a new comparison.",
        "",
    ]
    (output / "README.md").write_text("\n".join(readme), encoding="utf-8")

    software_versions = {
        "python": platform.python_version(),
        "numpy": importlib.metadata.version("numpy"),
        "pandas": importlib.metadata.version("pandas"),
        "scipy": importlib.metadata.version("scipy"),
        "statsmodels": importlib.metadata.version("statsmodels"),
    }
    (output / "software_versions.json").write_text(
        json.dumps(software_versions, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    source_path = Path(ingest_summary["source"]["path"])
    if not source_path.is_absolute():
        source_path = root / source_path
    input_paths = [
        source_path,
        accepted_path,
        ingest_summary_path,
        root / "analysis/v2/review/cache/alpha.tsv",
        root / "analysis/v2/review/cache/genus_counts.tsv",
        root / "analysis/v3/spatial_turnover_rescue/results/site_coordinates.tsv",
        root / "analysis/v3/xrf_community_rescue/laboratory_xrf_axis.tsv",
        Path(__file__).resolve(),
    ]
    input_rows = []
    for path in input_paths:
        input_rows.append(
            {
                "path": (
                    str(path.relative_to(root))
                    if path.is_relative_to(root)
                    else str(path)
                ),
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
            }
        )
    pd.DataFrame(input_rows).to_csv(
        output / "input_manifest.tsv", sep="\t", index=False
    )

    output_files = sorted(
        path
        for path in output.iterdir()
        if path.is_file() and path.name != "SHA256SUMS"
    )
    checksums = [f"{sha256_file(path)}  {path.name}" for path in output_files]
    (output / "SHA256SUMS").write_text("\n".join(checksums) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--project-root", type=Path, default=Path(__file__).resolve().parents[2]
    )
    parser.add_argument("--ph-dir", type=Path, required=True)
    parser.add_argument("--permutations", type=int, default=999)
    parser.add_argument("--minimum-group-reads", type=int, default=2000)
    parser.add_argument("--dataset-version", default=DEFAULT_DATASET_VERSION)
    parser.add_argument("--analysis-version", default=DEFAULT_ANALYSIS_VERSION)
    args = parser.parse_args()
    summary = analyse(
        args.project_root.resolve(),
        args.ph_dir.resolve(),
        args.permutations,
        args.minimum_group_reads,
        args.dataset_version,
        args.analysis_version,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
