# Validation Strategy

This document outlines the validation procedures for the Empty Quarter Knowledge Base. We employ a multi-layered validation strategy to ensure data integrity, logical consistency, and structural correctness.

## Quick Start

To run the full validation suite:

```bash
./scripts/validate_all.sh
```

This script generates a log file (e.g., `validation_report_YYYYMMDD_HHMMSS.log`) and summarizes the results.

## Validation Layers

### 1. Data Integrity (Source Level)
**Scope:** Raw data files (XRF, spreadsheets).
**Goal:** Ensure source data is complete and not corrupted before RDF generation.

*   **Script:** `scripts/verify_xrf_integrity.groovy`
*   **Checks:** 
    *   Parses `.xrf` or `.csv` exports from XRF devices.
    *   Verifies that file headers match expected formats.
    *   Checks for missing or anomalous values.

### 2. Logical Consistency (Ontology Level)
**Scope:** Generated RDF/OWL files.
**Goal:** Ensure the ontology is logically consistent (satisfiable) according to OWL 2 EL profile.

*   **Script:** `scripts/validate_consistency.groovy`
*   **Tool:** ELK Reasoner (via OWL API).
*   **Checks:**
    *   Loads the ontology and all imports.
    *   Runs the reasoner to check for unsatisfiable classes (inconsistencies).
    *   Reports any conflicting axioms.

### 3. Structural Validation (ShEx)
**Scope:** RDF Graph structure.
**Goal:** Ensure the RDF data conforms to the defined shapes and constraints (e.g., correct properties, cardinality, datatypes).

*   **Script:** `scripts/validate_rdf.groovy`
*   **Tool:** Apache Jena ShEx.
*   **Definitions:** stored in `data/processed/shex/`
    *   `sites.shex`: Validates Site and Region entities.
    *   `samples.shex`: Validates Sample and Collection entities.
    *   `measurements.shex`: Validates generic Measurement processes.
    *   `dna.shex`: Validates DNA Extracts and Concentrations.
    *   `sra.shex`: Validates Sequencing Libraries, Prep Experiments, and FASTQ Datasets.
    *   `qc.shex`: Validates Sequencing QC metrics (GC content, read count, length, duplicates).
    *   `xrf.shex`: Validates XRF measurements.
*   **Process:**
    *   Loads the RDF graphs.
    *   Selects nodes based on their `rdf:type`.
    *   Validates them against the corresponding Shape in the ShEx schema.

### 4. Integration & Query Validation (System Level)
**Scope:** Loaded Virtuoso Database.
**Goal:** Ensure the data is correctly loaded and queryable in the production triple store.

*   **Script:** `scripts/test_virtuoso_sparql.groovy`
*   **Prerequisites:** Virtuoso container must be running (`docker-compose up` in `viz/`).
*   **Checks:**
    *   Executes a set of reference SPARQL queries against the local endpoint.
    *   Verifies that specific "known truths" (Golden Records) exist.
    *   Checks that counts of triples match expectations.

### 5. Taxonomy Reconstruction Validation
**Scope:** Materialized Taxonomy Data (Virtuoso).
**Goal:** Ensure that OTU tables (abundance matrices) can be accurately reconstructed from the RDF graph and match the original source files.

*   **Script:** `scripts/validate_taxonomy_abundance.groovy`
*   **Prerequisites:** Virtuoso container running, `data/processed/taxon-tables/feature-table.tsv` present.
*   **Checks:**
    *   Queries the triple store for absolute and relative abundance values for specific samples.
    *   Sums the values retrieved via SPARQL.
    *   Compares these sums against the original values in `feature-table.tsv` to ensure 1:1 fidelity.

### 6. Measurement-pattern conformance (canonical SIO reification)
**Scope:** the abstract pattern every per-domain ABox generator must follow.
**Goal:** Detect direction reversals and shape drift in `is-measurement-value-of` (SIO_000215) usage. See `docs/MEASUREMENT_PATTERN.md` for the full design.

*   **Script:** `tests/measurement_pattern/run_tests.groovy`
*   **Tool:** ELK Reasoner + Apache Jena ShEx.
*   **Checks (3 stages):**
    *   ELK consistency on a minimal TBox + ABox encoding the pattern.
    *   ELK class-subsumption derivation: `Quality ⊑ ∃isAttributeOf.Bearer` via the property chain `hasMeasurementValue ∘ isOutputOf ∘ hasTarget ⊑ isAttributeOf`.
    *   ShEx conformance: a fully-asserted graph passes; a reversed-direction graph (`quality SIO_000215 value` instead of `value SIO_000215 quality`) is rejected.
*   **Run:** `groovy tests/measurement_pattern/run_tests.groovy`. No Virtuoso required.

### 7. Released-shape negative fixtures
**Scope:** the shapes actually shipped in `data/processed/semantics/shex/`.
**Goal:** Prove that each declared defect class is rejected, not merely that valid data passes. Check 6 uses a self-contained toy schema; this one drives the released shapes.

*   **Script:** `tests/shex_negatives/run_tests.groovy`
*   **Tool:** Apache Jena ShEx.
*   **Checks (7 fixtures, each a positive/negative pair differing in one respect):**
    *   `sites.shex` — a sampling site with `geo:asWKT` conforms; one without it is rejected. All 70 released site individuals carry a geometry, so the property is required rather than optional.
    *   `measurements.shex` — a canonical climate measurement conforms; the same graph with the payload typed `xsd:string` instead of `xsd:double` is rejected, as is the reversed `quality SIO_000215 value` direction.
    *   `xrf.shex` — a laboratory XRF process declaring `SIO_000230` conforms; a process declaring neither an input nor a target is rejected.
*   **Run:** `groovy tests/shex_negatives/run_tests.groovy`. No Virtuoso required.

## Running Individual Checks

If a specific step fails, you can run it individually to debug:

```bash
# 1. XRF Integrity
groovy scripts/verify_xrf_integrity.groovy

# 2. Consistency
groovy scripts/validate_consistency.groovy

# 3. ShEx Validation
groovy scripts/validate_rdf.groovy

# 4. SPARQL Tests
groovy scripts/test_virtuoso_sparql.groovy

# 6. Measurement-pattern conformance (no Virtuoso needed)
groovy tests/measurement_pattern/run_tests.groovy

# 7. Released-shape negative fixtures (no Virtuoso needed)
groovy tests/shex_negatives/run_tests.groovy
```
