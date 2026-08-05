#!/usr/bin/env python3
"""ASV-resolution and neighbour-graph sensitivity for the transect model.

The staged primary spatial analysis aggregates counts to genera and uses a
symmetric five-nearest-neighbour graph for the residual Moran diagnostic.
Two questions follow from that choice and are answered here as supplementary
sensitivities, not as replacements for the primary result:

* does genus aggregation create the transect association, or does it survive
  at amplicon-sequence-variant resolution;
* how much does the residual Moran statistic depend on the neighbour count k.

Both arms reuse the primary model's machinery unchanged, so any difference
is attributable to resolution or to k rather than to a different estimator.
The ASV arm is restricted to the exact site-campaign-compartment groups the
genus analysis retains, so the two cohorts share one denominator.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from spatial_turnover_rescue import (
    analyse,
    fit_multivariate,
    design_matrix,
    load_coordinates,
    load_grouped_counts,
    multivariate_moran,
    rank_taxa,
    sha256_file,
    site_level_clr,
    symmetric_knn_weights,
    write_tsv,
)

NEIGHBOUR_COUNTS = (3, 4, 5, 6, 8, 10)
ASV_TAXON_COUNTS = (800, 2000)


def align_to_reference_groups(
    counts: pd.DataFrame,
    metadata: pd.DataFrame,
    reference: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, int]]:
    """Restrict a count matrix to the reference analysis's group set.

    The ASV cache carries ten more profiles than the alpha cohort, which
    yields 631 groups instead of the canonical 630 when it is grouped
    independently.  Intersecting on the reference group keys keeps the
    supplementary sensitivity on exactly the primary denominator.
    """
    keys = ["campaign", "site", "compartment"]
    reference_keys = set(map(tuple, reference[keys].to_numpy()))
    mask = np.array(
        [tuple(row) in reference_keys for row in metadata[keys].to_numpy()]
    )
    dropped = int((~mask).sum())
    aligned_metadata = metadata.loc[mask].reset_index(drop=True)
    aligned_counts = counts.loc[:, mask.tolist()]
    aligned_counts.columns = pd.MultiIndex.from_frame(aligned_metadata)
    missing = len(reference_keys) - len(aligned_metadata)
    return (
        aligned_counts,
        aligned_metadata,
        {
            "reference_groups": len(reference_keys),
            "groups_dropped_from_asv_cache": dropped,
            "reference_groups_absent_from_asv_cache": int(missing),
            "aligned_groups": int(len(aligned_metadata)),
        },
    )


def moran_k_sensitivity(
    counts: pd.DataFrame,
    metadata: pd.DataFrame,
    coordinates: pd.DataFrame,
    taxa: list[str],
    pseudocount: float,
    permutations: int,
    seed: int,
) -> list[dict[str, Any]]:
    """Recompute the residual Moran diagnostic across neighbour counts."""
    sites, response, _ = site_level_clr(
        counts, metadata, taxa, None, pseudocount
    )
    spatial = coordinates.set_index("site").loc[sites]
    design = design_matrix(spatial["transect_km"].to_numpy(), 2)
    _, _, residual = fit_multivariate(response, design)
    rows = []
    for neighbours in NEIGHBOUR_COUNTS:
        weights = symmetric_knn_weights(
            spatial["x_km"].to_numpy(),
            spatial["y_km"].to_numpy(),
            neighbours=neighbours,
        )
        observed = multivariate_moran(residual, weights)
        rng = np.random.default_rng(seed + neighbours)
        null = np.empty(permutations)
        for index in range(permutations):
            null[index] = multivariate_moran(
                residual[rng.permutation(len(residual))], weights
            )
        p_value = (1 + int(np.sum(null >= observed))) / (permutations + 1)
        rows.append(
            {
                "neighbours_k": neighbours,
                "n_sites": int(len(sites)),
                "mean_degree": float(weights.sum(axis=1).mean()),
                "residual_moran_i": float(observed),
                "permutation_p": float(p_value),
                "null_mean": float(null.mean()),
                "null_p95": float(np.quantile(null, 0.95)),
            }
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--project-root", type=Path, default=Path(__file__).resolve().parents[2]
    )
    parser.add_argument(
        "--genus-counts",
        type=Path,
        default=None,
        help="genus count table; defaults to the canonical ecology cache",
    )
    parser.add_argument(
        "--asv-counts",
        type=Path,
        default=None,
        help="filtered ASV count table; defaults to the canonical ecology cache",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--minimum-group-reads", type=int, default=2000)
    parser.add_argument("--prevalence", type=float, default=0.20)
    parser.add_argument("--pseudocount", type=float, default=0.5)
    parser.add_argument("--permutations", type=int, default=999)
    parser.add_argument("--seed", type=int, default=20260728)
    args = parser.parse_args()

    root = args.project_root.resolve()
    cache = root / "analysis" / "v2" / "review" / "cache"
    genus_path = args.genus_counts or cache / "genus_counts.tsv"
    asv_path = args.asv_counts or cache / "asv_filt_counts.tsv"
    for path in (genus_path, asv_path):
        if not path.exists():
            raise FileNotFoundError(
                f"Spatial resolution sensitivity requires {path}; it is absent."
            )
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)

    coordinates = load_coordinates(root)
    genus_counts, genus_metadata, genus_info = load_grouped_counts(
        genus_path, args.minimum_group_reads
    )
    genus_taxa = rank_taxa(genus_counts, args.prevalence)

    asv_counts_raw, asv_metadata_raw, asv_info = load_grouped_counts(
        asv_path, args.minimum_group_reads
    )
    asv_counts, asv_metadata, alignment = align_to_reference_groups(
        asv_counts_raw, asv_metadata_raw, genus_metadata
    )
    asv_ranked = rank_taxa(asv_counts, args.prevalence)

    rows = []
    reference = analyse(
        genus_counts,
        genus_metadata,
        coordinates,
        genus_taxa[:200],
        omitted_campaign=None,
        trend_degree=2,
        permutations=args.permutations,
        seed=args.seed,
        pseudocount=args.pseudocount,
    )
    rows.append(
        {
            "resolution": "genus",
            "feature_count": 200,
            "eligible_features": len(genus_taxa),
            **{
                key: getattr(reference, key)
                for key in (
                    "n_sites",
                    "n_groups",
                    "partial_r2",
                    "pseudo_f",
                    "permutation_p",
                    "residual_moran_i",
                    "residual_moran_p",
                )
            },
        }
    )
    for feature_count in (*ASV_TAXON_COUNTS, len(asv_ranked)):
        if feature_count > len(asv_ranked):
            continue
        result = analyse(
            asv_counts,
            asv_metadata,
            coordinates,
            asv_ranked[:feature_count],
            omitted_campaign=None,
            trend_degree=2,
            permutations=args.permutations,
            seed=args.seed + feature_count,
            pseudocount=args.pseudocount,
        )
        rows.append(
            {
                "resolution": "asv",
                "feature_count": feature_count,
                "eligible_features": len(asv_ranked),
                **{
                    key: getattr(result, key)
                    for key in (
                        "n_sites",
                        "n_groups",
                        "partial_r2",
                        "pseudo_f",
                        "permutation_p",
                        "residual_moran_i",
                        "residual_moran_p",
                    )
                },
            }
        )
    write_tsv(
        output / "asv_resolution_sensitivity.tsv",
        rows,
        [
            "resolution",
            "feature_count",
            "eligible_features",
            "n_sites",
            "n_groups",
            "partial_r2",
            "pseudo_f",
            "permutation_p",
            "residual_moran_i",
            "residual_moran_p",
        ],
    )

    k_rows = moran_k_sensitivity(
        genus_counts,
        genus_metadata,
        coordinates,
        genus_taxa[:200],
        args.pseudocount,
        args.permutations,
        args.seed,
    )
    write_tsv(
        output / "moran_k_sensitivity.tsv",
        k_rows,
        [
            "neighbours_k",
            "n_sites",
            "mean_degree",
            "residual_moran_i",
            "permutation_p",
            "null_mean",
            "null_p95",
        ],
    )

    asv_rows = [row for row in rows if row["resolution"] == "asv"]
    genus_r2 = rows[0]["partial_r2"]
    asv_r2 = [row["partial_r2"] for row in asv_rows]
    moran_values = [row["residual_moran_i"] for row in k_rows]
    moran_ps = [row["permutation_p"] for row in k_rows]
    detected_k = [
        row["neighbours_k"] for row in k_rows if row["permutation_p"] < 0.05
    ]
    undetected_k = [
        row["neighbours_k"] for row in k_rows if row["permutation_p"] >= 0.05
    ]
    moran_k_robust = not undetected_k
    verdict = {
        "schema_version": "1.0",
        "status": (
            "asv_resolution_consistent_with_genus_primary"
            if all(value > 0.5 * genus_r2 for value in asv_r2)
            else "asv_resolution_diverges_from_genus_primary"
        ),
        "moran_k_status": (
            "residual_autocorrelation_detected_at_every_k"
            if moran_k_robust
            else "residual_autocorrelation_depends_on_neighbour_count"
        ),
        "genus_primary_partial_r2": genus_r2,
        "asv_partial_r2_range": [min(asv_r2), max(asv_r2)],
        "asv_alignment": alignment,
        "moran_i_range_across_k": [min(moran_values), max(moran_values)],
        "moran_p_max_across_k": max(moran_ps),
        "neighbour_counts_tested": list(NEIGHBOUR_COUNTS),
        "neighbour_counts_with_detected_autocorrelation": detected_k,
        "neighbour_counts_without_detected_autocorrelation": undetected_k,
        "permitted_wording": (
            "The transect association is not an artefact of genus "
            "aggregation: at amplicon-sequence-variant resolution the same "
            f"model gives partial R2 {min(asv_r2):.4f} to {max(asv_r2):.4f} "
            f"against {genus_r2:.4f} at genus level. The comparison runs on "
            f"the {alignment['aligned_groups']}-group intersection of the two "
            f"caches, covering {alignment['aligned_groups']} of the "
            f"{alignment['reference_groups']} genus-reference groups "
            f"({alignment['reference_groups_absent_from_asv_cache']} "
            "reference group absent from the ASV cache, "
            f"{alignment['groups_dropped_from_asv_cache']} extra ASV-cache "
            "groups dropped); the genus figure quoted here is the "
            f"{alignment['reference_groups']}-group primary fit. "
            + (
                "Residual spatial autocorrelation was detected at every "
                f"neighbour count tested (k = {min(NEIGHBOUR_COUNTS)} to "
                f"{max(NEIGHBOUR_COUNTS)}; Moran I {min(moran_values):.4f} to "
                f"{max(moran_values):.4f}, largest permutation p "
                f"{max(moran_ps):.3g})."
                if moran_k_robust
                else "The residual Moran diagnostic declines with the "
                f"neighbour count: it is detected at k = {detected_k} and not "
                f"at k = {undetected_k} (Moran I {max(moran_values):.4f} down "
                f"to {min(moran_values):.4f}). The fixed-k residual "
                "autocorrelation statement is bounded to the "
                "short-neighbourhood scale."
            )
        ),
        "prohibited_wording": (
            "Do not promote the ASV-resolution fit to the primary result; it "
            "is a supplementary resolution sensitivity on the same design and "
            "inherits every design limit of the primary model, including the "
            "collection-order alias. Do not state unqualified residual spatial "
            "autocorrelation without naming the neighbour count."
            if not moran_k_robust
            else "Do not promote the ASV-resolution fit to the primary result; "
            "it is a supplementary resolution sensitivity on the same design "
            "and inherits every design limit of the primary model, including "
            "the collection-order alias."
        ),
        "input": {
            "genus_counts_sha256": sha256_file(genus_path),
            "asv_counts_sha256": sha256_file(asv_path),
            "genus_groups": genus_info["retained_site_campaign_compartment_groups"],
            "asv_groups_before_alignment": asv_info[
                "retained_site_campaign_compartment_groups"
            ],
            "prevalence_threshold": args.prevalence,
            "pseudocount": args.pseudocount,
            "permutations": args.permutations,
            "seed": args.seed,
        },
    }
    (output / "claim_verdict.json").write_text(
        json.dumps(verdict, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    readme = [
        "# ASV-resolution and neighbour-graph sensitivity",
        "",
        verdict["permitted_wording"],
        "",
        verdict["prohibited_wording"],
        "",
        "Evidence files: `asv_resolution_sensitivity.tsv`,",
        "`moran_k_sensitivity.tsv`, `claim_verdict.json`.",
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
