#!/usr/bin/env python3
"""Fail-closed verification of committed and bulk repository artifacts."""

from __future__ import annotations

import argparse
import csv
import hashlib
import subprocess
import sys
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_repository_manifest(root: Path, failures: list[str]) -> None:
    manifest = root / "FILE_MANIFEST.tsv"
    if not manifest.is_file():
        failures.append("missing required repository file: FILE_MANIFEST.tsv")
        return

    expected: dict[str, tuple[int, str]] = {}
    with manifest.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if reader.fieldnames != ["path", "bytes", "sha256"]:
            failures.append("FILE_MANIFEST.tsv has an unexpected header")
            return
        for row in reader:
            relative = row["path"]
            if relative in expected:
                failures.append(f"duplicate repository manifest path: {relative}")
                continue
            expected[relative] = (int(row["bytes"]), row["sha256"])

    for relative, (size, digest) in expected.items():
        path = root / relative
        if path.is_symlink() or not path.is_file():
            failures.append(f"missing or non-regular tracked file: {relative}")
        elif path.stat().st_size != size:
            failures.append(f"wrong repository byte count: {relative}")
        elif sha256(path) != digest:
            failures.append(f"wrong repository SHA-256: {relative}")

    if (root / ".git").exists():
        output = subprocess.check_output(
            ["git", "-C", str(root), "ls-files", "-z", "--cached"]
        )
        tracked = {
            item.decode("utf-8")
            for item in output.split(b"\0")
            if item and item.decode("utf-8") != "FILE_MANIFEST.tsv"
        }
        listed = set(expected)
        for relative in sorted(tracked - listed):
            failures.append(f"tracked file absent from repository manifest: {relative}")
        for relative in sorted(listed - tracked):
            failures.append(f"repository manifest path is not tracked: {relative}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", type=Path, default=Path.cwd())
    parser.add_argument("--require-bulk", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()

    failures: list[str] = []
    missing_bulk: list[str] = []
    verify_repository_manifest(root, failures)
    with (root / "BULK_ARTIFACTS.tsv").open(
        newline="", encoding="utf-8"
    ) as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            path = root / row["path"]
            if row["distribution"] == "rebuild-not-download":
                if path.exists() and (
                    path.stat().st_size != int(row["bytes"])
                    or sha256(path) != row["sha256"]
                ):
                    failures.append(f"generated output differs: {row['path']}")
                continue
            if not path.is_file():
                missing_bulk.append(row["path"])
                continue
            if path.stat().st_size != int(row["bytes"]):
                failures.append(f"wrong byte count: {row['path']}")
            elif sha256(path) != row["sha256"]:
                failures.append(f"wrong SHA-256: {row['path']}")

    for required in (
        "PRE_RELEASE_MANIFEST.tsv",
        "environment/conda-linux-64.lock",
        "environment/pip-overlay.lock.txt",
        "environment/requirements.lock.txt",
        "metadata/DATA_DICTIONARY.tsv",
        "ontology/rubalkhali_kb.owl",
        "paper/sn-article.tex",
        "paper/supplement.tex",
        "workflow/analysis_manifest.tsv",
        "workflow/main.nf",
    ):
        if not (root / required).is_file():
            failures.append(f"missing required repository file: {required}")

    if args.require_bulk and missing_bulk:
        failures.extend(f"missing bulk input: {path}" for path in missing_bulk)
    if failures:
        print("FAIL: repository verification", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1
    if missing_bulk:
        print(
            "PASS: committed repository files verified; "
            f"{len(missing_bulk)} checksum-pinned bulk inputs are not installed"
        )
    else:
        print("PASS: committed repository files and all bulk inputs verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
