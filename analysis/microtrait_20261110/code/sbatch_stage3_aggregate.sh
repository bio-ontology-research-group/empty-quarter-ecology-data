#!/bin/bash
#SBATCH -A k10018
#SBATCH -p workq
#SBATCH -N 1
#SBATCH --exclusive
#SBATCH -t 01:30:00
#SBATCH -J eq_mt_s3_agg
#SBATCH -o /scratch/project/k10018/eq-microtrait-20261110/logs/stage3_agg_%j.out
#SBATCH -e /scratch/project/k10018/eq-microtrait-20261110/logs/stage3_agg_%j.err
set -euo pipefail

export EQ_MICROTRAIT_ROOT="/scratch/project/k10018/eq-microtrait-20261110"
export TMPDIR="${EQ_MICROTRAIT_ROOT}/tmp/stage3_agg_${SLURM_JOB_ID:-local}"
export TMP="$TMPDIR"
export TEMP="$TMPDIR"
mkdir -p "$TMPDIR"

export PATH="${EQ_MICROTRAIT_ROOT}/env/microtrait-r/bin:/project/k10018/sw/envs/gspa-tools/bin:$PATH"
PY="/project/k10018/sw/envs/mapping/bin/python"

cd "$EQ_MICROTRAIT_ROOT"
"$PY" code/stage3_aggregate_and_validate.py \
  --root "$EQ_MICROTRAIT_ROOT" \
  --ncores 32

"$PY" -m pytest -v tests/test_microtrait_pipeline.py
