from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = (
    PROJECT_ROOT / "scripts" / "validation" / "validate_competency_query.py"
)
QUERY = PROJECT_ROOT / "sparql" / "field_xrf_site10.rq"
if not QUERY.is_file():
    QUERY = (
        PROJECT_ROOT
        / "data-paper"
        / "zenodo"
        / "sparql"
        / "field_xrf_site10.rq"
    )
ONTOLOGY_DIR = PROJECT_ROOT / "ontology"
if not ONTOLOGY_DIR.is_dir():
    ONTOLOGY_DIR = (
        PROJECT_ROOT / "data" / "processed" / "semantics" / "ontology"
    )


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_canonical_field_xrf_competency_query(tmp_path: Path):
    subprocess.run(
        [
            sys.executable,
            str(VALIDATOR),
            "--base",
            str(ONTOLOGY_DIR / "rubalkhali.owl"),
            "--sites",
            str(ONTOLOGY_DIR / "rubalkhali_sites.owl"),
            "--xrf",
            str(ONTOLOGY_DIR / "rubalkhali_xrf.owl"),
            "--query",
            str(QUERY),
            "--expected-rows",
            "46",
            "--output-dir",
            str(tmp_path),
        ],
        check=True,
    )

    evidence = json.loads(
        (tmp_path / "competency_query_validation.json").read_text()
    )
    assert evidence["status"] == "passed"
    assert evidence["expected_rows"] == 46
    assert evidence["observed_rows"] == 46
    assert len(evidence["distinct_process_labels"]) == 2
    assert evidence["site_labels"] == ["Site 10"]

    query_snapshot = tmp_path / "field_xrf_site10.rq"
    assert query_snapshot.read_bytes() == QUERY.read_bytes()
    assert evidence["query_snapshot"]["sha256"] == sha256(QUERY)
    assert evidence["inputs"]["query"]["sha256"] == sha256(QUERY)

    with (tmp_path / "field_xrf_site10_results.tsv").open(
        newline="", encoding="utf-8"
    ) as handle:
        rows = list(csv.reader(handle, delimiter="\t"))
    assert len(rows) == 47

    checksums = (tmp_path / "SHA256SUMS").read_text().splitlines()
    assert len(checksums) == 3
    for line in checksums:
        expected, filename = line.split("  ", maxsplit=1)
        assert sha256(tmp_path / filename) == expected
