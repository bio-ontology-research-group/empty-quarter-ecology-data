# Author control confirmation, 31 August and 6 September 2026

Source: Rund Tawfiq (laboratory lead for Trips 1-3 extractions and 16S
library submission), emails to Robert Hoehndorf of 31 August 2026 11:47 and
6 September 2026 14:11 in the thread "Empty Quarter controls: Trips 1-3
extraction days, PCR blanks and control library roles", checked against her
sample-tracking sheet (Google Sheets, "Empty Quarter Samples"; identical to
the `dna_kit` column of `data/release/sample_ledger.tsv` for all 642
overlapping samples). Analysis checks: `analysis/rerun-controls-2026-08-30/`
in the ecology repository (14 re-denoised control libraries) and the
nearest-neighbour comparison of 6 September 2026 (ecology ledger).

## Confirmed by the laboratory

- Trips 1-3 extraction blanks were processed per extraction kit, not per
  extraction day: one for PowerLyzer PowerSoil, one for DNeasy PowerSoil Pro.
  Extractions were repeated; Trips 1 and 2 were extracted on the same days;
  nothing was sequenced on extraction days. No day-linked blank exists.
- Only the PowerSoil Pro kit blank was sequenced: Extraction-Ctrl-Pro-Trip1,
  M-25-0929, Qubit 1.11 ng/uL at library submission. The PowerSoil kit blank
  is in the laboratory sample record but on no sequencing sample sheet.
- M-25-0929 carried UDP0383 on the original submission sheet and UDP0384 on
  the re-run sheet, where UDP0383 belongs to M-25-0928 (60Dr3). It sits in the
  re-run series directly after M-25-0925..0928 (57PRr1, 57Sr2, 60Dr2, 60Dr3).
- Trip 1 "- Ctrl 1" (UDP0371, M-25-0323, Ctrl-1-Trip1) was prepared as
  negative control 1: soil treated with UV for more than two hours. Qubit
  25.70 ng/uL on the submission sheet; the exchange happened before
  quantification (physical swap or mislabelling in the laboratory, not at
  indexing or demultiplexing).
- Trip 1 "Ctrl 2" (UDP0372, M-25-0553) and "Ctrl 3" (UDP0373, M-25-0554):
  Qubit 3.89 and 18.99 ng/uL; not a matched pair of the same material;
  contents not resolved by the laboratory.
- Trip 1 "PCR Ctrl" (UDP0374, M-25-0555, PCR-Ctrl-Trip1): nuclease-free water
  PCR control, Qubit 1.51 ng/uL.
- Trip 3: one PCR blank, index pair xGen 10nt UDI 728 = M-23-8667 PCRCtrl,
  sequenced on the Trip 3 run (NovaSeq 6000 A01018 run 321, flowcell
  HVJY5DRX3) with all Trip 3 libraries. "- Ctrl 1" (M-23-8672, FNegCtrl1) and
  "- Ctrl 2" (M-23-8676, FNegCtrl2) are UV-treated soil negatives; "- Ctrl 3"
  (M-23-8649, "-Ctrl3") is negative control 3 of the same set and kept its
  raw name. Trip 3 M-numbers map onto the laboratory sheet in order.
- Trip 3 "+ Ctrl 1" (M-23-8294, FPosCtrl1): the sheet records index pair 374
  at well 1H, which is not possible; it is on a different index plate and has
  a 550 bp rather than 500 bp fragment size. Data-entry error, unresolved.

## Analysis result recorded with the confirmation (6 September 2026)

- M-25-0929 is neither a copy of 60Dr3 (Bray-Curtis 0.944) nor a mixture of
  M-25-0925..0928 (0.925-0.981). Its nearest canonical profile is
  e0917_46Dr1 (M-25-0917, same re-run series, UDP0352): Bray-Curtis 0.389
  (Trip 1 same-site, same-compartment replicate pairs: median 0.528), with
  97.8 % of 46Dr1 reads in ASVs shared with the blank. The blank is
  contaminated with soil template and is not used as an extraction blank.
- Ctrl-2 and Ctrl-3 versus the Trip 2 negatives Neg-Ctrl-1-Trip2 and
  Neg-Ctrl-2-Trip2: Bray-Curtis 0.74-0.75 (Ctrl-2) and 0.45-0.53 (Ctrl-3);
  the two Trip 2 negatives differ by 0.28. Consistent with soil negatives,
  not asserted.

## Registry consequence

Labelled roles in `metadata/controls/` and `ontology/rubalkhali_controls.ttl`
are unchanged. e0323_Ctrl_1_Trip1 stays unpromoted (its recorded role is
negative; its content is the D6322 standard). e0929_Extraction_Ctrl_Pro_Trip1
keeps the extraction-blank role but is characterization-only. e8294_FPosCtrl1
keeps the positive role with unresolved identity. The manuscripts describe
these facts in Methods (data descriptor) and Supplementary Section S2
(ecology paper).
