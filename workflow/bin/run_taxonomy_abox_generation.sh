#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 9 ]]; then
  echo "usage: $0 GENERATOR MAPPING_JSON MAPPING_MANIFEST TAXONOMY_TSV FEATURE_TABLE SRA_SHEET SRA_ONTOLOGY IMPORT_MODULE OUTPUT_DIR" >&2
  exit 64
fi

generator=$1
mapping_json=$2
mapping_manifest=$3
taxonomy_tsv=$4
feature_table=$5
sra_sheet=$6
sra_ontology=$7
import_module=$8
output_dir=$9
workflow_wrapper=$(readlink -f "${BASH_SOURCE[0]}")

for input in \
  "$generator" \
  "$workflow_wrapper" \
  "$mapping_json" \
  "$mapping_manifest" \
  "$taxonomy_tsv" \
  "$feature_table" \
  "$sra_sheet" \
  "$sra_ontology" \
  "$import_module"
do
  if [[ ! -s "$input" ]]; then
    echo "required taxonomy-ABox input is missing or empty: $input" >&2
    exit 66
  fi
done

mkdir -p "$output_dir"
output_ttl="$output_dir/rubalkhali_taxonomy_abox.ttl"

# The generator streams Turtle subject blocks instead of retaining the full
# ABox in OWLAPI. Nextflow assigns 48 GB, leaving headroom around a 32-GB heap.
export JAVA_OPTS=${JAVA_OPTS:-"-Xms2g -Xmx32g"}

groovy "$generator" \
  --mapping-json "$mapping_json" \
  --mapping-manifest "$mapping_manifest" \
  --taxonomy-tsv "$taxonomy_tsv" \
  --feature-table "$feature_table" \
  --sra-sheet "$sra_sheet" \
  --sra-ontology "$sra_ontology" \
  --import-module "$import_module" \
  --import-iri "https://rubalkhali.science/kb/ecosystem_module.owl" \
  --output "$output_ttl"

if [[ ! -s "$output_ttl" ]]; then
  echo "taxonomy ABox generator returned success without a non-empty TTL" >&2
  exit 65
fi

python3 - \
  "$output_dir/taxonomy_abox_manifest.json" \
  "$generator" \
  "$workflow_wrapper" \
  "$mapping_json" \
  "$mapping_manifest" \
  "$taxonomy_tsv" \
  "$feature_table" \
  "$sra_sheet" \
  "$sra_ontology" \
  "$import_module" \
  "$output_ttl" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

(
    manifest_path,
    generator,
    workflow_wrapper,
    mapping_json,
    mapping_manifest,
    taxonomy_tsv,
    feature_table,
    sra_sheet,
    sra_ontology,
    import_module,
    output_ttl,
) = map(Path, sys.argv[1:])


def evidence(path: Path) -> dict[str, object]:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return {
        "file": path.name,
        "bytes": path.stat().st_size,
        "sha256": digest.hexdigest(),
    }


manifest = {
    "schema_version": 1,
    "status": "passed",
    "generator": evidence(generator),
    "workflow_wrapper": evidence(workflow_wrapper),
    "inputs": {
        "corrected_mapping_json": evidence(mapping_json),
        "corrected_mapping_manifest": evidence(mapping_manifest),
        "taxonomy_tsv": evidence(taxonomy_tsv),
        "feature_table": evidence(feature_table),
        "sra_sheet": evidence(sra_sheet),
        "sra_ontology": evidence(sra_ontology),
        "import_module": evidence(import_module),
    },
    "output": evidence(output_ttl),
    "scope": {
        "campaigns": "Trips 1-5",
        "mapping_policy": (
            "Only the fail-closed corrected mapping manifest is accepted; "
            "invalid or ambiguous external mappings use lineage-and-rank-"
            "scoped project identifiers."
        ),
        "validation": (
            "Generation and checksum gate only. Full-file Turtle syntax and "
            "project structural invariants are checked downstream against "
            "this exact output."
        ),
    },
}
manifest_path.write_text(
    json.dumps(manifest, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
PY

(
  cd "$output_dir"
  sha256sum \
    rubalkhali_taxonomy_abox.ttl \
    taxonomy_abox_manifest.json \
    > SHA256SUMS
  sha256sum -c SHA256SUMS
)
