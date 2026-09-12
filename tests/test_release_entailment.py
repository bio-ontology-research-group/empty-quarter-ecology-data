"""Same rule bodies are exercised locally and on isolated staging Virtuoso."""
import importlib.util
from pathlib import Path
import sys

import pytest
from rdflib import BNode, Graph, Namespace, RDF, RDFS, OWL, URIRef

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "scripts/release/kg/materialize.py"
spec = importlib.util.spec_from_file_location("release_materialize", MODULE)
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)
EX = Namespace("urn:eq:release-test:entity:")
RAK = Namespace("https://rubalkhali.science/kb/")
SIO = Namespace("http://semanticscience.org/resource/")


@pytest.fixture(scope="module")
def closure():
    asserted = Graph().parse(ROOT / "scripts/release/kg/entailment_fixture.ttl")
    before = set(asserted)
    inferred, trace = m.materialize_local(asserted)
    assert set(asserted) == before
    assert not set(asserted).intersection(inferred)
    assert sum(trace[-1]) == 0
    return asserted, inferred, asserted + inferred, trace


def test_named_graph_delta_and_project_measurement_chain(closure):
    asserted, inferred, union, trace = closure
    triple = (EX.quality, SIO.SIO_000011, EX.specimen)
    assert triple not in asserted and triple in inferred
    assert (EX.measurementPart, SIO.SIO_000291, EX.specimen) in inferred
    assert len(union) == len(asserted) + len(inferred)


def test_inverse_property_chain_direction_and_reject_unsupported_expression(closure):
    asserted, inferred, union, _ = closure
    chain = Namespace("urn:eq:release-test:inverse-chain:")
    assert (chain.start, chain.result, chain.end) not in asserted
    assert (chain.start, chain.result, chain.end) in inferred
    assert (chain.end, chain.result, chain.start) not in union
    for operand in ("[]", "[owl:inverseOf [owl:inverseOf <urn:p>]]",
                    "[owl:inverseOf <urn:p>, <urn:q>]"):
        graph = Graph().parse(data=f"@prefix owl: <{OWL}> . <urn:result> owl:propertyChainAxiom (<urn:p> {operand}) .", format="turtle")
        with pytest.raises(ValueError, match="exactly one inverseOf named"):
            m.schema_audit(graph)


def test_supported_property_and_class_consequences(closure):
    _, inferred, union, _ = closure
    expected = [(EX.s, EX.q, EX.o), (EX.o, EX.inverse, EX.s),
                (EX.o, EX.symmetric, EX.s), (EX.a, EX.cycle, EX.a),
                (EX.s, RDF.type, EX.Domain), (EX.o, RDF.type, EX.Range),
                (EX.s, RDF.type, EX.Equivalent), (EX.s, EX.peq, EX.o),
                (EX.s, EX.fixed, EX.chosen), (EX.s, RDF.type, EX.KnownSome),
                (EX.o, RDF.type, EX.UniversalFiller), (EX.s, RDF.type, EX.Intersection),
                (EX.s, RDF.type, EX.Union), (EX.s, RDF.type, EX.Enumeration)]
    assert all(triple in inferred for triple in expected)


def test_pcr_role_never_becomes_extraction_or_positive_role(closure):
    _, inferred, union, _ = closure
    assert (EX.pcr_role, RDF.type, RAK.RAK_0000305) in inferred
    assert (EX.pcr_role, RDF.type, RAK.RAK_0000306) not in union
    assert (EX.pcr_role, RDF.type, RAK.RAK_0000304) not in union


def test_scope_does_not_fabricate_existentials_or_equalities(closure):
    asserted, _, union, _ = closure
    assert not list(union.objects(EX.unwitnessed, EX.missing))
    assert (EX.alias, EX.p, EX.o) not in union
    assert (EX.o, OWL.sameAs, EX.chosen) not in union
    audit = m.schema_audit(asserted)
    assert audit["excluded_construct_counts"][str(OWL.sameAs)] == 1
    assert audit["excluded_construct_counts"][str(OWL.FunctionalProperty)] == 1


def test_convergence_goes_beyond_three_rounds_and_limit_fails():
    graph = Graph()
    for index in range(40):
        graph.add((EX[f"C{index}"], RDFS.subClassOf, EX[f"C{index+1}"]))
    graph.add((EX.long, RDF.type, EX.C0))
    with pytest.raises(RuntimeError, match="did not converge"):
        m.materialize_local(graph, max_passes=3, batch_size=0)
    inferred, trace = m.materialize_local(graph, batch_size=0)
    assert len(trace) > 3
    assert (EX.long, RDF.type, EX.C40) in inferred
    assert trace[-1] == [0] * len(trace[-1])


def test_actual_tbox_property_chain_inventory_and_lists():
    schema = Graph().parse(ROOT / "ontology/rubalkhali.owl", format="xml")
    audit = m.schema_audit(schema)
    assert len(audit["property_chains"]) == 4
    assert audit["chain_lengths"] == [2, 3]
    assert {rule.name for rule in m.rules_for(schema)} >= {"property_chain_length_2", "property_chain_length_3"}
    broken = Graph().parse(data="@prefix owl: <http://www.w3.org/2002/07/owl#> . <urn:p> owl:propertyChainAxiom <urn:broken> .", format="turtle")
    with pytest.raises(ValueError, match="Malformed"):
        m.schema_audit(broken)


def test_graph_identifiers_cannot_inject_update_commands():
    assert m.iri("urn:staging:asserted") == "<urn:staging:asserted>"
    for value in ('urn:x>};CLEAR ALL;#', 'https://bad graph/', 'relative'):
        with pytest.raises(ValueError):
            m.iri(value)


def test_truncated_schema_query_fails_closed():
    endpoint = m.Endpoint("http://127.0.0.1:1/sparql", [], 1)
    endpoint.query = lambda query: ({"results": {"bindings": [{"n": {"value": "2"}}]}}
                                    if "COUNT(*)" in query else {"results": {"bindings": []}})
    with pytest.raises(RuntimeError, match="truncated"):
        endpoint.schema("urn:test:asserted")


def test_role_clash_diagnostic_rejects_corrupt_fixture(closure):
    _, _, union, _ = closure
    corrupted = union + Graph()
    corrupted.add((EX.pcr_role, RDF.type, RAK.RAK_0000306))
    query = m.diagnostic_queries("urn:a", "urn:i")["pcr_extraction_role_clash"]
    # This in-memory graph is already the asserted+inferred union selected by
    # FROM in the deployed query; evaluate the identical diagnostic body here.
    query = query.replace("FROM <urn:a> FROM <urn:i>", "")
    assert [row.s for row in corrupted.query(query)] == [EX.pcr_role]


def test_sql_error_is_failure_even_if_isql_exit_status_is_zero(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(m.subprocess, "run", lambda *args, **kwargs:
                        SimpleNamespace(returncode=0, stdout="*** Error 37000: failed statement", stderr=""))
    with pytest.raises(RuntimeError, match="SQL runner failed"):
        m.Endpoint("http://127.0.0.1:1/sparql", ["test-wrapper"], 1).sql("SELECT 1;")


def test_seeded_positive_partial_closure_matches_fresh(closure):
    asserted, fresh, _, _ = closure
    seed = Graph()
    for triple in list(fresh)[:17]:
        seed.add(triple)
    resumed, trace = m.materialize_local(asserted, seed=seed)
    assert set(resumed) == set(fresh)
    assert sum(trace[-1]) == 0


def test_resume_requires_exact_failed_source_rules_and_graph_identity(tmp_path):
    import hashlib
    source = tmp_path / "old.py"
    source.write_text("preserved generator")
    prior = {"status": "failed", "asserted_graph": "urn:a", "inferred_graph": "urn:i",
             "asserted_triples": 42, "rules_sha256": "rules",
             "generator_sha256": hashlib.sha256(source.read_bytes()).hexdigest()}
    m.validate_resume(prior, source, "urn:a", "urn:i", 42, "rules")
    interrupted = dict(prior, status='operator_interrupted')
    with pytest.raises(ValueError, match='interruption evidence'):
        m.validate_resume(interrupted, source, "urn:a", "urn:i", 42, "rules")
    interrupted['operator_interruption'] = {'controller_terminated': True,
                                          'all_update_children_completed': True,
                                          'preserved_running_report_sha256': 'preserved'}
    m.validate_resume(interrupted, source, "urn:a", "urn:i", 42, "rules")
    for field in prior:
        corrupted = dict(prior, **{field: "changed"})
        with pytest.raises(ValueError, match="does not match"):
            m.validate_resume(corrupted, source, "urn:a", "urn:i", 42, "rules")


def test_batched_closure_matches_large_batch_with_duplicate_witnesses():
    graph = Graph()
    for index in range(12):
        graph.add((EX[f"item{index}"], RDF.type, EX.Child))
        graph.add((EX[f"item{index}"], RDF.type, EX.Other))
    graph.add((EX.Child, RDFS.subClassOf, EX.Parent))
    graph.add((EX.Other, RDFS.subClassOf, EX.Parent))
    graph.add((EX.Parent, RDFS.subClassOf, EX.Ancestor))
    small, trace = m.materialize_local(graph, batch_size=3)
    large, _ = m.materialize_local(graph, batch_size=0)
    assert set(small) == set(large)
    assert sum(trace[-1]) == 0
    assert all((EX[f"item{i}"], RDF.type, EX.Ancestor) in small for i in range(12))


def test_class_partitions_include_anonymous_and_classes_activated_later():
    graph = Graph()
    anonymous = BNode()
    graph.add((EX.s, RDF.type, anonymous))
    graph.add((anonymous, RDFS.subClassOf, EX.Parent))
    graph.add((EX.New, RDFS.subClassOf, EX.Top))
    graph.add((EX.p, RDFS.domain, EX.New))
    graph.add((EX.later, EX.p, EX.o))
    partitioned, trace = m.materialize_local(graph, batch_size=3)
    reference, _ = m.materialize_local(graph, batch_size=0)
    assert set(partitioned) == set(reference)
    assert (EX.s, RDF.type, EX.Parent) in partitioned
    assert (EX.later, RDF.type, EX.Top) in partitioned
    assert sum(trace[-1]) == 0


def test_partition_inventory_truncation_fails_closed():
    endpoint = m.Endpoint('http://127.0.0.1:1/sparql', [], 1)
    endpoint.query = lambda query: ({'results': {'bindings': [{'n': {'value': '2'}}]}}
                                    if 'COUNT(DISTINCT' in query else {'results': {'bindings': []}})
    with pytest.raises(RuntimeError, match='partition query truncated'):
        endpoint.active_subclass_types('urn:a', 'urn:i')


@pytest.mark.parametrize('header,value', [('X-SQL-State', 'S1TAT'),
                                         ('X-SQL-Message', 'partial result'),
                                         ('X-SPARQL-MaxRows', '1000000')])
@pytest.mark.parametrize('count', [0, 42])
def test_partial_http_json_aggregates_are_rejected(monkeypatch, header, value, count):
    import json
    class Response:
        status = 200
        headers = {header: value}
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self): return json.dumps({'results': {'bindings': [{'n': {'value': str(count)}}]}}).encode()
    monkeypatch.setattr(m, 'urlopen', lambda *args, **kwargs: Response())
    with pytest.raises(RuntimeError, match='Partial or row-limited'):
        m.Endpoint('http://127.0.0.1:1/sparql', [], 1).count('urn:a')


def test_non200_json_response_is_rejected(monkeypatch):
    class Response:
        status = 206
        headers = {}
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self): raise AssertionError('Partial body must not be parsed')
    monkeypatch.setattr(m, 'urlopen', lambda *args, **kwargs: Response())
    with pytest.raises(RuntimeError, match='status206'):
        m.Endpoint('http://127.0.0.1:1/sparql', [], 1).query('ASK {}')


def test_partial_response_during_run_records_failure(monkeypatch, tmp_path):
    import json
    class Endpoint:
        def __init__(self, *args): self.count_calls = 0
        def count(self, graph):
            self.count_calls += 1
            if self.count_calls == 1: return 10
            if self.count_calls == 2: return 0
            raise RuntimeError('Partial or row-limited SPARQL response: S1TAT')
        def schema(self, graph): return Graph()
        def sql(self, statement): return ''
    command = tmp_path / 'command.json'
    command.write_text('["unused"]')
    output = tmp_path / 'result'
    monkeypatch.setattr(m, 'Endpoint', Endpoint)
    monkeypatch.setattr(m, 'rules_for', lambda _: [m.Rule('fixture', '?s ?p ?o .', '?s ?p ?o .')])
    monkeypatch.setattr(sys, 'argv', ['materialize.py', '--endpoint', 'http://127.0.0.1:1/sparql',
                                    '--sql-command-file', str(command), '--asserted-graph', 'urn:a',
                                    '--inferred-graph', 'urn:i', '--output-dir', str(output), '--staging-only'])
    with pytest.raises(RuntimeError, match='Partial or row-limited'):
        m.main()
    report = json.loads((output / 'materialization.json').read_text())
    assert report['status'] == 'failed'
    assert 'S1TAT' in report['error']


def test_semijoin_inventory_equals_original_join():
    graph = Graph()
    anonymous = BNode()
    graph.add((EX.A, RDFS.subClassOf, EX.Top))
    graph.add((anonymous, RDFS.subClassOf, EX.Top))
    graph.add((EX.Empty, RDFS.subClassOf, EX.Top))
    for n in range(4): graph.add((EX[f'item{n}'], RDF.type, EX.A))
    graph.add((EX.s, RDF.type, anonymous))
    joined = {row.c for row in graph.query(m.PREFIXES + 'SELECT DISTINCT ?c WHERE { ?s rdf:type ?c . ?c rdfs:subClassOf ?d }')}
    semi = {row.c for row in graph.query(m.PREFIXES + 'SELECT DISTINCT ?c WHERE { ?c rdfs:subClassOf ?d FILTER EXISTS { ?s rdf:type ?c } }')}
    assert joined == semi == {EX.A, anonymous}
