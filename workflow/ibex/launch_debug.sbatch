#!/usr/bin/env bash
#SBATCH --account=c2014
#SBATCH --partition=debug
#SBATCH --job-name=eq-nf-debug
#SBATCH --time=02:00:00
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --output=driver-debug-%j.log

set -euo pipefail
module load nextflow/25.10.4 singularity/3.9.7 groovy/4.0.7

: "${EQ_PROJECT_ROOT:?Set EQ_PROJECT_ROOT}"
: "${EQ_ECOLOGY_PAPER:?Set EQ_ECOLOGY_PAPER}"
: "${EQ_ANALYSIS_CONTAINER:?Set EQ_ANALYSIS_CONTAINER}"

cd "$EQ_PROJECT_ROOT"

outdir=${EQ_OUTDIR:-"$EQ_PROJECT_ROOT/results/reproducibility/debug"}

NXF_BOOTSTRAP_USE_SYSTEM=1 workflow/bin/bootstrap_nextflow.sh \
  run workflow/main.nf \
  -profile debug \
  --project_root "$EQ_PROJECT_ROOT" \
  --ecology_paper "$EQ_ECOLOGY_PAPER" \
  --outdir "$outdir" \
  --analysis_container "$EQ_ANALYSIS_CONTAINER" \
  --stage evidence \
  -resume
