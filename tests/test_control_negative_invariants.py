from rdflib import DCTERMS, OWL, RDF, Graph, Literal, Namespace

from scripts.validation.validate_controls import (
    control_graph_invariant_failures,
    string_sentinel_failures,
)


BASE = Namespace("https://rubalkhali.science/kb/")
SIO = Namespace("http://semanticscience.org/resource/")


def failures(graph=None, assertions=None, occurrences=None):
    return control_graph_invariant_failures(
        graph or Graph(), assertions or [], occurrences or []
    )


def test_reused_label_sameas_fixture_is_rejected():
    graph = Graph()
    graph.add((BASE.RAK_CTL_aa, OWL.sameAs, BASE.RAK_CTL_bb))
    assert any("owl:sameAs" in item for item in failures(graph))


def test_direct_control_to_trip_fixture_is_rejected():
    graph = Graph()
    graph.add((BASE.RAK_CTL_control, RDF.type, BASE.RAK_0000300))
    graph.add((BASE.RAK_CTL_trip, RDF.type, BASE.RAK_0000018))
    graph.add((BASE.RAK_CTL_control, SIO.SIO_000068, BASE.RAK_CTL_trip))
    assert any("directly assigned to expedition" in item for item in failures(graph))


def test_shared_role_fixture_is_rejected():
    graph = Graph()
    graph.add((BASE.RAK_CTL_role, RDF.type, BASE.RAK_0000304))
    for bearer in (BASE.RAK_CTL_material_a, BASE.RAK_CTL_material_b):
        graph.add((bearer, SIO.SIO_000228, BASE.RAK_CTL_role))
        graph.add((BASE.RAK_CTL_role, SIO.SIO_000227, bearer))
    assert any("2 graph bearers" in item for item in failures(graph))


def test_provisional_product_domain_triple_fixture_is_rejected():
    graph = Graph()
    graph.add(
        (BASE.RAK_CTL_material, SIO.SIO_000244, BASE.RAK_CTL_product)
    )
    assertions = [
        {
            "assertion_id": str(BASE.RAK_CTL_assertion),
            "subject_iri": str(BASE.RAK_CTL_material),
            "predicate_iri": str(SIO.SIO_000244),
            "object_iri": str(BASE.RAK_CTL_product),
            "status": "provisional",
        }
    ]
    assert any("non-confirmed assertion" in item for item in failures(graph, assertions))


def test_index_code_entity_fixture_is_rejected():
    graph = Graph()
    graph.add((BASE.RAK_CTL_index, DCTERMS.identifier, Literal("SU0216")))
    graph.add((BASE.RAK_CTL_index, RDF.type, BASE.RAK_0000322))
    occurrences = [{"index_code": "SU0216"}]
    assert any("index code was promoted" in item for item in failures(graph, [], occurrences))


def test_literal_unknown_fixture_is_rejected():
    detected = string_sentinel_failures(
        {"fixture.tsv": [{"batch_id": "unknown", "product": "D6322"}]}
    )
    assert detected == [
        "string sentinel 'unknown' in fixture.tsv:2:batch_id"
    ]
