"""Positive and negative checks for the source-updated control ledger gate."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "validate_controls_ledger", Path(__file__).resolve().parents[1]
    / "scripts/validation/validate_controls.py",
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_current_twelve_ground_truth_records_pass():
    assert not module.ground_truth_id_failures(
        [{"record_id": f"CGT-{n:03d}"} for n in range(1, 13)]
    )


def test_missing_pcr_confirmation_fails():
    assert module.ground_truth_id_failures(
        [{"record_id": f"CGT-{n:03d}"} for n in range(1, 12)]
    )


def test_duplicate_cannot_hide_behind_set_equality():
    rows = [{"record_id": f"CGT-{n:03d}"} for n in range(1, 13)]
    assert module.ground_truth_id_failures(rows + [rows[-1]])
