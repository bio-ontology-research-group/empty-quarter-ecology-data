#!/bin/bash
#SBATCH --job-name=H2_mapcov
#SBATCH --partition=batch
#SBATCH --array=1-551%40
#SBATCH --cpus-per-task=8
#SBATCH --mem=48G
#SBATCH --time=2-00:00:00
#SBATCH --output=/ibex/project/c2014/rob/eq-hypotheses-20261017/H2/logs/%x_%A_%a.out
# One library: bowtie2 --very-sensitive vs all 5,438 canonical representatives (competitive) -> sorted BAM ->
# CoverM genome coverage (reads >=95% identity; all genomes) -> subset BAM restricted to genomes with mean >= COV_CAND
# -> delete the full BAM. inStrain runs later (05) on the subset BAM against a reduced reference.
set -euo pipefail
source /ibex/project/c2014/rob/eq-hypotheses-20261017/H2/pipeline/config.sh
module load bowtie2/2.5.1 samtools/1.16.1 coverm/0.6.1
line=$(sed -n "$((SLURM_ARRAY_TASK_ID+1))p" $SAMPLES); [ -z "$line" ] && exit 0
S=$(cut -f1 <<<"$line"); R1=$(cut -f6 <<<"$line"); R2=$(cut -f7 <<<"$line")
bam=$WD/bam/$S.bam; sub=$WD/subbam/$S.bam; cov=$WD/cov/$S.tsv
if [ -s "$cov" ] && [ -s "$sub.bai" ]; then echo "exists $S"; rm -f $bam $bam.bai; exit 0; fi
while :; do used=$(du -s --block-size=1G $WD 2>/dev/null | cut -f1)
  [ "$used" -lt "$DISK_CAP_GB" ] && break; echo "$(date +%F_%T) disk ${used}G >= ${DISK_CAP_GB}G, waiting"; sleep 900; done
echo "$(date +%F_%T) start $S (work dir ${used}G)"
if [ ! -s $bam.bai ]; then
  bowtie2 -p 8 --very-sensitive --no-unal -u $MAX_PAIRS -x $REF -1 $R1 -2 $R2 2> $WD/bt2logs/${S}.log \
   | samtools sort -@ 3 -m 1500M -T $TMPDIR/${S}.sort -o $bam.tmp -
  mv $bam.tmp $bam; samtools index -@ 4 $bam
fi
echo "$(date +%F_%T) mapped $S: $(tail -1 $WD/bt2logs/${S}.log)"
coverm genome -b $bam --genome-definition $REF.coverm_def.tsv -m mean covered_fraction trimmed_mean count length \
  --min-read-percent-identity 95 --min-covered-fraction 0 -t 8 --output-file $cov.tmp
mv $cov.tmp $cov
echo "$(date +%F_%T) coverm $S"
python3 $WD/pipeline/cand_bed.py $cov $REF.stb $REF.fa.fai $COV_CAND > $WD/cov/$S.cand.bed
samtools view -@ 4 -b -M -L $WD/cov/$S.cand.bed -o $sub.tmp $bam
mv $sub.tmp $sub; samtools index -@ 4 $sub
rm -f $bam $bam.bai
echo "$(date +%F_%T) MAPCOV_DONE $S subset=$(du -h $sub | cut -f1)"
