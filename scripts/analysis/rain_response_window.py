#!/usr/bin/env python3
"""Estimate an antecedent-rain response window without treating sites as rain replicates.

This is a post-hoc, design-aware analysis for the Empty Quarter ecology paper.
Its primary estimand is the effect of antecedent NASA POWER precipitation on
the within-site, within-campaign surface-minus-shallow-subsurface contrast in
normalized evenness, H/log(E[S_25k]).  The contrast is formed before fitting so
campaign-wide laboratory effects shared by the two positions cancel.  Site and
campaign fixed effects then allow the baseline position contrast to vary among
sites and campaigns.  Campaign-specific route and collection-day terms address
the near-alias between geography and sampling order.

Primary inference uses complete days before sampling.  Sampling-day rain is a
sensitivity because collection times are unavailable.  A joint disjoint-lag
model avoids selecting among nested cumulative windows.  A cumulative scan is
reported as a diagnostic, with its full search calibrated by time-shifting the
entire gridded daily precipitation field.  Nominal clustered standard errors
are retained only as diagnostics; they do not determine the verdict.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import os
import platform
import subprocess
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

# Small repeated matrix products are much faster and byte-stable with one BLAS
# thread; multithread startup dominates this permutation workload.
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
from scipy import linalg, stats
import statsmodels
import statsmodels.api as sm


SCHEMA_VERSION = "1.0"
ANALYSIS_DATE = "2026-08-03"
SEED = 20260803
DEFAULT_PERMUTATIONS = 4_999
CORE_SITES = tuple(range(1, 61))
POSITIONS = ("Surface", "Deep")
PRIMARY_ENDPOINT = "evenness_h_over_log_hurlbert"
ENDPOINTS = (
    PRIMARY_ENDPOINT,
    "shannon",
    "richness_hurlbert_25000",
)
ENDPOINT_LABELS = {
    PRIMARY_ENDPOINT: r"Normalized evenness, $H/\log(E[S_{25k}])$",
    "shannon": "Shannon diversity",
    "richness_hurlbert_25000": "Hurlbert expected richness at 25,000 reads",
}
LAG_BINS = ((1, 3), (4, 7), (8, 14), (15, 30), (31, 60))
CUMULATIVE_WINDOWS = tuple(range(1, 61))
MIN_SHIFT_DAYS = 60
POSITION_CONTRAST = "Surface-minus-shallow-subsurface"
PRIMARY_NUISANCE_FORMULA = (
    "0 + C(Site) + C(Trip) + C(Trip):longitude_z + C(Trip):sampling_day_z"
)
REDUCED_NUISANCE_FORMULA = "0 + C(Site) + C(Trip)"
PDF_METADATA = {
    "Title": "Empty Quarter antecedent-rainfall response-window diagnostics",
    "Creator": "analysis/v3/rain_response_window.py",
    "CreationDate": None,
    "ModDate": None,
}


@dataclass(frozen=True)
class WeatherProduct:
    name: str
    values: pd.DataFrame  # continuous Date index, integer site columns
    source_path: Path
    source_column: str
    grid_ids: Mapping[int, str]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def json_default(value: Any) -> Any:
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def stable_path(path: Path, root: Path) -> str:
    candidate = path if path.is_absolute() else root / path
    try:
        return candidate.absolute().relative_to(root.absolute()).as_posix()
    except ValueError:
        return candidate.absolute().as_posix()


def write_tsv(
    path: Path,
    rows: Iterable[Mapping[str, Any]] | pd.DataFrame,
    columns: Sequence[str] | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(rows, pd.DataFrame):
        frame = rows.copy()
        if columns is not None:
            frame = frame.loc[:, list(columns)]
        frame.to_csv(path, sep="\t", index=False, lineterminator="\n")
        return
    materialized = list(rows)
    if columns is None:
        columns = list(materialized[0]) if materialized else []
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(columns),
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        for row in materialized:
            formatted: dict[str, Any] = {}
            for column in columns:
                value = row.get(column)
                if value is None:
                    formatted[column] = ""
                elif isinstance(value, (bool, np.bool_)):
                    formatted[column] = "true" if value else "false"
                elif isinstance(value, (float, np.floating)):
                    formatted[column] = (
                        f"{float(value):.12g}" if math.isfinite(float(value)) else ""
                    )
                else:
                    formatted[column] = value
            writer.writerow(formatted)


def zscore_within(frame: pd.DataFrame, group: str, value: str) -> pd.Series:
    def transform(series: pd.Series) -> pd.Series:
        standard_deviation = float(series.std(ddof=0))
        if not math.isfinite(standard_deviation) or standard_deviation == 0:
            return pd.Series(np.zeros(len(series)), index=series.index)
        return (series - series.mean()) / standard_deviation

    return frame.groupby(group, group_keys=False)[value].transform(transform)


def safe_spearman(first: Sequence[float], second: Sequence[float]) -> float:
    first_array = np.asarray(first, dtype=float)
    second_array = np.asarray(second, dtype=float)
    finite = np.isfinite(first_array) & np.isfinite(second_array)
    first_array = first_array[finite]
    second_array = second_array[finite]
    if (
        len(first_array) < 3
        or np.unique(first_array).size < 2
        or np.unique(second_array).size < 2
    ):
        return math.nan
    return float(stats.spearmanr(first_array, second_array).statistic)


def load_geodata(root: Path) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for trip in range(1, 6):
        path = root / f"data/metadata/geodata/trip{trip}_geodata.tsv"
        frame = pd.read_csv(path, sep="\t")
        integer_site = frame["Site"].astype(str).str.fullmatch(r"[0-9]+")
        frame = frame.loc[integer_site].copy()
        frame["Site"] = pd.to_numeric(frame["Site"], errors="raise").astype(int)
        frame = frame[frame["Site"].isin(CORE_SITES)].copy()
        frame["Trip"] = trip
        frame["Date"] = pd.to_datetime(frame["CenterDate"], errors="raise")
        frames.append(
            frame.loc[:, ["Trip", "Site", "Date", "Latitude", "Longitude"]]
        )
    result = pd.concat(frames, ignore_index=True)
    if result.duplicated(["Trip", "Site"]).any():
        duplicated = result.loc[
            result.duplicated(["Trip", "Site"], keep=False), ["Trip", "Site"]
        ]
        raise ValueError(f"Duplicate integer site-campaign geodata: {duplicated}")
    result["sampling_day"] = (
        result["Date"] - result.groupby("Trip")["Date"].transform("min")
    ).dt.days.astype(float)
    result["longitude_z"] = zscore_within(result, "Trip", "Longitude")
    result["sampling_day_z"] = zscore_within(result, "Trip", "sampling_day")
    return result.sort_values(["Trip", "Site"]).reset_index(drop=True)


def load_alpha_differences(path: Path, geodata: pd.DataFrame) -> pd.DataFrame:
    frame = pd.read_csv(path, sep="\t", dtype={"Site": "string"})
    required = {
        "Trip",
        "Site",
        "Type",
        "shannon",
        "richness_rare",
        "pielou",
    }
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"Alpha input is missing columns: {sorted(missing)}")
    frame = frame.copy()
    frame["Trip"] = pd.to_numeric(frame["Trip"], errors="raise").astype(int)
    integer_site = frame["Site"].str.strip().str.fullmatch(r"[0-9]+", na=False)
    frame = frame.loc[integer_site].copy()
    frame["Site"] = pd.to_numeric(frame["Site"], errors="raise").astype(int)
    frame = frame[
        frame["Trip"].between(1, 5)
        & frame["Site"].isin(CORE_SITES)
        & frame["Type"].isin(POSITIONS)
    ].copy()
    frame["evenness_h_over_log_hurlbert"] = pd.to_numeric(
        frame["pielou"], errors="raise"
    )
    frame["richness_hurlbert_25000"] = pd.to_numeric(
        frame["richness_rare"], errors="raise"
    )
    for endpoint in ENDPOINTS:
        frame[endpoint] = pd.to_numeric(frame[endpoint], errors="raise")

    blocks = (
        frame.groupby(["Trip", "Site", "Type"], as_index=False)
        .agg(
            **{endpoint: (endpoint, "mean") for endpoint in ENDPOINTS},
            n_profiles=("shannon", "size"),
        )
        .sort_values(["Trip", "Site", "Type"])
    )
    wide = blocks.pivot(index=["Trip", "Site"], columns="Type")
    result = pd.DataFrame(index=wide.index).reset_index()
    for endpoint in ENDPOINTS:
        result[endpoint] = (
            wide[(endpoint, "Surface")].to_numpy()
            - wide[(endpoint, "Deep")].to_numpy()
        )
    result["n_surface_profiles"] = wide[("n_profiles", "Surface")].to_numpy()
    result["n_deep_profiles"] = wide[("n_profiles", "Deep")].to_numpy()
    result = result.dropna(subset=list(ENDPOINTS)).copy()
    result = result.merge(
        geodata,
        on=["Trip", "Site"],
        how="inner",
        validate="one_to_one",
    )
    if len(result) < 150:
        raise ValueError(f"Unexpectedly small paired alpha cohort: {len(result)}")
    return result.sort_values(["Trip", "Site"]).reset_index(drop=True)


def _validate_weather_matrix(values: pd.DataFrame, name: str) -> pd.DataFrame:
    values = values.copy().sort_index()
    if values.index.duplicated().any() or values.columns.duplicated().any():
        raise ValueError(f"{name} weather matrix has duplicate dates or sites")
    expected_dates = pd.date_range(values.index.min(), values.index.max(), freq="D")
    if not values.index.equals(expected_dates):
        raise ValueError(f"{name} weather dates are not continuous")
    missing_sites = set(CORE_SITES) - {int(site) for site in values.columns}
    if missing_sites:
        raise ValueError(f"{name} weather misses sites: {sorted(missing_sites)}")
    values = values.loc[:, list(CORE_SITES)].astype(float)
    if values.isna().any().any():
        raise ValueError(f"{name} weather contains missing precipitation")
    if (values < 0).any().any():
        raise ValueError(f"{name} weather contains negative precipitation")
    return values


def series_grid_ids(values: pd.DataFrame, prefix: str) -> dict[int, str]:
    hashes: dict[int, str] = {}
    for site in values.columns:
        contiguous = np.ascontiguousarray(values[site].to_numpy(dtype="<f8"))
        hashes[int(site)] = hashlib.sha256(contiguous.tobytes()).hexdigest()
    ordered_hashes = list(dict.fromkeys(hashes.values()))
    labels = {
        series_hash: f"{prefix}_{index:03d}"
        for index, series_hash in enumerate(ordered_hashes, start=1)
    }
    return {site: labels[series_hash] for site, series_hash in hashes.items()}


def load_nasa(path: Path) -> WeatherProduct:
    if path.name.endswith(".tsv.gz") or path.suffix == ".tsv":
        frame = pd.read_csv(
            path,
            sep="\t",
            usecols=["Site", "Date", "Precip_mm"],
            dtype={"Site": int, "Date": str, "Precip_mm": float},
        )
        frame["Date"] = pd.to_datetime(frame["Date"], errors="raise")
        site_column = "Site"
        precipitation_column = "Precip_mm"
    else:
        frame = pd.read_csv(
            path,
            usecols=["site", "date", "PRECTOTCORR"],
            dtype={"site": int, "date": str, "PRECTOTCORR": float},
        )
        frame["Date"] = pd.to_datetime(
            frame["date"], format="%Y%m%d", errors="raise"
        )
        site_column = "site"
        precipitation_column = "PRECTOTCORR"
    values = frame.pivot(
        index="Date", columns=site_column, values=precipitation_column
    )
    values.columns.name = "Site"
    values = _validate_weather_matrix(values, "NASA POWER")
    return WeatherProduct(
        name="NASA_POWER_PRECTOTCORR",
        values=values,
        source_path=path,
        source_column="PRECTOTCORR",
        grid_ids=series_grid_ids(values, "POWER"),
    )


def load_open_meteo(path: Path) -> WeatherProduct:
    frame = pd.read_csv(path, sep="\t")
    required = {"Site", "Date", "Precip_mm"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"Open-Meteo input is missing columns: {sorted(missing)}")
    integer_site = frame["Site"].astype(str).str.fullmatch(r"[0-9]+")
    frame = frame.loc[integer_site].copy()
    frame["Site"] = pd.to_numeric(frame["Site"], errors="raise").astype(int)
    frame = frame[frame["Site"].isin(CORE_SITES)].copy()
    frame["Date"] = pd.to_datetime(frame["Date"], errors="raise")
    frame["Precip_mm"] = pd.to_numeric(frame["Precip_mm"], errors="raise")
    values = frame.pivot(index="Date", columns="Site", values="Precip_mm")
    values = _validate_weather_matrix(values, "Open-Meteo")
    return WeatherProduct(
        name="Open_Meteo_precipitation_sum",
        values=values,
        source_path=path,
        source_column="Precip_mm",
        grid_ids=series_grid_ids(values, "OPENMETEO"),
    )


def _date_position(index: pd.DatetimeIndex, timestamp: pd.Timestamp) -> int:
    position = int(index.searchsorted(timestamp))
    if position >= len(index) or index[position] != timestamp:
        raise ValueError(f"Weather date unavailable: {timestamp.date()}")
    return position


def exposure_matrix(
    observations: pd.DataFrame,
    weather: WeatherProduct,
    intervals: Sequence[tuple[int, int]],
    *,
    shifts: Mapping[int, int] | None = None,
    include_sampling_day: bool = False,
) -> np.ndarray:
    """Sum rain over inclusive lag intervals.

    Positive lag 1 is the complete calendar day before sampling.  When
    ``include_sampling_day`` is true, lag 1 is the sampling date; this is a
    sensitivity only because sampling times are not recorded.
    """
    values = weather.values
    cumulative = np.vstack(
        [np.zeros((1, values.shape[1])), np.cumsum(values.to_numpy(), axis=0)]
    )
    site_to_column = {int(site): index for index, site in enumerate(values.columns)}
    result = np.empty((len(observations), len(intervals)), dtype=float)
    shifts = shifts or {}
    day_offset = 0 if include_sampling_day else 1
    for row_index, row in enumerate(observations.itertuples(index=False)):
        shifted_date = row.Date + pd.Timedelta(days=int(shifts.get(int(row.Trip), 0)))
        sample_position = _date_position(values.index, shifted_date)
        site_column = site_to_column[int(row.Site)]
        for interval_index, (lag_start, lag_end) in enumerate(intervals):
            if lag_start < 1 or lag_end < lag_start:
                raise ValueError(f"Invalid lag interval: {(lag_start, lag_end)}")
            end_position = sample_position - day_offset - (lag_start - 1)
            start_position = sample_position - day_offset - (lag_end - 1)
            if start_position < 0 or end_position >= len(values):
                raise ValueError(
                    f"Lag interval {(lag_start, lag_end)} leaves weather range "
                    f"for trip {row.Trip}, site {row.Site}, date {shifted_date.date()}"
                )
            result[row_index, interval_index] = (
                cumulative[end_position + 1, site_column]
                - cumulative[start_position, site_column]
            )
    return result


def future_exposure(
    observations: pd.DataFrame,
    weather: WeatherProduct,
    days: int,
) -> np.ndarray:
    values = weather.values
    cumulative = np.vstack(
        [np.zeros((1, values.shape[1])), np.cumsum(values.to_numpy(), axis=0)]
    )
    site_to_column = {int(site): index for index, site in enumerate(values.columns)}
    result = np.empty(len(observations), dtype=float)
    for row_index, row in enumerate(observations.itertuples(index=False)):
        sample_position = _date_position(values.index, row.Date)
        start = sample_position + 1
        stop = sample_position + days
        if stop >= len(values):
            raise ValueError("Future-rain placebo leaves weather range")
        site_column = site_to_column[int(row.Site)]
        result[row_index] = (
            cumulative[stop + 1, site_column] - cumulative[start, site_column]
        )
    return result


def orthonormal_column_space(matrix: np.ndarray) -> tuple[np.ndarray, int]:
    matrix = np.asarray(matrix, dtype=float)
    u, singular_values, _ = np.linalg.svd(matrix, full_matrices=False)
    if singular_values.size == 0:
        return np.empty((matrix.shape[0], 0)), 0
    tolerance = np.finfo(float).eps * max(matrix.shape) * singular_values[0]
    rank = int(np.sum(singular_values > tolerance))
    return u[:, :rank], rank


def residualize(matrix: np.ndarray, nuisance_basis: np.ndarray) -> np.ndarray:
    matrix = np.asarray(matrix, dtype=float)
    one_dimensional = matrix.ndim == 1
    if one_dimensional:
        matrix = matrix[:, None]
    result = matrix - nuisance_basis @ (nuisance_basis.T @ matrix)
    return result[:, 0] if one_dimensional else result


def nuisance_basis(
    observations: pd.DataFrame,
    formula: str = PRIMARY_NUISANCE_FORMULA,
) -> tuple[np.ndarray, int, list[str]]:
    design = patsy.dmatrix(formula, observations, return_type="dataframe")
    basis, rank = orthonormal_column_space(design.to_numpy())
    return basis, rank, list(design.columns)


def single_regressor_statistics(
    outcome: np.ndarray,
    exposures: np.ndarray,
    basis: np.ndarray,
    nuisance_rank: int,
) -> dict[str, np.ndarray]:
    residual_outcome = residualize(outcome, basis)
    residual_exposures = residualize(exposures, basis)
    denominator = np.sum(residual_exposures**2, axis=0)
    numerator = residual_exposures.T @ residual_outcome
    beta = np.divide(
        numerator,
        denominator,
        out=np.full_like(numerator, np.nan, dtype=float),
        where=denominator > 1e-12,
    )
    outcome_ss = float(residual_outcome @ residual_outcome)
    residual_ss = outcome_ss - np.divide(
        numerator**2,
        denominator,
        out=np.zeros_like(numerator, dtype=float),
        where=denominator > 1e-12,
    )
    degrees_freedom = len(outcome) - nuisance_rank - 1
    variance = residual_ss / degrees_freedom
    standard_error = np.sqrt(
        np.divide(
            variance,
            denominator,
            out=np.full_like(variance, np.nan, dtype=float),
            where=denominator > 1e-12,
        )
    )
    t_value = beta / standard_error
    partial_r2 = np.divide(
        numerator**2 / np.maximum(denominator, 1e-300),
        outcome_ss,
        out=np.full_like(numerator, np.nan, dtype=float),
        where=outcome_ss > 0,
    )
    return {
        "beta": beta,
        "standard_error_classical": standard_error,
        "t_classical": t_value,
        "partial_r2": partial_r2,
        "residual_exposure_ss": denominator,
    }


def joint_lag_statistics(
    outcome: np.ndarray,
    exposures: np.ndarray,
    basis: np.ndarray,
    nuisance_rank: int,
) -> dict[str, Any]:
    residual_outcome = residualize(outcome, basis)
    residual_exposures = residualize(exposures, basis)
    exposure_rank = int(np.linalg.matrix_rank(residual_exposures))
    if exposure_rank != exposures.shape[1]:
        return {
            "valid": False,
            "reason": f"rank {exposure_rank}/{exposures.shape[1]}",
            "beta": np.full(exposures.shape[1], np.nan),
            "standard_error_classical": np.full(exposures.shape[1], np.nan),
            "t_classical": np.full(exposures.shape[1], np.nan),
            "max_negative_t": np.nan,
            "max_absolute_t": np.nan,
            "omnibus_f": np.nan,
        }
    beta, _, _, _ = np.linalg.lstsq(residual_exposures, residual_outcome, rcond=None)
    residual = residual_outcome - residual_exposures @ beta
    degrees_freedom = len(outcome) - nuisance_rank - exposure_rank
    residual_variance = float(residual @ residual) / degrees_freedom
    covariance = residual_variance * np.linalg.pinv(
        residual_exposures.T @ residual_exposures
    )
    standard_error = np.sqrt(np.diag(covariance))
    t_value = beta / standard_error
    fitted = residual_exposures @ beta
    omnibus_f = (
        float(fitted @ fitted) / exposure_rank / residual_variance
        if residual_variance > 0
        else np.nan
    )
    return {
        "valid": True,
        "reason": "",
        "beta": beta,
        "standard_error_classical": standard_error,
        "t_classical": t_value,
        "max_negative_t": float(np.nanmax(-t_value)),
        "max_absolute_t": float(np.nanmax(np.abs(t_value))),
        "omnibus_f": omnibus_f,
        "degrees_freedom": degrees_freedom,
    }


def clustered_single_fit(
    outcome: np.ndarray,
    exposure: np.ndarray,
    basis: np.ndarray,
    clusters: Sequence[str],
) -> dict[str, float]:
    design = np.column_stack([basis, exposure])
    fit = sm.OLS(outcome, design).fit(
        cov_type="cluster",
        cov_kwds={"groups": np.asarray(clusters), "use_correction": True},
    )
    estimate = float(fit.params[-1])
    standard_error = float(fit.bse[-1])
    return {
        "estimate": estimate,
        "standard_error": standard_error,
        "t": estimate / standard_error,
        "p_two_sided": float(fit.pvalues[-1]),
        "ci_low": estimate - stats.norm.ppf(0.975) * standard_error,
        "ci_high": estimate + stats.norm.ppf(0.975) * standard_error,
        "n_clusters": int(pd.Series(clusters).nunique()),
    }


def allowed_time_shifts(
    observations: pd.DataFrame,
    weather: WeatherProduct,
    *,
    maximum_lag: int,
    minimum_shift: int = MIN_SHIFT_DAYS,
) -> dict[int, np.ndarray]:
    lower_weather = weather.values.index.min()
    upper_weather = weather.values.index.max()
    result: dict[int, np.ndarray] = {}
    for trip, group in observations.groupby("Trip"):
        minimum_date = group["Date"].min()
        maximum_date = group["Date"].max()
        lower_shift = int((lower_weather + pd.Timedelta(days=maximum_lag) - minimum_date).days)
        upper_shift = int((upper_weather - maximum_date).days)
        candidates = np.arange(lower_shift, upper_shift + 1, dtype=int)
        candidates = candidates[np.abs(candidates) >= minimum_shift]
        if not len(candidates):
            raise ValueError(f"No admissible time shifts for Trip {trip}")
        result[int(trip)] = candidates
    return result


def draw_time_shifts(
    allowed: Mapping[int, np.ndarray],
    permutations: int,
    seed: int,
) -> list[dict[int, int]]:
    rng = np.random.default_rng(seed)
    rows: list[dict[int, int]] = []
    seen: set[tuple[int, ...]] = set()
    trips = sorted(allowed)
    while len(rows) < permutations:
        candidate = tuple(int(rng.choice(allowed[trip])) for trip in trips)
        if candidate in seen:
            continue
        seen.add(candidate)
        rows.append(dict(zip(trips, candidate)))
    return rows


def draw_estimable_time_shifts(
    observations: pd.DataFrame,
    weather: WeatherProduct,
    allowed: Mapping[int, np.ndarray],
    basis: np.ndarray,
    permutations: int,
    seed: int,
) -> tuple[list[dict[int, int]], int]:
    """Draw unique shifts whose joint lag matrix remains fully estimable."""
    rng = np.random.default_rng(seed)
    trips = sorted(allowed)
    accepted: list[dict[int, int]] = []
    seen: set[tuple[int, ...]] = set()
    attempts = 0
    maximum_attempts = max(50_000, permutations * 100)
    while len(accepted) < permutations and attempts < maximum_attempts:
        attempts += 1
        candidate_tuple = tuple(int(rng.choice(allowed[trip])) for trip in trips)
        if candidate_tuple in seen:
            continue
        seen.add(candidate_tuple)
        candidate = dict(zip(trips, candidate_tuple))
        exposures = exposure_matrix(
            observations,
            weather,
            LAG_BINS,
            shifts=candidate,
        )
        residual_exposures = residualize(exposures, basis)
        if np.linalg.matrix_rank(residual_exposures) != len(LAG_BINS):
            continue
        accepted.append(candidate)
    if len(accepted) < permutations:
        raise RuntimeError(
            f"Only {len(accepted)} fully estimable shifts found in {attempts} attempts"
        )
    return accepted, attempts


def run_time_shift_null(
    observations: pd.DataFrame,
    weather: WeatherProduct,
    outcomes: Mapping[str, np.ndarray],
    basis: np.ndarray,
    nuisance_rank: int,
    shifts: Sequence[Mapping[int, int]],
    *,
    include_sampling_day: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    lag_rows: list[dict[str, Any]] = []
    scan_rows: list[dict[str, Any]] = []
    cumulative_intervals = tuple((1, window) for window in CUMULATIVE_WINDOWS)
    for permutation_index, shift in enumerate(shifts, start=1):
        lag_exposures = exposure_matrix(
            observations,
            weather,
            LAG_BINS,
            shifts=shift,
            include_sampling_day=include_sampling_day,
        )
        cumulative_exposures = exposure_matrix(
            observations,
            weather,
            cumulative_intervals,
            shifts=shift,
            include_sampling_day=include_sampling_day,
        )
        endpoint_lag_max: list[float] = []
        endpoint_scan_max: list[float] = []
        per_endpoint_lag: dict[str, float] = {}
        per_endpoint_scan: dict[str, float] = {}
        for endpoint, outcome in outcomes.items():
            lag_fit = joint_lag_statistics(
                outcome, lag_exposures, basis, nuisance_rank
            )
            scan_fit = single_regressor_statistics(
                outcome, cumulative_exposures, basis, nuisance_rank
            )
            lag_statistic = float(lag_fit["max_absolute_t"])
            scan_statistic = float(np.nanmax(np.abs(scan_fit["t_classical"])))
            per_endpoint_lag[endpoint] = lag_statistic
            per_endpoint_scan[endpoint] = scan_statistic
            if math.isfinite(lag_statistic):
                endpoint_lag_max.append(lag_statistic)
            if math.isfinite(scan_statistic):
                endpoint_scan_max.append(scan_statistic)
        common = {
            "permutation": permutation_index,
            **{f"shift_trip_{trip}": shift[trip] for trip in sorted(shift)},
        }
        lag_rows.append(
            {
                **common,
                **{f"max_absolute_t_{key}": value for key, value in per_endpoint_lag.items()},
                "max_absolute_t_all_endpoints": (
                    max(endpoint_lag_max) if endpoint_lag_max else np.nan
                ),
            }
        )
        scan_rows.append(
            {
                **common,
                **{f"max_absolute_t_{key}": value for key, value in per_endpoint_scan.items()},
                "max_absolute_t_all_endpoints": max(endpoint_scan_max),
            }
        )
    return pd.DataFrame(lag_rows), pd.DataFrame(scan_rows)


def plus_one_p(null_values: Sequence[float], observed: float) -> float:
    array = np.asarray(null_values, dtype=float)
    array = array[np.isfinite(array)]
    if not len(array) or not math.isfinite(observed):
        return math.nan
    return float((1 + np.sum(array >= observed)) / (len(array) + 1))


def observed_window_tables(
    observations: pd.DataFrame,
    weather: WeatherProduct,
    basis: np.ndarray,
    nuisance_rank: int,
    time_lag_null: pd.DataFrame,
    time_scan_null: pd.DataFrame,
    *,
    include_sampling_day: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    lag_exposures = exposure_matrix(
        observations,
        weather,
        LAG_BINS,
        include_sampling_day=include_sampling_day,
    )
    cumulative_intervals = tuple((1, window) for window in CUMULATIVE_WINDOWS)
    cumulative_exposures = exposure_matrix(
        observations,
        weather,
        cumulative_intervals,
        include_sampling_day=include_sampling_day,
    )
    clusters = [
        f"T{trip}_{weather.grid_ids[int(site)]}"
        for trip, site in observations.loc[:, ["Trip", "Site"]].itertuples(index=False)
    ]
    lag_rows: list[dict[str, Any]] = []
    scan_rows: list[dict[str, Any]] = []
    decisions: dict[str, Any] = {}
    for endpoint in ENDPOINTS:
        outcome = observations[endpoint].to_numpy(dtype=float)
        lag_fit = joint_lag_statistics(outcome, lag_exposures, basis, nuisance_rank)
        scan_fit = single_regressor_statistics(
            outcome, cumulative_exposures, basis, nuisance_rank
        )
        lag_null_endpoint = time_lag_null[f"max_absolute_t_{endpoint}"]
        lag_null_family = time_lag_null["max_absolute_t_all_endpoints"]
        scan_null_endpoint = time_scan_null[f"max_absolute_t_{endpoint}"]
        scan_null_family = time_scan_null["max_absolute_t_all_endpoints"]

        for index, (lag_start, lag_end) in enumerate(LAG_BINS):
            statistic = float(abs(lag_fit["t_classical"][index]))
            lag_rows.append(
                {
                    "product": weather.name,
                    "sampling_day_included": include_sampling_day,
                    "endpoint": endpoint,
                    "endpoint_role": "primary" if endpoint == PRIMARY_ENDPOINT else "secondary",
                    "position_contrast": POSITION_CONTRAST,
                    "lag_start_days": lag_start,
                    "lag_end_days": lag_end,
                    "estimate_per_mm": lag_fit["beta"][index],
                    "classical_se": lag_fit["standard_error_classical"][index],
                    "classical_t": lag_fit["t_classical"][index],
                    "absolute_t_statistic": statistic,
                    "permutation_p_endpoint_fwer": plus_one_p(lag_null_endpoint, statistic),
                    "permutation_p_all_endpoint_fwer": plus_one_p(lag_null_family, statistic),
                    "n_site_campaign_pairs": len(observations),
                    "n_sites": observations["Site"].nunique(),
                    "n_exposure_cells": len(set(clusters)),
                    "nuisance_rank": nuisance_rank,
                    "model_residual_df": lag_fit.get("degrees_freedom"),
                }
            )

        for index, window in enumerate(CUMULATIVE_WINDOWS):
            clustered = clustered_single_fit(
                outcome,
                cumulative_exposures[:, index],
                basis,
                clusters,
            )
            statistic = float(abs(scan_fit["t_classical"][index]))
            scan_rows.append(
                {
                    "product": weather.name,
                    "sampling_day_included": include_sampling_day,
                    "endpoint": endpoint,
                    "endpoint_role": "primary" if endpoint == PRIMARY_ENDPOINT else "secondary",
                    "position_contrast": POSITION_CONTRAST,
                    "window_days": window,
                    "estimate_per_mm": scan_fit["beta"][index],
                    "classical_se": scan_fit["standard_error_classical"][index],
                    "classical_t": scan_fit["t_classical"][index],
                    "clustered_se_diagnostic": clustered["standard_error"],
                    "clustered_p_two_sided_diagnostic": clustered["p_two_sided"],
                    "absolute_t_statistic": statistic,
                    "partial_r2": scan_fit["partial_r2"][index],
                    "permutation_p_endpoint_fwer": plus_one_p(scan_null_endpoint, statistic),
                    "permutation_p_all_endpoint_fwer": plus_one_p(scan_null_family, statistic),
                    "n_site_campaign_pairs": len(observations),
                    "n_sites": observations["Site"].nunique(),
                    "n_exposure_cells": len(set(clusters)),
                    "nuisance_rank": nuisance_rank,
                }
            )

        best_lag_index = int(np.nanargmax(np.abs(lag_fit["t_classical"])))
        best_scan_index = int(np.nanargmax(np.abs(scan_fit["t_classical"])))
        best_lag_statistic = float(abs(lag_fit["t_classical"][best_lag_index]))
        best_scan_statistic = float(abs(scan_fit["t_classical"][best_scan_index]))
        decisions[endpoint] = {
            "best_disjoint_lag_bin": list(LAG_BINS[best_lag_index]),
            "best_disjoint_lag_absolute_t": best_lag_statistic,
            "disjoint_lag_permutation_p_endpoint_fwer": plus_one_p(
                lag_null_endpoint, best_lag_statistic
            ),
            "disjoint_lag_permutation_p_all_endpoint_fwer": plus_one_p(
                lag_null_family, best_lag_statistic
            ),
            "best_cumulative_window_days": CUMULATIVE_WINDOWS[best_scan_index],
            "best_cumulative_absolute_t": best_scan_statistic,
            "cumulative_scan_permutation_p_endpoint_fwer": plus_one_p(
                scan_null_endpoint, best_scan_statistic
            ),
            "cumulative_scan_permutation_p_all_endpoint_fwer": plus_one_p(
                scan_null_family, best_scan_statistic
            ),
        }
    return pd.DataFrame(lag_rows), pd.DataFrame(scan_rows), decisions


def exposure_diagnostics(
    geodata: pd.DataFrame,
    products: Sequence[WeatherProduct],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    rows: list[dict[str, Any]] = []
    alias_rows: list[dict[str, Any]] = []
    exposure_frames: list[pd.DataFrame] = []
    basic_basis, _basic_rank, _ = nuisance_basis(
        geodata, "0 + C(Site) + C(Trip)"
    )
    intervals = tuple((1, window) for window in (1, 3, 7, 14, 30, 60, 90))
    for product in products:
        exposures = exposure_matrix(geodata, product, intervals)
        product_frame = geodata.loc[:, ["Trip", "Site"]].copy()
        product_frame["product"] = product.name
        for index, (_lag_start, lag_end) in enumerate(intervals):
            values = exposures[:, index]
            residual = residualize(values, basic_basis)
            total_ss = float(np.sum((values - values.mean()) ** 2))
            residual_ss = float(residual @ residual)
            rows.append(
                {
                    "product": product.name,
                    "window_days": lag_end,
                    "n_site_campaigns": len(values),
                    "n_sites": geodata["Site"].nunique(),
                    "n_unique_daily_series": len(set(product.grid_ids.values())),
                    "mean_mm": float(values.mean()),
                    "median_mm": float(np.median(values)),
                    "maximum_mm": float(values.max()),
                    "fraction_zero": float(np.mean(values == 0)),
                    "variance_fraction_after_site_campaign_fe": (
                        residual_ss / total_ss if total_ss > 0 else np.nan
                    ),
                    "n_grid_campaigns_at_least_5mm": int(
                        pd.DataFrame(
                            {
                                "Trip": geodata["Trip"],
                                "grid": geodata["Site"].map(product.grid_ids),
                                "rain": values,
                            }
                        )
                        .groupby(["Trip", "grid"])["rain"]
                        .mean()
                        .ge(5)
                        .sum()
                    ),
                }
            )
            product_frame[f"rain_{lag_end}d"] = values
            for trip, indices in geodata.groupby("Trip").groups.items():
                local = geodata.loc[indices]
                rain = values[np.asarray(list(indices), dtype=int)]
                alias_rows.append(
                    {
                        "product": product.name,
                        "Trip": trip,
                        "window_days": lag_end,
                        "n": len(local),
                        "spearman_rain_longitude": safe_spearman(
                            rain, local["Longitude"]
                        ),
                        "spearman_rain_sampling_day": safe_spearman(
                            rain, local["sampling_day"]
                        ),
                        "spearman_sampling_day_longitude": safe_spearman(
                            local["sampling_day"], local["Longitude"]
                        ),
                    }
                )
        exposure_frames.append(product_frame)

    comparison_rows: list[dict[str, Any]] = []
    if len(exposure_frames) >= 2:
        first, second = exposure_frames[:2]
        merged = first.merge(second, on=["Trip", "Site"], suffixes=("_a", "_b"))
        for window in (1, 3, 7, 14, 30, 60, 90):
            a = merged[f"rain_{window}d_a"]
            b = merged[f"rain_{window}d_b"]
            comparison_rows.append(
                {
                    "product_a": products[0].name,
                    "product_b": products[1].name,
                    "window_days": window,
                    "n_site_campaigns": len(merged),
                    "pearson_r": stats.pearsonr(a, b).statistic,
                    "spearman_rho": stats.spearmanr(a, b).statistic,
                    "mean_a_mm": a.mean(),
                    "mean_b_mm": b.mean(),
                    "mean_absolute_difference_mm": np.mean(np.abs(a - b)),
                }
            )
    return (
        pd.DataFrame(rows),
        pd.DataFrame(alias_rows),
        pd.DataFrame(comparison_rows),
    )


def grid_membership_table(weather: WeatherProduct) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for grid_id in sorted(set(weather.grid_ids.values())):
        sites = sorted(site for site, label in weather.grid_ids.items() if label == grid_id)
        series = weather.values[sites[0]]
        rows.append(
            {
                "product": weather.name,
                "grid_series_id": grid_id,
                "sites": ",".join(str(site) for site in sites),
                "n_sites": len(sites),
                "first_site": sites[0],
                "last_site": sites[-1],
                "daily_series_sha256": hashlib.sha256(
                    np.ascontiguousarray(series.to_numpy(dtype="<f8")).tobytes()
                ).hexdigest(),
            }
        )
    return pd.DataFrame(rows)


def spatial_halves(
    observations: pd.DataFrame,
    weather: WeatherProduct,
    candidate_interval: tuple[int, int],
) -> pd.DataFrame:
    median_longitude = float(observations.groupby("Site")["Longitude"].first().median())
    rows: list[dict[str, Any]] = []
    for half, subset in (
        ("west", observations[observations["Longitude"] <= median_longitude].copy()),
        ("east", observations[observations["Longitude"] > median_longitude].copy()),
    ):
        basis, rank, _ = nuisance_basis(subset)
        exposure = exposure_matrix(subset, weather, (candidate_interval,))[:, 0]
        clusters = [
            f"T{trip}_{weather.grid_ids[int(site)]}"
            for trip, site in subset.loc[:, ["Trip", "Site"]].itertuples(index=False)
        ]
        for endpoint in ENDPOINTS:
            fit = clustered_single_fit(
                subset[endpoint].to_numpy(dtype=float), exposure, basis, clusters
            )
            rows.append(
                {
                    "half": half,
                    "endpoint": endpoint,
                    "lag_start_days": candidate_interval[0],
                    "lag_end_days": candidate_interval[1],
                    "n_site_campaign_pairs": len(subset),
                    "n_sites": subset["Site"].nunique(),
                    "n_exposure_cells": len(set(clusters)),
                    **fit,
                }
            )
    return pd.DataFrame(rows)


def placebo_table(
    observations: pd.DataFrame,
    weather: WeatherProduct,
    basis: np.ndarray,
    candidate_interval: tuple[int, int],
) -> pd.DataFrame:
    candidate_length = candidate_interval[1] - candidate_interval[0] + 1
    exposures = {
        "candidate_antecedent": exposure_matrix(
            observations, weather, (candidate_interval,)
        )[:, 0],
        "future_rain": future_exposure(observations, weather, candidate_length),
        "remote_180_365d": exposure_matrix(observations, weather, ((180, 365),))[:, 0],
    }
    clusters = [
        f"T{trip}_{weather.grid_ids[int(site)]}"
        for trip, site in observations.loc[:, ["Trip", "Site"]].itertuples(index=False)
    ]
    rows: list[dict[str, Any]] = []
    for endpoint in ENDPOINTS:
        for exposure_name, exposure in exposures.items():
            fit = clustered_single_fit(
                observations[endpoint].to_numpy(dtype=float),
                exposure,
                basis,
                clusters,
            )
            rows.append(
                {
                    "endpoint": endpoint,
                    "exposure": exposure_name,
                    "lag_start_days": (
                        candidate_interval[0]
                        if exposure_name == "candidate_antecedent"
                        else ""
                    ),
                    "lag_end_days": (
                        candidate_interval[1]
                        if exposure_name == "candidate_antecedent"
                        else ""
                    ),
                    "n_site_campaign_pairs": len(observations),
                    **fit,
                }
            )
    return pd.DataFrame(rows)


def approximate_mde_table(
    observations: pd.DataFrame,
    scan: pd.DataFrame,
    time_scan_null: pd.DataFrame,
    decision: Mapping[str, Any],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for endpoint in ENDPOINTS:
        window = int(decision[endpoint]["best_cumulative_window_days"])
        selected = scan[(scan["endpoint"] == endpoint) & (scan["window_days"] == window)].iloc[0]
        null_column = f"max_absolute_t_{endpoint}"
        critical_t = float(np.quantile(time_scan_null[null_column], 0.95))
        outcome_sd = float(observations[endpoint].std(ddof=1))
        clustered_se = float(selected["clustered_se_diagnostic"])
        mde_beta = (critical_t + stats.norm.ppf(0.80)) * clustered_se
        rows.append(
            {
                "endpoint": endpoint,
                "selected_window_days": window,
                "outcome_sd": outcome_sd,
                "clustered_se_per_mm": clustered_se,
                "permutation_max_t_95th_percentile": critical_t,
                "approximate_80pct_power_mde_per_mm": mde_beta,
                "approximate_80pct_power_mde_per_5mm": 5 * mde_beta,
                "approximate_80pct_power_mde_sd_per_5mm": (
                    5 * mde_beta / outcome_sd if outcome_sd > 0 else np.nan
                ),
                "interpretation": (
                    "Approximation using the empirical 95th percentile of the "
                    "endpoint-wise max-statistic null plus z_0.80; not a formal "
                    "simulation-based power curve."
                ),
            }
        )
    return pd.DataFrame(rows)


def make_figure(
    lag_table: pd.DataFrame,
    scan_table: pd.DataFrame,
    time_scan_null: pd.DataFrame,
    decision: Mapping[str, Any],
    output: Path,
) -> None:
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 9.5,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "pdf.fonttype": 42,
        }
    )
    fig, axes = plt.subplots(1, 3, figsize=(10.5, 3.2))
    primary_lag = lag_table[lag_table["endpoint"] == PRIMARY_ENDPOINT]
    labels = [
        f"{int(row.lag_start_days)}–{int(row.lag_end_days)}"
        for row in primary_lag.itertuples()
    ]
    axes[0].axhline(0, color="#777777", linewidth=0.8)
    lag_x = np.arange(len(primary_lag))
    axes[0].errorbar(
        lag_x,
        primary_lag["estimate_per_mm"],
        yerr=1.96 * primary_lag["classical_se"],
        fmt="o",
        color="#0072B2",
        capsize=3,
    )
    axes[0].set(
        xlabel="Complete days before sampling",
        ylabel="Surface–subsurface change per mm",
        title="(a) Joint lag estimates with uncertainty",
        xticks=lag_x,
        xticklabels=labels,
    )
    axes[0].tick_params(axis="x", rotation=35)

    primary_scan = scan_table[scan_table["endpoint"] == PRIMARY_ENDPOINT]
    axes[1].axhline(0, color="#777777", linewidth=0.8)
    axes[1].plot(
        primary_scan["window_days"],
        primary_scan["estimate_per_mm"],
        color="#009E73",
    )
    axes[1].fill_between(
        primary_scan["window_days"].to_numpy(dtype=float),
        (
            primary_scan["estimate_per_mm"]
            - 1.96 * primary_scan["classical_se"]
        ).to_numpy(dtype=float),
        (
            primary_scan["estimate_per_mm"]
            + 1.96 * primary_scan["classical_se"]
        ).to_numpy(dtype=float),
        color="#009E73",
        alpha=0.16,
        linewidth=0,
    )
    best_window = int(decision[PRIMARY_ENDPOINT]["best_cumulative_window_days"])
    best = primary_scan[primary_scan["window_days"] == best_window].iloc[0]
    axes[1].scatter([best_window], [best["estimate_per_mm"]], color="#CC3311", zorder=3)
    axes[1].set(
        xlabel="Cumulative antecedent window (days)",
        ylabel="Surface–subsurface change per mm",
        title="(b) Nested-window scan with uncertainty",
    )

    null = time_scan_null[f"max_absolute_t_{PRIMARY_ENDPOINT}"]
    observed = float(decision[PRIMARY_ENDPOINT]["best_cumulative_absolute_t"])
    axes[2].hist(null, bins=35, color="#BBBBBB", edgecolor="white")
    axes[2].axvline(observed, color="#CC3311", linewidth=1.6, label="Observed")
    p_value = decision[PRIMARY_ENDPOINT]["cumulative_scan_permutation_p_endpoint_fwer"]
    axes[2].set(
        xlabel="Maximum absolute t across 1–60-day scan",
        ylabel="Time shifts",
        title=f"(c) Calibrated null (p={p_value:.3f})",
    )
    axes[2].legend(frameon=False)
    fig.tight_layout()
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, bbox_inches="tight", metadata=PDF_METADATA)
    plt.close(fig)


def build_verdict(
    decisions: Mapping[str, Any],
    halves: pd.DataFrame,
    placebo: pd.DataFrame,
    product_sensitivity: Mapping[str, Any],
    same_day_sensitivity: Mapping[str, Any],
) -> dict[str, Any]:
    primary = decisions[PRIMARY_ENDPOINT]
    permutation_pass = (
        primary["cumulative_scan_permutation_p_endpoint_fwer"] < 0.05
    )
    half_primary = halves[halves["endpoint"] == PRIMARY_ENDPOINT]
    half_estimates = half_primary["estimate"].to_numpy(dtype=float)
    halves_pass = (
        len(half_primary) == 2
        and np.sign(half_estimates[0]) == np.sign(half_estimates[1])
        and min(abs(half_estimates[0]), abs(half_estimates[1]))
        / max(abs(half_estimates[0]), abs(half_estimates[1]))
        > 0.25
    )
    placebo_primary = placebo[placebo["endpoint"] == PRIMARY_ENDPOINT]
    future = placebo_primary[placebo_primary["exposure"] == "future_rain"].iloc[0]
    remote = placebo_primary[placebo_primary["exposure"] == "remote_180_365d"].iloc[0]
    placebo_pass = future["p_two_sided"] >= 0.05 and remote["p_two_sided"] >= 0.05
    product_pass = bool(product_sensitivity.get("direction_consistent", False))
    same_day_pass = bool(same_day_sensitivity.get("direction_consistent", False))
    criteria = {
        "permutation_endpoint_fwer_below_0.05": permutation_pass,
        "finite_selected_direction": math.isfinite(
            primary["best_cumulative_absolute_t"]
        ),
        "future_and_remote_placebos_nominally_null": placebo_pass,
        "spatial_halves_direction_and_magnitude_consistent": halves_pass,
        "climate_product_direction_consistent": product_pass,
        "sampling_day_sensitivity_direction_consistent": same_day_pass,
    }
    supported = all(criteria.values())
    return {
        "schema_version": SCHEMA_VERSION,
        "analysis_date": ANALYSIS_DATE,
        "analysis_status": (
            "response_window_supported" if supported else "response_window_not_identified"
        ),
        "main_paper_eligible": supported,
        "primary_endpoint": PRIMARY_ENDPOINT,
        "primary_endpoint_label": ENDPOINT_LABELS[PRIMARY_ENDPOINT],
        "position_contrast": POSITION_CONTRAST,
        "post_hoc_status": "post_hoc_design_audit_and_window_analysis",
        "criteria": criteria,
        "primary_results": primary,
        "permitted_wording": (
            "Antecedent rainfall was associated with a temporally localized "
            "surface-relative-to-subsurface evenness response."
            if supported
            else "The calibrated paired analysis did not identify a temporal "
            "response window to antecedent rainfall."
        ),
        "prohibited_wording": [
            "rain caused the observed community pattern",
            "a post-rain bloom was demonstrated",
            "the smallest nominal p-value identifies the response window",
            "sites sharing one POWER precipitation series are independent rain exposures",
        ],
    }


def write_checksums(output: Path) -> None:
    paths = sorted(
        path
        for path in output.iterdir()
        if path.is_file() and path.name != "SHA256SUMS"
    )
    content = "".join(f"{sha256_file(path)}  {path.name}\n" for path in paths)
    (output / "SHA256SUMS").write_text(content, encoding="utf-8")


def git_head(root: Path) -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def run(args: argparse.Namespace) -> None:
    root = args.root.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)

    geodata = load_geodata(root)
    primary_observations = load_alpha_differences(args.alpha, geodata)
    unfiltered_observations = load_alpha_differences(args.alpha_unfiltered, geodata)
    nasa = load_nasa(args.nasa_weather)
    open_meteo = load_open_meteo(args.open_meteo_weather)
    products = (nasa, open_meteo)

    primary_observations["power_grid_id"] = primary_observations["Site"].map(
        nasa.grid_ids
    )
    basis, nuisance_rank, nuisance_columns = nuisance_basis(primary_observations)
    outcomes = {
        endpoint: primary_observations[endpoint].to_numpy(dtype=float)
        for endpoint in ENDPOINTS
    }
    allowed = allowed_time_shifts(
        primary_observations, nasa, maximum_lag=max(max(interval) for interval in LAG_BINS)
    )
    shifts = draw_time_shifts(allowed, args.permutations, args.seed)
    shift_draw_attempts = args.permutations
    time_lag_null, time_scan_null = run_time_shift_null(
        primary_observations,
        nasa,
        outcomes,
        basis,
        nuisance_rank,
        shifts,
    )
    lag_null_finite_counts = {
        column: int(time_lag_null[column].notna().sum())
        for column in time_lag_null
        if column.startswith("max_absolute_t_")
    }
    scan_null_finite_counts = {
        column: int(time_scan_null[column].notna().sum())
        for column in time_scan_null
        if column.startswith("max_absolute_t_")
    }
    lag_table, scan_table, decisions = observed_window_tables(
        primary_observations,
        nasa,
        basis,
        nuisance_rank,
        time_lag_null,
        time_scan_null,
    )

    candidate_window = int(
        decisions[PRIMARY_ENDPOINT]["best_cumulative_window_days"]
    )
    candidate_interval = (1, candidate_window)
    halves = spatial_halves(primary_observations, nasa, candidate_interval)
    placebo = placebo_table(
        primary_observations, nasa, basis, candidate_interval
    )

    # Product sensitivity uses the same observed design and the NASA-derived
    # null only to compare selected direction. It never substitutes nominal p
    # values for the primary NASA time-shift inference.
    open_exposure = exposure_matrix(
        primary_observations, open_meteo, (candidate_interval,)
    )
    open_fit = single_regressor_statistics(
        outcomes[PRIMARY_ENDPOINT], open_exposure, basis, nuisance_rank
    )
    product_sensitivity = {
        "comparison_product": open_meteo.name,
        "candidate_interval": list(candidate_interval),
        "nasa_estimate_per_mm": float(
            scan_table[
                (scan_table["endpoint"] == PRIMARY_ENDPOINT)
                & (scan_table["window_days"] == candidate_window)
            ]["estimate_per_mm"].iloc[0]
        ),
        "comparison_estimate_per_mm": float(open_fit["beta"][0]),
    }
    product_sensitivity["direction_consistent"] = (
        np.sign(product_sensitivity["nasa_estimate_per_mm"])
        == np.sign(product_sensitivity["comparison_estimate_per_mm"])
    )

    same_day_exposure = exposure_matrix(
        primary_observations,
        nasa,
        (candidate_interval,),
        include_sampling_day=True,
    )
    same_day_fit = single_regressor_statistics(
        outcomes[PRIMARY_ENDPOINT], same_day_exposure, basis, nuisance_rank
    )
    same_day_sensitivity = {
        "candidate_interval": list(candidate_interval),
        "primary_complete_day_estimate_per_mm": product_sensitivity[
            "nasa_estimate_per_mm"
        ],
        "sampling_day_included_estimate_per_mm": float(
            same_day_fit["beta"][0]
        ),
    }
    same_day_sensitivity["direction_consistent"] = (
        np.sign(same_day_sensitivity["primary_complete_day_estimate_per_mm"])
        == np.sign(same_day_sensitivity["sampling_day_included_estimate_per_mm"])
    )

    # Contamination sensitivity is a point-estimate comparison on the same
    # candidate cumulative window. The filtered input is primary; the unfiltered table is
    # secondary because linked blank evidence currently applies only to Trip 5.
    unfiltered_basis, unfiltered_rank, _ = nuisance_basis(unfiltered_observations)
    unfiltered_exposure = exposure_matrix(
        unfiltered_observations, nasa, (candidate_interval,)
    )
    unfiltered_fit = single_regressor_statistics(
        unfiltered_observations[PRIMARY_ENDPOINT].to_numpy(dtype=float),
        unfiltered_exposure,
        unfiltered_basis,
        unfiltered_rank,
    )
    contamination_sensitivity = {
        "candidate_interval": list(candidate_interval),
        "filtered_n_pairs": len(primary_observations),
        "unfiltered_n_pairs": len(unfiltered_observations),
        "filtered_estimate_per_mm": product_sensitivity["nasa_estimate_per_mm"],
        "unfiltered_estimate_per_mm": float(unfiltered_fit["beta"][0]),
        "direction_consistent": (
            np.sign(product_sensitivity["nasa_estimate_per_mm"])
            == np.sign(unfiltered_fit["beta"][0])
        ),
        "scope_note": (
            "The contaminant filter changes linked Trip 5 profiles only; Trip 5 "
            "has little short-window rain, so this is a weak sensitivity for a "
            "rain effect carried by other campaigns."
        ),
    }

    exposure_summary, alias_table, product_agreement = exposure_diagnostics(
        geodata, products
    )
    mde = approximate_mde_table(
        primary_observations, scan_table, time_scan_null, decisions
    )
    verdict = build_verdict(
        decisions,
        halves,
        placebo,
        product_sensitivity,
        same_day_sensitivity,
    )
    verdict["contamination_sensitivity"] = contamination_sensitivity
    verdict["null_draw_accounting"] = {
        "requested_time_shifts": shift_draw_attempts,
        "disjoint_lag_finite_draws": lag_null_finite_counts,
        "cumulative_scan_finite_draws": scan_null_finite_counts,
        "p_value_denominator_rule": (
            "Plus-one permutation p-values use finite null statistics only. "
            "Non-estimable shifted disjoint-lag fits remain in the archived null "
            "table as missing values rather than being silently replaced."
        ),
    }

    pair_columns = [
        "Trip",
        "Site",
        "Date",
        "Latitude",
        "Longitude",
        "sampling_day",
        "longitude_z",
        "sampling_day_z",
        "power_grid_id",
        "n_surface_profiles",
        "n_deep_profiles",
        *ENDPOINTS,
    ]
    write_tsv(output / "paired_analysis_cohort.tsv", primary_observations, pair_columns)
    write_tsv(output / "power_grid_membership.tsv", grid_membership_table(nasa))
    write_tsv(output / "exposure_diagnostics.tsv", exposure_summary)
    write_tsv(output / "rain_route_alias.tsv", alias_table)
    write_tsv(output / "climate_product_agreement.tsv", product_agreement)
    write_tsv(output / "disjoint_lag_models.tsv", lag_table)
    write_tsv(output / "cumulative_window_scan.tsv", scan_table)
    write_tsv(output / "time_shift_null_disjoint_lags.tsv.gz", time_lag_null)
    write_tsv(output / "time_shift_null_cumulative_scan.tsv.gz", time_scan_null)
    write_tsv(output / "spatial_half_validation.tsv", halves)
    write_tsv(output / "negative_control_placebos.tsv", placebo)
    write_tsv(output / "minimum_detectable_effect.tsv", mde)
    (output / "analysis_decision.json").write_text(
        json.dumps(verdict, indent=2, sort_keys=True, default=json_default) + "\n",
        encoding="utf-8",
    )
    sensitivity = {
        "climate_product": product_sensitivity,
        "sampling_day": same_day_sensitivity,
        "contamination_filter": contamination_sensitivity,
    }
    (output / "sensitivity_summary.json").write_text(
        json.dumps(sensitivity, indent=2, sort_keys=True, default=json_default) + "\n",
        encoding="utf-8",
    )
    make_figure(
        lag_table,
        scan_table,
        time_scan_null,
        decisions,
        output / "rain_response_window.pdf",
    )

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "analysis_date": ANALYSIS_DATE,
        "script": stable_path(Path(__file__), root),
        "script_sha256": sha256_file(Path(__file__)),
        "git_head": git_head(root),
        "seed": args.seed,
        "time_shift_permutations": args.permutations,
        "time_shift_draw_attempts": shift_draw_attempts,
        "disjoint_lag_finite_null_draws": lag_null_finite_counts,
        "cumulative_scan_finite_null_draws": scan_null_finite_counts,
        "minimum_absolute_time_shift_days": MIN_SHIFT_DAYS,
        "lag_bins_complete_days_before_sampling": [list(interval) for interval in LAG_BINS],
        "cumulative_scan_complete_days_before_sampling": [1, 60],
        "sampling_day_primary": "excluded",
        "primary_endpoint": PRIMARY_ENDPOINT,
        "position_contrast": POSITION_CONTRAST,
        "nuisance_formula": PRIMARY_NUISANCE_FORMULA,
        "nuisance_columns": nuisance_columns,
        "nuisance_rank": nuisance_rank,
        "inputs": {
            "alpha_control_filtered": {
                "path": stable_path(args.alpha, root),
                "sha256": sha256_file(args.alpha),
            },
            "alpha_unfiltered": {
                "path": stable_path(args.alpha_unfiltered, root),
                "sha256": sha256_file(args.alpha_unfiltered),
            },
            "nasa_power": {
                "path": stable_path(args.nasa_weather, root),
                "sha256": sha256_file(args.nasa_weather),
                "column": nasa.source_column,
                "date_range": [
                    str(nasa.values.index.min().date()),
                    str(nasa.values.index.max().date()),
                ],
                "n_unique_daily_series": len(set(nasa.grid_ids.values())),
            },
            "open_meteo": {
                "path": stable_path(args.open_meteo_weather, root),
                "sha256": sha256_file(args.open_meteo_weather),
                "column": open_meteo.source_column,
                "date_range": [
                    str(open_meteo.values.index.min().date()),
                    str(open_meteo.values.index.max().date()),
                ],
            },
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
        json.dumps(manifest, indent=2, sort_keys=True, default=json_default) + "\n",
        encoding="utf-8",
    )
    readme = f"""# Antecedent-rainfall response-window analysis

This directory is generated by `analysis/v3/rain_response_window.py`.

The post-hoc primary estimand is antecedent-rainfall change in the paired
surface-minus-shallow-subsurface contrast for normalized evenness,
`H/log(E[S_25k])`. Profiles are first averaged within site, campaign and soil
position. The analysis then retains complete surface/deep pairs, allows the
baseline contrast to vary by site and campaign, and adjusts campaign-specific
longitude and collection-day trends. NASA POWER `PRECTOTCORR` is the primary
rain product. The control-filtered alpha-diversity table is primary and the
unfiltered table is a contamination-filter sensitivity. Open-Meteo is a
climate-product sensitivity.

Rain on the sampling date is excluded from the primary analysis because field
collection times are not recorded. Disjoint bins {LAG_BINS} are entered jointly.
The 1–60-day cumulative scan is diagnostic, and its entire search is calibrated
with {args.permutations:,} independent campaign-level time shifts of the full
daily gridded rain field. Sites sharing one POWER series are not treated as
independent rainfall observations. Nominal clustered values in the output are
diagnostics only; `analysis_decision.json` is determined by the permutation
result and the stated validation criteria.

All {scan_null_finite_counts[f"max_absolute_t_{PRIMARY_ENDPOINT}"]:,} requested
shifts produced a finite primary-endpoint statistic for the cumulative scan.
For the joint disjoint-lag fit,
{lag_null_finite_counts[f"max_absolute_t_{PRIMARY_ENDPOINT}"]:,} of
{args.permutations:,} shifts were estimable. Plus-one p-values use the finite
null statistics; non-estimable fits remain explicitly missing in the archived
null table.

Run from the project root:

```bash
.venv/bin/python analysis/v3/rain_response_window.py
```

See `run_manifest.json` for exact inputs, hashes, software versions, seed and
parameters. `SHA256SUMS` covers every generated artifact in this directory.
"""
    (output / "README.md").write_text(readme, encoding="utf-8")
    write_checksums(output)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    root = Path(__file__).resolve().parents[2]
    parser.add_argument("--root", type=Path, default=root)
    parser.add_argument(
        "--alpha",
        type=Path,
        default=root / "analysis/v3/control_audit/sensitivity_inputs/alpha.tsv",
    )
    parser.add_argument(
        "--alpha-unfiltered",
        type=Path,
        default=root / "analysis/v2/review/cache/alpha.tsv",
    )
    parser.add_argument(
        "--nasa-weather",
        type=Path,
        default=root / "data/processed/climate/nasa_power_daily_precipitation.tsv.gz",
    )
    parser.add_argument(
        "--open-meteo-weather",
        type=Path,
        default=root / "data/processed/climate/daily_weather_canonical.tsv",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=root / "analysis/v3/rain_response_window",
    )
    parser.add_argument("--permutations", type=int, default=DEFAULT_PERMUTATIONS)
    parser.add_argument("--seed", type=int, default=SEED)
    args = parser.parse_args()
    if args.permutations < 99:
        parser.error("--permutations must be at least 99")
    return args


if __name__ == "__main__":
    run(parse_args())
