#!/usr/bin/env python3
"""Record and install an approved root-subject-only release metadata correction."""
import argparse
import hashlib
import json
import shutil
from pathlib import Path
from rdflib import Graph, URIRef, OWL, DCTERMS
from rdflib.compare import isomorphic


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--workspace", type=Path, required=True)
    a = p.parse_args()
    w = a.workspace
    old_path = w / "release_inputs/rubalkhali.owl"
    new_path = w / "rubalkhali_metadata_corrected.owl"
    old = Graph().parse(old_path, format="xml")
    new = Graph().parse(new_path, format="xml")
    root = URIRef("https://rubalkhali.science/kb/")
    allowed = {OWL.versionInfo, URIRef("http://purl.org/pav/version"), URIRef("http://purl.org/pav/previousVersion"), DCTERMS.modified}
    old_root = set(old.triples((root, None, None)))
    new_root = set(new.triples((root, None, None)))
    removed = old_root - new_root
    added = new_root - old_root
    assert removed and added
    assert all(s == root and p in allowed for s, p, o in removed | added)
    for triple in removed:
        old.remove(triple)
    for triple in added:
        new.remove(triple)
    assert isomorphic(old, new)
    def serialize(triples):
        return "\n".join(" ".join(term.n3() for term in t) + " ." for t in sorted(triples, key=lambda t: tuple(map(str, t))))
    graph = "https://rubalkhali.science/graph/asserted/3.0.0"
    update = (f"DELETE DATA {{ GRAPH <{graph}> {{\n{serialize(removed)}\n}} }};\n"
              f"INSERT DATA {{ GRAPH <{graph}> {{\n{serialize(added)}\n}} }};\n")
    (w / "root_metadata_delta.rq").write_text(update)
    old_sha = hashlib.sha256(old_path.read_bytes()).hexdigest()
    new_sha = hashlib.sha256(new_path.read_bytes()).hexdigest()
    report = dict(scope="root-subject annotation correction only; no scientific entity axiom changes", old_sha256=old_sha, new_sha256=new_sha,
                  removed_triples=len(removed), added_triples=len(added), net_asserted_triples=len(added)-len(removed),
                  delete_nt=serialize(removed), insert_nt=serialize(added), remote_update_executed=False)
    (w / "root_metadata_delta.json").write_text(json.dumps(report, indent=2) + "\n")
    shutil.copy2(old_path, w / "source_baseline/rubalkhali_initial_release_stamp.owl")
    shutil.copy2(new_path, old_path)
    manifest_path = w / "release_inputs/manifest.json"
    shutil.copy2(manifest_path, w / "fresh_modules_manifest.initial_metadata.json")
    manifest = json.loads(manifest_path.read_text())
    for row in manifest["records"]:
        if row["file"] == "rubalkhali.owl":
            row.update(path=str(new_path.relative_to(w)), sha256=new_sha, bytes=new_path.stat().st_size,
                       derivation="post-build root-subject metadata-only normalization", prior_sha256=old_sha)
    manifest["metadata_correction"] = report
    for path in (manifest_path, w / "fresh_modules_manifest.json"):
        path.write_text(json.dumps(manifest, indent=2) + "\n")
    (w / "release_inputs/SHA256SUMS").write_text("".join(r["sha256"] + "  " + r["file"] + "\n" for r in manifest["records"]))
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
