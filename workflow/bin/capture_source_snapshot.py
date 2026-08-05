#!/usr/bin/env python3
"""Capture the exact source bytes used by one workflow invocation.

Git metadata is useful context, but it cannot identify a dirty or exported
tree on its own.  This script therefore makes deterministic source archives
and a file-level hash manifest authoritative.  Commit/status/diff records are
regenerated for the current invocation when Git metadata is available; they
are never copied from a previous export.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import os
import stat
import subprocess
import tarfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


EXCLUDED_PARTS = {
    "__pycache__",
    ".git",
    ".nextflow",
    ".nextflow-bin",
    ".pytest_cache",
}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}
ROOT_INCLUDES = (
    "workflow",
    "scripts",
    "analysis",
    "tests",
    "config",
    "docs",
    "relic-dna",
    "requirements.txt",
    "pytest.ini",
)
DATA_PAPER_AUTHORITATIVE_FILES = (
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
ECOLOGY_PAPER_AUTHORITATIVE_FILES = (
    "main.tex",
    "supplement.tex",
    "sample.bib",
    "olplainarticle.cls",
)


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def excluded(relative: Path) -> bool:
    return (
        any(part in EXCLUDED_PARTS for part in relative.parts)
        or relative.suffix in EXCLUDED_SUFFIXES
    )


def walk_includes(root: Path, includes: Iterable[str]) -> list[Path]:
    selected: set[Path] = set()
    for include in includes:
        candidate = root / include
        if candidate.is_symlink() or candidate.is_file():
            relative = candidate.relative_to(root)
            if not excluded(relative):
                selected.add(relative)
            continue
        if not candidate.is_dir():
            continue
        for directory, dirnames, filenames in os.walk(
            candidate, followlinks=False
        ):
            directory_path = Path(directory)
            dirnames[:] = sorted(
                name
                for name in dirnames
                if not excluded(
                    (directory_path / name).relative_to(root)
                )
            )
            for filename in sorted(filenames):
                relative = (directory_path / filename).relative_to(root)
                if not excluded(relative):
                    selected.add(relative)
            for dirname in dirnames:
                path = directory_path / dirname
                if path.is_symlink():
                    selected.add(path.relative_to(root))
    return sorted(selected, key=lambda item: item.as_posix())


def authoritative_paper_includes(
    root: Path,
    filenames: Iterable[str],
    directories: Iterable[str] = (),
) -> list[Path]:
    selected: list[Path] = []
    missing: list[str] = []
    for filename in filenames:
        path = root / filename
        if not (path.is_file() or path.is_symlink()):
            missing.append(filename)
        else:
            selected.append(Path(filename))
    if missing:
        raise FileNotFoundError(
            "authoritative manuscript input(s) missing from "
            f"{root}: {', '.join(missing)}"
        )
    selected.extend(walk_includes(root, directories))
    return sorted(set(selected), key=lambda item: item.as_posix())


@dataclass(frozen=True)
class ManifestRow:
    snapshot: str
    path: str
    kind: str
    mode: str
    bytes: int
    sha256: str
    link_target: str


def add_file(
    archive: tarfile.TarFile,
    root: Path,
    relative: Path,
    snapshot: str,
    *,
    dereference_file_symlinks: bool = False,
) -> ManifestRow:
    source = root / relative
    source_stat = source.lstat()
    dereference = (
        dereference_file_symlinks
        and source.is_symlink()
        and source.resolve(strict=True).is_file()
    )
    if dereference:
        source_stat = source.stat()
    info = tarfile.TarInfo(relative.as_posix())
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    info.mtime = 0
    info.mode = stat.S_IMODE(source_stat.st_mode)

    if source.is_symlink() and not dereference:
        target = os.readlink(source)
        info.type = tarfile.SYMTYPE
        info.linkname = target
        info.size = 0
        archive.addfile(info)
        return ManifestRow(
            snapshot=snapshot,
            path=relative.as_posix(),
            kind="symlink",
            mode=f"{info.mode:04o}",
            bytes=0,
            sha256=sha256_bytes(target.encode("utf-8")),
            link_target=target,
        )

    content = source.read_bytes()
    info.type = tarfile.REGTYPE
    info.size = len(content)
    archive.addfile(info, io.BytesIO(content))
    return ManifestRow(
        snapshot=snapshot,
        path=relative.as_posix(),
        kind="file",
        mode=f"{info.mode:04o}",
        bytes=len(content),
        sha256=sha256_bytes(content),
        link_target="",
    )


def write_archive(
    root: Path,
    relative_paths: list[Path],
    output: Path,
    snapshot: str,
    *,
    dereference_file_symlinks: bool = False,
) -> tuple[list[ManifestRow], dict[str, object]]:
    output.parent.mkdir(parents=True, exist_ok=True)
    rows: list[ManifestRow] = []
    temporary = output.with_suffix(output.suffix + ".tmp")
    with temporary.open("wb") as raw:
        with gzip.GzipFile(
            filename="",
            mode="wb",
            fileobj=raw,
            compresslevel=9,
            mtime=0,
        ) as compressed:
            with tarfile.open(
                fileobj=compressed,
                mode="w",
                format=tarfile.PAX_FORMAT,
            ) as archive:
                for relative in relative_paths:
                    rows.append(
                        add_file(
                            archive,
                            root,
                            relative,
                            snapshot,
                            dereference_file_symlinks=(
                                dereference_file_symlinks
                            ),
                        )
                    )
    os.replace(temporary, output)
    return rows, {
        "archive": output.name,
        "bytes": output.stat().st_size,
        "sha256": sha256_file(output),
        "files_and_symlinks": len(rows),
        "source_root_role": snapshot,
    }


def run_git(repo: Path, arguments: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *arguments],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def capture_git(
    repo: Path,
    label: str,
    output_dir: Path,
    pathspecs: list[str],
    patch_filename: str,
) -> dict[str, object]:
    commit_path = output_dir / f"{label}_commit.txt"
    status_path = output_dir / f"{label}_status.txt"
    patch_path = output_dir / patch_filename
    check = run_git(repo, ["rev-parse", "--is-inside-work-tree"])
    if check.returncode != 0 or check.stdout.strip() != "true":
        message = (
            "UNAVAILABLE: this is an exported tree without Git metadata; "
            "the per-file manifest and source archive are authoritative.\n"
        )
        commit_path.write_text(message, encoding="utf-8")
        status_path.write_text(message, encoding="utf-8")
        patch_path.write_text(
            "# No patch was copied from an earlier run.\n"
            "# Exact exported source bytes are in the authoritative archive.\n",
            encoding="utf-8",
        )
        return {
            "mode": "exported_tree",
            "commit": None,
            "dirty": None,
            "commit_file": commit_path.name,
            "status_file": status_path.name,
            "patch_file": patch_path.name,
        }

    commit = run_git(repo, ["rev-parse", "HEAD"])
    if commit.returncode != 0:
        raise RuntimeError(commit.stderr.strip())
    status = run_git(
        repo, ["status", "--short", "--untracked-files=all"]
    )
    if status.returncode != 0:
        raise RuntimeError(status.stderr.strip())
    patch = run_git(repo, ["diff", "--binary", "HEAD", "--", *pathspecs])
    if patch.returncode != 0:
        raise RuntimeError(patch.stderr.strip())
    commit_text = commit.stdout.strip()
    commit_path.write_text(commit_text + "\n", encoding="utf-8")
    status_path.write_text(status.stdout, encoding="utf-8")
    patch_path.write_text(patch.stdout, encoding="utf-8")
    return {
        "mode": "git_worktree",
        "commit": commit_text,
        "dirty": bool(status.stdout.strip()),
        "commit_file": commit_path.name,
        "status_file": status_path.name,
        "patch_file": patch_path.name,
        "note": (
            "Commit/status/patch are contextual. Untracked and all other "
            "captured source bytes are identified by the authoritative "
            "snapshot manifest and archive."
        ),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--ecology-paper", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    project_root = args.project_root.resolve()
    data_paper = (project_root / "data-paper").resolve()
    ecology_paper = args.ecology_paper.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    snapshot_specs = (
        (
            "analysis",
            project_root,
            walk_includes(project_root, ROOT_INCLUDES),
            output_dir / "analysis_source_snapshot.tar.gz",
        ),
        (
            "data_paper",
            data_paper,
            authoritative_paper_includes(
                data_paper,
                DATA_PAPER_AUTHORITATIVE_FILES,
                ("scripts", "zenodo/sparql"),
            ),
            output_dir / "data_paper_source_snapshot.tar.gz",
        ),
        (
            "ecology_paper",
            ecology_paper,
            authoritative_paper_includes(
                ecology_paper,
                ECOLOGY_PAPER_AUTHORITATIVE_FILES,
            ),
            output_dir / "ecology_paper_source_snapshot.tar.gz",
        ),
    )
    rows: list[ManifestRow] = []
    snapshots: dict[str, dict[str, object]] = {}
    for label, root, paths, archive_path in snapshot_specs:
        archive_rows, record = write_archive(
            root,
            paths,
            archive_path,
            label,
            # Standalone release layouts expose the canonical manuscript
            # files through compatibility symlinks.  A source snapshot must
            # identify the bytes that TeX consumes, not merely the spelling
            # of those links.  Directory links remain links so that this
            # narrowly scoped policy cannot pull large release trees into a
            # manuscript archive.
            dereference_file_symlinks=(
                label in {"data_paper", "ecology_paper"}
            ),
        )
        rows.extend(archive_rows)
        snapshots[label] = record

    manifest_path = output_dir / "snapshot_file_manifest.tsv"
    with manifest_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(
            (
                "snapshot",
                "path",
                "type",
                "mode",
                "bytes",
                "sha256",
                "link_target",
            )
        )
        for row in rows:
            writer.writerow(
                (
                    row.snapshot,
                    row.path,
                    row.kind,
                    row.mode,
                    row.bytes,
                    row.sha256,
                    row.link_target,
                )
            )

    git_records = {
        "root": capture_git(
            project_root,
            "root",
            output_dir,
            list(ROOT_INCLUDES),
            "root_targeted.patch",
        ),
        "data_paper": capture_git(
            data_paper,
            "data_paper",
            output_dir,
            [
                *DATA_PAPER_AUTHORITATIVE_FILES,
                "scripts",
                "zenodo/sparql",
            ],
            "data_paper_manuscript.patch",
        ),
        "ecology_paper": capture_git(
            ecology_paper,
            "ecology",
            output_dir,
            list(ECOLOGY_PAPER_AUTHORITATIVE_FILES),
            "ecology_manuscript.patch",
        ),
    }
    state = {
        "schema_version": "source-provenance-v2",
        "captured_at_utc": datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "authoritative_identity": {
            "file_manifest": {
                "file": manifest_path.name,
                "bytes": manifest_path.stat().st_size,
                "sha256": sha256_file(manifest_path),
            },
            "snapshots": snapshots,
            "statement": (
                "The file-level manifest and deterministic source archives "
                "identify the exact source bytes captured for this invocation. "
                "Git metadata is contextual and is not authoritative for a "
                "dirty or exported tree."
            ),
        },
        "git_context": git_records,
        "export_policy": (
            "No commit, status, or patch is copied from a prior run. An "
            "exported tree is identified directly by its current file hashes "
            "and source archives."
        ),
    }
    (output_dir / "source_state.json").write_text(
        json.dumps(state, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_dir / "source_provenance_mode.txt").write_text(
        ",".join(
            f"{label}:{record['mode']}"
            for label, record in git_records.items()
        )
        + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
