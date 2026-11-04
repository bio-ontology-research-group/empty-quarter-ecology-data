import csv
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("stage_mag_zenodo", ROOT / "scripts/release/stage_mag_zenodo.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_stage_writes_complete_described_upload_set(tmp_path):
    MODULE.stage(ROOT, tmp_path)
    for name in MODULE.TABLES + MODULE.RECEIPTS + ("README.md", "DATA_DICTIONARY.tsv", "zenodo_metadata.json",
                                                   "upload_to_zenodo.sh", "finish_on_ibex.sh"):
        assert (tmp_path / name).is_file()
    with (tmp_path / "DATA_DICTIONARY.tsv").open() as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    for table in MODULE.TABLES:
        with (tmp_path / table).open() as handle:
            header = next(csv.reader(handle, delimiter="\t"))
        assert set(header) == {r["field_or_pattern"] for r in rows if r["path"] == table}
    metadata = json.loads((tmp_path / "zenodo_metadata.json").read_text())["metadata"]
    assert [c["name"] for c in metadata["creators"]] == MODULE.AUTHORS
    assert metadata["license"] == "cc-by-4.0" and metadata["prereserve_doi"]
    readme = (tmp_path / "README.md").read_text()
    assert "5,438" in readme and "PRJEB125153" in readme and "12,434" in readme


def test_checksum_list_excludes_helpers_and_logs():
    for excluded in ("SHA256SUMS", "upload_to_zenodo.sh", "finish_on_ibex.sh", "zenodo_metadata.json", "\\.log"):
        assert excluded in MODULE.FINISH
