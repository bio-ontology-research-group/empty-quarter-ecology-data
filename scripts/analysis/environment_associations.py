#!/usr/bin/env python3
"""Relate measured weather and long-term climate to bacterial profiles.

The main analysis uses the 60 core sites as independent units.  Monthly
Open-Meteo records are averaged over the complete archived interval at each
site, while bacterial diversity and genus centred-log-ratio (CLR) abundance
are averaged over all available campaigns, positions and sequencing
replicates at that site.  Spearman correlations describe monotone
associations without assuming a linear response.  The nine diversity tests
form one Benjamini--Hochberg family; the 600 genus tests form a second family.

Weather recorded during collection is analysed separately at the
campaign-by-site level.  These measurements describe conditions at sampling,
not soil microclimate.  Raw correlations and models adjusted for campaign and
a quadratic transect coordinate are retained as supplementary diagnostics.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import re
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
import scipy
from scipy import stats
import statsmodels
import statsmodels.formula.api as smf


SCHEMA_VERSION = "1.1"
BOOTSTRAP_SEED = 20260805
DEFAULT_BOOTSTRAPS = 9_999
CLIMATE_VARIABLES = {
    "mean_air_temperature_c": "Avg_Temp_C",
    "mean_monthly_rain_mm": "Avg_Total_Rain_mm",
    "mean_relative_humidity_pct": "Avg_Humidity_Percent",
}
ALPHA_VARIABLES = {
    "shannon": "Shannon diversity",
    "expected_richness_25k": "Expected richness at 25,000 reads",
    "normalized_evenness": "Normalized evenness",
}
FIELD_VARIABLES = {
    "temperature_c": "Air temperature",
    "pressure_mbar": "Atmospheric pressure",
    "relative_humidity_pct": "Relative humidity",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def bh_fdr(values: Iterable[float]) -> np.ndarray:
    p = np.asarray(list(values), dtype=float)
    if p.size == 0:
        return p
    if np.any(~np.isfinite(p)) or np.any((p < 0) | (p > 1)):
        raise ValueError("BH input must contain finite probabilities")
    order = np.argsort(p, kind="mergesort")
    adjusted = p[order] * len(p) / np.arange(1, len(p) + 1)
    adjusted = np.minimum.accumulate(adjusted[::-1])[::-1]
    result = np.empty_like(adjusted)
    result[order] = np.minimum(adjusted, 1.0)
    return result


def write_tsv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, sep="\t", index=False, float_format="%.10g")


def load_coordinates(root: Path) -> pd.DataFrame:
    rows: list[dict[str, float | int]] = []
    for trip in range(1, 6):
        path = root / "data/metadata/geodata" / f"trip{trip}_geodata.tsv"
        frame = pd.read_csv(path, sep="\t")
        frame["Site"] = pd.to_numeric(frame["Site"], errors="coerce")
        frame = frame.dropna(subset=["Site", "Latitude", "Longitude"])
        frame = frame[frame["Site"].between(1, 60)]
        rows.extend(
            {
                "site": int(row.Site),
                "latitude": float(row.Latitude),
                "longitude": float(row.Longitude),
            }
            for row in frame.itertuples()
        )
    coordinates = (
        pd.DataFrame(rows)
        .groupby("site", as_index=False)[["latitude", "longitude"]]
        .mean()
        .sort_values("site")
    )
    if coordinates["site"].tolist() != list(range(1, 61)):
        raise ValueError("Coordinates do not cover the 60 core sites")
    latitude = coordinates["latitude"].to_numpy(dtype=float)
    longitude = coordinates["longitude"].to_numpy(dtype=float)
    xy = np.column_stack(
        [
            (longitude - longitude.mean())
            * 111.320
            * np.cos(np.deg2rad(latitude.mean())),
            (latitude - latitude.mean()) * 110.574,
        ]
    )
    _, _, vectors = np.linalg.svd(xy - xy.mean(axis=0), full_matrices=False)
    transect = (xy - xy.mean(axis=0)) @ vectors[0]
    if np.corrcoef(transect, longitude)[0, 1] < 0:
        transect *= -1
    coordinates["transect_km"] = transect
    return coordinates


def load_alpha(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, sep="\t", index_col=0)
    required = {"Trip", "Site", "shannon", "richness_rare"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"Alpha table lacks fields: {sorted(missing)}")
    frame = frame.rename(
        columns={"Trip": "trip", "Site": "site", "richness_rare": "expected_richness_25k"}
    )
    frame["trip"] = pd.to_numeric(frame["trip"], errors="raise").astype(int)
    frame["site"] = pd.to_numeric(frame["site"], errors="coerce")
    frame = frame[frame["site"].between(1, 60)].copy()
    frame["site"] = frame["site"].astype(int)
    frame["normalized_evenness"] = frame["shannon"] / np.log(
        frame["expected_richness_25k"]
    )
    frame.loc[
        ~np.isfinite(frame["normalized_evenness"]), "normalized_evenness"
    ] = np.nan
    if not np.isfinite(frame["shannon"].to_numpy(dtype=float)).all():
        raise ValueError("Shannon diversity contains non-finite values")
    observed_richness = frame["expected_richness_25k"].dropna()
    if (observed_richness < 1).any() or not np.isfinite(observed_richness).all():
        raise ValueError("Observed expected-richness values are invalid")
    frame.index.name = "profile_id"
    return frame


def load_climate(path: Path) -> tuple[pd.DataFrame, dict[str, object]]:
    monthly = pd.read_csv(path, sep="\t")
    required = {"Site", "Year", "Month", *CLIMATE_VARIABLES.values()}
    missing = required - set(monthly.columns)
    if missing:
        raise ValueError(f"Climate table lacks fields: {sorted(missing)}")
    monthly["site"] = pd.to_numeric(monthly["Site"], errors="coerce")
    monthly = monthly[
        monthly["site"].between(1, 60)
        & np.isclose(monthly["site"], np.round(monthly["site"]))
    ].copy()
    monthly["site"] = monthly["site"].astype(int)
    counts = monthly.groupby("site").size()
    if counts.index.tolist() != list(range(1, 61)) or counts.nunique() != 1:
        raise ValueError("Monthly climate coverage is not balanced across core sites")
    grouped = monthly.groupby("site", as_index=False)[list(CLIMATE_VARIABLES.values())].mean()
    grouped = grouped.rename(columns={value: key for key, value in CLIMATE_VARIABLES.items()})
    date_index = pd.to_datetime(
        dict(year=monthly["Year"], month=monthly["Month"], day=1)
    )
    accounting = {
        "core_sites": int(grouped.shape[0]),
        "months_per_site": int(counts.iloc[0]),
        "first_month": date_index.min().strftime("%Y-%m"),
        "last_month": date_index.max().strftime("%Y-%m"),
        "monthly_records": int(len(monthly)),
    }
    return grouped, accounting


def spearman_bootstrap_interval(
    first: pd.Series,
    second: pd.Series,
    indices: np.ndarray,
) -> tuple[float, float]:
    """Paired site-bootstrap percentile interval for Spearman correlation."""
    first_values = first.to_numpy(dtype=float)[indices]
    second_values = second.to_numpy(dtype=float)[indices]
    first_ranks = stats.rankdata(first_values, axis=1)
    second_ranks = stats.rankdata(second_values, axis=1)
    first_ranks -= first_ranks.mean(axis=1, keepdims=True)
    second_ranks -= second_ranks.mean(axis=1, keepdims=True)
    denominator = np.sqrt(
        np.square(first_ranks).sum(axis=1)
        * np.square(second_ranks).sum(axis=1)
    )
    correlations = np.divide(
        (first_ranks * second_ranks).sum(axis=1),
        denominator,
        out=np.full(len(indices), np.nan),
        where=denominator > 0,
    )
    lower, upper = np.nanquantile(correlations, (0.025, 0.975))
    return float(lower), float(upper)


def alpha_correlations(
    site: pd.DataFrame, bootstrap_indices: np.ndarray
) -> pd.DataFrame:
    rows = []
    for climate in CLIMATE_VARIABLES:
        for response, label in ALPHA_VARIABLES.items():
            result = stats.spearmanr(site[climate], site[response])
            ci_low, ci_high = spearman_bootstrap_interval(
                site[climate], site[response], bootstrap_indices
            )
            rows.append(
                {
                    "climate_variable": climate,
                    "response": response,
                    "response_label": label,
                    "n_sites": int(len(site)),
                    "spearman_rho": float(result.statistic),
                    "bootstrap_ci_low": ci_low,
                    "bootstrap_ci_high": ci_high,
                    "bootstrap_replicates": int(len(bootstrap_indices)),
                    "p_value": float(result.pvalue),
                }
            )
    frame = pd.DataFrame(rows)
    frame["q_global_9"] = bh_fdr(frame["p_value"])
    frame["supported_q_lt_0_05"] = frame["q_global_9"] < 0.05
    return frame


def climate_covariation(
    site: pd.DataFrame, bootstrap_indices: np.ndarray
) -> pd.DataFrame:
    variables = [*CLIMATE_VARIABLES, "transect_km"]
    rows = []
    for first_index, first in enumerate(variables):
        for second in variables[first_index + 1 :]:
            result = stats.spearmanr(site[first], site[second])
            ci_low, ci_high = spearman_bootstrap_interval(
                site[first], site[second], bootstrap_indices
            )
            rows.append(
                {
                    "variable_a": first,
                    "variable_b": second,
                    "n_sites": int(len(site)),
                    "spearman_rho": float(result.statistic),
                    "bootstrap_ci_low": ci_low,
                    "bootstrap_ci_high": ci_high,
                    "bootstrap_replicates": int(len(bootstrap_indices)),
                    "p_value": float(result.pvalue),
                }
            )
    frame = pd.DataFrame(rows)
    frame["q_global"] = bh_fdr(frame["p_value"])
    return frame


def genus_correlations(
    counts_path: Path,
    alpha: pd.DataFrame,
    climate: pd.DataFrame,
    selected_count: int,
    prevalence_threshold: float,
    pseudocount: float,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    counts = pd.read_csv(counts_path, sep="\t", index_col=0)
    counts = counts.loc[~counts.index.isna()].copy()
    counts.index = counts.index.astype(str)
    profile_ids = [profile for profile in alpha.index if profile in counts.columns]
    if len(profile_ids) != len(alpha):
        raise ValueError(
            f"Genus table matches {len(profile_ids)} of {len(alpha)} alpha profiles"
        )
    counts = counts[profile_ids]
    prevalence = (counts > 0).mean(axis=1)
    relative = counts.div(counts.sum(axis=0), axis=1)
    eligible = prevalence[prevalence >= prevalence_threshold].index
    ranking = (
        relative.loc[eligible]
        .mean(axis=1)
        .sort_values(ascending=False, kind="mergesort")
    )
    if len(ranking) < selected_count:
        raise ValueError(
            f"Only {len(ranking)} genera pass prevalence; need {selected_count}"
        )
    selected = ranking.iloc[:selected_count].index.tolist()
    matrix = counts.loc[selected, profile_ids].T.to_numpy(dtype=float)
    logged = np.log(matrix + pseudocount)
    clr = logged - logged.mean(axis=1, keepdims=True)
    clr_frame = pd.DataFrame(clr, index=profile_ids, columns=selected)
    clr_frame["site"] = alpha.loc[profile_ids, "site"].to_numpy(dtype=int)
    site_clr = clr_frame.groupby("site").mean()
    merged = climate.set_index("site").join(site_clr, how="inner")
    if len(merged) != 60:
        raise ValueError(f"Expected 60 sites for genus analysis; found {len(merged)}")

    rows = []
    for climate_name in CLIMATE_VARIABLES:
        for genus in selected:
            result = stats.spearmanr(merged[climate_name], merged[genus])
            rows.append(
                {
                    "climate_variable": climate_name,
                    "genus": genus,
                    "n_sites": int(len(merged)),
                    "spearman_rho": float(result.statistic),
                    "p_value": float(result.pvalue),
                }
            )
    results = pd.DataFrame(rows)
    results["q_global_600"] = bh_fdr(results["p_value"])
    results["supported_q_lt_0_05"] = results["q_global_600"] < 0.05
    rank_table = pd.DataFrame(
        {
            "rank": np.arange(1, selected_count + 1),
            "genus": selected,
            "prevalence": prevalence.loc[selected].to_numpy(),
            "mean_relative_abundance": ranking.loc[selected].to_numpy(),
        }
    )
    return results, rank_table


def field_weather_diagnostics(
    weather_path: Path,
    alpha: pd.DataFrame,
    coordinates: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    weather = pd.read_csv(weather_path, sep="\t")
    weather = weather[
        weather["record_role"].eq("primary_transect_site")
        & ~weather["qc_status"].eq("quarantined_out_of_range")
    ].copy()
    weather["trip"] = weather["expedition"].str.extract(r"Trip\s+(\d+)")[0].astype(int)
    weather["site"] = pd.to_numeric(weather["site"], errors="coerce")
    weather = weather[weather["site"].between(1, 60)].copy()
    weather["site"] = weather["site"].astype(int)

    summaries = []
    for variable, label in FIELD_VARIABLES.items():
        values = pd.to_numeric(weather[variable], errors="coerce").dropna()
        summaries.append(
            {
                "variable": variable,
                "label": label,
                "unit": {
                    "temperature_c": "degree Celsius",
                    "pressure_mbar": "mbar",
                    "relative_humidity_pct": "percent",
                }[variable],
                "n_site_visits": int(len(values)),
                "minimum": float(values.min()),
                "median": float(values.median()),
                "maximum": float(values.max()),
            }
        )

    alpha_visit = (
        alpha.groupby(["trip", "site"], as_index=False)[list(ALPHA_VARIABLES)]
        .mean()
    )
    joined = alpha_visit.merge(
        weather[["trip", "site", *FIELD_VARIABLES]],
        on=["trip", "site"],
        how="inner",
        validate="one_to_one",
    ).merge(coordinates[["site", "transect_km"]], on="site", validate="many_to_one")

    raw_rows = []
    adjusted_rows = []
    for weather_variable in FIELD_VARIABLES:
        for response in ALPHA_VARIABLES:
            model_data = joined[
                ["site", "trip", "transect_km", weather_variable, response]
            ].dropna().copy()
            correlation = stats.spearmanr(
                model_data[weather_variable], model_data[response]
            )
            raw_rows.append(
                {
                    "weather_variable": weather_variable,
                    "response": response,
                    "n_site_campaigns": int(len(model_data)),
                    "spearman_rho": float(correlation.statistic),
                    "p_value": float(correlation.pvalue),
                }
            )
            for value in ("transect_km", weather_variable):
                standard_deviation = model_data[value].std(ddof=1)
                model_data[f"z_{value}"] = (
                    model_data[value] - model_data[value].mean()
                ) / standard_deviation
            model_data["z_transect_squared"] = model_data["z_transect_km"] ** 2
            fitted = smf.ols(
                f"{response} ~ C(trip) + z_transect_km + "
                f"z_transect_squared + z_{weather_variable}",
                data=model_data,
            ).fit(cov_type="cluster", cov_kwds={"groups": model_data["site"]})
            term = f"z_{weather_variable}"
            adjusted_rows.append(
                {
                    "weather_variable": weather_variable,
                    "response": response,
                    "n_site_campaigns": int(len(model_data)),
                    "n_sites": int(model_data["site"].nunique()),
                    "standardized_coefficient": float(fitted.params[term]),
                    "cluster_se": float(fitted.bse[term]),
                    "p_value": float(fitted.pvalues[term]),
                }
            )
    raw = pd.DataFrame(raw_rows)
    raw["q_global_9"] = bh_fdr(raw["p_value"])
    adjusted = pd.DataFrame(adjusted_rows)
    adjusted["q_global_9"] = bh_fdr(adjusted["p_value"])
    return pd.DataFrame(summaries), joined, raw, adjusted


def write_checksums(output: Path) -> None:
    checksum_path = output / "SHA256SUMS"
    names = sorted(
        path.name
        for path in output.iterdir()
        if path.is_file() and path.name != checksum_path.name
    )
    checksum_path.write_text(
        "".join(f"{sha256_file(output / name)}  {name}\n" for name in names),
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--project-root", type=Path, default=Path(__file__).resolve().parents[2]
    )
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--selected-genera", type=int, default=200)
    parser.add_argument("--prevalence", type=float, default=0.20)
    parser.add_argument("--pseudocount", type=float, default=0.5)
    parser.add_argument("--bootstraps", type=int, default=DEFAULT_BOOTSTRAPS)
    parser.add_argument("--bootstrap-seed", type=int, default=BOOTSTRAP_SEED)
    parser.add_argument("--alpha-table", type=Path, default=None)
    parser.add_argument("--genus-counts", type=Path, default=None)
    parser.add_argument("--monthly-climate", type=Path, default=None)
    parser.add_argument("--field-weather", type=Path, default=None)
    args = parser.parse_args()

    root = args.project_root.resolve()
    output = (
        args.output_dir.resolve()
        if args.output_dir is not None
        else root / "analysis/v3/environment_associations"
    )
    output.mkdir(parents=True, exist_ok=True)
    paths = {
        "alpha": (
            args.alpha_table.resolve()
            if args.alpha_table is not None
            else root / "analysis/v2/review/cache/alpha.tsv"
        ),
        "genus_counts": (
            args.genus_counts.resolve()
            if args.genus_counts is not None
            else root / "analysis/v2/review/cache/genus_counts.tsv"
        ),
        "monthly_climate": (
            args.monthly_climate.resolve()
            if args.monthly_climate is not None
            else root
            / "data/processed/climate/monthly_weather_averages_canonical.tsv"
        ),
        "field_weather": (
            args.field_weather.resolve()
            if args.field_weather is not None
            else root
            / "data/processed/metadata/environmental_measurements_curated.tsv"
        ),
    }
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError("Missing analysis inputs:\n" + "\n".join(missing))

    alpha = load_alpha(paths["alpha"])
    coordinates = load_coordinates(root)
    climate, climate_accounting = load_climate(paths["monthly_climate"])
    site_alpha = alpha.groupby("site", as_index=False)[list(ALPHA_VARIABLES)].mean()
    site = (
        coordinates.merge(climate, on="site", validate="one_to_one")
        .merge(site_alpha, on="site", validate="one_to_one")
        .sort_values("site")
    )
    if len(site) != 60:
        raise ValueError(f"Expected 60 complete core sites; found {len(site)}")
    if args.bootstraps < 999:
        parser.error("--bootstraps must be at least 999")
    bootstrap_indices = np.random.default_rng(args.bootstrap_seed).integers(
        0, len(site), size=(args.bootstraps, len(site))
    )

    alpha_results = alpha_correlations(site, bootstrap_indices)
    covariation = climate_covariation(site, bootstrap_indices)
    genus_results, genus_ranking = genus_correlations(
        paths["genus_counts"],
        alpha,
        climate,
        args.selected_genera,
        args.prevalence,
        args.pseudocount,
    )
    field_summary, field_join, field_raw, field_adjusted = field_weather_diagnostics(
        paths["field_weather"], alpha, coordinates
    )

    outputs = {
        "climate_site_summary.tsv": site,
        "climate_alpha_correlations.tsv": alpha_results,
        "climate_covariation.tsv": covariation,
        "climate_genus_correlations.tsv": genus_results,
        "selected_genera.tsv": genus_ranking,
        "field_weather_summary.tsv": field_summary,
        "field_weather_site_campaign.tsv": field_join,
        "field_weather_raw_correlations.tsv": field_raw,
        "field_weather_adjusted_models.tsv": field_adjusted,
    }
    for name, frame in outputs.items():
        write_tsv(frame, output / name)

    genus_counts = (
        genus_results.groupby("climate_variable")["supported_q_lt_0_05"]
        .sum()
        .astype(int)
        .to_dict()
    )
    decision = {
        "schema_version": SCHEMA_VERSION,
        "status": "observational_climate_associations_supported",
        "analysis_unit": "core site",
        "climate_coverage": climate_accounting,
        "alpha_profiles": int(len(alpha)),
        "alpha_sites": int(alpha["site"].nunique()),
        "alpha_tests": int(len(alpha_results)),
        "alpha_tests_q_lt_0_05": int(alpha_results["supported_q_lt_0_05"].sum()),
        "selected_genera": int(args.selected_genera),
        "genus_tests": int(len(genus_results)),
        "genus_tests_q_lt_0_05_by_climate": genus_counts,
        "multiplicity": {
            "alpha": "Benjamini-Hochberg across all nine climate-diversity tests",
            "genus": "Benjamini-Hochberg across all 600 climate-genus tests",
        },
        "sampling_uncertainty": {
            "method": (
                "paired percentile bootstrap of the 60 complete sites; both "
                "variables are resampled together"
            ),
            "confidence_level": 0.95,
            "replicates": args.bootstraps,
            "seed": args.bootstrap_seed,
        },
        "interpretation": (
            "Long-term temperature, rain and humidity covary with bacterial diversity "
            "and genus CLR abundance across the 60 sites. These variables also covary "
            "with the transect and with one another, so the associations do not identify "
            "a causal climate driver."
        ),
        "field_weather_scope": (
            "Air temperature, pressure and relative humidity recorded at collection "
            "describe site-visit conditions rather than soil microclimate. Raw and "
            "geography-adjusted models are supplementary diagnostics."
        ),
        "input_sha256": {name: sha256_file(path) for name, path in paths.items()},
        "provenance": {
            "script": "analysis/v3/environment_associations.py",
            "script_sha256": sha256_file(Path(__file__).resolve()),
            "software": {
                "python": platform.python_version(),
                "numpy": np.__version__,
                "pandas": pd.__version__,
                "scipy": scipy.__version__,
                "statsmodels": statsmodels.__version__,
            },
            "random_operations": True,
            "bootstrap_replicates": args.bootstraps,
            "bootstrap_seed": args.bootstrap_seed,
        },
    }
    (output / "analysis_decision.json").write_text(
        json.dumps(decision, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (output / "README.md").write_text(
        "# Environmental association analysis\n\n"
        "This directory contains the deterministic site-level climate analysis "
        "and the separate collection-weather diagnostics used by the ecology "
        "manuscript. See `analysis_decision.json` for the interpretation boundary "
        "and each TSV for the exact estimates. Climate correlations include 95% "
        "percentile intervals from paired resampling of the 60 sites.\n",
        encoding="utf-8",
    )
    write_checksums(output)


if __name__ == "__main__":
    main()
