# Shared settings, sourced by every H2 v2 job. Nothing here submits jobs.
export WD=/ibex/project/c2014/rob/eq-hypotheses-20261017/H2
export RAW=/ibex/scratch/projects/c2014/EmptyQuarter_Data/soil/wgs_reads/processed
export CONCAT_FAA=/ibex/scratch/projects/c2014/EmptyQuarter_Data/soil/eq_regen/eggnog/concat.faa
export EMAPPER=/ibex/scratch/projects/c2014/EmptyQuarter_Data/soil/eq_regen/eggnog/eq.emapper.annotations
export REF=$WD/ref/reps            # reps.fa, reps.stb, reps.genes.fna/.faa, bowtie2 index reps.*.bt2l
export VENV=$WD/venv
export MAX_PAIRS=200000000         # bowtie2 -u cap per library (affects the 3 deepest libraries)
export DISK_CAP_GB=380             # mapping tasks wait while the work dir exceeds this
export TMPDIR=$WD/tmp
mkdir -p $TMPDIR $WD/logs
# v3: canonical catalogue (5,438 dRep representatives) replaces the ad-hoc dRep of workstation bins
export CAT=/ibex/scratch/projects/c2014/EmptyQuarter_Data/processed/sequencing-results/catalog
export MEMBERSHIP=$CAT/mags/catalog_membership.tsv

# ---- v4 (2026-10-18): all 551 libraries with reads; CoverM coverage on the full BAM, inStrain only on a reduced reference ----
export SAMPLES=$WD/pipeline/samples551.tsv   # sample trip site code replicate R1 R2 (header line 1)
export NLIB=551
export COV_CAND=3          # CoverM mean coverage (reads >=95% id) at which a genome's scaffolds are kept in the per-library subset BAM
export PRE_COV=4           # pre-selection on CoverM: mean >= PRE_COV and covered fraction >= PRE_FRAC ...
export PRE_FRAC=0.4        # ... in >=10 libraries / >=6 sites / >=2 thirds -> candidate genomes for the reduced reference
export REFQ=$WD/refQ/repsQ # repsQ.fa, repsQ.stb, repsQ.genes.fna/.faa, repsQ.scaffolds.txt
export DISK_CAP_GB=1500    # v4: project fs has ~17 TB free; full BAMs are deleted once the subset BAM exists
