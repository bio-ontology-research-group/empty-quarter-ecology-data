#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "$0")/../.." && pwd)"
python_bin="${PH_PYTHON:-$project_root/.venv/bin/python}"
dataset_version="EQ-PH-SHARED-v1.0.0"
analysis_version="ph-shared-v1.1.0"
source_path="$project_root/data/metadata/samples/ph/versions/$dataset_version/ph_measurements.xlsx"
output_dir="${PH_OUTPUT_DIR:-$project_root/analysis/v3/ph_shared_v1}"
paper_dir="$project_root/empty-quarter-amplicon"
expected_sha256="701db2a771b257da09bb276c8ca29df4408ba5986bd515821ccea275a8c692c1"
module_stem="rubalkhali_ph_eq_ph_shared_v1_0_0"

if [[ ! -x "$python_bin" ]]; then
  echo "Python environment is not executable: $python_bin" >&2
  exit 1
fi

actual_sha256="$(sha256sum "$source_path" | cut -d ' ' -f 1)"
if [[ "$actual_sha256" != "$expected_sha256" ]]; then
  echo "Frozen pH source hash mismatch: $actual_sha256" >&2
  exit 1
fi

mkdir -p "$output_dir/kg"
cp "$project_root/config/ph/ph_measurements.shex" \
  "$output_dir/kg/ph_measurements.shex"

"$python_bin" "$project_root/scripts/rdf/generate_ph_dataset.py" \
  --workbook "$source_path" \
  --project-root "$project_root" \
  --output-dir "$output_dir" \
  --as-of 2026-08-03 \
  --dataset-version "$dataset_version" \
  --dataset-status FROZEN \
  --dataset-purpose shared-manuscripts \
  --measurement-campaign-closed

"$python_bin" "$project_root/scripts/analysis/ph_ecology_analysis.py" \
  --project-root "$project_root" \
  --ph-dir "$output_dir" \
  --dataset-version "$dataset_version" \
  --analysis-version "$analysis_version" \
  --permutations 999 \
  --minimum-group-reads 2000

"$python_bin" "$project_root/scripts/analysis/compare_ph_versions.py" \
  --ecology-dir "$project_root/analysis/v3/ph_ecology_v1" \
  --successor-dir "$output_dir" \
  --output-dir "$output_dir/version_comparison"

if [[ -n "${PH_TEX_OUTPUT:-}" ]]; then
  tex_output="$PH_TEX_OUTPUT"
elif [[ -d "$paper_dir" ]]; then
  tex_output="$paper_dir/generated/ph_shared_v1_values.tex"
else
  tex_output="$output_dir/generated/ph_shared_v1_values.tex"
fi

"$python_bin" "$project_root/scripts/analysis/render_ph_ecology_tex.py" \
  --ph-dir "$output_dir" \
  --expected-dataset-version "$dataset_version" \
  --output "$tex_output"

for suffix in ttl owl; do
  generated="$output_dir/kg/rubalkhali_ph_measurements.$suffix"
  canonical="$project_root/data/processed/semantics/ontology/$module_stem.$suffix"
  if [[ ! -s "$canonical" ]]; then
    echo "Canonical pH module is missing: $canonical" >&2
    exit 1
  fi
  if ! cmp "$generated" "$canonical"; then
    echo "Generated pH module differs from canonical $suffix module" >&2
    exit 1
  fi
done

"$python_bin" "$project_root/scripts/validation/validate_ph_ecology.py" \
  --project-root "$project_root" \
  --ph-dir "$output_dir" \
  --expected-dataset-version "$dataset_version"

if [[ "${PH_SKIP_TESTS:-0}" != "1" ]]; then
  "$python_bin" -m pytest -q \
    "$project_root/tests/test_ph_shared.py" \
    "$project_root/tests/test_ph_ecology.py"
fi
