---
id: amplicon_lib_prep
category: lib_prep
version: 1.0
kits:
  name: Multiplex PCR kit
  vendor: QIAGEN
  catalog: 206143
primers:
  forward: Bakt_341F
  reverse: 806R
region: V3-V4
---

# 16S amplification of V3-V4 region

**Source:** [manufacturer protocol link](https://support.illumina.com/documents/documentation/chemistry_documentation/16s/16s-metagenomic-library-prep-guide-15044223-b.pdf)

**Notes for this project:**

- Primer sequences used:  
  - Bakt_341F: CCTACGGGNGGCWGCAG  
  - 806R: GGACTACNVGGGTWTCTAAT  
- Both primers were used with Illumina overhang adapter sequences.
- Template was amplified with the QIAGEN Multiplex PCR Kit under these conditions:  
  - Initial activation: 95 °C for 15 min  
  - 35 cycles of:  
    - Denaturation: 94 °C for 30 s  
    - Annealing: 57 °C for 90 s  
    - Extension: 72 °C for 90 s  
  - Final extension: 72 °C for 10 min
