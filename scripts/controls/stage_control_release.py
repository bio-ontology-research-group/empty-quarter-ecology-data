#!/usr/bin/env python3
"""Stage the validated control model and audit in the reviewer package.

The release is intentionally narrower than the private source-evidence tree:
it includes the author-confirmed ground truth, normalized records, generated
RDF, structural shape, analysis outputs, and replay code. Private-message
screenshots and third-party PDFs remain source-custody evidence and are not
redistributed by this script.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
from pathlib import Path


AUDIT_FILES = (
    "control_analysis_roles.tsv",
    "positive_control_dominant_taxa.tsv",
    "positive_control_expected_asv_occurrences.tsv",
    "positive_control_expected_taxon_recovery.tsv",
    "positive_control_index_neighbours.tsv",
    "positive_control_profiles.tsv",
    "positive_control_spillover_summary.json",
    "positive_control_spillover_summary.tsv",
    "run_manifest.json",
    "summary.json",
    "trip5_extraction_batch_summary.tsv",
    "trip5_filter_sensitivity.tsv",
    "trip5_mapped_feature_table_control_filtered.tsv.gz",
    "trip5_primary_contaminant_calls.tsv",
    "trip5_removal_fraction_by_campaign.tsv",
    "trip5_removal_fraction_by_compartment.tsv",
    "trip5_removal_fraction_by_profile.tsv",
    "sensitivity_inputs/alpha.tsv",
    "sensitivity_inputs/alpha_diversity_sensitivity.tsv",
    "sensitivity_inputs/asv_filt_counts.tsv.gz",
    "sensitivity_inputs/genus_counts.tsv.gz",
    "sensitivity_inputs/summary.json",
    "sensitivity_inputs/trip5_paired_compartment_sensitivity.tsv",
)

CONTROL_SCRIPTS = (
    "audit_positive_control_spillover.py",
    "build_control_sensitivity_inputs.py",
    "replay_control_sensitivity_package.sh",
    "run_assay_aware_control_audit.py",
    "run_control_ecology_sensitivity.sh",
    "stage_control_release.py",
    "summarize_control_ecology_sensitivity.py",
    "write_control_manifests.py",
)

CONTROL_VALIDATION_FIXTURES = (
    "control_positive.ttl",
    "control_negative_wrong_blank_stage.ttl",
    "control_negative_missing_specification_source.ttl",
    "site_positive.ttl",
    "negative_missing_coordinates.ttl",
    "positive.ttl",
    "negative_invalid_datatype.ttl",
    "negative_reversed_measurement_link.ttl",
    "xrf_positive.ttl",
    "negative_missing_process_input.ttl",
    "run_tests.groovy",
)

ECOLOGY_SCRIPTS = (
    "claim_rescue.py",
    "compartment_composition_rescue.py",
    "cross_desert_context.py",
    "depth_extraction_sensitivity.py",
    "distance_decay_turnover.py",
    "environment_associations.py",
    "evenness_decomposition_analysis.py",
    "geographic_prediction.py",
    "make_submission_figures.py",
    "picrust2_ecology.py",
    "rain_response_window.py",
    "spatial_resolution_sensitivity.py",
    "spatial_turnover_rescue.py",
    "xrf_community_clr_sensitivity.py",
)

CORE_ONTOLOGY_MODULES = (
    "rubalkhali.owl",
    "rubalkhali_kb.owl",
    "rubalkhali_sites.owl",
    "rubalkhali_measurements.owl",
    "rubalkhali_samples.owl",
    "rubalkhali_xrf.owl",
    "rubalkhali_dna.owl",
    "rubalkhali_sra.owl",
    "rubalkhali_qc.owl",
    "ncbitaxon_module.owl",
)

CORE_RDF_GENERATORS = (
    "generate_site_ontology.groovy",
    "generate_measurements_abox.groovy",
    "generate_samples_abox.groovy",
    "generate_xrf_abox.groovy",
    "generate_dna_abox.groovy",
    "generate_sra_abox.groovy",
    "generate_qc_abox.groovy",
    "update_rubalkhali_ontology.groovy",
)

CONTROL_DICTIONARY_ROOTS = (
    "metadata/controls",
    "metadata/samplesheets",
    "metadata/geodata",
    "metadata/samples/environmental_measurement_corrections.tsv",
    "metadata/sra-submissions",
    "metadata/climate/daily_weather_canonical.tsv",
    "metadata/climate/monthly_weather_averages_canonical.tsv",
    "metadata/environmental/environmental_measurements_curated.tsv",
    "evidence/controls/control_ground_truth.tsv",
    "evidence/control-audit",
    "evidence/control-sensitivity",
    "metadata/ph",
)

ECOLOGY_CANONICAL_DIRECTORIES = (
    ("analysis/v3/results", "results"),
    (
        "analysis/v3/spatial_turnover_rescue/results",
        "spatial_turnover_rescue/results",
    ),
    ("analysis/v3/geographic_prediction", "geographic_prediction"),
    ("analysis/v3/compartment_composition", "compartment_composition"),
    ("analysis/v3/depth_extraction", "depth_extraction"),
    ("analysis/v3/evenness_decomposition", "evenness_decomposition"),
    ("analysis/v3/xrf_community_clr", "xrf_community_clr"),
    (
        "analysis/v3/spatial_resolution_sensitivity",
        "spatial_resolution_sensitivity",
    ),
    ("analysis/v3/distance_decay_turnover", "distance_decay_turnover"),
    ("analysis/v3/environment_associations", "environment_associations"),
    ("analysis/v3/picrust2_ecology", "picrust2_ecology"),
    ("analysis/v3/rain_response_window", "rain_response_window"),
    ("analysis/v3/cross_desert_context", "cross_desert_context"),
)

CROSS_DESERT_INPUTS = (
    (
        "analysis/v2/RQ27_Transportability/atacama_gradient/atacama_per_site.csv",
        "metadata/comparators/atacama/gradient/atacama_per_site.csv",
    ),
    (
        "analysis/v2/RQ27_Transportability/atacama_pit/ASV_table.tsv",
        "metadata/comparators/atacama/pit/ASV_table.tsv",
    ),
    (
        "analysis/v2/RQ27_Transportability/atacama_pit/ASV_tax.silva_138_2.tsv",
        "metadata/comparators/atacama/pit/ASV_tax.silva_138_2.tsv",
    ),
    (
        "analysis/v2/RQ27_Transportability/atacama_pit/sample_depth_map.tsv",
        "metadata/comparators/atacama/pit/sample_depth_map.tsv",
    ),
)

PICRUST_ECOLOGY_INPUTS = (
    (
        "data/processed/functional/picrust2/merged/path_abun_unstrat.tsv",
        "metadata/functional/picrust2/merged/path_abun_unstrat.tsv",
    ),
    (
        "data/processed/functional/picrust2/merged/sample_metadata.tsv",
        "metadata/functional/picrust2/merged/sample_metadata.tsv",
    ),
    (
        "data/processed/functional/picrust2/merged/weighted_nsti.tsv",
        "metadata/functional/picrust2/merged/weighted_nsti.tsv",
    ),
    (
        "data/processed/functional/picrust2/path_abun_unstrat_descriptions.tsv",
        "metadata/functional/picrust2/path_abun_unstrat_descriptions.tsv",
    ),
)

ECOLOGY_CACHE_FILES = (
    "alpha.tsv",
    "genus_counts.tsv",
    "asv_filt_counts.tsv",
    "meta.json",
)

ENVIRONMENT_FILES = (
    ("workflow/environment.yml", "environment/environment.yml"),
    ("workflow/requirements.in", "environment/requirements.in"),
    ("workflow/requirements.lock.txt", "environment/requirements.lock.txt"),
)

WORKFLOW_FILES = (
    ".gitignore",
    "analysis_manifest.tsv",
    "main.nf",
    "nextflow.config",
    "README.md",
)

FIELD_DESCRIPTIONS = {
    "record_id": "Stable identifier for one author-confirmed control-design record.",
    "control_scope": "Trip, batch, assay or inventory scope to which the control statement applies.",
    "control_class": "Positive, negative, extraction-blank, PCR-blank, inventory-only or no-positive-control classification.",
    "workflow_stage": "Processing stage or stages in which the control participates.",
    "assay": "Molecular assay to which the record is applicable.",
    "status": "Evidence or curation status of the record.",
    "limitation": "Boundary that prevents broader interpretation or reuse.",
    "entity_id": "Deterministic project identifier for the normalized entity.",
    "entity_kind": "Material, role, process, batch, dataset, assertion or evidence category.",
    "canonical_key": "Canonical typed key used to mint the deterministic entity IRI.",
    "key_sha256": "SHA-256 digest of the canonical typed entity key.",
    "role_id": "Occurrence-specific control-role identifier.",
    "bearer_material_id": "Material entity that bears this occurrence-specific role.",
    "realized_in_process_id": "Laboratory process in which the role is realized.",
    "process_id": "Deterministic laboratory-process identifier.",
    "batch_id": "Laboratory processing batch containing this process; never a field trip.",
    "input_entity_id": "Material or data entity consumed by the process.",
    "output_entity_id": "Material or data entity produced by the process.",
    "taxon_iri": "NCBI Taxonomy IRI for an expected organism.",
    "expected_value": "Manufacturer-stated composition value retained in the normalized table; a genomic-DNA percentage is not an expected 16S read percentage.",
    "expected_unit_iri": "Unit IRI applying to expected_value in the normalized manufacturer-composition table.",
    "composition_basis": "Basis of the manufacturer composition, such as genomic-DNA percentage; it must be interpreted with expected_unit_iri.",
    "assertion_id": "Deterministic identifier of the reified metadata or expected-taxon assertion.",
    "assertion_status": "Controlled assertion state, including confirmed, provisional or unresolved.",
    "evidence_id": "Identifier of the evidence record supporting the row.",
    "disposition": "Controlled outcome for an uncertain or inapplicable metadata claim.",
    "profile_id": "Feature-table profile identifier.",
    "group_type": "Aggregation dimension for a control-removal summary.",
    "group_value": "Campaign or compartment value used for aggregation.",
    "biological_profile_count": "Number of compatible biological profiles in the aggregate.",
    "product_assignment_status": "Evidence boundary for a positive-labelled library/product mapping; the July mappings are provisional trip-design hypotheses.",
    "lane": "Three-digit sequencing-lane code parsed from the frozen FASTQ path.",
    "source_snapshot_id": "Repository-relative identifier of the source that contains the represented value.",
    "feature_id": "Amplicon sequence variant identifier.",
    "prevalence_score": "One-sided Fisher prevalence-enrichment probability used by the declared screen.",
    "candidate_contaminant_read_fraction": "Fraction of profile reads assigned to candidate contaminant ASVs.",
    "pooled_candidate_contaminant_read_fraction": "Candidate-contaminant reads divided by all reads across the aggregate.",
    "verdict_stable": "Whether the scientific verdict is identical before and after bounded filtering.",
    "ph_value": "Admitted or audited archived-soil pH reading under the declared CaCl2 protocol.",
    "ph_value_raw": "Verbatim content of the workbook pH-reading cell.",
    "ph10_check": "Recorded pH-10 buffer read-back for the measurement session.",
    "slope_percent": "Workbook-reported electrode slope percentage.",
    "measurement_date": "Accepted ISO 8601 measurement date; blank for a quarantined date.",
    "measurement_date_raw": "Verbatim date representation from the source workbook.",
    "ecology_eligible": "Whether the audited row is admitted to the ecology analysis.",
    "kg_eligible": "Whether the audited row is admitted to the pH knowledge-graph module.",
    "reason_codes": "Semicolon-delimited machine-readable reasons for the row disposition.",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def copy(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise FileNotFoundError(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def copy_directory_files(source: Path, destination: Path) -> None:
    """Copy a directory tree without carrying symlinks outside the package."""
    if not source.is_dir():
        raise FileNotFoundError(source)
    for path in sorted(item for item in source.rglob("*") if item.is_file()):
        if (
            "__pycache__" in path.parts
            or ".pytest_cache" in path.parts
            or path.suffix == ".pyc"
            or path.name == ".shex_classpath"
        ):
            continue
        copy(path, destination / path.relative_to(source))


def remove_staged_build_noise(stage: Path) -> None:
    """Remove transient caches left by local validation of the staged tree."""
    cache_directories = sorted(
        (
            path
            for path in stage.rglob("*")
            if path.is_dir() and path.name in {"__pycache__", ".pytest_cache"}
        ),
        key=lambda path: len(path.parts),
        reverse=True,
    )
    for directory in cache_directories:
        shutil.rmtree(directory)
    for path in stage.rglob("*"):
        if path.is_file() and (
            path.suffix == ".pyc" or path.name == ".shex_classpath"
        ):
            path.unlink()


def write_checksums(directory: Path) -> None:
    checksum_path = directory / "SHA256SUMS"
    files = sorted(
        path for path in directory.rglob("*")
        if path.is_file() and path != checksum_path
    )
    payload = "".join(
        f"{sha256(path)}  {path.relative_to(directory)}\n" for path in files
    )
    checksum_path.write_text(payload, encoding="utf-8")


def infer_data_type(values: list[str], field: str) -> str:
    populated = [value for value in values if value != ""]
    if not populated:
        return "string"
    lowered = {value.lower() for value in populated}
    if lowered <= {"true", "false"}:
        return "boolean"
    if all(re.fullmatch(r"-?\d+", value) for value in populated):
        return "integer"
    try:
        for value in populated:
            float(value)
        return "number"
    except ValueError:
        pass
    if field.endswith("_date") and all(
        re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) for value in populated
    ):
        return "date"
    return "string"


def field_unit(field: str) -> str:
    if field in {"ph_value", "ph_value_raw", "ph10_check"}:
        return "pH (UO:0000196 where represented in RDF)"
    if field == "slope_percent":
        return "percent"
    if field == "expected_value":
        return "specified by expected_unit_iri"
    if field.endswith("_fraction") or field.endswith("_prevalence"):
        return "proportion (0 to 1)"
    if "reads" in field:
        return "read count"
    if any(token in field for token in ("profiles", "features", "asvs")):
        return "count"
    if field.endswith("_date"):
        return "ISO 8601 calendar date"
    return "not applicable"


def augment_data_dictionary(stage: Path) -> None:
    dictionary = stage / "metadata/DATA_DICTIONARY.tsv"
    with dictionary.open(newline="", encoding="utf-8") as handle:
        existing = list(csv.DictReader(handle, delimiter="\t"))
    managed_prefixes = tuple(
        item.rstrip("/") + "/" if "." not in Path(item).name else item
        for item in CONTROL_DICTIONARY_ROOTS
    )
    rows = [
        row for row in existing
        if not any(
            row["path"] == prefix.rstrip("/") or row["path"].startswith(prefix)
            for prefix in managed_prefixes
        )
    ]

    sources: list[Path] = []
    for relative in CONTROL_DICTIONARY_ROOTS:
        path = stage / relative
        if path.is_file() and path.suffix == ".tsv":
            sources.append(path)
        elif path.is_dir():
            sources.extend(sorted(path.rglob("*.tsv")))
    for source in sorted(set(sources)):
        with source.open(newline="", encoding="utf-8") as handle:
            table = list(csv.DictReader(handle, delimiter="\t"))
        if not table:
            continue
        fields = [field for field in table[0] if isinstance(field, str)]
        for field in fields:
            values = [row.get(field, "") for row in table]
            rows.append(
                {
                    "path": str(source.relative_to(stage)),
                    "field_or_pattern": field,
                    "data_type": infer_data_type(values, field),
                    "unit": field_unit(field),
                    "missing_convention": (
                        "blank means unknown or not applicable as bounded by row status"
                        if any(value == "" for value in values)
                        else "never blank"
                    ),
                    "description": FIELD_DESCRIPTIONS.get(
                        field,
                        field.replace("_", " ").capitalize()
                        + " as defined by the file-specific audit method.",
                    ),
                }
            )
    rows.sort(key=lambda row: (row["path"], row["field_or_pattern"]))
    with dictionary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "path",
                "field_or_pattern",
                "data_type",
                "unit",
                "missing_convention",
                "description",
            ],
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


def stage_portable_commands(source: Path, destination: Path, root: Path) -> None:
    payload = source.read_text(encoding="utf-8")
    payload = payload.replace(str(root), "${PROJECT_ROOT}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        "# Repository-layout replay; set PROJECT_ROOT to the source checkout.\n"
        ': "${PROJECT_ROOT:?set PROJECT_ROOT to the source checkout}"\n'
        + payload,
        encoding="utf-8",
    )


def stage_package_replay_commands(destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'package_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)\n'
        'exec bash "$package_root/scripts/controls/'
        'replay_control_sensitivity_package.sh" "$@"\n',
        encoding="utf-8",
    )
    destination.chmod(0o755)


def stage_ncbitaxon_release_identity(root: Path, stage: Path) -> None:
    source = root / "data/ontologies/ncbitaxon.owl"
    with source.open(encoding="utf-8") as handle:
        header = handle.read(65_536)

    def required(pattern: str, field: str) -> str:
        match = re.search(pattern, header)
        if match is None:
            raise ValueError(f"NCBITaxon source omits {field}")
        return match.group(1)

    subset = stage / "ontology/ncbitaxon_module.owl"
    payload = {
        "schema_version": "1.0",
        "status": "source_release_identified",
        "source": {
            "repository_path": "data/ontologies/ncbitaxon.owl",
            "bytes": source.stat().st_size,
            "sha256": sha256(source),
            "ontology_iri": required(
                r'<owl:Ontology rdf:about="([^"]+)"',
                "ontology IRI",
            ),
            "version_iri": required(
                r'<owl:versionIRI rdf:resource="([^"]+)"',
                "version IRI",
            ),
            "version_info": required(
                r"<owl:versionInfo>([^<]+)</owl:versionInfo>",
                "versionInfo",
            ),
            "taxonomy_source_version": required(
                r"<rdfs:comment>NCBI organismal taxonomy version "
                r"([^<]+)</rdfs:comment>",
                "taxonomy source version",
            ),
            "retrieval_date": None,
            "retrieval_date_status": "not_recorded",
        },
        "derived_subset": {
            "package_path": "ontology/ncbitaxon_module.owl",
            "bytes": subset.stat().st_size,
            "sha256": sha256(subset),
        },
    }
    destination = stage / "ontology/ncbitaxon_release_identity.json"
    destination.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    stage = root / "data-paper/zenodo"
    remove_staged_build_noise(stage)

    copy(
        root / "data/metadata/samples/controls/control_ground_truth.tsv",
        stage / "evidence/controls/control_ground_truth.tsv",
    )

    normalized_source = root / "data/processed/metadata/controls"
    normalized_stage = stage / "metadata/controls"
    for source in sorted(normalized_source.iterdir()):
        if source.is_file():
            copy(source, normalized_stage / source.name)

    for suffix in ("ttl", "owl"):
        copy(
            root
            / f"data/processed/semantics/ontology/rubalkhali_controls.{suffix}",
            stage / f"ontology/rubalkhali_controls.{suffix}",
        )
        copy(
            root
            / f"data/processed/semantics/ontology/rubalkhali_ph_eq_ph_shared_v1_0_0.{suffix}",
            stage
            / f"ontology/rubalkhali_ph_eq_ph_shared_v1_0_0.{suffix}",
        )
    for name in CORE_ONTOLOGY_MODULES:
        copy(
            root / "data/processed/semantics/ontology" / name,
            stage / "ontology" / name,
        )
    stage_ncbitaxon_release_identity(root, stage)
    copy(root / "void.ttl", stage / "void.ttl")
    copy(root / "deploy_onto.sh", stage / "deploy_onto.sh")
    for source in sorted((root / "data/processed/semantics/shex").glob("*.shex")):
        copy(source, stage / "shex" / source.name)

    audit_source = root / "analysis/v3/control_audit"
    audit_stage = stage / "evidence/control-audit"
    for relative in AUDIT_FILES:
        copy(audit_source / relative, audit_stage / relative)

    sensitivity_source = root / "analysis/v3/control_sensitivity"
    sensitivity_stage = stage / "evidence/control-sensitivity"
    for name in (
        "headline_result_sensitivity.json",
        "headline_result_sensitivity.tsv",
    ):
        copy(sensitivity_source / name, sensitivity_stage / name)
    stage_portable_commands(
        sensitivity_source / "commands.sh",
        sensitivity_stage / "commands_repository.sh",
        root,
    )
    stage_package_replay_commands(sensitivity_stage / "commands.sh")

    for name in CONTROL_SCRIPTS:
        copy(root / "scripts/controls" / name, stage / "scripts/controls" / name)
    (stage / "scripts/controls/replay_control_sensitivity_package.sh").chmod(
        0o755
    )
    for name in ECOLOGY_SCRIPTS:
        copy(root / "analysis/v3" / name, stage / "scripts/analysis" / name)
    for source, destination in (
        (
            root / "analysis/v3/ph_ecology_analysis.py",
            stage / "scripts/analysis/ph_ecology_analysis.py",
        ),
        (
            root / "scripts/analysis/compare_ph_versions.py",
            stage / "scripts/analysis/compare_ph_versions.py",
        ),
        (
            root / "scripts/analysis/render_ph_ecology_tex.py",
            stage / "scripts/analysis/render_ph_ecology_tex.py",
        ),
        (
            root / "scripts/analysis/run_ph_shared_v1.sh",
            stage / "scripts/analysis/run_ph_shared_v1.sh",
        ),
    ):
        copy(source, destination)
    copy(
        root / "analysis/v3/primer_identity_audit.py",
        stage / "scripts/analysis/primer_identity_audit.py",
    )

    ecology_stage = stage / "evidence/ecology-canonical"
    for source_relative, destination_relative in ECOLOGY_CANONICAL_DIRECTORIES:
        copy_directory_files(
            root / source_relative,
            ecology_stage / destination_relative,
        )
    for name in ECOLOGY_CACHE_FILES:
        copy(
            root / "analysis/v2/review/cache" / name,
            ecology_stage / "cache" / name,
        )

    xrf_stage = stage / "evidence/xrf-community"
    for name in ("laboratory_xrf_axis.tsv", "elemental_pc1_loadings.tsv"):
        copy(
            root / "analysis/v3/xrf_community_rescue" / name,
            xrf_stage / name,
        )

    primer_stage = stage / "evidence/primer-identity"
    for name in ("README.md", "primer_counts.tsv", "source_paths.tsv"):
        copy(root / "analysis/v3/primer_identity_audit" / name, primer_stage / name)

    copy(
        root / "data/processed/climate/daily_weather_canonical.tsv",
        stage / "metadata/climate/daily_weather_canonical.tsv",
    )
    copy(
        root / "data/processed/climate/monthly_weather_averages_canonical.tsv",
        stage / "metadata/climate/monthly_weather_averages_canonical.tsv",
    )
    copy(
        root / "data/metadata/misc/boundary.kml",
        stage / "metadata/geodata/empty_quarter_boundary.kml",
    )
    copy(
        root / "data/processed/metadata/environmental_measurements_curated.tsv",
        stage / "metadata/environmental/environmental_measurements_curated.tsv",
    )
    for source_relative, destination_relative in PICRUST_ECOLOGY_INPUTS:
        copy(root / source_relative, stage / destination_relative)
    for source_relative, destination_relative in CROSS_DESERT_INPUTS:
        copy(root / source_relative, stage / destination_relative)
    copy_directory_files(
        root / "data/processed/amplicon",
        stage / "metadata/amplicon",
    )
    copy_directory_files(
        root / "data/metadata/protocols",
        stage / "metadata/protocols",
    )
    copy_directory_files(
        root / "data/metadata/samples/ph",
        stage / "metadata/samples/ph",
    )
    copy_directory_files(
        root / "analysis/v3/ph_shared_v1/normalized",
        stage / "metadata/ph",
    )
    ph_stage = stage / "evidence/ph"
    for name in (
        "summary.json",
        "input_output_manifest.tsv",
        "validation_report.json",
    ):
        copy(root / "analysis/v3/ph_shared_v1" / name, ph_stage / name)
    for name in (
        "shex_validation.log",
        "ph_validation.shexmap",
        "ph_negative_missing_unit.ttl",
        "ph_negative_missing_unit.shexmap",
        "ph_negative_missing_unit.log",
    ):
        copy(root / "analysis/v3/ph_shared_v1/kg" / name, ph_stage / name)
    copy_directory_files(
        root / "analysis/v3/ph_shared_v1/ecology",
        ph_stage / "ecology",
    )
    copy_directory_files(
        root / "analysis/v3/ph_shared_v1/version_comparison",
        ph_stage / "version_comparison",
    )
    predecessor_stage = ph_stage / "predecessor"
    copy(
        root / "analysis/v3/ph_ecology_v1/summary.json",
        predecessor_stage / "summary.json",
    )
    for directory in ("normalized", "kg", "ecology"):
        copy_directory_files(
            root / "analysis/v3/ph_ecology_v1" / directory,
            predecessor_stage / directory,
        )
    for source_relative, destination_relative in ENVIRONMENT_FILES:
        copy(root / source_relative, stage / destination_relative)
    for name in WORKFLOW_FILES:
        copy(root / "workflow" / name, stage / "workflow" / name)
    copy_directory_files(root / "workflow/bin", stage / "workflow/bin")
    copy_directory_files(root / "workflow/ibex", stage / "workflow/ibex")
    copy_directory_files(
        root / "workflow/.nextflow-bin", stage / "workflow/.nextflow-bin"
    )
    copy_directory_files(root / "workflow/tests", stage / "workflow/tests")
    for duplicate_environment_path in (
        "environment.yml",
        "requirements.in",
        "requirements.lock.txt",
    ):
        duplicate = stage / "workflow" / duplicate_environment_path
        if duplicate.exists():
            duplicate.unlink()
    copy(root / "pytest.ini", stage / "pytest.ini")
    copy(
        root / "scripts/rdf/generate_controls_abox.py",
        stage / "scripts/rdf/generate_controls_abox.py",
    )
    copy(
        root / "scripts/rdf/generate_ph_dataset.py",
        stage / "scripts/rdf/generate_ph_dataset.py",
    )
    copy(
        root / "scripts/release/bootstrap_package_layout.sh",
        stage / "scripts/release/bootstrap_package_layout.sh",
    )
    for name in CORE_RDF_GENERATORS:
        copy(root / "scripts/rdf" / name, stage / "scripts/rdf" / name)
    copy_directory_files(
        root / "scripts/validation",
        stage / "scripts/validation",
    )
    staged_shex_classpath = stage / "scripts/validation/.shex_classpath"
    if staged_shex_classpath.exists():
        staged_shex_classpath.unlink()
    for name in (
        "test_control_kg.py",
        "test_control_author_confirmation.py",
        "test_control_negative_invariants.py",
        "test_ph_shared.py",
    ):
        copy(root / "tests" / name, stage / "tests" / name)
    for name in CONTROL_VALIDATION_FIXTURES:
        copy(
            root / "tests/shex_negatives" / name,
            stage / "tests/shex_negatives" / name,
        )
    semantic_stage = stage / "evidence/semantic-validation"
    for obsolete_name in (
        "control_semantic_validation_20260730.json",
        "control_semantic_validation_20260730.log",
        "control_semantic_validation_20260731.json",
        "control_semantic_validation_20260731.log",
        "semantic_validation_20260729.json",
        "semantic_validation_20260729.log",
        "semantic_validation_20260731.json",
        "semantic_validation_20260731.log",
    ):
        obsolete = semantic_stage / obsolete_name
        if obsolete.exists():
            obsolete.unlink()
    for name in (
        "control_semantic_validation_20260801.json",
        "control_semantic_validation_20260801.log",
        "semantic_validation_20260801.json",
        "semantic_validation_20260801.log",
    ):
        copy(
            root / "revision/evidence" / name,
            semantic_stage / name,
        )

    copy(
        root / "revision/evidence/sample_visit_wiring_audit_20260801_rc25.json",
        semantic_stage / "sample_visit_wiring_audit_20260801_rc25.json",
    )
    core_regeneration_stage = stage / "evidence/core-kg-regeneration"
    copy_directory_files(
        root / "revision/evidence/core_kg_regeneration_20260801_rc25",
        core_regeneration_stage,
    )

    augment_data_dictionary(stage)

    for directory in (
        stage / "evidence/controls",
        normalized_stage,
        audit_stage,
        sensitivity_stage,
        ecology_stage,
        xrf_stage,
        primer_stage,
        ph_stage,
        stage / "evidence/semantic-validation",
        core_regeneration_stage,
    ):
        write_checksums(directory)

    print(
        "PASS: staged control and pH sources, normalized records, RDF, "
        "audit evidence, sensitivity summaries, and replay code"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
