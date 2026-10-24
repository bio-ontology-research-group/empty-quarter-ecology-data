#!/bin/bash
#SBATCH --job-name=H2_ref3
#SBATCH --partition=batch
#SBATCH --cpus-per-task=32
#SBATCH --mem=320G
#SBATCH --time=36:00:00
#SBATCH --output=/ibex/project/c2014/rob/eq-hypotheses-20261017/H2/logs/%x_%j.out
# Canonical catalogue -> reps.fa + reps.stb (file membership), prodigal genes (single mode, per genome, on the
# deduplicated contigs; the inStrain gene file), bowtie2 large index. Restartable: skips to bowtie2-build if genes exist.
# Memory: 128 GB was not enough (bowtie2-build of 20.5 Gbp stalled at the cgroup limit in job 53905260).
set -euo pipefail
source /ibex/project/c2014/rob/eq-hypotheses-20261017/H2/pipeline/config.sh
module load bowtie2/2.5.1 prodigal/2.6.3 python/3.11.0
cd $WD/ref 2>/dev/null || mkdir -p $WD/ref
if [ -s $REF.genes.faa ] && [ -s $REF.genes.fna ] && [ -s $REF.stb ] && [ ! -d $WD/ref/per_genome ]; then
  echo "reference fasta, stb and genes exist; skipping to bowtie2-build"
else
rm -rf $WD/ref/per_genome; mkdir -p $WD/ref/per_genome; cd $WD/ref
python $WD/pipeline/build_reference.py $MEMBERSHIP $CAT/mags/dereplicated $REF
# split back per genome for prodigal single mode (training per genome), 32 in parallel
python - <<PY
stb = dict(l.rstrip('\n').split('\t') for l in open('$REF.stb'))
fh = {}; cur = None
for line in open('$REF.fa'):
    if line.startswith('>'):
        g = stb[line[1:].split()[0]]
        if g not in fh:
            if len(fh) > 200: [h.close() for h in fh.values()]; fh.clear()
            fh[g] = open(f'$WD/ref/per_genome/{g}.fa', 'a')
        cur = fh[g]
    cur.write(line)
[h.close() for h in fh.values()]
PY
gp() { o=${1%.fa}; prodigal -p single -q -i $1 -d $o.fna -a $o.faa -o /dev/null 2>/dev/null || prodigal -p meta -q -i $1 -d $o.fna -a $o.faa -o /dev/null; }
export -f gp
ls $WD/ref/per_genome/*.fa | xargs -P 32 -I{} bash -c 'gp {}'
cat $WD/ref/per_genome/*.fna > $REF.genes.fna; cat $WD/ref/per_genome/*.faa > $REF.genes.faa
echo "per-genome fastas: $(ls $WD/ref/per_genome/*.fa | wc -l); genes: $(grep -c '^>' $REF.genes.faa)"
rm -rf $WD/ref/per_genome
fi
rm -f $REF.*.bt2l
bowtie2-build --large-index --threads 32 $REF.fa $REF > $WD/logs/bowtie2_build.log 2>&1
echo REF_DONE
