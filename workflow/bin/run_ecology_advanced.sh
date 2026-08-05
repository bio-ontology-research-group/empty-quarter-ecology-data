#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 4 ]]; then
  echo "usage: $0 PROJECT_ROOT CORE_RESULTS MEASURED_FUNCTION_INPUTS OUTPUT_DIR" >&2
  exit 64
fi

project_root=$1
core_results=$(realpath "$2")
measured_function_inputs=$(realpath "$3")
output_dir=$4
task_root=$PWD/advanced-sandbox

mkdir -p "$task_root" "$output_dir/logs"
mkdir -p \
  "$task_root/analysis/v2/RQ26_CausalIdentification/scripts" \
  "$task_root/analysis/v2/review/cache" \
  "$task_root/analysis/v3" \
  "$task_root/data/processed" \
  "$task_root/data/metadata"
cp "$project_root/analysis/v2/common.py" "$task_root/analysis/v2/"
cp "$project_root/analysis/v2/review/corrected.py" \
  "$task_root/analysis/v2/review/"
cp "$project_root/analysis/v2/RQ26_CausalIdentification/scripts/phylo_signal_test.py" \
  "$task_root/analysis/v2/RQ26_CausalIdentification/scripts/"
cp "$project_root/analysis/v3/measured_function_summary.py" \
  "$task_root/analysis/v3/"
cp \
  "$core_results/cache/asv_filt_counts.tsv" \
  "$core_results/cache/asv_filt_tree_rooted.nwk" \
  "$task_root/analysis/v2/review/cache/"
tar -xzf "$measured_function_inputs" -C "$task_root"
for required in \
  "$task_root/analysis/v2/review/measured_function/measured_ko_by_sample.tsv.gz" \
  "$task_root/analysis/v2/review/measured_function/measured_marker_by_sample.tsv" \
  "$task_root/analysis/v2/review/measured_function/genome_cfix_taxonomy.tsv" \
  "$task_root/analysis/v2/review/measured_function/filtered_genomes.tsv" \
  "$task_root/data/processed/functional/picrust2/merged/ko_metagenome_unstrat.tsv" \
  "$task_root/data/processed/functional/picrust2/merged/sample_metadata.tsv"
do
  if [[ ! -s "$required" ]]; then
    echo "measured-function archive is missing: $required" >&2
    exit 66
  fi
done
ln -s "$project_root/data/metadata/geodata" "$task_root/data/metadata/geodata"

cd "$task_root"

run_step() {
  local name=$1
  shift
  printf '%s\n' "$*" >> "$OLDPWD/$output_dir/commands.txt"
  "$@" > "$OLDPWD/$output_dir/logs/${name}.log" 2>&1
}

run_step phylo_signal \
  python3 analysis/v2/RQ26_CausalIdentification/scripts/phylo_signal_test.py \
  --elemental-axis \
  "$core_results/xrf_community_rescue/laboratory_xrf_axis.tsv" \
  --output-dir analysis/v3/phylo_signal \
  --permutations 999 \
  --seed 20260723
run_step measured_function_summary \
  python3 analysis/v3/measured_function_summary.py \
  --project-root "$task_root" \
  --output-dir analysis/v3/measured_function_summary

cp -a analysis/v3/phylo_signal "$OLDPWD/$output_dir/"
cp -a analysis/v3/measured_function_summary "$OLDPWD/$output_dir/"

python3 - "$OLDPWD/$output_dir" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

out = Path(sys.argv[1])
files = []
for path in sorted(p for p in out.rglob("*") if p.is_file()):
    files.append({
        "path": str(path.relative_to(out)),
        "bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    })
(out / "run_manifest.json").write_text(
    json.dumps({"stage": "ecology_advanced", "files": files}, indent=2) + "\n"
)
PY
