#!/usr/bin/env python3
"""Check real release control identities and measurement-chain entailments."""
import argparse
import hashlib
import json
from pathlib import Path

from rdflib import Graph, Namespace, RDF

from materialize import Endpoint, PREFIXES, dump_json, iri

RAK = Namespace("https://rubalkhali.science/kb/")
SIO = Namespace("http://semanticscience.org/resource/")
ROLES = (RAK.RAK_0000304, RAK.RAK_0000305, RAK.RAK_0000306, RAK.RAK_0000307)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--asserted-graph", required=True)
    parser.add_argument("--inferred-graph", required=True)
    parser.add_argument("--controls", type=Path, required=True,
                        help="Fresh canonical controls Turtle from the manifested release")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("Refusing to overwrite witness evidence")
    endpoint = Endpoint(args.endpoint, [], 7200)
    asserted, inferred = iri(args.asserted_graph), iri(args.inferred_graph)
    source = f"FROM {asserted} FROM {inferred}"
    controls = Graph().parse(str(args.controls), format="turtle")
    expected = {(str(role), str(kind)) for kind in ROLES for role in controls.subjects(RDF.type, kind)}
    if not expected:
        raise ValueError("Canonical controls file contains no role inventory")
    role_values = " ".join(iri(str(kind)) for kind in ROLES)
    rows = endpoint.query(PREFIXES + f"SELECT DISTINCT ?role ?kind WHERE {{ GRAPH {asserted} {{ ?role rdf:type ?kind }} VALUES ?kind {{ {role_values} }} }}")["results"]["bindings"]
    actual = {(row["role"]["value"], row["kind"]["value"]) for row in rows}
    role_checks = []
    for role in sorted(str(r) for r in controls.subjects(RDF.type, RAK.RAK_0000307)):
        negative = endpoint.query(PREFIXES + f"ASK {source} {{ {iri(role)} a {iri(str(RAK.RAK_0000305))} }}")["boolean"]
        forbidden = endpoint.query(PREFIXES + f"ASK {source} {{ {iri(role)} a ?kind . VALUES ?kind {{ {iri(str(RAK.RAK_0000304))} {iri(str(RAK.RAK_0000306))} }} }}")["boolean"]
        role_checks.append({"role": role, "negative_ancestor_present": bool(negative),
                            "positive_or_extraction_type_present": bool(forbidden)})
    # Count every asserted chain witness missing its conclusion from the union.
    # Record examples whose conclusion was supplied by materialization itself.
    chains = {}
    for last, label in (("SIO_000291", "target"), ("SIO_000230", "input")):
        body = (f"GRAPH {asserted} {{ ?quality {iri(str(SIO.SIO_000216))} ?value . "
                f"?value {iri(str(SIO.SIO_000232))} ?process . ?process {iri(str(SIO[last]))} ?bearer }}")
        missing = endpoint.query(f"SELECT (COUNT(*) AS ?n) WHERE {{ {body} FILTER NOT EXISTS {{ GRAPH {asserted} {{ ?quality {iri(str(SIO.SIO_000011))} ?bearer }} }} FILTER NOT EXISTS {{ GRAPH {inferred} {{ ?quality {iri(str(SIO.SIO_000011))} ?bearer }} }} }}")
        count = endpoint.query(f"SELECT (COUNT(*) AS ?n) WHERE {{ {body} }}")
        witness = endpoint.query(f"SELECT DISTINCT ?quality ?value ?process ?bearer WHERE {{ {body} GRAPH {inferred} {{ ?quality {iri(str(SIO.SIO_000011))} ?bearer }} }} ORDER BY ?quality ?value ?process ?bearer LIMIT 10")
        chains[label] = {"asserted_chain_witnesses": int(count["results"]["bindings"][0]["n"]["value"]),
                         "missing_conclusions": int(missing["results"]["bindings"][0]["n"]["value"]),
                         "inferred_examples": witness["results"]["bindings"]}
    overlap = endpoint.query(f"SELECT (COUNT(*) AS ?n) WHERE {{ GRAPH {asserted} {{ ?s ?p ?o }} GRAPH {inferred} {{ ?s ?p ?o }} }}")
    n_overlap = int(overlap["results"]["bindings"][0]["n"]["value"])
    record = {"controls_sha256": hashlib.sha256(args.controls.read_bytes()).hexdigest(),
              "expected_asserted_role_types": len(expected), "actual_asserted_role_types": len(actual),
              "missing_role_types": sorted(expected - actual), "unexpected_role_types": sorted(actual - expected),
              "pcr_role_checks": role_checks, "measurement_chains": chains,
              "asserted_inferred_overlap": n_overlap,
              "scope": "Canonical asserted control-role inventory, derived PCR negative ancestry, forbidden PCR positive/extraction types, and project measurement-chain consequences; not complete OWL consistency."}
    passed = (actual == expected and bool(role_checks) and n_overlap == 0
              and all(x["negative_ancestor_present"] and not x["positive_or_extraction_type_present"] for x in role_checks)
              and all(x["asserted_chain_witnesses"] > 0 and x["missing_conclusions"] == 0 for x in chains.values()))
    record["status"] = "passed" if passed else "failed"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    dump_json(args.output, record)
    print(json.dumps({"status": record["status"], "pcr_roles": len(role_checks), "role_types": len(actual)}), flush=True)
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
