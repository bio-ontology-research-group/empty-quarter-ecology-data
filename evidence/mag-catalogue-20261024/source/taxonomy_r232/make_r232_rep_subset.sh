#!/bin/bash
# Build the R232 taxonomy input for the 5,438 species representatives.
#
# WHY: eight analysis scripts (darkfam_basis_clean/fam_9, osmolyte_clean/osmo_{1,6,7},
# uv_survival_clean/uv_1, resistome_clean/amr_{1,3}, bgc_clean/bgc_1) read taxonomy from
# 05_refine/_gtdbtk_refined/, which is the GTDB-Tk 2.4.1 / **r226** run -- three of them even say
# "R232" in their docstrings, which is what hid the error.  Decision 2026-08-17 (Alejandra): the paper
# uses **R232** throughout; r226 was a mistake.
#
# WHAT: the authoritative GTDB-Tk 2.7.2 / R232 classify already exists, but it covers 5,742 genomes --
# our 5,438 dRep representatives PLUS 304 LQ-salvage bins that are not in the catalogue.  This script
# subsets it to exactly the 5,438, keeping GTDB-Tk's own file names, header and rows VERBATIM, so the
# eight consumers need only their directory path repointed: no format conversion, no synthesised
# values, and their `assert len(tax)==5438` guards keep working.
#
# Ground truth for "our reps" = the dRep output directory (one .fa per representative).
set -euo pipefail
M=/ibex/scratch/projects/c2014/rob/metagenomics
SRC=$M/rebuild_20260729/coassembly_novelty/legacy_taxonomic_screen_r232/gtdbtk_2.7.2_r232/run
REPS=$M/05_refine/_drep/out/dereplicated_genomes
OUT=$M/05_refine/_gtdbtk_r232

find "$REPS" -maxdepth 1 -name '*.fa' -printf '%f\n' | sed 's/\.fa$//' | sort -u > "$OUT/rep_ids.txt"
n_reps=$(wc -l < "$OUT/rep_ids.txt")
[ "$n_reps" -eq 5438 ] || { echo "FAIL: expected 5438 reps, got $n_reps" >&2; exit 1; }

for f in gtdbtk.bac120.summary.tsv gtdbtk.ar53.summary.tsv; do
  awk -F'\t' -v ids="$OUT/rep_ids.txt" '
    BEGIN { while ((getline l < ids) > 0) keep[l]=1 }
    FNR==1 { print; next }
    ($1 in keep) { print }
  ' "$SRC/$f" > "$OUT/$f"
  echo "$f: $(($(wc -l < "$OUT/$f") - 1)) rows kept of $(($(wc -l < "$SRC/$f") - 1))"
done

kept=$(( $(wc -l < "$OUT/gtdbtk.bac120.summary.tsv") + $(wc -l < "$OUT/gtdbtk.ar53.summary.tsv") - 2 ))
[ "$kept" -eq 5438 ] || { echo "FAIL: kept $kept rows, expected 5438" >&2; exit 1; }
echo "TOTAL kept: $kept  (= the catalogue, exactly)"
sha256sum "$OUT"/gtdbtk.*.summary.tsv > "$OUT/CHECKSUMS.sha256"
