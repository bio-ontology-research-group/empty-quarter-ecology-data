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
- `source/gunc/GUNC.progenomes_3.maxCSS_level.tsv`: GUNC v1.1.1 / proGenomes 3
  `maxCSS_level` output for the 12,434 refined bins, concatenated in sample order
  from the 539 per-library runs under
  `rebuild_20260729/defensome_v2/current_cellularity_r232/gunc_by_sample/` on IBEX
  (`gunc run --detailed_output --contig_taxonomy_output`, default thresholds).
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
Shared Bakta DB access was restored and confirmed in a fresh IBEX session on
24 October 2026; pilot 54460450 was released. The native version metadata is
preserved in `source/bakta_db_version.json` (6.0 full, dated 2025-02-24).
The core `bakta.db` and `psc.dmnd` files are readable. Reference indexing was
running at the time of this check. No alternative database has been provisioned.

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

## Completion, 2 November 2026

The annotation and recruitment rebuild completed on 30 October 2026 (receipt
`metadata/metagenome/canonical/analysis_receipt.json`; summary statistics and
tool versions in `analysis_run.json`). All 5,438 annotation receipts and all 551
coverage tables passed the per-genome and per-library checks in
`scripts/release/rebuild_refined_mag_analyses.py`.

Alejandra Lopez Velazquez deposited the reads, 549 primary assemblies, 12,434
binned metagenomes and 5,437 MAGs under PRJEB125153 (26 to 29 October 2026);
release is scheduled for 25 November 2026. The deposit tables and ENA accession
notifications are snapshotted in `source/ena_deposit/` and folded into
`metadata/metagenome/canonical/` by `scripts/release/prepare_mag_metadata.py`.
Her deposit metadata declares MEGAHIT 1.2.9, SemiBin2 2.2.1, DAS Tool 1.1.7 and
CheckM2 1.1.0 for every bin. Robert Hoehndorf decided on 2 November 2026 that the
functional annotation tables are hosted by the project rather than deposited at
ENA. The remaining gate is an immutable public or reviewer locator for the three
project-hosted archives; the sections above record the 24 October state.

## Library kits and public archive, 4 November 2026

Robert Hoehndorf confirmed on 4 November 2026 that Alejandra's kit assignment,
which Marwa Abdelhakim confirmed, applies to all runs: the 70 runs without an
index code used the QIAseq FX DNA Library UDI Kit (473 QIAseq FX runs and 81
NEBNext Ultra II runs in total). He also decided that the three project-hosted
archives are published as a Zenodo deposit linked from https://rubalkhali.science/;
he uploads the staged set (`metadata/metagenome/canonical/README.md`).

## Cross-paper cohort and product manifest, 8 November 2026

`scripts/release/build_cohort_product_manifest.py` generates
`metadata/cohorts/cohort_product_manifest.json`,
`metadata/cohorts/shotgun_cohort_accounting.tsv` and
`metadata/cohorts/mimag_quality_boundary.tsv` from the staged source tables in
`metadata/cohorts/source/` and `metadata/metagenome/canonical/`:

- Reconciles the 551 read-bearing shotgun libraries (554 paired-end runs across
  221 NovaSeq 6000 and 333 NovaSeq X runs; 61 site codes = 59 primary sites plus
  Trip 1 named sites 62 and 64; 549 primary MEGAHIT assemblies) to the current
  downstream cohorts: 550 non-zero mapped libraries (excluding `F5Dr1`), 546
  core-transect libraries across 59 primary sites (excluding `62PRr2`, `64Dr3`,
  `64PRr2`, `64Sr2`), 545 core read-depth-modeled libraries (excluding
  `F45PRr3`), 442 amplicon-matched libraries across 58 primary sites joined to
  the 1,186 deduplicated 16S profiles, and 441 matched read-depth-modeled
  libraries.
- Records the strict MIMAG boundary (`126` HQ, `5,311` strict MQ `<10%`
  contamination deposited as `5,437` ENA GCA MAGs, and `48Dr2__self_SemiBin_25`
  at `10.0%` contamination deposited as binned metagenome `ERZ29258845` while
  included in the `5,438` operational dRep set under `<=10%` contamination).
- Distinguishes the `19,186,792` Bakta v1.12.0 release proteins
  (snapshot identifier `EQ-PROT-BAKTA-v1.0.0`) from the `20,451,986` Pyrodigal
  per-representative proteins (snapshot identifier `EQ-PROT-PYRODIGAL-REP-v1.0.0`,
  associated with the same `5,438` representative genome identifiers and
  reconciled with `20,379,930` bin-mapped assembly proteins); matching genome
  identifiers do not establish identical underlying FASTA sequence contents or
  retained contig coordinates, keeping cross-caller sequence equivalence as
  `UNVERIFIED_SEPARATE_PRODUCTS`.
- Assigns distinct snapshot version identities to the four CoverM read-mapping products:
  `EQ-COVERM-REFINED-v1.0.0` (551-library Bowtie2/CoverM v0.6.1 depth/breadth),
  `EQ-COVERM-REL-ABUND-v1.0.0` (CoverM v0.7.0 relative-abundance cohort matrix),
  `EQ-COVERM-ARCHAEA-COMP-v1.0.0` (193-profile competitive archaeal mapping
  across 68 visits and 36 sites with 301 external Thermoplasmatota references,
  where `MAPQ >= 20` is a separate sensitivity analysis), and
  `EQ-COVERM-LEGACY-991-v0` (historical Trips 1–3 150-library / 991-genome /
  990-KO-genome pilot).
