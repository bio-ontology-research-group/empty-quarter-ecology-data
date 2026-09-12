import importlib.util
from pathlib import Path

import pytest
from rdflib import Graph, OWL, URIRef, DCTERMS, Literal, Namespace
from rdflib.compare import isomorphic

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("stamp_kg", ROOT / "scripts/release/stamp_kg_release.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_release_stamp_changes_only_root_metadata_and_is_idempotent():
    source = (ROOT / "ontology/rubalkhali.owl").read_text()
    revised = module.stamp(source, "3.0.0")
    assert revised == module.stamp(revised, "3.0.0")
    old, new = Graph().parse(data=source, format="xml"), Graph().parse(data=revised, format="xml")
    root = URIRef(module.BASE)
    for graph in (old, new):
        for predicate in (OWL.versionIRI, OWL.versionInfo, OWL.imports, DCTERMS.modified,
                          URIRef("http://purl.org/pav/version"), URIRef("http://purl.org/pav/previousVersion")):
            graph.remove((root, predicate, None))
    assert isomorphic(old, new)
    assert "v3.0.0/" in revised and "v2.0.6/" not in revised
    for filename in module.MODULES:
        assert module.BASE + filename in revised
    stamped = Graph().parse(data=revised, format="xml")
    pav = Namespace("http://purl.org/pav/")
    assert set(stamped.objects(root, OWL.versionInfo)) == {Literal("3.0.0")}
    assert set(stamped.objects(root, pav.version)) == {Literal("v3.0.0")}
    assert set(stamped.objects(root, pav.previousVersion)) == {Literal("v2.0.6")}
    assert set(stamped.objects(root, DCTERMS.modified)) == {Literal("2026-09-10T00:00:00Z")}


def test_stamp_requires_explicit_semver():
    with pytest.raises(ValueError):
        module.stamp("", "latest")
