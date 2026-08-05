# Empty Quarter XRF provenance and reconciliation audit

## Bottom line

The field and laboratory XRF datasets are not contradictory. They are different workflows with different observational units:

- **Field XRF:** the source log contains 106 Trip-5 entries across 59 sites. Of these, 71 complete instrument sessions at 58 sites were retained; 9 sites have repeated complete sessions. The source log is site-level and does not itself encode the sample, compartment, or depth.
- **Laboratory XRF:** 547 selected sample sheets from Trips 1--4 plus 178 selected Trip-5 sample sheets = **725 canonical laboratory records**.
- The former 158-row Trip-5 analytical subset (705 records when combined with Trips 1--4) is retired because it omits 20 records without an exclusion rule.
- With the >=2,000-read ecology filter, the canonical 725 records join to 621 community groups; the retired 705-record subset joined to 611.

Therefore, both manuscripts should describe the two workflows separately and use 725 (=547+178) as the laboratory sample count.

## Reconciliation

| Dataset | Workflow | Unit | Rows | Analyte rows | Joined (QC) | Caveat |
|---|---|---:|---:|---:|---:|---|
| field_session_log_all | field | instrument_session_log_entry | 106 |  |  | Includes COMPLETE, SHORT, and ERROR sessions. |
| field_session_log_complete | field | complete_instrument_session | 71 |  |  | Repeated complete sessions occur at some sites. |
| field_instrument_exports_complete | field | instrument_export | 71 |  |  | One Vanta composition export per retained complete TestID. |
| field_processed_table | field | complete_instrument_session | 71 |  |  | One row per complete TestID; not one row per site. |
| lab_source_t1_4 | lab | sample_sheet | 547 | 13552 |  | 12 sheets; run/method metadata are incomplete. |
| lab_canonical_table_t1_4 | lab | sample | 547 |  |  | Uses maximum positive value across XRF statuses. |
| lab_source_t5_all_sheets | lab | workbook_sheet | 180 | 4352 |  | 2 Best Detection sheets are excluded by the current parser. |
| lab_source_t5_selected_sheets | lab | selected_sample_sheet | 178 | 4352 |  | Selection reproduces the existing parser behavior. |
| lab_processed_table_t5 | lab | sample | 178 |  |  | Canonical Trip-5 table; repeated formulas keep the last workbook row. |
| lab_retired_analytical_subset_t5 | lab | sample | 158 |  |  | Retired 158-row subset; 20 canonical Trip-5 records are absent. |
| lab_all_retired_analytical_subset | lab | trip_site_compartment | 705 |  | 611 | Retired combination: 547 Trips 1-4 plus 158 Trip-5. |
| lab_all_canonical_analytical | lab | trip_site_compartment | 725 |  | 621 | Canonical: 547 Trips 1-4 plus 178 Trip-5 records. |

## Aggregation audit

The current Trips 1--4 builder explicitly takes the largest positive concentration across rows/statuses. The audit reproduces the current wide table from that rule. The current Trip-5 parser instead overwrites repeated formulas and therefore retains the last reported row. These are different policies.

In the present sources, the numerical impact is localized: the Trips 1--4 maximum agrees with the primary-status value whenever that value is present, while some rare compounds occur only under a secondary status. Trip 5 has a small number of within-status repeated rows for which last-value and primary-status-median choices differ. The detailed group-level candidate values are in `xrf_aggregation_group_details.tsv`.

The `primary_status` sensitivity below uses workbook section labels (`XRF 0 (Elements)` and `XRF 1 (Oxides)`) to compare a status-specific candidate against the current policy. It is not adopted as canonical because instrument method metadata, units, and non-detect semantics remain incomplete.

| Workflow | Analyte | Current rule | Multi-row groups | Current != primary | Missing primary | Spearman | Max absolute relative difference |
|---|---|---|---:|---:|---:|---:|---:|
| lab_t5 | Al | last_reported | 1 | 1 | 0 | 0.9999647983 | 0.04761904762 |
| lab_t5 | Ba | last_reported | 1 | 1 | 0 | 0.9983190609 | 0.7405582923 |
| lab_t5 | Ca | last_reported | 1 | 1 | 0 | 0.9998600502 | 0.1851851852 |
| lab_t5 | Fe | last_reported | 1 | 1 | 0 | 0.9980331769 | 0.2875318066 |
| lab_t5 | K | last_reported | 1 | 1 | 0 | 0.9976488653 | 0.2356687898 |
| lab_t5 | Mg | last_reported | 1 | 1 | 0 | 0.9997109336 | 0.1212121212 |
| lab_t5 | Na | last_reported | 1 | 1 | 0 | 0.9999587034 | 0.07692307692 |
| lab_t5 | P | last_reported | 1 | 1 | 0 | 0.9994142045 | 0.2258064516 |
| lab_t5 | Pr | last_reported | 1 | 1 | 0 | 0.9946816891 | 0.5306122449 |
| lab_t5 | Si | last_reported | 1 | 1 | 0 | 0.999487041 | 0.03117505995 |
| lab_t5 | Sr | last_reported | 1 | 1 | 0 | 0.9991986976 | 0.09090909091 |
| lab_t1_4 | Cl | max_positive | 126 | 0 | 0 | 1 | 0 |
| lab_t5 | Cl | last_reported | 45 | 0 | 0 | 1 | 0 |
| lab_t1_4 | Br | max_positive | 6 | 0 | 0 | 1 | 0 |
| lab_t5 | Br | last_reported | 3 | 0 | 0 | 1 | 0 |
| lab_t1_4 | I | max_positive | 1 | 0 | 0 |  | 0 |
| lab_t1_4 | CeO2 | max_positive | 0 | 0 | 12 | 1 | 0 |
| lab_t1_4 | Cr2O3 | max_positive | 0 | 0 | 10 | 1 | 0 |
| lab_t1_4 | Nd2O3 | max_positive | 0 | 0 | 9 | 1 | 0 |
| lab_t1_4 | BaO | max_positive | 0 | 0 | 6 | 1 | 0 |

## Acquisition metadata

Trip-5 acquisition settings are recoverable and confirm that the workflows are methodologically distinct: field exports report `Geochem(3-Beam)`/`NORMAL`, while laboratory workbooks report `Fast Screening-He8mm`/`He`, `8mm`, and `Oxides` for Deep, Surface, and Rhizosphere records. This supports treating the datasets as complementary rather than interchangeable.

| Workflow | Trips | Compartment | Field | Value | Records | Status |
|---|---|---|---|---|---:|---|
| field | 5 | not_encoded | Duration | N/A | 71 | encoded_in_instrument_export |
| field | 5 | not_encoded | Method | Geochem(3-Beam) | 71 | encoded_in_instrument_export |
| field | 5 | not_encoded | Mode | NORMAL | 71 | encoded_in_instrument_export |
| lab | 1-4 | Deep;Surface;Rhizosphere | Diameter |  | 547 | not_encoded_in_consolidated_workbook_or_table |
| lab | 1-4 | Deep;Surface;Rhizosphere | Material |  | 547 | not_encoded_in_consolidated_workbook_or_table |
| lab | 1-4 | Deep;Surface;Rhizosphere | Method |  | 547 | not_encoded_in_consolidated_workbook_or_table |
| lab | 1-4 | Deep;Surface;Rhizosphere | Mode |  | 547 | not_encoded_in_consolidated_workbook_or_table |
| lab | 5 | Deep | Diameter | 8mm | 60 | encoded_in_workbook |
| lab | 5 | Deep | Material | Oxides | 60 | encoded_in_workbook |
| lab | 5 | Deep | Method | Fast Screening-He8mm | 60 | encoded_in_workbook |
| lab | 5 | Deep | Mode | He | 60 | encoded_in_workbook |
| lab | 5 | Rhizosphere | Diameter | 8mm | 58 | encoded_in_workbook |
| lab | 5 | Rhizosphere | Material | Oxides | 58 | encoded_in_workbook |
| lab | 5 | Rhizosphere | Method | Fast Screening-He8mm | 58 | encoded_in_workbook |
| lab | 5 | Rhizosphere | Mode | He | 58 | encoded_in_workbook |
| lab | 5 | Surface | Diameter | 8mm | 60 | encoded_in_workbook |
| lab | 5 | Surface | Material | Oxides | 60 | encoded_in_workbook |
| lab | 5 | Surface | Method | Fast Screening-He8mm | 60 | encoded_in_workbook |
| lab | 5 | Surface | Mode | He | 60 | encoded_in_workbook |

## Trip-5 field versus laboratory comparison

The audit matched 58 sites after reducing repeated complete field sessions by their median and selecting the Trip-5 laboratory Deep record. This is a **site-level diagnostic**, not a same-aliquot validation experiment, because field session records lack a physical sample identifier.

Zeros are treated only as “not reported positive” because LOD metadata are incomplete. Rank correlations and log field/lab ratios are descriptive. They do not establish interchangeability.

| Analyte | Both positive | Positive agreement | Spearman (all sites) | Median field/lab ratio | Mean log10 bias |
|---|---:|---:|---:|---:|---:|
| Si | 58 | 1 | 0.4806017988 | 1.135770351 | 0.001816460131 |
| Mg | 17 | 0.4533333333 | 0.4698612358 | 0.7655454545 | -0.08800385501 |
| Ca | 58 | 1 | 0.3279339195 | 0.2328051282 | -0.5486763637 |
| Cr | 13 | 0.4814814815 | 0.2589048589 | 0.7947916667 | -0.227938397 |
| Ti | 37 | 0.7872340426 | 0.2401588598 | 0.6636956522 | -0.1211833987 |
| S | 43 | 0.8514851485 | 0.2025767308 | 2.502727273 | 0.2752873716 |
| Sr | 33 | 0.7252747253 | 0.1976519707 | 0.2555555556 | -0.5114653615 |
| Fe | 58 | 1 | 0.1578834032 | 0.5070487652 | -0.2852704555 |
| Zr | 32 | 0.7111111111 | 0.151890487 | 0.2360416667 | -0.6341348537 |
| Al | 51 | 0.9357798165 | -0.02598133422 | 0.5325294118 | -0.2976887606 |
| Ba | 18 | 0.4736842105 | -0.07948558427 | 0.1015338828 | -1.17933734 |
| K | 58 | 1 | -0.08104700362 | 0.454375 | -0.3336997412 |

## Metadata gaps and resolved decisions

| ID | Workflow | Severity | Missing/uncertain field | Consequence |
|---|---|---|---|---|
| XRF-GAP-001 | field_and_lab | blocking_for_absolute_method_comparison | concentration_unit | Weight-percent comparability is plausible from instrument output but cannot be established from released metadata alone. |
| XRF-GAP-002 | lab_t1_4 | limiting_for_cross_status_interpretation | instrument_method_mode_material_diameter | The documented max-positive processing rule must not be interpreted as evidence that statuses are calibrated or interchangeable. |
| XRF-GAP-003 | field_vs_lab | blocking_for_direct_interchangeability | cross_workflow_calibration | Field and laboratory values are complementary measurements, not interchangeable replicate measurements. |
| XRF-GAP-004 | lab_all | limiting_for_nondetect_analysis | lod_and_nondetect_encoding | Zero cannot safely be interpreted as a measured zero or a common detection threshold. |
| XRF-GAP-005 | field | limiting_for_field_lab_pairing | physical_sample_and_compartment_id | Field/lab validation is site-level only even though project context identifies the field measurements as Trip-5 Deep. |
| XRF-GAP-006 | lab_t5_retired_subset | resolved_by_canonical_selection | canonical_input_selection | No records are lost from the canonical analysis: the 178-row processed Trip-5 table is canonical and the 158-row table is retired. |

## Missing Trip-5 analytical records

5|1|Deep, 5|4|Deep, 5|8|Deep, 5|16|Deep, 5|17|Deep, 5|18|Deep, 5|26|Deep, 5|36|Deep, 5|38|Deep, 5|40|Deep, 5|41|Deep, 5|41|Rhizosphere, 5|48|Deep, 5|51|Deep, 5|52|Deep, 5|54|Deep, 5|56|Deep, 5|58|Deep, 5|59|Deep, 5|60|Rhizosphere

## Manuscript-ready wording

> During Trip 5, handheld X-ray fluorescence measurements were obtained in the field in 71 complete measurement sessions across 58 sites. These in-situ, site-level observations were maintained separately from laboratory XRF measurements of archived soil samples. The laboratory source data comprised 547 sample records from Trips 1--4 and 178 selected records from Trip 5. Laboratory values used for ecological analysis were linked by trip, site, and compartment; field values were used only for a descriptive Trip-5 site-level comparison because the field log did not encode a physical sample identifier.

Do not state that field and laboratory XRF disagree. State instead that their agreement is only partially testable with current linkage and method metadata. Use 725 (=547+178) as the canonical laboratory record count; the 158-row Trip-5 / 705-row combined subset is retired.

## Reproduction

```bash
uv run --with openpyxl python scripts/xrf/audit_xrf_provenance.py \
  --project-root . --output-dir analysis/xrf_audit
```

All TSV and JSON outputs are stably sorted and contain no run timestamp. The source inventory records SHA-256 checksums.
