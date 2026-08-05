#!/usr/bin/env python3
"""Canonical, grouped claim-rescue analyses for the ecology manuscript.

The script uses the cached, depth-normalized alpha-diversity table and daily
weather inputs.  It does not interpret campaign as an unconfounded season and
it never treats technical replicates or pairwise distances as independent.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import asdict, dataclass
from datetime import timedelta
from pathlib import Path
from typing import Iterable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
from scipy import stats
from statsmodels.genmod.cov_struct import Exchangeable


WINDOWS = (1, 3, 7, 10, 14, 30)
TYPE_ORDER = ("Surface", "Deep", "Rhizosphere")
CORE_SITES = range(1, 61)
TRIP1_ONLY_SITES = (61, 62, 63, 64)
TYPE_LABELS = {
    "Surface": "Surface",
    "Deep": "Shallow subsurface",
    "Rhizosphere": "Root-adjacent",
}
BOOTSTRAP_RESAMPLES = 1_000_000
BOOTSTRAP_SEED = 20260723
BOOTSTRAP_BATCH_SIZE = 25_000
LEGACY_RAIN_STATUS = "SUPERSEDED"
LEGACY_RAIN_REPLACEMENT = "analysis/v3/rain_response_window/"
LEGACY_RAIN_REASON = (
    "Historical compartment-wise screen; superseded because it does not "
    "estimate the paired surface-minus-shallow contrast with site- and "
    "campaign-specific position baselines or calibrate the complete window "
    "search while preserving the spatial rainfall field."
)


@dataclass
class ClaimDecision:
    claim: str
    current_test: str
    status: str
    permitted_wording: str
    reason: str
    evidence_file: str


def bh_fdr(values: Iterable[float]) -> np.ndarray:
    values = np.asarray(list(values), dtype=float)
    order = np.argsort(values)
    ranked = values[order] * len(values) / (np.arange(len(values)) + 1)
    ranked = np.minimum.accumulate(ranked[::-1])[::-1]
    adjusted = np.empty(len(values))
    adjusted[order] = np.clip(ranked, 0, 1)
    return adjusted


def bootstrap_mean_ci(
    values: np.ndarray,
    *,
    resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
    batch_size: int = BOOTSTRAP_BATCH_SIZE,
) -> tuple[float, float]:
    """Return a reproducible percentile interval without a large index array.

    The primary root-adjacent--shallow endpoint lies very close to zero.
    Five thousand resamples made the sign of that endpoint depend on the
    random seed, so the canonical analysis uses one million resamples and
    reports the endpoint only to two decimal places in the manuscript.
    """
    values = np.asarray(values, dtype=float)
    if values.ndim != 1 or values.size < 3:
        raise ValueError("Bootstrap input must contain at least three values")
    if resamples < 1 or batch_size < 1:
        raise ValueError("Bootstrap resamples and batch size must be positive")
    rng = np.random.default_rng(seed)
    bootstrap_means = np.empty(resamples, dtype=float)
    for start in range(0, resamples, batch_size):
        stop = min(start + batch_size, resamples)
        sampled = rng.choice(
            values,
            size=(stop - start, values.size),
            replace=True,
        )
        bootstrap_means[start:stop] = sampled.mean(axis=1)
    low, high = np.quantile(bootstrap_means, [0.025, 0.975])
    return float(low), float(high)


def load_alpha(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, sep="\t", index_col=0)
    required = {
        "Trip",
        "Site",
        "Type",
        "depth",
        "richness_rare",
        "shannon",
    }
    missing = required - set(frame)
    if missing:
        raise ValueError(f"Alpha table is missing columns: {sorted(missing)}")
    frame = frame[frame["Trip"].between(1, 5)].copy()
    frame["Site"] = frame["Site"].astype(int)
    frame["Trip"] = frame["Trip"].astype(int)
    frame["Type"] = frame["Type"].replace({"Rhizo": "Rhizosphere"})
    frame = frame[frame["Type"].isin(TYPE_ORDER)]
    return frame


def aggregate_profiles(alpha: pd.DataFrame) -> pd.DataFrame:
    return (
        alpha.groupby(["Trip", "Site", "Type"], as_index=False)
        .agg(
            shannon=("shannon", "mean"),
            richness_rare=("richness_rare", "mean"),
            sequencing_depth=("depth", "sum"),
            n_profiles=("shannon", "size"),
        )
        .sort_values(["Trip", "Site", "Type"])
    )


def gee_terms(frame: pd.DataFrame, outcome: str) -> tuple[pd.DataFrame, float]:
    formula = (
        f"{outcome} ~ C(Trip) * "
        "C(Type, Treatment(reference='Surface'))"
    )
    fit = smf.gee(
        formula,
        groups="Site",
        data=frame,
        family=None,
        cov_struct=Exchangeable(),
    ).fit()
    table = pd.DataFrame(
        {
            "term": fit.params.index,
            "estimate": fit.params.values,
            "std_error": fit.bse.values,
            "z": fit.tvalues.values,
            "p": fit.pvalues.values,
            "ci_low": fit.conf_int()[0].values,
            "ci_high": fit.conf_int()[1].values,
        }
    )
    # Compare the full campaign-by-compartment model to the additive model
    # using a Wald test of every interaction term.
    interaction_rows = [
        i for i, term in enumerate(fit.params.index) if ":" in term
    ]
    if interaction_rows:
        restriction = np.zeros((len(interaction_rows), len(fit.params)))
        for row, column in enumerate(interaction_rows):
            restriction[row, column] = 1
        interaction_p = float(fit.wald_test(restriction, scalar=True).pvalue)
    else:
        interaction_p = math.nan
    return table, interaction_p


def paired_effects(frame: pd.DataFrame, metric: str) -> pd.DataFrame:
    rows = []
    comparisons = (
        ("Deep", "Surface"),
        ("Rhizosphere", "Surface"),
        ("Rhizosphere", "Deep"),
    )
    for trip in ("all", 1, 2, 3, 4, 5):
        subset = frame if trip == "all" else frame[frame["Trip"] == trip]
        if trip == "all":
            subset = (
                subset.groupby(["Site", "Type"], as_index=False)[metric].mean()
            )
        wide = subset.pivot_table(
            index="Site", columns="Type", values=metric, aggfunc="mean"
        )
        for first, second in comparisons:
            pair = wide[[first, second]].dropna()
            difference = pair[first] - pair[second]
            if len(difference) < 3:
                continue
            test = stats.wilcoxon(difference)
            ci_low, ci_high = bootstrap_mean_ci(
                difference.to_numpy(),
                resamples=BOOTSTRAP_RESAMPLES,
                seed=BOOTSTRAP_SEED,
            )
            rows.append(
                {
                    "trip": trip,
                    "metric": metric,
                    "comparison": f"{first}-{second}",
                    "n_sites": len(difference),
                    "mean_difference": difference.mean(),
                    "median_difference": difference.median(),
                    "ci_low": ci_low,
                    "ci_high": ci_high,
                    "wilcoxon_w": test.statistic,
                    "p": test.pvalue,
                    "fraction_positive": (difference > 0).mean(),
                    "bootstrap_resamples": BOOTSTRAP_RESAMPLES,
                    "bootstrap_seed": BOOTSTRAP_SEED,
                }
            )
    result = pd.DataFrame(rows)
    result["q_within_metric"] = bh_fdr(result["p"])
    return result


def load_site_metadata(root: Path) -> pd.DataFrame:
    rows = []
    for trip in range(1, 6):
        path = root / f"data/metadata/geodata/trip{trip}_geodata.tsv"
        frame = pd.read_csv(path, sep="\t")
        # The Trip 3 geodata carries the label "19.5" (dated 2024-03-18), a
        # distinct location between sites 19 and 20, and "12.5+A". pd.to_numeric
        # accepts "19.5" and the int() below truncates it to 19, silently
        # duplicating the genuine site-19/Trip-3 row with the wrong date and
        # inflating the site--campaign count from 198 to 199. String matching
        # elsewhere does not prevent this, because it happens after this
        # conversion. Keep only labels that are already integers.
        frame = frame[frame["Site"].astype(str).str.fullmatch(r"[0-9]+")]
        frame["Site"] = pd.to_numeric(frame["Site"], errors="coerce")
        frame = frame.dropna(subset=["Site", "Latitude", "Longitude", "CenterDate"])
        for _, row in frame.iterrows():
            rows.append(
                {
                    "Trip": trip,
                    "Site": int(row["Site"]),
                    "Date": pd.to_datetime(row["CenterDate"]),
                    "Latitude": float(row["Latitude"]),
                    "Longitude": float(row["Longitude"]),
                }
            )
    return pd.DataFrame(rows)


def add_rain_windows(
    observations: pd.DataFrame, site_meta: pd.DataFrame, weather_path: Path
) -> pd.DataFrame:
    weather = pd.read_csv(weather_path, sep="\t")
    weather["Site"] = weather["Site"].astype(str)
    weather["Date"] = pd.to_datetime(weather["Date"])
    weather["Precip_mm"] = pd.to_numeric(
        weather["Precip_mm"], errors="coerce"
    ).fillna(0)
    weather_by_site = {
        site: group.sort_values("Date")
        for site, group in weather.groupby("Site")
    }
    joined = observations.merge(site_meta, on=["Trip", "Site"], how="inner")
    for window in WINDOWS:
        values = []
        for _, row in joined.iterrows():
            site_weather = weather_by_site.get(str(row["Site"]))
            if site_weather is None:
                values.append(np.nan)
                continue
            start = row["Date"] - timedelta(days=window)
            mask = (
                (site_weather["Date"] > start)
                & (site_weather["Date"] <= row["Date"])
            )
            values.append(float(site_weather.loc[mask, "Precip_mm"].sum()))
        joined[f"rain_{window}d"] = values
    return joined


def moran_i(
    residuals: np.ndarray,
    trips: np.ndarray,
    latitude: np.ndarray,
    longitude: np.ndarray,
    permutations: int = 999,
) -> tuple[float, float]:
    residuals = np.asarray(residuals, dtype=float)
    coords = np.column_stack([latitude, longitude])
    n = len(residuals)
    weights = np.zeros((n, n), dtype=float)
    for trip in np.unique(trips):
        indices = np.where(trips == trip)[0]
        if len(indices) < 3:
            continue
        local = coords[indices]
        distance = np.sqrt(
            ((local[:, None, :] - local[None, :, :]) ** 2).sum(axis=2)
        )
        np.fill_diagonal(distance, np.inf)
        k = min(5, len(indices) - 1)
        for row, neighbours in enumerate(
            np.argsort(distance, axis=1)[:, :k]
        ):
            weights[indices[row], indices[neighbours]] = 1
    weights = np.maximum(weights, weights.T)
    total_weight = weights.sum()
    centered = residuals - residuals.mean()
    denominator = np.square(centered).sum()
    if total_weight == 0 or denominator == 0:
        return math.nan, math.nan
    observed = (
        n / total_weight * (weights * np.outer(centered, centered)).sum()
        / denominator
    )
    rng = np.random.default_rng(20260723)
    permuted = []
    for _ in range(permutations):
        candidate = centered.copy()
        for trip in np.unique(trips):
            indices = np.where(trips == trip)[0]
            candidate[indices] = rng.permutation(candidate[indices])
        permuted.append(
            n
            / total_weight
            * (weights * np.outer(candidate, candidate)).sum()
            / np.square(candidate).sum()
        )
    p = (1 + np.sum(np.abs(permuted) >= abs(observed))) / (
        permutations + 1
    )
    return float(observed), float(p)


def fit_rain_models(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Fit the full compartment-by-window antecedent-rainfall family.

    Three soil positions times six antecedent windows give 18 tests.  Two
    Benjamini--Hochberg corrections are reported: ``q_within_compartment``
    over the six windows of one compartment, and ``q_global`` over the
    declared family of all 18 tests.  The global family is the one declared
    in the manuscript; the within-compartment column is retained so a reader
    can see how much of the correction the family size contributes.
    """
    model_rows = []
    loco_rows = []
    for compartment in TYPE_ORDER:
        subset = frame[frame["Type"] == compartment]
        for window in WINDOWS:
            column = f"rain_{window}d"
            data = subset.dropna(
                subset=["shannon", column, "Latitude", "Longitude"]
            ).copy()
            formula = (
                f"shannon ~ {column} + C(Trip) + Latitude + Longitude + "
                "I(Latitude ** 2) + I(Longitude ** 2)"
            )
            fit = smf.ols(formula, data=data).fit(
                cov_type="cluster", cov_kwds={"groups": data["Site"]}
            )
            coefficient = float(fit.params[column])
            ci = fit.conf_int().loc[column]
            moran, moran_p = moran_i(
                fit.resid.to_numpy(),
                data["Trip"].to_numpy(),
                data["Latitude"].to_numpy(),
                data["Longitude"].to_numpy(),
            )
            model_rows.append(
                {
                    "compartment": compartment,
                    "compartment_label": TYPE_LABELS[compartment],
                    "window_days": window,
                    "n_site_campaigns": len(data),
                    "n_sites": data["Site"].nunique(),
                    "estimate_per_mm": coefficient,
                    "std_error": float(fit.bse[column]),
                    "ci_low": float(ci.iloc[0]),
                    "ci_high": float(ci.iloc[1]),
                    "p": float(fit.pvalues[column]),
                    "residual_moran_i": moran,
                    "residual_moran_p": moran_p,
                }
            )
            for omitted in sorted(data["Trip"].unique()):
                reduced = data[data["Trip"] != omitted]
                reduced_fit = smf.ols(formula, data=reduced).fit(
                    cov_type="cluster",
                    cov_kwds={"groups": reduced["Site"]},
                )
                loco_ci = reduced_fit.conf_int().loc[column]
                loco_rows.append(
                    {
                        "compartment": compartment,
                        "compartment_label": TYPE_LABELS[compartment],
                        "window_days": window,
                        "omitted_trip": omitted,
                        "n_site_campaigns": len(reduced),
                        "estimate_per_mm": reduced_fit.params[column],
                        "ci_low": loco_ci.iloc[0],
                        "ci_high": loco_ci.iloc[1],
                        "p": reduced_fit.pvalues[column],
                    }
                )
    models = pd.DataFrame(model_rows)
    models["q_within_compartment"] = models.groupby("compartment")["p"].transform(
        lambda values: bh_fdr(values)
    )
    models["q_global"] = bh_fdr(models["p"])
    models["n_tests_in_global_family"] = len(models)
    return models, pd.DataFrame(loco_rows)


def build_claim_ledger(
    model_terms: pd.DataFrame,
    interaction_p: float,
    paired: pd.DataFrame,
    rain: pd.DataFrame,
    rain_loco: pd.DataFrame,
    root: Path,
    include_downstream: bool = True,
) -> list[ClaimDecision]:
    campaign_terms = model_terms[
        model_terms["term"].str.startswith("C(Trip)")
        & ~model_terms["term"].str.contains(":")
    ]
    campaign_detected = bool((campaign_terms["p"] < 0.05).any())

    root_row = paired[
        (paired["trip"] == "all")
        & (paired["metric"] == "shannon")
        & (paired["comparison"] == "Rhizosphere-Surface")
    ].iloc[0]
    root_mean_ci_excludes_zero = bool(
        root_row["ci_high"] < 0 or root_row["ci_low"] > 0
    )
    depth_wet = paired[
        (paired["metric"] == "shannon")
        & (paired["comparison"] == "Deep-Surface")
        & (paired["trip"].isin([1, 3]))
    ]
    depth_campaign_pattern = bool(
        len(depth_wet) == 2
        and (depth_wet["mean_difference"] > 0).all()
        and (depth_wet["q_within_metric"] < 0.05).all()
    )

    rain14 = rain[
        (rain["window_days"] == 14) & (rain["compartment"] == "Surface")
    ].iloc[0]
    loco14 = rain_loco[
        (rain_loco["window_days"] == 14)
        & (rain_loco["compartment"] == "Surface")
    ]
    rain_sign = np.sign(rain14["estimate_per_mm"])
    rain_loco_stable = bool(
        rain_sign != 0
        and len(loco14) == 5
        and (np.sign(loco14["estimate_per_mm"]) == rain_sign).all()
    )
    rain_rescued = bool(
        rain14["q_global"] < 0.05
        and rain_loco_stable
        and rain14["residual_moran_p"] >= 0.05
    )
    rain_family_survivors = int((rain["q_global"] < 0.05).sum())
    rain_family_min_q_within = float(rain["q_within_compartment"].min())
    rain_family_min_q_global = float(rain["q_global"].min())
    rain_family_supported = rain_family_survivors > 0

    return [
        ClaimDecision(
            claim="seasonal restructuring",
            current_test="Campaign fixed effects with site-clustered GEE",
            status="campaign_difference" if campaign_detected else "not_supported",
            permitted_wording=(
                "Community diversity differed among the five campaigns; the "
                "design cannot separate season from campaign and laboratory batch."
                if campaign_detected
                else "No robust campaign-level diversity difference was detected."
            ),
            reason=(
                "Season is structurally aliased with campaign; the analysis "
                "therefore reports campaign effects only."
            ),
            evidence_file="campaign_compartment_model.tsv",
        ),
        ClaimDecision(
            claim="14-day post-rain bloom",
            current_test=(
                "SUPERSEDED historical diagnostic: trip-adjusted spatial "
                "trend model, six-window FDR and campaign omission"
            ),
            status="superseded",
            permitted_wording=(
                "Do not use this historical diagnostic for a rainfall claim; "
                f"use {LEGACY_RAIN_REPLACEMENT}."
            ),
            reason=(
                f"{LEGACY_RAIN_REASON} Historical surface 14-day "
                f"q_global={rain14['q_global']:.3g} "
                f"(q_within_compartment={rain14['q_within_compartment']:.3g}); "
                f"LOCO sign-stable={rain_loco_stable}; residual Moran "
                f"p={rain14['residual_moran_p']:.3g}."
            ),
            evidence_file="../rain_response_window/analysis_decision.json",
        ),
        ClaimDecision(
            claim="antecedent-rainfall response in any compartment",
            current_test=(
                "SUPERSEDED historical diagnostic: 18 compartment-by-window "
                "trip-adjusted spatial trend models"
            ),
            status="superseded",
            permitted_wording=(
                "Do not use this historical diagnostic for a rainfall claim; "
                f"use {LEGACY_RAIN_REPLACEMENT}."
            ),
            reason=(
                f"{LEGACY_RAIN_REASON} Historical screen: "
                f"{rain_family_survivors}/{len(rain)} tests with q_global<0.05; "
                f"smallest q_within_compartment={rain_family_min_q_within:.3g}; "
                f"smallest q_global={rain_family_min_q_global:.3g}."
            ),
            evidence_file="../rain_response_window/analysis_decision.json",
        ),
        ClaimDecision(
            claim="root selective filter",
            current_test="Paired site-level root-adjacent minus surface Shannon",
            status=(
                "lower_diversity_pattern"
                if (
                    root_row["q_within_metric"] < 0.05
                    and root_mean_ci_excludes_zero
                )
                else "paired_distribution_shift_uncertain_magnitude"
                if root_row["q_within_metric"] < 0.05
                else "not_supported"
            ),
            permitted_wording=(
                "Root-adjacent alpha diversity was lower in paired site-level "
                "comparisons; plant-imposed selection was not measured."
                if (
                    root_row["q_within_metric"] < 0.05
                    and root_mean_ci_excludes_zero
                )
                else "The paired distribution shifted toward lower root-adjacent "
                "alpha diversity, but the bootstrap interval for the mean crossed "
                "zero; treat the magnitude as uncertain and do not infer filtering."
                if root_row["q_within_metric"] < 0.05
                else "A robust root-adjacent alpha-diversity difference was not detected."
            ),
            reason=(
                f"Paired mean difference={root_row['mean_difference']:.3f}, "
                f"95% bootstrap CI [{root_row['ci_low']:.3f}, "
                f"{root_row['ci_high']:.3f}], q={root_row['q_within_metric']:.3g}."
            ),
            evidence_file="paired_compartment_effects.tsv",
        ),
        ClaimDecision(
            claim="subsurface refugium",
            current_test="Campaign-by-compartment GEE and paired campaign contrasts",
            status=(
                "campaign_dependent_depth_pattern"
                if interaction_p < 0.05 and depth_campaign_pattern
                else "not_supported_as_refugium"
            ),
            permitted_wording=(
                "The 5–10 cm layer had higher paired diversity in Trip 1 and a "
                "similar, less precisely estimated shift in Trip 3, but not in "
                "Trips 4–5. This is a campaign-dependent depth pattern; persistence, "
                "buffering, and reseeding were not measured."
                if interaction_p < 0.05 and depth_campaign_pattern
                else "The data do not establish a persistent subsurface refugium."
            ),
            reason=(
                f"Campaign-by-compartment Wald p={interaction_p:.3g}; "
                f"Trips 1 and 3 paired effects both positive/FDR-significant="
                f"{depth_campaign_pattern}; Trip 3 mean bootstrap interval crosses zero."
            ),
            evidence_file="paired_compartment_effects.tsv",
        ),
        ClaimDecision(
            claim="XRF salinity mechanism",
            current_test="Separate XRF audit plus forthcoming pH and EC calibration",
            status="pending_xrf_ph_ec",
            permitted_wording=(
                "Use 'evaporite-associated elemental/mineralogical axis' until "
                "independent EC calibration supports a salinity proxy."
            ),
            reason="XRF-derived salinity is circular without independent EC.",
            evidence_file="../../xrf_audit/xrf_evidence_report.md",
        ),
        *(
            downstream_decisions(root)
            if include_downstream
            else []
        ),
    ]


# The four advanced analyses below were pending when this ledger was first
# written.  They are now implemented in their own directories and each emits a
# machine-readable verdict.  The ledger imports those verdicts rather than
# restating them, so a stale "pending" row cannot survive a rerun.
DOWNSTREAM_VERDICTS = (
    {
        "claim": "network restructuring",
        "current_test": "Compositional, null-calibrated network inference",
        "path": "analysis/v3/network_rescue/results/claim_verdict.json",
        "status_key": "descriptive_association_status",
        "reason_key": "reason",
        "evidence_file": "../network_rescue/results/network_metrics.tsv",
    },
    {
        "claim": "dispersal limitation from betaNTI/RCBray",
        "current_test": "Tree/signal/null-model sensitivity grid",
        "path": "analysis/v3/phylo_signal_results/phylo_signal_summary.json",
        "status_key": "status",
        "reason_key": "prohibited_wording",
        "evidence_file": "../phylo_signal_results/phylo_signal_distance_classes.tsv",
    },
    {
        "claim": "functional redundancy",
        "current_test": "Resolution-matched genome-label null",
        "path": (
            "analysis/v3/functional_redundancy_results/"
            "functional_redundancy_summary.json"
        ),
        "status_key": "status",
        "reason_key": "limitations",
        "evidence_file": "../functional_redundancy_results/functional_redundancy_null.tsv",
    },
    {
        "claim": "trace-gas-powered carbon fixation",
        "current_test": "Joint RuBisCO/PRK source-call screen on recovered genomes",
        "path": (
            "analysis/v3/measured_function_summary_results/"
            "encoded_function_summary.json"
        ),
        "status_key": "status",
        "reason_key": "not_supported",
        "evidence_file": "../measured_function_summary_results/pathway_screen.tsv",
    },
)


def downstream_decisions(root: Path) -> list[ClaimDecision]:
    """Import the four advanced verdicts, failing closed if any is absent."""
    decisions = []
    for spec in DOWNSTREAM_VERDICTS:
        path = root / spec["path"]
        if not path.exists():
            raise FileNotFoundError(
                f"Claim ledger requires the canonical verdict {path}. "
                "Re-run the corresponding analysis before rebuilding the ledger."
            )
        verdict = json.loads(path.read_text())
        missing = {
            "permitted_wording",
            spec["status_key"],
            spec["reason_key"],
        } - set(verdict)
        if missing:
            raise ValueError(f"{path} is missing required keys: {sorted(missing)}")
        reason = verdict[spec["reason_key"]]
        if isinstance(reason, list):
            reason = " ".join(str(item).rstrip(".") + "." for item in reason)
        decisions.append(
            ClaimDecision(
                claim=spec["claim"],
                current_test=spec["current_test"],
                status=verdict[spec["status_key"]],
                permitted_wording=verdict["permitted_wording"],
                reason=str(reason),
                evidence_file=spec["evidence_file"],
            )
        )
    return decisions


def write_figure(
    aggregate: pd.DataFrame,
    paired: pd.DataFrame,
    rain: pd.DataFrame,
    output: Path,
) -> None:
    plt.rcParams.update(
        {
            "font.size": 9,
            "axes.titlesize": 10,
            "axes.labelsize": 9,
            "xtick.labelsize": 8,
            "ytick.labelsize": 8,
            "pdf.fonttype": 42,
        }
    )
    fig, axes = plt.subplots(1, 3, figsize=(10.5, 3.4))

    summary = (
        aggregate.groupby(["Trip", "Type"])["shannon"]
        .agg(["mean", "sem"])
        .reset_index()
    )
    for sample_type, color in zip(TYPE_ORDER, ("#C17C36", "#3F7CAC", "#668F5A")):
        part = summary[summary["Type"] == sample_type]
        axes[0].errorbar(
            part["Trip"],
            part["mean"],
            yerr=1.96 * part["sem"],
            marker="o",
            capsize=2,
            color=color,
            label=TYPE_LABELS[sample_type],
        )
    axes[0].set(
        xlabel="Campaign",
        ylabel="Site-level mean Shannon diversity",
        title="(a) Five campaigns, shown separately",
        xticks=range(1, 6),
    )
    axes[0].legend(frameon=False, fontsize=7)

    depth = paired[
        (paired["metric"] == "shannon")
        & (paired["comparison"] == "Deep-Surface")
        & (paired["trip"] != "all")
    ].copy()
    axes[1].errorbar(
        depth["trip"].astype(int),
        depth["mean_difference"],
        yerr=[
            depth["mean_difference"] - depth["ci_low"],
            depth["ci_high"] - depth["mean_difference"],
        ],
        fmt="o",
        color="#3F7CAC",
        capsize=3,
    )
    axes[1].axhline(0, color="black", linewidth=0.7)
    axes[1].set(
        xlabel="Campaign",
        ylabel="Shallow subsurface − surface Shannon",
        title="(b) Depth effect is campaign-dependent",
        xticks=range(1, 6),
    )

    axes[2].axis("off")
    axes[2].text(
        0.5,
        0.62,
        "SUPERSEDED",
        color="#B22222",
        fontsize=18,
        fontweight="bold",
        ha="center",
        va="center",
        transform=axes[2].transAxes,
    )
    axes[2].text(
        0.5,
        0.39,
        "Historical compartment-wise rain screen\n"
        "Do not use for inference\n"
        "See analysis/v3/rain_response_window/",
        fontsize=9,
        ha="center",
        va="center",
        transform=axes[2].transAxes,
    )
    fig.tight_layout()
    fig.savefig(
        output,
        bbox_inches="tight",
        metadata={
            "Title": "Empty Quarter grouped ecology claim-rescue summary",
            "Creator": "analysis/v3/claim_rescue.py",
            "CreationDate": None,
            "ModDate": None,
        },
    )
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
    )
    parser.add_argument("--alpha", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--skip-downstream",
        action="store_true",
        help=(
            "Write the core campaign, rainfall, compartment and XRF claim "
            "rows without importing advanced verdict files. Use this in the "
            "clean core workflow, where advanced analyses have not run yet."
        ),
    )
    args = parser.parse_args()

    root = args.project_root.resolve()
    alpha_path = args.alpha or root / "analysis/v2/review/cache/alpha.tsv"
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)

    alpha = load_alpha(alpha_path)
    aggregate_all = aggregate_profiles(alpha)
    aggregate_all["analysis_cohort"] = np.where(
        aggregate_all["Site"].isin(TRIP1_ONLY_SITES),
        "trip1_only_nonrevisited",
        "core_sites_1_60",
    )
    aggregate_all.to_csv(
        output / "site_campaign_compartment_observations.tsv",
        sep="\t",
        index=False,
    )

    # Sites 61–64 were genuine Trip-1 sampling sites. They were removed from
    # the revisit design because their regions were inaccessible, so they
    # remain in the release/descriptive inventory but are not used for
    # repeated-campaign ecological inference.
    aggregate = aggregate_all[aggregate_all["Site"].isin(CORE_SITES)].copy()
    model_terms, interaction_p = gee_terms(aggregate, "shannon")
    model_terms["interaction_wald_p"] = interaction_p
    model_terms.to_csv(
        output / "campaign_compartment_model.tsv", sep="\t", index=False
    )

    paired = pd.concat(
        [
            paired_effects(aggregate, "shannon"),
            paired_effects(aggregate.dropna(subset=["richness_rare"]), "richness_rare"),
        ],
        ignore_index=True,
    )
    paired.to_csv(
        output / "paired_compartment_effects.tsv", sep="\t", index=False
    )

    site_meta = load_site_metadata(root)
    rain_frame = add_rain_windows(
        aggregate.copy(),
        site_meta,
        root / "data/processed/climate/daily_weather.tsv",
    )
    rain, rain_loco = fit_rain_models(rain_frame)
    for table in (rain, rain_loco):
        table.insert(0, "artifact_status", LEGACY_RAIN_STATUS)
        table.insert(1, "superseded_by", LEGACY_RAIN_REPLACEMENT)
        table.insert(2, "supersession_reason", LEGACY_RAIN_REASON)
    rain.to_csv(output / "rain_window_models.tsv", sep="\t", index=False)
    rain_loco.to_csv(output / "rain_leave_one_campaign.tsv", sep="\t", index=False)

    ledger = build_claim_ledger(
        model_terms,
        interaction_p,
        paired,
        rain,
        rain_loco,
        root,
        include_downstream=not args.skip_downstream,
    )
    pd.DataFrame([asdict(item) for item in ledger]).to_csv(
        output / "claim_ledger.tsv", sep="\t", index=False
    )
    (output / "claim_ledger.json").write_text(
        json.dumps([asdict(item) for item in ledger], indent=2) + "\n"
    )
    write_figure(
        aggregate, paired, rain, output / "claim_rescue_summary.pdf"
    )

    cohort_rows = [
        {
            "cohort": "all_observed_sites",
            "site_definition": "All genuine sampling sites, including 61–64",
            "n_alpha_profiles": len(alpha),
            "n_site_campaign_compartment_observations": len(aggregate_all),
            "n_sites": aggregate_all["Site"].nunique(),
            "inferential_role": "release inventory and descriptive accounting",
        },
        {
            "cohort": "core_sites_1_60",
            "site_definition": "Sites in the intended repeated-campaign frame",
            "n_alpha_profiles": int(alpha["Site"].isin(CORE_SITES).sum()),
            "n_site_campaign_compartment_observations": len(aggregate),
            "n_sites": aggregate["Site"].nunique(),
            "inferential_role": "primary ecological inference",
        },
        {
            "cohort": "trip1_only_nonrevisited",
            "site_definition": "Sites 61–64; inaccessible after Trip 1",
            "n_alpha_profiles": int(alpha["Site"].isin(TRIP1_ONLY_SITES).sum()),
            "n_site_campaign_compartment_observations": int(
                aggregate_all["Site"].isin(TRIP1_ONLY_SITES).sum()
            ),
            "n_sites": int(
                aggregate_all.loc[
                    aggregate_all["Site"].isin(TRIP1_ONLY_SITES), "Site"
                ].nunique()
            ),
            "inferential_role": "excluded from repeated-campaign inference",
        },
    ]
    pd.DataFrame(cohort_rows).to_csv(
        output / "cohort_accounting.tsv", sep="\t", index=False
    )

    readme = [
        "# Ecology claim-rescue results",
        "",
        "## Supersession warning",
        "",
        "`rain_window_models.tsv` and `rain_leave_one_campaign.tsv` are "
        "retained only as historical diagnostics and every row is marked "
        f"`{LEGACY_RAIN_STATUS}`. They are not canonical evidence for a "
        "rainfall claim. The replacement analysis, decision, calibrated null "
        f"and checksums are under `{LEGACY_RAIN_REPLACEMENT}`.",
        "",
        f"- Input alpha profiles: {len(alpha)}",
        f"- All-site observations: {len(aggregate_all)} across "
        f"{aggregate_all['Site'].nunique()} sites",
        f"- Primary observations: {len(aggregate)} across "
        f"{aggregate['Site'].nunique()} core sites (1–60)",
        f"- Campaign-by-compartment Wald p: {interaction_p:.4g}",
        "",
        "Sites 61–64 are genuine Trip-1-only sampling sites. They are retained "
        "in the release inventory and descriptive observation table, but "
        "excluded from primary repeated-campaign inference because their "
        "regions were inaccessible for subsequent trips.",
        "",
        "The campaign model uses a Gaussian GEE with site clusters. The "
        "superseded rainfall diagnostics aggregate technical/field replicates "
        "to site × campaign, include campaign and quadratic geographic trends, "
        "use site-clustered standard errors, correct six windows by BH-FDR, "
        "test leave-one-campaign-out stability and report residual Moran's I. "
        "Those diagnostics are retained for provenance, not inference.",
        "",
        "The structural season/campaign alias remains unidentifiable regardless "
        "of p-values. Interpret the machine-readable claim ledger accordingly.",
        (
            "This core-stage ledger intentionally excludes advanced network, "
            "phylogenetic and encoded-function verdicts; those analyses have "
            "separate machine-readable verdicts in the advanced workflow."
            if args.skip_downstream
            else "Advanced verdicts were imported into this ledger from their "
            "machine-readable canonical outputs."
        ),
        "",
    ]
    (output / "README.md").write_text("\n".join(readme))

    supersession = (
        "# Superseded rainfall artifacts\n\n"
        "Status: **SUPERSEDED**\n\n"
        "The files `rain_window_models.tsv` and "
        "`rain_leave_one_campaign.tsv`, the rainfall panels formerly shown in "
        "`claim_rescue_summary.pdf`, and the two rainfall rows in "
        "`claim_ledger.tsv`/`.json` are historical diagnostics. They must not "
        "be used as manuscript evidence.\n\n"
        f"Replacement: `{LEGACY_RAIN_REPLACEMENT}`\n\n"
        f"Reason: {LEGACY_RAIN_REASON}\n"
    )
    (output / "SUPERSEDED_RAIN_ANALYSIS.md").write_text(supersession)

    excluded = {"run_manifest.json", "SHA256SUMS"}
    artifacts = sorted(
        path for path in output.iterdir()
        if path.is_file() and path.name not in excluded
    )
    manifest_rows = []
    checksum_rows = []
    for path in artifacts:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        manifest_rows.append(
            {"bytes": path.stat().st_size, "path": path.name, "sha256": digest}
        )
        checksum_rows.append(f"{digest}  {path.name}")
    manifest = {
        "artifact_root": "analysis/v3/results",
        "files": manifest_rows,
        "schema_version": "1.0",
    }
    (output / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n"
    )
    manifest_path = output / "run_manifest.json"
    checksum_rows.append(
        f"{hashlib.sha256(manifest_path.read_bytes()).hexdigest()}  "
        f"{manifest_path.name}"
    )
    checksum_rows.sort(key=lambda row: row.split("  ", 1)[1])
    (output / "SHA256SUMS").write_text("\n".join(checksum_rows) + "\n")


if __name__ == "__main__":
    main()
