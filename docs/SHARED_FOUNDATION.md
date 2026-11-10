# Cross-Paper Shared Foundation and Mechanistic Studies Status

## 1. Overview & Repository Reference

This document establishes the relationship between this data package (`empty-quarter-data-paper`), the companion microbial ecology package (`empty-quarter-ecology`), and the archaeal proteome / mechanistic study package (`empty-quarter-proteome`).

- **Primary Repository**: `empty-quarter-proteome`
- **Relative Module Path**: `reproducibility/mechanism_20261109/shared_foundation/`
- **Local Checkout Path**: `/home/leechuck/Public/software/empty-quarter-proteome/reproducibility/mechanism_20261109/shared_foundation/`

*(Note: Mechanistic reproducibility artifacts are staged locally in the development repository and have not been pushed to the public GitHub repository; local checkout paths and relative module paths are referenced rather than external public URLs).*

---

## 2. Tripartite Paper Roles

The Rub' al Khali multi-omics investigation spans three distinct, complementary manuscripts:

1. **Data Manuscript** (`empty-quarter-data-current` / `empty-quarter-data-paper`):
   - **Role**: Foundational catalogue and institutional provenance.
   - **Scope**: Documents the landscape-scale multi-omics survey across 60 sites, specimen chain-of-custody, metagenomic assemblies, the 5,438-representative MAG catalogue, standardized environmental metadata, and the formal knowledge graph representation (KG v3.0.1).

2. **Ecology Manuscript** (`empty-quarter-ecology-current` / `empty-quarter-ecology`):
   - **Role**: Environmental and community biogeography and MAG-supported potential.
   - **Scope**: Describes landscape-scale distance decay, community assembly across dune landforms and soil depth compartments (surface, subsurface, root-adjacent), and MAG-supported functional potential (41-rule microTrait panel, compatible solute uptake, oxidative stress resistance, and trace-gas oxidation).

3. **Proteome / Mechanism Manuscript** (`empty-quarter-proteome`):
   - **Role**: Mechanistic questions.
   - **Scope**: Investigates archaeal cellular adaptations, metabolic dependencies and auxotrophies via genome-scale metabolic network models, archaeal viral host associations, and conserved genomic neighbourhoods of dark exported proteins.

---

## 3. Shared Foundation Cohorts & Reconciled Identifiers

All three packages share a common, verifiable foundation:
- **5,438 Empty Quarter MAG Catalogue**: `genome_manifest.tsv` (`EQ-MAG-REFINED-v1.0.0`), partitioned into 4,847 Bacteria and 591 Archaea.
- **Canonical GTDB Release 232 Reconciliation**: `taxonomy_reconciliation_all5438.tsv.gz` provides the canonical `canonical_gtdb_r232_classification` across all 5,438 MAGs.
- **Focal Thermoplasmatota Cohort (237 MAGs)**: `taxonomy_reconciliation_thermo237.tsv` represents the exact 237 Thermoplasmatota MAGs evaluated across the ecology and proteome manuscripts.
- **Metabolic Model Inventory (484 Genomes)**: `exp1_model_inventory_and_qc_484.tsv` contains the 237 EQ Thermoplasmatota MAGs joined 1:1 with 247 disjoint external reference comparators.

---

## 4. Status of Mechanistic Results & Boundary Contract

1. **Independent Review Pending**:
   - Mechanistic results in `empty-quarter-proteome` are currently undergoing independent scientific review, pending manuscript integration.
2. **Ongoing Results Remain Pending**:
   - Genome-scale metabolic model simulations (Experiment 1: 484-model FBA/FVA ensembles, nutrient deficiency screens, and masking controls) and archaeal virus host-association searches (Experiment 3: 591 archaeal genome screen) are **actively in progress**. Tentative outcomes must not be cited or treated as completed findings.
   - Dark exported protein analyses (Experiment 4: 1,460 family universe) confirm local operon-like adjacency for two lead families, but biochemical functions remain unassigned and associations do not survive genus-dereplicated joint FDR.
3. **No Retroactive Requirements on Existing Package**:
   - This data package retains its self-contained verification path. Verification scripts and claim tests in this package do not depend upon or require unreleased mechanistic results.
   - No provisional claims are inserted into the data manuscript or existing claim ledgers.
