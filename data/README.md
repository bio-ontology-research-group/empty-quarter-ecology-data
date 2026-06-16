# Source data

This directory holds the **small** source metadata vendored directly in the
repository. Large inputs and the generated knowledge graph are archived on
**Zenodo** and linked below — they are intentionally excluded from git (see the
root `.gitignore`).

## In this repository (`data/metadata/`)

| Subdirectory | Contents |
|--------------|----------|
| `samplesheets/` | Per-expedition sample sheets (`trip1-2023.tsv` … `trip5-2025.tsv`): site, date, coordinates, field conditions. |
| `samples/` | Master sample metadata and plant inventory. |
| `geodata/` | GPS coordinates, altitudes, site↔trip mapping. |
| `xrf/` | XRF field measurements and lab results. |
| `geochemistry/` | Processed XRF tables (field, lab, filtered). |
| `climate/` | Open-Meteo climate data (monthly averages, daily weather). |
| `QC_reads/` | MultiQC outputs for sequencing quality. |
| `sra-submissions/` | ENA/SRA submission sheets linking samples to run accessions. |
| `protocols/` | DNA extraction / library prep / sequencing / measurement protocols. |
| `taxonomy/` | **Small** taxonomy files only: `unique_taxa.txt`, `taxonomy.tsv` (the assignment table). The large feature tables and ASV FASTA are on Zenodo. |

## On Zenodo (not in git)

> **DOI:** _to be assigned upon publication_ — add the resolved DOI here and in
> `paper/04_data_records.tex` (currently a `\todo`) and `README.md`.

The Zenodo deposit (`zenodo/` staging bundle in the parent project, ~6 GB)
contains:

- **Generated knowledge graph** (`ontology/`): `rubalkhali_*.owl` modules and the
  1.1 GB `rubalkhali_taxonomy_abox.ttl` (1,401,008 taxon-abundance observations),
  plus the aligned NCBI taxonomy and ecosystem modules.
- **Large taxonomy inputs** (`metadata/taxonomy/`): `feature-table-trips1-5.tsv`
  (~1.7 GB), `feature-table*.tsv`, `ASV_seqs-trips1-5.fasta` (~155 MB),
  `taxonomy-trips1-5.tsv`.

To regenerate the KG locally, download these into the matching paths under
`data/metadata/taxonomy/` and follow [`../REPRODUCE.md`](../REPRODUCE.md).

## Other primary sources

- **Raw sequencing reads:** European Nucleotide Archive — `PRJEB104209`
  (umbrella project), `PRJEB106069` (amplicon).
- **Live knowledge graph:** https://rubalkhali.science/sparql (SPARQL),
  https://rubalkhali.science/ (web portal).
