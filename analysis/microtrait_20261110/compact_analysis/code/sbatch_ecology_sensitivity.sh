#!/bin/bash
#SBATCH -A k10018
#SBATCH -p workq
#SBATCH -N 1
#SBATCH -c 4
#SBATCH -t 00:15:00
#SBATCH -J eq_micro_sens
#SBATCH -o /scratch/project/k10018/eq-microtrait-20261110/integration_sensitivity/logs/%x_%j.out
#SBATCH -e /scratch/project/k10018/eq-microtrait-20261110/integration_sensitivity/logs/%x_%j.err

set -euo pipefail

BASE_DIR="/scratch/project/k10018/eq-microtrait-20261110/integration_sensitivity"
mkdir -p "$BASE_DIR/logs" "$BASE_DIR/results"

export TMPDIR="$BASE_DIR/tmp"
mkdir -p "$TMPDIR"

PY="/project/k10018/sw/envs/mapping/bin/python3"
MAG_KO="/scratch/project/k10018/eq-ecology-mag-20261105/inputs/ibex/rebuild_20260729/picrust2_current_20260803/mag_ko"
ECO_INT="/scratch/project/k10018/eq-ecology-integration-20261108"

echo "[Job Start] Running on $(hostname) at $(date -Is)..."

$PY "$BASE_DIR/run_ecology_sensitivity.py" \
    --mag-index "$MAG_KO/mag_index.tsv" \
    --coverm-npz "$MAG_KO/sample_by_mag_coverm_relative_abundance.npz" \
    --design "$ECO_INT/results/design.tsv" \
    --traits "$BASE_DIR/microtrait_calls_betl_ahpcf.tsv" \
    --out-dir "$BASE_DIR/results"

echo "[Job Done] Completed at $(date -Is)."
