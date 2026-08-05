# Manuscript sources

`sn-article.tex` and `supplement.tex` are the only manuscript roots. The other
TeX files are included from those roots. `sn-article.pdf` and `supplement.pdf`
are the locally validated builds corresponding to the committed sources.

Build both documents from this directory with:

```bash
latexmk -pdf -interaction=nonstopmode -halt-on-error sn-article.tex
latexmk -pdf -interaction=nonstopmode -halt-on-error supplement.tex
```

The Springer Nature class and bibliography styles are included unmodified for
compilation convenience and retain their original terms.
