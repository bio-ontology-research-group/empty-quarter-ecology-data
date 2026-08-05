---
id: amplicon_lib_prep
category: lib_prep
version: 1.1
kits:
  name: Multiplex PCR kit
  vendor: QIAGEN
  catalog: 206143
primers:
  forward: Bakt_341F
  reverse: Bakt_785R
  reference: Klindworth et al. 2013, Nucleic Acids Research 41:e1, doi:10.1093/nar/gks808
  superseded_reverse: 806R
region: V3-V4
---

# 16S amplification of V3-V4 region

**Source:** [manufacturer protocol link](https://support.illumina.com/documents/documentation/chemistry_documentation/16s/16s-metagenomic-library-prep-guide-15044223-b.pdf)

**Notes for this project:**

- Primer sequences used:  
  - Bakt_341F: CCTACGGGNGGCWGCAG  
  - Bakt_785R: GACTACHVGGGTATCTAATCC
- Both primers were used with Illumina overhang adapter sequences.
- Template was amplified with the QIAGEN Multiplex PCR Kit under these conditions:  
  - Initial activation: 95 °C for 15 min  
  - 35 cycles of:  
    - Denaturation: 94 °C for 30 s  
    - Annealing: 57 °C for 90 s  
    - Extension: 72 °C for 90 s  
  - Final extension: 72 °C for 10 min

## Correction record (version 1.1)

Version 1.0 of this record named the reverse primer `806R` with the sequence
`GGACTACNVGGGTWTCTAAT` (Apprill et al. 2015). That entry is superseded. A
bounded audit of the raw reads streamed the first 10,000 reads from each of
three Trips 1-4 and three Trip 5 biological R1/R2 files and counted primer
matches at the read start:

| Primer | Sequence | Matching reads |
|---|---|---|
| Bakt_341F | `CCTACGGGNGGCWGCAG` | 56,891 / 60,000 R1 (94.82%) |
| Bakt_785R | `GACTACHVGGGTATCTAATCC` | 55,057 / 60,000 R2 (91.76%) |
| Apprill 806RB | `GGACTACNVGGGTWTCTAAT` | 11 / 60,000 R2 (0.018%) |

The reads therefore support the Bakt_341F/Bakt_785R pair of Klindworth et al.
(2013) and reject the recorded 806RB sequence. In the candidate package,
the audit code is `scripts/analysis/primer_identity_audit.py`, its
checksummed outputs are under `evidence/primer-identity/`, and the exact
source paths are recorded without redistributing the raw reads. Development
provenance remains under `analysis/v3/primer_identity_audit.py` and
`analysis/v3/primer_identity_audit/`.

Fields that remain unrecorded for this protocol, and are not inferred here:
the exact index kit and adapter part numbers, the PCR template input mass, and
the number of clean-up and indexing PCR cycles applied after the primary
amplification.
