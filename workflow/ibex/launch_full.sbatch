#!/usr/bin/env bash
#SBATCH --account=c2014
#SBATCH --partition=batch
#SBATCH --job-name=eq-nf-full
#SBATCH --time=14-00:00:00
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --output=driver-full-%j.log

set -euo pipefail
module load nextflow/25.10.4 singularity/3.9.7 groovy/4.0.7

: "${EQ_PROJECT_ROOT:?Set EQ_PROJECT_ROOT}"
: "${EQ_ECOLOGY_PAPER:?Set EQ_ECOLOGY_PAPER}"
: "${EQ_ANALYSIS_CONTAINER:?Set EQ_ANALYSIS_CONTAINER}"
: "${EQ_TEX_CONTAINER:?Set EQ_TEX_CONTAINER}"

release_inputs="$EQ_PROJECT_ROOT/data-paper/zenodo/metadata"
pma_asv_table=${EQ_PMA_ASV_TABLE:-"$release_inputs/relic-dna/PMA_ASV_table.tsv"}
coverm_dir=${EQ_COVERM_DIR:-"$release_inputs/metagenome/coverm_profiles.tar.gz"}
eggnog_annotations=${EQ_EGGNOG_ANNOTATIONS:-"$release_inputs/metagenome/eq.emapper.annotations.gz"}
measured_function_inputs=${EQ_MEASURED_FUNCTION_INPUTS:-"$release_inputs/metagenome/measured_function_inputs.tar.gz"}
outdir=${EQ_OUTDIR:-"$EQ_PROJECT_ROOT/results/reproducibility/full"}

cd "$EQ_PROJECT_ROOT"

NXF_BOOTSTRAP_USE_SYSTEM=1 workflow/bin/bootstrap_nextflow.sh \
  run workflow/main.nf \
  -profile ibex \
  --project_root "$EQ_PROJECT_ROOT" \
  --ecology_paper "$EQ_ECOLOGY_PAPER" \
  --outdir "$outdir" \
  --analysis_container "$EQ_ANALYSIS_CONTAINER" \
  --tex_container "$EQ_TEX_CONTAINER" \
  --pma_asv_table "$pma_asv_table" \
  --coverm_dir "$coverm_dir" \
  --eggnog_annotations "$eggnog_annotations" \
  --measured_function_inputs "$measured_function_inputs" \
  --stage full
