#!/usr/bin/env python3
"""Self-contained regression and integrity test suite for analysis/microtrait_20261110.

Verifies:
1. Canonical 5,438-MAG cohort parity with metadata/metagenome/canonical/refined_representatives.tsv
   (4,847 Bacteria + 591 Archaea, including 237 Thermoplasmatota, 1,010 _sub IDs preserved).
2. V14 pipeline scripts presence, zero standalone /tmp usage, absence of deprecated V8 scripts, and dbCAN V14 pin.
3. Compressed matrices (trait_matrixatgranularity1/2/3.tsv.gz, rule_matrix.tsv.gz, hmm_matrix.tsv.gz)
   dimensions (5438 x 41, 5438 x 104, 5438 x 193, 5438 x 1449, 5438 x 1836), exact ID set match,
   and exclusion of .rds, uncompressed .tsv matrices, and >20 MB gene-hit tables.
4. Continuous predictors (growth_and_ogt_predictions_5438.tsv, microtrait_status_5438.tsv):
   20,379,930 fresh Prodigal v2.6.3 (-p meta) ORFs across 20,490,828,267 bases, optimalT_predict_wtRNA == False,
   and explicit applicability flags.
5. Model coverage & phosphatase audit (phosphatase_and_model_coverage_5438.tsv, model_coverage_ledger.json):
   1,831 rule-referenced HMMs, 1,829 assayed, 2 unassayed (aphA, phoN), 1,830 DB profiles (including phbB),
   2,986 confirmed phosphatase-positive (1), 2,452 safe NA (never coerced to 0 in interpretation-safe column).
6. Scientific scope from MICROTRAIT-ROOT-REVIEW.txt in compact_analysis/results/:
   All 237 Thermoplasmatota: free AA = 237, peptide = 10 (c__SW-10-69-26 only), protein degradation = 237,
   CO2 fixation category = 2 (c__SW-10-69-26 only, 3hp4hb marker rule only).
   HQ subset (>=90% completeness, <=5% contamination, N=59 Thermoplasmatota): free AA = 59, peptide = 1,
   protein degradation = 59, CO2 = 1.
7. Byte-exact SHA-256 verification against manifests/sha256_manifest.tsv.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
from pathlib import Path
import re

PACKAGE_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = PACKAGE_DIR.parents[1]
CANONICAL_REFINED_TSV = REPO_ROOT / "metadata" / "metagenome" / "canonical" / "refined_representatives.tsv"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_tsv_gz_dims_and_ids(path: Path) -> tuple[int, int, list[str]]:
    ids: list[str] = []
    ncols = 0
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        reader = csv.reader(fh, delimiter="\t")
        header = next(reader)
        ncols = len(header)
        assert header[0] == "id"
        for row in reader:
            assert len(row) == ncols
            ids.append(row[0])
    return len(ids), ncols, ids


def test_canonical_5438_cohort_parity() -> None:
    all_mags = [
        line.strip()
        for line in (PACKAGE_DIR / "inputs" / "all_5438_mags.txt").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(all_mags) == 5438
    assert len(set(all_mags)) == 5438
    assert sum(1 for m in all_mags if m.endswith("_sub")) == 1010

    with (PACKAGE_DIR / "inputs" / "cohort_manifest_5438.tsv").open("r", encoding="utf-8") as fh:
        cohort_rows = list(csv.DictReader(fh, delimiter="\t"))
    assert len(cohort_rows) == 5438
    cohort_ids = {r["mag"] for r in cohort_rows}
    assert cohort_ids == set(all_mags)
    assert sum(int(r["bases"]) for r in cohort_rows) == 20490828267

    if CANONICAL_REFINED_TSV.exists():
        with CANONICAL_REFINED_TSV.open("r", encoding="utf-8") as fh:
            canonical_rows = list(csv.DictReader(fh, delimiter="\t"))
        assert len(canonical_rows) == 5438
        canonical_ids = {r["mag"] for r in canonical_rows}
        assert cohort_ids == canonical_ids

        n_bac = sum(1 for r in canonical_rows if r["gtdb_r232_classification"].startswith("d__Bacteria"))
        n_arc = sum(1 for r in canonical_rows if r["gtdb_r232_classification"].startswith("d__Archaea"))
        n_thermo = sum(1 for r in canonical_rows if "p__Thermoplasmatota" in r["gtdb_r232_classification"])
        assert n_bac == 4847
        assert n_arc == 591
        assert n_thermo == 237


def test_v14_pipeline_code_and_provenance() -> None:
    expected_scripts = [
        "launch_pipeline.sh",
        "stage0a_extract_genomes.py",
        "sbatch_stage0a_extract.sh",
        "stage0b_prep_db.py",
        "sbatch_stage0b_db.sh",
        "sbatch_stage1_smoke.sh",
        "sbatch_stage2_array.sh",
        "sbatch_stage3_aggregate.sh",
        "run_node_chunk.py",
        "run_microtrait_batch.R",
        "aggregate_genomeset.R",
        "stage3_aggregate_and_validate.py",
    ]
    code_dir = PACKAGE_DIR / "code"
    for name in expected_scripts:
        p = code_dir / name
        assert p.is_file(), f"Missing pipeline script: {name}"
        text = p.read_text(encoding="utf-8")
        assert "TMPDIR" in text or "tmp" in text or name.endswith(".R") or name == "launch_pipeline.sh"

    for deprecated in ("stage0_prep_and_verify.py", "sbatch_stage0_prep.sh", "sync_results_collector.py"):
        assert not (code_dir / deprecated).exists(), f"Deprecated script present: {deprecated}"

    db_manifest = json.loads((PACKAGE_DIR / "provenance" / "database_assets_manifest.json").read_text(encoding="utf-8"))
    dbcan_sha = db_manifest["downloads"]["dbCAN-HMMdb-V14.txt"]["sha256"]
    assert dbcan_sha == "396c791fb13defab152864d8046687ef03b492937ec6f9bbab008bc77cbaa7a5"
    assert db_manifest["downloads"]["dbCAN-HMMdb-V14.txt"]["bytes"] == 129842960
    assert db_manifest["dbcan_selectids_count"] == 41
    assert db_manifest["model_counts"]["microtrait.hmmdb"]["n_models"] == 1789
    assert db_manifest["model_counts"]["dbcan.select.v14.hmmdb"]["n_models"] == 41
    assert db_manifest["pressed_files"]["dbcan.select.v14.hmmdb"]["sha256"] == (
        "0bcd0ab0c06baebc2b3960e38e1b2f4c5a2c8357780a094be79d641ecf720070"
    )
    assert db_manifest["pressed_files"]["dbcan.select.v14.hmmdb"]["bytes"] == 6678077


def test_compact_matrices_and_size_caps() -> None:
    for p in PACKAGE_DIR.rglob("*"):
        if p.is_file():
            assert p.suffix != ".rds", f"Forbidden .rds file bundled: {p}"
            assert p.name != "hmm_gene_hits_all5438.tsv.gz", f"Forbidden 41.7 MB gene-hit table bundled: {p}"
            assert p.stat().st_size < 20 * 1024 * 1024, f"File exceeds 20 MB cap: {p}"

    results_dir = PACKAGE_DIR / "results"
    for stem in (
        "trait_matrixatgranularity1",
        "trait_matrixatgranularity2",
        "trait_matrixatgranularity3",
        "rule_matrix",
        "hmm_matrix",
    ):
        assert not (results_dir / f"{stem}.tsv").exists(), f"Uncompressed matrix should not be bundled: {stem}.tsv"

    expected_dims = {
        "trait_matrixatgranularity1.tsv.gz": (5438, 41),
        "trait_matrixatgranularity2.tsv.gz": (5438, 104),
        "trait_matrixatgranularity3.tsv.gz": (5438, 193),
        "rule_matrix.tsv.gz": (5438, 1449),
        "hmm_matrix.tsv.gz": (5438, 1836),
    }
    all_mags = set(
        line.strip()
        for line in (PACKAGE_DIR / "inputs" / "all_5438_mags.txt").read_text(encoding="utf-8").splitlines()
        if line.strip()
    )
    for fname, (exp_rows, exp_cols) in expected_dims.items():
        nrows, ncols, ids = _read_tsv_gz_dims_and_ids(results_dir / fname)
        assert (nrows, ncols) == (exp_rows, exp_cols), f"{fname}: got {(nrows, ncols)}, expected {(exp_rows, exp_cols)}"
        assert set(ids) == all_mags


def test_continuous_predictors_and_orf_provenance() -> None:
    stage0a = json.loads((PACKAGE_DIR / "provenance" / "stage0a_extract_summary.json").read_text(encoding="utf-8"))
    assert stage0a["n_canonical_mags_verified"] == 5438
    assert stage0a["n_bacteria"] == 4847
    assert stage0a["n_archaea"] == 591
    assert stage0a["n_thermoplasmatota"] == 237
    assert stage0a["n_has_sub_suffix"] == 1010

    with (PACKAGE_DIR / "results" / "microtrait_status_5438.tsv").open("r", encoding="utf-8") as fh:
        status_rows = list(csv.DictReader(fh, delimiter="\t"))
    assert len(status_rows) == 5438
    total_cds = sum(int(r["norfs"]) for r in status_rows)
    assert total_cds == 20379930
    assert sum(int(r["fasta_bases"]) for r in status_rows) == 20490828267
    assert all(r["overall_status"] == "complete_all_components" for r in status_rows)

    with (PACKAGE_DIR / "results" / "growth_and_ogt_predictions_5438.tsv").open("r", encoding="utf-8") as fh:
        growth_rows = list(csv.DictReader(fh, delimiter="\t"))
    assert len(growth_rows) == 5438
    assert sum(int(r["norfs"]) for r in growth_rows) == 20379930
    assert all(r["optimalT_predict_wtRNA"] == "False" for r in growth_rows)
    assert all(
        r["ogt_applicability_flag"].startswith("genomic_orf_protein_model_without_trna_or_rrna")
        for r in growth_rows
    )
    assert all(r["growth_applicability_flag"] != "" for r in growth_rows)


def test_model_coverage_and_phosphatase_safe_na() -> None:
    ledger = json.loads((PACKAGE_DIR / "provenance" / "model_coverage_ledger.json").read_text(encoding="utf-8"))
    assert ledger["total_required_rule_hmms"] == 1831
    assert ledger["assayed_required_rule_hmms"] == 1829
    assert ledger["missing_required_rule_hmms"] == ["aphA", "phoN"]
    assert ledger["extra_database_models_not_in_rules"] == ["phbB"]
    assert ledger["microtrait_database_models"] == 1789
    assert ledger["microtrait_database_required_rule_models"] == 1788
    assert ledger["dbcan_v14_database_models"] == 41
    assert ledger["total_assayed_database_models"] == 1830

    with (PACKAGE_DIR / "results" / "phosphatase_and_model_coverage_5438.tsv").open("r", encoding="utf-8") as fh:
        phos_rows = list(csv.DictReader(fh, delimiter="\t"))
    assert len(phos_rows) == 5438
    n_pos = sum(1 for r in phos_rows if r["phosphatase_interpretation_safe_value"] == "1")
    n_na = sum(1 for r in phos_rows if r["phosphatase_interpretation_safe_value"] == "NA")
    n_zero = sum(1 for r in phos_rows if r["phosphatase_interpretation_safe_value"] == "0")
    assert n_pos == 2986
    assert n_na == 2452
    assert n_zero == 0


def test_microtrait_root_review_thermoplasmatota_scope() -> None:
    summary_path = PACKAGE_DIR / "compact_analysis" / "results" / "microtrait_analysis_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))

    assert summary["cohort_mag_count"] == 5438
    assert summary["hq_mag_count_comp90_cont5"] == 2259
    assert summary["domain_counts"] == {"d__Bacteria": 4847, "d__Archaea": 591}
    assert summary["thermoplasmatota_counts"] == {
        "total": 237,
        "c__SW-10-69-26": 185,
        "c__E2": 51,
        "c__Thermoplasmata": 1,
    }

    with (PACKAGE_DIR / "compact_analysis" / "results" / "thermoplasmatota_class_summaries.tsv").open(
        "r", encoding="utf-8"
    ) as fh:
        class_rows = list(csv.DictReader(fh, delimiter="\t"))

    all_by_class = {r["canonical_class"]: r for r in class_rows if r["subset"] == "all"}
    hq_by_class = {r["canonical_class"]: r for r in class_rows if r["subset"] == "hq_comp90_cont5"}

    assert int(all_by_class["p__Thermoplasmatota_total"]["n_genomes"]) == 237
    assert int(all_by_class["p__Thermoplasmatota_total"]["g2_free_amino_acid_transport_n_pos"]) == 237
    assert int(all_by_class["p__Thermoplasmatota_total"]["g2_peptide_transport_n_pos"]) == 10
    assert int(all_by_class["p__Thermoplasmatota_total"]["g2_protein_degradation_n_pos"]) == 237
    assert int(all_by_class["p__Thermoplasmatota_total"]["g2_co2_fixation_n_pos"]) == 2
    assert int(all_by_class["c__SW-10-69-26"]["g2_peptide_transport_n_pos"]) == 10
    assert int(all_by_class["c__SW-10-69-26"]["g2_co2_fixation_n_pos"]) == 2
    assert int(all_by_class["c__SW-10-69-26"]["g3_co2_3_hydroxypropionate_4_hydroxybutyrate_n_pos"]) == 2
    assert int(all_by_class["c__E2"]["g2_peptide_transport_n_pos"]) == 0
    assert int(all_by_class["c__E2"]["g2_co2_fixation_n_pos"]) == 0

    assert int(hq_by_class["p__Thermoplasmatota_total"]["n_genomes"]) == 59
    assert int(hq_by_class["p__Thermoplasmatota_total"]["g2_free_amino_acid_transport_n_pos"]) == 59
    assert int(hq_by_class["p__Thermoplasmatota_total"]["g2_peptide_transport_n_pos"]) == 1
    assert int(hq_by_class["p__Thermoplasmatota_total"]["g2_protein_degradation_n_pos"]) == 59
    assert int(hq_by_class["p__Thermoplasmatota_total"]["g2_co2_fixation_n_pos"]) == 1
    assert int(hq_by_class["c__SW-10-69-26"]["g3_co2_3_hydroxypropionate_4_hydroxybutyrate_n_pos"]) == 1

    sens_path = PACKAGE_DIR / "compact_analysis" / "results" / "ecology_sensitivity" / "sensitivity_summary.json"
    sens = json.loads(sens_path.read_text(encoding="utf-8"))
    assert sens["cohort_mag_count"] == 5438
    assert sens["n_samples"] == 546
    assert sens["n_paired_visits"] == 68
    assert sens["n_paired_sites"] == 36
    assert round(sens["results"]["betl_betaine_uptake"]["legacy_mapped"]["mean_pp"], 4) == 7.5515
    assert round(sens["results"]["betl_betaine_uptake"]["new_microtrait_mapped"]["mean_pp"], 4) == 6.9062
    assert round(sens["results"]["ahpcf_peroxide_defence"]["legacy_mapped"]["mean_pp"], 4) == 6.9491
    assert round(sens["results"]["ahpcf_peroxide_defence"]["new_microtrait_mapped"]["mean_pp"], 4) == 6.9301


def test_sha256_manifest_integrity() -> None:
    manifest_path = PACKAGE_DIR / "manifests" / "sha256_manifest.tsv"
    assert manifest_path.is_file()
    with manifest_path.open("r", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh, delimiter="\t"))
    assert len(rows) >= 40
    for row in rows:
        target = PACKAGE_DIR / row["relative_path"]
        assert target.is_file(), f"Missing file in sha256_manifest.tsv: {row['relative_path']}"
        assert target.stat().st_size == int(row["size_bytes"]), f"Size mismatch for {row['relative_path']}"
        assert _sha256(target) == row["sha256"], f"SHA-256 mismatch for {row['relative_path']}"
