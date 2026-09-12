#!/usr/bin/env bash
# Rebuild frozen KG source tables in a new output directory; never modify inputs.
set -euo pipefail
if [[ $# -lt 2 || $# -gt 3 ]]; then
  echo "usage: $0 SOURCE_ARCHIVE_DIRECTORY NEW_OUTPUT_DIRECTORY [--core-only]" >&2
  exit 64
fi
source_root=$(readlink -f "$1")
output_root=$(realpath -m "$2")
if [[ -e "$output_root" ]]; then
  echo "Refusing to overwrite output directory: $output_root" >&2
  exit 65
fi
mode=${3:---all}
[[ "$mode" == --all || "$mode" == --core-only ]] || exit 64
export JAVA_OPTS=${JAVA_OPTS:--Xms2g -Xmx32g}
mkdir -p "$output_root/data/processed/ontology" "$output_root/data/processed/semantics" "$output_root/logs"
ln -s "$source_root/config" "$output_root/config"
ln -s "$source_root/data/metadata" "$output_root/data/metadata"
ln -s "$source_root/data/release" "$output_root/data/release"
ln -s "$source_root/data/processed/climate" "$output_root/data/processed/climate"
ln -s "$source_root/data/processed/geochemistry" "$output_root/data/processed/geochemistry"
ln -s ../ontology "$output_root/data/processed/semantics/ontology"
python3 "$source_root/scripts/release/stamp_kg_release.py" \
  --input "$source_root/inputs/curated_rubalkhali_pre_release.owl" \
  --output "$output_root/data/processed/ontology/rubalkhali.owl" --version 3.0.0 \
  --released-at 2026-09-10T00:00:00Z --previous-version v2.0.6 \
  --manifest "$output_root/metadata_derivation.json"
cd "$output_root"
for component in site measurements samples xrf dna sra qc; do
  case "$component" in
    site) script=generate_site_ontology.groovy ;;
    *) script=generate_${component}_abox.groovy ;;
  esac
  groovy "$source_root/scripts/rdf/$script" > "$output_root/logs/$component.log" 2>&1
done
python3 "$source_root/scripts/rdf/generate_controls_abox.py" --project-root "$output_root" > logs/controls.log 2>&1
python3 "$source_root/scripts/rdf/generate_ph_dataset.py" \
  --project-root "$output_root" \
  --workbook "$source_root/data/metadata/samples/ph/versions/EQ-PH-SHARED-v1.0.1/ph_measurements.xlsx" \
  --output-dir "$output_root/ph_shared" --as-of 2026-08-03 \
  --dataset-version EQ-PH-SHARED-v1.0.1 --dataset-status FROZEN \
  --dataset-purpose shared-manuscripts --measurement-campaign-closed \
  --specimen-reconciliation "$source_root/data/metadata/samples/ph/versions/EQ-PH-SHARED-v1.0.1/trip4_specimen_reconciliation.tsv" > logs/ph.log 2>&1
cp ph_shared/kg/rubalkhali_ph_measurements.ttl data/processed/ontology/rubalkhali_ph_eq_ph_shared_v1_0_1.ttl
if [[ "$mode" == --all ]]; then
  python3 "$source_root/scripts/taxonomy/build_canonical_taxonomy.py" \
    --source-taxonomy "$source_root/data/metadata/taxonomy/taxonomy-trips1-5.tsv" \
    --feature-table "$source_root/data/metadata/taxonomy/feature-table-trips1-5.tsv" \
    --canonical-mapping "$source_root/inputs/mapped_taxonomy.tsv" \
    --ncbi-taxonomy "$source_root/data/ontologies/ncbitaxon.owl" \
    --output-dir "$output_root/taxonomy_mapping" --audit-dir "$output_root/taxonomy_audit" > logs/mapping.log 2>&1
  bash "$source_root/workflow/bin/run_taxonomy_abox_generation.sh" \
    "$source_root/scripts/rdf/generate_taxonomy_abox.groovy" \
    "$output_root/taxonomy_mapping/mapped_taxonomy_corrected.json" \
    "$output_root/taxonomy_mapping/mapped_taxonomy_corrected.manifest.json" \
    "$source_root/data/metadata/taxonomy/taxonomy-trips1-5.tsv" \
    "$source_root/data/metadata/taxonomy/feature-table-trips1-5.tsv" \
    "$source_root/data/metadata/sra-submissions/submission-sheet.tsv" \
    "$output_root/data/processed/ontology/rubalkhali_sra.owl" \
    "$output_root/taxonomy_mapping/ecosystem_module.owl" "$output_root/taxonomy_abox" > logs/taxonomy.log 2>&1
  ln "$output_root/taxonomy_abox/rubalkhali_taxonomy_abox.ttl" data/processed/ontology/rubalkhali_taxonomy_abox.ttl
  cp taxonomy_mapping/ecosystem_module.ttl data/processed/ontology/ecosystem_module.ttl
fi
for reference in sio envo pato uo; do
  cp "$source_root/data/ontologies/$reference.owl" data/processed/ontology/
done
python3 - "$source_root" "$output_root" "$mode" <<'PY'
import hashlib, json, sys
from pathlib import Path
source, out = map(Path, sys.argv[1:3])
mode = sys.argv[3]
records = json.loads((source / "expected/fresh_modules_manifest.json").read_text())["records"]
checks = []
for record in records:
    name = record["file"]
    if mode == "--core-only" and name in ("ecosystem_module.ttl", "rubalkhali_taxonomy_abox.ttl"):
        continue
    path = out / "data/processed/ontology" / name
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1048576), b""):
            h.update(block)
    actual = h.hexdigest()
    checks.append(dict(file=name, sha256=actual, expected_sha256=record["sha256"], passed=actual == record["sha256"]))
(out / "rebuild_verification.json").write_text(json.dumps(dict(mode=mode, checks=checks, passed=all(c["passed"] for c in checks)), indent=2) + "\n")
if not all(c["passed"] for c in checks):
    raise SystemExit("Regenerated module hash mismatch")
print(f"PASS: {len(checks)} regenerated/pinned module hashes")
PY
