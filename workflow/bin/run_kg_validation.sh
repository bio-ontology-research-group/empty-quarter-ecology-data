#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 5 ]]; then
  echo "usage: $0 PROJECT_ROOT OUTPUT_DIR CORE_KG_BUNDLE GENERATED_ABOX_BUNDLE CORRECTED_MAPPING_BUNDLE" >&2
  exit 64
fi

project_root=$1
output_dir=$2
core_kg_bundle=$(readlink -f "$3")
generated_abox_bundle=$(readlink -f "$4")
corrected_mapping_bundle=$(readlink -f "$5")
task_root=$PWD/kg-sandbox
output_dir_abs=$PWD/$output_dir
generated_abox=$generated_abox_bundle/rubalkhali_taxonomy_abox.ttl
abox_manifest=$generated_abox_bundle/taxonomy_abox_manifest.json
mapping_dir=$corrected_mapping_bundle/canonical
mapping_manifest=$mapping_dir/mapped_taxonomy_corrected.manifest.json
core_kg_manifest=$core_kg_bundle/core_kg_manifest.json

if ! command -v rapper >/dev/null 2>&1; then
  echo "Raptor rapper 2.0.16 is required for fail-closed Turtle validation" >&2
  exit 69
fi
rapper_version=$(rapper -v 2>&1 | head -1)
if [[ "$rapper_version" != "2.0.16" ]]; then
  echo "Raptor rapper 2.0.16 is required; found: $rapper_version" >&2
  exit 69
fi

for required in \
  "$core_kg_manifest" \
  "$core_kg_bundle/ontology_declaration_audit.json" \
  "$core_kg_bundle/input_manifest.tsv" \
  "$core_kg_bundle/SHA256SUMS" \
  "$core_kg_bundle/rubalkhali.owl" \
  "$core_kg_bundle/rubalkhali_sites.owl" \
  "$core_kg_bundle/rubalkhali_measurements.owl" \
  "$core_kg_bundle/rubalkhali_samples.owl" \
  "$core_kg_bundle/rubalkhali_xrf.owl" \
  "$core_kg_bundle/rubalkhali_dna.owl" \
  "$core_kg_bundle/rubalkhali_sra.owl" \
  "$core_kg_bundle/rubalkhali_qc.owl" \
  "$core_kg_bundle/rubalkhali_controls.owl" \
  "$core_kg_bundle/rubalkhali_controls.ttl" \
  "$core_kg_bundle/rubalkhali_ph_eq_ph_shared_v1_0_0.owl" \
  "$core_kg_bundle/rubalkhali_ph_eq_ph_shared_v1_0_0.ttl" \
  "$core_kg_bundle/control_metadata/control_entity_registry.tsv" \
  "$core_kg_bundle/control_metadata/control_aliases.tsv" \
  "$core_kg_bundle/control_metadata/control_roles.tsv" \
  "$core_kg_bundle/control_metadata/laboratory_processes.tsv" \
  "$core_kg_bundle/control_metadata/control_sequence_occurrences.tsv" \
  "$core_kg_bundle/control_metadata/control_composition.tsv" \
  "$core_kg_bundle/control_metadata/control_assertions.tsv" \
  "$core_kg_bundle/control_metadata/control_metadata_dispositions.tsv" \
  "$generated_abox" \
  "$abox_manifest" \
  "$generated_abox_bundle/SHA256SUMS" \
  "$mapping_manifest" \
  "$mapping_dir/mapped_taxonomy_corrected.json" \
  "$mapping_dir/mapped_taxonomy_corrected.tsv" \
  "$mapping_dir/ecosystem_module.owl" \
  "$mapping_dir/ecosystem_module.ttl" \
  "$corrected_mapping_bundle/SHA256SUMS"
do
  if [[ ! -s "$required" ]]; then
    echo "required generated taxonomy artifact is missing or empty: $required" >&2
    exit 66
  fi
done

project_taxonomy_abox=$(readlink -f \
  "$project_root/data/processed/ontology/rubalkhali_taxonomy_abox.ttl")
if [[ $(readlink -f "$generated_abox") == "$project_taxonomy_abox" ]]; then
  echo "refusing to validate the stale project taxonomy ABox" >&2
  exit 65
fi

(
  cd "$core_kg_bundle"
  sha256sum -c SHA256SUMS
)
(
  cd "$generated_abox_bundle"
  sha256sum -c SHA256SUMS
)
(
  cd "$corrected_mapping_bundle"
  sha256sum -c SHA256SUMS
)

python3 - "$core_kg_manifest" "$abox_manifest" "$mapping_manifest" <<'PY'
import json
import sys
from pathlib import Path

core = json.loads(Path(sys.argv[1]).read_text())
abox = json.loads(Path(sys.argv[2]).read_text())
mapping = json.loads(Path(sys.argv[3]).read_text())
if str(core.get("status", "")).lower() != "passed":
    raise SystemExit("core KG generation manifest is not passing")
if (
    core.get("ontology_declaration_audit", {}).get("status")
    != "passed"
):
    raise SystemExit("curated ontology declaration audit is not passing")
if str(abox.get("status", "")).lower() != "passed":
    raise SystemExit("taxonomy ABox generation manifest is not passing")
if str(mapping.get("status", "")).lower() != "passed":
    raise SystemExit("corrected taxonomy mapping manifest is not passing")
PY

mkdir -p \
  "$task_root/data/processed/semantics/ontology" \
  "$task_root/data/processed/metadata" \
  "$task_root/data/processed" \
  "$task_root/data/metadata" \
  "$output_dir_abs/logs" \
  "$output_dir_abs/input_manifests"
cp -a "$project_root/scripts" "$task_root/scripts"
cp -a "$project_root/tests" "$task_root/tests"
cp -a "$project_root/config" "$task_root/config"
cp -a "$project_root/docs" "$task_root/docs"

# Mirror the read-only semantics tree, but construct ontology/ explicitly so
# no stale taxonomy mapping, module, or ABox can enter this validation task.
for source in "$project_root/data/processed/semantics/"*; do
  name=$(basename "$source")
  if [[ "$name" != ontology ]]; then
    ln -s "$source" "$task_root/data/processed/semantics/$name"
  fi
done
for source in "$project_root/data/processed/semantics/ontology/"*; do
  name=$(basename "$source")
  case "$name" in
    rubalkhali.owl|rubalkhali_sites.owl|rubalkhali_measurements.owl|rubalkhali_samples.owl|rubalkhali_xrf.owl|rubalkhali_dna.owl|rubalkhali_sra.owl|rubalkhali_qc.owl|rubalkhali_controls.owl|rubalkhali_controls.ttl|rubalkhali_ph_eq_ph_shared_v1_0_0.owl|rubalkhali_ph_eq_ph_shared_v1_0_0.ttl|SHA256SUMS)
      continue
      ;;
    ecosystem_module.owl|ecosystem_module.ttl|mapped_taxonomy*.json|mapped_taxonomy*.tsv|rubalkhali_taxonomy_abox.*)
      continue
      ;;
    # These are outputs of the retired pre-audit mapper.  The generated
    # ecosystem module replaces both; loading either beside it reintroduces
    # stale project labels/parents and invalidates label-uniqueness checks.
    rubalkhali_taxonomy_rak.owl|ncbitaxon_module.owl|ncbitaxon_module.ttl)
      continue
      ;;
  esac
  ln -s "$source" "$task_root/data/processed/semantics/ontology/$name"
done
for generated_core_module in \
  rubalkhali.owl \
  rubalkhali_sites.owl \
  rubalkhali_measurements.owl \
  rubalkhali_samples.owl \
  rubalkhali_xrf.owl \
  rubalkhali_dna.owl \
  rubalkhali_sra.owl \
  rubalkhali_qc.owl \
  rubalkhali_controls.owl \
  rubalkhali_controls.ttl \
  rubalkhali_ph_eq_ph_shared_v1_0_0.owl \
  rubalkhali_ph_eq_ph_shared_v1_0_0.ttl
do
  ln -s "$core_kg_bundle/$generated_core_module" \
    "$task_root/data/processed/semantics/ontology/$generated_core_module"
done
for retired in \
  rubalkhali_taxonomy_rak.owl \
  ncbitaxon_module.owl \
  ncbitaxon_module.ttl
do
  retired_path=$task_root/data/processed/semantics/ontology/$retired
  if [[ -e "$retired_path" || -L "$retired_path" ]]; then
    echo "retired pre-audit taxonomy module entered KG sandbox: $retired" >&2
    exit 65
  fi
done

ln -s "$mapping_dir/ecosystem_module.owl" \
  "$task_root/data/processed/semantics/ontology/ecosystem_module.owl"
ln -s "$mapping_dir/ecosystem_module.ttl" \
  "$task_root/data/processed/semantics/ontology/ecosystem_module.ttl"
ln -s "$mapping_dir/mapped_taxonomy_corrected.json" \
  "$task_root/data/processed/semantics/ontology/mapped_taxonomy.json"
ln -s "$mapping_dir/mapped_taxonomy_corrected.tsv" \
  "$task_root/data/processed/semantics/ontology/mapped_taxonomy.tsv"
ln -s "$mapping_dir/mapped_taxonomy_corrected.json" \
  "$task_root/data/processed/semantics/ontology/mapped_taxonomy_corrected.json"
ln -s "$mapping_dir/mapped_taxonomy_corrected.tsv" \
  "$task_root/data/processed/semantics/ontology/mapped_taxonomy_corrected.tsv"
ln -s "$generated_abox" \
  "$task_root/data/processed/semantics/ontology/rubalkhali_taxonomy_abox.ttl"
ln -s semantics/ontology "$task_root/data/processed/ontology"
ln -s "$project_root/data/processed/geochemistry" \
  "$task_root/data/processed/geochemistry"
ln -s "$core_kg_bundle/control_metadata" \
  "$task_root/data/processed/metadata/controls"
ln -s "$project_root/analysis" "$task_root/analysis"
ln -s "$project_root/data/ontologies" "$task_root/data/ontologies"
ln -s "$project_root/data/metadata/samples" "$task_root/data/metadata/samples"
ln -s "$project_root/data/metadata/samplesheets" "$task_root/data/metadata/samplesheets"
ln -s "$project_root/data/metadata/sra-submissions" "$task_root/data/metadata/sra-submissions"

cd "$task_root"
python3 scripts/validation/check_iri_registry.py \
  > "$output_dir_abs/logs/iri_registry.log" 2>&1
python3 -m pytest -q \
  tests/test_iri_registry.py \
  tests/test_control_kg.py \
  tests/test_control_author_confirmation.py \
  tests/test_canonical_taxonomy_builder.py \
  tests/test_taxonomy_abox_generator.py \
  tests/test_taxonomy_abox_streaming.py \
  tests/test_taxonomy_mapping_audit.py \
  tests/test_xrf_data.py \
  > "$output_dir_abs/logs/pytest.log" 2>&1

python3 scripts/validation/validate_controls.py \
  --project-root "$task_root" \
  > "$output_dir_abs/logs/validate_controls.log" 2>&1

# This is the non-live, pre-inference validation suite: source-table/RDF XRF
# integrity, field-versus-laboratory semantics, a full streaming Turtle and
# project-invariant scan of the taxonomy ABox, ELK LITE consistency, ShEx spot
# checks for tractable modules, label uniqueness, and the IRI registry.
#
# The taxonomy report explicitly records that full ShEx is not run. This
# command is fail-closed: a missing input/parser, syntax error, short scan,
# triple-count mismatch, or structural violation terminates this stage.
python3 scripts/validation/validate_taxonomy_abox_streaming.py \
  --input data/processed/ontology/rubalkhali_taxonomy_abox.ttl \
  --output "$output_dir_abs/taxonomy_abox_streaming_validation.json" \
  > "$output_dir_abs/logs/taxonomy_abox_streaming_validation.log" 2>&1

VALIDATE_LIVE=0 bash scripts/validation/validate_original.sh \
  > "$output_dir_abs/logs/validate_original.log" 2>&1
cp validation_original_*.log \
  "$output_dir_abs/logs/validate_original_details.log"

python3 scripts/validation/validate_site_biome_completeness.py \
  --module data/processed/semantics/ontology/rubalkhali_sites.owl \
  --report "$output_dir_abs/site_biome_completeness.json" \
  > "$output_dir_abs/logs/site_biome_completeness.log" 2>&1

python3 "$project_root/scripts/manuscript/verify_manuscript_listings.py" \
  --paper-root "$project_root/data-paper" \
  --ontology-dir data/processed/semantics/ontology \
  --report "$output_dir_abs/manuscript_listing_verification.json" \
  > "$output_dir_abs/logs/manuscript_listing_verification.log" 2>&1

cp "$core_kg_manifest" \
  "$output_dir_abs/input_manifests/core_kg_manifest.json"
cp "$core_kg_bundle/ontology_declaration_audit.json" \
  "$output_dir_abs/input_manifests/ontology_declaration_audit.json"
cp "$core_kg_bundle/input_manifest.tsv" \
  "$output_dir_abs/input_manifests/core_kg_input_manifest.tsv"
cp "$core_kg_bundle/SHA256SUMS" \
  "$output_dir_abs/input_manifests/core_kg_SHA256SUMS"
cp "$abox_manifest" \
  "$output_dir_abs/input_manifests/taxonomy_abox_manifest.json"
cp "$mapping_manifest" \
  "$output_dir_abs/input_manifests/mapped_taxonomy_corrected.manifest.json"
cp "$generated_abox_bundle/SHA256SUMS" \
  "$output_dir_abs/input_manifests/taxonomy_abox_SHA256SUMS"
cp "$corrected_mapping_bundle/SHA256SUMS" \
  "$output_dir_abs/input_manifests/taxonomy_mapping_SHA256SUMS"

python3 - \
  "$output_dir_abs" \
  "$core_kg_manifest" \
  "$abox_manifest" \
  "$mapping_manifest" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

out = Path(sys.argv[1])
core_manifest = json.loads(Path(sys.argv[2]).read_text())
abox_manifest = json.loads(Path(sys.argv[3]).read_text())
mapping_manifest = json.loads(Path(sys.argv[4]).read_text())
taxonomy_report = json.loads(
    (out / "taxonomy_abox_streaming_validation.json").read_text()
)
if (
    taxonomy_report["input"]["sha256"]
    != abox_manifest["output"]["sha256"]
):
    raise SystemExit(
        "streaming validator did not inspect the generated manifest's ABox"
    )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


(out / "run_manifest.json").write_text(
    json.dumps(
        {
            "stage": "kg_validation",
            "status": "passed",
            "scope": [
                (
                    "fresh generation and byte-for-byte release regression "
                    "of tractable core RDF modules"
                ),
                "IRI registry and regression tests",
                "XRF source/RDF integrity",
                "field/laboratory XRF semantic separation",
                (
                    "full-file streaming Turtle syntax and project-specific "
                    "taxonomy-ABox structural invariants"
                ),
                "retired pre-audit taxonomy modules excluded",
                "ELK LITE consistency",
                "ShEx spot checks for tractable modules",
                "sampling-site biome and environmental-feature completeness",
                "manuscript listing and prose-IRI resolution",
                "label uniqueness",
            ],
            "core_kg_generation": {
                "manifest": "input_manifests/core_kg_manifest.json",
                "status": core_manifest["status"],
                "sha256": sha256(Path(sys.argv[2])),
                "generated_modules": core_manifest["scope"][
                    "generated_modules"
                ],
                "ontology_declaration_audit": core_manifest[
                    "ontology_declaration_audit"
                ],
            },
            "corrected_taxonomy_mapping": {
                "manifest": (
                    "input_manifests/"
                    "mapped_taxonomy_corrected.manifest.json"
                ),
                "status": mapping_manifest["status"],
                "sha256": sha256(Path(sys.argv[4])),
            },
            "taxonomy_abox_validation": {
                "report": "taxonomy_abox_streaming_validation.json",
                "status": taxonomy_report["status"],
                "source": (
                    "the ABox generated in the immediately upstream "
                    "Nextflow task"
                ),
                "generation_manifest": (
                    "input_manifests/taxonomy_abox_manifest.json"
                ),
                "input_sha256": taxonomy_report["input"]["sha256"],
                "input_bytes": taxonomy_report["input"]["bytes"],
                "triples": taxonomy_report["structural_scan"][
                    "triples_scanned"
                ],
                "turtle_syntax_scope": "entire input file",
                "structural_invariant_scope": (
                    "all generator P/dataset/Q/V records and links"
                ),
                "shex_status": taxonomy_report["coverage"]["shex"]["status"],
            },
        },
        indent=2,
        sort_keys=True,
    ) + "\n"
)
PY

(
  cd "$output_dir_abs"
  find . -type f ! -name SHA256SUMS -printf '%P\0' |
    sort -z |
    xargs -0 sha256sum > SHA256SUMS
  sha256sum -c SHA256SUMS
)
