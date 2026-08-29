# XRF provenance audit

`scripts/xrf/audit_xrf_provenance.py` creates the evidence bundle shared by
the data descriptor and ecology analyses. It does not rewrite source data.

## Data layers

The audit keeps these observational units distinct:

1. **Trip-5 field XRF:** 71 retained Vanta instrument sessions. Several sites
   have repeated sessions, so these are not 71 independent sites or samples.
2. **Laboratory source/processed XRF:** archived material from all five trips.
   The present sources contain 547 sample records for Trips 1--4 and 178
   selected Trip-5 records.
3. **Canonical laboratory analytical XRF:** 547 Trips 1--4 records and all 178
   processed Trip-5 records, for 725 records total. The former 158-record
   Trip-5 subset (705 combined records) is retained only as retired provenance.

The field-session log records sites but not physical sample IDs, compartments,
depths, or replicates. Consequently, field/lab diagnostics are site-level and
must not be described as same-aliquot validation.

## Reproduction

From any working directory:

```bash
uv run --with openpyxl python /path/to/empty-quarter/scripts/xrf/audit_xrf_provenance.py \
  --project-root /path/to/empty-quarter \
  --output-dir /path/to/output/xrf_audit
```

The derived community table and QC threshold are configurable:

```bash
uv run --with openpyxl python scripts/xrf/audit_xrf_provenance.py \
  --project-root . \
  --output-dir analysis/xrf_audit \
  --community-table analysis/v2/review/cache/genus_counts.tsv \
  --minimum-community-reads 2000
```

This interface is suitable for a Nextflow process:

- All data locations are resolved from explicit CLI arguments.
- Outputs are confined to `--output-dir`.
- Tables are stably sorted.
- No random procedure or current timestamp is used.
- The source inventory contains SHA-256 checksums.
- Repeating a run with identical inputs produces byte-identical outputs.

## Outputs

| File | Purpose |
|---|---|
| `xrf_audit_summary.json` | Machine-readable headline counts, parameters, and critical flags |
| `xrf_source_inventory.tsv` | Input roles, sizes, and SHA-256 checksums |
| `xrf_reconciliation.tsv` | Raw/processed/analytical counts and community joins |
| `xrf_aggregation_sensitivity.tsv` | Per-analyte comparison of candidate aggregation rules |
| `xrf_aggregation_group_details.tsv` | Sample/analyte-level values for every repeat or missing-primary-status case |
| `xrf_current_table_discrepancies.tsv` | Omitted samples/analytes and rule-reproduction checks |
| `xrf_metadata_gaps.tsv` | Missing units, modes, LOD semantics, linkage, and exclusion provenance |
| `xrf_method_metadata.tsv` | Encoded field and laboratory acquisition settings by workflow |
| `xrf_field_lab_agreement.tsv` | Site-level reported-positive, rank, ratio, and log Bland–Altman diagnostics |
| `xrf_field_lab_site_matches.tsv` | Auditable field-session medians and Trip-5 Deep laboratory values |
| `xrf_field_replicate_precision.tsv` | Within-site field-session CV summaries |
| `xrf_evidence_report.md` | Human-readable findings and manuscript-ready wording |

## Aggregation interpretation

The current Trips 1--4 builder uses the largest positive value across XRF
status rows. The Trip-5 parser instead keeps the last value for a repeated
formula. The audit compares both with:

- maximum positive;
- mean positive;
- median positive;
- first reported;
- last reported; and
- a `primary_status` candidate based on workbook section labels (`XRF 0` for
  elements and `XRF 1` for oxides).

`primary_status` is a sensitivity analysis, not the approved rule. The
canonical processing rules are max-positive for Trips 1--4 and last-reported
for Trip 5. They are data-processing choices, not evidence that XRF statuses or
field/laboratory methods are calibrated or interchangeable. When a
primary-status row is absent, the audit leaves the candidate blank rather than
substituting another status.

## Manuscript guardrails

- Describe field and laboratory XRF as complementary workflows; do not say
  that the papers or measurements disagree.
- Report the unit counted: instrument sessions, sample sheets, processed
  records, trip-site-compartment groups, or community joins.
- Do not call zero a measured absence while run/analyte LOD semantics remain
  unavailable.
- Use 725 (=547+178) as the canonical laboratory record count. Treat the
  158-row Trip-5 / 705-row combined input as retired.
- Do not claim field/lab interchangeability from the site-level diagnostic.
