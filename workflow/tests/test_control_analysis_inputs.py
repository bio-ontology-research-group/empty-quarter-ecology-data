from __future__ import annotations

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONTROL_INPUT = (
    ROOT
    / "evidence/controls/source_snapshots/ibex_20250714_qiime2/extracted"
)


EXPECTED = {
    "feature-table.biom": (
        16_057_756,
        "fe172ba5e5ef3ceb5dfc22b9b78146459915b1ecbd40972b852f26ae81f17568",
    ),
    "taxonomy.tsv": (
        7_878_855,
        "5cbca6e9904ffe395fe2e4215f6005622e47a9af71528c209398a22669c3b5db",
    ),
}


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def test_control_analysis_inputs_are_packaged_and_byte_identified() -> None:
    for name, (expected_bytes, expected_hash) in EXPECTED.items():
        path = CONTROL_INPUT / name
        assert path.is_file(), f"missing packaged control-analysis input: {path}"
        assert path.stat().st_size == expected_bytes
        assert digest(path) == expected_hash


def test_control_runner_exposes_packaged_inputs_in_its_sandbox() -> None:
    runner = (ROOT / "workflow/bin/run_control_analysis.sh").read_text(
        encoding="utf-8"
    )
    audit = (
        ROOT / "scripts/controls/run_assay_aware_control_audit.py"
    ).read_text(encoding="utf-8")
    assert 'ln -s "$project_root/data/metadata"' in runner
    assert '"$task_root/data/metadata"' in runner
    assert "ibex_20250714_qiime2/extracted/feature-table.biom" in audit
    assert "ibex_20250714_qiime2/extracted/taxonomy.tsv" in audit
