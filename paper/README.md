# Manuscript sources: Rub' al-Khali Data Descriptor

`sn-article.tex` and `supplement.tex` are the manuscript roots. The other
TeX files are included from those roots. `sn-article.pdf` and `supplement.pdf`
are the validated builds corresponding to the sources.

Build both documents from this directory with:

```bash
latexmk -pdf -interaction=nonstopmode -halt-on-error sn-article.tex
latexmk -pdf -interaction=nonstopmode -halt-on-error supplement.tex
```

The Springer Nature class and bibliography styles are included unmodified for
compilation convenience and retain their original terms.

## Data Foundation & Release Products

- **Representative Genomes**: 5,438 species representatives (126 high-quality, 5,311 strict medium-quality, 1 boundary representative at 10.0% contamination).
- **Knowledge Graph**: KG v3.0.1 (45,707,660 triples across 16 RDF modules), archived at Zenodo (10.5281/zenodo.23134168).
- **Gene Calling & Annotations**: Bakta/eggNOG release (`EQ-PROT-BAKTA-v1.0.0`, 19,186,792 proteins) and companion Pyrodigal representative proteins (`EQ-PROT-PYRODIGAL-REP-v1.0.0`, 20,451,986 proteins).
- **Genome-Resolved Traits**: microTrait profile product `EQ-MICROTRAIT-REP-v1.0.0` covering all 5,438 representative genomes with fresh Prodigal v2.6.3 calls, 37/100/189-category trait matrices, continuous predictions, rule and model matrices, and safe-interpretation flags for assayed models (distinguishing missing aphA/phoN models). Distributed through institutional bulk storage alongside compact reproducibility tables; separate from KG v3.0.1 without repository deposition claim.
