#!/bin/bash
#SBATCH -A k10018
#SBATCH -p workq
#SBATCH -N 1
#SBATCH --exclusive
#SBATCH -t 02:30:00
#SBATCH -J eq_mt_s2_arr
#SBATCH -o /scratch/project/k10018/eq-microtrait-20261110/logs/stage2_arr_%A_%a.out
#SBATCH -e /scratch/project/k10018/eq-microtrait-20261110/logs/stage2_arr_%A_%a.err
set -euo pipefail

export EQ_MICROTRAIT_ROOT="/scratch/project/k10018/eq-microtrait-20261110"
printf -v CHUNK_ID "%02d" "${SLURM_ARRAY_TASK_ID}"
export TMPDIR="${EQ_MICROTRAIT_ROOT}/tmp/stage2_${SLURM_ARRAY_JOB_ID:-local}_${CHUNK_ID}"
export TMP="$TMPDIR"
export TEMP="$TMPDIR"
mkdir -p "$TMPDIR"

export PATH="${EQ_MICROTRAIT_ROOT}/env/microtrait-r/bin:/project/k10018/sw/envs/gspa-tools/bin:$PATH"
PY="/project/k10018/sw/envs/mapping/bin/python"

cd "$EQ_MICROTRAIT_ROOT"
test -f results/SMOKE_OK
CHUNK_FILE="${EQ_MICROTRAIT_ROOT}/inputs/chunks/chunk_${CHUNK_ID}.txt"
test -s "$CHUNK_FILE"

"$PY" code/run_node_chunk.py \
  --root "$EQ_MICROTRAIT_ROOT" \
  --mag-list "$CHUNK_FILE" \
  --workers 32 \
  --hmm-threads 4 \
  --job-tag "chunk_${CHUNK_ID}"
touch "${EQ_MICROTRAIT_ROOT}/logs/chunk_${CHUNK_ID}.DONE"
