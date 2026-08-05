#!/usr/bin/env python3
"""Write deterministic checksum manifests for control artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


EXCLUDED = {"SHA256SUMS", "run_manifest.json"}


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "directories",
        nargs="*",
        type=Path,
        default=[
            root / "data/metadata/samples/controls",
            root / "data/processed/metadata/controls",
            root / "analysis/v3/control_audit",
            root / "analysis/v3/control_sensitivity",
        ],
    )
    args = parser.parse_args()
    for directory in args.directories:
        directory = directory.resolve()
        if not directory.is_dir():
            raise FileNotFoundError(directory)
        paths = sorted(
            path
            for path in directory.rglob("*")
            if path.is_file() and path.name not in EXCLUDED
        )
        records = [
            {
                "path": path.relative_to(directory).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": digest(path),
            }
            for path in paths
        ]
        (directory / "SHA256SUMS").write_text(
            "".join(
                f"{record['sha256']}  {record['path']}\n"
                for record in records
            ),
            encoding="utf-8",
        )
        (directory / "run_manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "artifact_root": (
                        directory.relative_to(root).as_posix()
                        if directory.is_relative_to(root)
                        else str(directory)
                    ),
                    "files": records,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"{directory}: {len(records)} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
