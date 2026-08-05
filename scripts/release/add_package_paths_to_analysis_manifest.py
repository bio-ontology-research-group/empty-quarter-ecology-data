#!/usr/bin/env python3
"""Add and verify reviewer-package paths in the analysis manifest."""

from __future__ import annotations

import argparse
import csv
import os
import tempfile
from pathlib import Path


def package_path(source: str, status: str) -> str:
    if status == "retired":
        return "NOT_INCLUDED_RETIRED"
    exceptions = {
        "data-paper/scripts/generate_env_table.py":
            "scripts/metadata/generate_env_table.py",
        "analysis/v3/primer_identity_audit/source_paths.tsv":
            "evidence/primer-identity/source_paths.tsv",
    }
    if source in exceptions:
        return exceptions[source]
    if source.startswith("data-paper/zenodo/"):
        return source.removeprefix("data-paper/zenodo/")
    if source.startswith("data-paper/scripts/"):
        return "scripts/validation/" + Path(source).name
    if source.startswith("data/metadata/"):
        return "metadata/" + source.removeprefix("data/metadata/")
    if source.startswith("data/release/"):
        return "evidence/release/" + source.removeprefix("data/release/")
    if source.startswith("analysis/"):
        return "scripts/analysis/" + Path(source).name
    if source.startswith(("scripts/", "workflow/")):
        return source
    raise ValueError(f"no package-path rule for {source!r}")


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manifest", type=Path,
        default=root / "workflow/analysis_manifest.tsv",
    )
    parser.add_argument(
        "--stage", type=Path,
        default=root / "data-paper/zenodo",
    )
    args = parser.parse_args()
    manifest = args.manifest.resolve()
    stage = args.stage.resolve()

    with manifest.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        rows = list(reader)
        fields = list(reader.fieldnames or [])
    if "package_path" not in fields:
        fields.insert(fields.index("decision_rule"), "package_path")

    missing: list[str] = []
    for row in rows:
        mapped = [
            package_path(source, row["status"])
            for source in row["implementation"].split(";")
        ]
        if row["status"] == "retired":
            mapped = ["NOT_INCLUDED_RETIRED"]
        row["package_path"] = ";".join(mapped)
        for relative in mapped:
            if relative == "NOT_INCLUDED_RETIRED" or relative.startswith("EXTERNAL:"):
                continue
            if not (stage / relative).is_file():
                missing.append(f"{row['analysis']}: {relative}")
    if missing:
        raise SystemExit("package paths are absent:\n" + "\n".join(missing))

    descriptor, temporary = tempfile.mkstemp(
        prefix=".analysis_manifest.", suffix=".tsv", dir=manifest.parent,
        text=True,
    )
    try:
        with os.fdopen(descriptor, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle, fieldnames=fields, delimiter="\t", lineterminator="\n"
            )
            writer.writeheader()
            writer.writerows(rows)
            handle.flush()
            os.fsync(handle.fileno())
        Path(temporary).replace(manifest)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    print(f"PASS: verified package paths for {len(rows)} analyses")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
