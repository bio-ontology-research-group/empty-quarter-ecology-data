# Tier 1 MAG provenance audit, 24 October 2026

## Decisions confirmed by Robert

Shotgun data belong in this data paper alongside amplicon data. The shotgun ENA
study is PRJEB125153, secondary ERP204894, and is not yet public. Exact processing
details should be recovered from IBEX. Manuscript conflict resolution prioritizes
Rund and Susana's text. Overleaf's 21 October rewrite was retained; the conflict
resolution is BORG commit dc72823 and the reference repair is Overleaf a44f232.
The earlier BORG stash was preserved.
Robert also selected actual refined representatives and extended this task to
rebuild both functional annotations and recruitment. He requested access to the
shared Bakta database; retain that database and wait for the grant to propagate.

## Source locations

All paths below are on IBEX unless a local checkout is named.

- Pickup catalogue: `/ibex/scratch/projects/c2014/EmptyQuarter_Data/processed/sequencing-results/catalog/`.
  `source/catalog_membership.tsv` is copied from `mags/catalog_membership.tsv`.
- Refined outputs: `/ibex/scratch/projects/c2014/rob/metagenomics/05_refine/`.
  `source/checkm2_refined_quality_report.tsv` is copied from
  `_checkm2_refined/quality_report.tsv`; `source/drep_cluster_arguments.json`
  from `_drep/out/log/cluster_arguments.json`.
- Recruitment: `/ibex/project/c2014/rob/eq-hypotheses-20261017/H2/`.
  `source/samples551.tsv`, `metagenome_sample_meta.tsv`,
  `metagenome_sample_meta_150.tsv`, `03_map_cov.sbatch`, `build_reference.py`
  and `config.sh` are copied from its `pipeline/` directory.
- `source/megahit_10Dr2.log`: `/ibex/scratch/projects/c2014/EmptyQuarter_Data/soil/wgs_assemblies/assemblies/10Dr2/log`.
- `source/semibin2_10Dr2.log`: pickup-tree `sites/trip1/site10/10Dr2/wgs/binning/single_sample/SemiBinRun.log`.
- `source/dastool_11PRr3.log`: refined-output `11PRr3/11PRr3_DASTool.log`.
- `source/checkm2_refined.log`: refined-output `_checkm2_refined/checkm2.log`.
- `source/taxonomy_r232/`: native summaries, upstream checksums, representative
  IDs, builder and README copied from refined-output `_gtdbtk_r232/`.

Source-file SHA-256 values are generated in
`metadata/metagenome/canonical/release_status.json`. Source code inspected locally:
`/home/leechuck/Public/software/empty-quarter-workbench/scripts/ibex/95_canonical_links.sh`
(checkout HEAD c38598a3482bc690caf06d0316e9fa437b9a5487).

## Sequence identity and verified package

The pickup directory contains 5,394 `.fa.gz` entries and 44 `.fa` entries.
The membership table contains 5,438 unique representative identifiers, including
1,010 marked `refined_sub=1`. The linker strips `_sub` before locating the source
bin and points those catalogue entries at parent SemiBin FASTAs. Thus the identifier
of a refined representative can label different sequence content in the pickup
directory and in the dRep output.

Direct comparison of `11PRr3__single_SemiBin_49_sub`:

| Source | Contigs | Bases |
| --- | ---: | ---: |
| Pickup catalogue, parent `SemiBin_49.fa.gz` | 863 | 3,575,962 |
| Actual refined dRep FASTA | 849 | 3,407,564 |

All 1,010 entries are exposed to this linker rule; only the example above has been
sequence-compared between pickup and dRep in this audit. Do not equate that count
with 1,010 verified sequence mismatches. The release bypasses the pickup links.
Do not alter the live pickup links: downstream jobs consume them.

Robert selected the **actual refined dRep representatives** on 24 October 2026.
Packaging runs separately from the live pickup tree in
`/ibex/project/c2014/rob/data-paper-mag-tier1-20261024/`, using
`scripts/release/package_refined_mags.py` (Slurm job 54457431).
The packager compares every FASTA's contig count and total length with refined-bin
CheckM2, embeds a per-genome checksum manifest, and rereads the archive to verify
every member's exact bytes. Job 54457431 completed successfully: 5,438 genomes,
2,485,945 contigs and 20,490,828,267 bases. The compressed archive is
7,215,750,013 bytes, SHA-256
`e7f46a9faee01ad7a723fe2fc4ad2310d19e0d2f1dbc832a787d8749a1303d6c`.
The machine-readable manifest and receipt are in `metadata/metagenome/canonical/`.
`source/package_refined_mags_run.py` preserves the exact executed packager;
the maintained script additionally fixes Python 3.7 error-path cleanup.
Annotation and recruitment rebuilds remain pending.

## Quality, taxonomy and annotations

The refined CheckM2 report contains 14,426 bins and matches all 5,438 representative
identifiers. The generated representative table uses those refined-bin estimates,
not the per-sample parent-bin report. The dRep settings specify 50% minimum
completeness, 10% maximum contamination, 50,000 bp minimum genome size, 90% primary
ANI and 95% secondary ANI (fastANI), alignment coverage 0.1 with `larger` convention.

Run logs inspected on IBEX identify MEGAHIT v1.2.9 and SemiBin2 v2.2.1 for 10Dr2,
DAS Tool v1.1.7 for 11PRr3, and CheckM2 v1.1.0 for the refined-bin quality run.
These checks establish those runs, not universal version identity across campaigns.
The exact self-supervised binning and dRep run versions and the full run-wide
assembly/preprocessing and wet-lab provenance remain to be checked.

The pickup taxonomy summaries point at the original single-sample GTDB-Tk results.
Their identifiers omit the binning-strategy token. They cannot be joined to all
representatives by simply stripping `single`, `self` or `_sub`. A refined GTDB-Tk
r226 log records only 268 genomes. The `_gtdbtk_r232/` directory provides a
checksummed subset of GTDB-Tk v2.7.2 / R232 classifications for exactly the 5,438
representative IDs (4,847 bacterial, 591 archaeal). Its README records Alejandra's
17 August correction that R232 supersedes r226. The metadata builder verifies both
upstream checksums and exact representative-ID coverage, then preserves the native
lineage strings. These classifications describe the refined representatives.

The supplied brief reports eggNOG outputs for 5,394 identifiers. Its aggregate
KO/CAZy/Pfam/preferred-name tables are based on per-bin annotations. Their exact
sequence scope must be established for refined representatives before release.
Missing annotations must remain explicit, rather than being represented as zero
gene counts. Do not transfer parent-bin annotations by renaming the genome ID.

## Recruitment and legacy inputs

There are 551 TSV files in `H2/cov/`, but only the file count and one table header
were checked; full content validation remains open. The paired-read inventory has
551 unique libraries and 61 source site codes, with campaign counts 210/37/128/85/91.
The brief reports an additional Trip 1 library, 22Sr1, without reads.

The recorded mapping command uses Bowtie2 v2.5.1, SAMtools v1.16.1 and CoverM
v0.6.1; Bowtie2 is capped at the first 200,000,000 read pairs per library.
CoverM retains reads at >=95% identity and uses `--min-covered-fraction 0`.
The output columns are mean depth, covered fraction, trimmed mean, read count and
reference length. These are coverage metrics, not the old genome-relative-abundance
percentages.

`build_reference.py` reads the pickup FASTAs and assigns duplicate contig identifiers
to the first representative in membership order, dropping subsequent occurrences.
A complete release must preserve the exact reference, genome-contig definition,
genome-size table and dropped-contig ledger, and reconcile them with the selected
MAG sequences. Existing recruitment cannot simply be relabelled as coverage of
the actual refined dRep genomes.

The 150-library metadata table contains 58 Trip 1, 15 Trip 2 and 77 Trip 3 libraries.
The legacy 991-genome catalogue / 990-genome KO intersection and six comparison
tables remain separate ecology-analysis inputs. The ecology paper's Trip 5 wording
needs correction in its own repository; this task updates the data paper only.

## Refined-sequence analysis rebuild

`analysis_run.json` records the submitted jobs and dependencies. The reference
builder checks every source FASTA against the sequence manifest, prefixes every
contig ID with `MAG|`, and retains all contigs, including identical original IDs
in different genomes. It records reference and genome-definition checksums.
Indexing requests 320 GB because the upstream indexing script records failure
with 128 GB for this reference scale.

Mapping preserves the recorded Bowtie2/CoverM versions and options, including
the first-200-million-pairs cap. Every output must contain exactly the catalogue's
genome IDs, matching reference lengths, finite nonnegative metrics and valid
coverage fractions. Each temporary BAM is removed after its validated coverage
table is committed. The archived coverage includes the contig-to-genome map,
reference receipt and library read inventory.

Annotation runs Bakta against DB 6.0, then eggNOG-mapper on the resulting proteins
using the shared eggNOG database at `/ibex/reference/KSL/eggnog-mapper/2.1.12`.
Actual executable versions are recorded per genome. The installed eggNOG mapper
inspected before submission reports 2.1.13; database-directory names are not
treated as executable-version evidence. Per-genome receipts bind outputs to the
packaged FASTA checksum and reject changed completed outputs. The aggregate
tables count KO, CAZy, Pfam and preferred-name assignments per gene and include
predicted, annotated and KO-assigned gene counts.

One pilot precedes each array. Remaining libraries are grouped five per task and
MAGs twenty per task to fit the 2,000-job submission limit; each array permits
eight concurrent tasks. The finalizer depends on both arrays and checks all 551
coverage tables and 5,438 annotation receipts before producing archives. These
jobs being accepted by Slurm is not evidence that the analyses have completed.
The annotation pilot is held until shared Bakta DB access is readable in a fresh
IBEX session. No alternative database has been provisioned.

Remaining publication gates: run/sample accession crosswalk; run-wide
assembly/binning versions and parameters; shotgun library-preparation provenance;
completed annotation/recruitment archives; taxonomy redistribution terms;
MAG submission metadata and immutable public/reviewer archive locators.

## ENA deposition

Submit eligible MAG assemblies under PRJEB125153 using Webin-CLI's genome context,
with a derived MAG sample per assembly, the GSC MIMAGS checklist, and links to
the source environmental sample and read runs. ENA recommends the highest-quality
unique representative per species/biome. Confirm sequence quality, taxonomy and
species dereplication before treating every catalogue entry as submission-ready.
Archive the complete versioned catalogue and supporting tables in the data deposit
as well. Use final GCA assembly accessions in the paper; the initial ERZ submission
identifier is administrative.

Official instructions checked on 24 October 2026:
https://ena-docs.readthedocs.io/en/latest/submit/assembly/metagenome/mag.html

No ENA submission, public release or modification of upstream sequences has been
performed by this task. The new sequence archive is a private staging artifact.
