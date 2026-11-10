"""
Unit and Integration Tests for Ecology microTrait Sensitivity Pipeline.

Verifies:
- Provenance checksums and artifact schemas.
- Exact legacy reproduction (7.5515 pp BetL, 6.9491 pp AhpCF).
- MicroTrait full rule effects (robustly positive, excluding zero).
- Recomputation from compact inputs without requiring raw bulk matrices.
- Invariance to ID / row shuffling.
- Strict fail-closed error handling on duplicate or missing IDs.
- Zero input yields zero effect ([0.0, 0.0] CI).
- Identical calls yield identical point estimates and bootstrap CIs.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
import pytest
import pandas as pd
import numpy as np

# Ensure code directory is on python path
CODE_DIR = Path(__file__).resolve().parents[1] / "code"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from run_ecology_sensitivity import (
    sha256_file,
    validate_traits_df,
    run_block_bootstrap,
    verify_legacy_reproduction,
)

BASE_DIR = Path(__file__).resolve().parents[1]
INPUTS_DIR = BASE_DIR / "inputs"
RESULTS_DIR = BASE_DIR / "results" / "ecology_sensitivity"


# =====================================================================
# 1. Artifact Integrity & Provenance Checksums
# =====================================================================

def test_sensitivity_results_exist_and_hashes_match():
    """Verify that all sensitivity artifacts exist and match SHA256SUMS."""
    sha256_path = RESULTS_DIR / "SHA256SUMS"
    assert sha256_path.exists(), "SHA256SUMS must exist in results/ecology_sensitivity"

    lines = sha256_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) >= 5, f"Expected at least 5 files in SHA256SUMS, found {len(lines)}"

    for line in lines:
        if not line.strip():
            continue
        expected_hash, fname = line.split(maxsplit=1)
        target_file = RESULTS_DIR / fname
        assert target_file.exists(), f"Result file missing: {fname}"
        actual_hash = sha256_file(target_file)
        assert actual_hash == expected_hash, f"Hash mismatch for {fname}: expected {expected_hash}, got {actual_hash}"


# =====================================================================
# 2. Exact Legacy Mean and CI Reproduction
# =====================================================================

def test_exact_legacy_mean_and_ci():
    """Verify exact reproduction of published legacy BetL and AhpCF effects."""
    effect_file = RESULTS_DIR / "effect_table.tsv"
    assert effect_file.exists()
    effects_df = pd.read_csv(effect_file, sep="\t")

    # 1. Legacy BetL mapped community
    row_betl_mapped = effects_df[
        (effects_df["raw_column"] == "legacy_HMM_glycine_betaine_transporter")
        & (effects_df["denominator"] == "mapped_community")
    ].iloc[0]
    assert abs(row_betl_mapped["point_estimate_pp"] - 7.551493) < 1e-5
    assert abs(row_betl_mapped["ci95_low_pp"] - 4.724321) < 1e-5
    assert abs(row_betl_mapped["ci95_high_pp"] - 10.334114) < 1e-5
    assert bool(row_betl_mapped["excludes_zero"]) is True

    # 2. Legacy BetL original reads
    row_betl_whole = effects_df[
        (effects_df["raw_column"] == "legacy_HMM_glycine_betaine_transporter")
        & (effects_df["denominator"] == "original_reads")
    ].iloc[0]
    assert abs(row_betl_whole["point_estimate_pp"] - 3.302473) < 1e-5
    assert abs(row_betl_whole["ci95_low_pp"] - 2.023768) < 1e-5
    assert abs(row_betl_whole["ci95_high_pp"] - 4.560354) < 1e-5
    assert bool(row_betl_whole["excludes_zero"]) is True

    # 3. Legacy AhpCF mapped community
    row_ahp_mapped = effects_df[
        (effects_df["raw_column"] == "legacy_HMM_ahpCF")
        & (effects_df["denominator"] == "mapped_community")
    ].iloc[0]
    assert abs(row_ahp_mapped["point_estimate_pp"] - 6.949125) < 1e-5
    assert abs(row_ahp_mapped["ci95_low_pp"] - 3.342769) < 1e-5
    assert abs(row_ahp_mapped["ci95_high_pp"] - 9.713747) < 1e-5
    assert bool(row_ahp_mapped["excludes_zero"]) is True

    # 4. Legacy AhpCF original reads
    row_ahp_whole = effects_df[
        (effects_df["raw_column"] == "legacy_HMM_ahpCF")
        & (effects_df["denominator"] == "original_reads")
    ].iloc[0]
    assert abs(row_ahp_whole["point_estimate_pp"] - 3.232487) < 1e-5
    assert abs(row_ahp_whole["ci95_low_pp"] - 1.367102) < 1e-5
    assert abs(row_ahp_whole["ci95_high_pp"] - 4.825049) < 1e-5
    assert bool(row_ahp_whole["excludes_zero"]) is True


# =====================================================================
# 3. MicroTrait Full Rule Robustness
# =====================================================================

def test_microtrait_effects_robustly_positive():
    """Verify new microTrait BetL and AhpCF rules remain robustly positive."""
    effects_df = pd.read_csv(RESULTS_DIR / "effect_table.tsv", sep="\t")

    # microTrait BetL mapped
    row_betl_mapped = effects_df[
        (effects_df["raw_column"] == "microtrait_rule_betL")
        & (effects_df["denominator"] == "mapped_community")
    ].iloc[0]
    assert abs(row_betl_mapped["point_estimate_pp"] - 6.906226) < 1e-5
    assert row_betl_mapped["ci95_low_pp"] > 4.0
    assert bool(row_betl_mapped["excludes_zero"]) is True

    # microTrait BetL original reads
    row_betl_whole = effects_df[
        (effects_df["raw_column"] == "microtrait_rule_betL")
        & (effects_df["denominator"] == "original_reads")
    ].iloc[0]
    assert abs(row_betl_whole["point_estimate_pp"] - 3.002153) < 1e-5
    assert row_betl_whole["ci95_low_pp"] > 1.5
    assert bool(row_betl_whole["excludes_zero"]) is True

    # microTrait AhpCF mapped
    row_ahp_mapped = effects_df[
        (effects_df["raw_column"] == "microtrait_rule_ahpCF")
        & (effects_df["denominator"] == "mapped_community")
    ].iloc[0]
    assert abs(row_ahp_mapped["point_estimate_pp"] - 6.930050) < 1e-5
    assert row_ahp_mapped["ci95_low_pp"] > 3.0
    assert bool(row_ahp_mapped["excludes_zero"]) is True


# =====================================================================
# 4. Recomputation from Compact Inputs
# =====================================================================

def test_recompute_from_compact_inputs():
    """Verify that effect estimates and CIs can be recomputed from compact paired site differences."""
    site_diff_file = INPUTS_DIR / "site_paired_differences.tsv"
    block_map_file = INPUTS_DIR / "spatial_block_mapping.tsv"
    assert site_diff_file.exists(), "Compact site_paired_differences.tsv must exist in inputs"
    assert block_map_file.exists(), "Compact spatial_block_mapping.tsv must exist in inputs"

    site_diff = pd.read_csv(site_diff_file, sep="\t", index_col=0)
    block_map_df = pd.read_csv(block_map_file, sep="\t")
    site_to_block = dict(zip(block_map_df["site"].astype(str), block_map_df["spatial_block"].astype(str)))

    detailed_metrics, df_effects = run_block_bootstrap(
        site_diff, site_to_block, seed=20261108, n_boot=1000, n_visits=68
    )

    # Check that verify_legacy_reproduction passes without error
    verify_legacy_reproduction(detailed_metrics)

    # Verify point estimates and CIs match effect_table.tsv
    expected_effects = pd.read_csv(RESULTS_DIR / "effect_table.tsv", sep="\t")
    pd.testing.assert_frame_equal(
        df_effects[["point_estimate_pp", "ci95_low_pp", "ci95_high_pp", "se_pp"]],
        expected_effects[["point_estimate_pp", "ci95_low_pp", "ci95_high_pp", "se_pp"]],
        check_exact=True,
    )


# =====================================================================
# 5. ID Shuffle Invariance
# =====================================================================

def test_id_shuffle_invariance():
    """Verify that shuffling the row order of site differences produces bit-for-bit identical results."""
    site_diff = pd.read_csv(INPUTS_DIR / "site_paired_differences.tsv", sep="\t", index_col=0)
    block_map_df = pd.read_csv(INPUTS_DIR / "spatial_block_mapping.tsv", sep="\t")
    site_to_block = dict(zip(block_map_df["site"].astype(str), block_map_df["spatial_block"].astype(str)))

    # Original
    m_orig, df_orig = run_block_bootstrap(site_diff, site_to_block, seed=20261108, n_boot=1000)

    # Shuffled order of sites
    rng = np.random.default_rng(42)
    shuffled_sites = rng.permutation(site_diff.index.tolist())
    site_diff_shuffled = site_diff.loc[shuffled_sites]

    m_shuff, df_shuff = run_block_bootstrap(site_diff_shuffled, site_to_block, seed=20261108, n_boot=1000)

    pd.testing.assert_frame_equal(df_orig, df_shuff, check_exact=True)


# =====================================================================
# 6. Duplicate and Missing ID Validation Failure
# =====================================================================

def test_duplicate_and_missing_mag_ids_fail():
    """Verify fail-closed validation on duplicated or missing MAG IDs."""
    genomes = [f"mag_{i}" for i in range(10)]

    # Missing MAG ID
    incomplete_df = pd.DataFrame({"mag": genomes[:9], "trait": np.ones(9)})
    with pytest.raises(ValueError, match="do not match genomes_ordered exactly"):
        validate_traits_df(incomplete_df, genomes)

    # Duplicate MAG ID
    duplicate_df = pd.DataFrame({"mag": genomes[:9] + [genomes[0]], "trait": np.ones(10)})
    with pytest.raises(ValueError, match="Duplicate MAG IDs"):
        validate_traits_df(duplicate_df, genomes)

    # Missing 'mag' column
    bad_col_df = pd.DataFrame({"wrong_col": genomes, "trait": np.ones(10)})
    with pytest.raises(KeyError, match="missing 'mag' column"):
        validate_traits_df(bad_col_df, genomes)


def test_missing_site_or_block_fail():
    """Verify fail-closed validation if sites are missing from spatial block mapping."""
    site_diff = pd.read_csv(INPUTS_DIR / "site_paired_differences.tsv", sep="\t", index_col=0)
    block_map_df = pd.read_csv(INPUTS_DIR / "spatial_block_mapping.tsv", sep="\t")
    site_to_block = dict(zip(block_map_df["site"].astype(str), block_map_df["spatial_block"].astype(str)))

    # Remove one site from block mapping
    del site_to_block[list(site_to_block.keys())[0]]
    with pytest.raises(ValueError, match="Sites missing from spatial block mapping"):
        run_block_bootstrap(site_diff, site_to_block)

    # Unexpected site count
    with pytest.raises(ValueError, match="Expected exactly 36 paired sites"):
        run_block_bootstrap(site_diff.iloc[:30], site_to_block)


# =====================================================================
# 7. All Zeros Yield Zero Effect
# =====================================================================

def test_all_zeros_yield_zero():
    """Verify that a vector of zeros yields point estimate 0.0 and CI [0.0, 0.0]."""
    site_diff = pd.read_csv(INPUTS_DIR / "site_paired_differences.tsv", sep="\t", index_col=0)
    block_map_df = pd.read_csv(INPUTS_DIR / "spatial_block_mapping.tsv", sep="\t")
    site_to_block = dict(zip(block_map_df["site"].astype(str), block_map_df["spatial_block"].astype(str)))

    zero_df = pd.DataFrame(
        {"zero_trait__mapped": np.zeros(len(site_diff))},
        index=site_diff.index,
    )

    metrics, df_eff = run_block_bootstrap(zero_df, site_to_block, seed=20261108, n_boot=1000)
    row = df_eff.iloc[0]
    assert row["point_estimate_pp"] == 0.0
    assert row["ci95_low_pp"] == 0.0
    assert row["ci95_high_pp"] == 0.0
    assert row["se_pp"] == 0.0
    assert bool(row["excludes_zero"]) is False


# =====================================================================
# 8. Same Calls Yield Identical Effects
# =====================================================================

def test_same_calls_yield_same_effects():
    """Verify that identical trait inputs yield identical estimates and CIs."""
    site_diff = pd.read_csv(INPUTS_DIR / "site_paired_differences.tsv", sep="\t", index_col=0)
    block_map_df = pd.read_csv(INPUTS_DIR / "spatial_block_mapping.tsv", sep="\t")
    site_to_block = dict(zip(block_map_df["site"].astype(str), block_map_df["spatial_block"].astype(str)))

    clone_df = pd.DataFrame(
        {
            "trait_A__mapped": site_diff["legacy_HMM_glycine_betaine_transporter__mapped"],
            "trait_B__mapped": site_diff["legacy_HMM_glycine_betaine_transporter__mapped"],
        },
        index=site_diff.index,
    )

    metrics, df_eff = run_block_bootstrap(clone_df, site_to_block, seed=20261108, n_boot=1000)
    assert len(df_eff) == 2
    row_a = df_eff.iloc[0]
    row_b = df_eff.iloc[1]

    assert row_a["point_estimate_pp"] == row_b["point_estimate_pp"]
    assert row_a["ci95_low_pp"] == row_b["ci95_low_pp"]
    assert row_a["ci95_high_pp"] == row_b["ci95_high_pp"]
    assert row_a["se_pp"] == row_b["se_pp"]


# =====================================================================
# 9. Summary Metadata Validation
# =====================================================================

def test_summary_metadata():
    """Verify structure and contents of sensitivity_summary.json."""
    summary_path = RESULTS_DIR / "sensitivity_summary.json"
    assert summary_path.exists()
    data = json.loads(summary_path.read_text(encoding="utf-8"))

    assert data["cohort_mag_count"] == 5438
    assert data["n_samples"] == 546
    assert data["n_paired_visits"] == 68
    assert data["n_paired_sites"] == 36
    assert data["bootstrap_parameters"]["n_blocks"] == 10
    assert data["bootstrap_parameters"]["n_boot"] == 1000
    assert data["bootstrap_parameters"]["seed"] == 20261108
    assert "input_hashes" in data
    assert len(data["input_hashes"]) == 4
