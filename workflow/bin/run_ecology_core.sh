#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 3 ]]; then
  echo "usage: $0 PROJECT_ROOT OUTPUT_DIR PMA_ASV_TABLE" >&2
  exit 64
fi

project_root=$1
output_dir=$2
pma_asv_table=$(realpath "$3")
task_root=$PWD/ecology-sandbox

mkdir -p "$task_root" "$output_dir/logs"
cp -a "$project_root/analysis" "$task_root/analysis"
mkdir -p \
  "$task_root/data/processed" \
  "$task_root/data/metadata" \
  "$task_root/data/release" \
  "$task_root/relic-dna"
ln -s "$project_root/data/processed/taxonomy" "$task_root/data/processed/taxonomy"
ln -s "$project_root/data/processed/geochemistry" "$task_root/data/processed/geochemistry"
ln -s "$project_root/data/processed/climate" "$task_root/data/processed/climate"
ln -s "$project_root/data/processed/relic_dna" "$task_root/data/processed/relic_dna"
ln -s "$project_root/data/processed/functional" "$task_root/data/processed/functional"
ln -s "$project_root/data/metadata/geodata" "$task_root/data/metadata/geodata"
ln -s "$project_root/data/metadata/samplesheets" \
  "$task_root/data/metadata/samplesheets"
ln -s "$project_root/data/release/sample_ledger.tsv" \
  "$task_root/data/release/sample_ledger.tsv"
ln -s "$pma_asv_table" "$task_root/relic-dna/ASV_table.tsv"

cd "$task_root"

# The sandbox is a copy of the repository, so every cache and output directory
# used by this stage is removed before the run. Otherwise a checked-in result
# could survive into the published checksum manifest without being regenerated.
rm -rf \
  analysis/v2/review/cache \
  analysis/v3/results \
  analysis/v3/pma_endpoint_results \
  analysis/v3/xrf_community_rescue \
  analysis/v3/spatial_turnover_rescue \
  analysis/v3/compartment_composition \
  analysis/v3/depth_extraction \
  analysis/v3/xrf_community_clr \
  analysis/v3/geographic_prediction \
  analysis/v3/spatial_resolution_sensitivity \
  analysis/v3/distance_decay_turnover \
  analysis/v3/evenness_decomposition

run_step() {
  local name=$1
  shift
  printf '%s\n' "$*" >> "$OLDPWD/$output_dir/commands.txt"
  "$@" > "$OLDPWD/$output_dir/logs/${name}.log" 2>&1
}

run_step build_cache python3 analysis/v2/review/build_cache.py
run_step build_asv_filter python3 analysis/v2/review/build_tree.py
printf '%s\n' \
  "mafft --retree 2 --maxiterate 0 --thread 8 --quiet analysis/v2/review/cache/asv_filt.fasta > analysis/v2/review/cache/asv_filt_aln.fasta" \
  >> "$OLDPWD/$output_dir/commands.txt"
mafft \
  --retree 2 \
  --maxiterate 0 \
  --thread 8 \
  --quiet \
  analysis/v2/review/cache/asv_filt.fasta \
  > analysis/v2/review/cache/asv_filt_aln.fasta \
  2> "$OLDPWD/$output_dir/logs/mafft.log"
printf '%s\n' \
  "FastTree -nt -gtr -quiet analysis/v2/review/cache/asv_filt_aln.fasta > analysis/v2/review/cache/asv_filt_tree.nwk" \
  >> "$OLDPWD/$output_dir/commands.txt"
FastTree \
  -nt \
  -gtr \
  -quiet \
  analysis/v2/review/cache/asv_filt_aln.fasta \
  > analysis/v2/review/cache/asv_filt_tree.nwk \
  2> "$OLDPWD/$output_dir/logs/fasttree.log"
run_step midpoint_root \
  python3 analysis/v3/midpoint_root_tree.py \
  --input analysis/v2/review/cache/asv_filt_tree.nwk \
  --output analysis/v2/review/cache/asv_filt_tree_rooted.nwk
run_step pma_endpoints python3 analysis/v3/pma_endpoint_analysis.py \
  --project-root "$task_root" \
  --output-dir analysis/v3/pma_endpoint_results
run_step xrf_community_rescue python3 analysis/v3/xrf_community_rescue.py \
  --project-root "$task_root" \
  --output-dir analysis/v3/xrf_community_rescue \
  --permutations 999
run_step spatial_turnover_rescue python3 analysis/v3/spatial_turnover_rescue.py \
  --project-root "$task_root" \
  --counts analysis/v2/review/cache/genus_counts.tsv \
  --output-dir analysis/v3/spatial_turnover_rescue/results \
  --permutations 999
run_step compartment_composition \
  python3 analysis/v3/compartment_composition_rescue.py \
  --project-root "$task_root" \
  --counts analysis/v2/review/cache/genus_counts.tsv \
  --output-dir analysis/v3/compartment_composition \
  --minimum-group-reads 2000 \
  --prevalence 0.20 \
  --permutations 999 \
  --bootstrap 2000 \
  --seed 20260725
run_step depth_extraction_sensitivity \
  python3 analysis/v3/depth_extraction_sensitivity.py \
  --project-root "$task_root" \
  --alpha analysis/v2/review/cache/alpha.tsv \
  --sample-ledger data/release/sample_ledger.tsv \
  --output-dir analysis/v3/depth_extraction \
  --bootstrap 5000 \
  --seed 20260725
run_step xrf_community_clr_sensitivity \
  python3 analysis/v3/xrf_community_clr_sensitivity.py \
  --project-root "$task_root" \
  --counts analysis/v2/review/cache/genus_counts.tsv \
  --alpha analysis/v2/review/cache/alpha.tsv \
  --elemental-axis \
  analysis/v3/xrf_community_rescue/laboratory_xrf_axis.tsv \
  --output-dir analysis/v3/xrf_community_clr \
  --minimum-group-reads 2000 \
  --prevalence 0.20 \
  --permutations 999 \
  --bootstrap 2000 \
  --seed 20260725
run_step geographic_prediction \
  python3 analysis/v3/geographic_prediction.py \
  --project-root "$task_root" \
  --counts analysis/v2/review/cache/genus_counts.tsv \
  --output-dir analysis/v3/geographic_prediction \
  --minimum-group-reads 2000 \
  --prevalence 0.20 \
  --pseudocount 0.5 \
  --taxon-count 200 \
  --site-permutations 499 \
  --seed 20260728
run_step spatial_resolution_sensitivity \
  python3 analysis/v3/spatial_resolution_sensitivity.py \
  --project-root "$task_root" \
  --output-dir analysis/v3/spatial_resolution_sensitivity \
  --minimum-group-reads 2000 \
  --prevalence 0.20 \
  --pseudocount 0.5 \
  --permutations 999 \
  --seed 20260728
run_step distance_decay_turnover \
  python3 analysis/v3/distance_decay_turnover.py \
  --project-root "$task_root" \
  --output-dir analysis/v3/distance_decay_turnover \
  --minimum-group-reads 2000 \
  --prevalence 0.20 \
  --pseudocount 0.5 \
  --taxon-count 200 \
  --permutations 9999 \
  --seed 20260728
run_step evenness_decomposition \
  python3 analysis/v3/evenness_decomposition_analysis.py \
  --alpha analysis/v2/review/cache/alpha.tsv \
  --output-dir analysis/v3/evenness_decomposition
run_step claim_rescue python3 analysis/v3/claim_rescue.py \
  --project-root "$task_root" \
  --alpha analysis/v2/review/cache/alpha.tsv \
  --output-dir analysis/v3/results \
  --skip-downstream

mkdir -p "$OLDPWD/$output_dir/cache"
cp \
  analysis/v2/review/cache/alpha.tsv \
  analysis/v2/review/cache/asv_filt.fasta \
  analysis/v2/review/cache/asv_filt_aln.fasta \
  analysis/v2/review/cache/asv_filt_counts.tsv \
  analysis/v2/review/cache/asv_filt_tree.nwk \
  analysis/v2/review/cache/asv_filt_tree_rooted.nwk \
  analysis/v2/review/cache/genus_counts.tsv \
  analysis/v2/review/cache/meta.json \
  "$OLDPWD/$output_dir/cache/"
cp -a analysis/v3/results "$OLDPWD/$output_dir/claim_rescue"
cp -a analysis/v3/pma_endpoint_results "$OLDPWD/$output_dir/pma_endpoints"
cp -a analysis/v3/xrf_community_rescue \
  "$OLDPWD/$output_dir/xrf_community_rescue"
cp -a analysis/v3/spatial_turnover_rescue \
  "$OLDPWD/$output_dir/spatial_turnover_rescue"
cp -a analysis/v3/compartment_composition \
  "$OLDPWD/$output_dir/compartment_composition"
cp -a analysis/v3/depth_extraction "$OLDPWD/$output_dir/depth_extraction"
cp -a analysis/v3/xrf_community_clr "$OLDPWD/$output_dir/xrf_community_clr"
cp -a analysis/v3/geographic_prediction \
  "$OLDPWD/$output_dir/geographic_prediction"
cp -a analysis/v3/spatial_resolution_sensitivity \
  "$OLDPWD/$output_dir/spatial_resolution_sensitivity"
cp -a analysis/v3/distance_decay_turnover \
  "$OLDPWD/$output_dir/distance_decay_turnover"
cp -a analysis/v3/evenness_decomposition \
  "$OLDPWD/$output_dir/evenness_decomposition"
cp -a "$project_root/analysis/v3/ph_shared_v1/ecology" \
  "$OLDPWD/$output_dir/ph_shared_v1"

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
    json.dumps({"stage": "ecology_core", "files": files}, indent=2) + "\n"
)
PY
