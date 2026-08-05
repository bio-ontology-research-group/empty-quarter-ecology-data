# Sequencing-control evidence

`control_ground_truth.tsv` is the current provenance-bearing control record.
It freezes the author-confirmed product, preparation stage, assay, and
applicability facts without inferring a trip from an extraction-blank label:

- Trips 1 and 2 used purified-DNA ZymoBIOMICS HMW DNA Standard D6322.
- Trip 3 used whole-cell ZymoBIOMICS Microbial Community Standard D6300.
- Trip 4 had no positive control.
- Trip 5 used D6300, but its positive and negative control pair was sequenced
  by shotgun metagenomics rather than 16S.
- EB1-EB18 and Negative1/2/4-7 are 16S extraction blanks. EB1-EB17 have
  extraction-batch mappings; the other seven are characterization-only.
- Extraction blanks belong to an extraction day or batch, not directly to a
  field trip. One extraction day can contain samples from several trips.
- PCR blanks and extraction blanks are distinct negative-control roles.
- Three paired 16S libraries with explicit PCR or NTC labels and one Trip 4
  workbook record already bear PCR-blank roles. Complete mapping of reused or
  generic labels to PCR batches awaits laboratory confirmation.
- No sterile-bag field-blank instance is asserted because no inventory record
  is available.

The files dated 2026-07-29 in this directory are retained as historical audit
evidence. Their preliminary product candidates and statements that composition
was pending are superseded by `control_ground_truth.tsv`; they must not be used
as the current control design. In particular, the archive title that mentioned
D6305 does not override the author-confirmed D6322 assignment for Trips 1 and
2.

Current normalized control records are in `../../metadata/controls/`. The
generated SIO-patterned graph is
`../../ontology/rubalkhali_controls.ttl`; its ShEx contract is
`../../shex/controls.shex`. The assay-aware negative- and positive-control
audit is in `../control-audit/`, and the 25 before/after ecology comparisons
are in `../control-sensitivity/`.

The control analysis follows three constraints:

1. positive controls are evaluation-only and never train the contaminant
   classifier;
2. a negative control is used only for a compatible assay and processing
   stage; and
3. candidate removal is a bounded sensitivity analysis, not a replacement for
   the unfiltered canonical feature table.

At the primary setting, 351 of 351,472 ASVs are blank-enriched. Removing them
only from the 217 biological profiles mapped to Trip 5 EB1-EB17 removes
2.19% of reads in aggregate (median 0.403%; maximum 56.6%). All 25 tracked
ecology verdicts remain stable. Remaining limitations include one unsequenced
Trip 4 blank affecting all or part of 23 sites, no Trip 5 16S positive
control, absent DNA concentrations, and the missing sterile-bag inventory.
The complete PCR-blank library-to-batch map is tracked separately as a
resolvable laboratory-confirmation task.
