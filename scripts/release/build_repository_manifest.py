#!/usr/bin/env python3
"""Build or verify the exhaustive manifest of Git-tracked repository files."""

from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import tempfile
from pathlib import Path


MANIFEST = "FILE_MANIFEST.tsv"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def tracked_paths(root: Path) -> list[Path]:
    output = subprocess.check_output(
        ["git", "-C", str(root), "ls-files", "-z", "--cached"]
    )
    relative_paths = sorted(
        item.decode("utf-8")
        for item in output.split(b"\0")
        if item and item.decode("utf-8") != MANIFEST
    )
    paths: list[Path] = []
    for relative in relative_paths:
        path = root / relative
        if path.is_symlink() or not path.is_file():
            raise SystemExit(f"tracked path is missing or not a regular file: {relative}")
        paths.append(path)
    return paths


def render(root: Path) -> str:
    lines = ["path\tbytes\tsha256"]
    for path in tracked_paths(root):
        lines.append(
            f"{path.relative_to(root)}\t{path.stat().st_size}\t{sha256(path)}"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", type=Path, default=Path.cwd())
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    expected = render(root)
    manifest = root / MANIFEST

    if not args.write:
        if not manifest.is_file() or manifest.read_text(encoding="utf-8") != expected:
            raise SystemExit("FILE_MANIFEST.tsv is absent or stale; rerun with --write")
        print(f"PASS: verified {expected.count(chr(10)) - 1} tracked files")
        return 0

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{MANIFEST}.", dir=root, text=True
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(expected)
        os.replace(temporary_name, manifest)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)
    print(f"PASS: checksummed {expected.count(chr(10)) - 1} tracked files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
