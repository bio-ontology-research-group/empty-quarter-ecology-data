#!/usr/bin/env python3
"""Paired, compositional test of surface/shallow/root-adjacent composition.

The retired one-way PERMANOVA and PERMDISP analyses treated sequencing
profiles as independent rows and could not separate a centroid shift from a
dispersion difference.  This replacement keeps the pairing that the sampling
design actually has:

1. sequencing replicates are summed within campaign x site x position;
2. a documented zero treatment and centred log ratio put the profiles in
   Aitchison geometry;
3. every campaign x site block is centred on its own mean, which removes the
   campaign, site and campaign-by-site additive effects while preserving the
   within-block position contrast;
4. block-centred vectors are averaged within site, so the site is the
   independent permutation and resampling unit; and
5. position labels are permuted within site for the omnibus test and paired
   difference vectors are sign-flipped for the pairwise contrasts.

Multivariate location and dispersion are reported separately: the location
statistic is the paired centroid displacement in Aitchison units, and the
dispersion diagnostic compares within-position spread after campaign-by-
position centring.  A compartment-composition difference is called supported
only when its direction and location result survive the taxon-set,
zero-treatment and leave-one-campaign sensitivities.

The analysis never identifies a mechanism.  Plant identity, root activity,
root distance and local moisture were not measured, so a retained compartment
effect must not be described as a plant selective filter.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd


SCHEMA_VERSION = "1.0"
POSITIONS = ("Surface", "Deep", "Rhizosphere")
POSITION_LABELS = {
    "Surface": "surface",
    "Deep": "shallow subsurface",
    "Rhizosphere": "root-adjacent",
}
CONTRASTS = (
    ("Deep", "Surface"),
    ("Rhizosphere", "Surface"),
    ("Rhizosphere", "Deep"),
)
ZERO_TREATMENTS = ("pseudocount_0.5", "pseudocount_1.0", "multiplicative_0.65")
PRIMARY_ZERO_TREATMENT = "pseudocount_0.5"
PRIMARY_TAXON_COUNT = 200
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
class LocationResult:
    analysis: str
    contrast: str
    omitted_campaign: int | None
    taxon_count: int
    zero_treatment: str
    n_sites: int
    n_blocks: int
    displacement: float
    displacement_ci_low: float
    displacement_ci_high: float
    standardized_displacement: float
    pseudo_f: float
    permutation_p: float
    direction_cosine_vs_primary: float


@dataclass(frozen=True)
class DispersionResult:
    analysis: str
    contrast: str
    omitted_campaign: int | None
    taxon_count: int
    zero_treatment: str
    n_sites: int
    mean_dispersion_first: float
    mean_dispersion_second: float
    dispersion_difference: float
    difference_ci_low: float
    difference_ci_high: float
    permutation_p: float


def sample_metadata(sample_id: str) -> dict[str, Any] | None:
    """Return the campaign, site and position encoded by a profile ID."""
    match = SAMPLE_RE.match(str(sample_id).replace(" ", ""))
    if match is None:
        return None
    prefix = match.group("prefix") or ""
    return {
        "sample_id": sample_id,
        "campaign": PREFIX_CAMPAIGN[prefix],
        "site": int(match.group("site")),
        "position": CODE_COMPARTMENT[match.group("compartment")],
    }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def provenance_path(path: Path, root: Path) -> str:
    """Return a stable project-relative path without resolving symlinks."""
    candidate = path if path.is_absolute() else root / path
    try:
        return candidate.absolute().relative_to(root.absolute()).as_posix()
    except ValueError:
        return candidate.absolute().as_posix()


def write_tsv(
    path: Path,
    rows: Iterable[Mapping[str, Any]],
    columns: Sequence[str],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
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
                if value is None:
                    formatted[column] = ""
                elif isinstance(value, bool):
                    formatted[column] = "true" if value else "false"
                elif isinstance(value, float):
                    formatted[column] = (
                        f"{value:.10g}" if math.isfinite(value) else ""
                    )
                else:
                    formatted[column] = value
            writer.writerow(formatted)


def bh_fdr(values: Sequence[float]) -> np.ndarray:
    array = np.asarray(list(values), dtype=float)
    if array.size == 0:
        return array
    order = np.argsort(array)
    ranked = array[order] * array.size / (np.arange(array.size) + 1)
    ranked = np.minimum.accumulate(ranked[::-1])[::-1]
    adjusted = np.empty(array.size)
    adjusted[order] = np.clip(ranked, 0, 1)
    return adjusted


def load_grouped_counts(
    path: Path,
    minimum_group_reads: int,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Sum sequencing replicates within campaign x site x position."""
    genus = pd.read_csv(path, sep="\t", index_col=0)
    genus = genus.loc[~genus.index.isna()].copy()
    genus.index = genus.index.astype(str)
    parsed = [
        value
        for sample_id in genus.columns
        if (value := sample_metadata(sample_id)) is not None
    ]
    metadata = pd.DataFrame(parsed)
    metadata = metadata[
        metadata["site"].between(1, 60)
        & metadata["campaign"].between(1, 5)
        & metadata["position"].isin(POSITIONS)
    ].copy()
    values = genus[metadata["sample_id"].tolist()].T
    values["campaign"] = metadata["campaign"].to_numpy()
    values["site"] = metadata["site"].to_numpy()
    values["position"] = metadata["position"].to_numpy()
    profile_counts = (
        values.groupby(["campaign", "site", "position"], sort=True)
        .size()
        .rename("n_profiles")
    )
    grouped = values.groupby(
        ["campaign", "site", "position"], sort=True
    ).sum(numeric_only=True)
    library_size = grouped.sum(axis=1)
    retained = library_size >= minimum_group_reads
    group_metadata = grouped.index.to_frame(index=False)
    group_metadata["group_reads"] = library_size.to_numpy()
    group_metadata["n_profiles"] = profile_counts.reindex(
        grouped.index
    ).to_numpy()
    group_metadata["retained"] = retained.to_numpy()
    counts = grouped.loc[retained.to_numpy()]
    info = {
        "input_genera": int(genus.shape[0]),
        "input_profile_columns": int(genus.shape[1]),
        "parsed_core_profile_columns": int(len(metadata)),
        "campaign_site_position_groups": int(len(group_metadata)),
        "retained_groups": int(counts.shape[0]),
        "excluded_low_read_groups": int((~retained).sum()),
        "minimum_group_reads": int(minimum_group_reads),
        "retained_sites": int(
            group_metadata.loc[retained.to_numpy(), "site"].nunique()
        ),
    }
    return counts, group_metadata, info


def rank_taxa(counts: pd.DataFrame, prevalence_threshold: float) -> list[str]:
    """Rank prevalent genera by mean relative abundance across groups."""
    prevalence = (counts > 0).mean(axis=0)
    relative = counts.div(counts.sum(axis=1), axis=0)
    eligible = prevalence[prevalence >= prevalence_threshold].index
    ranking = (
        relative[eligible]
        .mean(axis=0)
        .sort_values(ascending=False, kind="mergesort")
    )
    return ranking.index.tolist()


def clr_matrix(counts: np.ndarray, zero_treatment: str) -> np.ndarray:
    """Apply the declared zero treatment, then the centred log ratio."""
    matrix = np.asarray(counts, dtype=float)
    if zero_treatment.startswith("pseudocount_"):
        parts = matrix + float(zero_treatment.split("_", 1)[1])
    elif zero_treatment == "multiplicative_0.65":
        totals = matrix.sum(axis=1, keepdims=True)
        if not np.all(totals > 0):
            raise ValueError("Empty composition in multiplicative replacement")
        proportions = matrix / totals
        zeros = matrix <= 0
        # 0.65 x the row detection limit, then closure on the observed part.
        replacement = np.broadcast_to(0.65 / totals, proportions.shape)
        replaced_mass = np.where(zeros, replacement, 0.0).sum(
            axis=1, keepdims=True
        )
        parts = np.where(
            zeros, replacement, proportions * (1.0 - replaced_mass)
        )
    else:
        raise ValueError(f"Unknown zero treatment: {zero_treatment}")
    logged = np.log(parts)
    return logged - logged.mean(axis=1, keepdims=True)


def block_centred_site_tensor(
    counts: pd.DataFrame,
    taxa: Sequence[str],
    positions: Sequence[str],
    zero_treatment: str,
    omitted_campaign: int | None,
) -> tuple[np.ndarray, np.ndarray, int]:
    """Return (sites, tensor[n_sites, k, p], n_blocks) for a matched cohort.

    Every campaign x site block must contain each requested position exactly
    once.  Blocks are centred on their own mean and then averaged within site.
    """
    index = counts.index.to_frame(index=False)
    keep = index["position"].isin(positions)
    if omitted_campaign is not None:
        keep &= index["campaign"] != omitted_campaign
    index = index.loc[keep].reset_index(drop=True)
    matrix = clr_matrix(
        counts.loc[keep.to_numpy(), list(taxa)].to_numpy(), zero_treatment
    )
    order = {position: rank for rank, position in enumerate(positions)}
    blocks: dict[tuple[int, int], dict[int, int]] = {}
    for row, record in enumerate(index.itertuples()):
        blocks.setdefault((record.campaign, record.site), {})[
            order[record.position]
        ] = row
    complete = {
        key: value
        for key, value in blocks.items()
        if len(value) == len(positions)
    }
    if not complete:
        raise ValueError("No campaign x site block contains every position")
    per_site: dict[int, list[np.ndarray]] = {}
    for (_, site), members in sorted(complete.items()):
        rows = np.array(
            [members[rank] for rank in range(len(positions))], dtype=int
        )
        block = matrix[rows]
        per_site.setdefault(site, []).append(block - block.mean(axis=0))
    sites = np.array(sorted(per_site), dtype=int)
    tensor = np.stack(
        [np.mean(per_site[int(site)], axis=0) for site in sites]
    )
    return sites, tensor, len(complete)


def pseudo_f(tensor: np.ndarray) -> float:
    """Between-position over within-position variance on block-centred data."""
    n_sites, k, _ = tensor.shape
    centroids = tensor.mean(axis=0)
    ss_between = n_sites * float(np.square(centroids).sum())
    ss_within = float(np.square(tensor - centroids).sum())
    if ss_within <= 0:
        raise ValueError("Degenerate compartment model: zero residual variance")
    return (ss_between / (k - 1)) / (ss_within / (n_sites * k - k))


def omnibus_permutation_p(
    tensor: np.ndarray,
    permutations: int,
    seed: int,
) -> tuple[float, float]:
    """Permute position labels within site; the site is the exchangeable unit."""
    observed = pseudo_f(tensor)
    rng = np.random.default_rng(seed)
    n_sites, k, _ = tensor.shape
    exceed = 0
    for _ in range(permutations):
        permuted = np.empty_like(tensor)
        for site in range(n_sites):
            permuted[site] = tensor[site, rng.permutation(k)]
        exceed += pseudo_f(permuted) >= observed
    return observed, (exceed + 1) / (permutations + 1)


def paired_location(
    tensor: np.ndarray,
    permutations: int,
    bootstrap: int,
    seed: int,
) -> dict[str, float]:
    """Sign-flip test and site bootstrap for one paired position contrast."""
    differences = tensor[:, 0, :] - tensor[:, 1, :]
    mean_difference = differences.mean(axis=0)
    displacement = float(np.linalg.norm(mean_difference))
    per_site_norm = float(np.linalg.norm(differences, axis=1).mean())
    rng = np.random.default_rng(seed)
    n_sites = differences.shape[0]
    signs = rng.choice((-1.0, 1.0), size=(permutations, n_sites))
    null = np.linalg.norm(signs @ differences / n_sites, axis=1)
    permutation_p = (1 + int(np.sum(null >= displacement))) / (
        permutations + 1
    )
    boot_rng = np.random.default_rng(seed + 1)
    indices = boot_rng.integers(0, n_sites, size=(bootstrap, n_sites))
    boot = np.linalg.norm(differences[indices].mean(axis=1), axis=1)
    return {
        "displacement": displacement,
        "displacement_ci_low": float(np.quantile(boot, 0.025)),
        "displacement_ci_high": float(np.quantile(boot, 0.975)),
        "standardized_displacement": (
            displacement / per_site_norm if per_site_norm > 0 else math.nan
        ),
        "permutation_p": permutation_p,
        "mean_difference": mean_difference,
    }


def dispersion_tensor(
    counts: pd.DataFrame,
    taxa: Sequence[str],
    positions: Sequence[str],
    zero_treatment: str,
    omitted_campaign: int | None,
) -> tuple[np.ndarray, np.ndarray]:
    """Per site x position mean Aitchison distance to the position centroid.

    Campaign-by-position centring removes the location contrast, so the
    remaining spread is a dispersion diagnostic rather than a second location
    test.
    """
    index = counts.index.to_frame(index=False)
    keep = index["position"].isin(positions)
    if omitted_campaign is not None:
        keep &= index["campaign"] != omitted_campaign
    index = index.loc[keep].reset_index(drop=True)
    matrix = clr_matrix(
        counts.loc[keep.to_numpy(), list(taxa)].to_numpy(), zero_treatment
    )
    for _, rows in index.groupby(["campaign", "position"], sort=True).groups.items():
        selected = np.asarray(list(rows), dtype=int)
        matrix[selected] -= matrix[selected].mean(axis=0, keepdims=True)
    index["distance"] = np.linalg.norm(matrix, axis=1)
    wide = index.pivot_table(
        index="site",
        columns="position",
        values="distance",
        aggfunc="mean",
    )
    wide = wide.dropna(subset=list(positions))
    sites = wide.index.to_numpy(dtype=int)
    return sites, wide[list(positions)].to_numpy(dtype=float)


def paired_dispersion(
    values: np.ndarray,
    permutations: int,
    bootstrap: int,
    seed: int,
) -> dict[str, float]:
    differences = values[:, 0] - values[:, 1]
    observed = float(np.abs(differences.mean()))
    rng = np.random.default_rng(seed)
    signs = rng.choice((-1.0, 1.0), size=(permutations, len(differences)))
    null = np.abs(signs @ differences / len(differences))
    permutation_p = (1 + int(np.sum(null >= observed))) / (permutations + 1)
    boot_rng = np.random.default_rng(seed + 1)
    indices = boot_rng.integers(
        0, len(differences), size=(bootstrap, len(differences))
    )
    boot = differences[indices].mean(axis=1)
    return {
        "mean_dispersion_first": float(values[:, 0].mean()),
        "mean_dispersion_second": float(values[:, 1].mean()),
        "dispersion_difference": float(differences.mean()),
        "difference_ci_low": float(np.quantile(boot, 0.025)),
        "difference_ci_high": float(np.quantile(boot, 0.975)),
        "permutation_p": permutation_p,
    }


def run_configuration(
    counts: pd.DataFrame,
    taxa: Sequence[str],
    zero_treatment: str,
    omitted_campaign: int | None,
    analysis: str,
    permutations: int,
    bootstrap: int,
    seed: int,
    primary_directions: dict[str, np.ndarray] | None,
) -> tuple[
    list[LocationResult], list[DispersionResult], dict[str, np.ndarray]
]:
    location: list[LocationResult] = []
    dispersion: list[DispersionResult] = []
    directions: dict[str, np.ndarray] = {}

    sites, tensor, n_blocks = block_centred_site_tensor(
        counts, taxa, POSITIONS, zero_treatment, omitted_campaign
    )
    observed_f, omnibus_p = omnibus_permutation_p(
        tensor, permutations, seed
    )
    location.append(
        LocationResult(
            analysis=analysis,
            contrast="omnibus_three_positions",
            omitted_campaign=omitted_campaign,
            taxon_count=len(taxa),
            zero_treatment=zero_treatment,
            n_sites=len(sites),
            n_blocks=n_blocks,
            displacement=float(
                np.linalg.norm(tensor.mean(axis=0), axis=1).mean()
            ),
            displacement_ci_low=math.nan,
            displacement_ci_high=math.nan,
            standardized_displacement=math.nan,
            pseudo_f=observed_f,
            permutation_p=omnibus_p,
            direction_cosine_vs_primary=math.nan,
        )
    )

    for offset, (first, second) in enumerate(CONTRASTS):
        contrast = f"{first}-{second}"
        pair_sites, pair_tensor, pair_blocks = block_centred_site_tensor(
            counts, taxa, (first, second), zero_treatment, omitted_campaign
        )
        result = paired_location(
            pair_tensor,
            permutations,
            bootstrap,
            seed + 101 * (offset + 1),
        )
        direction = result.pop("mean_difference")
        directions[contrast] = direction
        if primary_directions is None:
            cosine = 1.0
        else:
            reference = primary_directions[contrast]
            shared = min(len(reference), len(direction))
            denominator = float(
                np.linalg.norm(reference[:shared])
                * np.linalg.norm(direction[:shared])
            )
            cosine = (
                float(np.dot(reference[:shared], direction[:shared]))
                / denominator
                if denominator > 0
                else math.nan
            )
        location.append(
            LocationResult(
                analysis=analysis,
                contrast=contrast,
                omitted_campaign=omitted_campaign,
                taxon_count=len(taxa),
                zero_treatment=zero_treatment,
                n_sites=len(pair_sites),
                n_blocks=pair_blocks,
                displacement=result["displacement"],
                displacement_ci_low=result["displacement_ci_low"],
                displacement_ci_high=result["displacement_ci_high"],
                standardized_displacement=result[
                    "standardized_displacement"
                ],
                pseudo_f=pseudo_f(pair_tensor),
                permutation_p=result["permutation_p"],
                direction_cosine_vs_primary=cosine,
            )
        )
        dispersion_sites, values = dispersion_tensor(
            counts, taxa, (first, second), zero_treatment, omitted_campaign
        )
        spread = paired_dispersion(
            values,
            permutations,
            bootstrap,
            seed + 211 * (offset + 1),
        )
        dispersion.append(
            DispersionResult(
                analysis=analysis,
                contrast=contrast,
                omitted_campaign=omitted_campaign,
                taxon_count=len(taxa),
                zero_treatment=zero_treatment,
                n_sites=len(dispersion_sites),
                **spread,
            )
        )
    return location, dispersion, directions


def decision(
    location: Sequence[LocationResult],
    dispersion: Sequence[DispersionResult],
    location_q: Mapping[tuple[str, str], float],
) -> dict[str, Any]:
    def primary(contrast: str) -> LocationResult:
        return next(
            item
            for item in location
            if item.analysis == "primary"
            and item.contrast == contrast
            and item.taxon_count == PRIMARY_TAXON_COUNT
            and item.zero_treatment == PRIMARY_ZERO_TREATMENT
        )

    omnibus = primary("omnibus_three_positions")
    contrasts: dict[str, Any] = {}
    for first, second in CONTRASTS:
        contrast = f"{first}-{second}"
        base = primary(contrast)
        related = [
            item
            for item in location
            if item.contrast == contrast and item is not base
        ]
        sensitivities = [
            item for item in related if item.analysis == "taxon_or_zero_sensitivity"
        ]
        loco = [
            item
            for item in related
            if item.analysis == "leave_one_campaign_out"
        ]
        primary_q = location_q[("primary", contrast)]
        supported = primary_q < 0.05
        sensitivity_supported = all(
            item.permutation_p < 0.05 for item in sensitivities
        )
        loco_supported = bool(loco) and all(
            item.permutation_p < 0.05 for item in loco
        )
        direction_stable = all(
            item.direction_cosine_vs_primary > 0
            for item in sensitivities + loco
            if math.isfinite(item.direction_cosine_vs_primary)
        )
        spread = next(
            item
            for item in dispersion
            if item.analysis == "primary"
            and item.contrast == contrast
            and item.taxon_count == PRIMARY_TAXON_COUNT
            and item.zero_treatment == PRIMARY_ZERO_TREATMENT
        )
        dispersion_differs = not (
            spread.difference_ci_low <= 0 <= spread.difference_ci_high
        )
        if (
            supported
            and sensitivity_supported
            and loco_supported
            and direction_stable
        ):
            status = "supported"
        elif supported:
            status = "model_dependent"
        else:
            status = "not_supported"
        contrasts[contrast] = {
            "label": (
                f"{POSITION_LABELS[first]} versus {POSITION_LABELS[second]}"
            ),
            "status": status,
            "n_sites": base.n_sites,
            "n_blocks": base.n_blocks,
            "centroid_displacement": base.displacement,
            "centroid_displacement_ci": [
                base.displacement_ci_low,
                base.displacement_ci_high,
            ],
            "standardized_displacement": base.standardized_displacement,
            "permutation_p": base.permutation_p,
            "q_within_primary_family": primary_q,
            "taxon_and_zero_sensitivities_supported": sensitivity_supported,
            "leave_one_campaign_supported": loco_supported,
            "direction_stable": direction_stable,
            "dispersion_difference": spread.dispersion_difference,
            "dispersion_difference_ci": [
                spread.difference_ci_low,
                spread.difference_ci_high,
            ],
            "dispersion_differs": dispersion_differs,
        }

    statuses = {value["status"] for value in contrasts.values()}
    if statuses == {"supported"}:
        status = "compartment_composition_supported"
    elif "supported" in statuses:
        status = "compartment_composition_partly_supported"
    elif "model_dependent" in statuses:
        status = "compartment_composition_model_dependent"
    else:
        status = "not_supported"
    supported_labels = [
        value["label"]
        for value in contrasts.values()
        if value["status"] == "supported"
    ]
    dependent_labels = [
        value["label"]
        for value in contrasts.values()
        if value["status"] == "model_dependent"
    ]
    absent_labels = [
        value["label"]
        for value in contrasts.values()
        if value["status"] == "not_supported"
    ]
    dispersion_labels = [
        value["label"]
        for value in contrasts.values()
        if value["status"] != "not_supported" and value["dispersion_differs"]
    ]
    sentences = []
    if supported_labels:
        sentences.append(
            "Paired compositional comparisons with the site as the "
            "permutation unit supported a multivariate location difference "
            "for " + "; ".join(supported_labels) + ", and the direction and "
            "location result persisted across taxon-set, zero-treatment and "
            "leave-one-campaign fits."
        )
    if dispersion_labels:
        sentences.append(
            "Within-position dispersion also differed for "
            + "; ".join(dispersion_labels)
            + ", so the compartments differ in spread as well as in location; "
            "the location result itself is a paired sign-flip test of the "
            "mean within-block difference vector and is exact under the "
            "paired-symmetry null irrespective of that dispersion "
            "heterogeneity."
        )
    if dependent_labels:
        sentences.append(
            "Support for " + "; ".join(dependent_labels) + " depended on "
            "taxon count, zero treatment or a single campaign, so it is "
            "reported as model-dependent and no general compartment-"
            "composition claim is made for it."
        )
    if absent_labels:
        sentences.append(
            "No compositional location difference was supported for "
            + "; ".join(absent_labels)
            + "."
        )
    sentences.append(
        "A retained compartment effect describes composition only. Plant "
        "identity, root activity, root distance and local moisture were not "
        "measured, so it must not be interpreted as a plant selective filter."
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "permitted_wording": " ".join(sentences),
        "prohibited_wording": (
            "Do not describe any compartment difference as a plant selective "
            "filter, rhizosphere effect mechanism, or moisture-driven "
            "selection; none of those variables were measured."
        ),
        "omnibus": {
            "n_sites": omnibus.n_sites,
            "n_blocks": omnibus.n_blocks,
            "pseudo_f": omnibus.pseudo_f,
            "permutation_p": omnibus.permutation_p,
            "caveat": (
                "The omnibus statistic permutes position labels within site "
                "and, like any pseudo-F, responds to both location and "
                "dispersion. Interpretation relies on the paired sign-flip "
                "location tests and the dispersion diagnostics reported "
                "separately below."
            ),
        },
        "location_test_dispersion_note": (
            "Each pairwise location test sign-flips the mean within-block "
            "difference vector across sites. It is exact under the "
            "paired-symmetry null even when within-position dispersion "
            "differs, so a dispersion difference does not by itself create a "
            "location result."
        ),
        "contrasts": contrasts,
        "multiplicity_family": (
            "The three primary pairwise position contrasts form one "
            "Benjamini-Hochberg family. Dispersion diagnostics are corrected "
            "in their own declared family and are not location tests."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
    )
    parser.add_argument("--counts", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--minimum-group-reads", type=int, default=2000)
    parser.add_argument("--prevalence", type=float, default=0.20)
    parser.add_argument("--permutations", type=int, default=999)
    parser.add_argument("--bootstrap", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=20260725)
    args = parser.parse_args()

    root = args.project_root.resolve()
    counts_path = (
        args.counts
        or root / "analysis" / "v2" / "review" / "cache" / "genus_counts.tsv"
    )
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)

    counts, group_metadata, input_info = load_grouped_counts(
        counts_path, args.minimum_group_reads
    )
    ranked = rank_taxa(counts, args.prevalence)
    if len(ranked) < PRIMARY_TAXON_COUNT:
        raise ValueError(
            f"At least {PRIMARY_TAXON_COUNT} eligible genera are required; "
            f"found {len(ranked)}"
        )
    taxon_sets = {
        80: ranked[:80],
        PRIMARY_TAXON_COUNT: ranked[:PRIMARY_TAXON_COUNT],
        len(ranked): ranked,
    }

    location: list[LocationResult] = []
    dispersion: list[DispersionResult] = []
    primary_location, primary_dispersion, primary_directions = (
        run_configuration(
            counts,
            taxon_sets[PRIMARY_TAXON_COUNT],
            PRIMARY_ZERO_TREATMENT,
            omitted_campaign=None,
            analysis="primary",
            permutations=args.permutations,
            bootstrap=args.bootstrap,
            seed=args.seed,
            primary_directions=None,
        )
    )
    location.extend(primary_location)
    dispersion.extend(primary_dispersion)

    for offset, (taxon_count, zero_treatment) in enumerate(
        itertools.product(sorted(taxon_sets), ZERO_TREATMENTS)
    ):
        if (
            taxon_count == PRIMARY_TAXON_COUNT
            and zero_treatment == PRIMARY_ZERO_TREATMENT
        ):
            continue
        extra_location, extra_dispersion, _ = run_configuration(
            counts,
            taxon_sets[taxon_count],
            zero_treatment,
            omitted_campaign=None,
            analysis="taxon_or_zero_sensitivity",
            permutations=args.permutations,
            bootstrap=args.bootstrap,
            seed=args.seed + 1000 * (offset + 1),
            primary_directions=primary_directions,
        )
        location.extend(extra_location)
        dispersion.extend(extra_dispersion)

    for campaign in range(1, 6):
        loco_location, loco_dispersion, _ = run_configuration(
            counts,
            taxon_sets[PRIMARY_TAXON_COUNT],
            PRIMARY_ZERO_TREATMENT,
            omitted_campaign=campaign,
            analysis="leave_one_campaign_out",
            permutations=args.permutations,
            bootstrap=args.bootstrap,
            seed=args.seed + 90000 + campaign,
            primary_directions=primary_directions,
        )
        location.extend(loco_location)
        dispersion.extend(loco_dispersion)

    location_rows = [item.__dict__.copy() for item in location]
    pairwise_primary = [
        row
        for row in location_rows
        if row["analysis"] == "primary"
        and row["contrast"] != "omnibus_three_positions"
    ]
    q_values = bh_fdr([row["permutation_p"] for row in pairwise_primary])
    location_q: dict[tuple[str, str], float] = {}
    for row, q_value in zip(pairwise_primary, q_values):
        row["q_primary_family"] = float(q_value)
        location_q[("primary", row["contrast"])] = float(q_value)
    for row in location_rows:
        row.setdefault("q_primary_family", None)

    dispersion_rows = [item.__dict__.copy() for item in dispersion]
    primary_spread = [
        row for row in dispersion_rows if row["analysis"] == "primary"
    ]
    spread_q = bh_fdr([row["permutation_p"] for row in primary_spread])
    for row, q_value in zip(primary_spread, spread_q):
        row["q_primary_family"] = float(q_value)
    for row in dispersion_rows:
        row.setdefault("q_primary_family", None)

    write_tsv(
        output / "cohort_accounting.tsv",
        group_metadata.to_dict(orient="records"),
        [
            "campaign",
            "site",
            "position",
            "n_profiles",
            "group_reads",
            "retained",
        ],
    )
    write_tsv(
        output / "compartment_location_results.tsv",
        location_rows,
        [
            "analysis",
            "contrast",
            "omitted_campaign",
            "taxon_count",
            "zero_treatment",
            "n_sites",
            "n_blocks",
            "displacement",
            "displacement_ci_low",
            "displacement_ci_high",
            "standardized_displacement",
            "pseudo_f",
            "permutation_p",
            "q_primary_family",
            "direction_cosine_vs_primary",
        ],
    )
    write_tsv(
        output / "compartment_dispersion_results.tsv",
        dispersion_rows,
        [
            "analysis",
            "contrast",
            "omitted_campaign",
            "taxon_count",
            "zero_treatment",
            "n_sites",
            "mean_dispersion_first",
            "mean_dispersion_second",
            "dispersion_difference",
            "difference_ci_low",
            "difference_ci_high",
            "permutation_p",
            "q_primary_family",
        ],
    )
    write_tsv(
        output / "paired_displacement_loadings.tsv",
        [
            {
                "contrast": contrast,
                "genus": genus,
                "mean_clr_difference": float(value),
            }
            for contrast, vector in primary_directions.items()
            for genus, value in zip(
                taxon_sets[PRIMARY_TAXON_COUNT], vector
            )
        ],
        ["contrast", "genus", "mean_clr_difference"],
    )

    verdict = decision(location, dispersion, location_q)
    verdict["input"] = {
        **input_info,
        "eligible_genera": len(ranked),
        "counts_path": provenance_path(counts_path, root),
        "counts_sha256": sha256_file(counts_path),
        "prevalence_threshold": args.prevalence,
        "primary_taxon_count": PRIMARY_TAXON_COUNT,
        "taxon_sets": sorted(taxon_sets),
        "zero_treatments": list(ZERO_TREATMENTS),
        "primary_zero_treatment": PRIMARY_ZERO_TREATMENT,
        "permutations": args.permutations,
        "bootstrap_resamples": args.bootstrap,
        "seed": args.seed,
    }
    (output / "claim_verdict.json").write_text(
        json.dumps(verdict, indent=2) + "\n", encoding="utf-8"
    )

    readme = [
        "# Paired compartment-composition rescue",
        "",
        f"- Status: `{verdict['status']}`",
        f"- Matched cohort: {verdict['omnibus']['n_blocks']} complete "
        f"campaign x site blocks over {verdict['omnibus']['n_sites']} sites",
        f"- Omnibus pseudo-F: {verdict['omnibus']['pseudo_f']:.4f} "
        f"(p = {verdict['omnibus']['permutation_p']:.4g})",
        "",
    ]
    for contrast, value in verdict["contrasts"].items():
        readme.extend(
            [
                f"## {contrast} ({value['label']})",
                "",
                f"- Status: `{value['status']}`",
                f"- Sites: {value['n_sites']} "
                f"({value['n_blocks']} paired blocks)",
                f"- Centroid displacement: {value['centroid_displacement']:.4f} "
                f"(95% CI {value['centroid_displacement_ci'][0]:.4f} to "
                f"{value['centroid_displacement_ci'][1]:.4f})",
                f"- Permutation p: {value['permutation_p']:.4g}; "
                f"q = {value['q_within_primary_family']:.4g}",
                f"- Taxon/zero sensitivities supported: "
                f"{value['taxon_and_zero_sensitivities_supported']}",
                f"- Leave-one-campaign supported: "
                f"{value['leave_one_campaign_supported']}",
                f"- Direction stable: {value['direction_stable']}",
                f"- Dispersion difference: "
                f"{value['dispersion_difference']:.4f} "
                f"(95% CI {value['dispersion_difference_ci'][0]:.4f} to "
                f"{value['dispersion_difference_ci'][1]:.4f}; "
                f"differs = {value['dispersion_differs']})",
                "",
            ]
        )
    readme.extend(
        [
            "## Permitted wording",
            "",
            verdict["permitted_wording"],
            "",
            "## Prohibited wording",
            "",
            verdict["prohibited_wording"],
            "",
        ]
    )
    (output / "README.md").write_text("\n".join(readme), encoding="utf-8")

    checksum_lines = [
        f"{sha256_file(path)}  {path.name}"
        for path in sorted(
            item
            for item in output.iterdir()
            if item.is_file() and item.name != "SHA256SUMS"
        )
    ]
    (output / "SHA256SUMS").write_text(
        "\n".join(checksum_lines) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
