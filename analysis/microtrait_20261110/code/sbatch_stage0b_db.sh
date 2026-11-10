#!/bin/bash
#SBATCH -A k10018
#SBATCH -p workq
#SBATCH -N 1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH -t 00:30:00
#SBATCH -J eq_mt_s0b_db
#SBATCH -o /scratch/project/k10018/eq-microtrait-20261110/logs/stage0b_db_%j.out
#SBATCH -e /scratch/project/k10018/eq-microtrait-20261110/logs/stage0b_db_%j.err
set -euo pipefail

export EQ_MICROTRAIT_ROOT="/scratch/project/k10018/eq-microtrait-20261110"
export TMPDIR="${EQ_MICROTRAIT_ROOT}/tmp/stage0b_${SLURM_JOB_ID:-local}"
export TMP="$TMPDIR"
export TEMP="$TMPDIR"
mkdir -p "$TMPDIR"

export PATH="${EQ_MICROTRAIT_ROOT}/env/microtrait-r/bin:/project/k10018/sw/envs/gspa-tools/bin:$PATH"
PY="/project/k10018/sw/envs/mapping/bin/python"

cd "$EQ_MICROTRAIT_ROOT"
"$PY" code/stage0b_prep_db.py \
  --root "$EQ_MICROTRAIT_ROOT" \
  --env-prefix "${EQ_MICROTRAIT_ROOT}/env/microtrait-r"
