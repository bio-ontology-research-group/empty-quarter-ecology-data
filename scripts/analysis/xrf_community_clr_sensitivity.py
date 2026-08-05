#!/usr/bin/env python3
"""Aitchison-geometry sensitivity for the laboratory-XRF community claim.

The canonical laboratory-XRF community test in ``xrf_community_rescue.py``
uses a Bray-Curtis PCoA.  Its result is small and threshold-dependent
(p = 0.056 with axes retaining 80% of variation, p = 0.044 at 95%), and the
microbiome response is compositional, so a centred-log-ratio sensitivity is
required before the "no robust association" conclusion can be retained.

This script reuses the canonical 11-element, within-campaign-standardized
laboratory-XRF axis exactly as the rescue emitted it; the axis is never
re-derived here and never relabelled as salinity.  Field XRF is not joined.
Genera are filtered by a declared prevalence rule, a documented zero treatment
is applied, and the CLR response is tested for the elemental axis after
campaign, position and site adjustment.  The elemental-axis residual is
permuted within site, so repeated observations of a site stay together and the
site remains the inferential unit.  Partial effect size, a site-cluster
resampling bias diagnostic and a residual multivariate Moran diagnostic are
reported for every taxon set and zero treatment.

No confidence interval is reported for the partial R2.  It is a non-negative,
upward-biased statistic and resampling 60 sites with replacement leaves only
about 38 distinct clusters, so the replicate distribution sits above the
full-sample estimate and a percentile interval would not be a valid confidence
interval.  Inference rests on the within-site permutation test.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd


SCHEMA_VERSION = "1.0"
POSITIONS = ("Surface", "Deep", "Rhizosphere")
ZERO_TREATMENTS = ("pseudocount_0.5", "pseudocount_1.0", "multiplicative_0.65")
PRIMARY_ZERO_TREATMENT = "pseudocount_0.5"
PRIMARY_TAXON_COUNT = 200


@dataclass(frozen=True)
class ClrResult:
    analysis: str
    axis: str
    taxon_count: int
    zero_treatment: str
    n_observations: int
    n_sites: int
    pseudo_f: float
    partial_r2: float
    bootstrap_median_partial_r2: float
    bootstrap_mean_distinct_sites: float
    permutation_p: float
    residual_moran_i: float
    residual_moran_p: float


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
                if value is None or (
                    isinstance(value, float) and not math.isfinite(value)
                ):
                    formatted[column] = ""
                elif isinstance(value, bool):
                    formatted[column] = "true" if value else "false"
                elif isinstance(value, float):
                    formatted[column] = f"{value:.10g}"
                else:
                    formatted[column] = value
            writer.writerow(formatted)


def load_grouped_counts(
    path: Path,
    alpha_path: Path,
    minimum_group_reads: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    genus = pd.read_csv(path, sep="\t", index_col=0)
    unassigned = genus.index.isna()
    # The canonical laboratory-XRF cohort is defined on the profiles that also
    # carry a depth-normalized alpha record, so the CLR sensitivity is run on
    # exactly the same joins as the Bray-Curtis analysis it tests.
    alpha = pd.read_csv(alpha_path, sep="\t", index_col=0)
    shared = genus.columns.intersection(alpha.index)
    metadata = alpha.loc[shared, ["Trip", "Site", "Type"]].copy()
    metadata["Trip"] = metadata["Trip"].astype(int)
    metadata["Site"] = metadata["Site"].astype(int)
    metadata["Type"] = metadata["Type"].replace({"Rhizo": "Rhizosphere"})
    metadata = metadata[
        metadata["Site"].between(1, 60)
        & metadata["Trip"].between(1, 5)
        & metadata["Type"].isin(POSITIONS)
    ]
    values = genus[metadata.index].T
    values["Trip"] = metadata["Trip"].to_numpy()
    values["Site"] = metadata["Site"].to_numpy()
    values["Type"] = metadata["Type"].to_numpy()
    grouped = values.groupby(["Trip", "Site", "Type"], sort=True).sum(
        numeric_only=True
    )
    # The read threshold is applied to the full library, including the
    # unassigned-genus row, so the retained cohort matches the canonical
    # Bray-Curtis analysis exactly.  Only the assigned genera enter the
    # composition.
    grouped = grouped.loc[grouped.sum(axis=1) >= minimum_group_reads]
    grouped = grouped.loc[:, ~unassigned]
    grouped.columns = grouped.columns.astype(str)
    keys = grouped.index.to_frame(index=False)
    return grouped.reset_index(drop=True), keys


def load_axis(path: Path) -> pd.DataFrame:
    axis = pd.read_csv(path, sep="\t")
    required = {"Trip", "Site", "Type", "elemental_pc1"}
    missing = required - set(axis)
    if missing:
        raise ValueError(
            f"Elemental-axis table is missing columns: {sorted(missing)}"
        )
    axis["Trip"] = axis["Trip"].astype(int)
    axis["Site"] = axis["Site"].astype(int)
    return axis


def load_coordinates(root: Path) -> pd.DataFrame:
    rows: list[dict[str, float]] = []
    for campaign in range(1, 6):
        path = (
            root
            / "data"
            / "metadata"
            / "geodata"
            / f"trip{campaign}_geodata.tsv"
        )
        frame = pd.read_csv(path, sep="\t")
        frame["Site"] = pd.to_numeric(frame["Site"], errors="coerce")
        frame = frame.dropna(subset=["Site", "Latitude", "Longitude"])
        frame = frame[frame["Site"].between(1, 60)]
        rows.extend(
            {
                "Site": int(row.Site),
                "latitude": float(row.Latitude),
                "longitude": float(row.Longitude),
            }
            for row in frame.itertuples()
        )
    coordinates = (
        pd.DataFrame(rows)
        .groupby("Site", as_index=False)[["latitude", "longitude"]]
        .mean()
    )
    latitude = coordinates["latitude"].to_numpy()
    longitude = coordinates["longitude"].to_numpy()
    coordinates["y_km"] = (latitude - latitude.mean()) * 110.574
    coordinates["x_km"] = (
        (longitude - longitude.mean())
        * 111.320
        * np.cos(np.deg2rad(latitude.mean()))
    )
    return coordinates


def rank_taxa(counts: pd.DataFrame, prevalence_threshold: float) -> list[str]:
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
    matrix = np.asarray(counts, dtype=float)
    if zero_treatment.startswith("pseudocount_"):
        parts = matrix + float(zero_treatment.split("_", 1)[1])
    elif zero_treatment == "multiplicative_0.65":
        totals = matrix.sum(axis=1, keepdims=True)
        if not np.all(totals > 0):
            raise ValueError("Empty composition in multiplicative replacement")
        proportions = matrix / totals
        zeros = matrix <= 0
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


def design_matrix(
    keys: pd.DataFrame,
    include_site: bool = True,
) -> np.ndarray:
    """Campaign, position and (optionally) site adjustment as indicators.

    The site indicators belong in the adjustment set for the association test.
    They must be left out of the residual spatial diagnostic: a design that
    absorbs site drives every site-mean residual to zero by construction, so a
    Moran statistic computed on those means would measure rounding error rather
    than spatial structure.
    """
    columns = ["Trip", "Type", "Site"] if include_site else ["Trip", "Type"]
    categorical = keys[columns].astype(str)
    encoded = pd.get_dummies(categorical, drop_first=True, dtype=float)
    return np.column_stack([np.ones(len(keys)), encoded.to_numpy()])


def orthonormal_basis(matrix: np.ndarray) -> np.ndarray:
    """Orthonormal basis for the column space, robust to rank deficiency."""
    left, singular, _ = np.linalg.svd(np.asarray(matrix, dtype=float),
                                      full_matrices=False)
    if singular.size == 0:
        return left[:, :0]
    tolerance = singular.max() * max(matrix.shape) * np.finfo(float).eps
    return left[:, singular > tolerance]


def demean_blocks(matrix: np.ndarray, sizes: np.ndarray) -> np.ndarray:
    """Subtract the mean of each contiguous block of rows."""
    out = np.array(matrix, dtype=float, copy=True)
    start = 0
    for size in sizes:
        stop = start + int(size)
        out[start:stop] -= out[start:stop].mean(axis=0, keepdims=True)
        start = stop
    return out


class ProjectedModel:
    """Frisch-Waugh-Lovell projection onto the orthogonal complement.

    Projecting the multivariate response and the elemental axis onto the
    complement of the campaign/position/site design once turns each nested
    test into two inner products, which keeps the permutation and bootstrap
    loops tractable without changing the statistic.
    """

    def __init__(self, response: np.ndarray, reduced: np.ndarray) -> None:
        # An orthonormal basis is taken from the SVD rather than by truncating
        # a non-pivoted QR: the QR columns beyond the rank of a rank-deficient
        # design need not span the column space, so truncating them would
        # silently project onto the wrong subspace.
        self.basis = orthonormal_basis(reduced)
        self.rank = self.basis.shape[1]
        self.n = response.shape[0]
        self.response_residual = response - self.basis @ (
            self.basis.T @ response
        )
        self.sse_reduced = float(np.square(self.response_residual).sum())
        self.residual_df = self.n - self.rank - 1
        if self.residual_df <= 0 or self.sse_reduced <= 0:
            raise ValueError("Degenerate CLR elemental-axis model")

    def orthogonalise(self, predictor: np.ndarray) -> np.ndarray:
        return predictor - self.basis @ (self.basis.T @ predictor)

    def effect_sum_of_squares(self, predictor_residual: np.ndarray) -> float:
        denominator = float(predictor_residual @ predictor_residual)
        if denominator <= 0:
            return 0.0
        projection = self.response_residual.T @ predictor_residual
        return float(projection @ projection) / denominator

    def statistics(self, predictor: np.ndarray) -> tuple[float, float]:
        effect_ss = self.effect_sum_of_squares(self.orthogonalise(predictor))
        sse_full = max(self.sse_reduced - effect_ss, 0.0)
        if sse_full <= 0:
            raise ValueError("Degenerate CLR elemental-axis model")
        return (
            effect_ss / (sse_full / self.residual_df),
            effect_ss / self.sse_reduced,
        )

    def residual(self, predictor: np.ndarray) -> np.ndarray:
        orthogonal = self.orthogonalise(predictor)
        denominator = float(orthogonal @ orthogonal)
        if denominator <= 0:
            return self.response_residual
        coefficients = (self.response_residual.T @ orthogonal) / denominator
        return self.response_residual - np.outer(orthogonal, coefficients)


def symmetric_knn_weights(
    x: np.ndarray,
    y: np.ndarray,
    neighbours: int = 5,
) -> np.ndarray:
    coordinates = np.column_stack([x, y])
    distances = np.sqrt(
        np.square(coordinates[:, None, :] - coordinates[None, :, :]).sum(
            axis=2
        )
    )
    np.fill_diagonal(distances, np.inf)
    k = min(neighbours, len(coordinates) - 1)
    weights = np.zeros_like(distances)
    for row, columns in enumerate(np.argsort(distances, axis=1)[:, :k]):
        weights[row, columns] = 1
    return np.maximum(weights, weights.T)


def multivariate_moran(residual: np.ndarray, weights: np.ndarray) -> float:
    centered = residual - residual.mean(axis=0, keepdims=True)
    numerator = float(np.sum(centered * (weights @ centered)))
    denominator = float(np.square(centered).sum())
    if denominator <= 0:
        return math.nan
    return len(centered) / weights.sum() * numerator / denominator


def site_residual_moran(
    residual: np.ndarray,
    sites: np.ndarray,
    coordinates: pd.DataFrame,
    permutations: int,
    seed: int,
) -> tuple[float, float]:
    """Moran diagnostic on site-averaged residuals of a site-free CLR model.

    The caller must pass residuals from a model adjusted for campaign,
    position and the elemental axis but *not* for site; see `design_matrix`.
    """
    frame = pd.DataFrame(residual)
    frame["Site"] = sites
    averaged = frame.groupby("Site", sort=True).mean()
    spatial = coordinates.set_index("Site").loc[averaged.index]
    weights = symmetric_knn_weights(
        spatial["x_km"].to_numpy(), spatial["y_km"].to_numpy()
    )
    values = averaged.to_numpy()
    observed = multivariate_moran(values, weights)
    rng = np.random.default_rng(seed)
    exceed = 0
    for _ in range(permutations):
        exceed += (
            multivariate_moran(values[rng.permutation(len(values))], weights)
            >= observed
        )
    return observed, (exceed + 1) / (permutations + 1)


def within_site_permutation_p(
    model: ProjectedModel,
    predictor: np.ndarray,
    sites: np.ndarray,
    observed_f: float,
    permutations: int,
    seed: int,
) -> float:
    """Permute the axis residual within site, keeping repeated rows together."""
    predictor_residual = model.orthogonalise(predictor)
    fitted = predictor - predictor_residual
    groups = [np.flatnonzero(sites == site) for site in np.unique(sites)]
    rng = np.random.default_rng(seed)
    exceed = 0
    for _ in range(permutations):
        permuted = predictor_residual.copy()
        for indices in groups:
            permuted[indices] = rng.permutation(permuted[indices])
        candidate_f, _ = model.statistics(fitted + permuted)
        exceed += candidate_f >= observed_f
    return (exceed + 1) / (permutations + 1)


def bootstrap_partial_r2(
    response: np.ndarray,
    keys: pd.DataFrame,
    predictor: np.ndarray,
    resamples: int,
    seed: int,
) -> dict[str, float]:
    """Site-cluster resampling diagnostic for the partial R2.

    This deliberately does NOT return a confidence interval. Partial R2 is a
    non-negative, upward-biased statistic, and drawing 60 sites with
    replacement leaves only about 38 distinct clusters, so the same adjustment
    absorbs variation from fewer independent sites and the replicate
    distribution sits well above the full-sample estimate. A percentile
    interval built from those replicates is therefore not a valid confidence
    interval: earlier versions of this function reported one whose lower limit
    exceeded the point estimate.

    Refitting is nonetheless exercised as a correctness check — resampling all
    60 distinct sites reproduces the point estimate exactly — and the returned
    median and mean distinct-cluster count quantify the bias so that it can be
    reported instead of concealed. Inference comes from the within-site
    permutation test, not from these replicates.

    Whole sites are drawn with replacement and each drawn copy is treated as
    its own cluster, preserving within-site identification. Site indicators are
    removed by demeaning within each drawn block and the remaining campaign and
    position columns are projected out afterwards; by Frisch-Waugh-Lovell this
    equals a joint fit of the whole design at a fraction of the cost.
    """
    sites = keys["Site"].to_numpy()
    unique = np.unique(sites)
    members = {site: np.flatnonzero(sites == site) for site in unique}
    covariates = pd.get_dummies(
        keys[["Trip", "Type"]].astype(str), drop_first=True, dtype=float
    ).to_numpy()
    rng = np.random.default_rng(seed)
    values: list[float] = []
    distinct: list[int] = []
    for _ in range(resamples):
        drawn = rng.choice(unique, size=len(unique), replace=True)
        distinct.append(int(np.unique(drawn).size))
        blocks = [members[site] for site in drawn]
        sizes = np.array([len(block) for block in blocks], dtype=int)
        rows = np.concatenate(blocks)
        # Within-block demeaning is the exact projection onto the per-copy
        # site indicators; the intercept is absorbed by the same span.
        outcome = demean_blocks(response[rows], sizes)
        axis = demean_blocks(predictor[rows].reshape(-1, 1), sizes).ravel()
        adjustment = demean_blocks(covariates[rows], sizes)
        basis = orthonormal_basis(adjustment)
        if basis.shape[1]:
            outcome = outcome - basis @ (basis.T @ outcome)
            axis = axis - basis @ (basis.T @ axis)
        denominator = float(axis @ axis)
        total = float(np.square(outcome).sum())
        if denominator <= 0 or total <= 0:
            continue
        projection = outcome.T @ axis
        values.append(float(projection @ projection) / denominator / total)
    if not values:
        return {
            "bootstrap_median_partial_r2": math.nan,
            "bootstrap_mean_distinct_sites": math.nan,
        }
    return {
        "bootstrap_median_partial_r2": float(np.median(values)),
        "bootstrap_mean_distinct_sites": float(np.mean(distinct)),
    }


def analyse(
    counts: pd.DataFrame,
    keys: pd.DataFrame,
    coordinates: pd.DataFrame,
    taxa: Sequence[str],
    axis_column: str,
    zero_treatment: str,
    analysis: str,
    permutations: int,
    bootstrap: int,
    seed: int,
) -> ClrResult:
    response = clr_matrix(counts[list(taxa)].to_numpy(), zero_treatment)
    model = ProjectedModel(response, design_matrix(keys))
    predictor = keys[axis_column].to_numpy(dtype=float)
    observed_f, partial_r2 = model.statistics(predictor)
    # The spatial diagnostic needs a site-free adjustment; see design_matrix.
    spatial_model = ProjectedModel(
        response, design_matrix(keys, include_site=False)
    )
    residual = spatial_model.residual(predictor)
    permutation_p = within_site_permutation_p(
        model,
        predictor,
        keys["Site"].to_numpy(),
        observed_f,
        permutations,
        seed,
    )
    resampling = bootstrap_partial_r2(
        response, keys, predictor, bootstrap, seed + 7
    )
    moran_i, moran_p = site_residual_moran(
        residual,
        keys["Site"].to_numpy(),
        coordinates,
        permutations,
        seed + 13,
    )
    return ClrResult(
        analysis=analysis,
        axis=axis_column,
        taxon_count=len(taxa),
        zero_treatment=zero_treatment,
        n_observations=len(keys),
        n_sites=int(keys["Site"].nunique()),
        pseudo_f=observed_f,
        partial_r2=partial_r2,
        bootstrap_median_partial_r2=resampling["bootstrap_median_partial_r2"],
        bootstrap_mean_distinct_sites=resampling["bootstrap_mean_distinct_sites"],
        permutation_p=permutation_p,
        residual_moran_i=moran_i,
        residual_moran_p=moran_p,
    )


def decision(results: Sequence[ClrResult]) -> dict[str, Any]:
    primary = next(
        item
        for item in results
        if item.analysis == "primary"
        and item.axis == "elemental_pc1"
        and item.taxon_count == PRIMARY_TAXON_COUNT
        and item.zero_treatment == PRIMARY_ZERO_TREATMENT
    )
    sensitivities = [item for item in results if item is not primary]
    primary_supported = primary.permutation_p < 0.05
    all_supported = primary_supported and all(
        item.permutation_p < 0.05 for item in sensitivities
    )
    effects_small = all(item.partial_r2 < 0.01 for item in results)
    residual_spatial = primary.residual_moran_p < 0.05
    spatial_sentence = (
        " Composition remained spatially autocorrelated after campaign, "
        f"position and the elemental axis (site-level multivariate Moran "
        f"I = {primary.residual_moran_i:.3f}, "
        f"p = {primary.residual_moran_p:.3g}), so the axis is not a spatially "
        "controlled explanation and geography remains an unmodelled "
        "alternative."
        if residual_spatial
        else ""
    )
    if all_supported:
        status = "bounded_elemental_axis_association"
        wording = (
            "In Aitchison geometry the laboratory-XRF elemental axis remained "
            "associated with community composition after campaign, position "
            "and site adjustment in every prespecified taxon set and zero "
            f"treatment (primary partial R2 = {primary.partial_r2:.4f}, "
            f"p = {primary.permutation_p:.3g}). The axis accounts for well "
            "under one percent of adjusted compositional variation, so report "
            "it as a bounded association with an elemental axis only. Do not "
            "infer salinity, soluble ions, osmotic stress or causality."
        )
    elif primary_supported:
        status = "sensitivity_dependent_elemental_axis_association"
        wording = (
            "The CLR analysis supported the elemental axis in the primary "
            "model but not across every taxon set and zero treatment, so the "
            "association is sensitivity-dependent and the conclusion of no "
            "robust laboratory-XRF association is retained."
        )
    else:
        status = "no_robust_association_retained"
        wording = (
            "In Aitchison geometry the laboratory-XRF elemental axis showed "
            "no supported association with community composition after "
            "campaign, position and site adjustment (primary partial "
            f"R2 = {primary.partial_r2:.4f}, "
            f"p = {primary.permutation_p:.3g}). The conclusion of no robust "
            "elemental-axis association is retained and is not an artefact "
            "of Bray-Curtis geometry."
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "permitted_wording": wording + spatial_sentence,
        "prohibited_wording": (
            "Do not call the axis salinity, and do not infer soluble ions, "
            "osmotic stress, or causality; no EC, pH or soluble-ion "
            "measurement supports that reading. Field XRF is not pooled with "
            "laboratory XRF."
        ),
        "primary": {
            "n_observations": primary.n_observations,
            "n_sites": primary.n_sites,
            "taxon_count": primary.taxon_count,
            "zero_treatment": primary.zero_treatment,
            "pseudo_f": primary.pseudo_f,
            "partial_r2": primary.partial_r2,
            "bootstrap_median_partial_r2": (
                primary.bootstrap_median_partial_r2
            ),
            "bootstrap_mean_distinct_sites": (
                primary.bootstrap_mean_distinct_sites
            ),
            "no_confidence_interval_reported": (
                "Partial R2 is upward biased when site clusters are resampled "
                "with replacement (about 38 of 60 sites remain distinct), so "
                "no percentile interval is reported; inference is the "
                "within-site permutation test."
            ),
            "permutation_p": primary.permutation_p,
            "residual_moran_i": primary.residual_moran_i,
            "residual_moran_p": primary.residual_moran_p,
        },
        "all_sensitivities_supported": all_supported,
        "all_partial_r2_below_0_01": effects_small,
        "residual_spatial_structure_present": bool(
            primary.residual_moran_p < 0.05
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
    )
    parser.add_argument(
        "--elemental-axis",
        type=Path,
        default=None,
        help="laboratory_xrf_axis.tsv emitted by xrf_community_rescue.py",
    )
    parser.add_argument("--counts", type=Path, default=None)
    parser.add_argument("--alpha", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--minimum-group-reads", type=int, default=2000)
    parser.add_argument("--prevalence", type=float, default=0.20)
    parser.add_argument("--permutations", type=int, default=999)
    parser.add_argument("--bootstrap", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=20260725)
    args = parser.parse_args()

    root = args.project_root.resolve()
    counts_path = (
        args.counts
        or root / "analysis" / "v2" / "review" / "cache" / "genus_counts.tsv"
    )
    alpha_path = (
        args.alpha
        or root / "analysis" / "v2" / "review" / "cache" / "alpha.tsv"
    )
    axis_path = args.elemental_axis or (
        root
        / "analysis"
        / "v3"
        / "xrf_community_rescue"
        / "laboratory_xrf_axis.tsv"
    )
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)

    counts, keys = load_grouped_counts(
        counts_path, alpha_path, args.minimum_group_reads
    )
    axis = load_axis(axis_path)
    keys = keys.reset_index(drop=True)
    keys["row_index"] = np.arange(len(keys))
    joined = (
        keys.merge(axis, on=["Trip", "Site", "Type"], how="inner")
        .sort_values(["Trip", "Site", "Type"])
        .reset_index(drop=True)
    )
    counts = counts.iloc[joined["row_index"].to_numpy()].reset_index(drop=True)
    coordinates = load_coordinates(root)

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

    results: list[ClrResult] = []
    for offset, (taxon_count, zero_treatment) in enumerate(
        itertools.product(sorted(taxon_sets), ZERO_TREATMENTS)
    ):
        is_primary = (
            taxon_count == PRIMARY_TAXON_COUNT
            and zero_treatment == PRIMARY_ZERO_TREATMENT
        )
        results.append(
            analyse(
                counts,
                joined,
                coordinates,
                taxon_sets[taxon_count],
                "elemental_pc1",
                zero_treatment,
                "primary" if is_primary else "taxon_or_zero_sensitivity",
                args.permutations,
                args.bootstrap,
                args.seed + 1000 * (offset + 1),
            )
        )
    if "elemental_pc1_global_sensitivity" in joined:
        results.append(
            analyse(
                counts,
                joined,
                coordinates,
                taxon_sets[PRIMARY_TAXON_COUNT],
                "elemental_pc1_global_sensitivity",
                PRIMARY_ZERO_TREATMENT,
                "global_standardisation_sensitivity",
                args.permutations,
                args.bootstrap,
                args.seed + 90001,
            )
        )

    write_tsv(
        output / "clr_elemental_axis_models.tsv",
        [item.__dict__ for item in results],
        [
            "analysis",
            "axis",
            "taxon_count",
            "zero_treatment",
            "n_observations",
            "n_sites",
            "pseudo_f",
            "partial_r2",
            "bootstrap_median_partial_r2",
            "bootstrap_mean_distinct_sites",
            "permutation_p",
            "residual_moran_i",
            "residual_moran_p",
        ],
    )
    write_tsv(
        output / "clr_analysis_cohort.tsv",
        joined[
            ["Trip", "Site", "Type", "elemental_pc1"]
        ].to_dict(orient="records"),
        ["Trip", "Site", "Type", "elemental_pc1"],
    )

    verdict = decision(results)
    verdict["input"] = {
        "counts_path": provenance_path(counts_path, root),
        "counts_sha256": sha256_file(counts_path),
        "alpha_path": provenance_path(alpha_path, root),
        "alpha_sha256": sha256_file(alpha_path),
        "elemental_axis_path": provenance_path(axis_path, root),
        "elemental_axis_sha256": sha256_file(axis_path),
        "axis_provenance": (
            "Canonical 11-element within-campaign-standardized laboratory-XRF "
            "PC1 as emitted by xrf_community_rescue.py; not re-derived here."
        ),
        "field_xrf_role": "Excluded; laboratory records only.",
        "minimum_group_reads": args.minimum_group_reads,
        "prevalence_threshold": args.prevalence,
        "eligible_genera": len(ranked),
        "taxon_sets": sorted(taxon_sets),
        "zero_treatments": list(ZERO_TREATMENTS),
        "primary_taxon_count": PRIMARY_TAXON_COUNT,
        "primary_zero_treatment": PRIMARY_ZERO_TREATMENT,
        "permutations": args.permutations,
        "bootstrap_resamples": args.bootstrap,
        "seed": args.seed,
    }
    (output / "claim_verdict.json").write_text(
        json.dumps(verdict, indent=2) + "\n", encoding="utf-8"
    )

    primary = verdict["primary"]
    readme = [
        "# Compositionally coherent XRF/community sensitivity",
        "",
        f"- Status: `{verdict['status']}`",
        f"- Cohort: {primary['n_observations']} laboratory-XRF/community "
        f"joins over {primary['n_sites']} core sites",
        f"- Primary partial R2: {primary['partial_r2']:.5f} "
        f"(site-cluster resampling median "
        f"{primary['bootstrap_median_partial_r2']:.5f} over "
        f"{primary['bootstrap_mean_distinct_sites']:.1f} distinct sites on "
        f"average; upward biased, so no interval is reported)",
        f"- Primary within-site permutation p: "
        f"{primary['permutation_p']:.4g}",
        f"- Residual multivariate Moran I: "
        f"{primary['residual_moran_i']:.4f} "
        f"(p = {primary['residual_moran_p']:.4g})",
        f"- Every taxon-set/zero-treatment fit supported: "
        f"{verdict['all_sensitivities_supported']}",
        f"- Every partial R2 below 0.01: "
        f"{verdict['all_partial_r2_below_0_01']}",
        "",
        "## Permitted wording",
        "",
        verdict["permitted_wording"],
        "",
        "## Prohibited wording",
        "",
        verdict["prohibited_wording"],
        "",
    ]
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
