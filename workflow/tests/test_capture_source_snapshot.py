from __future__ import annotations

import csv
import json
import subprocess
import sys
import tarfile
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "bin"
    / "capture_source_snapshot.py"
)


def write_fixture(root: Path) -> tuple[Path, Path]:
    (root / "workflow").mkdir(parents=True)
    (root / "scripts").mkdir()
    (root / "analysis").mkdir()
    (root / "tests").mkdir()
    (root / "config").mkdir()
    (root / "docs").mkdir()
    (root / "relic-dna").mkdir()
    (root / "workflow" / "main.nf").write_text("version one\n")
    (root / "requirements.txt").write_text("example==1\n")

    data_paper = root / "data-paper"
    data_paper.mkdir()
    data_paper_files = (
        "AUTHORITATIVE_MANUSCRIPT.md",
        "sn-article.tex",
        "01_introduction.tex",
        "02_methods.tex",
        "02_methods_taxonomy.tex",
        "03_knowledge_representation.tex",
        "04_data_records.tex",
        "05_validation.tex",
        "06_usage.tex",
        "supplement.tex",
        "kr_supplement.tex",
        "env_table.tex",
        "xrf_table.tex",
        "sn-bibliography.bib",
        "sn-jnl.cls",
        "sn-mathphys-num.bst",
    )
    for filename in data_paper_files:
        (data_paper / filename).write_text(f"{filename}\n")
    (data_paper / "retired-main.tex").write_text(
        "must not be captured\n"
    )
    (data_paper / "scripts").mkdir()
    (data_paper / "scripts" / "check.py").write_text("print('ok')\n")
    (data_paper / "zenodo" / "sparql").mkdir(parents=True)
    (data_paper / "zenodo" / "sparql" / "field_xrf_site10.rq").write_text(
        "SELECT * WHERE { ?s ?p ?o }\n"
    )
    (data_paper / "zenodo" / "large-release").mkdir()
    (data_paper / "zenodo" / "large-release" / "excluded.ttl").write_text(
        "must not be captured\n"
    )

    ecology = root / "ecology-paper"
    ecology.mkdir()
    for filename in (
        "main.tex",
        "supplement.tex",
        "ph_shared_v1.tex",
        "sample.bib",
        "olplainarticle.cls",
    ):
        (ecology / filename).write_text(f"{filename}\n")
    (ecology / "generated").mkdir()
    (ecology / "generated" / "ph_shared_v1_values.tex").write_text(
        "generated pH values\n"
    )
    (
        ecology
        / "generated"
        / "ph_shared_v1_values.manifest.json"
    ).write_text('{"status": "passed"}\n')
    (ecology / "figures").mkdir()
    (ecology / "figures" / "figure.pdf").write_bytes(b"%PDF-fixture")
    return data_paper, ecology


def run_snapshot(root: Path, ecology: Path, output: Path) -> None:
    subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--project-root",
            str(root),
            "--ecology-paper",
            str(ecology),
            "--output-dir",
            str(output),
        ],
        check=True,
    )


def test_exported_tree_uses_current_bytes_not_stale_patch(tmp_path: Path):
    root = tmp_path / "export"
    _, ecology = write_fixture(root)
    stale = root / ".reproducibility-provenance"
    stale.mkdir()
    (stale / "root_commit.txt").write_text("STALE-COMMIT\n")
    (stale / "root_targeted.patch").write_text("STALE-PATCH\n")

    first = tmp_path / "first"
    run_snapshot(root, ecology, first)
    state = json.loads((first / "source_state.json").read_text())
    assert state["git_context"]["root"]["mode"] == "exported_tree"
    assert "STALE" not in (first / "root_commit.txt").read_text()
    assert "STALE" not in (first / "root_targeted.patch").read_text()
    assert (
        state["export_policy"]
        == "No commit, status, or patch is copied from a prior run. An "
        "exported tree is identified directly by its current file hashes "
        "and source archives."
    )
    with tarfile.open(first / "analysis_source_snapshot.tar.gz", "r:gz") as tar:
        assert tar.extractfile("workflow/main.nf").read() == b"version one\n"
    with tarfile.open(
        first / "data_paper_source_snapshot.tar.gz", "r:gz"
    ) as tar:
        members = set(tar.getnames())
        assert "kr_supplement.tex" in members
        assert "zenodo/sparql/field_xrf_site10.rq" in members
        assert "zenodo/large-release/excluded.ttl" not in members
        assert "retired-main.tex" not in members
    with tarfile.open(
        first / "ecology_paper_source_snapshot.tar.gz", "r:gz"
    ) as tar:
        members = set(tar.getnames())
        assert "ph_shared_v1.tex" in members
        assert "generated/ph_shared_v1_values.tex" in members
        assert "generated/ph_shared_v1_values.manifest.json" in members
        assert "figures/figure.pdf" not in members

    (root / "workflow" / "main.nf").write_text("version two\n")
    second = tmp_path / "second"
    run_snapshot(root, ecology, second)
    first_hash = state["authoritative_identity"]["snapshots"]["analysis"][
        "sha256"
    ]
    second_state = json.loads((second / "source_state.json").read_text())
    second_hash = second_state["authoritative_identity"]["snapshots"][
        "analysis"
    ]["sha256"]
    assert first_hash != second_hash


def test_archives_are_byte_deterministic(tmp_path: Path):
    root = tmp_path / "export"
    _, ecology = write_fixture(root)
    first = tmp_path / "first"
    second = tmp_path / "second"
    run_snapshot(root, ecology, first)
    run_snapshot(root, ecology, second)
    for archive in (
        "analysis_source_snapshot.tar.gz",
        "data_paper_source_snapshot.tar.gz",
        "ecology_paper_source_snapshot.tar.gz",
    ):
        assert (first / archive).read_bytes() == (second / archive).read_bytes()
    assert (
        (first / "snapshot_file_manifest.tsv").read_bytes()
        == (second / "snapshot_file_manifest.tsv").read_bytes()
    )


def test_manuscript_file_symlinks_capture_consumed_bytes(tmp_path: Path):
    root = tmp_path / "export"
    data_paper, ecology = write_fixture(root)
    canonical = root / "paper"
    canonical.mkdir()
    canonical_intro = canonical / "01_introduction.tex"
    canonical_intro.write_text("canonical introduction\n")
    (data_paper / "01_introduction.tex").unlink()
    (data_paper / "01_introduction.tex").symlink_to(
        Path("../paper/01_introduction.tex")
    )

    output = tmp_path / "snapshot"
    run_snapshot(root, ecology, output)

    with (output / "snapshot_file_manifest.tsv").open(
        newline="", encoding="utf-8"
    ) as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    intro = next(
        row
        for row in rows
        if row["snapshot"] == "data_paper"
        and row["path"] == "01_introduction.tex"
    )
    assert intro["type"] == "file"
    assert intro["bytes"] == str(len(b"canonical introduction\n"))
    assert intro["link_target"] == ""

    with tarfile.open(
        output / "data_paper_source_snapshot.tar.gz", "r:gz"
    ) as archive:
        assert (
            archive.extractfile("01_introduction.tex").read()
            == b"canonical introduction\n"
        )
