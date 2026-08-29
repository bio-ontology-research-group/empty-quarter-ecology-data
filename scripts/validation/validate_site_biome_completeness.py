#!/usr/bin/env python3
"""Closed-world completeness gate for sampling-site biome and feature records.

The site individuals encode their biome and environmental feature as OWL class
restrictions on the individual, not as simple triples::

    <RAK_1000001> rdf:type [ owl:onProperty <RAK_2000001> ;
                             owl:someValuesFrom <ENVO_01000179> ] .

ShEx matches triple patterns, so no shipped shape can test that every site
actually carries those restrictions; the manuscript previously claimed such a
shape existed.  This gate supplies the missing check directly: every
``RAK_0000002`` individual must carry at least one ``RAK_2000001`` (has biome)
restriction and at least one ``RAK_2000002`` (has environmental feature)
restriction, and every filler must be an ENVO term.

Exit status is 0 when the module is complete and 1 otherwise, so the gate can
be wired into the validation stage.  It reads the RDF/XML serialization
directly and needs no triple store.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from xml.etree import ElementTree

RDF = "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}"
OWL = "{http://www.w3.org/2002/07/owl#}"
RDFS = "{http://www.w3.org/2000/01/rdf-schema#}"

KB = "https://rubalkhali.science/kb/"
ENVO = "http://purl.obolibrary.org/obo/ENVO_"

SAMPLING_SITE = KB + "RAK_0000002"
HAS_BIOME = KB + "RAK_2000001"
HAS_FEATURE = KB + "RAK_2000002"


def site_records(module: Path) -> dict[str, dict[str, list[str]]]:
    """Map each sampling-site IRI to its restriction fillers by property."""
    tree = ElementTree.parse(module)
    records: dict[str, dict[str, list[str]]] = {}
    for individual in tree.getroot().findall(f"{OWL}NamedIndividual"):
        iri = individual.get(f"{RDF}about")
        if iri is None:
            continue
        types = {
            element.get(f"{RDF}resource")
            for element in individual.findall(f"{RDF}type")
            if element.get(f"{RDF}resource")
        }
        if SAMPLING_SITE not in types:
            continue
        fillers: dict[str, list[str]] = {HAS_BIOME: [], HAS_FEATURE: []}
        for element in individual.findall(f"{RDF}type"):
            restriction = element.find(f"{OWL}Restriction")
            if restriction is None:
                continue
            on_property = restriction.find(f"{OWL}onProperty")
            some_values = restriction.find(f"{OWL}someValuesFrom")
            if on_property is None or some_values is None:
                continue
            prop = on_property.get(f"{RDF}resource")
            filler = some_values.get(f"{RDF}resource")
            if prop in fillers and filler:
                fillers[prop].append(filler)
        records[iri] = fillers
    return records


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--module",
        type=Path,
        default=Path(__file__).resolve().parents[2]
        / "data/processed/semantics/ontology/rubalkhali_sites.owl",
    )
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args()

    if not args.module.is_file():
        print(f"FAIL: site module is absent: {args.module}", file=sys.stderr)
        return 1

    records = site_records(args.module)
    missing_biome = sorted(iri for iri, f in records.items() if not f[HAS_BIOME])
    missing_feature = sorted(iri for iri, f in records.items() if not f[HAS_FEATURE])
    non_envo = sorted(
        {
            filler
            for fillers in records.values()
            for values in fillers.values()
            for filler in values
            if not filler.startswith(ENVO)
        }
    )

    report = {
        "module": str(args.module),
        "sampling_sites": len(records),
        "sites_missing_biome": missing_biome,
        "sites_missing_environmental_feature": missing_feature,
        "non_envo_fillers": non_envo,
        "distinct_biomes": sorted({f for r in records.values() for f in r[HAS_BIOME]}),
        "distinct_environmental_features": sorted(
            {f for r in records.values() for f in r[HAS_FEATURE]}
        ),
    }
    failed = bool(missing_biome or missing_feature or non_envo) or not records
    report["status"] = "failed" if failed else "passed"

    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if failed:
        print(json.dumps(report, indent=2, sort_keys=True), file=sys.stderr)
        print("FAIL: site biome/feature completeness gate", file=sys.stderr)
        return 1
    print(
        f"PASS: {len(records)} sampling sites each carry a biome and an "
        f"environmental-feature restriction with ENVO fillers"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
