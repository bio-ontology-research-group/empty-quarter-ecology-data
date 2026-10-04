# Library-order neighbour test for processing-batch cross-contamination (2026-09-07)

Decision (Robert Hoehndorf, 7 Sep 2026): the one sequenced Trips 1-3 extraction
blank (M-25-0929, PowerSoil Pro kit blank) carries a soil profile and cannot be
used; test directly whether co-processed Trips 1-3 profiles share DNA, with
Trips 4 and 5 as comparators.

## Method (`batch_adjacency_test.py`)

- Input: canonical `feature-table-trips1-5.tsv` (gzipped copy on Ibex), 1,237
  ecological profiles, relative abundance, Bray-Curtis over all ASVs
  (`outputs/braycurtis_1237.npy`, row order `outputs/braycurtis_profiles.txt`).
- `batch_meta.tsv`: profile, trip, site, compartment, depth, site coordinates
  (data repo `data/metadata/geodata/trip*_geodata.tsv`), library series and
  number (M-number from the July 2025 and Trip 5 samplesheets), DNA
  concentration and kit (`data/release/sample_ledger.tsv`). Trip 2 (24 profiles,
  15 without M-number) and the 29 Trip 3 profiles re-sequenced in the July run
  fall below the 50-profile minimum and are not tested.
- Within each series, profiles are ranked by library number; a pair counts as
  prepared together when ranks differ by at most 2. Different-site pairs only.
  Strata = geographic-distance decile x same-compartment. Statistic = stratum-
  weighted mean of (BC adjacent - BC non-adjacent). Null: 999 permutations of
  library order; one-sided p for adjacent pairs being more similar.
- Per profile: neighbour excess similarity = mean BC to matched non-neighbours
  minus mean BC to neighbours; Spearman against log10 DNA yield (contamination
  would give low-yield profiles a larger excess, i.e. a negative correlation).
- Ibex job 51426151, python/3.9.16 (numpy 1.26.2, scipy 1.11.4), 394 s (7 Sep);
  rerun locally on corrected coordinates 4 Oct 2026 (below).

## Site 52 coordinate correction (4 Oct 2026)

`batch_meta.tsv` was built before data-repository commit a3f1c21 and carried
the Site 53 position for the five Site 52 profiles of Trips 1 and 3
(e0503_52Dr1; e0790_F52Sr2, e8686_F52Sr3, e8736_F52Sr1, e8745_F52Sr2).
`refresh_batch_meta_coordinates.py` rewrites lat/lon from the pinned geodata
(data repository 5a17782) and fails on any other coordinate change. The test
was rerun locally on the pinned canonical table (sha256 129f47d8...):

    python refresh_batch_meta_coordinates.py batch_meta.tsv ../../data/metadata/geodata
    OMP_NUM_THREADS=8 python batch_adjacency_test.py \
        /path/to/data-paper/metadata/taxonomy/feature-table-trips1-5.tsv batch_meta.tsv outputs

(data-paper .venv: Python 3.11, numpy 2.1.3, scipy 1.14.1; log
`outputs/local-rerun-20261004.log`). The Bray-Curtis matrix is identical to
the Ibex run (maximum absolute difference 0). Trips 4 and 5 are unchanged.
Only the geographic-distance strata of Trips 1 and 3 move. Values before the
correction: Trip 1 delta -0.0035, p 0.145, Spearman +0.108 (p 0.095); Trip 3
delta +0.0071, p 0.997, Spearman +0.078 (p 0.117).

## Result (`outputs/batch_adjacency_results.json`)

| trip | series | profiles | adjacent pairs | delta | p (more similar) | Spearman yield vs excess |
|---|---|---|---|---|---|---|
| 1 | July 2025 M-25 | 325 | 318 | -0.003 | 0.145 | +0.11 (p 0.091, n 238) |
| 3 | Trip 3 run M-23 | 449 | 716 | +0.006 | 0.994 | +0.08 (p 0.13, n 401) |
| 4 | July 2025 M-25 | 177 | 177 | +0.016 | 1.000 | no yields in ledger |
| 5 | Trip 5 run M-25 | 233 | 453 | -0.022 | 0.001 | n 11, not computed |

Trips 1 and 3: no excess similarity between co-prepared profiles; low-yield
profiles are, if anything, less similar to their neighbours than high-yield
ones. Trip 5 shows a small batch signal, which is the trip with per-day blanks
and the extraction-blank screen. e0917_46Dr1 (the profile nearest the blank)
is not unusually close to its own library neighbours (see JSON).

Reported in the ecology supplement S2 and the data descriptor Methods.
