#!/usr/bin/env python3
"""Finite RDF rule closure for a release-local Virtuoso staging database.

This is a documented rule subset, not an OWL profile/consistency reasoner.
The asserted graph is immutable; only its non-asserted consequences enter the
inferred graph. No existential witnesses or datatype equalities are generated.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import re
import subprocess
import time
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from rdflib import BNode, Graph, Literal, OWL, RDF, RDFS, URIRef
import rdflib

VERSION = "rak-finite-rules-1.5.0"
PREFIXES = "\n".join(f"PREFIX {name}: <{iri}>" for name, iri in
                     (("rdf", RDF), ("rdfs", RDFS), ("owl", OWL))) + "\n"
SCHEMA_PREDICATES = (RDFS.subClassOf, RDFS.subPropertyOf, RDFS.domain, RDFS.range,
                     OWL.equivalentClass, OWL.equivalentProperty, OWL.inverseOf,
                     OWL.propertyChainAxiom, OWL.onProperty, OWL.someValuesFrom,
                     OWL.allValuesFrom, OWL.hasValue, OWL.intersectionOf,
                     OWL.unionOf, OWL.oneOf, OWL.disjointWith, OWL.complementOf,
                     OWL.imports, RDF.first, RDF.rest, OWL.cardinality,
                     OWL.minCardinality, OWL.maxCardinality, OWL.qualifiedCardinality,
                     OWL.minQualifiedCardinality, OWL.maxQualifiedCardinality,
                     OWL.hasKey, OWL.sameAs, OWL.differentFrom, OWL.disjointUnionOf,
                     OWL.propertyDisjointWith, OWL.hasSelf)
SCHEMA_TYPES = (OWL.TransitiveProperty, OWL.SymmetricProperty, OWL.Restriction,
                OWL.FunctionalProperty, OWL.InverseFunctionalProperty,
                OWL.ReflexiveProperty, OWL.IrreflexiveProperty,
                OWL.AsymmetricProperty, OWL.AllDisjointClasses,
                OWL.AllDisjointProperties, OWL.NegativePropertyAssertion)
EXCLUSIONS = {
    "owl_profile_completeness": "No claim of full OWL-Horst, OWL 2 RL, EL or DL reasoning.",
    "existential_generation": "someValuesFrom class membership never fabricates a property edge or witness.",
    "datatype_reasoning": "No datatype value-space equality, facet evaluation, range validation or literal typing.",
    "equality": "No sameAs substitution, functional/inverse-functional equality, keys or cardinality consequences.",
    "classification": "No existential class-subsumption completion; instance-level consequences only for listed rules.",
    "imports": "Only explicitly loaded RDF triples are used; owl:imports is audited and never fetched implicitly.",
    "consistency": "Explicit disjointWith/complement type clashes and owl:Nothing membership are diagnostic checks, not a complete consistency proof.",
    "open_world": "Missing statements do not imply negation; union/restriction rules introduce no selected disjunct or filler.",
}


def iri(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9+.-]*:[^<>\s\"{}|^`\\]*", value):
        raise ValueError(f"Unsafe or invalid graph IRI: {value!r}")
    return f"<{value}>"


@dataclass(frozen=True)
class Rule:
    name: str
    head: str
    body: str

    def update(self, asserted: str, inferred: str, batch_size: int = 0) -> str:
        body = f"{self.body}\nFILTER NOT EXISTS {{ {self.head} }}"
        if batch_size:
            if batch_size < 1:
                raise ValueError("Batch size must be positive")
            variables = " ".join(dict.fromkeys(re.findall(r"\?[A-Za-z][A-Za-z0-9_]*", self.head)))
            body = f"{{ SELECT DISTINCT {variables} WHERE {{\n{body}\n}} LIMIT {batch_size} }}"
        return (PREFIXES + f"INSERT {{ GRAPH {iri(inferred)} {{ {self.head} }} }}\n"
                f"USING {iri(asserted)} USING {iri(inferred)}\nWHERE {{\n"
                f"{body}\n}}")


def read_list(schema: Graph, head):
    values, seen = [], set()
    while head != RDF.nil:
        if head in seen:
            raise ValueError("Cyclic RDF list in schema")
        seen.add(head)
        first, rest = list(schema.objects(head, RDF.first)), list(schema.objects(head, RDF.rest))
        if len(first) != 1 or len(rest) != 1:
            raise ValueError("Malformed RDF list in schema")
        values.append(first[0]); head = rest[0]
    return values


def schema_audit(schema: Graph) -> dict:
    chains = []
    for prop, head in schema.subject_objects(OWL.propertyChainAxiom):
        members = read_list(schema, head)
        if not isinstance(prop, URIRef) or not members:
            raise ValueError("Property chain requires a named output property and a nonempty list")
        operands = []
        for member in members:
            if isinstance(member, URIRef):
                operands.append({"property": str(member), "inverse": False})
            else:
                inverse = list(schema.objects(member, OWL.inverseOf))
                if not isinstance(member, BNode) or len(inverse) != 1 or not isinstance(inverse[0], URIRef):
                    raise ValueError("Anonymous chain operand requires exactly one inverseOf named property")
                operands.append({"property": str(inverse[0]), "inverse": True})
        chains.append({"property": str(prop), "members": operands})
    for predicate in (OWL.intersectionOf, OWL.unionOf, OWL.oneOf):
        for head in schema.objects(None, predicate):
            read_list(schema, head)
    excluded_predicates = (OWL.sameAs, OWL.hasKey, OWL.cardinality, OWL.minCardinality,
                           OWL.maxCardinality, OWL.qualifiedCardinality,
                           OWL.minQualifiedCardinality, OWL.maxQualifiedCardinality,
                           OWL.disjointUnionOf, OWL.propertyDisjointWith, OWL.hasSelf)
    excluded_types = (OWL.FunctionalProperty, OWL.InverseFunctionalProperty,
                      OWL.ReflexiveProperty, OWL.IrreflexiveProperty,
                      OWL.AsymmetricProperty, OWL.AllDisjointClasses,
                      OWL.AllDisjointProperties, OWL.NegativePropertyAssertion)
    return {"schema_triples": len(schema), "property_chains": sorted(chains, key=lambda x: (x['property'], json.dumps(x['members'], sort_keys=True))),
            "chain_lengths": sorted({len(c['members']) for c in chains}),
            "imports": sorted({str(o) for o in schema.objects(None, OWL.imports)}),
            "construct_counts": {str(p): len(list(schema.triples((None, p, None)))) for p in SCHEMA_PREDICATES},
            "excluded_construct_counts": {**{str(p): len(list(schema.triples((None, p, None)))) for p in excluded_predicates},
                                          **{str(t): len(list(schema.subjects(RDF.type, t))) for t in excluded_types}},
            "scope_limits": EXCLUSIONS}


def rules_for(schema: Graph) -> list[Rule]:
    audit = schema_audit(schema)
    rules = [
        Rule("equivalent_class_forward", "?c rdfs:subClassOf ?d .", "?c owl:equivalentClass ?d ."),
        Rule("equivalent_class_reverse", "?d rdfs:subClassOf ?c .", "?c owl:equivalentClass ?d ."),
        Rule("equivalent_property_forward", "?p rdfs:subPropertyOf ?q .", "?p owl:equivalentProperty ?q . FILTER(isIRI(?p) && isIRI(?q))"),
        Rule("equivalent_property_reverse", "?q rdfs:subPropertyOf ?p .", "?p owl:equivalentProperty ?q . FILTER(isIRI(?p) && isIRI(?q))"),
        Rule("subclass_transitive", "?c rdfs:subClassOf ?e .", "?c rdfs:subClassOf ?d . ?d rdfs:subClassOf ?e ."),
        Rule("subproperty_transitive", "?p rdfs:subPropertyOf ?r .", "?p rdfs:subPropertyOf ?q . ?q rdfs:subPropertyOf ?r . FILTER(isIRI(?p) && isIRI(?r))"),
        Rule("subclass_type", "?s rdf:type ?d .", "?s rdf:type ?c . ?c rdfs:subClassOf ?d ."),
        Rule("subproperty_fact", "?s ?q ?o .", "?p rdfs:subPropertyOf ?q . ?s ?p ?o . FILTER(isIRI(?q))"),
        Rule("domain", "?s rdf:type ?c .", "?p rdfs:domain ?c . ?s ?p ?o ."),
        Rule("range_resource", "?o rdf:type ?c .", "?p rdfs:range ?c . ?s ?p ?o . FILTER(!isLiteral(?o))"),
        Rule("inverse_forward", "?o ?q ?s .", "?p owl:inverseOf ?q . ?s ?p ?o . FILTER(isIRI(?q) && !isLiteral(?o))"),
        Rule("inverse_reverse", "?o ?p ?s .", "?p owl:inverseOf ?q . ?s ?q ?o . FILTER(isIRI(?p) && !isLiteral(?o))"),
        Rule("symmetric", "?o ?p ?s .", "?p rdf:type owl:SymmetricProperty . ?s ?p ?o . FILTER(!isLiteral(?o))"),
        Rule("transitive", "?s ?p ?o .", "?p rdf:type owl:TransitiveProperty . ?s ?p ?m . ?m ?p ?o ."),
        Rule("has_value_forward", "?s ?p ?v .", "?s rdf:type ?r . ?r owl:onProperty ?p ; owl:hasValue ?v . FILTER(isIRI(?p))"),
        Rule("has_value_classify", "?s rdf:type ?r .", "?r owl:onProperty ?p ; owl:hasValue ?v . ?s ?p ?v ."),
        Rule("some_values_classify", "?s rdf:type ?r .", "?r owl:onProperty ?p ; owl:someValuesFrom ?c . ?s ?p ?v . ?v rdf:type ?c . FILTER(!isLiteral(?v))"),
        Rule("some_thing_classify", "?s rdf:type ?r .", "?r owl:onProperty ?p ; owl:someValuesFrom owl:Thing . ?s ?p ?v . FILTER(!isLiteral(?v))"),
        Rule("all_values_existing", "?v rdf:type ?c .", "?s rdf:type ?r . ?r owl:onProperty ?p ; owl:allValuesFrom ?c . ?s ?p ?v . FILTER(!isLiteral(?v))"),
        Rule("intersection_eliminate", "?s rdf:type ?c .", "?s rdf:type ?i . ?i owl:intersectionOf ?list . ?list rdf:rest*/rdf:first ?c ."),
        Rule("intersection_introduce", "?s rdf:type ?i .", "?i owl:intersectionOf ?list . ?list rdf:rest*/rdf:first ?c . ?s rdf:type ?c . FILTER NOT EXISTS { ?list rdf:rest*/rdf:first ?missing . FILTER NOT EXISTS { ?s rdf:type ?missing } }"),
        Rule("union_introduce", "?s rdf:type ?u .", "?u owl:unionOf ?list . ?list rdf:rest*/rdf:first ?c . ?s rdf:type ?c ."),
        Rule("enumeration_members", "?s rdf:type ?c .", "?c owl:oneOf ?list . ?list rdf:rest*/rdf:first ?s . FILTER(!isLiteral(?s))"),
    ]
    patterns = sorted({tuple(member["inverse"] for member in chain["members"])
                       for chain in audit["property_chains"]})
    for pattern in patterns:
        length = len(pattern)
        lists, edges = [], []
        for i in range(length):
            operand = f"?inverse{i}" if pattern[i] else f"?p{i}"
            lists.append(f"?l{i} rdf:first {operand} ; rdf:rest " + ("rdf:nil ." if i == length - 1 else f"?l{i+1} ."))
            if pattern[i]:
                lists.append(f"?inverse{i} owl:inverseOf ?p{i} . FILTER(isBlank(?inverse{i}))")
            edges.append(f"?x{i+1} ?p{i} ?x{i} ." if pattern[i] else f"?x{i} ?p{i} ?x{i+1} .")
        filters = " && ".join(["isIRI(?p)"] + [f"isIRI(?p{i})" for i in range(length)])
        body = "?p owl:propertyChainAxiom ?l0 . " + " ".join(lists + edges) + f" FILTER({filters})"
        suffix = "_inverse_" + "_".join(str(i) for i, inverse in enumerate(pattern) if inverse) if any(pattern) else ""
        rules.append(Rule(f"property_chain_length_{length}{suffix}", f"?x0 ?p ?x{length} .", body))
    return rules


def subclass_partitions(rule, classes):
    """Disjoint, exhaustive partitions of the rule's bound class variable."""
    if rule.name != 'subclass_type':
        return [rule]
    variants = [Rule('subclass_type_named_' + hashlib.sha256(str(c).encode()).hexdigest()[:16],
                     rule.head, f'VALUES ?c {{ {iri(str(c))} }}\n' + rule.body)
                for c in sorted(set(classes), key=str) if isinstance(c, URIRef)]
    if any(isinstance(c, BNode) for c in classes):
        variants.append(Rule('subclass_type_anonymous', rule.head, rule.body + '\nFILTER(isBlank(?c))'))
    return variants


def materialize_local(asserted: Graph, max_passes=100, seed=None, batch_size=200000):
    """Small-fixture runner exercising the same SPARQL rule bodies as Virtuoso."""
    import rdflib.plugins.sparql
    # USING resolves the explicitly loaded named graphs, never network imports.
    original_load_setting = rdflib.plugins.sparql.SPARQL_LOAD_GRAPHS
    rdflib.plugins.sparql.SPARQL_LOAD_GRAPHS = False
    try:
        return _materialize_local(asserted, max_passes, seed, batch_size)
    finally:
        rdflib.plugins.sparql.SPARQL_LOAD_GRAPHS = original_load_setting


def _materialize_local(asserted: Graph, max_passes, seed=None, batch_size=200000):
    from rdflib import Dataset
    dataset = Dataset()
    a, i = "urn:rak-test:asserted", "urn:rak-test:inferred"
    for triple in asserted:
        dataset.graph(URIRef(a)).add(triple)
    for triple in seed or ():
        dataset.graph(URIRef(i)).add(triple)
    rules = rules_for(asserted)
    trace = []
    for iteration in range(1, max_passes + 1):
        changes = []
        for logical_rule in rules:
            current = dataset.graph(URIRef(a)) + dataset.graph(URIRef(i))
            classes = set(current.objects(None, RDF.type)) & set(current.subjects(RDFS.subClassOf, None))
            variants = subclass_partitions(logical_rule, classes) if batch_size else [logical_rule]
            for rule in variants:
                before = len(dataset.graph(URIRef(i)))
                while True:
                    previous = len(dataset.graph(URIRef(i)))
                    dataset.update(rule.update(a, i, batch_size))
                    added = len(dataset.graph(URIRef(i))) - previous
                    if batch_size == 0 or added == 0:
                        break
                changes.append(len(dataset.graph(URIRef(i))) - before)
        trace.append(changes)
        if not any(changes):
            return dataset.graph(URIRef(i)), trace
    raise RuntimeError("Materialization did not converge within the operational pass limit")


class Endpoint:
    def __init__(self, url, sql_command, timeout):
        self.url, self.sql_command, self.timeout = url, sql_command, timeout

    def query(self, query):
        request = Request(self.url, data=urlencode({"query": query, "format": "application/sparql-results+json"}).encode(),
                          headers={"Accept": "application/sparql-results+json"})
        with urlopen(request, timeout=self.timeout) as response:
            if response.status != 200:
                raise RuntimeError(f'Incomplete SPARQL HTTP response: status{response.status}')
            flags = {name: response.headers.get(name) for name in
                     ('X-SQL-State', 'X-SQL-Message', 'X-SPARQL-MaxRows')
                     if response.headers.get(name) is not None}
            if flags:
                raise RuntimeError('Partial or row-limited SPARQL response: ' + json.dumps(flags))
            data = response.read()
        return json.loads(data)

    def sql(self, statement):
        result = subprocess.run(self.sql_command, input=statement + "\n", capture_output=True,
                                text=True, timeout=self.timeout, check=False)
        output = result.stdout + result.stderr
        if result.returncode or re.search(r"\*\*\* Error|SQLSTATE|Virtuoso .* Error", output, re.I):
            raise RuntimeError(f"SQL runner failed ({result.returncode}): {output[:1800]}\n...\n{output[-1000:]}")
        return output

    def count(self, graph):
        answer = self.query(f"SELECT (COUNT(*) AS ?n) WHERE {{ GRAPH {iri(graph)} {{ ?s ?p ?o }} }}")
        return int(answer["results"]["bindings"][0]["n"]["value"])

    def active_subclass_types(self, asserted, inferred):
        source = f'FROM {iri(asserted)} FROM {iri(inferred)}'
        body = '?c rdfs:subClassOf ?d . FILTER EXISTS { ?s rdf:type ?c }'
        expected = self.query(PREFIXES + f'SELECT (COUNT(DISTINCT ?c) AS ?n) {source} WHERE {{ {body} }}')
        rows = self.query(PREFIXES + f'SELECT DISTINCT ?c {source} WHERE {{ {body} }}')['results']['bindings']
        if len(rows) != int(expected['results']['bindings'][0]['n']['value']):
            raise RuntimeError('Active class partition query truncated or concurrent data change')
        return [URIRef(row['c']['value']) if row['c']['type'] == 'uri' else BNode(row['c']['value']) for row in rows]

    def schema(self, graph):
        predicates = ",".join(iri(str(p)) for p in SCHEMA_PREDICATES)
        types = ",".join(iri(str(p)) for p in SCHEMA_TYPES)
        body = f"GRAPH {iri(graph)} {{ ?s ?p ?o . FILTER(?p IN ({predicates}) || (?p = {iri(str(RDF.type))} && ?o IN ({types}))) }}"
        expected = int(self.query(f"SELECT (COUNT(*) AS ?n) WHERE {{ {body} }}")["results"]["bindings"][0]["n"]["value"])
        answer = self.query(f"SELECT ?s ?p ?o WHERE {{ {body} }}")
        if len(answer["results"]["bindings"]) != expected:
            raise RuntimeError("Schema response is truncated or asserted graph changed; increase the staging result limit")
        schema = Graph()
        def term(value):
            if value["type"] == "uri": return URIRef(value["value"])
            if value["type"] == "bnode": return BNode(value["value"])
            return Literal(value["value"], lang=value.get("xml:lang"), datatype=value.get("datatype"))
        for row in answer["results"]["bindings"]:
            schema.add(tuple(term(row[k]) for k in ("s", "p", "o")))
        return schema


def diagnostic_queries(asserted, inferred):
    source = f"FROM {iri(asserted)} FROM {iri(inferred)}"
    return {
        "explicit_disjoint_types": PREFIXES + f"SELECT ?s ?a ?b {source} WHERE {{ ?a owl:disjointWith ?b . ?s a ?a, ?b }}",
        "complement_types": PREFIXES + f"SELECT ?s ?a ?b {source} WHERE {{ ?a owl:complementOf ?b . ?s a ?a, ?b }}",
        "nothing_members": PREFIXES + f"SELECT ?s {source} WHERE {{ ?s a owl:Nothing }}",
        "pcr_extraction_role_clash": PREFIXES + f"SELECT ?s {source} WHERE {{ ?s a <https://rubalkhali.science/kb/RAK_0000306>, <https://rubalkhali.science/kb/RAK_0000307> }}",
    }


def dump_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def validate_resume(prior, prior_source, asserted, inferred, asserted_count, rules_hash):
    """Require preserved source/rules and a failed or audited, stopped controller."""
    if prior.get('status') not in ('failed', 'operator_interrupted'):
        raise ValueError("Resume failed/interrupted status does not match")
    if prior['status'] == 'operator_interrupted':
        proof = prior.get('operator_interruption', {})
        if not (proof.get('controller_terminated') and proof.get('all_update_children_completed')
                and proof.get('preserved_running_report_sha256')):
            raise ValueError("Resume interruption evidence does not match")
    expected = {"asserted_graph": asserted,
                "inferred_graph": inferred, "asserted_triples": asserted_count,
                "rules_sha256": rules_hash,
                "generator_sha256": hashlib.sha256(prior_source.read_bytes()).hexdigest()}
    if any(prior.get(key) != value for key, value in expected.items()):
        raise ValueError("Resume source, rules, graph identity or failed status does not match")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--sql-command-file", type=Path, required=True,
                        help="JSON argv list for an administrator-owned stdin SQL wrapper; never copied to logs")
    parser.add_argument("--asserted-graph", required=True)
    parser.add_argument("--inferred-graph", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--max-passes", type=int, default=100)
    parser.add_argument("--timeout-seconds", type=int, default=7200)
    parser.add_argument("--batch-size", type=int, default=200000,
                        help="Maximum distinct conclusion triples per SQL update")
    parser.add_argument("--resume-report", type=Path,
                        help="Preserved failed or audited interrupted report for this immutable graph and positive delta")
    parser.add_argument("--resume-generator", type=Path,
                        help="Preserved exact generator source from the failed run")
    parser.add_argument("--staging-only", action="store_true", required=True,
                        help="Explicit assertion that endpoint is a new isolated staging database")
    args = parser.parse_args()
    if not 1 <= args.batch_size <= 1000000:
        raise ValueError("Batch size must be between1 and1000000")
    if bool(args.resume_report) != bool(args.resume_generator):
        raise ValueError("Resume requires both the failed report and its exact preserved generator")
    if urlparse(args.endpoint).hostname not in ("localhost", "127.0.0.1", "::1"):
        raise ValueError("Only loopback staging endpoints are accepted")
    if args.asserted_graph == args.inferred_graph:
        raise ValueError("Asserted and inferred graphs must differ")
    iri(args.asserted_graph); iri(args.inferred_graph)
    command = json.loads(args.sql_command_file.read_text())
    if not isinstance(command, list) or not command or not all(isinstance(x, str) for x in command):
        raise ValueError("SQL command must be a nonempty JSON string array")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    report_path = args.output_dir / "materialization.json"
    if report_path.exists():
        raise FileExistsError("Refusing to overwrite an existing materialization report")
    endpoint = Endpoint(args.endpoint, command, args.timeout_seconds)
    # The administrator must disable implicit inference in the staging service.
    # Rule bodies use explicit datasets and never invoke a Virtuoso ruleset.
    asserted_count = endpoint.count(args.asserted_graph)
    initial_inferred_count = endpoint.count(args.inferred_graph)
    if asserted_count == 0 or (initial_inferred_count != 0 and not args.resume_report):
        raise ValueError("Requires nonempty asserted graph and fresh empty inferred graph")
    schema = endpoint.schema(args.asserted_graph)
    audit = schema_audit(schema)
    rules = rules_for(schema)
    program = "\n\n".join("# " + r.name + "\n" + r.update(args.asserted_graph, args.inferred_graph) for r in rules)
    execution_program = "\n\n".join("# " + r.name + "\n" + r.update(args.asserted_graph, args.inferred_graph, args.batch_size) for r in rules)
    rules_hash = hashlib.sha256((program + "\n").encode()).hexdigest()
    if args.resume_report:
        prior = json.loads(args.resume_report.read_text())
        validate_resume(prior, args.resume_generator, args.asserted_graph,
                        args.inferred_graph, asserted_count, rules_hash)
        overlap = endpoint.query(f"SELECT (COUNT(*) AS ?n) WHERE {{ GRAPH {iri(args.asserted_graph)} {{ ?s ?p ?o }} GRAPH {iri(args.inferred_graph)} {{ ?s ?p ?o }} }}")
        if int(overlap["results"]["bindings"][0]["n"]["value"]):
            raise ValueError("Resume delta overlaps asserted graph")
    (args.output_dir / "rules.rq").write_text(program + "\n")
    (args.output_dir / "execution_rules.rq").write_text(execution_program + "\n")
    dump_json(args.output_dir / "schema_audit.json", audit)
    report = {"program_version": VERSION, "started_at": datetime.now(timezone.utc).isoformat(),
              "software": {"python": platform.python_version(), "rdflib": rdflib.__version__},
              "generator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "rules_sha256": rules_hash,
              "execution_rules_sha256": hashlib.sha256((execution_program + "\n").encode()).hexdigest(),
              "batch_size": args.batch_size,
              "asserted_graph": args.asserted_graph, "inferred_graph": args.inferred_graph,
              "asserted_triples": asserted_count, "scope_limits": EXCLUSIONS,
              "status": "running", "passes": [], "maximum_passes_is_failure_limit": args.max_passes,
              "initial_inferred_triples": initial_inferred_count}
    if args.resume_report:
        report["resumed_from"] = {"report_sha256": hashlib.sha256(args.resume_report.read_bytes()).hexdigest(),
                                  "generator_sha256": prior["generator_sha256"],
                                  "prior_status": prior["status"], "prior_error": prior.get("error"),
                                  "policy": "Preserved positive delta; restart every rule from the beginning, require a complete zero-addition pass. Asserted and inferred graphs must remain exclusively write-frozen except for this runner."}
    dump_json(report_path, report)
    try:
        inferred_count = initial_inferred_count
        for iteration in range(1, args.max_passes + 1):
            row = {"iteration": iteration, "rules": []}
            scheduled_rules = []
            for rule in rules:
                if rule.name == 'subclass_type':
                    classes = endpoint.active_subclass_types(args.asserted_graph, args.inferred_graph)
                    variants = subclass_partitions(rule, classes)
                    partition_program = '\n\n'.join('# ' + variant.name + '\n' + variant.update(args.asserted_graph, args.inferred_graph, args.batch_size) for variant in variants) + '\n'
                    partition_dir = args.output_dir / 'execution_partitions'
                    partition_dir.mkdir(exist_ok=True)
                    (partition_dir / f'iteration_{iteration:04d}.rq').write_text(partition_program)
                    inventory = {'named_classes': sorted(str(c) for c in classes if isinstance(c, URIRef)),
                                 'anonymous_class_partition': any(isinstance(c, BNode) for c in classes),
                                 'query_sha256': hashlib.sha256(partition_program.encode()).hexdigest()}
                    dump_json(partition_dir / f'iteration_{iteration:04d}.json', inventory)
                    row['subclass_type_partitions'] = inventory
                    scheduled_rules.extend(variants)
                else:
                    scheduled_rules.append(rule)
            for rule in scheduled_rules:
                start = time.monotonic()
                batches, before = [], inferred_count
                while True:
                    endpoint.sql("SPARQL\n" + rule.update(args.asserted_graph, args.inferred_graph, args.batch_size) + ";\nCOMMIT WORK;")
                    count = endpoint.count(args.inferred_graph)
                    added = count - inferred_count
                    if not 0 <= added <= args.batch_size:
                        raise RuntimeError("Inferred update violated monotone batch bound")
                    batches.append(added)
                    inferred_count = count
                    print(json.dumps({"iteration": iteration, "rule": rule.name,
                                      "batch": len(batches), "added": added,
                                      "inferred_triples": count}), flush=True)
                    if added == 0:
                        break
                row["rules"].append({"name": rule.name, "new_triples": inferred_count - before,
                                     "batch_additions": batches,
                                     "seconds": round(time.monotonic() - start, 3)})
            row["new_triples"] = sum(r["new_triples"] for r in row["rules"])
            row["inferred_triples"] = inferred_count
            report["passes"].append(row)
            dump_json(report_path, report)
            print(json.dumps({k: v for k, v in row.items() if k != "rules"}), flush=True)
            if row["new_triples"] == 0:
                break
        else:
            raise RuntimeError("Pass limit reached before fixed point; closure incomplete")
        if endpoint.count(args.asserted_graph) != asserted_count:
            raise RuntimeError("Asserted graph count changed during inference")
        diagnostics = {name: endpoint.query(q)["results"]["bindings"] for name, q in diagnostic_queries(args.asserted_graph, args.inferred_graph).items()}
        dump_json(args.output_dir / "contradiction_diagnostics.json", diagnostics)
        if any(diagnostics.values()):
            raise RuntimeError("Materialized graph has a monitored contradiction")
        report.update(status="fixed_point_reached", inferred_triples=inferred_count,
                      asserted_plus_inferred_triples=asserted_count + inferred_count,
                      finished_at=datetime.now(timezone.utc).isoformat())
        endpoint.sql("CHECKPOINT;")
    except Exception as error:
        report.update(status="failed", error=str(error))
        dump_json(report_path, report)
        raise
    dump_json(report_path, report)


if __name__ == "__main__":
    main()
