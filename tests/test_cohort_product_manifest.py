"""Automated tests for the shared cohort/product provenance manifest.

Tests both real canonical tables and adversarial fixtures for:
1. Same-count wrong-member joins (swapping cohort membership between libraries
   while keeping cohort totals unchanged).
2. Specimen, campaign, compartment, and dune-zone join integrity.
3. Altered cohort counts across the 551 -> 550 -> 546 -> 545 -> 442 -> 441
   hierarchy.
4. Strict MIMAG (<10% contamination) vs operational dRep (<=10% contamination)
   quality boundary on 48Dr2__self_SemiBin_25.
5. Distinct versioned protein products (19,186,792 Bakta vs 20,451,986
   Pyrodigal) and CoverM mapping products without version conflation or false
   equivalence claims.
6. Explicit failure on missing staged inputs with no output-as-input or
   home-directory fallback.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
import shutil

import pytest

from scripts.release.build_cohort_product_manifest import (
    build_cohorts,
    classify_drep_operational,
    classify_mimag_strict,
    read_tsv,
    reconcile_taxonomy_snapshots,
    validate_cohort_joins_and_counts,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_real_inputs(root: Path = PROJECT_ROOT):
    libraries = read_tsv(root / "metadata/metagenome/canonical/library_metadata.tsv")
    representatives = read_tsv(
        root / "metadata/metagenome/canonical/refined_representatives.tsv"
    )
    ena_genomes = read_tsv(
        root / "metadata/metagenome/canonical/ena_genome_accessions.tsv"
    )
    legacy_150_rows = read_tsv(
        root / "evidence/mag-catalogue-20261024/source/metagenome_sample_meta_150.tsv"
    )
    wgs_runs = read_tsv(
        root / "evidence/mag-catalogue-20261024/source/ena_deposit/wgs_runs.tsv"
    )
    amplicon_1186 = read_tsv(root / "metadata/cohorts/source/included_samples_1186.tsv")
    site_dunes = read_tsv(root / "metadata/cohorts/source/site_dune_zones.tsv")
    shotgun_qc_source = read_tsv(
        root / "metadata/cohorts/source/shotgun_mapping_qc_source.tsv"
    )
    shotgun_rows, mimag_rows, manifest = build_cohorts(root)
    return (
        libraries,
        shotgun_rows,
        amplicon_1186,
        site_dunes,
        shotgun_qc_source,
        legacy_150_rows,
        representatives,
        ena_genomes,
        wgs_runs,
        mimag_rows,
        manifest,
    )


def test_real_cohort_product_manifest_matches_canonical_sources() -> None:
    shotgun_rows, mimag_rows, manifest = build_cohorts(PROJECT_ROOT)
    assert len(shotgun_rows) == 551
    assert len(mimag_rows) == 5438

    on_disk = json.loads(
        (PROJECT_ROOT / "metadata/cohorts/cohort_product_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert (
        on_disk["companion_manuscripts"]["ecology"]["title"]
        == "Microbial biogeography and functional differentiation across the Rub' al-Khali"
    )
    assert (
        on_disk["companion_manuscripts"]["proteome"]["title"]
        == "Widespread desert archaea harbour an export-enriched unknown protein repertoire"
    )

    cohorts = on_disk["cohorts"]
    assert cohorts["EQ-SPECIMEN-SOURCE-2550"]["count"] == 2550
    assert cohorts["EQ-SPECIMEN-KG-2516"]["count"] == 2516
    assert cohorts["EQ-AMP-CANONICAL-1271"]["count"] == 1271
    assert cohorts["EQ-AMP-QC-1237"]["count"] == 1237
    assert cohorts["EQ-AMP-PRIMARY-1227"]["count"] == 1227
    assert cohorts["EQ-AMP-DEDUP-1186"]["count"] == 1186
    assert cohorts["EQ-WGS-LIBS-551"]["count"] == 551
    assert cohorts["EQ-WGS-LIBS-551"]["site_codes"] == 61
    assert cohorts["EQ-WGS-LIBS-551"]["primary_sites"] == 59
    assert cohorts["EQ-WGS-NONZERO-550"]["count"] == 550
    assert cohorts["EQ-WGS-CORE-546"]["count"] == 546
    assert cohorts["EQ-WGS-CORE-546"]["sites"] == 59
    assert cohorts["EQ-WGS-CORE-MODEL-545"]["count"] == 545
    assert cohorts["EQ-MATCHED-AMP-WGS-442"]["count"] == 442
    assert cohorts["EQ-MATCHED-AMP-WGS-442"]["sites"] == 58
    assert cohorts["EQ-MATCHED-MODEL-441"]["count"] == 441
    assert cohorts["EQ-WGS-ARCHAEA-PAIRED-193"]["count"] == 193
    assert cohorts["EQ-WGS-LEGACY-150"]["count"] == 150

    for removed_key in (
        "archaeal_protein_families_21760",
        "archaeal_structural_models_3165",
        "archaeal_metabolic_candidates_7381",
        "EQ-PROT-FAM-21760",
    ):
        assert removed_key not in cohorts

    arch_prod = on_disk["products"]["EQ-COVERM-ARCHAEA-COMP-v1.0.0"]
    assert "Separate sensitivity analysis" in arch_prod["mapq20_sensitivity_mode"]
    assert "not applied as a filter to every primary breadth-gated result" in arch_prod["mapq20_sensitivity_mode"]

    tax_prod = on_disk["products"]["EQ-TAX-LEGACY-ANALYTICAL-v0"]
    assert tax_prod["equivalence_with_canonical_gtdb_r232"] == "FROZEN_HISTORICAL_SNAPSHOT_NOT_IDENTICAL"
    rec_sum = tax_prod["reconciliation_with_canonical_gtdb_r232"]
    assert rec_sum["total_representatives"] == 5438
    assert rec_sum["whole_taxonomy_strings_differing"] == 1898
    assert rec_sum["rank_differences"] == {
        "domain": 0,
        "phylum": 247,
        "class": 34,
        "order": 220,
        "family": 511,
        "genus": 1124,
        "species": 46,
    }
    th_sum = rec_sum["thermoplasmatota_reconciliation"]
    assert th_sum["count"] == 237
    assert th_sum["whole_taxonomy_strings_differing"] == 42
    assert th_sum["canonical_classes"] == {"SW-10-69-26": 185, "E2": 51, "Thermoplasmata": 1}
    assert th_sum["canonical_named_orders"] == 4
    assert th_sum["canonical_unassigned_orders"] == 2
    assert th_sum["canonical_named_genera"] == 19
    assert th_sum["canonical_unassigned_genera"] == 135
    assert th_sum["legacy_named_orders"] == 4
    assert th_sum["legacy_unassigned_orders"] == 0
    assert th_sum["legacy_named_genera"] == 14
    assert th_sum["legacy_unassigned_genera"] == 139

    ko_prod = on_disk["products"]["EQ-KO-LEGACY-ANALYTICAL-v0"]
    assert ko_prod["sequence_equivalence_with_bakta"] == "UNVERIFIED_SEPARATE_PRODUCTS"
    assert ko_prod["distinct_kos"] == 11386
    assert ko_prod["shared_kos_with_picrust2"] == 8860

    mt_prod = on_disk["products"]["EQ-MICROTRAIT-REP-v1.0.0"]
    assert mt_prod["source_genomes"] == 5438
    assert mt_prod["protein_count"] == 20379930
    assert mt_prod["total_bases"] == 20490828267
    assert mt_prod["sequence_equivalence_with_bakta"] == "UNVERIFIED_SEPARATE_PRODUCTS"
    assert mt_prod["sequence_equivalence_with_pyrodigal"] == "UNVERIFIED_SEPARATE_PRODUCTS"
    assert mt_prod["model_coverage_ledger"] == {
        "rule_referenced_hmms_total": 1831,
        "rule_referenced_hmms_assayed": 1829,
        "rule_referenced_hmms_unassayed": ["aphA", "phoN"],
        "installed_microtrait_hmms": 1830,
        "microtrait_db_models": 1789,
        "dbcan_v14_gh_models": 41,
        "installed_hmms_not_in_rules": ["phbB"],
        "hmmer_version": "3.3.2",
        "dbcan_version": "V14",
        "dbcan_sha256": "396c791fb13defab152864d8046687ef03b492937ec6f9bbab008bc77cbaa7a5",
        "dbcan_pressed_sha256": "0bcd0ab0c06baebc2b3960e38e1b2f4c5a2c8357780a094be79d641ecf720070",
        "phosphatase_confirmed_positive": 2986,
        "phosphatase_unconfirmed_safe_na": 2452,
        "phosphatase_false_zeros": 0,
    }

    tax_rec_rows = read_tsv(PROJECT_ROOT / "metadata/cohorts/taxonomy_snapshot_reconciliation.tsv")
    assert len(tax_rec_rows) == 5438
    assert sum(r["whole_string_diff"] == "1" for r in tax_rec_rows) == 1898
    assert sum(r["genus_diff"] == "1" for r in tax_rec_rows) == 1124
    assert sum(r["order_diff"] == "1" for r in tax_rec_rows) == 220
    assert sum(r["phylum_diff"] == "1" for r in tax_rec_rows) == 247
    assert sum(r["class_diff"] == "1" for r in tax_rec_rows) == 34
    assert sum(r["domain_diff"] == "1" for r in tax_rec_rows) == 0


def test_adversarial_same_count_wrong_member_join_fails() -> None:
    (
        libraries,
        shotgun_rows,
        amplicon_1186,
        site_dunes,
        shotgun_qc_source,
        legacy_150_rows,
        representatives,
        ena_genomes,
        wgs_runs,
        _mimag_rows,
        manifest,
    ) = _load_real_inputs()

    # 1. Swap in_442_amplicon_matched (and in_441_matched_read_depth_model)
    # between a matched core library and an unmatched core library so the
    # cohort totals remain 442 and 441, but the members are wrong.
    swapped_442 = copy.deepcopy(shotgun_rows)
    matched_idx = next(
        i
        for i, r in enumerate(swapped_442)
        if r["in_546_core_transect"] == "1"
        and r["in_442_amplicon_matched"] == "1"
        and r["in_441_matched_read_depth_model"] == "1"
    )
    unmatched_idx = next(
        i
        for i, r in enumerate(swapped_442)
        if r["in_546_core_transect"] == "1"
        and r["in_442_amplicon_matched"] == "0"
        and r["in_545_read_depth_model"] == "1"
    )
    swapped_442[matched_idx]["in_442_amplicon_matched"] = "0"
    swapped_442[matched_idx]["in_441_matched_read_depth_model"] = "0"
    swapped_442[unmatched_idx]["in_442_amplicon_matched"] = "1"
    swapped_442[unmatched_idx]["in_441_matched_read_depth_model"] = "1"

    assert sum(r["in_442_amplicon_matched"] == "1" for r in swapped_442) == 442
    assert sum(r["in_441_matched_read_depth_model"] == "1" for r in swapped_442) == 441
    with pytest.raises(ValueError, match="member mismatch in 442 amplicon-matched cohort"):
        validate_cohort_joins_and_counts(
            libraries,
            swapped_442,
            amplicon_1186,
            site_dunes,
            shotgun_qc_source,
            legacy_150_rows,
            representatives,
            ena_genomes,
            wgs_runs,
            manifest,
        )

    # 2. Swap in_545_read_depth_model between F45PRr3 and a valid core library
    # so the total remains 545, but the member identity is wrong.
    swapped_545 = copy.deepcopy(shotgun_rows)
    f45_idx = next(i for i, r in enumerate(swapped_545) if r["sample"] == "F45PRr3")
    valid_unmatched_idx = next(
        i
        for i, r in enumerate(swapped_545)
        if r["in_545_read_depth_model"] == "1" and r["in_442_amplicon_matched"] == "0"
    )
    swapped_545[f45_idx]["in_545_read_depth_model"] = "1"
    swapped_545[valid_unmatched_idx]["in_545_read_depth_model"] = "0"
    assert sum(r["in_545_read_depth_model"] == "1" for r in swapped_545) == 545
    with pytest.raises(ValueError, match="member mismatch in 545 read-depth cohort"):
        validate_cohort_joins_and_counts(
            libraries,
            swapped_545,
            amplicon_1186,
            site_dunes,
            shotgun_qc_source,
            legacy_150_rows,
            representatives,
            ena_genomes,
            wgs_runs,
            manifest,
        )

    # 3. Swap in_546_core_transect between a named-site library (62PRr2) and a
    # primary-site library so the total remains 546, but the member identity is wrong.
    swapped_546 = copy.deepcopy(shotgun_rows)
    named_idx = next(i for i, r in enumerate(swapped_546) if r["sample"] == "62PRr2")
    primary_idx = next(
        i
        for i, r in enumerate(swapped_546)
        if r["in_546_core_transect"] == "1" and r["in_442_amplicon_matched"] == "0"
    )
    swapped_546[named_idx]["in_546_core_transect"] = "1"
    swapped_546[primary_idx]["in_546_core_transect"] = "0"
    assert sum(r["in_546_core_transect"] == "1" for r in swapped_546) == 546
    with pytest.raises(ValueError, match="member mismatch in 546 core cohort"):
        validate_cohort_joins_and_counts(
            libraries,
            swapped_546,
            amplicon_1186,
            site_dunes,
            shotgun_qc_source,
            legacy_150_rows,
            representatives,
            ena_genomes,
            wgs_runs,
            manifest,
        )


def test_adversarial_wrong_specimen_compartment_or_dune_join_fails() -> None:
    (
        libraries,
        shotgun_rows,
        amplicon_1186,
        site_dunes,
        shotgun_qc_source,
        legacy_150_rows,
        representatives,
        ena_genomes,
        wgs_runs,
        _mimag_rows,
        manifest,
    ) = _load_real_inputs()

    bad_compartment = copy.deepcopy(shotgun_rows)
    bad_compartment[0]["compartment_canonical"] = "RootAdjacent"
    with pytest.raises(ValueError, match="compartment join mismatch"):
        validate_cohort_joins_and_counts(
            libraries,
            bad_compartment,
            amplicon_1186,
            site_dunes,
            shotgun_qc_source,
            legacy_150_rows,
            representatives,
            ena_genomes,
            wgs_runs,
            manifest,
        )

    bad_dune = copy.deepcopy(shotgun_rows)
    bad_dune[0]["edgell_dune_type"] = "Central_Transverse"
    with pytest.raises(ValueError, match="dune_field mismatch"):
        validate_cohort_joins_and_counts(
            libraries,
            bad_dune,
            amplicon_1186,
            site_dunes,
            shotgun_qc_source,
            legacy_150_rows,
            representatives,
            ena_genomes,
            wgs_runs,
            manifest,
        )

    bad_amp_join = copy.deepcopy(amplicon_1186)
    matched_sample = next(
        r["sample"] for r in shotgun_rows if r["in_442_amplicon_matched"] == "1"
    )
    for row in bad_amp_join:
        if row["library_id"].endswith(f"_{matched_sample}") or row["library_id"] == matched_sample:
            row["compartment"] = (
                "surface" if row["compartment"] != "surface" else "root-adjacent"
            )
            break
    with pytest.raises(
        ValueError,
        match="cross-assay specimen metadata disagreement between shotgun and amplicon",
    ):
        validate_cohort_joins_and_counts(
            libraries,
            shotgun_rows,
            bad_amp_join,
            site_dunes,
            shotgun_qc_source,
            legacy_150_rows,
            representatives,
            ena_genomes,
            wgs_runs,
            manifest,
        )


def test_adversarial_altered_cohort_counts_fail() -> None:
    (
        libraries,
        shotgun_rows,
        amplicon_1186,
        site_dunes,
        shotgun_qc_source,
        legacy_150_rows,
        representatives,
        ena_genomes,
        wgs_runs,
        _mimag_rows,
        manifest,
    ) = _load_real_inputs()

    with pytest.raises(ValueError, match="expected 551 shotgun cohort rows"):
        validate_cohort_joins_and_counts(
            libraries,
            shotgun_rows[:-1],
            amplicon_1186,
            site_dunes,
            shotgun_qc_source,
            legacy_150_rows,
            representatives,
            ena_genomes,
            wgs_runs,
            manifest,
        )


def test_adversarial_mimag_strict_vs_inclusive_boundary_fails() -> None:
    (
        libraries,
        shotgun_rows,
        amplicon_1186,
        site_dunes,
        shotgun_qc_source,
        legacy_150_rows,
        representatives,
        ena_genomes,
        wgs_runs,
        _mimag_rows,
        manifest,
    ) = _load_real_inputs()

    assert classify_mimag_strict(64.61, 10.0, False, False, False, 12) == "below-medium"
    assert classify_mimag_strict(64.61, 9.99, False, False, False, 12) == "medium"
    assert classify_drep_operational(64.61, 10.0) == "drep_included_le10"
    assert classify_drep_operational(64.61, 10.01) == "drep_excluded"

    bad_ena = copy.deepcopy(ena_genomes)
    for row in bad_ena:
        if row["genome"] == "48Dr2__self_SemiBin_25":
            row["mimag_tier"] = "medium"
    with pytest.raises(
        ValueError, match="10.0% contamination genome 48Dr2__self_SemiBin_25 misclassified"
    ):
        validate_cohort_joins_and_counts(
            libraries,
            shotgun_rows,
            amplicon_1186,
            site_dunes,
            shotgun_qc_source,
            legacy_150_rows,
            representatives,
            bad_ena,
            wgs_runs,
            manifest,
        )


def test_adversarial_swapped_protein_and_coverm_product_versions_fail() -> None:
    (
        libraries,
        shotgun_rows,
        amplicon_1186,
        site_dunes,
        shotgun_qc_source,
        legacy_150_rows,
        representatives,
        ena_genomes,
        wgs_runs,
        _mimag_rows,
        manifest,
    ) = _load_real_inputs()

    # 1. Conflate Bakta (19,186,792) and Pyrodigal (20,451,986) protein counts.
    conflated_proteins = copy.deepcopy(manifest)
    conflated_proteins["products"]["EQ-PROT-BAKTA-v1.0.0"]["protein_count"] = 20451986
    with pytest.raises(ValueError, match="altered protein product counts"):
        validate_cohort_joins_and_counts(
            libraries,
            shotgun_rows,
            amplicon_1186,
            site_dunes,
            shotgun_qc_source,
            legacy_150_rows,
            representatives,
            ena_genomes,
            wgs_runs,
            conflated_proteins,
        )

    # 2. Assert unverified cross-caller equivalence as verified.
    false_equivalence = copy.deepcopy(manifest)
    false_equivalence["products"]["EQ-PROT-BAKTA-v1.0.0"][
        "sequence_equivalence_with_pyrodigal"
    ] = "VERIFIED_EQUIVALENT"
    with pytest.raises(
        ValueError,
        match="unverified protein equivalence must not be marked equivalent",
    ):
        validate_cohort_joins_and_counts(
            libraries,
            shotgun_rows,
            amplicon_1186,
            site_dunes,
            shotgun_qc_source,
            legacy_150_rows,
            representatives,
            ena_genomes,
            wgs_runs,
            false_equivalence,
        )

    # 3. Swap CoverM product version IDs so two products share an ID.
    swapped_coverm = copy.deepcopy(manifest)
    swapped_coverm["products"]["EQ-COVERM-REL-ABUND-v1.0.0"][
        "version_id"
    ] = "EQ-COVERM-REFINED-v1.0.0"
    with pytest.raises(ValueError, match="missing or duplicate CoverM product versions"):
        validate_cohort_joins_and_counts(
            libraries,
            shotgun_rows,
            amplicon_1186,
            site_dunes,
            shotgun_qc_source,
            legacy_150_rows,
            representatives,
            ena_genomes,
            wgs_runs,
            swapped_coverm,
        )

    # 4. Conflate microTrait Prodigal (20,379,930) with Pyrodigal or treat aphA/phoN as assayed.
    conflated_microtrait = copy.deepcopy(manifest)
    conflated_microtrait["products"]["EQ-MICROTRAIT-REP-v1.0.0"][
        "protein_count"
    ] = 20451986
    with pytest.raises(ValueError, match="altered protein product counts"):
        validate_cohort_joins_and_counts(
            libraries,
            shotgun_rows,
            amplicon_1186,
            site_dunes,
            shotgun_qc_source,
            legacy_150_rows,
            representatives,
            ena_genomes,
            wgs_runs,
            conflated_microtrait,
        )

    bad_phosphatase = copy.deepcopy(manifest)
    bad_phosphatase["products"]["EQ-MICROTRAIT-REP-v1.0.0"]["model_coverage_ledger"][
        "rule_referenced_hmms_unassayed"
    ] = []
    with pytest.raises(ValueError, match="invalid or conflated microTrait model coverage ledger"):
        validate_cohort_joins_and_counts(
            libraries,
            shotgun_rows,
            amplicon_1186,
            site_dunes,
            shotgun_qc_source,
            legacy_150_rows,
            representatives,
            ena_genomes,
            wgs_runs,
            bad_phosphatase,
        )


def test_adversarial_missing_staged_source_input_fails_without_fallback(
    tmp_path: Path,
) -> None:
    # Copy the output cohort table into tmp_path, plus canonical metadata,
    # but omit metadata/cohorts/source/included_samples_1186.tsv.
    # Verify build_cohorts fails with FileNotFoundError instead of falling back
    # to the existing output table or HOME paths.
    (tmp_path / "metadata/cohorts/source").mkdir(parents=True)
    (tmp_path / "metadata/metagenome/canonical").mkdir(parents=True)
    (tmp_path / "evidence/mag-catalogue-20261024/source/ena_deposit").mkdir(
        parents=True
    )
    shutil.copy2(
        PROJECT_ROOT / "metadata/cohorts/shotgun_cohort_accounting.tsv",
        tmp_path / "metadata/cohorts/shotgun_cohort_accounting.tsv",
    )
    for rel in (
        "metadata/metagenome/canonical/library_metadata.tsv",
        "metadata/metagenome/canonical/refined_representatives.tsv",
        "metadata/metagenome/canonical/ena_genome_accessions.tsv",
        "evidence/mag-catalogue-20261024/source/metagenome_sample_meta_150.tsv",
        "evidence/mag-catalogue-20261024/source/ena_deposit/wgs_runs.tsv",
        "evidence/mag-catalogue-20261024/source/ena_deposit/wgs_bins.tsv",
    ):
        shutil.copy2(PROJECT_ROOT / rel, tmp_path / rel)

    with pytest.raises(
        FileNotFoundError,
        match="required staged input table is missing.*included_samples_1186.tsv",
    ):
        build_cohorts(tmp_path)


def test_adversarial_stale_taxonomy_substitution_with_same_ids_and_counts() -> None:
    (
        libraries,
        shotgun_rows,
        amplicon_1186,
        site_dunes,
        shotgun_qc_source,
        legacy_150_rows,
        representatives,
        ena_genomes,
        wgs_runs,
        _mimag_rows,
        manifest,
    ) = _load_real_inputs()
    legacy_taxonomy_rows = read_tsv(
        PROJECT_ROOT / "metadata/cohorts/source/legacy_analytical_genome_quality.tsv"
    )

    # 1. False claim that legacy analytical taxonomy is identical to canonical GTDB R232
    false_identical_tax = copy.deepcopy(manifest)
    false_identical_tax["products"]["EQ-TAX-LEGACY-ANALYTICAL-v0"][
        "equivalence_with_canonical_gtdb_r232"
    ] = "IDENTICAL"
    with pytest.raises(
        ValueError,
        match="legacy analytical taxonomy must not be marked identical to canonical GTDB R232",
    ):
        validate_cohort_joins_and_counts(
            libraries,
            shotgun_rows,
            amplicon_1186,
            site_dunes,
            shotgun_qc_source,
            legacy_150_rows,
            representatives,
            ena_genomes,
            wgs_runs,
            false_identical_tax,
        )

    # 2. Stale substitution where the same 5,438 genome IDs and 237 Thermoplasmatota
    # count are preserved, but two genomes swap their legacy taxonomy strings/qualities
    swapped_leg = copy.deepcopy(legacy_taxonomy_rows)
    swapped_leg[0]["genome"], swapped_leg[1]["genome"] = (
        swapped_leg[1]["genome"],
        swapped_leg[0]["genome"],
    )
    with pytest.raises(
        ValueError,
        match="quality metric mismatch between canonical and legacy taxonomy table",
    ):
        reconcile_taxonomy_snapshots(representatives, swapped_leg)

    # 3. Stale taxonomy label substitution where IDs and CheckM2 qualities match 1:1
    # and Thermoplasmatota count remains 237, but a legacy genus label is silently
    # overwritten with the canonical genus label (altering the 1,124 genus-difference count).
    stale_labels = copy.deepcopy(legacy_taxonomy_rows)
    can_by_id = {r["mag"]: r for r in representatives}
    for row in stale_labels:
        gid = row["genome"]
        if row["gtdb_classification"] != can_by_id[gid]["gtdb_r232_classification"]:
            row["gtdb_classification"] = can_by_id[gid]["gtdb_r232_classification"]
            break
    _rows, bad_summary = reconcile_taxonomy_snapshots(representatives, stale_labels)
    stale_manifest = copy.deepcopy(manifest)
    stale_manifest["products"]["EQ-TAX-LEGACY-ANALYTICAL-v0"][
        "reconciliation_with_canonical_gtdb_r232"
    ] = bad_summary
    with pytest.raises(
        ValueError,
        match="stale or altered taxonomy reconciliation summary in manifest",
    ):
        validate_cohort_joins_and_counts(
            libraries,
            shotgun_rows,
            amplicon_1186,
            site_dunes,
            shotgun_qc_source,
            legacy_150_rows,
            representatives,
            ena_genomes,
            wgs_runs,
            stale_manifest,
        )
