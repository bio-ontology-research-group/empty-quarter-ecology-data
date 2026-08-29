#!/usr/bin/env bash
#SBATCH --account=c2014
#SBATCH --partition=batch
#SBATCH --job-name=eq-function-null
#SBATCH --time=24:00:00
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G

set -euo pipefail

: "${EQ_FUNCTION_SCRIPT:?Set EQ_FUNCTION_SCRIPT to functional_redundancy_null.py}"
: "${EQ_FUNCTION_OUTPUT:?Set EQ_FUNCTION_OUTPUT to a new output directory}"

coverm_dir=${EQ_COVERM_DIR:-/ibex/scratch/projects/c2014/EmptyQuarter_Data/soil/eq_regen/coverm}
eggnog_annotations=${EQ_EGGNOG_ANNOTATIONS:-/ibex/scratch/projects/c2014/EmptyQuarter_Data/soil/eq_regen/eggnog/eq.emapper.annotations}
permutations=${EQ_FUNCTION_PERMUTATIONS:-999}
max_kos=${EQ_FUNCTION_MAX_KOS:-2000}
uv_bin=${EQ_UV_BIN:-/home/hohndor/.local/bin/uv}

test -f "$EQ_FUNCTION_SCRIPT"
test -d "$coverm_dir"
test -f "$eggnog_annotations"
test ! -e "$EQ_FUNCTION_OUTPUT"

export OMP_NUM_THREADS=${SLURM_CPUS_PER_TASK:-16}
export OPENBLAS_NUM_THREADS=${SLURM_CPUS_PER_TASK:-16}
export MKL_NUM_THREADS=${SLURM_CPUS_PER_TASK:-16}

"$uv_bin" run \
  --python 3.11 \
  --with 'numpy==2.1.*' \
  --with 'scipy==1.14.*' \
  python "$EQ_FUNCTION_SCRIPT" \
  --coverm-dir "$coverm_dir" \
  --eggnog-annotations "$eggnog_annotations" \
  --output-dir "$EQ_FUNCTION_OUTPUT" \
  --permutations "$permutations" \
  --max-kos "$max_kos"

(
  cd "$EQ_FUNCTION_OUTPUT"
  find . -maxdepth 1 -type f ! -name SHA256SUMS -printf '%P\0' |
    sort -z |
    xargs -0 sha256sum > SHA256SUMS
)
