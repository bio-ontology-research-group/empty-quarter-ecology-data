#!/usr/bin/env bash
# Submit with resource limits and dependencies recorded in the run receipt.
set -euo pipefail
work=${EQ_MAG_WORK:-/ibex/project/c2014/rob/data-paper-mag-tier1-20261024}
genomes=/ibex/scratch/projects/c2014/rob/metagenomics/05_refine/_drep/out/dereplicated_genomes
threads=${SLURM_CPUS_PER_TASK:-8}
mode=${1:?reference, map, annotate or finish}
cd "$work"

case "$mode" in
reference)
    module load bowtie2/2.5.1 samtools/1.16.1
    python3 rebuild_refined_mag_analyses.py reference --work "$work" --genomes "$genomes"
    bowtie2-build --threads "$threads" reference/refined.fa reference/refined
    samtools faidx reference/refined.fa
    bowtie2 --version > reference/bowtie2.version.txt
    ;;
map)
    module load bowtie2/2.5.1 samtools/1.16.1 coverm/0.6.1
    row=$(sed -n "$((SLURM_ARRAY_TASK_ID + 1))p" samples551.tsv)
    IFS=$'\t' read -r sample trip site compartment replicate r1 r2 <<< "$row"
    test -n "$sample" && test -s "$r1" && test -s "$r2"
    mkdir -p coverage mapping_logs
    if [[ -s "coverage/${sample}.tsv" ]]; then
        python3 rebuild_refined_mag_analyses.py coverage --work "$work" --sample "$sample" --complete
        exit 0
    fi
    scratch=$(mktemp -d "$work/.map_${sample}.XXXXXX")
    trap 'rm -rf "$scratch"' EXIT
    bowtie2 -p "$((threads - 3))" --very-sensitive --no-unal -u 200000000 \
        -x reference/refined -1 "$r1" -2 "$r2" 2> "mapping_logs/${sample}.log" \
        | samtools sort -@ 2 -m 1500M -T "$scratch/sort" -o "$scratch/$sample.bam" -
    coverm genome -b "$scratch/$sample.bam" --genome-definition reference/genomes.tsv \
        -m mean covered_fraction trimmed_mean count length --min-read-percent-identity 95 \
        --min-covered-fraction 0 -t "$threads" --output-file "coverage/${sample}.tsv.partial"
    python3 rebuild_refined_mag_analyses.py coverage --work "$work" --sample "$sample"
    mv "coverage/${sample}.tsv.partial" "coverage/${sample}.tsv"
    ;;
annotate)
    source /ibex/scratch/projects/c2014/rob/miniconda3/etc/profile.d/conda.sh
    mag=$(sed -n "$((SLURM_ARRAY_TASK_ID + 1))p" release/genome_manifest.tsv | cut -f1)
    test -n "$mag"
    expected=$(awk -F '\t' -v m="$mag" '$1==m {print $4}' release/genome_manifest.tsv)
    printf '%s  %s\n' "$expected" "$genomes/$mag.fa" | sha256sum -c -
    mkdir -p annotations
    if [[ -s "annotations/$mag/DONE.json" ]]; then
        python3 rebuild_refined_mag_analyses.py annotation-receipt --work "$work" --mag "$mag" --directory "$work/annotations/$mag"
        exit 0
    fi
    test ! -e "annotations/$mag"
    scratch=$(mktemp -d "$work/annotations/.${mag}.XXXXXX")
    conda activate bakta
    bakta --version > "$scratch/bakta.version.txt"
    bakta --db /ibex/reference/KSL/bakta/6.0/db --output "$scratch/bakta" \
        --prefix "$mag" --threads "$threads" --skip-plot "$genomes/$mag.fa"
    conda activate eggnog
    emapper.py --version > "$scratch/eggnog.version.txt"
    mkdir -p "$scratch/eggnog"
    emapper.py -i "$scratch/bakta/$mag.faa" --output "$mag" --output_dir "$scratch/eggnog" \
        --data_dir /ibex/reference/KSL/eggnog-mapper/2.1.12 --cpu "$threads" --itype proteins
    python3 rebuild_refined_mag_analyses.py annotation-receipt --work "$work" --mag "$mag" --directory "$scratch"
    mv "$scratch" "annotations/$mag"
    ;;
finish)
    python3 rebuild_refined_mag_analyses.py finish --work "$work"
    ;;
annotate-packed)
    start=$(( (SLURM_ARRAY_TASK_ID - 1) * 20 + 2 ))
    end=$((start + 19))
    if ((end > 5438)); then end=5438; fi
    for index in $(seq "$start" "$end"); do
        SLURM_ARRAY_TASK_ID=$index bash "$0" annotate
    done
    ;;
map-packed)
    start=$(( (SLURM_ARRAY_TASK_ID - 1) * 5 + 2 ))
    end=$((start + 4))
    if ((end > 551)); then end=551; fi
    for index in $(seq "$start" "$end"); do
        SLURM_ARRAY_TASK_ID=$index bash "$0" map
    done
    ;;
*) exit 64 ;;
esac
