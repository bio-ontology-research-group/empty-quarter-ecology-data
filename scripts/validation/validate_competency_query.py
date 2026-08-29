#!/usr/bin/env python3
"""Execute the manuscript field-XRF competency query and archive evidence."""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import json
from pathlib import Path

from rdflib import Graph


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--sites", type=Path, required=True)
    parser.add_argument("--xrf", type=Path, required=True)
    parser.add_argument("--query", type=Path, required=True)
    parser.add_argument("--expected-rows", type=int, default=46)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    inputs = {
        "base": args.base.resolve(),
        "sites": args.sites.resolve(),
        "xrf": args.xrf.resolve(),
        "query": args.query.resolve(),
    }
    for role, path in inputs.items():
        if not path.is_file():
            parser.error(f"{role} input is missing: {path}")

    graph = Graph()
    for role in ("base", "sites", "xrf"):
        graph.parse(inputs[role])
    query_bytes = inputs["query"].read_bytes()
    query_text = query_bytes.decode("utf-8")
    result = graph.query(query_text)
    variables = [str(variable) for variable in result.vars]
    rows = [
        ["" if value is None else str(value) for value in row]
        for row in result
    ]

    if len(rows) != args.expected_rows:
        raise SystemExit(
            f"FAIL: field-XRF query returned {len(rows)} rows; "
            f"expected {args.expected_rows}"
        )
    process_index = variables.index("processLabel")
    site_index = variables.index("siteLabel")
    processes = sorted({row[process_index] for row in rows})
    sites = sorted({row[site_index] for row in rows})
    if len(processes) != 2 or sites != ["Site 10"]:
        raise SystemExit(
            "FAIL: expected two field-XRF processes targeting only Site 10; "
            f"found processes={processes!r}, sites={sites!r}"
        )

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    results_path = output_dir / "field_xrf_site10_results.tsv"
    query_snapshot_path = output_dir / "field_xrf_site10.rq"
    query_snapshot_path.write_bytes(query_bytes)
    with results_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(variables)
        writer.writerows(rows)

    evidence = {
        "schema_version": "1.0",
        "status": "passed",
        "engine": {
            "name": "RDFLib",
            "version": importlib.metadata.version("rdflib"),
        },
        "graph_triples_after_union": len(graph),
        "expected_rows": args.expected_rows,
        "observed_rows": len(rows),
        "distinct_process_labels": processes,
        "site_labels": sites,
        "query_snapshot": {
            "file": query_snapshot_path.name,
            "bytes": query_snapshot_path.stat().st_size,
            "sha256": sha256(query_snapshot_path),
        },
        "inputs": {
            role: {
                "path": str(path),
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
            for role, path in inputs.items()
        },
    }
    evidence_path = output_dir / "competency_query_validation.json"
    evidence_path.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    checksum_path = output_dir / "SHA256SUMS"
    with checksum_path.open("w", encoding="utf-8") as handle:
        for path in (evidence_path, results_path, query_snapshot_path):
            handle.write(f"{sha256(path)}  {path.name}\n")

    print(
        "PASS: field-XRF Site 10 query returned "
        f"{len(rows)} rows from {len(processes)} processes"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
