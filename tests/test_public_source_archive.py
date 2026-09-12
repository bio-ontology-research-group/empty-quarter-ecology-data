import importlib.util
import json
import sys
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("archive_public", ROOT / "scripts/release/archive_public_sources.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def fixture_source(tmp_path, name="scientific.tsv"):
    source = tmp_path / "source"
    source.mkdir()
    (source / "scientific.tsv").write_text("site\tvalue\n1\t2\n")
    (source / "private-correspondence.txt").write_text("Never package this unlisted file")
    (source / "SOURCE_MANIFEST.json").write_text(json.dumps({"files": 1, "bytes": 15, "records": [{"path": name}]}))
    (source / "SOURCE_SHA256SUMS").write_text("test manifest\n")
    return source


def test_archive_only_contains_explicit_whitelist_and_is_deterministic(tmp_path, monkeypatch):
    source = fixture_source(tmp_path)
    archives = [tmp_path / "first.tar.gz", tmp_path / "second.tar.gz"]
    for archive in archives:
        monkeypatch.setattr(sys, "argv", ["archive", "--source", str(source), "--archive", str(archive)])
        module.main()
    assert archives[0].read_bytes() == archives[1].read_bytes()
    with tarfile.open(archives[0]) as tar:
        assert set(tar.getnames()) == {"rubalkhali-kg-3.0.0-source/" + name for name in ("scientific.tsv", "SOURCE_MANIFEST.json", "SOURCE_SHA256SUMS")}


def test_archive_rejects_path_escape(tmp_path, monkeypatch):
    source = fixture_source(tmp_path, "../private-correspondence.txt")
    monkeypatch.setattr(sys, "argv", ["archive", "--source", str(source), "--archive", str(tmp_path / "bad.tar.gz")])
    with pytest.raises(AssertionError):
        module.main()
