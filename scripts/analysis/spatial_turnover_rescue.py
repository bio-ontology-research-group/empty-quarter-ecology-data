#!/usr/bin/env python3
"""Grouped, compositional test of broad-scale geographic community structure.

The historical manuscript used significance from pairwise Mantel tests.  Those
tests reuse samples across many distances and can be anti-conservative under
spatial autocorrelation.  This replacement makes the site the independent
unit:

1. sequencing replicates are summed within campaign x site x compartment;
2. common genera are transformed with a centred log ratio;
3. campaign x compartment means are removed before values are averaged by site;
4. the site-level composition is regressed on a pre-specified linear and
   quadratic transect coordinate; and
5. whole site rows are permuted for inference.

Leave-one-campaign-out and taxon-count sensitivities are reported, together
with a multivariate Moran diagnostic on the fitted residuals.  The analysis can
support broad geographic structure, but it cannot identify dispersal
limitation or a particular environmental mechanism.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd


SCHEMA_VERSION = "1.0"
COMPARTMENTS = ("Surface", "Deep", "Rhizosphere")
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
class SpatialResult:
    analysis: str
    omitted_campaign: int | None
    taxon_count: int
    trend_degree: int
    n_sites: int
    n_groups: int
    partial_r2: float
    pseudo_f: float
    permutation_p: float
    residual_moran_i: float
    residual_moran_p: float


def sample_metadata(sample_id: str) -> dict[str, Any] | None:
    """Parse the normalized sample identifiers used by the count matrix."""
    match = SAMPLE_RE.match(str(sample_id).replace(" ", ""))
    if match is None:
        return None
    prefix = match.group("prefix") or ""
    return {
        "sample_id": sample_id,
        "campaign": PREFIX_CAMPAIGN[prefix],
        "site": int(match.group("site")),
        "compartment": CODE_COMPARTMENT[match.group("compartment")],
    }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
            formatted = {}
            for column in columns:
                value = row.get(column)
                if value is None:
                    formatted[column] = ""
                elif isinstance(value, float):
                    formatted[column] = (
                        f"{value:.10g}" if math.isfinite(value) else ""
                    )
                elif isinstance(value, bool):
                    formatted[column] = "true" if value else "false"
                else:
                    formatted[column] = value
            writer.writerow(formatted)


def load_coordinates(project_root: Path) -> pd.DataFrame:
    rows = []
    for campaign in range(1, 6):
        path = (
            project_root
            / "data"
            / "metadata"
            / "geodata"
            / f"trip{campaign}_geodata.tsv"
        )
        frame = pd.read_csv(path, sep="\t")
        frame["Site"] = pd.to_numeric(frame["Site"], errors="coerce")
        frame = frame.dropna(subset=["Site", "Latitude", "Longitude"])
        frame = frame[frame["Site"].between(1, 60)].copy()
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
    if len(coordinates) != 60:
        raise ValueError(
            f"Expected coordinates for 60 core sites, found {len(coordinates)}"
        )
    return add_transect_coordinate(coordinates)


def add_transect_coordinate(coordinates: pd.DataFrame) -> pd.DataFrame:
    """Project latitude/longitude to the first kilometre-scale spatial axis."""
    result = coordinates.copy()
    latitude = result["latitude"].to_numpy(dtype=float)
    longitude = result["longitude"].to_numpy(dtype=float)
    latitude_km = (latitude - latitude.mean()) * 110.574
    longitude_km = (
        (longitude - longitude.mean())
        * 111.320
        * np.cos(np.deg2rad(latitude.mean()))
    )
    xy = np.column_stack([longitude_km, latitude_km])
    _, _, vectors = np.linalg.svd(xy - xy.mean(axis=0), full_matrices=False)
    transect = (xy - xy.mean(axis=0)) @ vectors[0]
    if np.corrcoef(transect, longitude)[0, 1] < 0:
        transect *= -1
    result["x_km"] = longitude_km
    result["y_km"] = latitude_km
    result["transect_km"] = transect
    return result


def load_grouped_counts(
    path: Path,
    minimum_group_reads: int,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Return genera x groups counts and one metadata row per retained group."""
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
        & metadata["compartment"].isin(COMPARTMENTS)
    ].copy()
    sample_order = metadata["sample_id"].tolist()
    values = genus[sample_order].T
    values["campaign"] = metadata["campaign"].to_numpy()
    values["site"] = metadata["site"].to_numpy()
    values["compartment"] = metadata["compartment"].to_numpy()
    grouped = values.groupby(
        ["campaign", "site", "compartment"], sort=True
    ).sum(numeric_only=True)
    library_size = grouped.sum(axis=1)
    grouped = grouped.loc[library_size >= minimum_group_reads]
    group_metadata = grouped.index.to_frame(index=False)
    counts = grouped.T
    counts.columns = pd.MultiIndex.from_frame(group_metadata)
    info = {
        "input_genera": int(genus.shape[0]),
        "input_sample_columns": int(genus.shape[1]),
        "parsed_core_sample_columns": int(len(metadata)),
        "retained_site_campaign_compartment_groups": int(counts.shape[1]),
        "retained_sites": int(group_metadata["site"].nunique()),
        "minimum_group_reads": int(minimum_group_reads),
    }
    return counts, group_metadata, info


def rank_taxa(
    counts: pd.DataFrame,
    prevalence_threshold: float,
) -> list[str]:
    prevalence = (counts > 0).mean(axis=1)
    relative = counts.div(counts.sum(axis=0), axis=1)
    eligible = prevalence[prevalence >= prevalence_threshold].index
    ranking = (
        relative.loc[eligible]
        .mean(axis=1)
        .sort_values(ascending=False, kind="mergesort")
    )
    return ranking.index.tolist()


def site_level_clr(
    counts: pd.DataFrame,
    group_metadata: pd.DataFrame,
    taxa: Sequence[str],
    omitted_campaign: int | None,
    pseudocount: float,
) -> tuple[np.ndarray, np.ndarray, int]:
    """Campaign/compartment-centre CLR values, then average within each site."""
    metadata = group_metadata.copy()
    matrix = counts.loc[list(taxa)].T.to_numpy(dtype=float)
    if omitted_campaign is not None:
        keep = metadata["campaign"].to_numpy() != omitted_campaign
        metadata = metadata.loc[keep].reset_index(drop=True)
        matrix = matrix[keep]
    logged = np.log(matrix + pseudocount)
    clr = logged - logged.mean(axis=1, keepdims=True)
    for (_, _), indices in metadata.groupby(
        ["campaign", "compartment"], sort=True
    ).groups.items():
        index = np.asarray(list(indices), dtype=int)
        clr[index] -= clr[index].mean(axis=0, keepdims=True)
    site_rows = []
    site_values = []
    for site, indices in metadata.groupby("site", sort=True).groups.items():
        index = np.asarray(list(indices), dtype=int)
        site_rows.append(int(site))
        site_values.append(clr[index].mean(axis=0))
    return (
        np.asarray(site_rows, dtype=int),
        np.vstack(site_values),
        int(len(metadata)),
    )


def design_matrix(transect: np.ndarray, degree: int) -> np.ndarray:
    standardized = (transect - transect.mean()) / transect.std(ddof=1)
    columns = [np.ones(len(standardized))]
    for power in range(1, degree + 1):
        value = standardized**power
        if power > 1:
            value = value - value.mean()
        columns.append(value)
    return np.column_stack(columns)


def fit_multivariate(
    response: np.ndarray,
    design: np.ndarray,
) -> tuple[float, float, np.ndarray]:
    centered = response - response.mean(axis=0, keepdims=True)
    fitted = design @ np.linalg.lstsq(design, centered, rcond=None)[0]
    residual = centered - fitted
    tss = float(np.square(centered).sum())
    sse = float(np.square(residual).sum())
    q = design.shape[1] - 1
    residual_df = response.shape[0] - design.shape[1]
    if tss <= 0 or sse <= 0 or residual_df <= 0:
        raise ValueError("Degenerate multivariate spatial model")
    partial_r2 = 1 - sse / tss
    pseudo_f = ((tss - sse) / q) / (sse / residual_df)
    return partial_r2, pseudo_f, residual


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
    nearest = np.argsort(distances, axis=1)[:, :k]
    for row, columns in enumerate(nearest):
        weights[row, columns] = 1
    return np.maximum(weights, weights.T)


def multivariate_moran(
    residual: np.ndarray,
    weights: np.ndarray,
) -> float:
    centered = residual - residual.mean(axis=0, keepdims=True)
    # trace(E' W E), evaluated without constructing an n x n x p tensor.
    numerator = float(np.sum(centered * (weights @ centered)))
    denominator = float(np.square(centered).sum())
    return len(centered) / weights.sum() * numerator / denominator


def analyse(
    counts: pd.DataFrame,
    group_metadata: pd.DataFrame,
    coordinates: pd.DataFrame,
    taxa: Sequence[str],
    omitted_campaign: int | None,
    trend_degree: int,
    permutations: int,
    seed: int,
    pseudocount: float,
) -> SpatialResult:
    sites, response, n_groups = site_level_clr(
        counts,
        group_metadata,
        taxa,
        omitted_campaign,
        pseudocount,
    )
    spatial = coordinates.set_index("site").loc[sites]
    design = design_matrix(spatial["transect_km"].to_numpy(), trend_degree)
    partial_r2, pseudo_f, residual = fit_multivariate(response, design)
    weights = symmetric_knn_weights(
        spatial["x_km"].to_numpy(), spatial["y_km"].to_numpy()
    )
    observed_moran = multivariate_moran(residual, weights)
    rng = np.random.default_rng(seed)
    null_f = np.empty(permutations)
    null_moran = np.empty(permutations)
    for index in range(permutations):
        permuted = rng.permutation(len(response))
        _, null_f[index], _ = fit_multivariate(response[permuted], design)
        null_moran[index] = multivariate_moran(residual[permuted], weights)
    permutation_p = (1 + int(np.sum(null_f >= pseudo_f))) / (
        permutations + 1
    )
    residual_moran_p = (1 + int(np.sum(null_moran >= observed_moran))) / (
        permutations + 1
    )
    return SpatialResult(
        analysis=(
            "primary" if omitted_campaign is None else "leave_one_campaign_out"
        ),
        omitted_campaign=omitted_campaign,
        taxon_count=len(taxa),
        trend_degree=trend_degree,
        n_sites=len(sites),
        n_groups=n_groups,
        partial_r2=partial_r2,
        pseudo_f=pseudo_f,
        permutation_p=permutation_p,
        residual_moran_i=observed_moran,
        residual_moran_p=residual_moran_p,
    )


def decision(results: Sequence[SpatialResult]) -> dict[str, Any]:
    primary = next(
        item
        for item in results
        if item.analysis == "primary"
        and item.taxon_count == 200
        and item.trend_degree == 2
    )
    loco = [
        item
        for item in results
        if item.analysis == "leave_one_campaign_out"
        and item.taxon_count == 200
        and item.trend_degree == 2
    ]
    sensitivities = [
        item
        for item in results
        if item.analysis == "primary"
    ]
    detected = primary.permutation_p < 0.05
    stable = bool(loco) and all(item.permutation_p < 0.05 for item in loco)
    sensitivity_stable = all(
        item.permutation_p < 0.05 for item in sensitivities
    )
    residual_clear = primary.residual_moran_p >= 0.05
    if detected and stable and sensitivity_stable:
        status = "broad_geographic_structure_supported"
        wording = (
            "Community composition varied along the transect after "
            "campaign/compartment centring, and the result persisted in "
            "leave-one-campaign and taxon-set sensitivities. This supports "
            "broad geographic structure, not dispersal limitation or a "
            "specific environmental mechanism. Residual spatial "
            "autocorrelation remained, so the quadratic transect trend is a "
            "summary rather than a complete spatial model."
        )
    elif detected:
        status = "geographic_pattern_sensitivity_limited"
        wording = (
            "The primary grouped compositional analysis detected a geographic "
            "pattern, but its sensitivity gates were incomplete; describe it "
            "as exploratory and do not infer a process."
        )
    else:
        status = "not_supported"
        wording = (
            "The grouped compositional analysis did not support a broad "
            "geographic trend; retire confirmatory geographic claims."
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "permitted_wording": wording,
        "primary_partial_r2": primary.partial_r2,
        "primary_permutation_p": primary.permutation_p,
        "primary_residual_moran_i": primary.residual_moran_i,
        "primary_residual_moran_p": primary.residual_moran_p,
        "all_leave_one_campaign_p_below_0_05": stable,
        "all_primary_sensitivity_p_below_0_05": sensitivity_stable,
        "residual_spatial_autocorrelation_cleared": residual_clear,
        "mechanisms_not_identified": [
            "dispersal limitation",
            "environmental selection",
            "wind homogenisation",
            "plant buffering",
        ],
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
    parser.add_argument("--pseudocount", type=float, default=0.5)
    parser.add_argument("--permutations", type=int, default=999)
    parser.add_argument("--seed", type=int, default=20260723)
    args = parser.parse_args()

    root = args.project_root.resolve()
    counts_path = args.counts or (
        root / "analysis" / "v2" / "review" / "cache" / "genus_counts.tsv"
    )
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)

    counts, metadata, input_info = load_grouped_counts(
        counts_path, args.minimum_group_reads
    )
    coordinates = load_coordinates(root)
    ranked_taxa = rank_taxa(counts, args.prevalence)
    if len(ranked_taxa) < 200:
        raise ValueError(
            f"At least 200 eligible genera are required; found {len(ranked_taxa)}"
        )

    results = []
    for taxon_count in (80, 200, min(500, len(ranked_taxa))):
        for degree in (1, 2):
            results.append(
                analyse(
                    counts,
                    metadata,
                    coordinates,
                    ranked_taxa[:taxon_count],
                    omitted_campaign=None,
                    trend_degree=degree,
                    permutations=args.permutations,
                    seed=args.seed + taxon_count * 10 + degree,
                    pseudocount=args.pseudocount,
                )
            )
    for campaign in range(1, 6):
        results.append(
            analyse(
                counts,
                metadata,
                coordinates,
                ranked_taxa[:200],
                omitted_campaign=campaign,
                trend_degree=2,
                permutations=args.permutations,
                seed=args.seed + campaign,
                pseudocount=args.pseudocount,
            )
        )

    result_rows = [item.__dict__ for item in results]
    write_tsv(
        output / "spatial_model_results.tsv",
        result_rows,
        [
            "analysis",
            "omitted_campaign",
            "taxon_count",
            "trend_degree",
            "n_sites",
            "n_groups",
            "partial_r2",
            "pseudo_f",
            "permutation_p",
            "residual_moran_i",
            "residual_moran_p",
        ],
    )
    write_tsv(
        output / "site_coordinates.tsv",
        coordinates.to_dict(orient="records"),
        ["site", "latitude", "longitude", "x_km", "y_km", "transect_km"],
    )
    verdict = decision(results)
    verdict["input"] = {
        **input_info,
        "eligible_genera": len(ranked_taxa),
        "counts_path": str(counts_path),
        "counts_sha256": sha256_file(counts_path),
        "prevalence_threshold": args.prevalence,
        "pseudocount": args.pseudocount,
        "permutations": args.permutations,
        "seed": args.seed,
    }
    (output / "claim_verdict.json").write_text(
        json.dumps(verdict, indent=2) + "\n", encoding="utf-8"
    )
    readme = [
        "# Spatial-turnover rescue",
        "",
        verdict["permitted_wording"],
        "",
        f"- Primary partial R2: {verdict['primary_partial_r2']:.4f}",
        f"- Primary permutation p: {verdict['primary_permutation_p']:.4g}",
        f"- Primary residual multivariate Moran I: "
        f"{verdict['primary_residual_moran_i']:.4f}",
        f"- Residual Moran permutation p: "
        f"{verdict['primary_residual_moran_p']:.4g}",
        f"- All leave-one-campaign p < 0.05: "
        f"{verdict['all_leave_one_campaign_p_below_0_05']}",
        f"- All taxon-set/trend sensitivities p < 0.05: "
        f"{verdict['all_primary_sensitivity_p_below_0_05']}",
        "",
        "The site is the permutation unit. The result does not identify an "
        "assembly process or a causal environmental driver.",
        "",
    ]
    (output / "README.md").write_text(
        "\n".join(readme), encoding="utf-8"
    )
    checksum_lines = []
    for path in sorted(
        item
        for item in output.iterdir()
        if item.is_file() and item.name != "SHA256SUMS"
    ):
        checksum_lines.append(f"{sha256_file(path)}  {path.name}")
    (output / "SHA256SUMS").write_text(
        "\n".join(checksum_lines) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
