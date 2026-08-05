#!/usr/bin/env bash
set -euo pipefail

project_root=${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}
output_root=${2:-"$project_root/analysis/v3/control_sensitivity"}
python_bin=${PYTHON:-python3}
input_root="$project_root/analysis/v3/control_audit/sensitivity_inputs"

mkdir -p "$output_root/logs"

run_step() {
  local name=$1
  shift
  printf '%q ' "$@" >> "$output_root/commands.executed.sh"
  printf '\n' >> "$output_root/commands.executed.sh"
  printf 'Running %s\n' "$name"
  "$@" > "$output_root/logs/${name}.log" 2>&1
}

: > "$output_root/commands.executed.sh"

run_step build_inputs \
  "$python_bin" "$project_root/scripts/controls/build_control_sensitivity_inputs.py"

run_step claim_rescue \
  "$python_bin" "$project_root/analysis/v3/claim_rescue.py" \
  --project-root "$project_root" \
  --alpha "$input_root/alpha.tsv" \
  --output-dir "$output_root/claim_rescue" \
  --skip-downstream

run_step evenness_decomposition \
  "$python_bin" "$project_root/analysis/v3/evenness_decomposition_analysis.py" \
  --alpha "$input_root/alpha.tsv" \
  --output-dir "$output_root/evenness_decomposition"

run_step depth_extraction \
  "$python_bin" "$project_root/analysis/v3/depth_extraction_sensitivity.py" \
  --project-root "$project_root" \
  --alpha "$input_root/alpha.tsv" \
  --sample-ledger "$project_root/data/release/sample_ledger.tsv" \
  --output-dir "$output_root/depth_extraction" \
  --bootstrap 5000 \
  --seed 20260725

run_step spatial_turnover \
  "$python_bin" "$project_root/analysis/v3/spatial_turnover_rescue.py" \
  --project-root "$project_root" \
  --counts "$input_root/genus_counts.tsv.gz" \
  --output-dir "$output_root/spatial_turnover" \
  --permutations 999

run_step compartment_composition \
  "$python_bin" "$project_root/analysis/v3/compartment_composition_rescue.py" \
  --project-root "$project_root" \
  --counts "$input_root/genus_counts.tsv.gz" \
  --output-dir "$output_root/compartment_composition" \
  --minimum-group-reads 2000 \
  --prevalence 0.20 \
  --permutations 999 \
  --bootstrap 2000 \
  --seed 20260725

run_step xrf_community_clr \
  "$python_bin" "$project_root/analysis/v3/xrf_community_clr_sensitivity.py" \
  --project-root "$project_root" \
  --counts "$input_root/genus_counts.tsv.gz" \
  --alpha "$input_root/alpha.tsv" \
  --elemental-axis \
  "$project_root/analysis/v3/xrf_community_rescue/laboratory_xrf_axis.tsv" \
  --output-dir "$output_root/xrf_community_clr" \
  --minimum-group-reads 2000 \
  --prevalence 0.20 \
  --permutations 999 \
  --bootstrap 2000 \
  --seed 20260725

run_step geographic_prediction \
  "$python_bin" "$project_root/analysis/v3/geographic_prediction.py" \
  --project-root "$project_root" \
  --counts "$input_root/genus_counts.tsv.gz" \
  --output-dir "$output_root/geographic_prediction" \
  --minimum-group-reads 2000 \
  --prevalence 0.20 \
  --pseudocount 0.5 \
  --taxon-count 200 \
  --site-permutations 499 \
  --seed 20260728

run_step spatial_resolution \
  "$python_bin" "$project_root/analysis/v3/spatial_resolution_sensitivity.py" \
  --project-root "$project_root" \
  --genus-counts "$input_root/genus_counts.tsv.gz" \
  --asv-counts "$input_root/asv_filt_counts.tsv.gz" \
  --output-dir "$output_root/spatial_resolution" \
  --minimum-group-reads 2000 \
  --prevalence 0.20 \
  --pseudocount 0.5 \
  --permutations 999 \
  --seed 20260728

run_step distance_decay_turnover \
  "$python_bin" "$project_root/analysis/v3/distance_decay_turnover.py" \
  --project-root "$project_root" \
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
  "$project_root/scripts/controls/summarize_control_ecology_sensitivity.py" \
  --canonical-root "$project_root/analysis/v3" \
  --sensitivity-root "$output_root" \
  --output-dir "$output_root"

python3 - "$output_root" "$project_root" "$python_bin" <<'PY'
import sys
from pathlib import Path

output = Path(sys.argv[1])
project_root = sys.argv[2]
python_bin = sys.argv[3]
commands = (output / "commands.executed.sh").read_text(encoding="utf-8")
commands = commands.replace(project_root, "${PROJECT_ROOT}")
commands = commands.replace(python_bin, "${PYTHON:-python3}")
(output / "commands.sh").write_text(
    "#!/usr/bin/env bash\n"
    "set -euo pipefail\n"
    ': "${PROJECT_ROOT:?set PROJECT_ROOT to the extracted project root}"\n'
    + commands,
    encoding="utf-8",
)
PY

"$python_bin" "$project_root/scripts/controls/write_control_manifests.py" \
  "$output_root"

printf 'Control-adjusted ecology sensitivity completed: %s\n' "$output_root"
