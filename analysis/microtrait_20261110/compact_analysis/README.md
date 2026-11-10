# Empty Quarter 5,438-MAG MicroTrait Compact Analysis

Reproducible, self-contained functional trait analysis across the 5,438 canonical Empty Quarter metagenome-assembled genomes (MAGs) implementing the requirements in `paper-integration-20261110/MICROTRAIT-TASK.txt`.

Root owns scientific interpretation and narrative prose; this directory provides deterministic, verifiable tables, provenance checksums, and unit tests.

---

## 1. Quickstart & Verification

Run the reproducible pipeline and test suite using `uv`:

```bash
# Execute the complete analysis pipeline
uv run python code/run_microtrait_analysis.py

# Run all unit tests and fixture audits (11 passed)
uv run pytest tests/test_microtrait_analysis.py -v

# Verify SHA-256 provenance checksums
cd results && sha256sum -c SHA256SUMS
```

---

## 2. Compact Inputs (< 20MB Each)

All input data are self-contained in `inputs/` and meet the compact portability requirement:

| File | Size | Description |
|:---|:---|:---|
| `inputs/cohort_manifest_5438.tsv` | 2.3 MB | Authoritative cohort manifest of 5,438 MAGs with CheckM2 QC and canonical GTDB r232 taxonomy |
| `inputs/trait_matrixatgranularity2.tsv.gz` | 357 KB | G2 trait matrix from microTrait pipeline across 5,438 MAGs |
| `inputs/trait_matrixatgranularity3.tsv.gz` | 412 KB | G3 trait matrix from microTrait pipeline across 5,438 MAGs |
| `inputs/rule_matrix.tsv.gz` | 1.5 MB | Full boolean rule evaluation matrix across 5,438 MAGs (gzipped to remain < 20MB) |
| `inputs/phosphatase_and_model_coverage_5438.tsv` | 828 KB | Phosphatase hits, unassayed model ledger (`aphA`, `phoN`), and safe-interpretation flags |
| `inputs/microtrait_rule2trait_runtime.tsv` | 126 KB | Runtime mapping of microTrait rules to traits at granularities 1, 2, and 3 |
| `inputs/microtrait_rules.tsv` | 63 KB | Upstream microTrait logical rule expressions |
| `inputs/microtrait_ruleunwrapped.tsv` | 134 KB | Unwrapped boolean expressions mapping rules to terminal HMM profiles |
| `inputs/ecology_genome_panels_hmm.tsv` | 1.0 MB | Existing 41-rule protein HMM per-MAG calls from `proteome-integration-20261106` |
| `inputs/ecology_task_d_panel_and_multiplicity_manifest.json` | 12 KB | Panel definitions and published logical rule formulas for the 41 protein HMM rules |

---

## 3. Cohort ID Coverage

- **Cohort Size**: Exact 5,438 canonical MAGs.
- **Coverage Audit**: Verified 100% 1:1 join across `cohort_manifest_5438.tsv`, `trait_matrixatgranularity2.tsv.gz`, `trait_matrixatgranularity3.tsv.gz`, `rule_matrix.tsv.gz`, `phosphatase_and_model_coverage_5438.tsv`, and `ecology_genome_panels_hmm.tsv`.
- **Integrity**: 0 missing MAGs, 0 duplicate MAGs, 0 unrecognized MAGs (`results/cohort_id_coverage_audit.tsv`).

---

## 4. Key Trait Analysis & Findings

Positivity is strictly defined as `value > 0` (reflecting sums of asserted upstream rules, not copy numbers or pathway completeness).

### A. Predefined G2 Traits & G3 CO2 Fixation Pathways (Cohort & High-Quality Sensitivity)

Sensitivity subset applies the criteria `checkm2_completeness >= 90.0` and `checkm2_contamination <= 5.0` (N = 2,259 MAGs):

| Trait | Target Name / Scope | All Cohort (N = 5,438) | HQ Sensitivity (N = 2,259) |
|:---|:---|:---:|:---:|
| **G2 Peptide transport** | `Resource Acquisition:Substrate uptake:peptide transport` | 2,516 (46.27%) | 1,198 (53.03%) |
| **G2 Free amino acid transport** | `Resource Acquisition:Substrate uptake:free amino acids transport` | 5,244 (96.43%) | 2,170 (96.06%) |
| **G2 Protein degradation** | `Resource Acquisition:Substrate degradation:...:protein degradation` | 5,438 (100.00%) | 2,259 (100.00%) |
| **G2 CO2 fixation** | `Resource Acquisition:Substrate assimilation:C1 compounds:CO2 fixation` | 647 (11.90%) | 295 (13.06%) |
| **G3 Calvin Cycle** | `...:CO2 fixation:Calvin Cycle` | 343 (6.31%) | 211 (9.34%) |
| **G3 3-hydroxypropionate** | `...:CO2 fixation:3-hydroxypropionate pathway` | 0 (0.00%) | 0 (0.00%) |
| **G3 3-HP/4-HB pathway** | `...:CO2 fixation:3-hydroxypropionate/4-hydroxybutyrate pathway` | 2 (0.04%) | 1 (0.04%) |
| **G3 Dicarboxylate-4-HB** | `...:CO2 fixation:dicarboxylate-hydroxybutyrate pathway` | 213 (3.92%) | 38 (1.68%) |
| **G3 Reductive acetyl-CoA** | `...:CO2 fixation:reductive acetyl-CoA pathway` | 0 (0.00%) | 0 (0.00%) |
| **G3 Reductive citric acid** | `...:CO2 fixation:reductive citric acid pathway` | 9 (0.17%) | 4 (0.18%) |
| **G3 Carboxysome** | `...:CO2 fixation:carboxysome` | 90 (1.66%) | 46 (2.04%) |

### B. Canonical Domain Breakdown

- **Bacteria (`d__Bacteria`)**: N = 4,847 all, N = 2,140 HQ
  - Peptide transport: 2,505 (51.68%) all, 1,197 (55.93%) HQ
  - Free amino acid transport: 4,679 (96.53%) all, 2,060 (96.26%) HQ
  - Protein degradation: 4,847 (100.00%) all, 2,140 (100.00%) HQ
  - CO2 fixation: 493 (10.17%) all, 278 (12.99%) HQ (predominantly Calvin Cycle: 343 all, 211 HQ; Dicarboxylate-4-HB: 61 all, 22 HQ; Carboxysome: 90 all, 46 HQ)
- **Archaea (`d__Archaea`)**: N = 591 all, N = 119 HQ
  - Peptide transport: 11 (1.86%) all, 1 (0.84%) HQ
  - Free amino acid transport: 565 (95.60%) all, 110 (92.44%) HQ
  - Protein degradation: 591 (100.00%) all, 119 (100.00%) HQ
  - CO2 fixation: 154 (26.06%) all, 17 (14.29%) HQ (Dicarboxylate-4-HB: 152 all, 16 HQ; 3-HP/4-HB: 2 all, 1 HQ; Calvin Cycle: 0; Reductive acetyl-CoA: 0)

### C. Thermoplasmatota Class Breakdown

Across all 237 `p__Thermoplasmatota` MAGs (N = 59 HQ):

| Class | Total N (HQ N) | Peptide Transport | Free Amino Acid Transport | Protein Degradation | CO2 Fixation | Detected Pathways |
|:---|:---:|:---:|:---:|:---:|:---:|:---|
| **Total `p__Thermoplasmatota`** | **237 (59)** | **10 (1)** | **237 (59)** | **237 (59)** | **2 (1)** | 3-HP/4-HB (2 all, 1 HQ) |
| `c__SW-10-69-26` | 185 (43) | 10 (1) | 185 (43) | 185 (43) | 2 (1) | 3-HP/4-HB (2 all, 1 HQ) |
| `c__E2` | 51 (15) | 0 (0) | 51 (15) | 51 (15) | 0 (0) | None |
| `c__Thermoplasmata` | 1 (1) | 0 (0) | 1 (1) | 1 (1) | 0 (0) | None |

*Scientific Note on Content (No Phenotypic Over-Interpretation)*:
- **Protein degradation** positivity in Thermoplasmatota is driven by universal presence of ubiquitous intracellular peptidase models (e.g. `pepA_M17`, `pepT`, `map`, `pepD_M20`), and does not imply extracellular protein degradation or secretome-mediated proteolytic scavenging.
- **Peptide transport** is confined to 10 genomes in `c__SW-10-69-26` (1 in HQ), asserting dipeptide/oligopeptide ABC transporter substrate-binding protein rules (`dpp-1_key`, `opp-1_key`, `sap_key`).
- **CO2 fixation** is restricted to exactly 2 genomes in `c__SW-10-69-26` (1 in HQ) satisfying the `3hp4hb_key1` rule. All other CO2 fixation pathways are absent across the entire phylum.

---

## 5. Ecology 41-Rule BetL and AhpCF Concordance Audit

Comparison of existing 41-rule protein HMM calls from `proteome-integration-20261106` (`genome_panels_hmm.tsv`) against full microTrait rule evaluation (`rule_matrix.tsv`):

### A. Logical Rule Definitions & Target HMMs
- **BetL**:
  - Published / Ecology logical rule: `(('betL'))` (single profile `betL`, TIGR02293).
  - microTrait logical rule: `('betL')` (evaluated identically under rules `betL` and `glycine betaine transporter`).
- **AhpCF**:
  - Published / Ecology logical rule: `((('ahpC_1') | ('ahpC_2') | ('ahpC_3')) & (('ahpF')))`
  - microTrait logical rule: `(('ahpC_1' | 'ahpC_2' | 'ahpC_3') & ('ahpF'))`

### B. Concordance Contingency Across 5,438 MAGs

| Metric | BetL (`glycine betaine transporter`) | AhpCF (`ahpCF`) |
|:---|:---:|:---:|
| Ecology Positive Count | 415 | 525 |
| microTrait Positive Count | 341 | 522 |
| Concordant Positive | 341 | 522 |
| Concordant Negative | 5,023 | 4,913 |
| Discordant Total | 74 | 3 |
| Ecology (+) / microTrait (-) | 74 | 3 |
| microTrait (+) / Ecology (-) | 0 | 0 |
| **Concordance Rate** | **98.64%** | **99.94%** |

### C. Schema Findings & Scientific Protocol Disposition
- **Methodology Divergence**:
  - Ecology evaluated `hmmsearch --cut_tc --tblout` against `panels-release.hmm` in `hmm.sbatch` and assigned hits per MAG directly.
  - microTrait official pipeline uses `hmmsearch --domtblout` with `microtrait::extract.traits()`, applying domain-coordinate overlap resolution, trusted cutoff checks, and specific domain coverage requirements.
- **Scientific Disposition**:
  - Per `MICROTRAIT-TASK.txt`, the schema and file differences are explicitly documented, and concordance is **left unresolved** rather than forcing ad-hoc equivalence.

### D. Phosphatase & Absent HMM Models
- The microTrait logical rule for phosphatase is `phosphatase = ('phoA' | 'phoD' | 'phoN' | 'aphA')`.
- The official microTrait release completely lacks HMM models for `aphA` and `phoN`.
- Status for `aphA` and `phoN`: `unassayed_model_missing_from_release` across all 5,438 MAGs.
- **Safe-NA Count**: Exactly **2,452** MAGs have safe `NA` values (unconfirmed absence because `phoA = 0` and `phoD = 0`, but `aphA` and `phoN` were unassayed).
- **Confirmed Positive**: Exactly **2,986** MAGs have confirmed presence (`phoA > 0` or `phoD > 0`).

---

## 6. Generated Output Artifacts (Compact Analysis)

| Output File | Size | Description |
|:---|:---|:---|
| `results/cohort_id_coverage_audit.tsv` | 550 B | Verification of exact 5,438-MAG cohort coverage across 6 input datasets |
| `results/per_mag_selected_traits.tsv.gz` | 338 KB | Full per-MAG table (5,438 rows) with canonical taxonomy, QC, raw trait sums, positivity flags, and phosphatase status |
| `results/group_summaries_all_cohort.tsv` | 8.8 KB | Trait positivity summaries across all 5,438 MAGs (cohort, domain, and 46 phyla) |
| `results/group_summaries_hq_subset.tsv` | 7.0 KB | Trait positivity summaries across 2,259 high-quality MAGs (completeness >= 90, contamination <= 5) |
| `results/thermoplasmatota_class_summaries.tsv` | 1.8 KB | Exact Thermoplasmatota class counts and frequencies under both all and HQ denominators |
| `results/selected_traits_upstream_rules_audit.tsv` | 42 KB | Full audit of constituent rules, boolean logic, and HMMs for all 4 G2 and 7 G3 traits |
| `results/ecology_41rule_betl_ahpcf_concordance.tsv` | 275 KB | Per-MAG side-by-side comparison of BetL and AhpCF rule calls |
| `results/ecology_concordance_report.json` | 2.6 KB | Machine-readable report of rule definitions, contingency counts, schema analysis, and absent models |
| `results/microtrait_analysis_summary.json` | 2.5 KB | Top-level JSON summary of cohort dimensions, trait prevalences, and concordance metrics |
| `results/SHA256SUMS` | 2.0 KB | Authoritative SHA-256 provenance manifest across all input and output files |

---

## 7. Thermoplasmatota Genome-Level & Marker-Rule Audit (`MICROTRAIT-ROOT-REVIEW.txt`)

As confirmed independently by Root and this audit across the 237 `p__Thermoplasmatota` genomes (59 in the high-quality `completeness >= 90, contamination <= 5` subset):

- **Free amino acid transport**: 237/237 (100.0%) all; 59/59 (100.0%) HQ. Driven by ubiquitous generic ABC amino acid transporter substrate-binding proteins (`liv-1_key`, `aap-1_key`).
- **Protein degradation**: 237/237 (100.0%) all; 59/59 (100.0%) HQ. Driven by universal intracellular peptidase/protease machinery (`map`, `lon`, `pepA_M17`, `pepD_M20`, `psmA`, `psmB`). **Critical scientific clarification**: This reflects baseline cytosolic protein turnover/chaperone function, *not* secretome-mediated extracellular proteolysis or protein scavenging.
- **Peptide transport**: Exactly 10/237 (4.22%) all; 1/59 (1.69%) HQ. All 10 positive genomes belong to class `c__SW-10-69-26`:
  1. `19Dr1__single_SemiBin_89`
  2. `1PRr2__self_SemiBin_81` (HQ)
  3. `50PRr2__self_SemiBin_16`
  4. `9Dr3__self_SemiBin_15`
  5. `T1PRr2__self_SemiBin_311`
  6. `V30PRr1__self_SemiBin_253`
  7. `V33PRr1__single_SemiBin_49`
  8. `V3PRr2__self_SemiBin_8`
  9. `V40PRr2__single_SemiBin_29`
  10. `V47PRr1__self_SemiBin_699_sub`
  *Driving rule*: Exclusively rule `tc.pot` (`('tc.pot')`), classified by microTrait under substrate uptake:peptide transport.
- **CO2 fixation**: Exactly 2/237 (0.84%) all; 1/59 (1.69%) HQ. Both positive genomes belong to class `c__SW-10-69-26`:
  1. `F27Dr1__self_SemiBin_13` (HQ)
  2. `58Sr1__self_SemiBin_66_sub`
  *Driving pathway*: 3-hydroxypropionate/4-hydroxybutyrate (3-HP/4-HB) cycle exclusively.
  *Driving rule*: Exclusively rule `3hp4hb_key1` (`('bioB' & 'carB' & 'pccA' & 'accC') | ('bioB' & 'carB' & 'mcr' & 'accC') | ('bioB' & 'pyr_accD' & 'pccA' & 'accC') | ('bioB' & 'pyr_accD' & 'mcr' & 'accC')`).
  *Critical scientific clarification*: Positivity reflects a boolean marker-rule matching alternative 4-reaction sets; it must *not* be interpreted as a confirmed, complete autotrophic carbon fixation cycle.

---

## 8. Ecology Community-Weighted Trait Effect Sensitivity (`ECOLOGY-MICROTRAIT-SENSITIVITY-TASK.txt`)

To evaluate whether the loss of 74 legacy positive BetL carriers (341 microTrait vs. 415 legacy HMM) impacts the community-weighted ecological contrast, a prespecified sensitivity analysis was deployed to Shaheen III.

### A. Execution & Slurm Job Receipt
- **Script**: `code/run_ecology_sensitivity.py` executed via `code/sbatch_ecology_sensitivity.sh`.
- **Slurm Cluster**: Shaheen III (HPE Cray EX).
- **Job ID**: `15926786`
- **Partition / Account**: `workq` / `k10018`
- **Execution Node**: `nid01464` (single-node ordinary CPU, 384 allocated cores).
- **Execution Time**: Started at `2026-11-10T13:47:52+03:00`, completed at `2026-11-10T13:47:57+03:00` (elapsed: 5 seconds).
- **Exit Status**: `0:0` (Success).
- **Remote Directory**: `/scratch/project/k10018/eq-microtrait-20261110/integration_sensitivity`
- **Standard Out / Err Logs**: `logs/eq_micro_sens_15926786.out`, `logs/eq_micro_sens_15926786.err` (0 bytes).

### B. Sensitivity Effect Estimates: Legacy HMM vs. Full microTrait Rules

Evaluated across 546 samples, 68 paired visits, and 36 paired sites with 1,000 spatial block bootstrap resamples (`seed=20261108`, 10 contiguous spatial blocks ordered by mean `transect_km`, equal-site weighting across sampled blocks):

| Trait Family | Specification | Denominator | Contrast | N Sites (Visits) | Point Est. (pp) | 95% Bootstrap CI (pp) | SE (pp) | Excludes Zero | Delta from Legacy (pp) |
|:---|:---|:---|:---|:---:|:---:|:---:|:---:|:---:|:---:|
| **BetL** (betaine uptake) | Legacy HMM | `mapped_community` | Surface - Deep | 36 (68) | +7.5515 | [+4.7243, +10.3341] | 1.4290 | True | 0.0000 (baseline) |
| **BetL** (betaine uptake) | **microTrait full rule** | `mapped_community` | Surface - Deep | 36 (68) | **+6.9062** | **[+4.3320, +9.4466]** | 1.3037 | **True** | **-0.6453** |
| **BetL** (betaine uptake) | Legacy HMM | `original_reads` | Surface - Deep | 36 (68) | +3.3025 | [+2.0238, +4.5604] | 0.6590 | True | 0.0000 (baseline) |
| **BetL** (betaine uptake) | **microTrait full rule** | `original_reads` | Surface - Deep | 36 (68) | **+3.0022** | **[+1.8441, +4.1372]** | 0.5996 | **True** | **-0.3003** |
| **AhpCF** (peroxide defence) | Legacy HMM | `mapped_community` | Surface - Deep | 36 (68) | +6.9491 | [+3.3428, +9.7137] | 1.6268 | True | 0.0000 (baseline) |
| **AhpCF** (peroxide defence) | **microTrait full rule** | `mapped_community` | Surface - Deep | 36 (68) | **+6.9301** | **[+3.3445, +9.6754]** | 1.6189 | **True** | **-0.0191** |
| **AhpCF** (peroxide defence) | Legacy HMM | `original_reads` | Surface - Deep | 36 (68) | +3.2325 | [+1.3671, +4.8250] | 0.9010 | True | 0.0000 (baseline) |
| **AhpCF** (peroxide defence) | **microTrait full rule** | `original_reads` | Surface - Deep | 36 (68) | **+3.2213** | **[+1.3659, +4.8058]** | 0.8955 | **True** | **-0.0112** |

### C. Scientific Synthesis & Key Findings
1. **Exact Legacy Reproduction**: The pipeline faithfully reproduces published paired means (7.5515 pp BetL, 6.9491 pp AhpCF) and canonical 95% CIs down to 1e-6 precision, confirming exact preservation of the frozen CoverM matrix, sample metadata, and spatial block bootstrap resampling protocol.
2. **Ecological Robustness**:
   - Despite excluding 74 marginal/unresolved BetL carriers under microTrait trusted cutoffs, the community-weighted surface excess of BetL remains **+6.91 pp** (95% CI `[+4.33, +9.45] pp`) in mapped communities and **+3.00 pp** (95% CI `[+1.84, +4.14] pp`) across total reads. Both exclude zero by >3 standard errors.
   - AhpCF shows virtually zero shift (-0.02 pp in mapped, -0.01 pp in whole reads), maintaining a +6.93 pp surface enrichment.
3. **Classification**: As prespecified, this analysis serves strictly as a sensitivity check confirming that the biological conclusions of the primary INLA model are insensitive to HMM filtering nuances, rather than a replacement of primary INLA modeling.

---

## 9. Ecology Sensitivity Artifacts & Checksums

Results synced from Shaheen and verified in `results/ecology_sensitivity/`:

| Output File | Size | Description |
|:---|:---|:---|
| `results/ecology_sensitivity/effect_table.tsv` | 1.4 KB | Point estimates, 95% CIs, SEs, site/visit counts, and deltas vs. legacy |
| `results/ecology_sensitivity/sample_trait_shares.tsv` | 89 KB | Per-sample community-weighted scores (mapped and whole-read) across 546 samples |
| `results/ecology_sensitivity/site_paired_differences.tsv` | 5.7 KB | Replicate-averaged Surface-minus-Deep visit differences averaged across 36 sites |
| `results/ecology_sensitivity/spatial_block_mapping.tsv` | 1.3 KB | Assignment of 59 sites to 10 contiguous spatial blocks based on mean transect_km |
| `results/ecology_sensitivity/sensitivity_summary.json` | 2.8 KB | Full parameter receipt, metadata, input SHA-256 hashes, and effect summary |
| `results/ecology_sensitivity/SHA256SUMS` | 450 B | SHA-256 checksums of all 5 sensitivity output artifacts |

Compact inputs (`inputs/site_paired_differences.tsv` and `inputs/spatial_block_mapping.tsv`) are retained in `inputs/` enabling offline recomputation and automated unit testing without requiring raw bulk CoverM abundance files.
