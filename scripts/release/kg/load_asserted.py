#!/usr/bin/env python3
"""Load only checksum-listed fresh modules into an empty release asserted graph."""
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlencode
from urllib.request import urlopen

from kg_admin import execute
from prepare_wkt_import import prepare

GRAPH = "https://rubalkhali.science/graph/asserted/3.0.0"


def loader_input(inputs, source, record):
    """Keep manifested bytes intact; derive only the known site loader copy."""
    if record['file'] != 'rubalkhali_sites.owl':
        return '/release-inputs/scientific', None
    directory = inputs.parent / 'loader'
    directory.mkdir(exist_ok=False)
    adaptation = prepare(source, directory / source.name, 'xml')
    if (adaptation['source_sha256'] != record['sha256']
            or adaptation['typed_point_whitespace_changes'] != 70):
        raise ValueError('site loader derivation differs from the frozen 70-point input')
    return '/release-inputs/loader', adaptation


def count(endpoint):
    params = urlencode({"query": f"SELECT (COUNT(*) AS ?n) FROM <{GRAPH}> WHERE {{?s ?p ?o}}",
                        "format": "application/sparql-results+json"})
    with urlopen(endpoint + "?" + params, timeout=120) as response:
        data = json.load(response)
    return int(data["results"]["bindings"][0]["n"]["value"])


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--container", required=True)
    p.add_argument("--endpoint", required=True)
    args = p.parse_args()
    root = args.root.resolve()
    if root.parent != Path("/data/empty-quarter-releases"):
        p.error("explicit release root required")
    out = root / "evidence" / "asserted_load"
    out.mkdir(exist_ok=False)
    inputs = root / "inputs" / "scientific"
    manifest = json.loads((inputs / "manifest.json").read_text())
    if manifest["version"] != "3.0.0" or manifest["module_count"] != 16:
        raise ValueError("unexpected release manifest")
    if count(args.endpoint) != 0:
        raise ValueError("asserted target is not empty; no clearing is permitted")
    records = manifest["records"]
    if len(records) != 16 or len({r["file"] for r in records}) != 16:
        raise ValueError("module inventory is not exactly sixteen unique files")
    statements, adaptations = [], []
    for record in records:
        name = record["file"]
        if not re.fullmatch(r"[A-Za-z0-9_.-]+\.(owl|ttl)", name) or record["load_graph"] != GRAPH:
            raise ValueError("invalid module name or graph")
        source = inputs / name
        digest = hashlib.file_digest(source.open("rb"), "sha256").hexdigest() if hasattr(hashlib, "file_digest") else None
        if digest is None:
            h = hashlib.sha256()
            with source.open("rb") as stream:
                for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
                    h.update(block)
            digest = h.hexdigest()
        if source.stat().st_size != record["bytes"] or digest != record["sha256"]:
            raise ValueError(f"hash/size mismatch: {name}")
        directory, adaptation = loader_input(inputs, source, record)
        if adaptation is not None:
            adaptations.append(adaptation)
        statements.append(f"ld_dir('{directory}', '{name}', '{GRAPH}');")
    if len(adaptations) != 1:
        raise ValueError('exactly one source-preserving site import adaptation is required')
    (out / 'import_adaptations.json').write_text(json.dumps(adaptations, indent=2) + '\n')
    sql = "\n".join(statements) + "\nrdf_loader_run();\ncheckpoint;\n"
    (out / "load.sql").write_text(sql)
    started = dt.datetime.now(dt.timezone.utc).isoformat()
    print(f"Loading sixteen hash-verified modules at {started}", flush=True)
    output, failed = execute(args.container, sql, timeout=14400)
    (out / "load.log").write_text(output)
    if failed:
        raise RuntimeError("loader returned an SQL error; see load.log")
    audit = ("SELECT LL_FILE, LL_STATE, LL_ERROR FROM DB.DBA.LOAD_LIST;\n"
             "SELECT concat('LOAD_FAILURES=', CAST(COUNT(*) AS VARCHAR)) AS gate "
             "FROM DB.DBA.LOAD_LIST WHERE LL_STATE <> 2 OR LL_ERROR IS NOT NULL;\n")
    output, failed = execute(args.container, audit)
    (out / "loader_inventory.log").write_text(output)
    if failed or not re.search(r"(?m)^LOAD_FAILURES=0\s*$", output):
        raise RuntimeError("loader inventory reports failures or is unverifiable")
    triples = count(args.endpoint)
    if triples < 44_528_482:
        raise RuntimeError("loaded graph is smaller than the validated taxonomy alone")
    report = {"version": "3.0.0", "started_utc": started,
              "completed_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
              "graph": GRAPH, "module_count": len(records), "triples": triples,
              "input_manifest_sha256": hashlib.sha256((inputs / "manifest.json").read_bytes()).hexdigest(),
              "import_adaptations": adaptations,
              "passed": True, "production_mutated": False}
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    main()
