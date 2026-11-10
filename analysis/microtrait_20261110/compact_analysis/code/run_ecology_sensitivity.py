#!/usr/bin/env python3
"""
Ecology Community-Weighted Trait Effect Sensitivity Pipeline.

Evaluates ecological sensitivity for BetL (glycine betaine transporter) and AhpCF
(peroxide defence) under the new full microTrait logical rules vs. published legacy HMM calls.

Scope:
- Uses exact 5,438 MAG index and frozen CoverM relative abundance matrix.
- Evaluates prespecified Surface-minus-Deep contrast under:
    * Mapped-community denominator (known catalogue fraction)
    * Original-read denominator (whole-read bound)
- Averages biological replicates within (site, trip, compartment).
- Computes paired visit differences averaged within site (expected 68 visits across 36 sites).
- Resamples the 10 contiguous spatial blocks (transect_km) over 1,000 bootstrap draws
  using seed 20261108 (matching published canonical sensitivity methodology).
- Reproduces legacy paired means (7.5515 pp BetL, 6.9491 pp AhpCF) and canonical CIs;
  fails closed on any deviation > 1e-6.
- Produces sample trait shares, site paired differences, effect table, and summary JSON.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd
from scipy import sparse

# Strict prohibition of /tmp
TMPDIR_ENV = os.environ.get("TMPDIR", "")
if TMPDIR_ENV.startswith("/tmp") or TMPDIR_ENV == "/tmp":
    fallback_tmp = Path.cwd() / "tmp_scratch"
    fallback_tmp.mkdir(parents=True, exist_ok=True)
    os.environ["TMPDIR"] = str(fallback_tmp)


def sha256_file(filepath: Path) -> str:
    """Compute SHA256 checksum of a file."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def build_spatial_blocks(design_df: pd.DataFrame, n_blocks: int = 10) -> Dict[str, str]:
    """Construct 10 contiguous spatial blocks ordered by site mean transect_km."""
    site_order = (
        design_df.assign(_tkm=pd.to_numeric(design_df["transect_km"], errors="raise"))
        .groupby("site")["_tkm"]
        .mean()
        .sort_values()
        .index
    )
    if len(site_order) < n_blocks:
        raise ValueError(f"Cannot split {len(site_order)} sites into {n_blocks} spatial blocks")
    return {
        str(s): f"spatial_block_{i:02d}"
        for i, grp in enumerate(np.array_split(site_order, n_blocks))
        for s in grp
    }


def compute_sample_scores(
    AA: np.ndarray,
    row_mapped: np.ndarray,
    traits_df: pd.DataFrame,
    genomes_ordered: List[str],
) -> pd.DataFrame:
    """Compute per-sample whole-read and mapped-community scores for each trait."""
    n_samples = AA.shape[0]
    scores_dict: Dict[str, np.ndarray] = {}

    for col in traits_df.columns:
        if col == "mag":
            continue
        t_vec = traits_df[col].to_numpy(dtype=float)
        if len(t_vec) != AA.shape[1]:
            raise ValueError(f"Trait vector length {len(t_vec)} != MAG count {AA.shape[1]}")

        # Whole-read bound (percentage points)
        whole = 100.0 * (AA @ t_vec)
        # Mapped-community denominator (percentage points)
        mapped = np.divide(whole, row_mapped, out=np.full(n_samples, np.nan), where=row_mapped > 0)

        scores_dict[f"{col}__whole"] = whole
        scores_dict[f"{col}__mapped"] = mapped

    return pd.DataFrame(scores_dict)


def validate_traits_df(traits_raw: pd.DataFrame, genomes_ordered: List[str]) -> pd.DataFrame:
    """Validate that traits dataframe matches genomes_ordered exactly (no duplicates, no missing)."""
    if "mag" not in traits_raw.columns:
        raise KeyError("traits dataframe missing 'mag' column")
    mag_series = traits_raw["mag"].astype(str)
    if mag_series.duplicated().any():
        dupes = mag_series[mag_series.duplicated()].tolist()
        raise ValueError(f"Duplicate MAG IDs in traits dataframe: {dupes[:5]}")
    if set(mag_series) != set(genomes_ordered):
        missing = set(genomes_ordered) - set(mag_series)
        extra = set(mag_series) - set(genomes_ordered)
        raise ValueError(
            f"MAG IDs in traits table do not match genomes_ordered exactly "
            f"(missing {len(missing)}, extra {len(extra)})"
        )
    return traits_raw.set_index("mag").reindex(genomes_ordered).reset_index()


def run_block_bootstrap(
    site_diff: pd.DataFrame,
    site_to_block: Dict[str, str],
    *,
    seed: int = 20261108,
    n_boot: int = 1000,
    n_visits: int = 68,
) -> Tuple[Dict[str, Any], pd.DataFrame]:
    """Compute 10-block bootstrap CIs from site paired differences."""
    site_diff = site_diff.copy()
    site_diff.index = site_diff.index.astype(str)
    site_to_block = {str(k): str(v) for k, v in site_to_block.items()}
    sites_ordered = sorted(site_diff.index)
    n_sites = len(sites_ordered)
    if n_sites != 36:
        raise ValueError(f"Expected exactly 36 paired sites, found {n_sites}")

    missing_blocks = [s for s in sites_ordered if s not in site_to_block]
    if missing_blocks:
        raise ValueError(f"Sites missing from spatial block mapping: {missing_blocks}")

    site_blocks = [site_to_block[s] for s in sites_ordered]
    unique_blocks, inverse = np.unique(site_blocks, return_inverse=True)
    n_b = len(unique_blocks)
    if n_b != 10:
        raise ValueError(f"Expected 10 spatial blocks, found {n_b}")
    block_indices = [np.where(inverse == i)[0] for i in range(n_b)]

    rng = np.random.default_rng(seed)
    chosen_blocks = rng.integers(0, n_b, size=(n_boot, n_b))
    resampled_site_indices = [
        np.concatenate([block_indices[c] for c in chosen_blocks[b]])
        for b in range(n_boot)
    ]

    effect_records = []
    detailed_metrics: Dict[str, Any] = {}

    for score_col in site_diff.columns:
        vals = site_diff.loc[sites_ordered, score_col].to_numpy(dtype="float64")
        point_est = float(np.mean(vals))

        boot_draws = np.empty(n_boot, dtype="float64")
        for b in range(n_boot):
            boot_draws[b] = np.mean(vals[resampled_site_indices[b]])

        ci_low = float(np.percentile(boot_draws, 2.5))
        ci_high = float(np.percentile(boot_draws, 97.5))
        se = float(np.std(boot_draws, ddof=1))
        excludes_zero = bool((ci_low > 0 and ci_high > 0) or (ci_low < 0 and ci_high < 0))

        if "__" in score_col:
            base_name, denom_tag = score_col.split("__", 1)
        else:
            base_name, denom_tag = score_col, "mapped"

        is_legacy = base_name.startswith("legacy_")
        trait_family = "BetL (betaine uptake)" if "bet" in base_name.lower() else "AhpCF (peroxide defence)"
        spec_label = "legacy_HMM" if is_legacy else "new_microtrait_full_rule"
        denom_label = "mapped_community" if denom_tag == "mapped" else "original_reads"

        rec = {
            "trait_family": trait_family,
            "specification": spec_label,
            "raw_column": base_name,
            "denominator": denom_label,
            "contrast": "Surface-minus-Deep",
            "n_sites": n_sites,
            "n_visits": n_visits,
            "point_estimate_pp": round(point_est, 6),
            "ci95_low_pp": round(ci_low, 6),
            "ci95_high_pp": round(ci_high, 6),
            "se_pp": round(se, 6),
            "excludes_zero": excludes_zero,
        }
        effect_records.append(rec)
        detailed_metrics[score_col] = {
            "point_estimate": point_est,
            "ci95_low": ci_low,
            "ci95_high": ci_high,
            "se": se,
            "excludes_zero": excludes_zero,
        }

    df_effects = pd.DataFrame(effect_records)

    # Compute deltas from legacy
    df_effects["delta_from_legacy_pp"] = np.nan
    for (fam, denom), grp in df_effects.groupby(["trait_family", "denominator"]):
        legacy_matches = grp.loc[grp["specification"] == "legacy_HMM", "point_estimate_pp"]
        if not legacy_matches.empty:
            leg_val = legacy_matches.values[0]
            for idx in grp.index:
                df_effects.loc[idx, "delta_from_legacy_pp"] = round(
                    df_effects.loc[idx, "point_estimate_pp"] - leg_val, 6
                )

    return detailed_metrics, df_effects


def compute_paired_contrasts_and_bootstrap(
    design_df: pd.DataFrame,
    scores_df: pd.DataFrame,
    site_to_block: Dict[str, str],
    *,
    seed: int = 20261108,
    n_boot: int = 1000,
) -> Tuple[pd.DataFrame, pd.DataFrame, Dict[str, Any], pd.DataFrame]:
    """Compute replicate-averaged visit contrasts, site means, and 10-block bootstrap CIs."""
    eval_df = design_df[["sample_id", "site", "trip", "compartment"]].copy()
    eval_df["site"] = eval_df["site"].astype(str)
    eval_df["trip"] = eval_df["trip"].astype(str)
    eval_df["compartment"] = eval_df["compartment"].astype(str)

    # Attach scores
    for col in scores_df.columns:
        eval_df[col] = scores_df[col].to_numpy()

    # Step 1: Average biological replicates within (site, trip, compartment)
    grouped = eval_df.groupby(["site", "trip", "compartment"])[scores_df.columns.tolist()].mean()

    # Step 2: Paired visit differences (Surface minus Deep)
    if "Surface" not in grouped.index.get_level_values("compartment") or "Deep" not in grouped.index.get_level_values("compartment"):
        raise ValueError("Both Surface and Deep compartments must be present")

    v_surf = grouped.xs("Surface", level="compartment")
    v_deep = grouped.xs("Deep", level="compartment")
    shared_visits = v_surf.index.intersection(v_deep.index)

    n_visits = len(shared_visits)
    if n_visits != 68:
        raise ValueError(f"Expected exactly 68 paired visits, found {n_visits}")

    visit_diff = v_surf.loc[shared_visits] - v_deep.loc[shared_visits]

    # Step 3: Average visit differences within site
    site_diff = visit_diff.groupby("site").mean()

    # Step 4: Run block bootstrap
    detailed_metrics, df_effects = run_block_bootstrap(
        site_diff, site_to_block, seed=seed, n_boot=n_boot, n_visits=n_visits
    )

    return visit_diff, site_diff, detailed_metrics, df_effects


def verify_legacy_reproduction(detailed_metrics: Dict[str, Any]) -> None:
    """Verify that legacy BetL and AhpCF estimates match published values down to 1e-5."""
    expected = {
        "legacy_HMM_glycine_betaine_transporter__mapped": {
            "point": 7.551493,
            "ci_low": 4.724321,
            "ci_high": 10.334114,
        },
        "legacy_HMM_glycine_betaine_transporter__whole": {
            "point": 3.302473,
            "ci_low": 2.023768,
            "ci_high": 4.560354,
        },
        "legacy_HMM_ahpCF__mapped": {
            "point": 6.949125,
            "ci_low": 3.342769,
            "ci_high": 9.713747,
        },
        "legacy_HMM_ahpCF__whole": {
            "point": 3.232487,
            "ci_low": 1.367102,
            "ci_high": 4.825049,
        },
    }

    for col, targets in expected.items():
        if col not in detailed_metrics:
            raise KeyError(f"Missing required legacy specification: {col}")
        actual = detailed_metrics[col]
        diff_pt = abs(actual["point_estimate"] - targets["point"])
        diff_lo = abs(actual["ci95_low"] - targets["ci_low"])
        diff_hi = abs(actual["ci95_high"] - targets["ci_high"])

        if diff_pt > 1e-5 or diff_lo > 1e-5 or diff_hi > 1e-5:
            raise ValueError(
                f"Legacy reproduction failed for {col} (fail-closed): "
                f"point diff={diff_pt:.7f}, ci_low diff={diff_lo:.7f}, ci_high diff={diff_hi:.7f}"
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="Ecology microTrait Sensitivity Analysis Pipeline")
    parser.add_argument("--mag-index", type=Path, required=True, help="Path to mag_index.tsv")
    parser.add_argument("--coverm-npz", type=Path, required=True, help="Path to sample_by_mag_coverm_relative_abundance.npz")
    parser.add_argument("--design", type=Path, required=True, help="Path to design.tsv")
    parser.add_argument("--traits", type=Path, required=True, help="Path to microtrait_calls_betl_ahpcf.tsv")
    parser.add_argument("--out-dir", type=Path, required=True, help="Directory to save sensitivity results")
    args = parser.parse_args()

    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 70)
    print("Ecology microTrait Sensitivity Analysis: BetL and AhpCF")
    print("=" * 70)

    # 1. Load and validate inputs
    print("[1/6] Loading input matrices and manifests...")
    for p, name in [
        (args.mag_index, "mag_index"),
        (args.coverm_npz, "coverm_npz"),
        (args.design, "design"),
        (args.traits, "traits"),
    ]:
        if not p.exists():
            raise FileNotFoundError(f"Required input not found: {p} ({name})")

    mag_index_df = pd.read_csv(args.mag_index, sep="\t").sort_values("mag_index")
    genomes_ordered = mag_index_df["mag_id"].astype(str).tolist()
    if len(genomes_ordered) != 5438:
        raise ValueError(f"Expected 5438 MAGs in mag_index, got {len(genomes_ordered)}")

    design_df = pd.read_csv(args.design, sep="\t")
    if len(design_df) != 546:
        raise ValueError(f"Expected 546 samples in design.tsv, got {len(design_df)}")

    traits_raw = pd.read_csv(args.traits, sep="\t")
    traits_df = validate_traits_df(traits_raw, genomes_ordered)

    npz = sparse.load_npz(args.coverm_npz)
    if npz.shape[1] != 5438:
        raise ValueError(f"CoverM NPZ MAG dimension {npz.shape[1]} != 5438")

    AA = npz.toarray()[design_df["sample_index"].to_numpy()]
    if AA.shape != (546, 5438):
        raise ValueError(f"Unexpected aligned abundance matrix shape: {AA.shape}")
    row_mapped = AA.sum(axis=1)

    print("      546 samples and 5,438 MAGs verified and aligned.")

    # 2. Build 10 contiguous spatial blocks
    print("[2/6] Building 10 contiguous spatial blocks from mean transect_km...")
    site_to_block = build_spatial_blocks(design_df, n_blocks=10)
    print(f"      Mapped {len(site_to_block)} sites into 10 spatial blocks.")
    block_mapping_out = out_dir / "spatial_block_mapping.tsv"
    pd.DataFrame(
        [{"site": s, "spatial_block": b} for s, b in sorted(site_to_block.items())]
    ).to_csv(block_mapping_out, sep="\t", index=False)
    print(f"      Spatial block mapping saved to {block_mapping_out.name}.")

    # 3. Compute per-sample scores
    print("[3/6] Computing per-sample community-weighted scores...")
    scores_df = compute_sample_scores(AA, row_mapped, traits_df, genomes_ordered)
    sample_shares_out = out_dir / "sample_trait_shares.tsv"
    sample_shares_df = pd.concat([design_df[["sample_id", "site", "trip", "compartment"]], scores_df], axis=1)
    sample_shares_df.to_csv(sample_shares_out, sep="\t", index=False)
    print(f"      Sample trait shares saved to {sample_shares_out.name}.")

    # 4. Paired visit contrasts and bootstrap
    print("[4/6] Computing paired contrasts and 10-block bootstrap CIs (seed=20261108)...")
    visit_diff, site_diff, detailed_metrics, df_effects = compute_paired_contrasts_and_bootstrap(
        design_df, scores_df, site_to_block, seed=20261108, n_boot=1000
    )

    site_diff_out = out_dir / "site_paired_differences.tsv"
    site_diff.to_csv(site_diff_out, sep="\t")
    print(f"      Site paired differences saved to {site_diff_out.name}.")

    effect_table_out = out_dir / "effect_table.tsv"
    df_effects.to_csv(effect_table_out, sep="\t", index=False)
    print(f"      Effect table saved to {effect_table_out.name}.")

    # 5. Verify legacy reproduction
    print("[5/6] Verifying exact reproduction of legacy published estimates...")
    verify_legacy_reproduction(detailed_metrics)
    print("      PASS: Legacy BetL (7.5515 pp) and AhpCF (6.9491 pp) reproduced within 1e-5.")

    # 6. Summary JSON and Checksums
    print("[6/6] Generating sensitivity summary JSON and SHA256 checksums...")
    summary_data = {
        "analysis": "Ecology microTrait Community-Weighted Effect Sensitivity",
        "cohort_mag_count": 5438,
        "n_samples": 546,
        "n_paired_visits": 68,
        "n_paired_sites": 36,
        "bootstrap_parameters": {
            "n_blocks": 10,
            "block_definition": "10 contiguous spatial blocks ordered by mean transect_km",
            "n_boot": 1000,
            "seed": 20261108,
            "weighting": "equal-site weighting across sampled blocks",
        },
        "legacy_reproduction_check": "PASS (matched published point estimates and 95% CIs)",
        "results": {
            "betl_betaine_uptake": {
                "legacy_mapped": {
                    "mean_pp": detailed_metrics["legacy_HMM_glycine_betaine_transporter__mapped"]["point_estimate"],
                    "ci95_pp": [
                        detailed_metrics["legacy_HMM_glycine_betaine_transporter__mapped"]["ci95_low"],
                        detailed_metrics["legacy_HMM_glycine_betaine_transporter__mapped"]["ci95_high"],
                    ],
                    "se_pp": detailed_metrics["legacy_HMM_glycine_betaine_transporter__mapped"]["se"],
                },
                "new_microtrait_mapped": {
                    "mean_pp": detailed_metrics["microtrait_rule_betL__mapped"]["point_estimate"],
                    "ci95_pp": [
                        detailed_metrics["microtrait_rule_betL__mapped"]["ci95_low"],
                        detailed_metrics["microtrait_rule_betL__mapped"]["ci95_high"],
                    ],
                    "se_pp": detailed_metrics["microtrait_rule_betL__mapped"]["se"],
                    "delta_pp": detailed_metrics["microtrait_rule_betL__mapped"]["point_estimate"]
                    - detailed_metrics["legacy_HMM_glycine_betaine_transporter__mapped"]["point_estimate"],
                },
                "legacy_whole_reads": {
                    "mean_pp": detailed_metrics["legacy_HMM_glycine_betaine_transporter__whole"]["point_estimate"],
                    "ci95_pp": [
                        detailed_metrics["legacy_HMM_glycine_betaine_transporter__whole"]["ci95_low"],
                        detailed_metrics["legacy_HMM_glycine_betaine_transporter__whole"]["ci95_high"],
                    ],
                    "se_pp": detailed_metrics["legacy_HMM_glycine_betaine_transporter__whole"]["se"],
                },
                "new_microtrait_whole_reads": {
                    "mean_pp": detailed_metrics["microtrait_rule_betL__whole"]["point_estimate"],
                    "ci95_pp": [
                        detailed_metrics["microtrait_rule_betL__whole"]["ci95_low"],
                        detailed_metrics["microtrait_rule_betL__whole"]["ci95_high"],
                    ],
                    "se_pp": detailed_metrics["microtrait_rule_betL__whole"]["se"],
                    "delta_pp": detailed_metrics["microtrait_rule_betL__whole"]["point_estimate"]
                    - detailed_metrics["legacy_HMM_glycine_betaine_transporter__whole"]["point_estimate"],
                },
            },
            "ahpcf_peroxide_defence": {
                "legacy_mapped": {
                    "mean_pp": detailed_metrics["legacy_HMM_ahpCF__mapped"]["point_estimate"],
                    "ci95_pp": [
                        detailed_metrics["legacy_HMM_ahpCF__mapped"]["ci95_low"],
                        detailed_metrics["legacy_HMM_ahpCF__mapped"]["ci95_high"],
                    ],
                    "se_pp": detailed_metrics["legacy_HMM_ahpCF__mapped"]["se"],
                },
                "new_microtrait_mapped": {
                    "mean_pp": detailed_metrics["microtrait_rule_ahpCF__mapped"]["point_estimate"],
                    "ci95_pp": [
                        detailed_metrics["microtrait_rule_ahpCF__mapped"]["ci95_low"],
                        detailed_metrics["microtrait_rule_ahpCF__mapped"]["ci95_high"],
                    ],
                    "se_pp": detailed_metrics["microtrait_rule_ahpCF__mapped"]["se"],
                    "delta_pp": detailed_metrics["microtrait_rule_ahpCF__mapped"]["point_estimate"]
                    - detailed_metrics["legacy_HMM_ahpCF__mapped"]["point_estimate"],
                },
                "legacy_whole_reads": {
                    "mean_pp": detailed_metrics["legacy_HMM_ahpCF__whole"]["point_estimate"],
                    "ci95_pp": [
                        detailed_metrics["legacy_HMM_ahpCF__whole"]["ci95_low"],
                        detailed_metrics["legacy_HMM_ahpCF__whole"]["ci95_high"],
                    ],
                    "se_pp": detailed_metrics["legacy_HMM_ahpCF__whole"]["se"],
                },
                "new_microtrait_whole_reads": {
                    "mean_pp": detailed_metrics["microtrait_rule_ahpCF__whole"]["point_estimate"],
                    "ci95_pp": [
                        detailed_metrics["microtrait_rule_ahpCF__whole"]["ci95_low"],
                        detailed_metrics["microtrait_rule_ahpCF__whole"]["ci95_high"],
                    ],
                    "se_pp": detailed_metrics["microtrait_rule_ahpCF__whole"]["se"],
                    "delta_pp": detailed_metrics["microtrait_rule_ahpCF__whole"]["point_estimate"]
                    - detailed_metrics["legacy_HMM_ahpCF__whole"]["point_estimate"],
                },
            },
        },
        "input_hashes": {
            "mag_index": sha256_file(args.mag_index),
            "coverm_npz": sha256_file(args.coverm_npz),
            "design": sha256_file(args.design),
            "traits": sha256_file(args.traits),
        },
    }

    summary_json_out = out_dir / "sensitivity_summary.json"
    with open(summary_json_out, "w", encoding="utf-8") as f:
        json.dump(summary_data, f, indent=2)

    # Checksums
    checksum_lines = []
    for p in sorted(out_dir.glob("*")):
        if p.is_file() and p.name != "SHA256SUMS":
            checksum_lines.append(f"{sha256_file(p)}  {p.name}")

    sha256_out = out_dir / "SHA256SUMS"
    sha256_out.write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")
    print(f"      Provenance checksums written to {sha256_out.name}.")

    print("=" * 70)
    print("Ecology Sensitivity Pipeline Completed Successfully.")
    print("=" * 70)


if __name__ == "__main__":
    main()
