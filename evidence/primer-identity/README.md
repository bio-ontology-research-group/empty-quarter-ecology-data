# Raw-read primer identity audit

**Status:** the manuscript/SOP reverse-primer record is contradicted by the
raw reads; the executed trimming parameter is supported.

Earlier manuscript and SOP versions named 806R and recorded the Apprill
806RB sequence `GGACTACNVGGGTWTCTAAT`. The combined nf-core command instead uses
`GACTACHVGGGTATCTAATCC`, the Klindworth V3--V4 reverse primer usually named
Bakt_785R (and sometimes informally 805R).

On IBEX, the first 10,000 reads were inspected from each of three biological
R1/R2 files from Trips 1--4 and three from Trip 5. Across the 60,000 R2 reads:

- 56,693 (94.49%) began `GACTAC`;
- 55,057 (91.76%) matched the degenerate Bakt_785R sequence; and
- 11 (0.018%) matched the degenerate Apprill 806RB sequence.

Across the 60,000 corresponding R1 reads, 56,891 (94.82%) matched Bakt_341F.
The few 806RB matches are compatible with chance/error among amplicon
sequences and do not support that oligo as the library primer.

Thus the raw data resolve the identity question: report the actual primer pair
as Bakt_341F (`CCTACGGGNGGCWGCAG`) and Bakt_785R
(`GACTACHVGGGTATCTAATCC`), cite the appropriate source, and correct the SOP.
This audit does not determine whether any upstream processing run used
additional primer trimming beyond the recorded nf-core command.

## Evidence

`primer_counts.tsv` contains per-file counts and `source_paths.tsv` records
the exact frozen path and source-manifest row for each audited read file.
Files were sampled in lexical order within the two recorded raw-read
directories. No raw data were copied from IBEX.

The reviewer-package path for the streaming audit code is
`scripts/analysis/primer_identity_audit.py`; its development-tree source is
`analysis/v3/primer_identity_audit.py`. It was
executed on the IBEX login host because it reads only the first 10,000 records
per file and performs no material computation. A representative reproduction
form is:

```bash
ssh ibex 'python3 - --limit 10000 /absolute/path/sample_R2_001.fastq.gz' \
  < analysis/v3/primer_identity_audit.py
```

The analysis was performed on 28 July 2026.
