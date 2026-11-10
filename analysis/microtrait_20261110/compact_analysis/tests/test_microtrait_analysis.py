"""
Unit and Integration Tests for Empty Quarter 5,438-MAG MicroTrait Analysis.

Tests cover:
- Real artifact integrity, schemas, and SHA256 checksums.
- Exact cohort ID coverage (5,438 MAGs, 0 missing, 0 extra).
- Correct positivity evaluation (val > 0, sums of rules).
- High-quality subset denominators (completeness >= 90, contamination <= 5; N=2259).
- Canonical taxonomy breakdowns (Bacteria N=4847, Archaea N=591).
- Thermoplasmatota class counts (SW-10-69-26: 185; E2: 51; Thermoplasmata: 1).
- Ecology 41-rule BetL and AhpCF concordance audit and unresolved status.
- Absent HMM models (aphA, phoN) and phosphatase safe-NA count (2452).
- Meaningful fixture tests:
    * Bad-ID fixture (duplicate, missing, extra IDs detected).
    * Missing coverage fixture (incomplete row coverage detected).
    * Positivity edge-case fixture (verifying val > 0 logic).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
import pytest
import pandas as pd
import numpy as np

# Add code directory to path
CODE_DIR = Path(__file__).resolve().parents[1] / "code"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from run_microtrait_analysis import (
    ANALYSIS_DIR,
    INPUTS_DIR,
    RESULTS_DIR,
    G2_TRAIT_MAP,
    G3_CO2_TRAIT_MAP,
    ALL_TRAIT_MAP,
    sha256_file,
    audit_cohort_id_coverage,
    build_per_mag_selected_traits,
    compute_group_summary,
    generate_thermoplasmatota_class_summaries,
    compare_ecology_41rules,
)


# =====================================================================
# Real Artifact Integrity & Provenance
# =====================================================================

def test_sha256sums_manifest_valid():
    """Verify that every file listed in results/SHA256SUMS exists and matches hash."""
    sha256_file_path = RESULTS_DIR / "SHA256SUMS"
    assert sha256_file_path.exists(), "SHA256SUMS file must exist"

    lines = sha256_file_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) >= 15, f"Expected at least 15 entries in SHA256SUMS, got {len(lines)}"

    for line in lines:
        if not line or line.startswith("#"):
            continue
        expected_hash, rel_path = line.split(maxsplit=1)
        target_path = ANALYSIS_DIR / rel_path.strip()
        assert target_path.exists(), f"Target file does not exist: {target_path}"
        actual_hash = sha256_file(target_path)
        assert actual_hash == expected_hash, f"Hash mismatch for {rel_path}: {actual_hash} != {expected_hash}"


def test_cohort_id_coverage_audit_passes():
    """Verify cohort_id_coverage_audit.tsv confirms exact 100% 5438 coverage."""
    audit_path = RESULTS_DIR / "cohort_id_coverage_audit.tsv"
    assert audit_path.exists()
    df_audit = pd.read_csv(audit_path, sep="\t")

    assert len(df_audit) == 6
    assert (df_audit["total_rows"] == 5438).all()
    assert (df_audit["unique_ids"] == 5438).all()
    assert (df_audit["missing_from_cohort_count"] == 0).all()
    assert (df_audit["extra_not_in_cohort_count"] == 0).all()
    assert (df_audit["exact_cohort_match"] == True).all()
    assert (df_audit["status"] == "PASS").all()


def test_per_mag_table_schema_and_contents():
    """Verify per_mag_selected_traits.tsv.gz columns, types, and dimensions."""
    table_path = RESULTS_DIR / "per_mag_selected_traits.tsv.gz"
    assert table_path.exists()
    df = pd.read_csv(table_path, sep="\t")

    assert len(df) == 5438
    assert df["mag"].is_unique

    # Check taxonomy columns
    for col in ["canonical_domain", "canonical_phylum", "canonical_class",
                "canonical_order", "canonical_family", "canonical_genus", "canonical_species"]:
        assert col in df.columns
        assert df[col].notna().all()

    # Check G2 and G3 trait columns
    for trait_key in ALL_TRAIT_MAP.keys():
        val_col = f"{trait_key}_val"
        pos_col = f"{trait_key}_pos"
        assert val_col in df.columns
        assert pos_col in df.columns
        # Positivity strictly reflects val > 0
        expected_pos = (df[val_col] > 0).astype(int)
        assert (df[pos_col] == expected_pos).all()
        # Positivity values must only be 0 or 1
        assert set(df[pos_col].unique()).issubset({0, 1})


def test_denominators_and_sensitivity_subset():
    """Verify denominators: all cohort (5438) and HQ sensitivity (2259)."""
    df = pd.read_csv(RESULTS_DIR / "per_mag_selected_traits.tsv.gz", sep="\t")

    # High quality condition: completeness >= 90 and contamination <= 5
    hq_mask = (df["checkm2_completeness"] >= 90.0) & (df["checkm2_contamination"] <= 5.0)
    assert (df["is_hq_comp90_cont5"] == hq_mask.astype(int)).all()
    assert hq_mask.sum() == 2259

    # Domain breakdown
    assert (df["canonical_domain"] == "d__Bacteria").sum() == 4847
    assert (df["canonical_domain"] == "d__Archaea").sum() == 591

    assert ((df["canonical_domain"] == "d__Bacteria") & hq_mask).sum() == 2140
    assert ((df["canonical_domain"] == "d__Archaea") & hq_mask).sum() == 119


def test_thermoplasmatota_exact_class_counts():
    """Verify exact Thermoplasmatota class counts and trait positivity."""
    df_thermo = pd.read_csv(RESULTS_DIR / "thermoplasmatota_class_summaries.tsv", sep="\t")
    assert len(df_thermo) == 8  # 4 rows for 'all', 4 rows for 'hq_comp90_cont5'

    # Check 'all' subset
    all_rows = df_thermo[df_thermo["subset"] == "all"].set_index("canonical_class")
    assert all_rows.loc["p__Thermoplasmatota_total", "n_genomes"] == 237
    assert all_rows.loc["c__SW-10-69-26", "n_genomes"] == 185
    assert all_rows.loc["c__E2", "n_genomes"] == 51
    assert all_rows.loc["c__Thermoplasmata", "n_genomes"] == 1

    # Check HQ subset
    hq_rows = df_thermo[df_thermo["subset"] == "hq_comp90_cont5"].set_index("canonical_class")
    assert hq_rows.loc["p__Thermoplasmatota_total", "n_genomes"] == 59
    assert hq_rows.loc["c__SW-10-69-26", "n_genomes"] == 43
    assert hq_rows.loc["c__E2", "n_genomes"] == 15
    assert hq_rows.loc["c__Thermoplasmata", "n_genomes"] == 1

    # Protein degradation and amino acid transport are 100% across all Thermoplasmatota
    assert all_rows.loc["p__Thermoplasmatota_total", "g2_protein_degradation_n_pos"] == 237
    assert all_rows.loc["p__Thermoplasmatota_total", "g2_free_amino_acid_transport_n_pos"] == 237
    assert hq_rows.loc["p__Thermoplasmatota_total", "g2_protein_degradation_n_pos"] == 59
    assert hq_rows.loc["p__Thermoplasmatota_total", "g2_free_amino_acid_transport_n_pos"] == 59

    # Peptide transport: 10 in all (all in SW-10-69-26), 1 in HQ
    assert all_rows.loc["p__Thermoplasmatota_total", "g2_peptide_transport_n_pos"] == 10
    assert all_rows.loc["c__SW-10-69-26", "g2_peptide_transport_n_pos"] == 10
    assert all_rows.loc["c__E2", "g2_peptide_transport_n_pos"] == 0
    assert hq_rows.loc["p__Thermoplasmatota_total", "g2_peptide_transport_n_pos"] == 1
    assert hq_rows.loc["c__SW-10-69-26", "g2_peptide_transport_n_pos"] == 1

    # CO2 fixation: 2 in all (both 3-HP/4-HB in SW-10-69-26), 1 in HQ
    assert all_rows.loc["p__Thermoplasmatota_total", "g2_co2_fixation_n_pos"] == 2
    assert all_rows.loc["c__SW-10-69-26", "g3_co2_3_hydroxypropionate_4_hydroxybutyrate_n_pos"] == 2
    assert hq_rows.loc["c__SW-10-69-26", "g3_co2_3_hydroxypropionate_4_hydroxybutyrate_n_pos"] == 1


def test_selected_traits_upstream_rules_audit():
    """Verify constituent upstream rules table captures all target traits and HMMs."""
    audit_path = RESULTS_DIR / "selected_traits_upstream_rules_audit.tsv"
    assert audit_path.exists()
    df_rules = pd.read_csv(audit_path, sep="\t")

    # Verify G2 targets present
    assert "Resource Acquisition:Substrate uptake:peptide transport" in df_rules["target_trait_name"].values
    assert "Resource Acquisition:Substrate uptake:free amino acids transport" in df_rules["target_trait_name"].values
    assert "Resource Acquisition:Substrate degradation:simple compound degradation:protein degradation" in df_rules["target_trait_name"].values
    assert "Resource Acquisition:Substrate assimilation:C1 compounds:CO2 fixation" in df_rules["target_trait_name"].values

    # Verify peptide transport has 6 rules
    pep_rules = df_rules[df_rules["target_trait_short"] == "g2_peptide_transport"]
    assert len(pep_rules) == 6
    assert set(pep_rules["rule_name"]).issubset({"dpp-1_key", "dpp-2_key", "gsi_key", "opp-1_key", "sap_key", "tc.pot"})

    # Verify CO2 fixation rules (7 explicit rules/pathways)
    co2_rules = df_rules[df_rules["target_trait_short"] == "g2_co2_fixation"]
    assert len(co2_rules) == 7
    assert set(co2_rules["rule_name"]).issubset({
        "cc_key", "3hpb1_key1", "3hp4hb_key1", "dicarb-4hb_CO2fixation",
        "rac_key1", "rca_key1", "carboxysome"
    })

    # Verify all constituent HMMs are non-empty strings
    assert df_rules["constituent_hmms"].str.len().gt(0).all()


def test_ecology_concordance_report_and_numbers():
    """Verify ecology 41-rule BetL and AhpCF comparison numbers and unresolved flag."""
    rep_path = RESULTS_DIR / "ecology_concordance_report.json"
    assert rep_path.exists()
    with open(rep_path, "r", encoding="utf-8") as f:
        rep = json.load(f)

    # BetL
    betl = rep["betl_comparison"]
    assert betl["published_logical_rule"] == "(('betL'))"
    assert betl["microtrait_logical_rule"] == "('betL')"
    assert betl["ecology_positive_count"] == 415
    assert betl["microtrait_positive_count"] == 341
    assert betl["concordant_positive_count"] == 341
    assert betl["concordant_negative_count"] == 5023
    assert betl["discordant_count"] == 74
    assert betl["ecology_pos_microtrait_neg"] == 74
    assert betl["microtrait_pos_ecology_neg"] == 0

    # AhpCF
    ahp = rep["ahpcf_comparison"]
    assert ahp["published_logical_rule"] == "((('ahpC_1') | ('ahpC_2') | ('ahpC_3')) & (('ahpF')))"
    assert ahp["microtrait_logical_rule"] == "(('ahpC_1' | 'ahpC_2' | 'ahpC_3') & ('ahpF'))"
    assert ahp["ecology_positive_count"] == 525
    assert ahp["microtrait_positive_count"] == 522
    assert ahp["concordant_positive_count"] == 522
    assert ahp["concordant_negative_count"] == 4913
    assert ahp["discordant_count"] == 3
    assert ahp["ecology_pos_microtrait_neg"] == 3
    assert ahp["microtrait_pos_ecology_neg"] == 0

    # Phosphatase & Absent models
    phos = rep["phosphatase_and_unassayed_models"]
    assert phos["aphA_status"] == "unassayed_model_missing_from_release"
    assert phos["phoN_status"] == "unassayed_model_missing_from_release"
    assert phos["phosphatase_safe_na_count"] == 2452
    assert phos["phosphatase_confirmed_present_count"] == 2986
    assert phos["phosphatase_total_evaluated"] == 5438


# =====================================================================
# Meaningful Fixture Tests: Bad IDs, Missing Coverage, Edge Cases
# =====================================================================

def test_fixture_bad_id_duplicate():
    """Verify that audit_cohort_id_coverage detects duplicate IDs in cohort."""
    cohort_df = pd.read_csv(INPUTS_DIR / "cohort_manifest_5438.tsv", sep="\t")
    # Duplicate first MAG
    bad_cohort = pd.concat([cohort_df, cohort_df.iloc[:1]], ignore_index=True)
    g2_df = pd.read_csv(INPUTS_DIR / "trait_matrixatgranularity2.tsv.gz", sep="\t")
    g3_df = pd.read_csv(INPUTS_DIR / "trait_matrixatgranularity3.tsv.gz", sep="\t")
    rule_df = pd.read_csv(INPUTS_DIR / "rule_matrix.tsv.gz", sep="\t")
    phos_df = pd.read_csv(INPUTS_DIR / "phosphatase_and_model_coverage_5438.tsv", sep="\t")
    eco_df = pd.read_csv(INPUTS_DIR / "ecology_genome_panels_hmm.tsv", sep="\t")

    with pytest.raises(ValueError, match="Cohort manifest has 5439 MAGs"):
        audit_cohort_id_coverage(bad_cohort, g2_df, g3_df, rule_df, phos_df, eco_df)


def test_fixture_bad_id_mismatched_mag():
    """Verify that audit_cohort_id_coverage detects mismatched / corrupt MAG IDs."""
    cohort_df = pd.read_csv(INPUTS_DIR / "cohort_manifest_5438.tsv", sep="\t")
    g2_df = pd.read_csv(INPUTS_DIR / "trait_matrixatgranularity2.tsv.gz", sep="\t")
    g3_df = pd.read_csv(INPUTS_DIR / "trait_matrixatgranularity3.tsv.gz", sep="\t")
    rule_df = pd.read_csv(INPUTS_DIR / "rule_matrix.tsv.gz", sep="\t")
    phos_df = pd.read_csv(INPUTS_DIR / "phosphatase_and_model_coverage_5438.tsv", sep="\t")
    eco_df = pd.read_csv(INPUTS_DIR / "ecology_genome_panels_hmm.tsv", sep="\t").copy()

    # Corrupt one ID in eco_df
    eco_df.loc[0, "genome"] = "CORRUPT_UNKNOWN_MAG_ID_9999"

    with pytest.raises(ValueError, match="Cohort coverage validation failed for ecology_genome_panels_hmm.tsv"):
        audit_cohort_id_coverage(cohort_df, g2_df, g3_df, rule_df, phos_df, eco_df)


def test_fixture_missing_coverage_dropped_rows():
    """Verify that dropped rows in any input matrix fail validation."""
    cohort_df = pd.read_csv(INPUTS_DIR / "cohort_manifest_5438.tsv", sep="\t")
    g2_df = pd.read_csv(INPUTS_DIR / "trait_matrixatgranularity2.tsv.gz", sep="\t").iloc[:-5]  # drop 5 rows
    g3_df = pd.read_csv(INPUTS_DIR / "trait_matrixatgranularity3.tsv.gz", sep="\t")
    rule_df = pd.read_csv(INPUTS_DIR / "rule_matrix.tsv.gz", sep="\t")
    phos_df = pd.read_csv(INPUTS_DIR / "phosphatase_and_model_coverage_5438.tsv", sep="\t")
    eco_df = pd.read_csv(INPUTS_DIR / "ecology_genome_panels_hmm.tsv", sep="\t")

    with pytest.raises(ValueError, match="Cohort coverage validation failed for trait_matrixatgranularity2.tsv.gz"):
        audit_cohort_id_coverage(cohort_df, g2_df, g3_df, rule_df, phos_df, eco_df)


def test_fixture_positivity_edge_cases():
    """Verify strict positivity rule: val > 0 on edge case synthetic inputs."""
    cohort_toy = pd.DataFrame({
        "mag": ["M1", "M2", "M3", "M4"],
        "canonical_domain": ["d__Bacteria"] * 4,
        "canonical_phylum": ["p__Bacillota"] * 4,
        "canonical_class": ["c__Bacilli"] * 4,
        "canonical_order": ["o__Bacillales"] * 4,
        "canonical_family": ["f__Bacillaceae"] * 4,
        "canonical_genus": ["g__Bacillus"] * 4,
        "canonical_species": ["s__subtilis"] * 4,
        "checkm2_completeness": [95.0, 85.0, 92.0, 99.0],
        "checkm2_contamination": [2.0, 1.0, 7.0, 0.0],
        "quality_tier": ["high", "medium", "medium", "high"],
    })

    # Edge cases: 0, negative (-1), positive int (3), positive float (0.5)
    g2_toy = pd.DataFrame({
        "id": ["M1", "M2", "M3", "M4"],
        G2_TRAIT_MAP["g2_peptide_transport"]: [0, 0, 3, 1],
        G2_TRAIT_MAP["g2_free_amino_acid_transport"]: [-1, 0, 0, 2],
        G2_TRAIT_MAP["g2_protein_degradation"]: [5, 10, 1, 2],
        G2_TRAIT_MAP["g2_co2_fixation"]: [0, 0, 0, 1],
    })

    g3_toy = pd.DataFrame({"id": ["M1", "M2", "M3", "M4"]})
    for col in G3_CO2_TRAIT_MAP.values():
        g3_toy[col] = [0, 0, 0, 0]

    phos_toy = pd.DataFrame({
        "mag": ["M1", "M2", "M3", "M4"],
        "phoA_hits": [0, 1, 0, 1],
        "phoD_hits": [0, 0, 0, 1],
        "aphA_status": ["unassayed"] * 4,
        "phoN_status": ["unassayed"] * 4,
        "phosphatase_raw_rule_value": [0, 1, 0, 1],
        "phosphatase_coverage_flag": ["indeterminate", "confirmed", "indeterminate", "confirmed"],
        "phosphatase_interpretation_safe_value": ["NA", "1", "NA", "1"],
    })

    res = build_per_mag_selected_traits(cohort_toy, g2_toy, g3_toy, phos_toy)

    # Check peptide transport positivity: M1=0 -> 0, M2=0 -> 0, M3=3 -> 1, M4=1 -> 1
    assert res["g2_peptide_transport_pos"].tolist() == [0, 0, 1, 1]

    # Check free amino acid transport: M1=-1 -> 0, M2=0 -> 0, M3=0 -> 0, M4=2 -> 1
    assert res["g2_free_amino_acid_transport_pos"].tolist() == [0, 0, 0, 1]

    # Check HQ sensitivity: comp >= 90 & cont <= 5
    # M1: 95, 2 -> 1
    # M2: 85, 1 -> 0 (comp < 90)
    # M3: 92, 7 -> 0 (cont > 5)
    # M4: 99, 0 -> 1
    assert res["is_hq_comp90_cont5"].tolist() == [1, 0, 0, 1]
