# Superseded preliminary contaminant screen

The four data files in this directory preserve the first pooled prevalence
screen for audit history. They are **not** the control analysis reported in
either manuscript and must not be used as the canonical filtered table.

That preliminary screen treated all 24 name-selected `EB*` and `Negative*`
profiles as exchangeable controls, had no extraction-batch mappings, and
identified 14,822 candidate features. The author-confirmed, assay-aware audit
supersedes it. The current analysis:

- trains only on the 17 mapped Trip 5 16S extraction blanks, EB1--EB17;
- never trains on positive controls;
- applies its 351-ASV candidate set only to the 217 biological profiles linked
  to those extraction batches; and
- reruns 25 headline ecological metrics.

Use `../control-audit/` for the current audit and `../control-sensitivity/` for
the before/after ecological results. The preliminary files remain here only to
make the evolution of the analysis transparent.
