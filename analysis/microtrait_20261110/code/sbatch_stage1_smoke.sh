#!/bin/bash
#SBATCH -A k10018
#SBATCH -p workq
#SBATCH -N 1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=64
#SBATCH -t 01:00:00
#SBATCH -J eq_mt_s1_smoke
#SBATCH -o /scratch/project/k10018/eq-microtrait-20261110/logs/stage1_smoke_%j.out
#SBATCH -e /scratch/project/k10018/eq-microtrait-20261110/logs/stage1_smoke_%j.err
set -euo pipefail

export EQ_MICROTRAIT_ROOT="/scratch/project/k10018/eq-microtrait-20261110"
export TMPDIR="${EQ_MICROTRAIT_ROOT}/tmp/stage1_smoke_${SLURM_JOB_ID:-local}"
export TMP="$TMPDIR"
export TEMP="$TMPDIR"
mkdir -p "$TMPDIR"

export PATH="${EQ_MICROTRAIT_ROOT}/env/microtrait-r/bin:/project/k10018/sw/envs/gspa-tools/bin:$PATH"
PY="/project/k10018/sw/envs/mapping/bin/python"

cd "$EQ_MICROTRAIT_ROOT"
test -f inputs/STAGE0A_DONE
test -f inputs/STAGE0B_DONE
"$PY" code/run_node_chunk.py \
  --root "$EQ_MICROTRAIT_ROOT" \
  --mag-list "${EQ_MICROTRAIT_ROOT}/inputs/smoke_mags.txt" \
  --workers 6 \
  --hmm-threads 8 \
  --job-tag "smoke_${SLURM_JOB_ID:-local}" \
  --smoke-check
test -f results/SMOKE_OK
