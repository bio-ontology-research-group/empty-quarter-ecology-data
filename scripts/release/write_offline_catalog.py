#!/usr/bin/env python3
"""Map frozen release import/document IRIs to local module serializations."""
import argparse
import json
from pathlib import Path
from xml.etree import ElementTree as ET


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--inputs", type=Path, required=True)
    p.add_argument("--references", type=Path, required=True)
    a = p.parse_args()
    manifest = json.loads((a.inputs / "manifest.json").read_text())
    files = {r["file"] for r in manifest["records"]}
    base = "https://rubalkhali.science/kb/"
    aliases = {}
    for name in sorted(files):
        aliases[base + name] = name
        if name.endswith(".ttl"):
            aliases[base + name[:-4] + ".owl"] = name
    aliases[base] = "rubalkhali.owl"
    aliases[manifest["version_iri"]] = "rubalkhali.owl"
    refs = json.loads(a.references.read_text())["references"]
    for ref in refs:
        if ref["file"] not in files:
            continue
        for ontology in ref["ontology_declarations"]:
            if ontology["ontology_iri"]:
                aliases[ontology["ontology_iri"]] = ref["file"]
            for ann in ontology["annotations"]:
                if ann["predicate"].endswith("}versionIRI") and ann["resource"]:
                    aliases[ann["resource"]] = ref["file"]
    aliases["http://semanticscience.org/ontology/sio/v1.59/sio-release.owl"] = "sio.owl"
    ns = "urn:oasis:names:tc:entity:xmlns:xml:catalog"
    ET.register_namespace("", ns)
    root = ET.Element("{" + ns + "}catalog", {"prefer": "public"})
    for iri, name in sorted(aliases.items()):
        ET.SubElement(root, "{" + ns + "}uri", {"name": iri, "uri": name})
    ET.indent(root)
    ET.ElementTree(root).write(a.inputs / "catalog-v001.xml", encoding="UTF-8", xml_declaration=True)
    print(f"Wrote {len(aliases)} offline IRI mappings for {len(files)} RDF modules")


if __name__ == "__main__":
    main()
