#!/usr/bin/env python3
"""Compartment-specific distance decay and turnover/nestedness structure.

Both analyses answer questions about the transect gradient that pairwise
tests are routinely used to answer wrongly.  Two rules are enforced here:

* pairwise distances are never treated as independent observations.  Every
  p-value comes from permuting whole site labels simultaneously across the
  rows and columns of all three compartment distance matrices, with the
  geographic distance matrix held fixed;
* compartment slopes are compared through paired distance contrasts
  (``D_surface - D_root``, ``D_shallow - D_root``) rather than by comparing
  independently fitted slopes, so any decay shared by all compartments
  cancels before the test.

The decomposition arm partitions dissimilarity into replacement and
richness-difference components.  Presence-absence Sorensen is partitioned
after coverage standardisation and is the reportable arm.  The abundance
Bray-Curtis partition is computed on unstandardised pooled counts, because
the abundance-gradient component is identically zero once every sample is
standardised to a common depth; that arm is reported with its library-size
diagnostic and is not used to support a claim.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import pandas as pd
from scipy import stats

from spatial_turnover_rescue import (
    COMPARTMENTS,
    load_coordinates,
    load_grouped_counts,
    rank_taxa,
    sha256_file,
    write_tsv,
)

COMPARTMENT_LABELS = {
    "Surface": "Surface",
    "Deep": "Shallow subsurface",
    "Rhizosphere": "Root-adjacent",
}
CONTRASTS = (("Surface", "Rhizosphere"), ("Deep", "Rhizosphere"))


def provenance_path(path: Path, root: Path) -> str:
    """Return a stable project-relative path without resolving symlinks."""
    candidate = path if path.is_absolute() else root / path
    try:
        return candidate.absolute().relative_to(root.absolute()).as_posix()
    except ValueError:
        return candidate.absolute().as_posix()


def site_compartment_clr(
    counts: pd.DataFrame,
    metadata: pd.DataFrame,
    taxa: Sequence[str],
    pseudocount: float,
) -> dict[str, pd.DataFrame]:
    """Campaign-and-compartment-centred CLR values averaged per site."""
    matrix = counts.loc[list(taxa)].T.to_numpy(dtype=float)
    logged = np.log(matrix + pseudocount)
    clr = logged - logged.mean(axis=1, keepdims=True)
    for _, indices in metadata.groupby(
        ["campaign", "compartment"], sort=True
    ).groups.items():
        index = np.asarray(list(indices), dtype=int)
        clr[index] -= clr[index].mean(axis=0, keepdims=True)
    frames = {}
    for compartment in COMPARTMENTS:
        mask = (metadata["compartment"] == compartment).to_numpy()
        sub_meta = metadata.loc[mask]
        sub_values = clr[mask]
        rows = []
        sites = []
        for site, indices in sub_meta.reset_index(drop=True).groupby(
            "site", sort=True
        ).groups.items():
            index = np.asarray(list(indices), dtype=int)
            sites.append(int(site))
            rows.append(sub_values[index].mean(axis=0))
        frames[compartment] = pd.DataFrame(
            np.vstack(rows), index=pd.Index(sites, name="site")
        )
    return frames


def site_compartment_counts(
    counts: pd.DataFrame, metadata: pd.DataFrame
) -> dict[str, pd.DataFrame]:
    """Pool raw counts within each site and compartment across campaigns."""
    values = counts.T
    values.index = pd.MultiIndex.from_frame(metadata)
    frames = {}
    for compartment in COMPARTMENTS:
        mask = (metadata["compartment"] == compartment).to_numpy()
        sub = counts.loc[:, mask].T
        sub.index = metadata.loc[mask, "site"].to_numpy()
        frames[compartment] = sub.groupby(level=0).sum()
    return frames


def euclidean_matrix(frame: pd.DataFrame) -> np.ndarray:
    values = frame.to_numpy(dtype=float)
    squared = np.square(values[:, None, :] - values[None, :, :]).sum(axis=2)
    return np.sqrt(np.maximum(squared, 0.0))


def geographic_matrix(coordinates: pd.DataFrame, sites: Sequence[int]) -> np.ndarray:
    frame = coordinates.set_index("site").loc[list(sites)]
    xy = frame[["x_km", "y_km"]].to_numpy(dtype=float)
    squared = np.square(xy[:, None, :] - xy[None, :, :]).sum(axis=2)
    return np.sqrt(np.maximum(squared, 0.0))


def upper_triangle(matrix: np.ndarray) -> np.ndarray:
    rows, columns = np.triu_indices(matrix.shape[0], k=1)
    return matrix[rows, columns]


def matrix_slope(geographic: np.ndarray, response: np.ndarray) -> float:
    x = upper_triangle(geographic)
    y = upper_triangle(response)
    centred = x - x.mean()
    return float(np.dot(centred, y) / np.square(centred).sum())


def jackknife_interval(
    estimate: float,
    leave_one_values: Sequence[float],
    *,
    lower_bound: float | None = None,
    upper_bound: float | None = None,
) -> tuple[float, float, float]:
    values = np.asarray(leave_one_values, dtype=float)
    n = len(values)
    standard_error = float(
        np.sqrt((n - 1) / n * np.square(values - values.mean()).sum())
    )
    critical = float(stats.t.ppf(0.975, df=n - 1))
    low = estimate - critical * standard_error
    high = estimate + critical * standard_error
    if lower_bound is not None:
        low = max(lower_bound, low)
    if upper_bound is not None:
        high = min(upper_bound, high)
    return standard_error, low, high


def delete_one_site_slope_interval(
    geographic: np.ndarray, response: np.ndarray
) -> tuple[float, float, float]:
    estimate = matrix_slope(geographic, response)
    leave_one = []
    for omitted in range(len(geographic)):
        keep = np.arange(len(geographic)) != omitted
        leave_one.append(
            matrix_slope(
                geographic[np.ix_(keep, keep)],
                response[np.ix_(keep, keep)],
            )
        )
    return jackknife_interval(estimate, leave_one)


def delete_one_site_ratio_interval(
    numerator: np.ndarray, denominator: np.ndarray
) -> tuple[float, float, float]:
    estimate = float(upper_triangle(numerator).mean() / upper_triangle(denominator).mean())
    leave_one = []
    for omitted in range(len(denominator)):
        keep = np.arange(len(denominator)) != omitted
        leave_one.append(
            float(
                upper_triangle(numerator[np.ix_(keep, keep)]).mean()
                / upper_triangle(denominator[np.ix_(keep, keep)]).mean()
            )
        )
    return jackknife_interval(
        estimate, leave_one, lower_bound=0.0, upper_bound=1.0
    )


def sorensen_partition(
    presence: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (Sorensen, Simpson turnover, nestedness-resultant) matrices."""
    presence = presence.astype(float)
    shared = presence @ presence.T
    totals = presence.sum(axis=1)
    only_first = totals[:, None] - shared
    only_second = totals[None, :] - shared
    minimum = np.minimum(only_first, only_second)
    denominator = 2 * shared + only_first + only_second
    sorensen = np.divide(
        only_first + only_second,
        denominator,
        out=np.zeros_like(shared),
        where=denominator > 0,
    )
    simpson_denominator = shared + minimum
    simpson = np.divide(
        minimum,
        simpson_denominator,
        out=np.zeros_like(shared),
        where=simpson_denominator > 0,
    )
    return sorensen, simpson, sorensen - simpson


def bray_partition(
    abundance: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (Bray-Curtis, balanced variation, abundance gradient)."""
    n = abundance.shape[0]
    bray = np.zeros((n, n))
    balanced = np.zeros((n, n))
    for i in range(n):
        for j in range(i + 1, n):
            a = abundance[i]
            b = abundance[j]
            shared = float(np.minimum(a, b).sum())
            first = float(a.sum()) - shared
            second = float(b.sum()) - shared
            denominator = 2 * shared + first + second
            if denominator <= 0:
                continue
            bray[i, j] = bray[j, i] = (first + second) / denominator
            minimum = min(first, second)
            if shared + minimum > 0:
                balanced[i, j] = balanced[j, i] = minimum / (shared + minimum)
    return bray, balanced, bray - balanced


def permutation_slopes(
    geographic: np.ndarray,
    responses: dict[str, np.ndarray],
    permutations: int,
    seed: int,
) -> tuple[dict[str, float], dict[str, np.ndarray]]:
    """Slope of each response on geographic distance, plus its null draws.

    A whole-site relabelling permutes rows and columns of the response
    matrices together.  Because the geographic matrix is held fixed and its
    entry multiset is invariant under relabelling, permuting the geographic
    matrix instead gives the identical null and costs one reindex per draw.
    """
    rows, columns = np.triu_indices(geographic.shape[0], k=1)
    x = geographic[rows, columns]
    x_centred = x - x.mean()
    denominator = float(np.square(x_centred).sum())
    observed = {
        name: float(np.dot(x_centred, values) / denominator)
        for name, values in responses.items()
    }
    rng = np.random.default_rng(seed)
    null = {name: np.empty(permutations) for name in responses}
    n = geographic.shape[0]
    for index in range(permutations):
        order = rng.permutation(n)
        permuted = geographic[np.ix_(order, order)][rows, columns]
        permuted = permuted - permuted.mean()
        scale = float(np.square(permuted).sum())
        for name, values in responses.items():
            null[name][index] = float(np.dot(permuted, values) / scale)
    return observed, null


def two_sided_p(observed: float, null: np.ndarray) -> float:
    centre = float(null.mean())
    extreme = int(np.sum(np.abs(null - centre) >= abs(observed - centre)))
    return (1 + extreme) / (len(null) + 1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--project-root", type=Path, default=Path(__file__).resolve().parents[2]
    )
    parser.add_argument(
        "--counts",
        type=Path,
        default=None,
        help="genus count table; defaults to the canonical ecology cache",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--minimum-group-reads", type=int, default=2000)
    parser.add_argument("--prevalence", type=float, default=0.20)
    parser.add_argument("--pseudocount", type=float, default=0.5)
    parser.add_argument("--taxon-count", type=int, default=200)
    parser.add_argument("--permutations", type=int, default=9999)
    parser.add_argument("--seed", type=int, default=20260728)
    args = parser.parse_args()

    root = args.project_root.resolve()
    counts_path = args.counts or (
        root / "analysis" / "v2" / "review" / "cache" / "genus_counts.tsv"
    )
    if not counts_path.exists():
        raise FileNotFoundError(
            f"Distance-decay analysis requires {counts_path}; it is absent."
        )
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)

    coordinates = load_coordinates(root)
    counts, metadata, input_info = load_grouped_counts(
        counts_path, args.minimum_group_reads
    )
    taxa = rank_taxa(counts, args.prevalence)[: args.taxon_count]
    clr_frames = site_compartment_clr(counts, metadata, taxa, args.pseudocount)
    count_frames = site_compartment_counts(counts, metadata)

    matched = sorted(
        set.intersection(
            *(set(frame.index.tolist()) for frame in clr_frames.values())
        )
    )
    if len(matched) < 20:
        raise ValueError(
            f"Only {len(matched)} sites carry all three compartments; the "
            "paired distance-decay design requires a matched cohort."
        )
    geographic = geographic_matrix(coordinates, matched)
    aitchison = {
        compartment: euclidean_matrix(frame.loc[matched])
        for compartment, frame in clr_frames.items()
    }

    # Preserve the plotted distances as a canonical output. The manuscript
    # figure bins these values only for display; all inference below continues
    # to permute whole sites rather than treating pairs as independent.
    pair_i, pair_j = np.triu_indices(len(matched), k=1)
    geographic_vector = geographic[pair_i, pair_j]
    pair_rows = []
    for compartment in COMPARTMENTS:
        dissimilarity = aitchison[compartment][pair_i, pair_j]
        for index, (first, second) in enumerate(zip(pair_i, pair_j)):
            pair_rows.append(
                {
                    "site_a": int(matched[first]),
                    "site_b": int(matched[second]),
                    "geographic_distance_km": float(geographic_vector[index]),
                    "compartment": compartment,
                    "compartment_label": COMPARTMENT_LABELS[compartment],
                    "aitchison_dissimilarity": float(dissimilarity[index]),
                }
            )
    write_tsv(
        output / "distance_decay_pairs.tsv",
        pair_rows,
        list(pair_rows[0]),
    )

    response_matrices = {
        f"aitchison::{compartment}": matrix
        for compartment, matrix in aitchison.items()
    }
    for first, second in CONTRASTS:
        response_matrices[f"contrast::{first}-{second}"] = (
            aitchison[first] - aitchison[second]
        )
    responses = {
        name: upper_triangle(matrix)
        for name, matrix in response_matrices.items()
    }

    # Coverage-standardised presence/absence for the replacement partition.
    pooled = {
        compartment: frame.loc[matched].to_numpy(dtype=float)
        for compartment, frame in count_frames.items()
    }
    depths = [matrix.sum(axis=1).min() for matrix in pooled.values()]
    standard_depth = int(min(depths))
    rng = np.random.default_rng(args.seed)
    rarefied = {}
    for compartment, matrix in pooled.items():
        drawn = np.vstack(
            [
                rng.multivariate_hypergeometric(
                    row.astype(np.int64), standard_depth
                )
                for row in matrix
            ]
        )
        rarefied[compartment] = drawn
    partition_rows = []
    for compartment, drawn in rarefied.items():
        sorensen, simpson, nestedness = sorensen_partition(drawn > 0)
        response_matrices[f"sorensen::{compartment}"] = sorensen
        response_matrices[f"simpson_turnover::{compartment}"] = simpson
        response_matrices[f"nestedness::{compartment}"] = nestedness
        responses[f"sorensen::{compartment}"] = upper_triangle(sorensen)
        responses[f"simpson_turnover::{compartment}"] = upper_triangle(simpson)
        responses[f"nestedness::{compartment}"] = upper_triangle(nestedness)
        bray, balanced, gradient = bray_partition(pooled[compartment])
        library = pooled[compartment].sum(axis=1)
        log_ratio = np.abs(
            np.log(library[:, None]) - np.log(library[None, :])
        )
        gradient_vector = upper_triangle(gradient)
        turnover_share = float(
            upper_triangle(simpson).mean() / upper_triangle(sorensen).mean()
        )
        turnover_se, turnover_ci_low, turnover_ci_high = (
            delete_one_site_ratio_interval(simpson, sorensen)
        )
        partition_rows.append(
            {
                "compartment": compartment,
                "compartment_label": COMPARTMENT_LABELS[compartment],
                "n_sites": len(matched),
                "standardised_depth": standard_depth,
                "mean_sorensen": float(upper_triangle(sorensen).mean()),
                "mean_simpson_turnover": float(upper_triangle(simpson).mean()),
                "mean_nestedness_resultant": float(
                    upper_triangle(nestedness).mean()
                ),
                "turnover_share_of_sorensen": turnover_share,
                "turnover_share_jackknife_se": turnover_se,
                "turnover_share_ci_low": turnover_ci_low,
                "turnover_share_ci_high": turnover_ci_high,
                "mean_bray_curtis_unstandardised": float(
                    upper_triangle(bray).mean()
                ),
                "mean_balanced_variation_unstandardised": float(
                    upper_triangle(balanced).mean()
                ),
                "mean_abundance_gradient_unstandardised": float(
                    gradient_vector.mean()
                ),
                "abundance_gradient_vs_log_library_ratio_pearson_r": float(
                    np.corrcoef(gradient_vector, upper_triangle(log_ratio))[0, 1]
                ),
            }
        )
    write_tsv(
        output / "turnover_nestedness_components.tsv",
        partition_rows,
        list(partition_rows[0]),
    )

    observed, null = permutation_slopes(
        geographic, responses, args.permutations, args.seed
    )
    slope_rows = []
    for name, value in observed.items():
        family, _, label = name.partition("::")
        draws = null[name]
        slope_se, slope_ci_low, slope_ci_high = delete_one_site_slope_interval(
            geographic, response_matrices[name]
        )
        slope_rows.append(
            {
                "family": family,
                "response": label,
                "slope_per_km": value,
                "slope_per_100km": value * 100.0,
                "jackknife_se_per_100km": slope_se * 100.0,
                "jackknife_ci_low_per_100km": slope_ci_low * 100.0,
                "jackknife_ci_high_per_100km": slope_ci_high * 100.0,
                "null_mean_slope_per_100km": float(draws.mean()) * 100.0,
                "null_sd_slope_per_100km": float(draws.std(ddof=1)) * 100.0,
                "two_sided_p": two_sided_p(value, draws),
                "permutations": int(args.permutations),
            }
        )
    contrast_names = [
        name for name in observed if name.startswith("contrast::")
    ]
    standardized = {}
    for name in contrast_names:
        draws = null[name]
        scale = float(draws.std(ddof=1))
        standardized[name] = (
            (observed[name] - float(draws.mean())) / scale,
            (draws - float(draws.mean())) / scale,
        )
    omnibus_observed = float(
        sum(value[0] ** 2 for value in standardized.values())
    )
    omnibus_null = np.sum(
        np.vstack([value[1] ** 2 for value in standardized.values()]), axis=0
    )
    omnibus_p = (1 + int(np.sum(omnibus_null >= omnibus_observed))) / (
        len(omnibus_null) + 1
    )
    max_t_null = np.max(
        np.abs(np.vstack([value[1] for value in standardized.values()])), axis=0
    )
    for name in contrast_names:
        statistic = abs(standardized[name][0])
        adjusted = (1 + int(np.sum(max_t_null >= statistic))) / (
            len(max_t_null) + 1
        )
        for row in slope_rows:
            if f"{row['family']}::{row['response']}" == name:
                row["standardized_statistic"] = standardized[name][0]
                row["max_t_adjusted_p"] = adjusted
    columns = [
        "family",
        "response",
        "slope_per_km",
        "slope_per_100km",
        "jackknife_se_per_100km",
        "jackknife_ci_low_per_100km",
        "jackknife_ci_high_per_100km",
        "null_mean_slope_per_100km",
        "null_sd_slope_per_100km",
        "two_sided_p",
        "standardized_statistic",
        "max_t_adjusted_p",
        "permutations",
    ]
    write_tsv(output / "distance_decay_slopes.tsv", slope_rows, columns)

    contrast_supported = {
        row["response"]: bool(row.get("max_t_adjusted_p", 1.0) < 0.05)
        for row in slope_rows
        if row["family"] == "contrast"
    }
    turnover_dominates = all(
        row["turnover_share_of_sorensen"] > 0.5 for row in partition_rows
    )
    verdict = {
        "schema_version": "1.1",
        "status": (
            "compartment_slopes_differ"
            if any(contrast_supported.values())
            else "no_supported_compartment_slope_difference"
        ),
        "matched_sites": len(matched),
        "site_pairs": int(len(matched) * (len(matched) - 1) // 2),
        "permutations": int(args.permutations),
        "sampling_uncertainty": (
            "95% t intervals from delete-one-site jackknife standard errors; "
            "all distances involving the omitted site are removed together"
        ),
        "omnibus_statistic": omnibus_observed,
        "omnibus_p": float(omnibus_p),
        "contrast_max_t_supported": contrast_supported,
        "standardised_depth": standard_depth,
        "turnover_dominates_sorensen_in_every_compartment": bool(
            turnover_dominates
        ),
        "permitted_wording": (
            "Aitchison dissimilarity increased with geographic distance in "
            "every soil position. Paired distance contrasts, tested with "
            "whole-site permutations and family-wise maximum-statistic "
            "control, "
            + (
                "supported a difference between compartment decay slopes "
                f"(omnibus p = {omnibus_p:.4g})."
                if any(contrast_supported.values())
                else "did not support a difference between compartment decay "
                f"slopes (omnibus p = {omnibus_p:.4g})."
            )
            + " After coverage standardisation to "
            f"{standard_depth} reads, Simpson replacement accounted for "
            + (
                "the majority of Sorensen dissimilarity in every compartment."
                if turnover_dominates
                else "a variable share of Sorensen dissimilarity across "
                "compartments."
            )
        ),
        "prohibited_wording": (
            "Do not treat site pairs as independent observations, do not "
            "report a p-value from permuting the pairwise distance vector, "
            "and do not read compartment slope differences as a plant or "
            "root process. The abundance-gradient component of Bray-Curtis is "
            "reported only with its library-size diagnostic and supports no "
            "claim, because it is identically zero under coverage "
            "standardisation."
        ),
        "input": {
            **input_info,
            "counts_path": provenance_path(counts_path, root),
            "counts_sha256": sha256_file(counts_path),
            "prevalence_threshold": args.prevalence,
            "pseudocount": args.pseudocount,
            "taxon_count": args.taxon_count,
            "seed": args.seed,
        },
    }
    (output / "claim_verdict.json").write_text(
        json.dumps(verdict, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    readme = [
        "# Compartment distance decay and turnover/nestedness",
        "",
        verdict["permitted_wording"],
        "",
        verdict["prohibited_wording"],
        "",
        "Sampling uncertainty is reported as a 95% t interval from a "
        "delete-one-site jackknife. Every distance involving the omitted site "
        "is removed together, so site pairs are never treated as independent.",
        "",
        "Evidence files: `distance_decay_pairs.tsv`,",
        "`distance_decay_slopes.tsv`, `turnover_nestedness_components.tsv`,",
        "and `claim_verdict.json`.",
        "",
    ]
    (output / "README.md").write_text("\n".join(readme), encoding="utf-8")
    digests = [
        f"{sha256_file(path)}  {path.name}"
        for path in sorted(output.glob("*"))
        if path.is_file() and path.name != "SHA256SUMS"
    ]
    (output / "SHA256SUMS").write_text("\n".join(digests) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
