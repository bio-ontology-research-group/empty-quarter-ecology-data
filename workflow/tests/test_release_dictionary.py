import csv
import hashlib
import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
STAGE = (
    ROOT / "data-paper/zenodo"
    if (ROOT / "data-paper/zenodo").is_dir()
    else ROOT
)


def fields(path: Path) -> set[str]:
    with path.open(newline="", encoding="utf-8") as handle:
        return set(next(csv.reader(handle, delimiter="\t")))


def test_curated_release_tables_have_field_dictionary_coverage() -> None:
    dictionary_path = STAGE / "metadata/DATA_DICTIONARY.tsv"
    with dictionary_path.open(newline="", encoding="utf-8") as handle:
        dictionary = list(csv.DictReader(handle, delimiter="\t"))
    for relative in (
        "metadata/climate/monthly_weather_averages.tsv",
        "ontology/mapped_taxonomy_corrected.tsv",
    ):
        described = {
            row["field_or_pattern"]
            for row in dictionary
            if row["path"] == relative
        }
        assert fields(STAGE / relative) <= described


SPEC = importlib.util.spec_from_file_location(
    "manifest_refresh", ROOT / "scripts/manuscript/update_pre_release_manifest.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def bulk_manifest(root, row):
    with (root / "BULK_ARTIFACTS.tsv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["path", "bytes", "sha256"], delimiter="\t")
        writer.writeheader()
        writer.writerow({key: row[key] for key in writer.fieldnames})


def test_refresh_hashes_present_files_without_changing_dispositions(tmp_path):
    (tmp_path / "payload").write_bytes(b"current\n")
    row = {"path": "payload", "bytes": "0", "sha256": "stale",
           "license_status": "AUTHOR_GATE_UNRESOLVED", "release_status": "audit-evidence"}
    MODULE.refresh_declared(tmp_path, [row])
    assert row == {"path": "payload", "bytes": "8",
                   "sha256": hashlib.sha256(b"current\n").hexdigest(),
                   "license_status": "AUTHOR_GATE_UNRESOLVED", "release_status": "audit-evidence"}


def test_matching_absent_bulk_keeps_recorded_hash(tmp_path):
    row = {"path": "large.ttl", "bytes": "100", "sha256": "a" * 64}
    bulk_manifest(tmp_path, row)
    original = row.copy()
    MODULE.refresh_declared(tmp_path, [row])
    assert row == original


@pytest.mark.parametrize("mismatch", ["bytes", "sha256"])
def test_absent_bulk_with_conflicting_declaration_fails(tmp_path, mismatch):
    row = {"path": "large.ttl", "bytes": "100", "sha256": "a" * 64}
    bulk_manifest(tmp_path, row)
    row[mismatch] = "200" if mismatch == "bytes" else "b" * 64
    with pytest.raises(ValueError, match="missing artifact without matching bulk"):
        MODULE.refresh_declared(tmp_path, [row])


def test_undeclared_missing_artifact_fails(tmp_path):
    with pytest.raises(ValueError, match="missing artifact without matching bulk"):
        MODULE.refresh_declared(tmp_path, [{"path": "missing", "bytes": "1", "sha256": "a" * 64}])


def test_duplicate_bulk_declaration_fails(tmp_path):
    row = {"path": "large.ttl", "bytes": "100", "sha256": "a" * 64}
    bulk_manifest(tmp_path, row)
    with (tmp_path / "BULK_ARTIFACTS.tsv").open("a") as handle:
        handle.write("large.ttl\t100\t" + "b" * 64 + "\n")
    with pytest.raises(ValueError, match="duplicate bulk declaration"):
        MODULE.refresh_declared(tmp_path, [row])


@pytest.mark.parametrize("field,value", [("bytes", "-1"), ("bytes", "1.5"),
                                         ("sha256", ""), ("sha256", "z" * 64)])
def test_matching_malformed_bulk_declarations_fail(tmp_path, field, value):
    row = {"path": "large.ttl", "bytes": "100", "sha256": "a" * 64}
    row[field] = value
    bulk_manifest(tmp_path, row)
    with pytest.raises(ValueError, match="invalid size or SHA-256"):
        MODULE.refresh_declared(tmp_path, [row])
