# XRF acquisition evidence

Robert Hoehndorf confirmed on 9 September 2026 that all laboratory measurements used Fast Mode. This applies to the 547 selected specimens from Trips 1–4 and 178 from Trip 5. The machine-readable confirmation is `metadata/xrf/acquisition_confirmation_20260909.json`.

## Original workbooks

The four original workbooks are retained under `metadata/xrf/all-trips-consolidated/` and `metadata/xrf/xrf-lab/`. They are byte-identical to the copies recovered from the project's `empty-quarter/data/metadata/xrf/` directory. The source hashes and a sheet-by-sheet metadata audit are in `evidence/xrf_audit/workbook_acquisition_20260909.json`.

All 178 canonical Trip 5 specimens have explicit workbook settings: Method `Fast Screening-He8mm`, Mode `He`, Diameter `8mm`, and Material `Oxides`. The 62-sheet deep-soil workbook contains 58 ordinary sheets and Fast Screening/Best Detection comparisons for V4Dr3 and V18Dr3. The canonical parser retains both Fast Screening sheets and excludes both Best Detection sheets. Surface and root-adjacent workbooks contribute 60 and 58 specimens, respectively. Element and oxide reporting sections retain their original channels.

The Trips 1–4 consolidated workbook preserves 28 XRF export columns. Its index names the pre-consolidation workbooks; those separate files were absent from the inspected source tree. Acquisition metadata rows are absent from the consolidation. The all-campaign Fast Mode confirmation resolves the method family; the exact method label, gas and diameter for Trips 1–4 remain undocumented.

## Units and remaining acquisition parameters

The original concentration and calculated-concentration columns carry numeric values with no unit label. Trip 5 uses Excel's `General` format for those values. Percent formats occur in the statistical-error columns, with four additional percent-formatted lower-limit-of-detection cells. PPM labels occur in lower-limit-of-detection columns. The resource therefore retains instrument-reported magnitudes with an unknown concentration unit.

The laboratory analyser model, measurement duration, tube voltage/current, sample preparation, moisture/mass basis, calibration and reference-material results remain undocumented in the recovered files. The Olympus Vanta VMR-XXX-G3-E (serial 841307) identifies the handheld field instrument. Its retained field exports specify `Geochem(3-Beam)` and `NORMAL`; their Duration field is `N/A`.

## Reproduce this check

Run from the repository root:

```sh
python scripts/xrf/audit_xrf_workbook_metadata.py --xrf-root metadata/xrf --output evidence/xrf_audit/workbook_acquisition_20260909.json
python -m pytest tests/test_xrf_workbook_metadata.py
```

This audit supplements the archived XRF provenance and unit audits. It preserves the source workbooks, canonical concentrations, specimen selection and downstream numerical results unchanged.

The current coauthor ecology manuscript identifies the laboratory instrument
family as Vanta. The data descriptor attributes that identification to the
companion protocol; exact model variant and serial number remain absent from
the exports. See metadata/xrf/laboratory_instrument_provenance_20261004.json.
