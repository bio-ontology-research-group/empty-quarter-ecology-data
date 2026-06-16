# Empty Quarter — Data Descriptor Paper

This repository contains the manuscript, reproduction code, and source metadata
for the data-descriptor paper:

> **A formal knowledge base for metagenomics and geochemistry of the Rub' al Khali desert**

It accompanies the **Empty Quarter** knowledge graph — a semantic integration of
geochemistry (XRF), environmental metadata, DNA/sequencing records, and 16S
taxon-abundance data from soil samples collected across the Rub' al-Khali
(Empty Quarter) desert.

The knowledge graph itself, its full ETL pipeline, and the web portal are
developed in the parent repository:
**https://github.com/bio-ontology-research-group/empty-quarter**

This repository is the self-contained, citable companion to the *paper*: it holds
everything needed to compile the manuscript and to regenerate the knowledge
graph from source metadata, while the multi-GB generated artifacts are archived
on Zenodo (see [`data/README.md`](data/README.md)).

---

## Repository layout

| Path | Contents |
|------|----------|
| [`paper/`](paper/) | LaTeX sources for the manuscript (Springer Nature `sn-jnl` class), supplement, journal variants (GigaScience, SWJ), bibliography, figures, and the built PDFs. |
| [`rdf/`](rdf/) | Ontology engineering + RDF generation: hand-authored TBox modules (`ontology-src/`), Groovy ABox generators (`generators/`), the taxonomy-alignment pipeline, ShEx schemas, SPARQL/competency-question docs, config codes, and the `manage.sh` build orchestrator. |
| [`scripts/`](scripts/) | Helper scripts that produce paper artifacts — LaTeX table generators and the competency-question / ELK benchmarks. |
| [`data/`](data/) | Small source metadata (sample sheets, climate, XRF, geochemistry, QC, SRA submissions, protocols). Large tables and the generated KG are linked to Zenodo — see [`data/README.md`](data/README.md). |
| [`metrics/`](metrics/) | Benchmark result tables reported in the paper (CQ latencies, ELK classification, materialization, Virtuoso state). |

## Quick start

### Build the manuscript

```bash
cd paper
pdflatex sn-article.tex && bibtex sn-article && pdflatex sn-article.tex && pdflatex sn-article.tex
pdflatex supplement.tex          # supplementary tables
```

The built PDFs (`paper/sn-article.pdf`, `paper/supplement.pdf`) are committed for
convenience.

### Regenerate the knowledge graph

See [`REPRODUCE.md`](REPRODUCE.md) for the full pipeline (Groovy/OWL API → OWL
modules → Virtuoso → validation). In short, from source metadata in `data/` plus
the large tables from Zenodo:

```bash
cd rdf
./manage.sh reset        # wipe + regenerate all OWL modules and reload the triple store
./manage.sh validate     # run the ShEx / consistency / competency-question suite
```

## Live resources

- **SPARQL endpoint:** https://rubalkhali.science/sparql
- **Web portal:** https://rubalkhali.science/
- **Source code (full project):** https://github.com/bio-ontology-research-group/empty-quarter
- **Raw sequencing data (ENA):** `PRJEB104209` (umbrella), `PRJEB106069` (amplicon)
- **Archived dataset (Zenodo):** DOI pending — see [`data/README.md`](data/README.md)

## Citation

A `CITATION.cff` will be added on acceptance. Until then, cite the manuscript in
`paper/` and the Zenodo deposit (DOI to be assigned).

## License

- **Code** (Groovy generators, Python helpers, validation, build tooling): MIT
- **Data & ontology modules** (`data/`, `rdf/ontology-src/`, Zenodo artifacts): CC-BY 4.0
- **Manuscript** (`paper/`): journal copyright terms; included for review/reproducibility

See [`LICENSE`](LICENSE) for details.

> **Note:** an earlier manuscript draft (`paper/06_usage.tex`) refers to the code
> as GPL-licensed; this repository follows the Zenodo deposit's declared terms
> (MIT code / CC-BY-4.0 data). Reconcile before publication.
