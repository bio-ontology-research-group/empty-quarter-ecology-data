# PICRUSt2 Functional Predictions

## Overview

Predicted functional profiles (MetaCyc pathways, EC numbers, KEGG Orthologs) for all five expedition trips, generated with [PICRUSt2 v2.4.1](https://github.com/picrust/picrust2) on the IBEX HPC cluster (Slurm).

## Input Data

PICRUSt2 requires two inputs per run:
- **Representative sequences** (`rep-seq.fasta`) — ASV sequences from DADA2 via nf-core/ampliseq
- **Feature table** (`feature-table.biom`) — ASV abundance table

| Run | Ampliseq results path on IBEX | ASVs |
|-----|-------------------------------|------|
| Trips 1–4 | `novaseq_14_07_25/final_analysis/functional_analysis/PICRUSt2/picrust2_in_clean/` | not recorded |
| Trip 5 | `Trip5/analysis/ampliseq/results_trip5_fixed/qiime2/` | 330,830 |

Trip 5 used `results_trip5_fixed` (the corrected ampliseq run). 484 of 303,922 non-filtered ASVs were above the NSTI cut-off of 2.0 and removed.
The exact Trips 1–4 input files and their checksums were not retained. The
commands and output products are documented, but exact upstream PICRUSt2
re-execution for Trips 1–4 is therefore not claimed.

## Pipeline Steps

Both runs executed the same five-step pipeline:

```bash
# 1. Full pipeline: placement + EC/COG HSP + EC metagenome prediction
picrust2_pipeline.py -i feature-table.biom -s rep-seq.fasta -o picrust2_out -p 36 --verbose

# 2. KO prediction via PIC method (includes confidence intervals)
hsp.py --tree out.tre --output KO_predicted.tsv.gz \
  --observed_trait_table ko.txt.gz \
  --hsp_method pic --edge_exponent 0.5 --seed 100 --processes 36

# 3. EC metagenome prediction (min_reads=100)
metagenome_pipeline.py -i feature-table.biom -m marker_predicted_and_nsti.tsv.gz \
  -f EC_predicted.tsv.gz -o metagenome_out_minR100 --min_reads 100

# 4. KO metagenome prediction (min_reads=100)
metagenome_pipeline.py -i feature-table.biom -m marker_predicted_and_nsti.tsv.gz \
  -f KO_predicted.tsv.gz -o metagenome_out_minR100/KO --min_reads 100

# 5. MetaCyc pathway inference
pathway_pipeline.py -i metagenome_out_minR100/pred_metagenome_unstrat.tsv.gz \
  -o Pathways --intermediate pathways_working -p 36
```

**Note on KO_predicted.tsv.gz file size**: The PIC method (step 2) outputs predicted counts plus upper/lower confidence intervals per ASV, making `KO_predicted.tsv.gz` substantially larger than the EC equivalent.

**SLURM resources**: 36 CPUs, 200 GB RAM, 2-day walltime.

## Output Locations on IBEX

| Trip(s) | PICRUSt2 output path |
|---------|----------------------|
| 1–4 | `/ibex/scratch/projects/c2014/EmptyQuarter_Data/soil/amplicon_16S/novaseq_14_07_25/final_analysis/functional_analysis/PICRUSt2/picrust2_out_clean/` |
| 5 | `/ibex/scratch/projects/c2014/EmptyQuarter_Data/soil/amplicon_16S/Trip5/analysis/functional_analysis/PICRUSt2/picrust2_out/` |

Slurm script for Trip 5: `run_picrust2_trip5.sh` in the Trip 5 PICRUSt2 directory (job ID 45925397).

## Local Data

Downloaded to `data/processed/functional/picrust2/`:

```
picrust2/
├── trips1-4/           # Raw PICRUSt2 output for Trips 1–4
│   ├── EC_predicted.tsv
│   ├── KO_predicted.tsv.gz
│   ├── marker_predicted_and_nsti.tsv.gz
│   ├── out.tre
│   ├── metagenome_out_minR100/
│   │   ├── pred_metagenome_unstrat.tsv      # EC per-sample predictions
│   │   ├── seqtab_norm.tsv.gz
│   │   ├── weighted_nsti.tsv.gz
│   │   └── KO/
│   │       └── pred_metagenome_unstrat.tsv.gz  # KO per-sample predictions
│   └── Pathways/
│       ├── path_abun_unstrat.tsv            # MetaCyc pathway abundances
│       ├── path_abun_unstrat_descriptions.tsv
│       └── path_abun_unstrat_relative_pct.tsv
├── trip5/              # Raw PICRUSt2 output for Trip 5
│   ├── EC_predicted.tsv.gz
│   ├── KO_predicted.tsv.gz
│   ├── marker_predicted_and_nsti.tsv.gz
│   ├── out.tre
│   ├── metagenome_out_minR100/
│   │   ├── pred_metagenome_unstrat.tsv.gz   # EC per-sample predictions
│   │   ├── seqtab_norm.tsv.gz
│   │   ├── weighted_nsti.tsv.gz
│   │   └── KO/
│   │       └── pred_metagenome_unstrat.tsv.gz  # KO per-sample predictions
│   └── Pathways/
│       └── path_abun_unstrat.tsv.gz         # MetaCyc pathway abundances
└── merged/             # All trips merged — use these for analysis
    ├── path_abun_unstrat.tsv       # MetaCyc pathways (462 × 1270)
    ├── ec_metagenome_unstrat.tsv   # EC numbers   (2551 × 1270)
    ├── ko_metagenome_unstrat.tsv   # KOs          (10543 × 1270)
    ├── weighted_nsti.tsv           # NSTI per sample (1270)
    └── sample_metadata.tsv         # Unified sample metadata (see below)
```

## Merged Files

The `merged/` directory is the primary resource for cross-trip analysis. All files share the same 1,270 sample columns. Missing features (functions/pathways absent in one run) are filled with 0.

| File | Rows (features) | Columns (samples) |
|------|----------------|-------------------|
| `path_abun_unstrat.tsv` | 462 MetaCyc pathways | 1,270 |
| `ec_metagenome_unstrat.tsv` | 2,551 EC numbers | 1,270 |
| `ko_metagenome_unstrat.tsv` | 10,543 KOs | 1,270 |
| `weighted_nsti.tsv` | — | 1,270 |

Trip 5 contributed 13 pathways and 108 EC numbers not observed in Trips 1–4.

Generated by `scripts/utils/merge_picrust2.py`.

## Sample Metadata (`merged/sample_metadata.tsv`)

One row per sample column. Generated by `scripts/utils/align_picrust2_metadata.py`.

### Columns

| Column | Description |
|--------|-------------|
| `picrust2_col` | Column name in the merged files (matches exactly) |
| `sample_id` | Canonical sample ID (trip prefix + site + compartment + replicate) |
| `trip` | Expedition trip number (1–5) |
| `site` | Site number within trip |
| `compartment` | `deep`, `surface`, or `plant_rhizosphere` |
| `replicate` | Replicate number (1–3) |
| `extraction_suffix` | Trip 5 only: `O` (original), `T` (alternative method), `R`/`RE` (re-extraction) |
| `biome` | From samplesheet (e.g. `desert biome`) |
| `feature` | Habitat type (see below) |
| `date` | Sampling date |
| `coordinates` | GPS coordinates (decimal degrees) |
| `is_control` | `True` for EB and Negative control samples |
| `duplicate_run` | `True` if this sample was sequenced more than once |

### Sample ID Naming Convention

Sample IDs encode trip, site, compartment, and replicate:

| Trip | Prefix | Example |
|------|--------|---------|
| 1 | *(none)* | `10Dr2` = site 10, deep, replicate 2 |
| 2 | `T` | `T6PRr3` = site 6, plant rhizosphere, replicate 3 |
| 3 | `F` | `F24PRr3` |
| 4 | `S` | `S22PRr1` |
| 5 | `V` | `V45Dr1`, `V16Dr1O` (O/T/R/RE suffix = extraction method) |

Trips 1–4 picrust2 column names have the form `e####_<sample_id>` (e.g. `e0325_10Dr2`) where `####` is a sequencing index.

### Sample Counts

**By trip:**

| Trip | Samples | Date(s) |
|------|---------|---------|
| 1 | 330 | March 2023 |
| 2 | 28 | July 2023 (sites 1–8 only; trip terminated due to extreme heat) |
| 3 | 478 | 2024 |
| 4 | 177 | August 2024 |
| 5 | 257 | October 2025 |
| **Total** | **1,270** | |

**By habitat (excluding controls):**

| Feature | Trip 1 | Trip 2 | Trip 3 | Trip 4 | Trip 5 |
|---------|--------|--------|--------|--------|--------|
| sand dune | 245 | 13 | 373 | 129 | 173 |
| saline pan | 41 | 12 | 49 | 27 | 32 |
| desert oasis | 7 | 0 | 27 | 9 | 7 |
| gravel | 8 | 3 | 10 | 3 | 5 |
| dune slack | 6 | 0 | 9 | 3 | 4 |
| aeolian lake | 8 | 0 | 1 | 3 | 3 |
| oilspill | 4 | 0 | 9 | 3 | 9 |

**By compartment (excluding controls):**

| Compartment | Trip 1 | Trip 2 | Trip 3 | Trip 4 | Trip 5 |
|-------------|--------|--------|--------|--------|--------|
| deep | 110 | 9 | 148 | 59 | 60 |
| plant_rhizosphere | 106 | 13 | 162 | 58 | 143 |
| surface | 114 | 6 | 168 | 60 | 30 |

### Controls

24 control samples are included in the merged files and flagged with `is_control=True`:

- **EB1–EB18** (18 samples): extraction blanks
- **Negative1, 2, 4, 5, 6, 7** (6 samples): extraction blanks

Controls should be excluded for ecological analyses.

### Duplicate Runs

58 rows (29 unique samples) have `duplicate_run=True` — they were sequenced in two separate runs:

- 2 from Trip 2
- 56 from Trip 3

The upstream relationship between each pair is undocumented. The release
therefore retains both profiles and does not prescribe selection or averaging.
