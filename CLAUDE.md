# CLAUDE.md

Guidance for Claude Code (claude.ai/code) when working in this repository.

## What this repository is

The self-contained, citable companion to the **data-descriptor paper**:

> *A formal knowledge base for metagenomics and geochemistry of the Rub' al Khali desert*

It bundles the manuscript, the RDF-generation + ontology code needed to
reproduce the **Empty Quarter** knowledge graph, the small source metadata, and
the benchmark results reported in the paper. Large inputs and the generated KG
(~6 GB) are archived on Zenodo, not in git (see `data/README.md`).

The full project — ETL pipeline, web portal, HPC bioinformatics — lives in the
parent repo: https://github.com/bio-ontology-research-group/empty-quarter

## Layout

- `paper/` — Springer Nature LaTeX manuscript. Primary doc is `sn-article.tex`
  (pulls in `01_introduction.tex` … `06_usage.tex` via `\input`). `supplement.tex`
  builds the supplementary tables; `main.tex` is an older inline draft. Journal
  variants under `paper/variants/` (GigaScience, SWJ). Do **not** edit the
  Springer class/style files (`sn-jnl.cls`, `sn-*.bst`).
- `rdf/` — ontology engineering + RDF generation. See `rdf/README.md`.
- `scripts/` — paper-artifact helpers: LaTeX table generators + benchmarks.
- `data/metadata/` — small vendored source metadata. See `data/README.md`.
- `metrics/` — benchmark result TSVs cited in the paper.

## Build

```bash
# Manuscript
cd paper
pdflatex sn-article.tex && bibtex sn-article && pdflatex sn-article.tex && pdflatex sn-article.tex
pdflatex supplement.tex

# Regenerate / validate the KG (needs Java/Groovy/Virtuoso — see REPRODUCE.md)
cd rdf && ./manage.sh reset && ./manage.sh validate
```

## Helper scripts

Run from the repo root unless noted. Paths assume the in-repo layout
(`data/metadata/…`, output into `paper/`):

```bash
python scripts/generate_env_table.py      # -> paper/env_table.tex
python scripts/generate_xrf_table.py      # -> paper/xrf_table.tex
python scripts/get_stats.py               # live stats from SPARQL endpoint :8895
python scripts/benchmark_cqs.py           # competency-question latencies -> metrics/
```

## Load-bearing invariants (do not break)

- **XRF analyte IRIs.** `rdf/generators/update_rubalkhali_ontology.groovy` and
  `generate_xrf_abox.groovy` both iterate `rdf/config/codes/xrf_chemical_mapping.yml`
  with counters at 100 (quality) / 500 (value) and **MUST skip `LE`** (Light
  Elements, predefined `RAK_0000032/0000033`). Failing to skip causes an
  off-by-one that swaps analyte labels (SiO2↔Fe2O3).
- **Measurement reification (SIO split).** Every measurement uses the canonical
  four-individual pattern. Assert **both** `value SIO_000215 quality` and
  `quality SIO_000216 value` directly — ELK has no inverse-property reasoning,
  and the TBox property chain uses `SIO_000216` as its head.
- **Centralized TBox.** Every RAK class/property used by an ABox generator is
  declared once (label + parent) in `update_rubalkhali_ontology.groovy`; ABox
  scripts only attach instances. Don't reuse IRI ranges across modules.

### Reserved RAK IRI ranges

- `RAK_0000001-0000099` — TBox core (sites, climate, samples, devices,
  processes, sequencing, abundance); DNA conc. quality/value `RAK_0000043/44`.
- `RAK_0000100-0000191` — XRF analyte qualities (one per non-LE analyte).
- `RAK_0000200-0000224` — sequencing QC TBox.
- `RAK_0000251-0000253` — XRF lab protocol subclasses.
- `RAK_0000500-0000591` — XRF analyte measurement-value classes.
- `RAK_2000001-2000099` — properties (`2000021` monthly temp; `2000026` absolute abundance).
- Single-letter individual prefixes `RAK_<L><6-pad>`: `A` agents, `D` devices,
  `E` experiments, `F` fwd primers, `FN` measuring functions, `L`
  protocols/libraries, `P` processes, `R` rev primers, `T` time, `X` per-site
  material. Numeric `4/5/7` prefixes = values/qualities/datasets.
- **Taxonomy ABox** uses dedicated 8-digit-pad letter prefixes: `RAK_V<8>`
  (values), `RAK_Q<8>` (qualities) — disjoint from numeric `4/5` because
  letter ≠ digit.

## Conventions

- **Sample naming by Trip:** Trip 1 no prefix (`61PRr1`), Trip 2 `T`, Trip 3 `F`,
  Trip 4 `S`, Trip 5 `V`. Trip-5 suffixes O/T/R(E) are different
  extraction/library methods, **not** technical replicates.
- **Bibliography:** `paper/sn-bibliography.bib`, style `sn-mathphys-num.bst`.
- **Zenodo DOI** is still a `\todo` in `paper/04_data_records.tex` — fill it in
  on deposit (and in `README.md` / `data/README.md`).

## Licensing note

Code is MIT, data/ontology CC-BY-4.0 (per the Zenodo deposit). An older draft
(`paper/06_usage.tex`) still says GPL — reconcile before publication.
