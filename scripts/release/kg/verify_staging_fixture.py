#!/usr/bin/env python3
"""Run real SPARQL rule fixtures only in a release-test named-graph namespace."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

from rdflib import Graph, Namespace, RDF, RDFS

from materialize import Endpoint, iri, PREFIXES, dump_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--sql-command-file", type=Path, required=True)
    parser.add_argument("--graph-prefix", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"urn:eq:release-test:[A-Za-z0-9:._-]+", args.graph_prefix):
        raise ValueError("Fixture graph must use isolated urn:eq:release-test: namespace")
    asserted, inferred = args.graph_prefix + ":asserted", args.graph_prefix + ":inferred"
    endpoint = Endpoint(args.endpoint, json.loads(args.sql_command_file.read_text()), 7200)
    if endpoint.count(asserted) or endpoint.count(inferred):
        raise ValueError("Fixture graphs must be new and empty")
    fixture = Path(__file__).with_name("entailment_fixture.ttl")
    graph = Graph().parse(str(fixture), format="turtle")
    ex = Namespace("urn:eq:release-test:entity:")
    for index in range(40):
        graph.add((ex[f"C{index}"], RDFS.subClassOf, ex[f"C{index+1}"]))
    graph.add((ex.long, RDF.type, ex.C0))
    nt = graph.serialize(format="nt")
    if isinstance(nt, bytes): nt = nt.decode()
    # The deployed Virtuoso rejects blank-node constants in INSERT DATA;
    # its Turtle loader preserves the fixture's RDF lists without skolemization.
    escaped = nt.replace("\\", "\\\\").replace("'", "''")
    endpoint.sql(f"DB.DBA.TTLP('{escaped}', '', '{asserted}', 0);\nCOMMIT WORK;")
    subprocess.run([sys.executable, str(Path(__file__).with_name("materialize.py")),
                    "--endpoint", args.endpoint, "--sql-command-file", str(args.sql_command_file),
                    "--asserted-graph", asserted, "--inferred-graph", inferred,
                    "--output-dir", str(args.output_dir), "--staging-only"], check=True)
    inferred_tests = {
        "inverse_property_chain": "<urn:eq:release-test:inverse-chain:start> <urn:eq:release-test:inverse-chain:result> <urn:eq:release-test:inverse-chain:end>",
        "measurement_chain_3": "<urn:eq:release-test:entity:quality> <http://semanticscience.org/resource/SIO_000011> <urn:eq:release-test:entity:specimen>",
        "part_target_chain_2": "<urn:eq:release-test:entity:measurementPart> <http://semanticscience.org/resource/SIO_000291> <urn:eq:release-test:entity:specimen>",
        "long_hierarchy": "<urn:eq:release-test:entity:long> a <urn:eq:release-test:entity:C40>",
        "pcr_negative_role": "<urn:eq:release-test:entity:pcr_role> a <https://rubalkhali.science/kb/RAK_0000305>",
        "transitive_cycle_self": "<urn:eq:release-test:entity:a> <urn:eq:release-test:entity:cycle> <urn:eq:release-test:entity:a>",
        "intersection": "<urn:eq:release-test:entity:s> a <urn:eq:release-test:entity:Intersection>",
        "some_values_existing": "<urn:eq:release-test:entity:s> a <urn:eq:release-test:entity:KnownSome>",
    }
    forbidden = {
        "no_reversed_chain_conclusion": "<urn:eq:release-test:inverse-chain:end> <urn:eq:release-test:inverse-chain:result> <urn:eq:release-test:inverse-chain:start>",
        "no_pcr_extraction_role": "<urn:eq:release-test:entity:pcr_role> a <https://rubalkhali.science/kb/RAK_0000306>",
        "no_pcr_positive_role": "<urn:eq:release-test:entity:pcr_role> a <https://rubalkhali.science/kb/RAK_0000304>",
        "no_existential_witness": "<urn:eq:release-test:entity:unwitnessed> <urn:eq:release-test:entity:missing> ?anything",
        "no_unclaimed_equality": "<urn:eq:release-test:entity:alias> <urn:eq:release-test:entity:p> <urn:eq:release-test:entity:o>",
    }
    results = {}
    for name, body in inferred_tests.items():
        results[name] = bool(endpoint.query(PREFIXES + f"ASK {{ GRAPH {iri(inferred)} {{ {body} }} }}")["boolean"])
        results[name + "_absent_from_asserted"] = not endpoint.query(PREFIXES + f"ASK {{ GRAPH {iri(asserted)} {{ {body} }} }}")["boolean"]
    for name, body in forbidden.items():
        results[name] = not endpoint.query(PREFIXES + f"ASK FROM {iri(asserted)} FROM {iri(inferred)} {{ {body} }}")["boolean"]
    overlap = endpoint.query(f"SELECT (COUNT(*) AS ?n) WHERE {{ GRAPH {iri(asserted)} {{ ?s ?p ?o }} GRAPH {iri(inferred)} {{ ?s ?p ?o }} }}")
    results["asserted_inferred_disjoint"] = int(overlap["results"]["bindings"][0]["n"]["value"]) == 0
    materialization = json.loads((args.output_dir / "materialization.json").read_text())
    results["operational_pass_limit_exceeds_three"] = materialization["maximum_passes_is_failure_limit"] > 3
    results["converged_complete_zero_pass"] = materialization["passes"][-1]["new_triples"] == 0
    record = {"fixture_sha256": hashlib.sha256(fixture.read_bytes()).hexdigest(),
              "long_hierarchy_edges": 40, "asserted_triples": len(graph), "checks": results,
              "status": "passed" if all(results.values()) else "failed"}
    dump_json(args.output_dir / "fixture_verification.json", record)
    print(json.dumps(record, indent=2), flush=True)
    if not all(results.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
