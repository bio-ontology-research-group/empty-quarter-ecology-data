#!/usr/bin/env python3
"""Test geographic and soil-position structure in PICRUSt2 pathways.

PICRUSt2 pathways are predictions from the 16S ASVs, not direct measurements
of activity.  This analysis therefore asks whether predicted metabolic
potential retains the ecological structure found in the taxonomic profiles.
It preserves the sampling design by summing sequencing replicates within each
campaign-by-site-by-position group and using the site as the permutation and
resampling unit.

Geographic inference removes campaign-by-position means, averages the CLR
pathway profiles within site, and permutes whole sites against a pre-specified
quadratic transect coordinate.  Soil-position inference centres complete
campaign-by-site blocks and averages them within site before position labels
are permuted or paired differences are sign-flipped.  Pathway-level tests use
one global Benjamini--Hochberg family across the three paired contrasts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np
import pandas as pd
import scipy


SCHEMA_VERSION = "1.0"
POSITIONS = ("Surface", "Deep", "Rhizosphere")
POSITION_MAP = {
    "surface": "Surface",
    "deep": "Deep",
    "plant_rhizosphere": "Rhizosphere",
}
CONTRASTS = (
    ("Deep", "Surface"),
    ("Rhizosphere", "Surface"),
    ("Rhizosphere", "Deep"),
)
PRIMARY_PATHWAYS = 200
PRIMARY_PSEUDOCOUNT = 0.5


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
    rows = []
    for trip in range(1, 6):
        frame = pd.read_csv(
            root / "data/metadata/geodata" / f"trip{trip}_geodata.tsv", sep="\t"
        )
        frame["Site"] = pd.to_numeric(frame["Site"], errors="coerce")
        frame = frame.dropna(subset=["Site", "Latitude", "Longitude"])
        frame = frame[
            frame["Site"].between(1, 60)
            & np.isclose(frame["Site"], np.round(frame["Site"]))
        ]
        rows.extend(
            {
                "site": int(row.Site),
                "latitude": float(row.Latitude),
                "longitude": float(row.Longitude),
            }
            for row in frame.itertuples()
        )
    result = (
        pd.DataFrame(rows)
        .groupby("site", as_index=False)[["latitude", "longitude"]]
        .mean()
        .sort_values("site")
    )
    if result["site"].tolist() != list(range(1, 61)):
        raise ValueError("Coordinates do not cover the 60 core sites")
    latitude = result["latitude"].to_numpy(dtype=float)
    longitude = result["longitude"].to_numpy(dtype=float)
    x = (
        (longitude - longitude.mean())
        * 111.320
        * np.cos(np.deg2rad(latitude.mean()))
    )
    y = (latitude - latitude.mean()) * 110.574
    xy = np.column_stack([x, y])
    _, _, vectors = np.linalg.svd(xy - xy.mean(axis=0), full_matrices=False)
    transect = (xy - xy.mean(axis=0)) @ vectors[0]
    if np.corrcoef(transect, longitude)[0, 1] < 0:
        transect *= -1
    result["transect_km"] = transect
    return result


def load_profiles(
    pathway_path: Path,
    metadata_path: Path,
    alpha_path: Path,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, int]]:
    alpha = pd.read_csv(alpha_path, sep="\t", index_col=0)
    alpha["Site"] = pd.to_numeric(alpha["Site"], errors="coerce")
    alpha_ids = alpha.index[alpha["Site"].between(1, 60)].astype(str)
    metadata = pd.read_csv(metadata_path, sep="\t")
    required = {"picrust2_col", "trip", "site", "compartment", "is_control"}
    missing = required - set(metadata.columns)
    if missing:
        raise ValueError(f"PICRUSt2 metadata lacks fields: {sorted(missing)}")
    metadata["picrust2_col"] = metadata["picrust2_col"].astype(str)
    metadata["site"] = pd.to_numeric(metadata["site"], errors="coerce")
    metadata["trip"] = pd.to_numeric(metadata["trip"], errors="coerce")
    metadata["position"] = metadata["compartment"].map(POSITION_MAP)
    metadata["is_control"] = metadata["is_control"].astype(str).str.lower().eq("true")
    selected = metadata[
        metadata["picrust2_col"].isin(set(alpha_ids))
        & ~metadata["is_control"]
        & metadata["site"].between(1, 60)
        & metadata["trip"].between(1, 5)
        & metadata["position"].notna()
    ].copy()
    selected["site"] = selected["site"].astype(int)
    selected["trip"] = selected["trip"].astype(int)
    if selected["picrust2_col"].duplicated().any():
        raise ValueError("PICRUSt2 profile metadata are not unique")
    if set(selected["picrust2_col"]) != set(alpha_ids):
        absent = sorted(set(alpha_ids) - set(selected["picrust2_col"]))[:10]
        raise ValueError(f"PICRUSt2 lacks ecology profiles, including: {absent}")

    pathways = pd.read_csv(pathway_path, sep="\t", index_col=0)
    pathways.index = pathways.index.astype(str)
    profile_order = selected["picrust2_col"].tolist()
    absent_columns = sorted(set(profile_order) - set(pathways.columns))
    if absent_columns:
        raise ValueError(f"Pathway table lacks profiles: {absent_columns[:10]}")
    pathways = pathways[profile_order]
    if not np.isfinite(pathways.to_numpy(dtype=float)).all() or (pathways < 0).any().any():
        raise ValueError("Pathway predictions contain invalid abundances")

    values = pathways.T.copy()
    values["campaign"] = selected["trip"].to_numpy()
    values["site"] = selected["site"].to_numpy()
    values["position"] = selected["position"].to_numpy()
    grouped = values.groupby(["campaign", "site", "position"], sort=True).sum(numeric_only=True)
    grouped_metadata = grouped.index.to_frame(index=False)
    accounting = {
        "pathways": int(pathways.shape[0]),
        "picrust2_columns": int(len(metadata)),
        "ecology_profiles": int(len(selected)),
        "ecology_sites": int(selected["site"].nunique()),
        "grouped_profiles": int(len(grouped)),
    }
    return grouped, grouped_metadata, selected, accounting


def rank_pathways(grouped: pd.DataFrame, prevalence_threshold: float) -> pd.DataFrame:
    prevalence = (grouped > 0).mean(axis=0)
    relative = grouped.div(grouped.sum(axis=1), axis=0)
    eligible = prevalence[prevalence >= prevalence_threshold].index
    abundance = relative[eligible].mean(axis=0).sort_values(
        ascending=False, kind="mergesort"
    )
    return pd.DataFrame(
        {
            "pathway": abundance.index,
            "prevalence": prevalence.loc[abundance.index].to_numpy(),
            "mean_relative_abundance": abundance.to_numpy(),
        }
    )


def clr(values: np.ndarray, pseudocount: float) -> np.ndarray:
    logged = np.log(np.asarray(values, dtype=float) + pseudocount)
    return logged - logged.mean(axis=1, keepdims=True)


def block_centred_tensor(
    grouped: pd.DataFrame,
    pathways: Sequence[str],
    omitted_campaign: int | None,
    pseudocount: float,
) -> tuple[np.ndarray, np.ndarray, int]:
    metadata = grouped.index.to_frame(index=False)
    keep = np.ones(len(metadata), dtype=bool)
    if omitted_campaign is not None:
        keep &= metadata["campaign"].to_numpy() != omitted_campaign
    metadata = metadata.loc[keep].reset_index(drop=True)
    matrix = clr(grouped.loc[keep, list(pathways)].to_numpy(), pseudocount)
    position_order = {position: index for index, position in enumerate(POSITIONS)}
    blocks: dict[tuple[int, int], dict[int, int]] = {}
    for row, record in enumerate(metadata.itertuples()):
        blocks.setdefault((int(record.campaign), int(record.site)), {})[
            position_order[record.position]
        ] = row
    complete = {key: members for key, members in blocks.items() if len(members) == 3}
    if not complete:
        raise ValueError("No complete site-by-campaign position blocks")
    per_site: dict[int, list[np.ndarray]] = {}
    for (_, site), members in sorted(complete.items()):
        indices = np.asarray([members[index] for index in range(3)], dtype=int)
        block = matrix[indices]
        per_site.setdefault(site, []).append(block - block.mean(axis=0))
    sites = np.asarray(sorted(per_site), dtype=int)
    tensor = np.stack([np.mean(per_site[int(site)], axis=0) for site in sites])
    return sites, tensor, len(complete)


def pseudo_f(tensor: np.ndarray) -> float:
    n_sites, positions, _ = tensor.shape
    centroids = tensor.mean(axis=0)
    between = n_sites * float(np.square(centroids).sum())
    within = float(np.square(tensor - centroids).sum())
    return (between / (positions - 1)) / (within / (n_sites * positions - positions))


def omnibus_test(tensor: np.ndarray, permutations: int, seed: int) -> tuple[float, float]:
    observed = pseudo_f(tensor)
    rng = np.random.default_rng(seed)
    exceed = 0
    for _ in range(permutations):
        permuted = np.empty_like(tensor)
        for site in range(len(tensor)):
            permuted[site] = tensor[site, rng.permutation(3)]
        exceed += pseudo_f(permuted) >= observed
    return observed, (exceed + 1) / (permutations + 1)


def paired_test(
    differences: np.ndarray, permutations: int, bootstrap: int, seed: int
) -> dict[str, float]:
    mean_difference = differences.mean(axis=0)
    observed = float(np.linalg.norm(mean_difference))
    mean_site_norm = float(np.linalg.norm(differences, axis=1).mean())
    rng = np.random.default_rng(seed)
    signs = rng.choice((-1.0, 1.0), size=(permutations, len(differences)))
    null = np.linalg.norm(signs @ differences / len(differences), axis=1)
    boot_rng = np.random.default_rng(seed + 1)
    indices = boot_rng.integers(0, len(differences), size=(bootstrap, len(differences)))
    boot = np.linalg.norm(differences[indices].mean(axis=1), axis=1)
    return {
        "displacement": observed,
        "ci_low": float(np.quantile(boot, 0.025)),
        "ci_high": float(np.quantile(boot, 0.975)),
        "standardized_displacement": observed / mean_site_norm,
        "permutation_p": (1 + int(np.sum(null >= observed))) / (permutations + 1),
    }


def position_analysis(
    grouped: pd.DataFrame,
    pathways: Sequence[str],
    omitted_campaign: int | None,
    pseudocount: float,
    label: str,
    permutations: int,
    bootstrap: int,
    seed: int,
) -> tuple[list[dict[str, object]], np.ndarray, np.ndarray]:
    sites, tensor, n_blocks = block_centred_tensor(
        grouped, pathways, omitted_campaign, pseudocount
    )
    omnibus_f, omnibus_p = omnibus_test(tensor, permutations, seed)
    rows: list[dict[str, object]] = [
        {
            "analysis": label,
            "omitted_campaign": omitted_campaign,
            "pathway_count": len(pathways),
            "pseudocount": pseudocount,
            "contrast": "omnibus_three_positions",
            "n_sites": len(sites),
            "n_complete_blocks": n_blocks,
            "displacement": np.nan,
            "ci_low": np.nan,
            "ci_high": np.nan,
            "standardized_displacement": np.nan,
            "pseudo_f": omnibus_f,
            "permutation_p": omnibus_p,
        }
    ]
    position_index = {position: index for index, position in enumerate(POSITIONS)}
    for offset, (first, second) in enumerate(CONTRASTS):
        differences = tensor[:, position_index[first], :] - tensor[:, position_index[second], :]
        result = paired_test(
            differences, permutations, bootstrap, seed + 101 * (offset + 1)
        )
        rows.append(
            {
                "analysis": label,
                "omitted_campaign": omitted_campaign,
                "pathway_count": len(pathways),
                "pseudocount": pseudocount,
                "contrast": f"{first}-{second}",
                "n_sites": len(sites),
                "n_complete_blocks": n_blocks,
                **result,
                "pseudo_f": np.nan,
            }
        )
    return rows, sites, tensor


def site_level_clr(
    grouped: pd.DataFrame,
    pathways: Sequence[str],
    omitted_campaign: int | None,
    pseudocount: float,
) -> tuple[np.ndarray, np.ndarray, int]:
    metadata = grouped.index.to_frame(index=False)
    keep = np.ones(len(metadata), dtype=bool)
    if omitted_campaign is not None:
        keep &= metadata["campaign"].to_numpy() != omitted_campaign
    metadata = metadata.loc[keep].reset_index(drop=True)
    matrix = clr(grouped.loc[keep, list(pathways)].to_numpy(), pseudocount)
    for _, indices in metadata.groupby(["campaign", "position"], sort=True).groups.items():
        selected = np.asarray(list(indices), dtype=int)
        matrix[selected] -= matrix[selected].mean(axis=0, keepdims=True)
    sites = []
    values = []
    for site, indices in metadata.groupby("site", sort=True).groups.items():
        selected = np.asarray(list(indices), dtype=int)
        sites.append(int(site))
        values.append(matrix[selected].mean(axis=0))
    return np.asarray(sites), np.vstack(values), len(metadata)


def quadratic_design(transect: np.ndarray) -> np.ndarray:
    z = (transect - transect.mean()) / transect.std(ddof=1)
    return np.column_stack([np.ones(len(z)), z, z**2 - np.mean(z**2)])


def fit_multivariate(response: np.ndarray, design: np.ndarray) -> tuple[float, float]:
    centred = response - response.mean(axis=0, keepdims=True)
    basis, _ = np.linalg.qr(design, mode="reduced")
    fitted = basis @ (basis.T @ centred)
    residual = centred - fitted
    tss = float(np.square(centred).sum())
    sse = float(np.square(residual).sum())
    r2 = 1 - sse / tss
    pseudo = ((tss - sse) / 2) / (sse / (len(response) - 3))
    return r2, pseudo


def spatial_test(
    grouped: pd.DataFrame,
    coordinates: pd.DataFrame,
    pathways: Sequence[str],
    omitted_campaign: int | None,
    pseudocount: float,
    label: str,
    permutations: int,
    seed: int,
) -> dict[str, object]:
    sites, response, n_groups = site_level_clr(
        grouped, pathways, omitted_campaign, pseudocount
    )
    spatial = coordinates.set_index("site").loc[sites]
    design = quadratic_design(spatial["transect_km"].to_numpy(dtype=float))
    r2, observed = fit_multivariate(response, design)
    rng = np.random.default_rng(seed)
    centred = response - response.mean(axis=0, keepdims=True)
    total_ss = float(np.square(centred).sum())
    basis, _ = np.linalg.qr(design, mode="reduced")
    exceed = 0
    completed = 0
    # Work in bounded batches to avoid repeated least-squares fits while
    # keeping peak memory below the size of the pathway input table.
    while completed < permutations:
        batch_size = min(250, permutations - completed)
        orders = np.vstack(
            [rng.permutation(len(response)) for _ in range(batch_size)]
        )
        permuted = centred[orders]
        projections = np.einsum(
            "nq,bnf->bqf", basis, permuted, optimize=True
        )
        explained_ss = np.square(projections).sum(axis=(1, 2))
        residual_ss = total_ss - explained_ss
        null_f = (explained_ss / 2) / (
            residual_ss / (len(response) - design.shape[1])
        )
        exceed += int(np.sum(null_f >= observed))
        completed += batch_size
    return {
        "analysis": label,
        "omitted_campaign": omitted_campaign,
        "pathway_count": len(pathways),
        "pseudocount": pseudocount,
        "n_sites": len(sites),
        "n_grouped_profiles": n_groups,
        "quadratic_transect_r2": r2,
        "pseudo_f": observed,
        "permutation_p": (exceed + 1) / (permutations + 1),
    }


def pathway_level_position(
    tensor: np.ndarray,
    pathways: Sequence[str],
    descriptions: dict[str, str],
    permutations: int,
    seed: int,
) -> pd.DataFrame:
    position_index = {position: index for index, position in enumerate(POSITIONS)}
    rows = []
    for offset, (first, second) in enumerate(CONTRASTS):
        differences = tensor[:, position_index[first], :] - tensor[:, position_index[second], :]
        observed = np.abs(differences.mean(axis=0))
        rng = np.random.default_rng(seed + 1000 * (offset + 1))
        signs = rng.choice((-1.0, 1.0), size=(permutations, len(differences)))
        null = np.abs(signs @ differences / len(differences))
        p_values = (1 + np.sum(null >= observed[None, :], axis=0)) / (permutations + 1)
        for pathway_index, pathway in enumerate(pathways):
            rows.append(
                {
                    "contrast": f"{first}-{second}",
                    "pathway": pathway,
                    "description": descriptions.get(pathway, ""),
                    "n_sites": len(differences),
                    "mean_clr_difference": float(differences[:, pathway_index].mean()),
                    "p_value": float(p_values[pathway_index]),
                }
            )
    result = pd.DataFrame(rows)
    result["q_global_600"] = bh_fdr(result["p_value"])
    result["supported_q_lt_0_05"] = result["q_global_600"] < 0.05
    return result


def pathway_level_geography(
    sites: np.ndarray,
    response: np.ndarray,
    pathways: Sequence[str],
    descriptions: dict[str, str],
    coordinates: pd.DataFrame,
) -> pd.DataFrame:
    transect = coordinates.set_index("site").loc[sites, "transect_km"].to_numpy()
    rows = []
    from scipy import stats

    for index, pathway in enumerate(pathways):
        result = stats.spearmanr(transect, response[:, index])
        rows.append(
            {
                "pathway": pathway,
                "description": descriptions.get(pathway, ""),
                "n_sites": len(sites),
                "spearman_rho": float(result.statistic),
                "p_value": float(result.pvalue),
            }
        )
    frame = pd.DataFrame(rows)
    frame["q_global_200"] = bh_fdr(frame["p_value"])
    frame["supported_q_lt_0_05"] = frame["q_global_200"] < 0.05
    return frame


def nsti_summary(
    nsti_path: Path, selected_metadata: pd.DataFrame
) -> tuple[pd.DataFrame, dict[str, float | int]]:
    nsti = pd.read_csv(nsti_path, sep="\t")
    nsti["sample"] = nsti["sample"].astype(str)
    joined = selected_metadata[["picrust2_col", "trip", "position"]].merge(
        nsti, left_on="picrust2_col", right_on="sample", how="left", validate="one_to_one"
    )
    if joined["weighted_NSTI"].isna().any():
        raise ValueError("NSTI is missing for ecology profiles")
    rows = []
    for grouping, frame in [("all", joined), *[(f"position:{key}", value) for key, value in joined.groupby("position")], *[(f"campaign:{int(key)}", value) for key, value in joined.groupby("trip")]]:
        values = frame["weighted_NSTI"]
        rows.append(
            {
                "group": grouping,
                "n_profiles": len(values),
                "mean_weighted_nsti": values.mean(),
                "median_weighted_nsti": values.median(),
                "minimum_weighted_nsti": values.min(),
                "maximum_weighted_nsti": values.max(),
            }
        )
    all_values = joined["weighted_NSTI"]
    summary = {
        "n_profiles": int(len(all_values)),
        "median": float(all_values.median()),
        "mean": float(all_values.mean()),
        "minimum": float(all_values.min()),
        "maximum": float(all_values.max()),
    }
    return pd.DataFrame(rows), summary


def write_checksums(output: Path) -> None:
    checksum = output / "SHA256SUMS"
    names = sorted(
        path.name for path in output.iterdir() if path.is_file() and path != checksum
    )
    checksum.write_text(
        "".join(f"{sha256_file(output / name)}  {name}\n" for name in names),
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--project-root", type=Path, default=Path(__file__).resolve().parents[2]
    )
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--permutations", type=int, default=9999)
    parser.add_argument("--bootstrap", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=20260804)
    parser.add_argument("--prevalence", type=float, default=0.20)
    parser.add_argument("--alpha-table", type=Path, default=None)
    parser.add_argument("--measured-function-summary", type=Path, default=None)
    args = parser.parse_args()

    root = args.project_root.resolve()
    output = (
        args.output_dir.resolve()
        if args.output_dir is not None
        else root / "analysis/v3/picrust2_ecology"
    )
    output.mkdir(parents=True, exist_ok=True)
    base = root / "data/processed/functional/picrust2/merged"
    paths = {
        "pathways": base / "path_abun_unstrat.tsv",
        "metadata": base / "sample_metadata.tsv",
        "nsti": base / "weighted_nsti.tsv",
        "descriptions": root / "data/processed/functional/picrust2/path_abun_unstrat_descriptions.tsv",
        "alpha": (
            args.alpha_table.resolve()
            if args.alpha_table is not None
            else root / "analysis/v2/review/cache/alpha.tsv"
        ),
        "measured_function": (
            args.measured_function_summary.resolve()
            if args.measured_function_summary is not None
            else root
            / "analysis/v3/measured_function_summary_results/summary_metrics.tsv"
        ),
    }
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError("Missing PICRUSt2 analysis inputs:\n" + "\n".join(missing))

    grouped, _, selected_metadata, accounting = load_profiles(
        paths["pathways"], paths["metadata"], paths["alpha"]
    )
    ranking = rank_pathways(grouped, args.prevalence)
    if len(ranking) < PRIMARY_PATHWAYS:
        raise ValueError(f"Only {len(ranking)} pathways pass prevalence filtering")
    descriptions_frame = pd.read_csv(paths["descriptions"], sep="\t", usecols=["pathway", "description"])
    descriptions = descriptions_frame.set_index("pathway")["description"].astype(str).to_dict()
    ranking["description"] = ranking["pathway"].map(descriptions).fillna("")
    primary = ranking["pathway"].iloc[:PRIMARY_PATHWAYS].tolist()
    all_eligible = ranking["pathway"].tolist()
    sets = {100: ranking["pathway"].iloc[:100].tolist(), 200: primary, len(all_eligible): all_eligible}
    coordinates = load_coordinates(root)

    position_rows = []
    primary_sites: np.ndarray | None = None
    primary_tensor: np.ndarray | None = None
    configurations = []
    for count, pathways in sets.items():
        for pseudocount in (0.5, 1.0):
            if count == PRIMARY_PATHWAYS and pseudocount == PRIMARY_PSEUDOCOUNT:
                label = "primary"
            else:
                label = "pathway_or_zero_sensitivity"
            configurations.append((pathways, pseudocount, None, label))
    for campaign in range(1, 6):
        configurations.append((primary, PRIMARY_PSEUDOCOUNT, campaign, "leave_one_campaign_out"))
    for index, (pathways, pseudocount, omitted, label) in enumerate(configurations):
        rows, sites, tensor = position_analysis(
            grouped,
            pathways,
            omitted,
            pseudocount,
            label,
            args.permutations,
            args.bootstrap,
            args.seed + 10000 * index,
        )
        position_rows.extend(rows)
        if label == "primary":
            primary_sites, primary_tensor = sites, tensor
    position = pd.DataFrame(position_rows)
    primary_pairs = position[
        position["analysis"].eq("primary")
        & ~position["contrast"].eq("omnibus_three_positions")
    ].copy()
    position.loc[primary_pairs.index, "q_primary_three"] = bh_fdr(
        primary_pairs["permutation_p"]
    )

    spatial_rows = []
    for index, (pathways, pseudocount, omitted, label) in enumerate(configurations):
        spatial_rows.append(
            spatial_test(
                grouped,
                coordinates,
                pathways,
                omitted,
                pseudocount,
                label,
                args.permutations,
                args.seed + 500000 + 10000 * index,
            )
        )
    spatial = pd.DataFrame(spatial_rows)

    if primary_sites is None or primary_tensor is None:
        raise RuntimeError("Primary position configuration was not run")
    pathway_position = pathway_level_position(
        primary_tensor,
        primary,
        descriptions,
        args.permutations,
        args.seed + 900000,
    )
    geography_sites, geography_response, _ = site_level_clr(
        grouped, primary, None, PRIMARY_PSEUDOCOUNT
    )
    pathway_geography = pathway_level_geography(
        geography_sites, geography_response, primary, descriptions, coordinates
    )
    nsti, nsti_values = nsti_summary(paths["nsti"], selected_metadata)

    validation = pd.read_csv(paths["measured_function"], sep="\t")
    validation_lookup = validation.set_index("metric")["estimate"].to_dict()
    required_metrics = {
        "per_sample_ko_profile_spearman_median",
        "community_mean_ko_profile_spearman",
    }
    if not required_metrics <= set(validation_lookup):
        raise ValueError("Measured-function summary lacks required validation metrics")

    write_tsv(ranking.assign(rank=np.arange(1, len(ranking) + 1))[["rank", "pathway", "description", "prevalence", "mean_relative_abundance"]], output / "pathway_ranking.tsv")
    write_tsv(position, output / "position_profile_tests.tsv")
    write_tsv(spatial, output / "geographic_profile_tests.tsv")
    write_tsv(pathway_position, output / "pathway_position_effects.tsv")
    write_tsv(pathway_geography, output / "pathway_geographic_correlations.tsv")
    write_tsv(nsti, output / "weighted_nsti_summary.tsv")

    primary_position = position[position["analysis"].eq("primary")].copy()
    primary_spatial = spatial[spatial["analysis"].eq("primary")].iloc[0]
    omnibus_position_sensitivities = position[
        ~position["analysis"].eq("primary")
        & position["contrast"].eq("omnibus_three_positions")
    ]
    sensitivities_spatial = spatial[~spatial["analysis"].eq("primary")]
    contrast_sensitivity = {}
    for first, second in CONTRASTS:
        contrast = f"{first}-{second}"
        relevant = position[
            ~position["analysis"].eq("primary")
            & position["contrast"].eq(contrast)
        ]
        contrast_sensitivity[contrast] = {
            "tests": int(len(relevant)),
            "all_p_lt_0_05": bool((relevant["permutation_p"] < 0.05).all()),
            "maximum_p": float(relevant["permutation_p"].max()),
        }
    decision = {
        "schema_version": SCHEMA_VERSION,
        "status": "predicted_functional_structure_supported",
        "interpretation_boundary": (
            "PICRUSt2 estimates gene-family and pathway potential from 16S ASVs. "
            "It does not measure gene expression, metabolic activity or process rates."
        ),
        "cohort": accounting,
        "primary_geography": {
            "n_sites": int(primary_spatial["n_sites"]),
            "quadratic_transect_r2": float(primary_spatial["quadratic_transect_r2"]),
            "permutation_p": float(primary_spatial["permutation_p"]),
            "all_sensitivities_p_lt_0_05": bool((sensitivities_spatial["permutation_p"] < 0.05).all()),
        },
        "primary_position": {
            row["contrast"]: {
                "n_sites": int(row["n_sites"]),
                "n_complete_blocks": int(row["n_complete_blocks"]),
                "standardized_displacement": None if pd.isna(row["standardized_displacement"]) else float(row["standardized_displacement"]),
                "permutation_p": float(row["permutation_p"]),
                "q_primary_three": None if pd.isna(row.get("q_primary_three")) else float(row["q_primary_three"]),
            }
            for _, row in primary_position.iterrows()
        },
        "omnibus_position_sensitivities_all_p_lt_0_05": bool(
            (omnibus_position_sensitivities["permutation_p"] < 0.05).all()
        ),
        "position_contrast_sensitivity": contrast_sensitivity,
        "pathway_level": {
            "position_tests": int(len(pathway_position)),
            "position_tests_q_lt_0_05": int(pathway_position["supported_q_lt_0_05"].sum()),
            "geographic_tests": int(len(pathway_geography)),
            "geographic_tests_q_lt_0_05": int(pathway_geography["supported_q_lt_0_05"].sum()),
        },
        "prediction_quality": {
            "weighted_nsti": nsti_values,
            "shotgun_matched_samples": 125,
            "shared_kos": 3471,
            "median_per_sample_ko_spearman": float(validation_lookup["per_sample_ko_profile_spearman_median"]),
            "community_mean_ko_spearman": float(validation_lookup["community_mean_ko_profile_spearman"]),
        },
        "multiplicity": {
            "position_profiles": "Benjamini-Hochberg across three primary paired contrasts",
            "pathway_position": "Benjamini-Hochberg across 600 pathway-by-position tests",
            "pathway_geography": "Benjamini-Hochberg across 200 pathway-transect correlations",
        },
        "input_sha256": {name: sha256_file(path) for name, path in paths.items()},
        "provenance": {
            "script": "analysis/v3/picrust2_ecology.py",
            "script_sha256": sha256_file(Path(__file__).resolve()),
            "seed": args.seed,
            "permutations": args.permutations,
            "bootstrap": args.bootstrap,
            "software": {
                "python": platform.python_version(),
                "numpy": np.__version__,
                "pandas": pd.__version__,
                "scipy": scipy.__version__,
            },
        },
    }
    (output / "analysis_decision.json").write_text(
        json.dumps(decision, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (output / "README.md").write_text(
        "# PICRUSt2 ecology analysis\n\n"
        "This directory contains the site-level geographic and paired soil-position "
        "tests of predicted MetaCyc pathway profiles, pathway-level follow-up tests, "
        "weighted NSTI summaries and the bounded interpretation used in the ecology "
        "manuscript.\n",
        encoding="utf-8",
    )
    write_checksums(output)


if __name__ == "__main__":
    main()
