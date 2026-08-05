import csv
import hashlib
import json
import re
from pathlib import Path

from rdflib import DCTERMS, RDF, Graph, Namespace, URIRef

ROOT = Path(__file__).resolve().parents[1]
BASE = Namespace("https://rubalkhali.science/kb/")
SIO = Namespace("http://semanticscience.org/resource/")
REPOSITORY_LAYOUT = (ROOT / "data/processed/metadata/controls").is_dir()
NORMALIZED = (
    ROOT / "data/processed/metadata/controls"
    if REPOSITORY_LAYOUT
    else ROOT / "metadata/controls"
)
ANALYSIS = (
    ROOT / "analysis/v3/control_audit"
    if REPOSITORY_LAYOUT
    else ROOT / "evidence/control-audit"
)
GRAPH = (
    ROOT / "data/processed/semantics/ontology/rubalkhali_controls.ttl"
    if REPOSITORY_LAYOUT
    else ROOT / "ontology/rubalkhali_controls.ttl"
)


def rows(name: str):
    path = NORMALIZED / name
    with path.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def test_control_iris_are_recomputable_and_unique():
    registry = rows("control_entity_registry.tsv")
    iris = set()
    keys = set()
    for row in registry:
        canonical = f"{row['entity_kind']}|{row['stable_key_type']}|{row['stable_key']}"
        digest = hashlib.sha256(canonical.encode()).hexdigest()
        assert row["canonical_key"] == canonical
        assert row["key_sha256"] == digest
        assert row["entity_id"] == str(BASE) + "RAK_CTL_" + digest
        assert row["entity_id"] not in iris
        assert canonical not in keys
        iris.add(row["entity_id"])
        keys.add(canonical)


def test_reused_eb_labels_do_not_merge_entities():
    aliases = rows("control_aliases.tsv")
    eb1 = {row["entity_id"] for row in aliases if row["alias"] == "EB1"}
    assert len(eb1) >= 2


def test_positive_controls_never_train_contaminant_model():
    path = ANALYSIS / "control_analysis_roles.tsv"
    with path.open(encoding="utf-8") as handle:
        analysis_roles = list(csv.DictReader(handle, delimiter="\t"))
    assert all(
        "contaminant_training" not in row["use"] or "never" in row["use"]
        for row in analysis_roles
        if row["control_role"] == "positive_control"
    )
    summary = json.loads((ANALYSIS / "summary.json").read_text())
    assert summary["positive_controls_in_training"] == 0
    assert summary["training_extraction_blanks"] == [f"EB{i}" for i in range(1, 18)]


def test_controls_and_batches_are_not_assigned_to_expeditions_or_targets():
    graph = Graph().parse(GRAPH)
    subjects = set(graph.subjects(RDF.type, BASE.RAK_0000300))
    subjects.update(graph.subjects(RDF.type, BASE.RAK_0000308))
    for subject in subjects:
        assert not list(graph.objects(subject, SIO.SIO_000291))
        for parent in graph.objects(subject, SIO.SIO_000068):
            assert (parent, RDF.type, BASE.RAK_0000018) not in graph


def test_numeric_composition_has_unit_basis_specification_and_reified_taxon_claim():
    graph = Graph().parse(GRAPH)
    assertions = {
        row["assertion_id"]: row for row in rows("control_assertions.tsv")
    }
    expected_nodes = set()
    for row in rows("control_composition.tsv"):
        assert row["assertion_status"] == "confirmed"
        assert row["expected_unit_iri"]
        assert row["composition_basis"]
        assertion = assertions[row["assertion_id"]]
        assert assertion["status"] == "confirmed"
        assert assertion["subject_iri"] == row["composition_specification_id"]
        assert assertion["predicate_iri"] == str(BASE.RAK_2000092)
        assert assertion["object_iri"] == row["taxon_iri"]
        expected_nodes.add(URIRef(row["assertion_id"]))
        assert (
            URIRef(row["composition_specification_id"]),
            BASE.RAK_2000092,
            URIRef(row["taxon_iri"]),
        ) in graph
        assert (
            URIRef(row["assertion_id"]),
            RDF.type,
            BASE.RAK_0000317,
        ) in graph
        product = URIRef(row["control_material_or_product_id"])
        specification = URIRef(row["composition_specification_id"])
        assert (product, SIO.SIO_000339, specification) in graph
        assert (specification, SIO.SIO_000338, product) in graph
        assert list(graph.objects(specification, DCTERMS.source))
        assert not list(graph.objects(specification, SIO.SIO_000772))
    assert len(expected_nodes) == 18
    assert set(graph.subjects(RDF.type, BASE.RAK_0000317)) == expected_nodes


def test_july_positive_library_product_links_remain_provisional():
    graph = Graph().parse(GRAPH)
    assertions = rows("control_assertions.tsv")
    dispositions = rows("control_metadata_dispositions.tsv")
    provisional = [
        row
        for row in assertions
        if row["predicate_iri"] == str(SIO.SIO_000244)
        and row["status"] == "provisional"
    ]
    assert len(provisional) == 7
    subjects = {row["subject_iri"] for row in provisional}
    assert {
        row["about_entity_id"]
        for row in dispositions
        if row["metadata_field"] == "positive_control_product_identity"
        and row["disposition"] == "unresolved"
    } == subjects
    for row in provisional:
        assert (
            URIRef(row["subject_iri"]),
            SIO.SIO_000244,
            URIRef(row["object_iri"]),
        ) not in graph


def test_sio_assertion_and_disposition_inverses_are_explicit():
    graph = Graph().parse(GRAPH)
    for row in rows("control_assertions.tsv"):
        assertion = URIRef(row["assertion_id"])
        evidence = URIRef(row["evidence_id"])
        assert (assertion, SIO.SIO_000772, evidence) in graph
        assert (evidence, SIO.SIO_000773, assertion) in graph
        if (
            row["status"] == "confirmed"
            and row["predicate_iri"] == str(SIO.SIO_000244)
        ):
            subject = URIRef(row["subject_iri"])
            product = URIRef(row["object_iri"])
            assert (product, SIO.SIO_000245, subject) in graph
    for row in rows("control_metadata_dispositions.tsv"):
        disposition = URIRef(row["disposition_id"])
        about = URIRef(row["about_entity_id"])
        evidence = URIRef(row["evidence_id"])
        assert (disposition, SIO.SIO_000332, about) in graph
        assert (about, SIO.SIO_000629, disposition) in graph
        assert (disposition, SIO.SIO_000772, evidence) in graph
        assert (evidence, SIO.SIO_000773, disposition) in graph


def test_lanes_and_trip4_fastq_provenance_are_normalized_from_sources():
    occurrences = rows("control_sequence_occurrences.tsv")
    for row in occurrences:
        match = re.search(r"_L(\d{3})_", row["read_1_file"])
        if match:
            assert row["lane"] == match.group(1)
    trip4 = [
        row
        for row in occurrences
        if row["source_snapshot_id"]
        == "data/metadata/samplesheets/additional_fastqs_v2.tsv"
    ]
    assert len(trip4) == 6
    assert all(row["source_row"].isdigit() for row in trip4)
