# `_gtdbtk_r232` — the R232 taxonomy input for the 5,438 species representatives

**STATUS: DONE / IN USE 2026-08-17.** This is the taxonomy every downstream census now reads.

## What this is
`gtdbtk.bac120.summary.tsv` (4,847 rows) + `gtdbtk.ar53.summary.tsv` (591) = **5,438 = the catalogue,
exactly**. Rows and header are copied **verbatim** from the GTDB-Tk **2.7.2 / R232** run at
`rebuild_20260729/coassembly_novelty/legacy_taxonomic_screen_r232/gtdbtk_2.7.2_r232/run/`, subset to our
reps. Nothing is reformatted or synthesised. Builder: `make_r232_rep_subset.sh` (re-runnable, fails
closed); checksums in `CHECKSUMS.sha256`.

**Why a subset:** the upstream R232 run covers 5,742 genomes — our 5,438 dRep representatives plus 304
LQ-salvage bins that are not in the catalogue. Consumers carry `assert len(tax)==5438`, so they need the
catalogue's rows only. Ground truth for "our reps" = `_drep/out/dereplicated_genomes/` (5,438 `.fa`).

## Why it exists
Alejandra, 2026-08-17: **the paper uses R232 throughout; r226 was an error.** Eight scripts had been
reading `05_refine/_gtdbtk_refined/` — the GTDB-Tk **2.4.1 / r226** run — and three of them even said
"R232" in their docstrings, which is what hid it. All 17 taxonomy paths in those eight were repointed
here (fam_9_phylum.sh · osmo_{1,6,7} · uv_1_census · amr_{1,3} · bgc_1_census), and those eight plus
five downstream scripts were rerun. Jobs 50630897, 50630898.

## Effect on the paper — ONE claim moved
§2.3's within-phylum photolyase control now replicates in **three** phyla (Actinomycetota p=0.0014,
Pseudomonadota p=0.020, Bacillota p=0.021), not four: **Bacteroidota falls to p=0.30**, because the
r226→R232 `Bacteroidota_A`→`Bacteroidota` merge adds 107 representatives and dilutes the effect.

**Everything else is unchanged, verified not assumed:** pathogen census still 2 named species (0.037%),
AMR 37.40%, arsenic 17.34%, mercury 7.52%, BGC 97.48% / 44,002 regions / 85.29% edge, NHEJ 74.5%,
§1.4 97.9% single-phylum of 78,727 (Actinomycetota 32.1% / Thermoplasmatota 19.4%), Halobacteriota salt
turnover S rho=+0.451 p=7.4e-14. Rep-level phylum renames are only Myxococcota→Myxococcota_A (121),
Bacteroidota_A→Bacteroidota (107), Bacillota→Bacillota_I (11), Desulfobacterota_B/I→Desulfobacterota (7),
JAWLBW01→J088 (1). Actinomycetota and Thermoplasmatota are untouched, so §1.4's leaders could not move.

## Do not
- Do **not** point anything back at `_gtdbtk_refined/` — that is r226 and superseded for taxonomy.
- Do **not** regenerate this by reformatting `per_genome_taxonomic_screen.tsv`; use the native run output.
- Do **not** "correct" the site count 60 → 61. 61 counts field-notebook labels. See CORRECTIONS 2026-08-17.

Shipped: Overleaf `8a59de5` / GitHub `cd83b4f`. Full record: repo `notes/CORRECTIONS.md` 2026-08-17.
