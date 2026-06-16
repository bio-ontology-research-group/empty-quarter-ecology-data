# Reproducing the Rub' al-Khali knowledge graph

This document describes how to regenerate the Empty Quarter knowledge graph from
source metadata, validate it, and reproduce the figures/tables/benchmarks in the
paper. It is self-contained: everything except the multi-GB source tables and
generated artifacts (which are on Zenodo) lives in this repository.

## 1. What you need

### Software

| Tool | Version | Used for |
|------|---------|----------|
| Java | 11+ | runs Groovy |
| Groovy | 4.x (`@Grab` for deps) | RDF generators, validators, alignment |
| OWL API | 5.1.20 | OWL/RDF generation |
| ELK reasoner | 0.4.3 | consistency + classification |
| Apache Jena | 4.10.0 | ShEx validation |
| OpenLink Virtuoso | 7.x | triple-store deployment + SPARQL |
| Python | 3.10+ (`uv` recommended) | table generators, benchmarks |
| Docker + Docker Compose | recent | local Virtuoso + portal (via `manage.sh`) |
| TeX Live | 2023+ | compiling the manuscript |

Groovy scripts resolve their own dependencies via `@Grab`, so no manual Maven
setup is required.

### Data

Small source metadata is vendored in [`data/metadata/`](data/metadata/). The
large inputs and the generated knowledge graph are archived on Zenodo (DOI
pending — see [`data/README.md`](data/README.md)). Download and place them as:

```
data/metadata/taxonomy/feature-table-trips1-5.tsv   # ~1.7 GB, from Zenodo
data/metadata/taxonomy/ASV_seqs-trips1-5.fasta      # ~155 MB, from Zenodo
data/metadata/taxonomy/feature-table*.tsv           # from Zenodo
```

The pre-generated OWL/TTL modules (`rubalkhali_*.owl`, the 1.1 GB
`rubalkhali_taxonomy_abox.ttl`, etc.) are also on Zenodo if you prefer to load
the KG directly without regenerating.

## 2. Regenerate the OWL modules

The Groovy generators in [`rdf/generators/`](rdf/generators/) transform source
metadata into OWL/RDF. Run them in dependency order (this is exactly what
`rdf/manage.sh update` orchestrates):

1. `update_rubalkhali_ontology.groovy` — base ontology (TBox)
2. `generate_site_ontology.groovy` — sites
3. `generate_samples_abox.groovy` — samples
4. `generate_measurements_abox.groovy` — environmental + climate measurements
5. `generate_xrf_abox.groovy` — XRF analyte concentrations
6. `generate_dna_abox.groovy` — DNA extracts
7. `generate_sra_abox.groovy` — sequencing runs / ENA accessions
8. `generate_qc_abox.groovy` — sequencing QC metrics
9. `generate_taxonomy_abox.groovy` — taxon abundance ABox
10. `MapToEcosystem.groovy` — unified ecosystem ontology mapping

> **Convention checks:** the XRF generator and the TBox script both iterate
> `rdf/config/codes/xrf_chemical_mapping.yml` and **must** skip the `LE`
> (Light Elements) entry, or all analyte labels shift by one (Si↔Fe). The
> measurement reification follows the SIO four-individual split. See
> [`CLAUDE.md`](CLAUDE.md) for the full set of invariants.

## 3. Load + validate

```bash
cd rdf
./manage.sh reset        # wipe DB, regenerate every module, rebuild, reload
./manage.sh validate     # full validation suite
```

The validation suite ([`rdf/validation/`](rdf/validation/)):

- `validate_rdf.groovy` — ShEx structural validation against [`rdf/shex/`](rdf/shex/)
- `validate_consistency.groovy` — OWL consistency (ELK)
- `verify_xrf_integrity.groovy`, `validate_xrf_*` — XRF data integrity
- `validate_taxonomy_*` — taxon abundance value/abundance checks
- `test_sparql_queries.groovy` — competency-question regression tests

## 4. Reproduce paper tables, benchmarks, and stats

```bash
# LaTeX tables (write into paper/)
python scripts/generate_env_table.py      # -> paper/env_table.tex
python scripts/generate_xrf_table.py      # -> paper/xrf_table.tex (run from repo root)

# Live statistics from a running SPARQL endpoint (localhost:8895)
python scripts/get_stats.py

# Benchmarks reported in metrics/
python scripts/benchmark_cqs.py           # competency-question latencies
groovy scripts/benchmark_elk.groovy       # ELK classification timing
```

Benchmark outputs in [`metrics/`](metrics/) are the exact values cited in the
paper.

## 5. Compile the manuscript

```bash
cd paper
pdflatex sn-article.tex && bibtex sn-article && pdflatex sn-article.tex && pdflatex sn-article.tex
pdflatex supplement.tex
```

Journal variants live under `paper/variants/` (GigaScience data note, SWJ
knowledge-graph article).
