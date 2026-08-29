# Authoritative submission sources

The Scientific Data submission is built only from these roots:

- `sn-article.tex` for the main article. It includes
  `01_introduction.tex`, `02_methods.tex`, `02_methods_taxonomy.tex`,
  `03_knowledge_representation.tex`, `04_data_records.tex`,
  `05_validation.tex`, and `06_usage.tex`.
- `supplement.tex` for the supplement. It includes `kr_supplement.tex`,
  `env_table.tex`, and `xrf_table.tex`.

`03_knowledge_representation.tex` is a Methods subsection, not a top-level
section: Scientific Data prescribes a fixed section set, so the knowledge
representation is folded into Methods and the six patterns that are not
reproduced in the main text live in `kr_supplement.tex`.
Author Contributions, Funding, Acknowledgements and Competing Interests are
not present as sections and no placeholder text is written for them. They are
author-controlled gates, tracked in `revision/master_revision_ledger.tsv` and
in the readiness report, and are inserted by the corresponding author before
submission.

Both documents use `sn-bibliography.bib`, `sn-jnl.cls`, and
`sn-mathphys-num.bst`. The article's `transect_altitude.png` is a generated
workflow input, rebuilt from `data/metadata/geodata/site_altitudes.tsv` with
an archived profile table, summary, and checksums.
`workflow/bin/build_papers.sh` stages exactly these files, and
`workflow/bin/capture_source_snapshot.py` records only this allowlisted
submission source plus the manuscript checks and published SPARQL query.

The top-level historical `main.tex`, `sn-article-diff.tex`, unused section and
table fragments, `swj/`, and `gigascience/` are retired alternatives. They are
retained for provenance but are not submission sources and must not be used to
derive claims, counts, or a release PDF.
