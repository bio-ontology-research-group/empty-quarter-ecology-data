#!/usr/bin/env python3
"""Recompute the checksummed pre-release package manifest.

The script preserves human-curated categories, release dispositions, and
record-scope descriptions, while deriving byte sizes and SHA-256 values from
the exact staged files.  New high-risk XRF mapping artifacts are declared
here so they cannot be omitted from a regenerated manifest.

The manifest is exhaustive by construction: every file in the staging tree is
enumerated and must resolve to a classification, either an explicit per-file
entry in ``ADDITIONS`` or a directory rule in ``DIRECTORY_RULES``.  A staged
file that matches neither is an error, so a new artifact cannot enter the
package silently, and a declared row whose file is absent is also an error.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import os
import tempfile
from pathlib import Path

COLUMNS = [
    "path",
    "category",
    "release_status",
    "record_scope",
    "bytes",
    "sha256",
    "license_status",
    "license_gate",
]

RETIRED_PATHS = {
    "evidence/semantic-validation/control_semantic_validation_20260730.json",
    "evidence/semantic-validation/control_semantic_validation_20260730.log",
    "evidence/semantic-validation/control_semantic_validation_20260731.json",
    "evidence/semantic-validation/control_semantic_validation_20260731.log",
    "evidence/semantic-validation/semantic_validation_20260729.json",
    "evidence/semantic-validation/semantic_validation_20260729.log",
    "evidence/semantic-validation/semantic_validation_20260731.json",
    "evidence/semantic-validation/semantic_validation_20260731.log",
    "evidence/release/xrf_chemical_mapping_audit/SHA256SUMS",
    "evidence/release/xrf_chemical_mapping_audit/xrf_chemical_mapping_audit.json",
    "evidence/release/xrf_chemical_mapping_audit/xrf_chemical_mapping_audit.tsv",
    "scripts/analysis/__pycache__/spatial_turnover_rescue.cpython-310.pyc",
    "scripts/validation/__pycache__/validate_controls.cpython-310.pyc",
    "scripts/validation/.shex_classpath",
    "tests/__pycache__/test_control_author_confirmation.cpython-310-pytest-9.0.1.pyc",
    "tests/__pycache__/test_control_kg.cpython-310-pytest-9.0.1.pyc",
    "tests/__pycache__/test_control_negative_invariants.cpython-310-pytest-9.0.1.pyc",
    "workflow/tests/test_sample_visit_wiring.py",
    "workflow/environment.yml",
    "workflow/requirements.in",
    "workflow/requirements.lock.txt",
}


def is_build_noise(relative: str) -> bool:
    path = Path(relative)
    return (
        "__pycache__" in path.parts
        or ".nextflow-bin" in path.parts
        or ".pytest_cache" in path.parts
        or path.suffix == ".pyc"
        or path.name == ".shex_classpath"
    )

# Per-file licence disposition.  No licence identifier is asserted here: the
# deposit licence is the depositor's decision and the upstream licences of
# redistributed third-party content must be taken from the pinned upstream
# releases.  Each row therefore records which gate is open and what evidence
# closes it, instead of an opaque PENDING marker.
AUTHOR_GATE = (
    "AUTHOR_GATE_UNRESOLVED",
    "Project-produced artifact. The depositor selects the deposit licence; "
    "replace only when the deposit metadata supplies the licence identifier.",
)
THIRD_PARTY_GATE_TEMPLATE = (
    "THIRD_PARTY_LICENCE_UNRECORDED",
    "Redistributes content derived from {source}. Record that resource's own "
    "licence for the pinned release before deposition; the project licence "
    "does not govern it.",
)

# Longest-prefix rules for staged files that redistribute third-party content.
THIRD_PARTY_SOURCES: tuple[tuple[str, str], ...] = (
    ("ontology/ncbitaxon_module.owl", "the pinned NCBI Taxonomy release"),
    ("ontology/rubalkhali_taxonomy_rak.owl", "the pinned NCBI Taxonomy release"),
    ("ontology/mapped_taxonomy_corrected.", "the pinned NCBI Taxonomy release"),
    ("ontology/ecosystem_module.", "the imported OBO Foundry and Unified Ecosystem ontologies"),
    ("metadata/taxonomy/taxonomy", "the SILVA reference database used by the classifier"),
    (
        "evidence/controls/source_snapshots/ibex_20250714_qiime2/extracted/taxonomy.tsv",
        "the SILVA reference database used by the classifier",
    ),
    (
        "metadata/comparators/atacama/",
        "the pinned public Atacama gradient and depth-profile datasets",
    ),
)


def license_disposition(relative: str) -> tuple[str, str]:
    """Licence status and gate text for one staged file."""
    best: tuple[int, str] | None = None
    for prefix, source in THIRD_PARTY_SOURCES:
        if relative.startswith(prefix) and (best is None or len(prefix) > best[0]):
            best = (len(prefix), source)
    if best is None:
        return AUTHOR_GATE
    status, template = THIRD_PARTY_GATE_TEMPLATE
    return status, template.format(source=best[1])

ADDITIONS = {
    "evidence/controls/source_snapshots/ibex_20250714_qiime2/extracted/feature-table.biom": (
        "control-source",
        "canonical-candidate",
        "analysis-ready July 2025 feature table used to evaluate replicated positive controls and compatible negative controls",
    ),
    "evidence/controls/source_snapshots/ibex_20250714_qiime2/extracted/taxonomy.tsv": (
        "control-source",
        "canonical-candidate",
        "taxonomy assignments paired byte-for-byte with the July 2025 control-audit feature table",
    ),
    "config/codes/xrf_chebi_mapping_validated.yml": (
        "xrf-mapping",
        "audit-evidence",
        "legacy validated ChEBI projection retained as an exact regression copy of the canonical chemical mapping",
    ),
    "ontology/rubalkhali_ph_eq_ph_shared_v1_0_0.ttl": (
        "ph-measurement-graph",
        "canonical-candidate",
        "Turtle serialization of 712 admitted archived-soil pH observations using the SIO measurement pattern",
    ),
    "ontology/rubalkhali_ph_eq_ph_shared_v1_0_0.owl": (
        "ph-measurement-graph",
        "canonical-candidate",
        "graph-equivalent RDF/XML serialization of the shared pH module",
    ),
    "ontology/rubalkhali_controls.ttl": (
        "control-graph",
        "canonical-candidate",
        "SIO-patterned control ABox in Turtle: material, role, process, batch, "
        "sequence occurrence, composition, evidence and disposition",
    ),
    "ontology/rubalkhali_controls.owl": (
        "control-graph",
        "canonical-candidate",
        "RDF/XML serialization of the SIO-patterned control ABox",
    ),
    "ontology/ncbitaxon_release_identity.json": (
        "taxonomy-provenance",
        "audit-evidence",
        "machine-readable source ontology IRI, version IRI, versionInfo, "
        "taxonomy source version and checksums for the pinned NCBITaxon source "
        "and its staged subset; the unrecorded retrieval date remains explicit",
    ),
    "metadata/DATA_DICTIONARY.tsv": (
        "data-dictionary",
        "canonical-candidate",
        "field names, data types, units, missing-value conventions and reuse definitions",
    ),
    "metadata/samples/site_iri_registry.tsv": (
        "source-metadata",
        "canonical-candidate",
        "stable bijection for the 10 named site labels and their project IRIs",
    ),
    "metadata/samples/site_aliases.tsv": (
        "source-metadata",
        "canonical-candidate",
        "four coordinate-confirmed Trip 1 numeric-to-named site aliases",
    ),
    "metadata/samples/EB_Sample_Map_FourthTrip2.xlsx": (
        "control-source",
        "canonical-candidate",
        "laboratory extraction-day map for Trip 4 specimens and extraction blanks",
    ),
    "metadata/samples/Sequenced_Samples_by_EB_FifthTrip.xlsx": (
        "control-source",
        "canonical-candidate",
        "laboratory extraction-day map for Trip 5 specimens and extraction blanks",
    ),
    "scripts/rdf/generate_samples_abox.groovy": (
        "release-code",
        "audit-evidence",
        "specimen generator preserving numeric IDs while resolving site aliases",
    ),
    "metadata/metagenome/coverm_profiles.tar.gz": (
        "companion-analysis-input",
        "canonical-candidate",
        "150 genome-relative-abundance profiles used by the encoded-function null",
    ),
    "metadata/metagenome/eq.emapper.annotations.gz": (
        "companion-analysis-input",
        "canonical-candidate",
        "eggNOG annotation table used to construct the 990-genome KO matrix",
    ),
    "metadata/metagenome/measured_function_inputs.tar.gz": (
        "companion-analysis-input",
        "canonical-candidate",
        "six inputs for the PICRUSt2, shotgun-KO, and marker-summary module",
    ),
    "metadata/relic-dna/PMA_ASV_table.tsv": (
        "companion-analysis-input",
        "canonical-candidate",
        "ASV count matrix for nine paired Trip 5 PMA aliquots",
    ),
    "evidence/companion-analysis/derived_input_archives.SHA256SUMS": (
        "companion-analysis-evidence",
        "audit-evidence",
        "checksums for the deposited functional and PMA analysis inputs",
    ),
    "scripts/analysis/functional_redundancy_null.py": (
        "analysis-code",
        "audit-evidence",
        "resolution-matched intact-genome-label null analysis",
    ),
    "scripts/analysis/measured_function_summary.py": (
        "analysis-code",
        "audit-evidence",
        "PICRUSt2, shotgun-KO, and metabolic-marker summary",
    ),
    "scripts/analysis/pma_endpoint_analysis.py": (
        "analysis-code",
        "audit-evidence",
        "paired deterministic PMA endpoint analysis",
    ),
    "sparql/field_xrf_site10.rq": (
        "competency-query",
        "canonical-candidate",
        "bounded field-XRF Site 10 query with a workflow-checked cardinality",
    ),
    "scripts/validation/validate_competency_query.py": (
        "validation-code",
        "audit-evidence",
        "RDFLib execution gate for the bounded field-XRF query",
    ),
    "evidence/competency-query/competency_query_validation.json": (
        "query-evidence",
        "audit-evidence",
        "query engine, input hashes, process labels, and 46-row result",
    ),
    "evidence/competency-query/field_xrf_site10_results.tsv": (
        "query-evidence",
        "audit-evidence",
        "complete ordered 46-row field-XRF query result",
    ),
    "evidence/competency-query/field_xrf_site10.rq": (
        "query-evidence",
        "audit-evidence",
        "byte-identical query snapshot executed by the validation workflow",
    ),
    "evidence/competency-query/SHA256SUMS": (
        "query-evidence",
        "audit-evidence",
        "checksums for the competency-query evidence",
    ),
    "metadata/samplesheets/trip1-2023.tsv": (
        "environmental-source",
        "canonical-candidate",
        "Trip 1 immutable field environmental sheet",
    ),
    "metadata/samplesheets/trip2-2023.tsv": (
        "environmental-source",
        "canonical-candidate",
        "Trip 2 immutable field sheet; shifted cells curated by ledger",
    ),
    "metadata/samplesheets/trip3-2024.tsv": (
        "environmental-source",
        "canonical-candidate",
        "Trip 3 immutable field sheet; appended dates curated by ledger",
    ),
    "metadata/samplesheets/trip4-2024.tsv": (
        "environmental-source",
        "canonical-candidate",
        "Trip 4 immutable field environmental sheet",
    ),
    "metadata/samplesheets/trip5-2025.tsv": (
        "environmental-source",
        "canonical-candidate",
        "Trip 5 immutable field sheet; invalid humidity quarantined by ledger",
    ),
    "metadata/samplesheets/additional_fastqs_v2.tsv": (
        "control-source",
        "canonical-candidate",
        "sequencing-library and FASTQ-path ledger used to identify Trip 4 control libraries",
    ),
    "metadata/samples/environmental_measurement_corrections.tsv": (
        "environmental-curation",
        "canonical-candidate",
        "24 exact-cell dispositions: 8 shifted values, 15 dates, 1 quarantine",
    ),
    "metadata/environmental/environmental_measurements_curated.tsv": (
        "environmental-derived",
        "canonical-candidate",
        "274 range-checked field environmental records",
    ),
    "evidence/environmental/environmental_measurements_audit.json": (
        "environmental-evidence",
        "audit-evidence",
        "source hashes, correction dispositions, ranges, and campaign dates",
    ),
    "evidence/environmental/Trip_Metadata.xlsx": (
        "environmental-source",
        "audit-evidence",
        "legacy workbook supporting Trip 3 humidity and campaign-date curation",
    ),
    "scripts/metadata/generate_env_table.py": (
        "release-code",
        "audit-evidence",
        "deterministic environmental curation and supplementary-table generator",
    ),
    "scripts/rdf/generate_measurements_abox.groovy": (
        "release-code",
        "audit-evidence",
        "environmental RDF generator consuming the exact-cell correction ledger",
    ),
    "config/codes/xrf_chemical_mapping.yml": (
        "xrf-mapping",
        "canonical-candidate",
        "single canonical mapping for all 93 instrument reporting channels",
    ),
    "config/codes/xrf_chebi_mapping.yml": (
        "xrf-mapping",
        "audit-evidence",
        "ChEBI-only projection regression-tested against the canonical mapping",
    ),
    "config/codes/xrf_pubchem_snapshot.json": (
        "external-reference-snapshot",
        "audit-evidence",
        "dated PubChem property snapshot used by the fail-closed mapping audit",
    ),
    "evidence/xrf_chemical_mapping_audit/xrf_chemical_mapping_audit.json": (
        "xrf-evidence",
        "audit-evidence",
        "machine-readable 93-row chemical-identifier audit and source hashes",
    ),
    "evidence/xrf_chemical_mapping_audit/xrf_chemical_mapping_audit.tsv": (
        "xrf-evidence",
        "audit-evidence",
        "human-readable labels, formulas, charges, entity types and dispositions",
    ),
    "evidence/xrf_chemical_mapping_audit/SHA256SUMS": (
        "xrf-evidence",
        "audit-evidence",
        "checksums for the chemical-mapping audit outputs",
    ),
    "scripts/xrf/audit_xrf_chemical_mapping.py": (
        "release-code",
        "audit-evidence",
        "fail-closed pinned-ChEBI and PubChem mapping validator",
    ),
    "scripts/xrf/audit_xrf_provenance.py": (
        "release-code",
        "audit-evidence",
        "field/laboratory XRF source and aggregation reconciliation",
    ),
}

# Existing rows retain their curated classifications when the manifest is
# regenerated.  These explicit overrides are for artifacts whose scientific
# disposition changed after they first entered the staging tree.
MANIFEST_OVERRIDES = {
    "evidence/contaminant-screen/README.md": (
        "contaminant-evidence",
        "legacy-excluded",
        "warning and provenance note for the superseded pooled prevalence screen",
    ),
    "evidence/contaminant-screen/control_prevalent_features_annotated.tsv": (
        "contaminant-evidence",
        "legacy-excluded",
        "superseded pooled prevalence screen retained only as audit history",
    ),
    "evidence/contaminant-screen/removal_fraction_by_group.tsv": (
        "contaminant-evidence",
        "legacy-excluded",
        "superseded pooled removal summary retained only as audit history",
    ),
    "evidence/contaminant-screen/removal_fraction_by_sample.tsv": (
        "contaminant-evidence",
        "legacy-excluded",
        "superseded pooled removal summary retained only as audit history",
    ),
    "evidence/contaminant-screen/summary.json": (
        "contaminant-evidence",
        "legacy-excluded",
        "superseded 14,822-feature screen retained only as audit history",
    ),
}


# Directory-level classification for staged files without an explicit entry
# above.  Rules are matched longest-prefix first; a trailing "/" matches every
# file at or below that directory, otherwise the rule matches an exact path.
DIRECTORY_RULES: tuple[tuple[str, tuple[str, str, str]], ...] = (
    (
        "README.md",
        (
            "release-documentation",
            "canonical-candidate",
            "package README: directory layout, provenance boundaries, reuse notes",
        ),
    ),
    (
        "void.ttl",
        (
            "release-metadata",
            "canonical-candidate",
            "minimal pre-release VoID identity without unverified licence, "
            "version, service, access or download assertions",
        ),
    ),
    (
        "pytest.ini",
        (
            "validation-config",
            "audit-evidence",
            "pytest discovery configuration used by the staged regression tests",
        ),
    ),
    (
        "deploy_onto.sh",
        (
            "release-code",
            "operational-reference",
            "deployment helper for the public endpoint; not required to rebuild records",
        ),
    ),
    (
        "manage.sh",
        (
            "release-code",
            "operational-reference",
            "container lifecycle helper; not required to rebuild records",
        ),
    ),
    (
        "config/codes/biome_codes.yml",
        (
            "config-source",
            "canonical-candidate",
            "biome and environmental-feature code table consumed by the site generator",
        ),
    ),
    (
        "metadata/taxonomy/README.md",
        (
            "taxonomy-source",
            "audit-evidence",
            "canonical versus legacy-excluded disposition of the staged taxonomy tables",
        ),
    ),
    (
        "metadata/xrf/xrf-measurements.tsv",
        (
            "xrf-source",
            "canonical-candidate",
            "consolidated instrument export underlying the laboratory XRF table",
        ),
    ),
    (
        "metadata/xrf/all-trips-consolidated/",
        (
            "xrf-source",
            "canonical-candidate",
            "Trips 1--4 consolidated laboratory XRF source workbook used to reproduce the 547-record analytical table",
        ),
    ),
    (
        "metadata/geochemistry/xrf/",
        (
            "xrf-source",
            "canonical-candidate",
            "field XRF instrument value and acquisition-metadata exports for the 71 complete sessions",
        ),
    ),
    (
        "evidence/ph/",
        (
            "ph-evidence",
            "audit-evidence",
            "pH source reconciliation, ecology analysis, cross-version comparison, ShEx validation and checksums",
        ),
    ),
    (
        "evidence/release/",
        (
            "release-evidence",
            "audit-evidence",
            "release-evidence builder outputs and their checksums",
        ),
    ),
    (
        "evidence/release/taxonomy_mapping_audit/",
        (
            "taxonomy-evidence",
            "audit-evidence",
            "fail-closed taxonomy mapping decisions, violations, and source schema audit",
        ),
    ),
    (
        "evidence/release/xrf_chemical_mapping_audit/",
        (
            "xrf-evidence",
            "audit-evidence",
            "pinned ChEBI and PubChem chemical-identifier audit outputs",
        ),
    ),
    (
        "evidence/xrf_audit/",
        (
            "xrf-evidence",
            "audit-evidence",
            "field and laboratory XRF provenance, aggregation, and metadata-gap audit",
        ),
    ),
    (
        "evidence/controls/",
        (
            "control-evidence",
            "audit-evidence",
            "current author-confirmed product, stage and assay ground truth plus "
            "clearly marked historical preliminary identity evidence",
        ),
    ),
    (
        "evidence/control-audit/",
        (
            "control-analysis-evidence",
            "audit-evidence",
            "assay-aware blank prevalence, positive-control recovery, exact-ASV "
            "overlap, removal fractions and pre/post-filter tables",
        ),
    ),
    (
        "evidence/control-sensitivity/",
        (
            "control-sensitivity-evidence",
            "audit-evidence",
            "package-only replay command, repository-run provenance and 25 "
            "before/after ecology headline comparisons",
        ),
    ),
    (
        "evidence/ecology-canonical/",
        (
            "ecology-analysis-evidence",
            "audit-evidence",
            "checksummed baseline caches and canonical verdict tables required "
            "to replay and compare the bounded control-filter sensitivity",
        ),
    ),
    (
        "evidence/xrf-community/",
        (
            "xrf-analysis-evidence",
            "audit-evidence",
            "laboratory-XRF elemental axis and loadings consumed by the "
            "control-adjusted community analysis",
        ),
    ),
    (
        "evidence/primer-identity/",
        (
            "primer-evidence",
            "audit-evidence",
            "source-path ledger and exact forward/reverse primer identity counts",
        ),
    ),
    (
        "evidence/contaminant-screen/",
        (
            "contaminant-evidence",
            "audit-evidence",
            "prevalence screen of the canonical feature table against its control profiles",
        ),
    ),
    (
        "evidence/semantic-validation/",
        (
            "semantic-validation-evidence",
            "audit-evidence",
            "current ELK, ShEx, label-uniqueness and IRI-registry run with checksums",
        ),
    ),
    (
        "evidence/core-kg-regeneration/",
        (
            "core-kg-regeneration-evidence",
            "audit-evidence",
            "current-source core-module regeneration manifests, generator logs and checksums",
        ),
    ),
    (
        "evidence/taxonomy-abox/",
        (
            "taxonomy-evidence",
            "audit-evidence",
            "full-file taxonomy ABox streaming validation, independent parser log, "
            "input manifest and checksums",
        ),
    ),
    (
        "scripts/controls/",
        (
            "control-code",
            "audit-evidence",
            "control discovery and contaminant-screen implementation",
        ),
    ),
    (
        "scripts/amplicon/",
        (
            "amplicon-code",
            "audit-evidence",
            "portable samplesheet construction from the deposited submission records",
        ),
    ),
    (
        "scripts/climate/",
        (
            "climate-code",
            "audit-evidence",
            "exact-key climate curation and recoverable acquisition-provenance capture",
        ),
    ),
    (
        "scripts/utils/",
        (
            "climate-code",
            "audit-evidence",
            "frozen-window Open-Meteo acquisition scripts with response snapshots",
        ),
    ),
    (
        "metadata/samples/ph/",
        (
            "ph-source",
            "canonical-candidate",
            "frozen pH workbooks, version manifests, registry and version policy",
        ),
    ),
    (
        "metadata/ph/",
        (
            "ph-derived",
            "canonical-candidate",
            "row-level pH audit, admitted measurements, session table and stable entity registry",
        ),
    ),
    (
        "metadata/amplicon/",
        (
            "amplicon-processing",
            "canonical-candidate",
            "portable ampliseq samplesheet, accession table, resource config and "
            "the canonical command",
        ),
    ),
    (
        "metadata/functional/",
        (
            "functional-processing",
            "audit-evidence",
            "PICRUSt2 execution manifest: version, commands, parameters and resources",
        ),
    ),
    (
        "metadata/comparators/atacama/",
        (
            "cross-desert-comparator-source",
            "canonical-candidate",
            "pinned public Atacama site-level gradient and depth-profile inputs "
            "used for the quantitative contextual reanalysis",
        ),
    ),
    (
        "metadata/controls/",
        (
            "control-metadata",
            "canonical-candidate",
            "normalized materials, aliases, roles, processes, sequence occurrences, "
            "composition specifications, evidence assertions and dispositions",
        ),
    ),
    (
        "evidence/bibliography/",
        (
            "bibliography-evidence",
            "audit-evidence",
            "source-custody audit of every cited work",
        ),
    ),
    (
        "evidence/accessions/",
        (
            "accession-evidence",
            "audit-evidence",
            "live archive reconciliation of the cited project and run accessions",
        ),
    ),
    (
        "metadata/QC_reads/",
        (
            "qc-source",
            "canonical-candidate",
            "MultiQC per-run FastQC statistics underlying the sequencing QC records",
        ),
    ),
    (
        "metadata/climate/",
        (
            "climate-derived",
            "canonical-candidate",
            "Open-Meteo derived daily and monthly tables consumed by the climate generator",
        ),
    ),
    (
        "metadata/geodata/",
        (
            "geodata-source",
            "canonical-candidate",
            "per-trip site coordinates, altitudes, and site-to-trip mapping",
        ),
    ),
    (
        "metadata/protocols/",
        (
            "protocol-source",
            "canonical-candidate",
            "protocol descriptions referenced by protocol-execution individuals",
        ),
    ),
    (
        "metadata/sra-submissions/",
        (
            "accession-source",
            "canonical-candidate",
            "submitted ENA sample and run sheets backing the accession cross-references",
        ),
    ),
    (
        "metadata/xrf/trip-5-lab/",
        (
            "xrf-source",
            "canonical-candidate",
            "per-session Trip 5 laboratory XRF instrument export",
        ),
    ),
    (
        "metadata/xrf/xrf-lab/",
        (
            "xrf-source",
            "canonical-candidate",
            "Trip 5 laboratory XRF result workbook as received from the laboratory",
        ),
    ),
    (
        "ontology-src/",
        (
            "ontology-source",
            "canonical-candidate",
            "hand-maintained Turtle sources merged into the generated terminology",
        ),
    ),
    (
        "scripts/rdf/",
        (
            "release-code",
            "audit-evidence",
            "Groovy or Python generator producing a staged ABox or terminology module",
        ),
    ),
    (
        "scripts/release/",
        (
            "release-code",
            "audit-evidence",
            "release reconciliation and package-layout bootstrap utilities",
        ),
    ),
    (
        "scripts/xrf/",
        (
            "release-code",
            "audit-evidence",
            "XRF provenance, identifier and unit-evidence validation code",
        ),
    ),
    (
        "scripts/analysis/",
        (
            "analysis-code",
            "audit-evidence",
            "downstream statistical analysis used by a staged result",
        ),
    ),
    (
        "scripts/taxonomy-alignment/",
        (
            "taxonomy-code",
            "legacy-excluded",
            "historical cross-resource alignment tooling; its GTDB and iNaturalist "
            "candidates are not asserted in the release graph",
        ),
    ),
    (
        "scripts/taxonomy/",
        (
            "taxonomy-code",
            "audit-evidence",
            "canonical taxonomy mapping builder and pinned NCBITaxon index reader",
        ),
    ),
    (
        "scripts/validation/",
        (
            "validation-code",
            "audit-evidence",
            "validation gate executed against the generated modules",
        ),
    ),
    (
        "environment/",
        (
            "execution-environment",
            "audit-evidence",
            "explicit Linux Conda package lock, pinned cross-platform recipe, "
            "and hash-locked Python inputs used by the reproducible workflow",
        ),
    ),
    (
        "workflow/",
        (
            "reproducible-workflow",
            "audit-evidence",
            "Nextflow orchestration, stage manifest, execution wrappers and "
            "workflow regression tests for the frozen analysis sequence",
        ),
    ),
    (
        "tests/",
        (
            "validation-fixture",
            "audit-evidence",
            "positive, negative and invariant regression tests for the staged control model",
        ),
    ),
    (
        "shex/",
        (
            "validation-shape",
            "canonical-candidate",
            "ShEx shape enforcing the structural contract of one entity family",
        ),
    ),
    (
        "sparql/",
        (
            "query-documentation",
            "audit-evidence",
            "query patterns and schema notes for the published graph",
        ),
    ),
)


def classify(relative: str) -> tuple[str, str, str] | None:
    """Longest-prefix classification for a staged file, or None if unmatched."""
    best: tuple[int, tuple[str, str, str]] | None = None
    for pattern, values in DIRECTORY_RULES:
        if pattern.endswith("/"):
            matched = relative.startswith(pattern)
        else:
            matched = relative == pattern
        if matched and (best is None or len(pattern) > best[0]):
            best = (len(pattern), values)
    return None if best is None else best[1]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--stage",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "zenodo",
    )
    args = parser.parse_args()
    stage = args.stage.resolve()
    manifest = stage / "PRE_RELEASE_MANIFEST.tsv"

    with manifest.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    if not rows:
        parser.error(f"empty manifest in {manifest}")
    rows = [
        row
        for row in rows
        if row["path"] not in RETIRED_PATHS and not is_build_noise(row["path"])
    ]
    legacy_columns = [column for column in COLUMNS if column not in ("license_status", "license_gate")]
    if list(rows[0]) not in (COLUMNS, legacy_columns):
        parser.error(f"unexpected manifest schema in {manifest}")
    by_path = {row["path"]: row for row in rows}
    if len(by_path) != len(rows):
        parser.error("manifest contains duplicate paths")

    for relative, (category, status, scope) in ADDITIONS.items():
        if relative not in by_path:
            row = {
                "path": relative,
                "category": category,
                "release_status": status,
                "record_scope": scope,
                "bytes": "",
                "sha256": "",
            }
            rows.append(row)
            by_path[relative] = row

    for relative, (category, status, scope) in MANIFEST_OVERRIDES.items():
        if relative not in by_path:
            row = {
                "path": relative,
                "category": category,
                "release_status": status,
                "record_scope": scope,
                "bytes": "",
                "sha256": "",
            }
            rows.append(row)
            by_path[relative] = row
        else:
            by_path[relative].update(
                category=category,
                release_status=status,
                record_scope=scope,
            )

    staged = sorted(
        str(path.relative_to(stage))
        for path in stage.rglob("*")
        if path.is_file()
        and path.name != manifest.name
        and not is_build_noise(str(path.relative_to(stage)))
    )
    unclassified = []
    for relative in staged:
        if relative in by_path:
            continue
        values = classify(relative)
        if values is None:
            unclassified.append(relative)
            continue
        category, status, scope = values
        row = {
            "path": relative,
            "category": category,
            "release_status": status,
            "record_scope": scope,
            "bytes": "",
            "sha256": "",
        }
        rows.append(row)
        by_path[relative] = row
    for row in rows:
        row["license_status"], row["license_gate"] = license_disposition(row["path"])
    if unclassified:
        parser.error(
            "staged files have no classification; add an ADDITIONS entry or a "
            f"DIRECTORY_RULES rule for: {unclassified[:10]}"
            + (f" (+{len(unclassified) - 10} more)" if len(unclassified) > 10 else "")
        )

    for row in rows:
        artifact = stage / row["path"]
        if not artifact.is_file():
            parser.error(f"staged artifact is missing: {row['path']}")
        row["bytes"] = str(artifact.stat().st_size)
        row["sha256"] = sha256(artifact)

    rows.sort(key=lambda row: row["path"])

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".PRE_RELEASE_MANIFEST.",
        suffix=".tsv",
        dir=stage,
        text=True,
    )
    try:
        with os.fdopen(descriptor, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle,
                delimiter="\t",
                fieldnames=COLUMNS,
                lineterminator="\n",
            )
            writer.writeheader()
            writer.writerows(rows)
            handle.flush()
            os.fsync(handle.fileno())
        Path(temporary_name).replace(manifest)
    except BaseException:
        Path(temporary_name).unlink(missing_ok=True)
        raise

    print(f"PASS: checksummed {len(rows)} staged artifacts in {manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
