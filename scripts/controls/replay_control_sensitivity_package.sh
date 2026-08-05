#!/usr/bin/env bash
set -euo pipefail

package_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
output_root=${1:-"$PWD/control-sensitivity-replay"}
python_bin=${PYTHON:-python3}

if [[ -e "$output_root" ]]; then
  echo "refusing to overwrite existing output: $output_root" >&2
  exit 73
fi

mkdir -p "$output_root/logs"
output_root=$(cd "$output_root" && pwd)
work_root=$(mktemp -d "${TMPDIR:-/tmp}/eq-control-replay.XXXXXX")
cleanup() {
  rm -rf -- "$work_root"
}
trap cleanup EXIT

mkdir -p \
  "$work_root/data/metadata" \
  "$work_root/data/processed/climate" \
  "$work_root/data/release" \
  "$work_root/analysis/v3/control_audit/sensitivity_inputs"
ln -s "$package_root/metadata/geodata" "$work_root/data/metadata/geodata"
ln -s "$package_root/metadata/samplesheets" \
  "$work_root/data/metadata/samplesheets"
ln -s "$package_root/metadata/climate/daily_weather.tsv" \
  "$work_root/data/processed/climate/daily_weather.tsv"
ln -s "$package_root/evidence/release/sample_ledger.tsv" \
  "$work_root/data/release/sample_ledger.tsv"

input_root="$work_root/analysis/v3/control_audit/sensitivity_inputs"

run_step() {
  local name=$1
  shift
  printf '%q ' "$@" >> "$output_root/commands.executed.sh"
  printf '\n' >> "$output_root/commands.executed.sh"
  printf 'Running %s\n' "$name"
  "$@" >"$output_root/logs/${name}.log" 2>&1
}

: >"$output_root/commands.executed.sh"

run_step build_inputs \
  "$python_bin" \
  "$package_root/scripts/controls/build_control_sensitivity_inputs.py" \
  --filtered-table \
  "$package_root/evidence/control-audit/trip5_mapped_feature_table_control_filtered.tsv.gz" \
  --calls \
  "$package_root/evidence/control-audit/trip5_primary_contaminant_calls.tsv" \
  --removal \
  "$package_root/evidence/control-audit/trip5_removal_fraction_by_profile.tsv" \
  --taxonomy "$package_root/metadata/taxonomy/taxonomy-trips1-5.tsv" \
  --base-alpha "$package_root/evidence/ecology-canonical/cache/alpha.tsv" \
  --base-genus "$package_root/evidence/ecology-canonical/cache/genus_counts.tsv" \
  --base-asv \
  "$package_root/evidence/ecology-canonical/cache/asv_filt_counts.tsv" \
  --cache-meta "$package_root/evidence/ecology-canonical/cache/meta.json" \
  --output-dir "$input_root"

run_step claim_rescue \
  "$python_bin" "$package_root/scripts/analysis/claim_rescue.py" \
  --project-root "$work_root" \
  --alpha "$input_root/alpha.tsv" \
  --output-dir "$output_root/claim_rescue" \
  --skip-downstream

run_step evenness_decomposition \
  "$python_bin" \
  "$package_root/scripts/analysis/evenness_decomposition_analysis.py" \
  --alpha "$input_root/alpha.tsv" \
  --output-dir "$output_root/evenness_decomposition"

run_step depth_extraction \
  "$python_bin" \
  "$package_root/scripts/analysis/depth_extraction_sensitivity.py" \
  --project-root "$work_root" \
  --alpha "$input_root/alpha.tsv" \
  --sample-ledger "$package_root/evidence/release/sample_ledger.tsv" \
  --output-dir "$output_root/depth_extraction" \
  --bootstrap 5000 \
  --seed 20260725

run_step spatial_turnover \
  "$python_bin" \
  "$package_root/scripts/analysis/spatial_turnover_rescue.py" \
  --project-root "$work_root" \
  --counts "$input_root/genus_counts.tsv.gz" \
  --output-dir "$output_root/spatial_turnover" \
  --permutations 999

run_step compartment_composition \
  "$python_bin" \
  "$package_root/scripts/analysis/compartment_composition_rescue.py" \
  --project-root "$work_root" \
  --counts "$input_root/genus_counts.tsv.gz" \
  --output-dir "$output_root/compartment_composition" \
  --minimum-group-reads 2000 \
  --prevalence 0.20 \
  --permutations 999 \
  --bootstrap 2000 \
  --seed 20260725

run_step xrf_community_clr \
  "$python_bin" \
  "$package_root/scripts/analysis/xrf_community_clr_sensitivity.py" \
  --project-root "$work_root" \
  --counts "$input_root/genus_counts.tsv.gz" \
  --alpha "$input_root/alpha.tsv" \
  --elemental-axis \
  "$package_root/evidence/xrf-community/laboratory_xrf_axis.tsv" \
  --output-dir "$output_root/xrf_community_clr" \
  --minimum-group-reads 2000 \
  --prevalence 0.20 \
  --permutations 999 \
  --bootstrap 2000 \
  --seed 20260725

run_step geographic_prediction \
  "$python_bin" "$package_root/scripts/analysis/geographic_prediction.py" \
  --project-root "$work_root" \
  --counts "$input_root/genus_counts.tsv.gz" \
  --output-dir "$output_root/geographic_prediction" \
  --minimum-group-reads 2000 \
  --prevalence 0.20 \
  --pseudocount 0.5 \
  --taxon-count 200 \
  --site-permutations 499 \
  --seed 20260728

run_step spatial_resolution \
  "$python_bin" \
  "$package_root/scripts/analysis/spatial_resolution_sensitivity.py" \
  --project-root "$work_root" \
  --genus-counts "$input_root/genus_counts.tsv.gz" \
  --asv-counts "$input_root/asv_filt_counts.tsv.gz" \
  --output-dir "$output_root/spatial_resolution" \
  --minimum-group-reads 2000 \
  --prevalence 0.20 \
  --pseudocount 0.5 \
  --permutations 999 \
  --seed 20260728

run_step distance_decay_turnover \
  "$python_bin" \
  "$package_root/scripts/analysis/distance_decay_turnover.py" \
  --project-root "$work_root" \
  --counts "$input_root/genus_counts.tsv.gz" \
  --output-dir "$output_root/distance_decay_turnover" \
  --minimum-group-reads 2000 \
  --prevalence 0.20 \
  --pseudocount 0.5 \
  --taxon-count 200 \
  --permutations 9999 \
  --seed 20260728

run_step summarize_headline_results \
  "$python_bin" \
  "$package_root/scripts/controls/summarize_control_ecology_sensitivity.py" \
  --canonical-root "$package_root/evidence/ecology-canonical" \
  --sensitivity-root "$output_root" \
  --output-dir "$output_root"

"$python_bin" \
  "$package_root/scripts/controls/write_control_manifests.py" \
  "$output_root"
(
  cd "$output_root"
  sha256sum -c SHA256SUMS
)

printf 'PASS: package-only control sensitivity replay: %s\n' "$output_root"
