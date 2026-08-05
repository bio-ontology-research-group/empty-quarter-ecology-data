#!/usr/bin/env python3
"""Estimate a short-term rise-and-decay association with antecedent rain.

This post-hoc analysis uses technical-replicate means for every available
site, campaign and soil position. Daily rain over the 60 complete days before
collection is convolved with a one-parameter pulse kernel. The kernel is zero
at the time of rain, rises to a candidate peak, and decays afterwards. Site by
soil-position baselines, campaigns, and campaign-specific route and
collection-day trends are held constant.

The complete search over peak times and three co-oriented alpha-diversity
endpoints is calibrated by rotating the lag axis of each campaign's observed
60-day rain histories.  This conditional null preserves the amount, rarity,
spatial field and clustering of rain in every campaign.  It tests temporal
alignment without requiring rain events to recur in every campaign.  A second
route-orbit null shifts and reflects the spatial rain field while preserving
calendar dates.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import patsy
import scipy
from scipy import stats
import statsmodels


SCHEMA_VERSION = "1.2"
ANALYSIS_DATE = "2026-08-05"
SEED = 20260804
BOOTSTRAP_SEED = 20260805
DEFAULT_PERMUTATIONS = 19_999
DEFAULT_BOOTSTRAPS = 9_999
HORIZON_DAYS = 60
PEAK_GRID_DAYS = np.arange(0.5, 30.0 + 0.5, 0.5)
LAG_BIN_SENSITIVITY = (
    (1, 1),
    (2, 2),
    (3, 4),
    (5, 7),
    (8, 14),
    (15, 30),
    (31, 60),
)
POSITIONS = ("Surface", "Deep")
ENDPOINTS = (
    "richness_hurlbert_25000",
    "shannon",
    "evenness_h_over_log_hurlbert",
)
ENDPOINT_LABELS = {
    "richness_hurlbert_25000": "Hurlbert expected richness at 25,000 reads",
    "shannon": "Shannon diversity",
    "evenness_h_over_log_hurlbert": "Normalized evenness",
}
TYPE_LABELS = {
    "Surface": "surface",
    "Deep": "shallow-subsurface",
    "Rhizosphere": "root-adjacent",
}
NUISANCE_FORMULA = (
    "0 + C(Site) + C(Trip) + C(Trip):longitude_z + "
    "C(Trip):sampling_day_z"
)
GROUPED_NUISANCE_FORMULA = (
    "0 + C(Site):C(Type) + C(Trip) + C(Trip):longitude_z + "
    "C(Trip):sampling_day_z"
)
NUISANCE_ADDITIONS = {
    "linear": "",
    "quadratic_longitude": " + C(Trip):I(longitude_z ** 2)",
    "quadratic_longitude_day": (
        " + C(Trip):I(longitude_z ** 2) + C(Trip):I(sampling_day_z ** 2)"
    ),
    "cubic_longitude": (
        " + C(Trip):I(longitude_z ** 2) + C(Trip):I(longitude_z ** 3)"
    ),
}


def load_base_module(root: Path):
    path = root / "analysis/v3/rain_response_window.py"
    specification = importlib.util.spec_from_file_location(
        "rain_response_window_for_pulse", path
    )
    if specification is None or specification.loader is None:
        raise RuntimeError(f"Cannot load shared rainfall utilities from {path}")
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stable_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def load_paired_means(path: Path, geodata: pd.DataFrame) -> pd.DataFrame:
    frame = pd.read_csv(path, sep="\t", dtype={"Site": "string"})
    required = {"Trip", "Site", "Type", "shannon", "richness_rare", "pielou"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"Alpha input is missing fields: {sorted(missing)}")
    frame["Trip"] = pd.to_numeric(frame["Trip"], errors="raise").astype(int)
    integer_site = frame["Site"].str.strip().str.fullmatch(r"[0-9]+", na=False)
    frame = frame.loc[integer_site].copy()
    frame["Site"] = pd.to_numeric(frame["Site"], errors="raise").astype(int)
    frame = frame[
        frame["Trip"].between(1, 5)
        & frame["Site"].isin(range(1, 61))
        & frame["Type"].isin(POSITIONS)
    ].copy()
    frame["richness_hurlbert_25000"] = pd.to_numeric(
        frame["richness_rare"], errors="raise"
    )
    frame["shannon"] = pd.to_numeric(frame["shannon"], errors="raise")
    frame["evenness_h_over_log_hurlbert"] = pd.to_numeric(
        frame["pielou"], errors="raise"
    )
    grouped = frame.groupby(["Trip", "Site", "Type"], as_index=False).agg(
        **{endpoint: (endpoint, "mean") for endpoint in ENDPOINTS},
        n_profiles=("shannon", "size"),
    )
    wide = grouped.pivot(index=["Trip", "Site"], columns="Type")
    result = pd.DataFrame(index=wide.index).reset_index()
    for endpoint in ENDPOINTS:
        result[endpoint] = (
            wide[(endpoint, "Surface")].to_numpy(dtype=float)
            + wide[(endpoint, "Deep")].to_numpy(dtype=float)
        ) / 2.0
    result["n_surface_profiles"] = wide[("n_profiles", "Surface")].to_numpy()
    result["n_deep_profiles"] = wide[("n_profiles", "Deep")].to_numpy()
    result = result.dropna(subset=list(ENDPOINTS)).merge(
        geodata,
        on=["Trip", "Site"],
        how="inner",
        validate="one_to_one",
    )
    if len(result) != 179:
        raise ValueError(f"Expected 179 paired observations, found {len(result)}")
    return result.sort_values(["Trip", "Site"]).reset_index(drop=True)


def load_group_means(path: Path, geodata: pd.DataFrame) -> pd.DataFrame:
    """Aggregate technical replicates while retaining every soil position."""
    frame = pd.read_csv(path, sep="\t", dtype={"Site": "string"})
    required = {"Trip", "Site", "Type", "shannon", "richness_rare", "pielou"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"Alpha input is missing fields: {sorted(missing)}")
    frame["Trip"] = pd.to_numeric(frame["Trip"], errors="raise").astype(int)
    integer_site = frame["Site"].str.strip().str.fullmatch(r"[0-9]+", na=False)
    frame = frame.loc[integer_site].copy()
    frame["Site"] = pd.to_numeric(frame["Site"], errors="raise").astype(int)
    frame = frame[
        frame["Trip"].between(1, 5)
        & frame["Site"].isin(range(1, 61))
        & frame["Type"].isin(("Surface", "Deep", "Rhizosphere"))
    ].copy()
    frame["richness_hurlbert_25000"] = pd.to_numeric(
        frame["richness_rare"], errors="raise"
    )
    frame["shannon"] = pd.to_numeric(frame["shannon"], errors="raise")
    frame["evenness_h_over_log_hurlbert"] = pd.to_numeric(
        frame["pielou"], errors="raise"
    )
    result = frame.groupby(["Trip", "Site", "Type"], as_index=False).agg(
        **{endpoint: (endpoint, "mean") for endpoint in ENDPOINTS},
        n_profiles=("shannon", "size"),
    )
    result = result.dropna(subset=list(ENDPOINTS)).merge(
        geodata,
        on=["Trip", "Site"],
        how="inner",
        validate="many_to_one",
    )
    if len(result) != 617:
        raise ValueError(f"Expected 617 soil-position observations, found {len(result)}")
    return result.sort_values(["Trip", "Site", "Type"]).reset_index(drop=True)


def pulse_kernel(lags: np.ndarray, peak_days: float) -> np.ndarray:
    """Unit-height gamma-shape pulse with its maximum at ``peak_days``."""
    lags = np.asarray(lags, dtype=float)
    if peak_days <= 0 or np.any(lags <= 0):
        raise ValueError("Pulse peak and lags must be positive")
    return (lags / peak_days) * np.exp(1.0 - lags / peak_days)


def kernel_matrix(
    lags: np.ndarray, peaks: Sequence[float] = PEAK_GRID_DAYS
) -> np.ndarray:
    return np.column_stack([pulse_kernel(lags, float(peak)) for peak in peaks])


def daily_lag_matrix(
    observations: pd.DataFrame,
    weather: Any,
    *,
    horizon: int = HORIZON_DAYS,
    future: bool = False,
    source_site_by_target: Sequence[int] | None = None,
) -> np.ndarray:
    values = weather.values
    site_to_column = {int(site): index for index, site in enumerate(values.columns)}
    mapping = (
        np.asarray(source_site_by_target, dtype=int)
        if source_site_by_target is not None
        else np.arange(1, 61, dtype=int)
    )
    if mapping.shape != (60,) or set(mapping) != set(range(1, 61)):
        raise ValueError("The route mapping must be a permutation of sites 1--60")
    lags = np.arange(1, horizon + 1, dtype=int)
    result = np.empty((len(observations), horizon), dtype=float)
    for index, row in enumerate(observations.itertuples(index=False)):
        date_position = int(values.index.searchsorted(pd.Timestamp(row.Date)))
        if date_position >= len(values.index) or values.index[date_position] != row.Date:
            raise ValueError(f"Weather date unavailable: {row.Date}")
        source_site = int(mapping[int(row.Site) - 1])
        column = site_to_column[source_site]
        positions = date_position + lags if future else date_position - lags
        if positions.min() < 0 or positions.max() >= len(values.index):
            raise ValueError(f"Weather horizon leaves source range for {row.Date}")
        result[index, :] = values.iloc[positions, column].to_numpy(dtype=float)
    return result


def nuisance_basis(
    observations: pd.DataFrame,
    formula: str = NUISANCE_FORMULA,
    extra_columns: np.ndarray | None = None,
) -> tuple[np.ndarray, int, list[str]]:
    design = patsy.dmatrix(formula, observations, return_type="dataframe")
    names = list(design.columns)
    matrix = design.to_numpy(dtype=float)
    if extra_columns is not None:
        extra = np.asarray(extra_columns, dtype=float)
        if extra.ndim == 1:
            extra = extra[:, None]
        matrix = np.column_stack([matrix, extra])
        names.extend(f"extra_{index + 1}" for index in range(extra.shape[1]))
    basis, rank = load_linear_algebra_basis(matrix)
    return basis, rank, names


def load_linear_algebra_basis(matrix: np.ndarray) -> tuple[np.ndarray, int]:
    u, singular_values, _ = np.linalg.svd(np.asarray(matrix, dtype=float), full_matrices=False)
    tolerance = (
        np.finfo(float).eps * max(matrix.shape) * singular_values[0]
        if singular_values.size
        else 0.0
    )
    rank = int(np.sum(singular_values > tolerance))
    return u[:, :rank], rank


def residualize(matrix: np.ndarray, basis: np.ndarray) -> np.ndarray:
    values = np.asarray(matrix, dtype=float)
    one_dimensional = values.ndim == 1
    if one_dimensional:
        values = values[:, None]
    residual = values - basis @ (basis.T @ values)
    return residual[:, 0] if one_dimensional else residual


def scan_statistics(
    outcomes: Mapping[str, np.ndarray],
    exposure_by_peak: np.ndarray,
    basis: np.ndarray,
    nuisance_rank: int,
) -> dict[str, dict[str, np.ndarray]]:
    residual_exposure = residualize(exposure_by_peak, basis)
    denominator = np.sum(residual_exposure**2, axis=0)
    degrees_freedom = len(exposure_by_peak) - nuisance_rank - 1
    results: dict[str, dict[str, np.ndarray]] = {}
    for endpoint, outcome in outcomes.items():
        residual_outcome = residualize(outcome, basis)
        numerator = residual_exposure.T @ residual_outcome
        beta = np.divide(
            numerator,
            denominator,
            out=np.full_like(numerator, np.nan),
            where=denominator > 1e-12,
        )
        residual_ss = float(residual_outcome @ residual_outcome) - np.divide(
            numerator**2,
            denominator,
            out=np.zeros_like(numerator),
            where=denominator > 1e-12,
        )
        variance = residual_ss / degrees_freedom
        standard_error = np.sqrt(
            np.divide(
                variance,
                denominator,
                out=np.full_like(variance, np.nan),
                where=denominator > 1e-12,
            )
        )
        t_value = beta / standard_error
        results[endpoint] = {
            "beta": beta,
            "standard_error_classical": standard_error,
            "t_classical": t_value,
            "partial_r2": np.divide(
                numerator**2 / np.maximum(denominator, 1e-300),
                float(residual_outcome @ residual_outcome),
            ),
        }
    return results


def maximum_statistics(
    scans: Mapping[str, Mapping[str, np.ndarray]]
) -> tuple[float, float, dict[str, float]]:
    endpoint_maxima = {
        endpoint: float(np.nanmax(result["t_classical"]))
        for endpoint, result in scans.items()
    }
    positive = max(endpoint_maxima.values())
    absolute = max(
        float(np.nanmax(np.abs(result["t_classical"]))) for result in scans.values()
    )
    return positive, absolute, endpoint_maxima


def percentile_interval(values: np.ndarray) -> tuple[float, float]:
    finite = np.asarray(values, dtype=float)
    finite = finite[np.isfinite(finite)]
    if not len(finite):
        return math.nan, math.nan
    lower, upper = np.quantile(finite, (0.025, 0.975))
    return float(lower), float(upper)


def site_block_bootstrap_uncertainty(
    observations: pd.DataFrame,
    exposure_by_peak: np.ndarray,
    outcomes: Mapping[str, np.ndarray],
    basis: np.ndarray,
    nuisance_rank: int,
    selected_endpoint: str,
    selected_peak: float,
    bootstraps: int,
    seed: int,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Quantify sampling uncertainty while preserving complete site histories.

    The nuisance-adjusted outcome and exposure curves are resampled in whole
    site blocks. A multinomial representation avoids materializing repeated
    observations. The fixed-curve interval conditions on the selected endpoint
    and peak. A second summary repeats the peak search within the selected
    endpoint, while the endpoint frequencies repeat the complete search.
    """
    residual_exposure = residualize(exposure_by_peak, basis)
    residual_outcomes = {
        endpoint: residualize(values, basis)
        for endpoint, values in outcomes.items()
    }
    site_values = observations["Site"].to_numpy(dtype=int)
    sites = np.asarray(sorted(np.unique(site_values)), dtype=int)
    groups = [np.flatnonzero(site_values == site) for site in sites]
    cluster_counts = np.asarray([len(indices) for indices in groups], dtype=int)
    cluster_exposure_ss = np.asarray(
        [np.square(residual_exposure[indices]).sum(axis=0) for indices in groups]
    )
    cluster_cross = {
        endpoint: np.asarray(
            [
                (
                    residual_exposure[indices]
                    * values[indices, None]
                ).sum(axis=0)
                for indices in groups
            ]
        )
        for endpoint, values in residual_outcomes.items()
    }
    cluster_outcome_ss = {
        endpoint: np.asarray(
            [np.square(values[indices]).sum() for indices in groups]
        )
        for endpoint, values in residual_outcomes.items()
    }

    rng = np.random.default_rng(seed)
    weights = rng.multinomial(
        len(sites), np.full(len(sites), 1.0 / len(sites)), size=bootstraps
    )
    denominator = weights @ cluster_exposure_ss
    weighted_n = weights @ cluster_counts
    degrees_freedom = weighted_n - nuisance_rank - 1
    if np.any(degrees_freedom <= 0):
        raise ValueError("A site bootstrap draw has no residual degrees of freedom")

    bootstrap_scans: dict[str, dict[str, np.ndarray]] = {}
    for endpoint in ENDPOINTS:
        numerator = weights @ cluster_cross[endpoint]
        outcome_ss = weights @ cluster_outcome_ss[endpoint]
        beta = np.divide(
            numerator,
            denominator,
            out=np.full_like(numerator, np.nan),
            where=denominator > 1e-12,
        )
        residual_ss = outcome_ss[:, None] - np.divide(
            numerator**2,
            denominator,
            out=np.zeros_like(numerator),
            where=denominator > 1e-12,
        )
        standard_error = np.sqrt(
            np.divide(
                residual_ss / degrees_freedom[:, None],
                denominator,
                out=np.full_like(residual_ss, np.nan),
                where=denominator > 1e-12,
            )
        )
        bootstrap_scans[endpoint] = {
            "beta": beta,
            "t": beta / standard_error,
            "partial_r2": np.divide(
                numerator**2 / np.maximum(denominator, 1e-300),
                outcome_ss[:, None],
            ),
        }

    fixed_peak_index = int(np.flatnonzero(PEAK_GRID_DAYS == selected_peak)[0])
    selected_scan = bootstrap_scans[selected_endpoint]
    endpoint_peak_indices = np.nanargmax(selected_scan["t"], axis=1)
    draw_indices = np.arange(bootstraps)
    endpoint_peaks = PEAK_GRID_DAYS[endpoint_peak_indices]

    stacked_t = np.stack(
        [bootstrap_scans[endpoint]["t"] for endpoint in ENDPOINTS], axis=1
    )
    full_indices = np.nanargmax(stacked_t.reshape(bootstraps, -1), axis=1)
    full_endpoint_indices = full_indices // len(PEAK_GRID_DAYS)
    full_peak_indices = full_indices % len(PEAK_GRID_DAYS)
    endpoint_array = np.asarray(ENDPOINTS, dtype=object)
    full_endpoints = endpoint_array[full_endpoint_indices]
    full_peaks = PEAK_GRID_DAYS[full_peak_indices]
    full_effects = np.asarray(
        [
            bootstrap_scans[str(endpoint)]["beta"][draw, peak]
            for draw, endpoint, peak in zip(
                draw_indices, full_endpoints, full_peak_indices
            )
        ]
    )
    full_partial_r2 = np.asarray(
        [
            bootstrap_scans[str(endpoint)]["partial_r2"][draw, peak]
            for draw, endpoint, peak in zip(
                draw_indices, full_endpoints, full_peak_indices
            )
        ]
    )

    draws = pd.DataFrame(
        {
            "draw": draw_indices + 1,
            "weighted_analysis_units": weighted_n,
            "fixed_endpoint": selected_endpoint,
            "fixed_peak_complete_days": selected_peak,
            "fixed_effect_per_mm_at_peak": selected_scan["beta"][:, fixed_peak_index],
            "fixed_partial_r2": selected_scan["partial_r2"][:, fixed_peak_index],
            "endpoint_reselected_peak_complete_days": endpoint_peaks,
            "endpoint_reselected_effect_per_mm_at_peak": selected_scan["beta"][
                draw_indices, endpoint_peak_indices
            ],
            "endpoint_reselected_partial_r2": selected_scan["partial_r2"][
                draw_indices, endpoint_peak_indices
            ],
            "full_search_selected_endpoint": full_endpoints,
            "full_search_selected_peak_complete_days": full_peaks,
            "full_search_selected_effect_per_mm_at_peak": full_effects,
            "full_search_selected_partial_r2": full_partial_r2,
        }
    )

    fixed_effect_ci = percentile_interval(
        draws["fixed_effect_per_mm_at_peak"].to_numpy()
    )
    fixed_r2_ci = percentile_interval(draws["fixed_partial_r2"].to_numpy())
    peak_ci = percentile_interval(endpoint_peaks)
    reselected_effect_ci = percentile_interval(
        draws["endpoint_reselected_effect_per_mm_at_peak"].to_numpy()
    )
    half_multiplier = effect_decay_times(1.0)["half_maximum_day"]
    ten_percent_multiplier = effect_decay_times(1.0)["ten_percent_day"]
    half_ci = percentile_interval(endpoint_peaks * half_multiplier)
    ten_percent_ci = percentile_interval(endpoint_peaks * ten_percent_multiplier)
    summary_rows = [
        {
            "quantity": "effect_per_mm_at_fixed_selected_peak",
            "estimate": math.nan,
            "ci_low": fixed_effect_ci[0],
            "ci_high": fixed_effect_ci[1],
            "uncertainty_type": "95% site-block percentile bootstrap interval",
        },
        {
            "quantity": "partial_r2_at_fixed_selected_peak",
            "estimate": math.nan,
            "ci_low": fixed_r2_ci[0],
            "ci_high": fixed_r2_ci[1],
            "uncertainty_type": "95% site-block percentile bootstrap interval",
        },
        {
            "quantity": "selected_endpoint_peak_complete_days",
            "estimate": selected_peak,
            "ci_low": peak_ci[0],
            "ci_high": peak_ci[1],
            "uncertainty_type": "95% site-block peak-selection interval",
        },
        {
            "quantity": "effect_at_reselected_endpoint_peak",
            "estimate": math.nan,
            "ci_low": reselected_effect_ci[0],
            "ci_high": reselected_effect_ci[1],
            "uncertainty_type": "95% site-block peak-selection interval",
        },
        {
            "quantity": "half_maximum_complete_day",
            "estimate": math.nan,
            "ci_low": half_ci[0],
            "ci_high": half_ci[1],
            "uncertainty_type": "95% site-block peak-selection interval",
        },
        {
            "quantity": "ten_percent_complete_day",
            "estimate": math.nan,
            "ci_low": ten_percent_ci[0],
            "ci_high": ten_percent_ci[1],
            "uncertainty_type": "95% site-block peak-selection interval",
        },
    ]
    summary = pd.DataFrame(summary_rows)
    summary["bootstrap_replicates"] = bootstraps
    summary["seed"] = seed
    summary["analysis_unit"] = "site with all repeated observations"

    metadata = {
        "method": (
            "multinomial site-block percentile bootstrap of nuisance-adjusted "
            "outcomes and all candidate rain-exposure curves"
        ),
        "replicates": bootstraps,
        "seed": seed,
        "fixed_effect_95_ci": list(fixed_effect_ci),
        "fixed_partial_r2_95_ci": list(fixed_r2_ci),
        "selected_endpoint_peak_95_interval_complete_days": list(peak_ci),
        "half_maximum_95_interval_complete_days": list(half_ci),
        "ten_percent_95_interval_complete_days": list(ten_percent_ci),
        "full_search_endpoint_selection_frequency": {
            endpoint: float(np.mean(full_endpoints == endpoint))
            for endpoint in ENDPOINTS
        },
        "boundary": (
            "The bootstrap quantifies sampling variation among sites conditional "
            "on the fitted nuisance adjustment and rainfall product. Product and "
            "route-model uncertainty are reported separately."
        ),
    }
    return draws, summary, metadata


def plus_one_p(null: Sequence[float], observed: float) -> float:
    values = np.asarray(null, dtype=float)
    values = values[np.isfinite(values)]
    return float((1 + np.sum(values >= observed)) / (len(values) + 1))


def conditional_lag_rotation_null(
    rain_lags: np.ndarray,
    observations: pd.DataFrame,
    kernels: np.ndarray,
    outcomes: Mapping[str, np.ndarray],
    basis: np.ndarray,
    nuisance_rank: int,
    permutations: int,
    seed: int,
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    trip_indices = {
        int(trip): np.asarray(list(indices), dtype=int)
        for trip, indices in observations.groupby("Trip").groups.items()
    }
    rows: list[dict[str, Any]] = []
    for draw in range(1, permutations + 1):
        permuted = np.empty_like(rain_lags)
        shifts: dict[int, int] = {}
        for trip, indices in trip_indices.items():
            shift = int(rng.integers(0, HORIZON_DAYS))
            shifts[trip] = shift
            permuted[indices, :] = np.roll(rain_lags[indices, :], shift, axis=1)
        scans = scan_statistics(
            outcomes, permuted @ kernels, basis, nuisance_rank
        )
        maximum_positive, maximum_absolute, endpoint_maxima = maximum_statistics(scans)
        row: dict[str, Any] = {
            "draw": draw,
            "max_positive_t_all_endpoints": maximum_positive,
            "max_absolute_t_all_endpoints": maximum_absolute,
        }
        row.update({f"trip_{trip}_lag_shift": shift for trip, shift in shifts.items()})
        row.update(
            {f"max_positive_t_{endpoint}": value for endpoint, value in endpoint_maxima.items()}
        )
        rows.append(row)
    return pd.DataFrame(rows)


def spatial_route_orbit_null(
    observations: pd.DataFrame,
    weather: Any,
    kernels: np.ndarray,
    outcomes: Mapping[str, np.ndarray],
    basis: np.ndarray,
    nuisance_rank: int,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for reflected in (False, True):
        route = np.arange(1, 61, dtype=int)
        if reflected:
            route = route[::-1]
        for shift in range(60):
            mapping = np.roll(route, shift)
            rain = daily_lag_matrix(
                observations, weather, source_site_by_target=mapping
            )
            scans = scan_statistics(outcomes, rain @ kernels, basis, nuisance_rank)
            maximum_positive, maximum_absolute, endpoint_maxima = maximum_statistics(scans)
            row: dict[str, Any] = {
                "reflected": reflected,
                "route_shift": shift,
                "max_positive_t_all_endpoints": maximum_positive,
                "max_absolute_t_all_endpoints": maximum_absolute,
            }
            row.update(
                {
                    f"max_positive_t_{endpoint}": value
                    for endpoint, value in endpoint_maxima.items()
                }
            )
            rows.append(row)
    return pd.DataFrame(rows)


def selected_cluster_fits(
    observations: pd.DataFrame,
    exposure: np.ndarray,
    basis: np.ndarray,
    weather: Any,
) -> pd.DataFrame:
    import statsmodels.api as sm

    design = np.column_stack([basis, exposure])
    cluster_sets = {
        "site": observations["Site"].astype(str).to_numpy(),
        "campaign_rain_grid": np.asarray(
            [
                f"T{trip}_{weather.grid_ids[int(site)]}"
                for trip, site in observations[["Trip", "Site"]].itertuples(index=False)
            ]
        ),
    }
    rows: list[dict[str, Any]] = []
    for endpoint in ENDPOINTS:
        for cluster_name, clusters in cluster_sets.items():
            fit = sm.OLS(observations[endpoint].to_numpy(dtype=float), design).fit(
                cov_type="cluster",
                cov_kwds={"groups": clusters, "use_correction": True},
            )
            estimate = float(fit.params[-1])
            standard_error = float(fit.bse[-1])
            rows.append(
                {
                    "endpoint": endpoint,
                    "cluster_definition": cluster_name,
                    "n_clusters": int(pd.Series(clusters).nunique()),
                    "estimate_per_mm_at_kernel_peak": estimate,
                    "standard_error": standard_error,
                    "t": estimate / standard_error,
                    "p_two_sided": float(fit.pvalues[-1]),
                    "ci_low": estimate - stats.norm.ppf(0.975) * standard_error,
                    "ci_high": estimate + stats.norm.ppf(0.975) * standard_error,
                }
            )
    return pd.DataFrame(rows)


def scan_table(
    scans: Mapping[str, Mapping[str, np.ndarray]],
    peaks: Sequence[float],
    n_observations: int,
    n_sites: int,
    nuisance_rank: int,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for endpoint, result in scans.items():
        for index, peak in enumerate(peaks):
            rows.append(
                {
                    "endpoint": endpoint,
                    "endpoint_label": ENDPOINT_LABELS[endpoint],
                    "candidate_peak_days": peak,
                    "estimate_per_mm_at_kernel_peak": result["beta"][index],
                    "classical_standard_error": result["standard_error_classical"][index],
                    "classical_t": result["t_classical"][index],
                    "partial_r2": result["partial_r2"][index],
                    "n_analysis_units": n_observations,
                    "n_sites": n_sites,
                    "nuisance_rank": nuisance_rank,
                }
            )
    return pd.DataFrame(rows)


def position_effect_sensitivity(
    observations: pd.DataFrame,
    weather: Any,
    selected_kernel: np.ndarray,
    nuisance_model: str,
    *,
    adjust_ph: bool,
) -> pd.DataFrame:
    """Estimate the selected common pulse separately in each soil position."""
    if "Type" not in observations.columns:
        return pd.DataFrame()
    rows: list[pd.DataFrame] = []
    for position in ("Surface", "Deep", "Rhizosphere"):
        subset = observations[observations["Type"] == position].copy()
        if subset.empty:
            continue
        extra = subset["ph"].to_numpy(dtype=float) if adjust_ph else None
        formula = NUISANCE_FORMULA + NUISANCE_ADDITIONS[nuisance_model]
        basis, nuisance_rank, _ = nuisance_basis(subset, formula, extra)
        exposure = daily_lag_matrix(subset, weather) @ selected_kernel
        fits = selected_cluster_fits(subset, exposure, basis, weather)
        fits.insert(0, "soil_position", position)
        fits.insert(1, "soil_position_label", TYPE_LABELS[position])
        fits.insert(2, "n_analysis_units", len(subset))
        fits.insert(3, "nuisance_rank", nuisance_rank)
        rows.append(fits)
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def lag_bin_sensitivity(
    observations: pd.DataFrame,
    rain_lags: np.ndarray,
    basis: np.ndarray,
    endpoint: str,
) -> pd.DataFrame:
    """Fit disjoint lag bins together as a shape sensitivity.

    These nominal estimates show whether a flexible lag representation places
    the positive association in the same early period. They are not used to
    select the primary model or to declare statistical support.
    """
    import statsmodels.api as sm

    exposures = np.column_stack(
        [rain_lags[:, start - 1 : end].sum(axis=1) for start, end in LAG_BIN_SENSITIVITY]
    )
    design = np.column_stack([basis, exposures])
    fit = sm.OLS(observations[endpoint].to_numpy(dtype=float), design).fit(
        cov_type="cluster",
        cov_kwds={
            "groups": observations["Site"].astype(str).to_numpy(),
            "use_correction": True,
        },
    )
    rows: list[dict[str, Any]] = []
    offset = len(fit.params) - len(LAG_BIN_SENSITIVITY)
    for index, (start, end) in enumerate(LAG_BIN_SENSITIVITY):
        coefficient_index = offset + index
        estimate = float(fit.params[coefficient_index])
        standard_error = float(fit.bse[coefficient_index])
        rows.append(
            {
                "endpoint": endpoint,
                "lag_start_complete_days": start,
                "lag_end_complete_days": end,
                "estimate_per_mm": estimate,
                "site_clustered_standard_error": standard_error,
                "site_clustered_t": estimate / standard_error,
                "nominal_two_sided_p": float(fit.pvalues[coefficient_index]),
                "interpretation": "descriptive shape sensitivity",
            }
        )
    return pd.DataFrame(rows)


def campaign_exposure_summary(
    observations: pd.DataFrame,
    rain_lags: np.ndarray,
    selected_exposure: np.ndarray,
) -> pd.DataFrame:
    """Describe exposure support without treating campaigns as replications."""
    values = observations[["Trip", "Site"]].copy()
    values["kernel_weighted_rain_mm"] = selected_exposure
    values["rain_1_to_4_complete_days_mm"] = rain_lags[:, :4].sum(axis=1)
    values["rain_1_to_60_complete_days_mm"] = rain_lags.sum(axis=1)
    values = values.drop_duplicates(
        ["Trip", "Site", "kernel_weighted_rain_mm"], keep="first"
    )
    rows: list[dict[str, Any]] = []
    for trip, subset in values.groupby("Trip", sort=True):
        exposure = subset["kernel_weighted_rain_mm"]
        exposure_threshold = 0.01
        rows.append(
            {
                "trip": int(trip),
                "n_sampled_sites": int(subset["Site"].nunique()),
                "n_sites_with_kernel_exposure_at_least_0_01_mm": int(
                    (exposure >= exposure_threshold).sum()
                ),
                "kernel_weighted_rain_mm_minimum": float(exposure.min()),
                "kernel_weighted_rain_mm_median": float(exposure.median()),
                "kernel_weighted_rain_mm_maximum": float(exposure.max()),
                "rain_1_to_4_complete_days_mm_maximum": float(
                    subset["rain_1_to_4_complete_days_mm"].max()
                ),
                "rain_1_to_60_complete_days_mm_maximum": float(
                    subset["rain_1_to_60_complete_days_mm"].max()
                ),
            }
        )
    return pd.DataFrame(rows)


def evidence_status(one_sided_p: float) -> str:
    if one_sided_p < 0.05:
        return "temporally_localized_association_supported"
    if one_sided_p < 0.10:
        return "temporally_localized_association_borderline"
    return "temporally_localized_association_not_supported"


def effect_decay_times(peak_days: float) -> dict[str, float]:
    grid = np.linspace(peak_days, 20 * peak_days, 200_000)
    weights = pulse_kernel(grid, peak_days)
    result: dict[str, float] = {}
    for label, threshold in (("half_maximum_day", 0.5), ("ten_percent_day", 0.1)):
        candidates = grid[weights <= threshold]
        result[label] = float(candidates[0]) if len(candidates) else math.nan
    return result


def plot_diagnostics(
    output: Path,
    selected_endpoint: str,
    selected_peak: float,
    selected_beta: float,
    scan: pd.DataFrame,
    lag_null: pd.DataFrame,
    observed_maximum: float,
    bootstrap_draws: pd.DataFrame,
    bootstrap_metadata: Mapping[str, Any],
) -> None:
    figure, axes = plt.subplots(1, 3, figsize=(11.2, 3.3))
    timing_upper = float(
        bootstrap_metadata["ten_percent_95_interval_complete_days"][1]
    )
    display_horizon = min(HORIZON_DAYS, max(15.0, timing_upper))
    days = np.linspace(0.001, display_horizon, 600)
    bootstrap_peaks = bootstrap_draws[
        "endpoint_reselected_peak_complete_days"
    ].to_numpy(dtype=float)
    bootstrap_effects = bootstrap_draws[
        "endpoint_reselected_effect_per_mm_at_peak"
    ].to_numpy(dtype=float)
    bootstrap_curves = bootstrap_effects[:, None] * (
        (days[None, :] / bootstrap_peaks[:, None])
        * np.exp(1.0 - days[None, :] / bootstrap_peaks[:, None])
    )
    curve_low, curve_high = np.quantile(bootstrap_curves, (0.025, 0.975), axis=0)
    axes[0].fill_between(
        days,
        curve_low,
        curve_high,
        color="#56B4E9",
        alpha=0.24,
        linewidth=0,
        label="95% site-bootstrap envelope",
    )
    axes[0].plot(
        days,
        selected_beta * pulse_kernel(days, selected_peak),
        color="#0072B2",
        linewidth=2,
    )
    axes[0].axhline(0, color="black", linewidth=0.7)
    peak_interval = bootstrap_metadata[
        "selected_endpoint_peak_95_interval_complete_days"
    ]
    axes[0].axvspan(
        float(peak_interval[0]),
        float(peak_interval[1]),
        color="#E69F00",
        alpha=0.10,
        linewidth=0,
        label="95% peak-selection interval",
    )
    axes[0].axvline(selected_peak, color="#D55E00", linestyle="--", linewidth=1)
    axes[0].set(
        xlabel="Complete days since rain",
        ylabel="Estimated change per mm",
        title="(a) Fitted pulse response",
    )
    axes[0].legend(frameon=False, fontsize=7, loc="upper right")

    colors = {
        "richness_hurlbert_25000": "#0072B2",
        "shannon": "#009E73",
        "evenness_h_over_log_hurlbert": "#CC79A7",
    }
    for endpoint in ENDPOINTS:
        subset = scan[scan["endpoint"] == endpoint]
        axes[1].plot(
            subset["candidate_peak_days"],
            subset["classical_t"],
            label=ENDPOINT_LABELS[endpoint],
            color=colors[endpoint],
        )
    threshold = float(lag_null["max_positive_t_all_endpoints"].quantile(0.95))
    axes[1].axhline(threshold, color="black", linestyle=":", linewidth=1)
    axes[1].set(
        xlabel="Candidate peak time (days)",
        ylabel="Positive association statistic",
        title="(b) Complete peak-time scan",
    )
    axes[1].legend(frameon=False, fontsize=7)

    axes[2].hist(
        lag_null["max_positive_t_all_endpoints"],
        bins=35,
        color="#BBBBBB",
        edgecolor="white",
    )
    axes[2].axvline(observed_maximum, color="#D55E00", linewidth=1.5)
    axes[2].set(
        xlabel="Maximum statistic after lag rotation",
        ylabel="Null rotations",
        title="(c) Conditional timing null",
    )
    figure.tight_layout()
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(
        output,
        bbox_inches="tight",
        metadata={
            "Title": "Empty Quarter fitted rainfall pulse response",
            "Creator": "analysis/v3/rain_pulse_response.py",
            "CreationDate": None,
            "ModDate": None,
        },
    )
    plt.close(figure)


def git_head(root: Path) -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def write_checksums(output: Path) -> None:
    files = sorted(
        path for path in output.iterdir() if path.is_file() and path.name != "SHA256SUMS"
    )
    (output / "SHA256SUMS").write_text(
        "".join(f"{sha256_file(path)}  {path.name}\n" for path in files),
        encoding="utf-8",
    )


def run(args: argparse.Namespace) -> None:
    root = args.root.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    legacy_paired_cohort = output / "paired_bulk_cohort.tsv"
    if legacy_paired_cohort.exists():
        legacy_paired_cohort.unlink()
    base = load_base_module(root)
    geodata = base.load_geodata(root)
    if args.cohort == "grouped":
        observations = load_group_means(args.alpha, geodata)
        nuisance_formula = GROUPED_NUISANCE_FORMULA
        cohort_description = (
            "technical replicates averaged within 617 site-campaign-position groups"
        )
    else:
        observations = load_paired_means(args.alpha, geodata)
        nuisance_formula = NUISANCE_FORMULA
        cohort_description = (
            "surface and shallow-subsurface values averaged within 179 complete pairs"
        )
    nuisance_formula += NUISANCE_ADDITIONS[args.nuisance_model]
    extra_nuisance = None
    if args.adjust_ph:
        if args.cohort != "grouped":
            raise ValueError("pH adjustment currently requires the grouped cohort")
        ph = pd.read_csv(args.ph_group_table, sep="\t").rename(
            columns={"trip": "Trip", "site": "Site", "compartment": "Type"}
        )
        observations = observations.merge(
            ph[["Trip", "Site", "Type", "ph"]],
            on=["Trip", "Site", "Type"],
            how="inner",
            validate="one_to_one",
        )
        observations = observations.sort_values(
            ["Trip", "Site", "Type"]
        ).reset_index(drop=True)
        extra_nuisance = observations["ph"].to_numpy(dtype=float)
        cohort_description += "; restricted to groups with measured pH"
    weather = (
        base.load_open_meteo(args.nasa_weather)
        if args.weather_product == "open_meteo"
        else base.load_nasa(args.nasa_weather)
    )
    rain_lags = daily_lag_matrix(observations, weather)
    lags = np.arange(1, HORIZON_DAYS + 1, dtype=float)
    kernels = kernel_matrix(lags)
    basis, nuisance_rank, nuisance_columns = nuisance_basis(
        observations, nuisance_formula, extra_nuisance
    )
    outcomes = {
        endpoint: observations[endpoint].to_numpy(dtype=float)
        for endpoint in ENDPOINTS
    }
    scans = scan_statistics(outcomes, rain_lags @ kernels, basis, nuisance_rank)
    observed_positive, observed_absolute, endpoint_maxima = maximum_statistics(scans)
    observed_scan = scan_table(
        scans,
        PEAK_GRID_DAYS,
        len(observations),
        observations["Site"].nunique(),
        nuisance_rank,
    )
    lag_null = conditional_lag_rotation_null(
        rain_lags,
        observations,
        kernels,
        outcomes,
        basis,
        nuisance_rank,
        args.permutations,
        args.seed,
    )
    spatial_null = spatial_route_orbit_null(
        observations, weather, kernels, outcomes, basis, nuisance_rank
    )

    selected_row = observed_scan.loc[observed_scan["classical_t"].idxmax()]
    selected_endpoint = str(selected_row["endpoint"])
    selected_peak = float(selected_row["candidate_peak_days"])
    selected_beta = float(selected_row["estimate_per_mm_at_kernel_peak"])
    selected_kernel = pulse_kernel(lags, selected_peak)
    selected_exposure = rain_lags @ selected_kernel
    cluster_fits = selected_cluster_fits(
        observations, selected_exposure, basis, weather
    )
    bootstrap_draws, bootstrap_summary, bootstrap_metadata = (
        site_block_bootstrap_uncertainty(
            observations,
            rain_lags @ kernels,
            outcomes,
            basis,
            nuisance_rank,
            selected_endpoint,
            selected_peak,
            args.bootstraps,
            args.bootstrap_seed,
        )
    )
    position_effects = position_effect_sensitivity(
        observations,
        weather,
        selected_kernel,
        args.nuisance_model,
        adjust_ph=args.adjust_ph,
    )
    lag_bins = lag_bin_sensitivity(
        observations, rain_lags, basis, selected_endpoint
    )
    campaign_exposures = campaign_exposure_summary(
        observations, rain_lags, selected_exposure
    )
    future_rain_lags = daily_lag_matrix(observations, weather, future=True)
    future_scans = scan_statistics(
        outcomes, future_rain_lags @ kernels, basis, nuisance_rank
    )
    future_scan = scan_table(
        future_scans,
        PEAK_GRID_DAYS,
        len(observations),
        observations["Site"].nunique(),
        nuisance_rank,
    )
    future_row = future_scan.loc[future_scan["classical_t"].idxmax()]
    future_richness_maximum = float(
        future_scan.loc[
            future_scan["endpoint"] == "richness_hurlbert_25000", "classical_t"
        ].max()
    )
    decay = effect_decay_times(selected_peak)
    bootstrap_estimates = {
        "effect_per_mm_at_fixed_selected_peak": selected_beta,
        "partial_r2_at_fixed_selected_peak": float(selected_row["partial_r2"]),
        "selected_endpoint_peak_complete_days": selected_peak,
        "effect_at_reselected_endpoint_peak": selected_beta,
        "half_maximum_complete_day": decay["half_maximum_day"],
        "ten_percent_complete_day": decay["ten_percent_day"],
    }
    bootstrap_summary["estimate"] = bootstrap_summary["quantity"].map(
        bootstrap_estimates
    )
    lag_one_sided = plus_one_p(
        lag_null["max_positive_t_all_endpoints"], observed_positive
    )
    lag_two_sided = plus_one_p(
        lag_null["max_absolute_t_all_endpoints"], observed_absolute
    )
    spatial_one_sided = float(
        np.mean(spatial_null["max_positive_t_all_endpoints"] >= observed_positive)
    )
    spatial_two_sided = float(
        np.mean(spatial_null["max_absolute_t_all_endpoints"] >= observed_absolute)
    )

    status = evidence_status(lag_one_sided)
    if status == "temporally_localized_association_supported":
        permitted_wording = (
            "Bacterial richness was positively associated with a fitted short-lived "
            "antecedent-rain pulse."
        )
    elif status == "temporally_localized_association_borderline":
        permitted_wording = (
            "Bacterial richness showed a short-lived positive association with "
            "antecedent rain, with borderline familywise evidence in this rainfall "
            "product."
        )
    else:
        permitted_wording = (
            "The fitted rise-and-decay model did not identify a calibrated short-term "
            "rainfall association."
        )
    decision = {
        "schema_version": SCHEMA_VERSION,
        "analysis_date": ANALYSIS_DATE,
        "analysis_status": status,
        "post_hoc": True,
        "cohort": args.cohort,
        "cohort_description": cohort_description,
        "community_table_role": args.community_table_role,
        "weather_product": args.weather_product,
        "nuisance_model": args.nuisance_model,
        "ph_adjusted": args.adjust_ph,
        "positive_pulse_hypothesis": True,
        "selected_endpoint": selected_endpoint,
        "selected_endpoint_label": ENDPOINT_LABELS[selected_endpoint],
        "selected_peak_complete_days": selected_peak,
        "selected_estimate_per_mm_at_peak": selected_beta,
        "selected_classical_t": float(selected_row["classical_t"]),
        "selected_partial_r2": float(selected_row["partial_r2"]),
        "kernel": "(lag / peak) * exp(1 - lag / peak)",
        "kernel_horizon_complete_days": HORIZON_DAYS,
        **decay,
        "sampling_uncertainty": bootstrap_metadata,
        "familywise_inference": {
            "conditional_lag_rotation_one_sided_p": lag_one_sided,
            "conditional_lag_rotation_two_sided_p": lag_two_sided,
            "spatial_route_orbit_one_sided_p": spatial_one_sided,
            "spatial_route_orbit_two_sided_p": spatial_two_sided,
            "n_lag_rotation_draws": len(lag_null),
            "n_spatial_route_orbit_members": len(spatial_null),
            "correction_scope": "all candidate peaks and three alpha-diversity endpoints",
        },
        "campaign_interpretation": (
            "Rainfall is rare and uneven among campaigns. Campaign omission is not a "
            "replication or stability requirement; the conditional timing null retains "
            "each campaign's observed rain amount and spatial field."
        ),
        "future_rain_placebo": {
            "maximum_endpoint": str(future_row["endpoint"]),
            "maximum_peak_days": float(future_row["candidate_peak_days"]),
            "maximum_t": float(future_row["classical_t"]),
            "richness_maximum_t": future_richness_maximum,
            "inferential_role": "descriptive negative control only",
        },
        "permitted_wording": permitted_wording,
        "prohibited_wording": [
            "rain caused the diversity change",
            "the response was replicated across campaigns",
            "the fitted peak proves an exact biological latency",
            "campaign omission tests rainfall stability",
            "a threshold crossing after control filtering strengthens the effect size",
        ],
    }

    observed_scan.to_csv(
        output / "pulse_peak_scan.tsv", sep="\t", index=False, lineterminator="\n"
    )
    lag_null.to_csv(
        output / "conditional_lag_rotation_null.tsv.gz",
        sep="\t",
        index=False,
        compression={"method": "gzip", "compresslevel": 9, "mtime": 0},
        lineterminator="\n",
    )
    spatial_null.to_csv(
        output / "spatial_route_orbit_null.tsv",
        sep="\t",
        index=False,
        lineterminator="\n",
    )
    cluster_fits.to_csv(
        output / "selected_kernel_cluster_fits.tsv",
        sep="\t",
        index=False,
        lineterminator="\n",
    )
    bootstrap_draws.to_csv(
        output / "site_block_bootstrap_draws.tsv.gz",
        sep="\t",
        index=False,
        compression={"method": "gzip", "compresslevel": 9, "mtime": 0},
        lineterminator="\n",
    )
    bootstrap_summary.to_csv(
        output / "site_block_bootstrap_summary.tsv",
        sep="\t",
        index=False,
        lineterminator="\n",
    )
    if not position_effects.empty:
        position_effects.to_csv(
            output / "soil_position_sensitivity.tsv",
            sep="\t",
            index=False,
            lineterminator="\n",
        )
    elif (output / "soil_position_sensitivity.tsv").exists():
        (output / "soil_position_sensitivity.tsv").unlink()
    lag_bins.to_csv(
        output / "disjoint_lag_bin_sensitivity.tsv",
        sep="\t",
        index=False,
        lineterminator="\n",
    )
    campaign_exposures.to_csv(
        output / "campaign_exposure_summary.tsv",
        sep="\t",
        index=False,
        lineterminator="\n",
    )
    future_scan.to_csv(
        output / "future_rain_placebo_scan.tsv",
        sep="\t",
        index=False,
        lineterminator="\n",
    )
    cohort_output = observations.copy()
    cohort_output["selected_kernel_weighted_rain_mm"] = selected_exposure
    cohort_output["rain_1_to_4_complete_days_mm"] = rain_lags[:, :4].sum(axis=1)
    cohort_output["rain_1_to_60_complete_days_mm"] = rain_lags.sum(axis=1)
    cohort_output.to_csv(
        output / "analysis_cohort.tsv", sep="\t", index=False, lineterminator="\n"
    )
    (output / "analysis_decision.json").write_text(
        json.dumps(decision, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    plot_diagnostics(
        output / "rain_pulse_response.pdf",
        selected_endpoint,
        selected_peak,
        selected_beta,
        observed_scan,
        lag_null,
        observed_positive,
        bootstrap_draws,
        bootstrap_metadata,
    )
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "analysis_date": ANALYSIS_DATE,
        "git_head": git_head(root),
        "script": stable_path(Path(__file__), root),
        "parameters": {
            "seed": args.seed,
            "permutations": args.permutations,
            "bootstrap_seed": args.bootstrap_seed,
            "site_block_bootstraps": args.bootstraps,
            "bootstrap_method": bootstrap_metadata["method"],
            "horizon_complete_days": HORIZON_DAYS,
            "candidate_peak_days": PEAK_GRID_DAYS.tolist(),
            "sampling_day_included": False,
            "cohort": args.cohort,
            "cohort_description": cohort_description,
            "community_table_role": args.community_table_role,
            "nuisance_model": args.nuisance_model,
            "ph_adjusted": args.adjust_ph,
            "nuisance_formula": nuisance_formula,
            "nuisance_rank": nuisance_rank,
            "nuisance_columns": nuisance_columns,
        },
        "inputs": {
            "alpha": {
                "path": stable_path(args.alpha, root),
                "sha256": sha256_file(args.alpha),
            },
            "rainfall": {
                "path": stable_path(args.nasa_weather, root),
                "sha256": sha256_file(args.nasa_weather),
                "source_column": weather.source_column,
                "weather_product": args.weather_product,
            },
            **(
                {
                    "ph_group_table": {
                        "path": stable_path(args.ph_group_table, root),
                        "sha256": sha256_file(args.ph_group_table),
                    }
                }
                if args.adjust_ph
                else {}
            ),
        },
        "software": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "pandas": pd.__version__,
            "scipy": scipy.__version__,
            "statsmodels": statsmodels.__version__,
            "matplotlib": matplotlib.__version__,
        },
    }
    (output / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (output / "README.md").write_text(
        f"""# Short-term rainfall pulse-response analysis

This directory is generated by `analysis/v3/rain_pulse_response.py`.

This run uses the {args.community_table_role.replace('_', ' ')} community table
and the {args.weather_product.replace('_', ' ')} rainfall product. Its analysis
units are {cohort_description}. The model
represents the association following a millimetre of rain as a curve that
rises to a fitted peak and then decays. The full search covers peak times from
0.5 to 30 days and expected richness, Shannon diversity and normalized
evenness. Site and campaign baselines and campaign-specific route and
collection-day trends are adjusted.

The primary conditional null rotates the 60-day lag axis independently within
each campaign. It retains every campaign's observed rain amount, rarity and
spatial field, so it does not require rain to be stable or replicated across
campaigns. The route-orbit null is a separate spatial sensitivity. Neither
test establishes causation or an exact biological latency.

Sampling uncertainty is quantified with {args.bootstraps:,} site-block
bootstrap draws (seed {args.bootstrap_seed}). Each draw resamples a complete
site history and repeats the peak search on the nuisance-adjusted curves.
This interval does not include rainfall-product or route-model uncertainty;
those are reported as separate sensitivities.

Run from the project root:

```bash
.venv/bin/python analysis/v3/rain_pulse_response.py --permutations {args.permutations} --bootstraps {args.bootstraps}
```

`analysis_decision.json` states the allowed interpretation. `run_manifest.json`
records inputs, hashes, parameters and software; `SHA256SUMS` covers every
generated artifact.
""",
        encoding="utf-8",
    )
    write_checksums(output)


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=root)
    parser.add_argument(
        "--alpha",
        type=Path,
        default=root / "analysis/v2/review/cache/alpha.tsv",
    )
    parser.add_argument(
        "--nasa-weather",
        type=Path,
        default=root / "data/processed/climate/nasa_power_daily_precipitation.tsv.gz",
    )
    parser.add_argument(
        "--weather-product",
        choices=("nasa_power", "open_meteo"),
        default="nasa_power",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=root / "analysis/v3/rain_pulse_response",
    )
    parser.add_argument("--permutations", type=int, default=DEFAULT_PERMUTATIONS)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--bootstraps", type=int, default=DEFAULT_BOOTSTRAPS)
    parser.add_argument("--bootstrap-seed", type=int, default=BOOTSTRAP_SEED)
    parser.add_argument(
        "--cohort",
        choices=("grouped", "paired"),
        default="grouped",
        help="Use every soil-position group (primary) or complete bulk pairs.",
    )
    parser.add_argument(
        "--community-table-role",
        choices=("primary_unfiltered", "control_filtered_sensitivity"),
        default="primary_unfiltered",
    )
    parser.add_argument(
        "--nuisance-model",
        choices=tuple(NUISANCE_ADDITIONS),
        default="linear",
    )
    parser.add_argument("--adjust-ph", action="store_true")
    parser.add_argument(
        "--ph-group-table",
        type=Path,
        default=root / "analysis/v3/ph_shared_v1/ecology/ph_group_analysis_table.tsv",
    )
    args = parser.parse_args()
    if args.permutations < 99:
        parser.error("--permutations must be at least 99")
    if args.bootstraps < 999:
        parser.error("--bootstraps must be at least 999")
    return args


if __name__ == "__main__":
    run(parse_args())
