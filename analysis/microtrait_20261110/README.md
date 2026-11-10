# Full-Catalogue microTrait v1.0.0 Analysis (`analysis/microtrait_20261110`)

This module packages the full-catalogue **microTrait v1.0.0** (pinned commit `b4344ebd4e0cdc6f7f37f10e25a947a839d61eaa`) and **gRodon / optimalT** pipeline code, provenance ledgers, compact compressed trait/rule/HMM matrices, continuous growth/OGT predictors, and downstream Thermoplasmatota + ecology community-weighted sensitivity analyses across all **5,438 canonical refined MAGs** (`4,847` Bacteria + `591` Archaea, including `237` Thermoplasmatota; `1,010` `_sub` IDs preserved).

## 1. Directory Layout

- `code/`: Complete V14 Shaheen III Slurm + R/Python pipeline (`launch_pipeline.sh`, `stage0a_extract_genomes.py`, `sbatch_stage0a_extract.sh`, `stage0b_prep_db.py`, `sbatch_stage0b_db.sh`, `sbatch_stage1_smoke.sh`, `sbatch_stage2_array.sh`, `sbatch_stage3_aggregate.sh`, `run_node_chunk.py`, `run_microtrait_batch.R`, `aggregate_genomeset.R`, `stage3_aggregate_and_validate.py`).
- `inputs/`: Canonical 5,438-MAG input manifests (`all_5438_mags.txt`, `cohort_manifest_5438.tsv`, `genome_manifest.tsv`, `smoke_mags.txt`).
- `provenance/`: Exact environment and database provenance (`conda_explicit_packages.txt`, `database_assets_manifest.json`, `model_coverage_ledger.json`, `r_session_info.txt`, `r_session_info_setup.txt`, `root_jobs.json`, `root_required_hmm_ids.txt`, `root_rule_hmm_coverage.json`, `stage0a_extract_summary.json`, `stage0a_job_id.txt`).
- `results/`:
  - `trait_matrixatgranularity1.tsv.gz` (`5,438 x 41`)
  - `trait_matrixatgranularity2.tsv.gz` (`5,438 x 104`)
  - `trait_matrixatgranularity3.tsv.gz` (`5,438 x 193`)
  - `rule_matrix.tsv.gz` (`5,438 x 1,449`)
  - `hmm_matrix.tsv.gz` (`5,438 x 1,836`)
  - `growth_and_ogt_predictions_5438.tsv` (`5,438` rows; gRodon + optimalT continuous predictors with explicit applicability flags)
  - `microtrait_status_5438.tsv` (`5,438` rows; per-genome ORF counts, HMM hit counts, and component completion status)
  - `phosphatase_and_model_coverage_5438.tsv` (`5,438` rows; phosphatase rule audit separating confirmed positives from unassayed `aphA`/`phoN` safe `NA`)
  - `aggregation_summary.json`, `smoke_official_extract_traits_parity.json`, `smoke_test_validation.json`, `SHA256SUMS`
- `compact_analysis/`: Self-contained downstream analysis and ecology community-weighted sensitivity module (`code/run_microtrait_analysis.py`, `code/run_ecology_sensitivity.py`, `inputs/`, `results/`, `results/ecology_sensitivity/`, `tests/test_microtrait_analysis.py`, `tests/test_ecology_sensitivity.py`).
- `manifests/`:
  - `bulk_shaheen_artifacts.tsv`: Inventory and fetch instructions for large intermediate/bulk artifacts retained on Shaheen III (`hmm_gene_hits_all5438.tsv.gz`, per-MAG `.rds` checkpoints, uncompressed `.tsv` matrices, and pressed HMM databases).
  - `sha256_manifest.tsv`: Byte sizes and SHA-256 digests of all packaged files.
- `tests/test_microtrait_package.py`: Package integrity, provenance, and scientific scope regression test suite.

## 2. Provenance, Software Versions, and Database Accounting

1. **Software & Gene Caller Provenance (`EQ-MICROTRAIT-REP-v1.0.0`)**:
   - Upstream `microtrait::extract.traits` invokes **Prodigal v2.6.3 (`-p meta`)** and **HMMER v3.3.2 (`hmmsearch`)** directly on the 5,438 canonical genome FASTAs (`20,490,828,267` bp), predicting **20,379,930 ORFs**.
   - This 20,379,930-ORF Prodigal callset is a distinct product (`EQ-MICROTRAIT-REP-v1.0.0`) from the **19,186,792** CDSs predicted by **Bakta v1.12.0** (`EQ-PROT-BAKTA-v1.0.0`) and the **20,451,986** ORFs predicted by **Pyrodigal** (v3.7.1 in the verified proteome environment; `EQ-PROT-PYRODIGAL-REP-v1.0.0`).
2. **HMM Database Accounting (`provenance/database_assets_manifest.json` & `model_coverage_ledger.json`)**:
   - **`microtrait.hmmdb`**: `1,789` HMM models (`1,788` required-rule models + `1` extra model `phbB` not referenced in `rules.txt`; compressed archive `microtrait.hmmdb.gz` SHA-256 `98d106ce0ad84c916c489ecb7b9f4576b4034a7cb4ab111d02c09a6df1ccd690`, pressed `microtrait.hmmdb` SHA-256 `00b6fbfe4681a6054edefce0c1c415aa8f559ce94d9c1c098a1306b65411a953`).
   - **`dbcan.select.v14.hmmdb`**: `41` GH domain profiles subsetted from official `dbCAN-HMMdb-V14.txt` (`129,842,960` bytes, SHA-256 `396c791fb13defab152864d8046687ef03b492937ec6f9bbab008bc77cbaa7a5`) using `dbcan.selectids.txt` (`41` verified GH IDs, SHA-256 `78462c7e3245c199c3b3e1b3511dbfc7df97c522bb3aed2347974a3fd56eea86`), yielding pressed `dbcan.select.v14.hmmdb` (`6,678,077` bytes, SHA-256 `0bcd0ab0c06baebc2b3960e38e1b2f4c5a2c8357780a094be79d641ecf720070`).
   - **`arcbacribosomal.hmmdb`**: `56` ribosomal protein HMMs for gRodon (`2,953,795` bytes, SHA-256 `bb6ead55a998907f5e626c237819716fbefe427c7b520de4ceceee66ab3f428c`).
   - **Combined Rule-Model Coverage**: `microtrait.hmmdb` (`1,789`) + `dbcan.select.v14.hmmdb` (`41`) = **`1,830` total assayed database models**. Because `phbB` is not referenced by any rule in `rules.txt`, **`1,829 of 1,831` required-rule HMMs are assayed**, and **`2` required-rule HMMs (`aphA`, `phoN`) are absent from the upstream Zenodo release**.
3. **Phosphatase Safe-`NA` Accounting (`results/phosphatase_and_model_coverage_5438.tsv`)**:
   - The upstream phosphatase rule is `('phoA' | 'phoD' | 'phoN' | 'aphA')`.
   - Across the 5,438 MAGs: **2,986 MAGs** are confirmed positive (`1`) via `phoA` and/or `phoD` hits, while **2,452 MAGs** have zero `phoA`/`phoD` hits and are recorded as **`NA`** in `phosphatase_interpretation_safe_value` (never coerced to `0`, because `aphA` and `phoN` were unassayed).

## 3. Scientific Scope & Interpretation Boundaries

1. **Numerical Quality Subset vs. Formal MIMAG HQ**:
   - The sensitivity subset defined by CheckM2 `completeness >= 90%` and `contamination <= 5%` (**`N = 2,259` MAGs** across the cohort: `2,140` Bacteria, `119` Archaea, **`59` Thermoplasmatota**) is a **numerical quality subset**, **NOT** the formal Bowers et al. (2017) MIMAG High-Quality (HQ) tier (which additionally requires 5S, 16S, and 23S rRNAs plus `>=18` tRNAs and strict `<5%` contamination, totaling `126` MAGs in the foundation catalogue).
2. **Thermoplasmatota Marker-Rule Positivity (`compact_analysis/results/thermoplasmatota_class_summaries.tsv`)**:
   - **All 237 Thermoplasmatota (`185` `c__SW-10-69-26`, `51` `c__E2`, `1` `c__Thermoplasmata`)**:
     - `free amino acids transport`: `237 / 237` (`100.0%`)
     - `peptide transport`: `10 / 237` (`4.22%`, all `10` in `c__SW-10-69-26`; `0` in `c__E2` and `c__Thermoplasmata`)
     - `protein degradation`: `237 / 237` (`100.0%`)
     - `CO2 fixation` (G2 category): `2 / 237` (`0.84%`, both in `c__SW-10-69-26`, hitting G3 `3-hydroxypropionate/4-hydroxybutyrate pathway` (`3hp4hb_key1`) only; `0` across all other CO2 fixation pathways)
   - **Numerical Quality Subset (`>=90%` completeness, `<=5%` contamination; `N = 59` Thermoplasmatota: `43` `c__SW-10-69-26`, `15` `c__E2`, `1` `c__Thermoplasmata`)**:
     - `free amino acids transport`: `59 / 59` (`100.0%`)
     - `peptide transport`: `1 / 59` (`1.69%`, in `c__SW-10-69-26`)
     - `protein degradation`: `59 / 59` (`100.0%`)
     - `CO2 fixation`: `1 / 59` (`1.69%`, in `c__SW-10-69-26`, `3hp4hb_key1` only)
   - **Interpretation Boundaries**:
     - Upstream `microtrait` G2 `protein degradation` aggregates rules spanning intracellular processing and housekeeping peptidases/proteasome subunits (e.g., `psmA`/`psmB`, `map`, `lon`, `pepA_M17`, `pepT`, `pepD_M20`); positivity in this broad category does not by itself establish extracellular protein hydrolysis.
     - Positivity on `3hp4hb_key1` reflects microTrait marker-rule satisfaction (which permits alternative 4-reaction combinations) and does not establish a complete functional autotrophic carbon-fixation cycle.
3. **Ecology Community-Weighted Sensitivity (`compact_analysis/results/ecology_sensitivity/sensitivity_summary.json`, Job `15926786`)**:
   - Across `546` core shotgun samples (`68` paired Surface-vs-Deep visits across `36` sites; `1,000` spatial block bootstrap draws across `10` contiguous `transect_km` blocks, seed `20261108`):
     - **BetL (`betL`)**: legacy mapped `+7.5515 pp` (`95% CI [4.7243, 10.3341]`) vs. full microTrait mapped `+6.9062 pp` (`95% CI [4.3320, 9.4466]`, `delta = -0.6453 pp`); whole-read `+3.3025 pp` vs. `+3.0022 pp` (`delta = -0.3003 pp`).
     - **AhpCF (`ahpCF`)**: legacy mapped `+6.9491 pp` (`95% CI [3.3428, 9.7137]`) vs. full microTrait mapped `+6.9301 pp` (`95% CI [3.3445, 9.6754]`, `delta = -0.0191 pp`); whole-read `+3.2325 pp` vs. `+3.2213 pp` (`delta = -0.0112 pp`).

## 4. Verification Commands

```bash
uv run --python 3.12 pytest analysis/microtrait_20261110/tests/test_microtrait_package.py \
  analysis/microtrait_20261110/compact_analysis/tests/test_microtrait_analysis.py \
  analysis/microtrait_20261110/compact_analysis/tests/test_ecology_sensitivity.py -v
```
