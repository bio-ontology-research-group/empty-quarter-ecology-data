#!/bin/bash
#SBATCH -A k10018
#SBATCH -p workq
#SBATCH -N 1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH -t 01:00:00
#SBATCH -J eq_mt_s0a_ext
#SBATCH -o /scratch/project/k10018/eq-microtrait-20261110/logs/stage0a_ext_%j.out
#SBATCH -e /scratch/project/k10018/eq-microtrait-20261110/logs/stage0a_ext_%j.err
set -euo pipefail

export EQ_MICROTRAIT_ROOT="/scratch/project/k10018/eq-microtrait-20261110"
export TMPDIR="${EQ_MICROTRAIT_ROOT}/tmp/stage0a_${SLURM_JOB_ID:-local}"
export TMP="$TMPDIR"
export TEMP="$TMPDIR"
mkdir -p "$TMPDIR"

PY="/project/k10018/sw/envs/mapping/bin/python"
cd "$EQ_MICROTRAIT_ROOT"
"$PY" code/stage0a_extract_genomes.py \
  --root "$EQ_MICROTRAIT_ROOT" \
  --n-chunks 34
