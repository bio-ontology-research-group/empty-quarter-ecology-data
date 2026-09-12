import importlib.util
from pathlib import Path

import pytest
from rdflib import Graph

DIRECTORY = Path(__file__).resolve().parents[1] / "scripts/release/kg"
SPEC = importlib.util.spec_from_file_location("contract", DIRECTORY / "check_engine_contract.py")
CONTRACT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CONTRACT)


@pytest.mark.parametrize("headers", [{"X-SQL-State": "S1TAT"}, {"X-SQL-Message": "partial"},
                                   {"X-SPARQL-MaxRows": "100"}, {"X-Result-Truncated": "true"}])
def test_partial_headers_fail_closed(headers):
    with pytest.raises(RuntimeError):
        CONTRACT.complete_headers(headers)


def test_success_state_is_accepted():
    CONTRACT.complete_headers({"X-SQL-State": "00000"})


@pytest.mark.parametrize("body", ['{}', '{"head":{"vars":[]},"error":"failed"}',
                                 '{"head":{"vars":[]},"results":{}}'])
def test_missing_bindings_cannot_pass_as_empty_dataset(body):
    with pytest.raises(RuntimeError):
        CONTRACT.select_rows(200, body, "application/sparql-results+json")


@pytest.mark.parametrize("mutation", [None, "double_to_decimal", "wkt_to_geometry", "missing_statement"])
def test_graph_roundtrip_requires_source_terms_and_exact_types(mutation):
    source = Graph().parse(DIRECTORY / "export_fixture.ttl", format="turtle")
    native = source.serialize(format="nt")
    if mutation == "double_to_decimal":
        native = native.replace("XMLSchema#double", "XMLSchema#decimal")
    elif mutation == "wkt_to_geometry":
        native = native.replace("www.opengis.net/ont/geosparql#wktLiteral", "www.openlinksw.com/schemas/virtrdf#Geometry")
    elif mutation == "missing_statement":
        native = "\n".join(native.splitlines()[1:])
    if mutation:
        with pytest.raises(RuntimeError):
            CONTRACT.graph_roundtrip(native, "ntriples", source)
    else:
        assert CONTRACT.graph_roundtrip(native, "ntriples", source) == dict(
            triples=6, graph_isomorphic=True, literal_datatypes_preserved=True)


@pytest.mark.parametrize('fmt', ['json', 'xml'])
@pytest.mark.parametrize('mutation', [None, 'geometry', 'decimal', 'duplicate'])
def test_select_bound_literals_preserve_source_result(fmt, mutation):
    source = Graph().parse(DIRECTORY / 'export_fixture.ttl', format='turtle')
    result = source.query('SELECT ?s ?p ?o WHERE {?s ?p ?o} ORDER BY ?p')
    if mutation == 'duplicate':
        result.bindings[0] = result.bindings[1]
    body = result.serialize(format=fmt).decode()
    if mutation == 'geometry':
        body = body.replace('www.opengis.net/ont/geosparql#wktLiteral', 'www.openlinksw.com/schemas/virtrdf#Geometry')
    if mutation == 'decimal':
        body = body.replace('XMLSchema#double', 'XMLSchema#decimal')
    if mutation:
        with pytest.raises(RuntimeError):
            CONTRACT.select_roundtrip(body, fmt, source)
    else:
        assert CONTRACT.select_roundtrip(body, fmt, source) == dict(rows=6,
            literal_datatypes_preserved=True, result_multiset_preserved=True)
