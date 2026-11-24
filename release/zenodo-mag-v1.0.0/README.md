# Metagenome-assembled genome catalogue of Rub' al-Khali (Empty Quarter) desert soils, v1.0.0

This deposit contains the species-representative metagenome-assembled genomes
(MAGs) reconstructed from 551 shotgun metagenomes of Rub' al-Khali desert soil,
collected in five campaigns between 2023 and 2025, together with their quality
estimates, taxonomy, gene annotations and per-library coverage, and the specimen,
library and gene tables needed to join them. It accompanies the
data descriptor of the Rub' al-Khali knowledge base
(https://rubalkhali.science/; KG v3.0.1, https://doi.org/10.5281/zenodo.23134168).

## Contents

| File | Content |
|---|---|
| `refined_mags.tar.gz` | 5,438 refined dRep representative FASTAs (2,485,945 contigs, 20,490,828,267 bp) |
| `refined_functional_tables.tar.gz` | `functional/`: per-genome KO, CAZy, Pfam and preferred-name counts (`genome_*_long.tsv`), predicted/annotated protein counts (`genome_ngenes.tsv`), tool versions and checksums per genome (`annotation_provenance.tsv`) |
| `refined_coverm_profiles.tar.gz` | `coverage/<library>.tsv`: CoverM mean depth, covered fraction, trimmed mean, read count and length of every genome in each of the 551 libraries; `reference/genomes.tsv` (contig-to-genome definition) and `reference/reference_receipt.json`; `samples551.tsv` (library list) |
| `refined_representatives.tsv` | source library, binning strategy, CheckM2 quality and GTDB R232 lineage per representative |
| `genome_manifest.tsv` | archive member path, size, SHA-256, contig and base count per FASTA |
| `library_metadata.tsv` | campaign, site, compartment, replicate and ENA BioSample, experiment, run and assembly accessions per library |
| `ena_genome_accessions.tsv` | 12,434 refined bins with MIMAG tier, binned-metagenome accessions and, for 5,437 representatives, MAG BioSample, analysis, GCA and sequence accessions |
| `gene_crosswalk.tar` | `crosswalk/<library>.tsv.gz` (473 files, one per source library): every Pyrodigal gene of the 5,438 representatives (20,451,986 genes) with contig, coordinates and strand, its protein-family representative, the matching Bakta coding sequence (locus tag, product) and the eggNOG record (orthologous group, COG, KO and further identifiers); columns in `DATA_DICTIONARY.tsv` |
| `crosswalk_by_genome.tsv`, `crosswalk_summary.txt` | per-genome and overall counts of Pyrodigal genes, Bakta coding sequences, matched pairs and eggNOG records |
| `annotation_provenance.corrected.tsv` | replaces `functional/annotation_provenance.tsv` inside `refined_functional_tables.tar.gz`, whose `eggnog_version` field holds captured console text; same rows and other fields, with the tool and database versions written out |
| `genome_quality_flags.tsv` | one row per representative: GUNC chimerism status (4,319 pass, 837 flagged, 282 unscored), the probable laboratory contaminant flag (one genome, see below) and the MIMAG boundary case |
| `gunc_progenomes3.tsv` | GUNC v1.1.1 scores against proGenomes 3 for all 12,434 refined bins |
| `sample_ledger.tsv` | every collected specimen entry with site, compartment, campaign role, DNA and sequencing status |
| `specimen_assay_outcomes.tsv`, `amplicon_missingness_by_cause.tsv` | per specimen of the primary sites (2,232): extract, 16S PCR result, 16S profile outcome and shotgun library; and the counts by campaign and cause |
| `library_batches.tsv` | one row per sequenced library (554 shotgun runs, 4 shotgun controls, 1,271 16S profiles): extraction kit, extraction batch (Trips 4 and 5), library kit, sequencing instrument, run, flow cell and lane |
| `combined_samplesheet_accessions.tsv`, `alpha.tsv` | 16S profiles with ENA accessions, and their read depth and alpha diversity |
| `shotgun_cohort_accounting.tsv`, `shotgun_mapping_qc_source.tsv` | membership of each shotgun library in the analysis sets (551, 550, 546, 545, 442, 441) and per-library recruitment of the relative-abundance product (CoverM v0.7.0) |
| `ph_accepted_measurements.tsv` | accepted soil pH measurements (712 specimens) with calibration checks |
| `mixs_fill_counts.tsv` | number of specimens with a value for each MIxS soil checklist term or supporting field |
| `worked_example_10Dr2.py`, `worked_example_10Dr2.expected.txt` | script that follows specimen 10Dr2 to an annotated gene using only files of this deposit, and its expected output |
| `DATA_DICTIONARY.tsv` | field definitions, units and missing-value conventions of the tables |
| `packaging_receipt.json`, `analysis_receipt.json` | integrity receipts of the three archives |
| `SHA256SUMS` | SHA-256 of every file in this deposit |

## Methods summary

Reads were assembled per library with MEGAHIT v1.2.9 (contigs of at least 500 bp),
binned with SemiBin2 v2.2.1 (single-sample and self-supervised) and refined with
DAS Tool v1.1.7. CheckM2 v1.1.0 estimated completeness and contamination. dRep
dereplicated the 12,434 bins with at least 50% completeness and
at most 10% contamination at 95% ANI (fastANI) into 5,438 species
representatives; GTDB-Tk v2.7.2 classified them against GTDB R232. MIMAG tiers:
126 high quality, 5,311 medium quality, and 1 representative at exactly
10% contamination. Bakta v1.12.0 (database v6.0 full) predicted genes;
eggNOG-mapper v2.1.13 (eggNOG v5.0.2, DIAMOND v2.0.15) assigned KOs, CAZy
families, Pfam domains and preferred names. Bowtie2 v2.5.1 (`--very-sensitive`,
first 200 million read pairs) mapped each library to a reference of all refined
contigs, each prefixed with its genome identifier; CoverM v0.6.1 genome mode
counted reads at 95% identity or more. Code and validation:
https://github.com/bio-ontology-research-group/empty-quarter-ecology-data
(`scripts/release/`, `evidence/mag-catalogue-20261024/`).

## Known issues and flags

- `V42PRr2__single_SemiBin_33` (*Escherichia coli*, GCA_990088080, the only representative of
  this species) is flagged as a probable laboratory contaminant. It was assembled from a Trip 5
  root-adjacent library. The Trip 5 positive standard yielded *E. coli* only, and its reads cover
  94.0% of this genome (2 million read pairs, alignments of at least 95% identity). The genome
  stays in the archive so that the deposit matches the ENA records; exclude it from ecological
  analyses (`probable_laboratory_contaminant = 1` in `genome_quality_flags.tsv`).
- 837 representatives are flagged and 282 are unscored by the GUNC chimerism screen. They are
  kept for read recruitment; use `gunc_status` to restrict gene-content analyses.
- `functional/annotation_provenance.tsv` inside `refined_functional_tables.tar.gz` has console
  text in its `eggnog_version` field. Use `annotation_provenance.corrected.tsv`.
- Gene sets: the Bakta annotation has 19,185,632 coding sequences. The crosswalk uses 20,451,986
  genes predicted by Pyrodigal v3 in single-genome mode on the same genomes; 18,187,942 Bakta
  coding sequences match one of them (same coordinates or same stop codon).
- Two mapping products exist. `refined_coverm_profiles.tar.gz` (Bowtie2 and CoverM v0.6.1, reads
  at 95% identity or more, every genome reported) is the depth and breadth product.
  `shotgun_mapping_qc_source.tsv` reports recruitment of the relative-abundance product
  (CoverM v0.7.0 with minimap2, genomes below 10% covered fraction set to zero), which recruits a
  median of 3.6 percentage points more reads per library.
- Compartment labels: "Deep" (code D) is shallow subsurface soil, "Rhizosphere" (code PR) is
  root-adjacent soil, "Surface" (code S) is surface soil.
- `library_batches.tsv`: Trips 1 to 3 have no extraction-day batches; 32 Trip 1 and one Trip 4
  shotgun library have no extraction kit on record. Trip 3 library preparation dates carry a
  wrong year in the source sheet; use day and month.

## Worked example

```bash
tar -xf gene_crosswalk.tar crosswalk/10Dr2.tsv.gz
python3 worked_example_10Dr2.py . > output.txt
diff worked_example_10Dr2.expected.txt output.txt
```

The script needs Python 3.6 or later and no packages. It follows specimen 10Dr2 to its 16S
profile and shotgun library, the most abundant genome in that library, one gene of that genome
with its annotation, and the soil pH of the same tube.

## How to cite

Cite this deposit by its DOI and version, and the accompanying data descriptor.

## Related ENA records

ENA study PRJEB125153 (ERP204894) holds the 554 read runs, 549 primary
assemblies, 12,434 binned metagenomes and 5,437 MAGs (public from
2026-11-25). `48Dr2__self_SemiBin_25` is at ENA as a binned metagenome only,
because ENA admits MAGs below 10% contamination. This deposit contains all
5,438 representatives.

## Licence

Project-authored data in this deposit are licensed under CC BY 4.0
(https://creativecommons.org/licenses/by/4.0/). Taxonomic lineages derive from
GTDB release R232; functional identifiers derive from KEGG, CAZy, Pfam and eggNOG,
which retain their own terms. Raw reads at ENA retain their own access conditions.
