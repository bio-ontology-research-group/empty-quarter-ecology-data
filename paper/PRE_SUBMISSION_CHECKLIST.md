# Data Descriptor pre-submission checklist

This file holds operational and editorial gates that do not belong in the
submission-facing manuscript. Completed current counts are recorded in
`data/release/release_evidence.json`, the XRF audit, and
`zenodo/PRE_RELEASE_MANIFEST.tsv`.

## Authors and declarations

- Confirm the complete author list, order, and corresponding author.
- Agree and insert CRediT roles for every author.
- Obtain competing-interest declarations from every author.
- Confirm acknowledgements, funders, grant identifiers, and any required
  Ministry wording.

## Sample, sequence, and ecology dispositions

- [x] Encode Trip-1-only numeric identifiers 61–64 through the
  coordinate-confirmed alias ledger. Preserve their source identifiers, map
  them to the four existing named site individuals, and keep them outside the
  repeated-campaign analysis frame.
- [x] Represent the 34 master-sheet controls through the separate SIO-patterned
  control module rather than forcing them through the field-specimen model.
- [x] Encode the control-labelled SRA rows as control sequence occurrences or
  evidence-bearing unresolved dispositions, without inventing field specimens.
- [x] Freeze D6322 for Trips 1 and 2, D6300 for Trips 3 and 5, no Trip 4
  positive, and the Trip 5 shotgun-only control pair. Keep extraction and PCR
  blank roles distinct; link EB1–EB17 to extraction batches rather than trips;
  preserve EB18, Negative1/2/4-7, reused labels and the ambiguous
  `e0323_Ctrl_1_Trip1` polarity as explicit dispositions.
- Retain the documented study limits: the unsequenced Trip 4 blank, no Trip 5
  16S positive, unavailable DNA concentrations and absent sterile-bag
  inventory.
- Obtain laboratory confirmation of the complete PCR-blank library-to-batch
  map, including the biological libraries amplified in each batch. Treat this
  as a resolvable metadata gate, not as an irrecoverable study limitation.
- Record explicit QC reasons for the nine biological profile identifiers and
  the additional `T1Dr1` run present in the canonical feature table but absent
  from the ecological table.
- Reconfirm the final profile accounting after those dispositions:
  1,271 canonical feature profiles, 1,237 ecology profiles across sites 1–64,
  and 1,227 primary profiles across sites 1–60.

## Taxonomy

- Generate and validate the taxonomy-ABox observation count from
  `feature-table-trips1-5.tsv`; do not reuse the historical 1,401,008 count.
  Record the exact generated-file checksum, byte count and triple count.
- Require complete Trips 1–5 lineage coverage, rank and NCBI-ancestry
  validation, deterministic contextual identifiers for rejected or ambiguous
  candidates, and a machine-readable decision ledger before release.
- Preserve the appended species-assignment field and its conflicts as
  provenance only; do not promote it to an eighth rank or silently overwrite
  the canonical seven-rank classifier lineage.
- Keep GTDB and iNaturalist candidates out of the asserted release graph.
  They are not required for submission. If a future competency need warrants
  reinstating cross-resource identity mappings, first run a stratified manual
  evaluation (including homonyms, *Candidatus* names, suffix-normalized
  labels, rank conflicts and ambiguous targets) and report rank-stratified
  precision with Wilson intervals. Report recall only if a defensible
  correspondence universe exists.
- Keep `feature-table-trips1-5.tsv`, `taxonomy-trips1-5.tsv`, and
  `ASV_seqs-trips1-5.fasta` canonical. Preserve `feature-table.tsv` and
  `taxonomy.tsv` as `legacy-excluded`; never select them through a fallback in
  the canonical workflow.

## Shared soil pH dataset

- [x] Freeze all measurements available on 3 August 2026 as
  `EQ-PH-SHARED-v1.0.0`; use that exact source in both manuscripts and retain
  `EQ-PH-ECOLOGY-v1.0.0` as an uncompiled predecessor.
- [x] Account for all 1,168 source rows: 712 admitted, 356 pending, 45
  depleted, 36 date-quarantined and 19 quality-control-quarantined. Preserve
  `S28Sr1` as missed during preparation and `S57Dr1` as depleted.
- [x] Archive the cross-version membership table: 653 predecessor
  observations unchanged, 59 added, and no revised or absent observation.
- [x] Regenerate the ecology sensitivity from the shared cohort and update
  both papers from one generated value file.
- [x] Import graph-equivalent Turtle and RDF/XML pH modules into the canonical
  KG and validate all 712 process-quality-value sets and 29 sessions. The
  missing-unit negative fixture must be rejected.
- [x] Stage the source, normalized tables, graph, shape, analysis, comparison,
  checksums and validation evidence in the reviewer package. Any future
  correction requires a new version and a fresh cross-version review.

## XRF

- Obtain authoritative machine-readable concentration units, detection limits,
  and non-detect semantics, or retain the manuscript limitation and remove
  unsupported unit assertions from the released graph.
- Recover acquisition metadata for Trips 1–4 if available.
- Complete authoritative label/formula/entity-type review for every proposed
  ChEBI or PubChem mapping. Keep Light Elements as an instrument
  pseudo-analyte.
- Preserve the source-specific aggregation policies: Trips 1–4
  maximum-positive and Trip 5 last-reported. Do not describe either as
  calibration or imply field/laboratory interchangeability.
- Re-run the provenance audit and regression tests against the frozen 725-row
  laboratory input and 71 field sessions.

## Graph and query validation

- Parse the newly generated taxonomy ABox in full and validate every generated
  process, dataset, quality, value, identifier range and relationship
  direction. Continue to state explicitly that the multi-gigabyte file is
  outside the full-ShEx run.
- Add negative ShEx fixtures for missing coordinates, invalid datatypes,
  missing process inputs, and reversed measurement links.
- Run and archive an OWL profile report and out-of-profile axiom inventory.
- Run complete reasoning on the TBox and bounded representative modules, plus
  full-ABox integrity queries for identifiers, domains, ranges, datatypes,
  measurement directions, and provenance.
- Test the selected forward rules to a zero-delta fixed point with expected and
  forbidden entailment micrographs. Do not claim complete OWL-Horst coverage.
- Give every published competency query a versioned query, expected schema and
  cardinality, representative records, timeout, and pass/fail result.
- Bound or precompute the historical cross-run taxonomy query that exceeded
  300 seconds. Diagnose historical zero-result queries before publishing them.

## Workflow and package

- Execute the complete Nextflow workflow in a clean environment. The current
  real run covers only provenance, release evidence, and XRF audit; ecology,
  advanced analyses, KG validation, and paper-build outputs must not be
  represented by stubs.
- Archive the actual trace, parameters, environment/container locks, input and
  output checksums, and software versions. Resolve the current profile/output
  path mismatch for the trace.
- Make the archive layout directly consumable by the workflow or document the
  required repository-relative layout.
- Rebuild all generated modules and `PRE_RELEASE_MANIFEST.tsv` from the exact
  frozen source state.
- Freeze per-file licences, including third-party ontology and taxonomy
  licences. Replace `PENDING_RELEASE_LICENSE` only when the deposit metadata
  supplies the evidence.

## Reporting and external availability

- Complete and archive the MIxS/MIMARKS field crosswalk and STREAMS checklist;
  report missing required/recommended fields explicitly.
- Deposit an immutable, checksummed public archive and insert its DOI.
- Freeze and cite the repository commit used for the archive.
- Verify anonymous resolution and download for `PRJEB104209`, `PRJEB106069`,
  every project/sample/run accession, and every manifest entry.
- Test the DOI, bulk download, checksum verification, and documented smoke
  queries from an anonymous clean environment.

## Final manuscript pass

- Insert the confirmed author contributions, competing interests,
  acknowledgements, and funding sections.
- Replace the provisional Data Availability paragraph with the public DOI,
  frozen commit, and verified accession links.
- Regenerate all manuscript-derived counts and tables from the frozen package.
- Run `python3 scripts/test_manuscript_consistency.py`.
- Build the article and separate supplement from a clean tree and inspect both
  PDFs for layout, duplicate hyperlink destinations, unresolved references,
  and citation warnings.
