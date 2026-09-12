#!/usr/bin/env python3
"""Hash reference ontology bytes and their explicit version declarations."""
import argparse
import hashlib
import json
from pathlib import Path
from xml.etree import ElementTree as ET


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    records = []
    for path in sorted(args.reference_dir.glob("*.owl")):
        h = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1048576), b""):
                h.update(chunk)
        declarations = []
        for event, elem in ET.iterparse(path, events=("end",)):
            if elem.tag == "{http://www.w3.org/2002/07/owl#}Ontology":
                declarations.append({"ontology_iri": elem.get("{http://www.w3.org/1999/02/22-rdf-syntax-ns#}about"),
                                     "annotations": [{"predicate": child.tag, "resource": child.get("{http://www.w3.org/1999/02/22-rdf-syntax-ns#}resource"), "text": child.text} for child in elem]})
                break
        records.append({"file": path.name, "bytes": path.stat().st_size, "sha256": h.hexdigest(), "ontology_declarations": declarations})
    args.output.write_text(json.dumps({"scope": "Exact cached scientific reference inputs; no remote ontology dereferencing", "references": records}, indent=2) + "\n")


if __name__ == "__main__":
    main()
