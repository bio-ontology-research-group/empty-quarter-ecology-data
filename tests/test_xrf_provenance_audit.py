"""Focused tests for the deterministic XRF provenance audit."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from scripts.xrf.audit_xrf_provenance import (
    aggregate_group,
    aggregation_group_details,
    canonical_sample_key,
    canonical_t5_sheet_id,
    run_audit,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def digest_directory(path: Path) -> dict[str, str]:
    return {
        item.name: hashlib.sha256(item.read_bytes()).hexdigest()
        for item in sorted(path.iterdir())
        if item.is_file()
    }


def observation(formula: str, value: float, status: str, row: int) -> dict:
    return {
        "source": "synthetic",
        "trip": 1,
        "site": 1,
        "compartment": "Deep",
        "sample_id": "1Dr1",
        "formula": formula,
        "value": value,
        "status": status,
        "sheet": "T1-Dr",
        "row_index": row,
    }


def test_sample_id_normalization_keeps_trip_and_compartment_distinct():
    assert canonical_sample_key("1Dr1") == (1, 1, "Deep")
    assert canonical_sample_key("T1PRr3") == (2, 1, "Rhizosphere")
    assert canonical_sample_key("F21Sr2") == (3, 21, "Surface")
    assert canonical_sample_key("S41Dr1") == (4, 41, "Deep")
    assert canonical_sample_key("V8Sr1") == (5, 8, "Surface")
    assert canonical_sample_key("8Sr1", default_trip=5) == (5, 8, "Surface")
    assert canonical_sample_key("not-a-sample") is None


def test_trip5_sheet_normalization_reproduces_documented_selection():
    assert canonical_t5_sheet_id("20", "Deep") == "V20Dr1"
    assert canonical_t5_sheet_id("V4Dr3Fast screening", "Deep") == "V4Dr3"
    assert canonical_t5_sheet_id("4PRr1", "Rhizosphere") == "V4PRr1"
    assert canonical_t5_sheet_id("V18Dr3 Best Detection", "Deep") is None


def test_candidate_aggregation_rules_remain_explicit():
    rows = [
        observation("Cl", 1.0, "XRF 0", 1),
        observation("Cl", 2.0, "XRF 1", 2),
    ]
    assert aggregate_group(rows, "max_positive") == 2.0
    assert aggregate_group(rows, "mean_positive") == 1.5
    assert aggregate_group(rows, "median_positive") == 1.5
    assert aggregate_group(rows, "first_reported") == 1.0
    assert aggregate_group(rows, "last_reported") == 2.0
    assert aggregate_group(rows, "primary_status") == 1.0


def test_group_audit_records_missing_primary_status_without_guessing():
    rows = [observation("CeO2", 0.37, "XRF 2", 1)]
    details = aggregation_group_details("lab_t1_4", rows, "max_positive")
    assert len(details) == 1
    assert details[0]["expected_primary_status"] == "XRF 1"
    assert details[0]["primary_status_available"] is False
    assert details[0]["primary_status_value"] is None
    assert details[0]["current_value"] == pytest.approx(0.37)


@pytest.fixture(scope="module")
def real_audit(tmp_path_factory):
    first = tmp_path_factory.mktemp("xrf-audit-first")
    second = tmp_path_factory.mktemp("xrf-audit-second")
    summary = run_audit(PROJECT_ROOT, first)
    run_audit(PROJECT_ROOT, second)
    return summary, first, second


def test_real_source_reconciliation(real_audit):
    summary, output, _ = real_audit
    counts = summary["counts"]

    assert counts["field_log_rows"] == 106
    assert counts["field_log_sites"] == 59
    assert counts["field_complete_sessions"] == 71
    assert counts["field_instrument_exports"] == 71
    assert counts["field_sites"] == 58
    assert counts["field_repeated_sites"] == 9

    assert counts["lab_t14_samples"] == 547
    assert counts["lab_t5_workbook_sheets"] == 180
    assert counts["lab_t5_selected_sheets"] == 178
    assert counts["lab_t5_processed_samples"] == 178
    assert counts["lab_t5_canonical"] == 178
    assert counts["lab_t5_retired_analytical_subset"] == 158
    assert counts["lab_t5_missing_from_retired_subset"] == 20
    assert counts["lab_all_canonical"] == 725
    assert counts["lab_all_retired_analytical_subset"] == 705

    assert counts["community_join_canonical_qc"] == 621
    assert counts["community_join_retired_subset_qc"] == 611
    assert counts["field_lab_matched_sites"] == 58
    assert summary["canonical_policy"] == {
        "laboratory_record_count": 725,
        "trips_1_4_records": 547,
        "trips_1_4_rule": "max_positive",
        "trip_5_records": 178,
        "trip_5_rule": "last_reported",
        "retired_trip_5_subset_records": 158,
        "field_lab_interchangeability_claim": False,
    }

    expected = {
        "xrf_aggregation_group_details.tsv",
        "xrf_aggregation_sensitivity.tsv",
        "xrf_audit_summary.json",
        "xrf_current_table_discrepancies.tsv",
        "xrf_evidence_report.md",
        "xrf_field_lab_agreement.tsv",
        "xrf_field_lab_site_matches.tsv",
        "xrf_field_replicate_precision.tsv",
        "xrf_metadata_gaps.tsv",
        "xrf_method_metadata.tsv",
        "xrf_reconciliation.tsv",
        "xrf_source_inventory.tsv",
    }
    assert {path.name for path in output.iterdir()} == expected


def test_real_audit_is_byte_deterministic(real_audit):
    _, first, second = real_audit
    assert digest_directory(first) == digest_directory(second)


def test_current_aggregation_rules_are_exactly_reproduced(real_audit):
    summary, _, _ = real_audit
    t14 = summary["aggregation_reproduction"]["lab_t1_4"]
    t5 = summary["aggregation_reproduction"]["lab_t5"]

    assert t14["rule"] == "max_positive"
    assert t14["mismatched_reported_cells"] == 0
    assert t14["checked_reported_cells"] == 13390

    assert t5["rule"] == "last_reported"
    assert t5["mismatched_reported_cells"] == 0
    assert t5["checked_reported_cells"] == 4293
