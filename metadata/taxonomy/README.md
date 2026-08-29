# Taxonomy artifact status

This directory intentionally retains both the current Trips 1–5 artifacts and
older or derived tables needed to audit previous analyses. Presence in this
staging directory does not make a file a canonical release input.

| File | Status | Scope | SHA-256 |
|---|---|---|---|
| `feature-table-trips1-5.tsv` | canonical-candidate | 1,271 profiles; 1,242 normalized field identifiers | `129f47d8f0db8d9afd6f8c67b8d80b5bead90155d8c91d2f43ea6a4139b0cb12` |
| `taxonomy-trips1-5.tsv` | canonical-candidate | Taxonomy assignments paired with the Trips 1–5 feature table | `fcf0a3ea0ca8ed956532fb4d7bffa0c20249e3048779a219155cc1bb7e483d35` |
| `ASV_seqs-trips1-5.fasta` | canonical-candidate | ASV sequences paired with the Trips 1–5 feature table | `7b2b6f23a0d80ca004f730b164b9b9b4514aafcb23f8e2019e1d2d3216b88854` |
| `feature-table.tsv` | legacy-excluded | Older 1,013-profile table; 984 normalized field identifiers | `0d13260637e4974072f9efbfad9518a83dfea89cbda2a4a573641fde8dea1b78` |
| `taxonomy.tsv` | legacy-excluded | Taxonomy assignments paired with the older feature table | `5cbca6e9904ffe395fe2e4215f6005622e47a9af71528c209398a22669c3b5db` |
| `feature_table_filtered_normalized.tsv` | derived-review-required | Supporting normalized table; 531 profiles | `df5bfbcf21c14c257128294d66a80fcc27e6002c2c8b397bf3a71f3250d60a3e` |
| `feature_table_filtered_raw_w_reps.tsv` | derived-review-required | Supporting raw filtered table; 975 profiles | `cdf236fdeb5f539c6d39cb7f2c48f0aa5e83e82a0f06bd267f91545f63b769a6` |
| `unique_taxa.txt` | derived-review-required | Supporting taxon list | `039b8be31e81b49a5fa6237fad281149f8ebb9b40cbfdee51064e4fe2187af9d` |

`canonical-candidate` means the artifact is the current pre-release source but
is not yet frozen. `legacy-excluded` means the file is preserved for
provenance and must not be selected by the canonical workflow or counted in
release totals. `derived-review-required` means that inclusion requires an
explicit generating process, source inputs, parameters, and QC disposition in
the final manifest.

The canonical feature table is byte-identical to
`data/processed/taxonomy/taxon-tables/feature-table-trips1-5.tsv` in the
working repository at the time of staging. The frozen release workflow must
recheck every checksum and reject any use of the two legacy files as canonical
inputs.
