#!/bin/bash
#SBATCH --job-name=r5d-controls
#SBATCH --account=k10018
#SBATCH --partition=workq
#SBATCH --nodes=1
#SBATCH --time=04:00:00
#SBATCH --output=/scratch/project/k10018/work/eq-round5-20261124/data/controls/%x-%j.log
# Shotgun positive and negative controls: map 2 million read pairs (all reads for SNTC) competitively to the
# ZymoBIOMICS D6300 reference genomes and, separately, to the 5,438 catalogue representatives.
set -eu
E=/project/k10018/sw/envs/mapping/bin
W=/scratch/project/k10018/work/eq-round5-20261124/data/controls
F=/project/k10018/empty-quarter/data/reads/fastq
REPS=/project/k10018/empty-quarter/analyses/hypotheses-20261017/H2/ref/reps
T=${SLURM_CPUS_ON_NODE:-64}
cd $W
mkdir -p idx reads bam out
[ -s idx/zymo.1.bt2 ] || $E/bowtie2-build --threads $T zymo_refs.fa idx/zymo > idx/build.log 2>&1
N=8000000  # lines = 2M reads
for s in SPositive SNTC P34; do
  zcat $F/${s}_R1.fastq.gz | head -n $N > reads/${s}_R1.fq || true
  zcat $F/${s}_R2.fastq.gz | head -n $N > reads/${s}_R2.fq || true
done
zcat T5pos_R1.fq.gz | head -n $N > reads/T5pos_R1.fq || true
zcat T5pos_R2.fq.gz | head -n $N > reads/T5pos_R2.fq || true
for s in SPositive SNTC P34 T5pos; do
  echo "== $s pairs: $(( $(wc -l < reads/${s}_R1.fq) / 4 ))" >> out/read_counts.txt
  $E/bowtie2 -p $T --very-sensitive --no-unal -x idx/zymo -1 reads/${s}_R1.fq -2 reads/${s}_R2.fq 2> out/${s}.zymo.bowtie2.log \
    | $E/samtools sort -@ 8 -o bam/${s}.zymo.bam -
  $E/coverm genome -b bam/${s}.zymo.bam -s '|' -m relative_abundance count covered_fraction --min-read-percent-identity 95 \
    --min-covered-fraction 0 -t $T > out/${s}.zymo.coverm.tsv 2> out/${s}.zymo.coverm.log
  $E/bowtie2 -p $T --very-sensitive --no-unal -x $REPS -1 reads/${s}_R1.fq -2 reads/${s}_R2.fq 2> out/${s}.reps.bowtie2.log \
    | $E/samtools sort -@ 8 -o bam/${s}.reps.bam -
  $E/coverm genome -b bam/${s}.reps.bam --genome-definition $REPS.coverm_def.tsv -m relative_abundance count covered_fraction \
    --min-read-percent-identity 95 --min-covered-fraction 0 -t $T > out/${s}.reps.coverm.tsv 2> out/${s}.reps.coverm.log
done
rm -rf reads bam
echo done
