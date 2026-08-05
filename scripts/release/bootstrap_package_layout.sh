#!/usr/bin/env bash
set -euo pipefail

package_root=${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}
package_root=$(cd "$package_root" && pwd)

link_path() {
  local destination=$1
  local target_abs=$2
  mkdir -p "$(dirname "$destination")"
  local parent_abs
  parent_abs=$(cd "$(dirname "$destination")" && pwd -P)
  local target
  target=$(realpath --relative-to="$parent_abs" "$target_abs")
  if [[ -L "$destination" ]]; then
    if [[ $(readlink "$destination") == "$target" ]]; then
      return
    fi
    echo "existing symlink has an unexpected target: $destination" >&2
    exit 73
  fi
  if [[ -e "$destination" ]]; then
    echo "refusing to replace existing path: $destination" >&2
    exit 73
  fi
  ln -s "$target" "$destination"
}

# Repository generators intentionally retain their source-tree paths. These
# relative links expose the staged package under that same read-only layout
# without duplicating or modifying any payload file.
link_path "$package_root/data/metadata" "$package_root/metadata"
link_path "$package_root/data/release" "$package_root/evidence/release"
link_path "$package_root/data/processed/ontology" "$package_root/ontology"
link_path \
  "$package_root/data/processed/semantics/ontology" \
  "$package_root/ontology"
link_path "$package_root/data/processed/semantics/shex" "$package_root/shex"
link_path \
  "$package_root/data/processed/climate" \
  "$package_root/metadata/climate"
link_path \
  "$package_root/data/processed/geochemistry" \
  "$package_root/metadata/geochemistry"
link_path \
  "$package_root/data/processed/functional" \
  "$package_root/metadata/functional"
link_path \
  "$package_root/data/processed/relic_dna" \
  "$package_root/metadata/relic-dna"
link_path \
  "$package_root/data/processed/taxonomy/taxon-tables" \
  "$package_root/metadata/taxonomy"
link_path \
  "$package_root/analysis/v2/review/cache" \
  "$package_root/evidence/ecology-canonical/cache"
link_path \
  "$package_root/analysis/v3/spatial_turnover_rescue" \
  "$package_root/evidence/ecology-canonical/spatial_turnover_rescue"
link_path \
  "$package_root/analysis/v3/xrf_community_rescue" \
  "$package_root/evidence/xrf-community"
link_path \
  "$package_root/analysis/v3/control_audit" \
  "$package_root/evidence/control-audit"
link_path \
  "$package_root/analysis/xrf_audit" \
  "$package_root/evidence/xrf_audit"

link_path \
  "$package_root/metadata/samples/controls" \
  "$package_root/evidence/controls"

# Re-expose the shared pH evidence using the repository paths consumed by its
# generator, analysis and regression tests. The links retain one canonical
# copy of each staged byte stream.
mkdir -p \
  "$package_root/analysis/v3/ph_shared_v1/kg" \
  "$package_root/config/ph"
link_path \
  "$package_root/analysis/v3/ph_shared_v1/normalized" \
  "$package_root/metadata/ph"
link_path \
  "$package_root/analysis/v3/ph_shared_v1/ecology" \
  "$package_root/evidence/ph/ecology"
link_path \
  "$package_root/analysis/v3/ph_shared_v1/version_comparison" \
  "$package_root/evidence/ph/version_comparison"
link_path \
  "$package_root/analysis/v3/ph_ecology_v1" \
  "$package_root/evidence/ph/predecessor"
for file in summary.json input_output_manifest.tsv validation_report.json; do
  link_path \
    "$package_root/analysis/v3/ph_shared_v1/$file" \
    "$package_root/evidence/ph/$file"
done
link_path \
  "$package_root/analysis/v3/ph_shared_v1/kg/rubalkhali_ph_measurements.ttl" \
  "$package_root/ontology/rubalkhali_ph_eq_ph_shared_v1_0_0.ttl"
link_path \
  "$package_root/analysis/v3/ph_shared_v1/kg/rubalkhali_ph_measurements.owl" \
  "$package_root/ontology/rubalkhali_ph_eq_ph_shared_v1_0_0.owl"
link_path \
  "$package_root/analysis/v3/ph_shared_v1/kg/ph_measurements.shex" \
  "$package_root/shex/ph_measurements.shex"
for file in \
  ph_validation.shexmap \
  ph_negative_missing_unit.ttl \
  ph_negative_missing_unit.shexmap \
  ph_negative_missing_unit.log \
  shex_validation.log
do
  link_path \
    "$package_root/analysis/v3/ph_shared_v1/kg/$file" \
    "$package_root/evidence/ph/$file"
done
link_path \
  "$package_root/config/ph/ph_measurements.shex" \
  "$package_root/shex/ph_measurements.shex"

# The package groups the frozen software environment under one top-level
# directory, whereas the staged Nextflow tests retain their repository paths.
# Restore those paths with relative links so the shipped workflow tests execute
# unchanged after extraction.
link_path \
  "$package_root/workflow/environment.yml" \
  "$package_root/environment/environment.yml"
link_path \
  "$package_root/workflow/requirements.in" \
  "$package_root/environment/requirements.in"
link_path \
  "$package_root/workflow/requirements.lock.txt" \
  "$package_root/environment/requirements.lock.txt"

mkdir -p "$package_root/data/processed/metadata"
link_path \
  "$package_root/data/processed/metadata/environmental_measurements_curated.tsv" \
  "$package_root/metadata/environmental/environmental_measurements_curated.tsv"
link_path \
  "$package_root/data/processed/metadata/environmental_measurements_audit.json" \
  "$package_root/evidence/environmental/environmental_measurements_audit.json"
link_path \
  "$package_root/data/processed/metadata/controls" \
  "$package_root/metadata/controls"

mkdir -p "$package_root/data/processed/figures"
link_path \
  "$package_root/data/processed/figures/transect_altitude.png" \
  "$package_root/paper/transect_altitude.png"

# Preserve the historical monorepo paths consumed by the provenance and paper
# build tasks. Each link points at one authoritative byte stream in this
# standalone repository; no manuscript or release payload is duplicated.
mkdir -p "$package_root/data-paper"
link_path \
  "$package_root/data-paper/scripts" \
  "$package_root/scripts/manuscript"
link_path \
  "$package_root/data-paper/zenodo" \
  "$package_root"
for file in \
  AUTHORITATIVE_MANUSCRIPT.md \
  sn-article.tex \
  01_introduction.tex \
  02_methods.tex \
  02_methods_taxonomy.tex \
  03_knowledge_representation.tex \
  04_data_records.tex \
  05_validation.tex \
  06_usage.tex \
  supplement.tex \
  kr_supplement.tex \
  env_table.tex \
  xrf_table.tex \
  sn-bibliography.bib \
  sn-jnl.cls \
  sn-mathphys-num.bst \
  transect_altitude.png
do
  link_path \
    "$package_root/data-paper/$file" \
    "$package_root/paper/$file"
done
link_path \
  "$package_root/paper/zenodo" \
  "$package_root"

mkdir -p "$package_root/data/metadata/obsolete"
link_path \
  "$package_root/data/metadata/obsolete/Trip_Metadata.xlsx" \
  "$package_root/evidence/environmental/Trip_Metadata.xlsx"

printf 'PASS: package compatibility layout created under %s\n' "$package_root"
