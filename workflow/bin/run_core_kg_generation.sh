#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: $0 PROJECT_ROOT OUTPUT_DIR" >&2
  exit 64
fi

project_root=$(readlink -f "$1")
output_dir_abs=$PWD/$2
task_root=$PWD/core-kg-sandbox
ontology_dir=$task_root/data/processed/ontology

mkdir -p \
  "$ontology_dir" \
  "$task_root/data/metadata" \
  "$task_root/data/release" \
  "$task_root/data/processed" \
  "$task_root/data/processed/semantics" \
  "$output_dir_abs/logs"
ln -s ../ontology "$task_root/data/processed/semantics/ontology"

# The generators use repository-relative paths.  Present only their declared
# read-only inputs in an isolated workspace and keep the output ontology
# directory local to this task, so a workflow run cannot rewrite the source
# checkout.
ln -s "$project_root/config" "$task_root/config"
ln -s "$project_root/data/metadata/geodata" \
  "$task_root/data/metadata/geodata"
ln -s "$project_root/data/metadata/QC_reads" \
  "$task_root/data/metadata/QC_reads"
ln -s "$project_root/data/metadata/samples" \
  "$task_root/data/metadata/samples"
ln -s "$project_root/data/metadata/samplesheets" \
  "$task_root/data/metadata/samplesheets"
ln -s "$project_root/data/metadata/sra-submissions" \
  "$task_root/data/metadata/sra-submissions"
# The canonical site module does not encode altitude. Its generator has an
# optional historical lookup at data/metadata/site_altitudes.tsv, a path that
# is absent from the release tree; do not invent that alias in the sandbox.
# The actual geodata/site_altitudes.tsv remains hashed below and supports the
# separately generated transect figure.
ln -s "$project_root/data/processed/climate" \
  "$task_root/data/processed/climate"
ln -s "$project_root/data/processed/geochemistry" \
  "$task_root/data/processed/geochemistry"
ln -s "$project_root/data/release/sample_ledger.tsv" \
  "$task_root/data/release/sample_ledger.tsv"

# rubalkhali.owl is the curated TBox/RBox input.  The workflow regenerates all
# source-derived tractable ABoxes from it; versioning the curated ontology
# itself remains an ontology-engineering release action rather than a data
# analysis step.
cp "$project_root/data/processed/ontology/rubalkhali.owl" \
  "$ontology_dir/rubalkhali.owl"

cd "$task_root"

groovy "$project_root/scripts/rdf/generate_site_ontology.groovy" \
  > "$output_dir_abs/logs/generate_sites.log" 2>&1
groovy "$project_root/scripts/rdf/generate_measurements_abox.groovy" \
  > "$output_dir_abs/logs/generate_measurements.log" 2>&1
groovy "$project_root/scripts/rdf/generate_samples_abox.groovy" \
  > "$output_dir_abs/logs/generate_samples.log" 2>&1
groovy "$project_root/scripts/rdf/generate_xrf_abox.groovy" \
  > "$output_dir_abs/logs/generate_xrf.log" 2>&1
groovy "$project_root/scripts/rdf/generate_dna_abox.groovy" \
  > "$output_dir_abs/logs/generate_dna.log" 2>&1
groovy "$project_root/scripts/rdf/generate_sra_abox.groovy" \
  > "$output_dir_abs/logs/generate_sra.log" 2>&1
JAVA_OPTS="${JAVA_OPTS:--Xms1g -Xmx16g}" \
  groovy "$project_root/scripts/rdf/generate_qc_abox.groovy" \
  > "$output_dir_abs/logs/generate_qc.log" 2>&1
python3 "$project_root/scripts/rdf/generate_controls_abox.py" \
  --project-root "$task_root" \
  > "$output_dir_abs/logs/generate_controls.log" 2>&1
python3 "$project_root/scripts/rdf/generate_ph_dataset.py" \
  --project-root "$task_root" \
  --workbook "$task_root/data/metadata/samples/ph/versions/EQ-PH-SHARED-v1.0.0/ph_measurements.xlsx" \
  --output-dir "$task_root/ph_shared_v1" \
  --as-of 2026-08-03 \
  --dataset-version EQ-PH-SHARED-v1.0.0 \
  --dataset-status FROZEN \
  --dataset-purpose shared-manuscripts \
  --measurement-campaign-closed \
  > "$output_dir_abs/logs/generate_ph.log" 2>&1
cp "$task_root/ph_shared_v1/kg/rubalkhali_ph_measurements.owl" \
  "$ontology_dir/rubalkhali_ph_eq_ph_shared_v1_0_0.owl"
cp "$task_root/ph_shared_v1/kg/rubalkhali_ph_measurements.ttl" \
  "$ontology_dir/rubalkhali_ph_eq_ph_shared_v1_0_0.ttl"

modules=(
  rubalkhali.owl
  rubalkhali_sites.owl
  rubalkhali_measurements.owl
  rubalkhali_samples.owl
  rubalkhali_xrf.owl
  rubalkhali_dna.owl
  rubalkhali_sra.owl
  rubalkhali_qc.owl
  rubalkhali_controls.owl
  rubalkhali_controls.ttl
  rubalkhali_ph_eq_ph_shared_v1_0_0.owl
  rubalkhali_ph_eq_ph_shared_v1_0_0.ttl
)

for module in "${modules[@]}"; do
  generated=$ontology_dir/$module
  canonical=$project_root/data/processed/ontology/$module
  if [[ ! -s "$generated" ]]; then
    echo "core KG generator omitted required module: $module" >&2
    exit 66
  fi
  if [[ ! -s "$canonical" ]]; then
    echo "staged canonical module is missing: $canonical" >&2
    exit 66
  fi
  if ! cmp "$generated" "$canonical"; then
    echo "freshly generated module differs from staged candidate: $module" >&2
    exit 65
  fi
  cp "$generated" "$output_dir_abs/$module"
done

mkdir -p "$output_dir_abs/control_metadata"
for generated in "$task_root/data/processed/metadata/controls/"*; do
  name=$(basename "$generated")
  canonical=$project_root/data/processed/metadata/controls/$name
  if [[ ! -s "$canonical" ]]; then
    echo "staged canonical control table is missing: $canonical" >&2
    exit 66
  fi
  if ! cmp "$generated" "$canonical"; then
    echo "freshly generated control table differs from staged candidate: $name" >&2
    exit 65
  fi
  cp "$generated" "$output_dir_abs/control_metadata/$name"
done

python3 - "$project_root" "$output_dir_abs" <<'PY'
import hashlib
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

root = Path(sys.argv[1])
out = Path(sys.argv[2])

generators = [
    "scripts/rdf/generate_site_ontology.groovy",
    "scripts/rdf/generate_measurements_abox.groovy",
    "scripts/rdf/generate_samples_abox.groovy",
    "scripts/rdf/generate_xrf_abox.groovy",
    "scripts/rdf/generate_dna_abox.groovy",
    "scripts/rdf/generate_sra_abox.groovy",
    "scripts/rdf/generate_qc_abox.groovy",
    "scripts/rdf/generate_controls_abox.py",
    "scripts/rdf/generate_ph_dataset.py",
]
input_roots = [
    "config/codes/biome_codes.yml",
    "config/codes/xrf_chemical_mapping.yml",
    "config/ph/ph_measurements.shex",
    "data/metadata/geodata",
    "data/metadata/QC_reads",
    "data/metadata/samples",
    "data/metadata/samplesheets",
    "data/metadata/sra-submissions",
    "data/processed/climate",
    "data/processed/geochemistry",
    "data/processed/ontology/rubalkhali.owl",
    "data/release/sample_ledger.tsv",
]
modules = [
    "rubalkhali.owl",
    "rubalkhali_sites.owl",
    "rubalkhali_measurements.owl",
    "rubalkhali_samples.owl",
    "rubalkhali_xrf.owl",
    "rubalkhali_dna.owl",
    "rubalkhali_sra.owl",
    "rubalkhali_qc.owl",
    "rubalkhali_controls.owl",
    "rubalkhali_controls.ttl",
    "rubalkhali_ph_eq_ph_shared_v1_0_0.owl",
    "rubalkhali_ph_eq_ph_shared_v1_0_0.ttl",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def expand(relative: str) -> list[Path]:
    path = root / relative
    if path.is_dir():
        return sorted(item for item in path.rglob("*") if item.is_file())
    return [path]


source_files: list[Path] = []
for item in generators + input_roots:
    source_files.extend(expand(item))
source_files = sorted(set(source_files))

with (out / "input_manifest.tsv").open("w", encoding="utf-8") as handle:
    handle.write("path\tbytes\tsha256\n")
    for path in source_files:
        if not path.is_file():
            raise SystemExit(f"declared core-KG input is missing: {path}")
        handle.write(
            f"{path.relative_to(root)}\t{path.stat().st_size}\t"
            f"{sha256(path)}\n"
        )

module_records = []
for name in modules:
    path = out / name
    module_records.append(
        {
            "file": name,
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
            "role": (
                "curated TBox/RBox input"
                if name == "rubalkhali.owl"
                else "freshly generated ABox"
            ),
        }
    )

owl_namespace = "{http://www.w3.org/2002/07/owl#}"
rdf_about = "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}about"
rak_prefix = "https://rubalkhali.science/kb/RAK_"
sio_prefix = "http://semanticscience.org/resource/SIO_"
pato_prefix = "http://purl.obolibrary.org/obo/PATO_"
ontology_root = ET.parse(out / "rubalkhali.owl").getroot()


def declarations(kind: str) -> set[str]:
    return {
        value
        for element in ontology_root.iter(f"{owl_namespace}{kind}")
        if (value := element.attrib.get(rdf_about))
    }


declaration_sets = {
    "classes": declarations("Class"),
    "object_properties": declarations("ObjectProperty"),
    "datatype_properties": declarations("DatatypeProperty"),
}
observed_declarations = {
    "classes": {
        "total": len(declaration_sets["classes"]),
        "project_local": sum(
            value.startswith(rak_prefix)
            for value in declaration_sets["classes"]
        ),
        "sio_referenced": sum(
            value.startswith(sio_prefix)
            for value in declaration_sets["classes"]
        ),
        "pato_referenced": sum(
            value.startswith(pato_prefix)
            for value in declaration_sets["classes"]
        ),
    },
    "object_properties": {
        "total": len(declaration_sets["object_properties"]),
        "project_local": sum(
            value.startswith(rak_prefix)
            for value in declaration_sets["object_properties"]
        ),
        "sio_referenced": sum(
            value.startswith(sio_prefix)
            for value in declaration_sets["object_properties"]
        ),
    },
    "datatype_properties": {
        "total": len(declaration_sets["datatype_properties"]),
        "project_local": sum(
            value.startswith(rak_prefix)
            for value in declaration_sets["datatype_properties"]
        ),
        "sio_referenced": sum(
            value.startswith(sio_prefix)
            for value in declaration_sets["datatype_properties"]
        ),
    },
}
expected_declarations = {
    "classes": {
        "total": 333,
        "project_local": 297,
        "sio_referenced": 32,
        "pato_referenced": 4,
    },
    "object_properties": {
        "total": 20,
        "project_local": 11,
        "sio_referenced": 9,
    },
    "datatype_properties": {
        "total": 35,
        "project_local": 34,
        "sio_referenced": 1,
    },
}
if observed_declarations != expected_declarations:
    raise SystemExit(
        "curated ontology declaration counts differ from the manuscript: "
        f"observed={observed_declarations!r}"
    )

ontology_audit_path = out / "ontology_declaration_audit.json"
ontology_audit_path.write_text(
    json.dumps(
        {
            "schema_version": "1.0",
            "status": "passed",
            "input": {
                "file": "rubalkhali.owl",
                "bytes": (out / "rubalkhali.owl").stat().st_size,
                "sha256": sha256(out / "rubalkhali.owl"),
            },
            "counting_rule": (
                "Distinct rdf:about IRIs on serialized owl:Class, "
                "owl:ObjectProperty, and owl:DatatypeProperty declarations "
                "in the curated base module; imported ontology contents are "
                "not counted."
            ),
            "declarations": observed_declarations,
            "expected_manuscript_values": expected_declarations,
        },
        indent=2,
        sort_keys=True,
    )
    + "\n",
    encoding="utf-8",
)

(out / "core_kg_manifest.json").write_text(
    json.dumps(
        {
            "schema_version": "1.0",
            "status": "passed",
            "scope": {
                "curated_input": "rubalkhali.owl",
                "generated_modules": [
                    item["file"]
                    for item in module_records
                    if item["role"] == "freshly generated ABox"
                ],
                "regression_gate": (
                    "Every freshly generated byte stream is identical to the "
                    "staged release candidate."
                ),
            },
            "modules": module_records,
            "input_manifest": "input_manifest.tsv",
            "ontology_declaration_audit": {
                "file": ontology_audit_path.name,
                "sha256": sha256(ontology_audit_path),
                "status": "passed",
            },
        },
        indent=2,
        sort_keys=True,
    )
    + "\n",
    encoding="utf-8",
)
PY

(
  cd "$output_dir_abs"
  find . -type f ! -name SHA256SUMS -printf '%P\0' |
    sort -z |
    xargs -0 sha256sum > SHA256SUMS
  sha256sum -c SHA256SUMS
)
