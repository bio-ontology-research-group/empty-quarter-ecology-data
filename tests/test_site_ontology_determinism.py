import csv
from pathlib import Path
from xml.etree import ElementTree


ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "data/metadata/samples/site_iri_registry.tsv"
SITES = ROOT / "data/processed/ontology/rubalkhali_sites.owl"
GENERATOR = (
    ROOT / "scripts/rdf/generate_site_ontology.groovy"
).read_text(encoding="utf-8")

OWL_INDIVIDUAL = "{http://www.w3.org/2002/07/owl#}NamedIndividual"
RDF_ABOUT = "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}about"
RDFS_LABEL = "{http://www.w3.org/2000/01/rdf-schema#}label"


def registry_rows() -> list[dict[str, str]]:
    with REGISTRY.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def test_named_site_registry_is_bijective() -> None:
    rows = registry_rows()
    assert len(rows) == 10
    assert len({row["site_label"] for row in rows}) == len(rows)
    assert len({row["site_iri"] for row in rows}) == len(rows)
    assert {row["status"] for row in rows} == {"canonical"}


def test_named_site_registry_matches_the_canonical_site_module() -> None:
    labels_by_iri = {}
    root = ElementTree.parse(SITES).getroot()
    for individual in root.iter(OWL_INDIVIDUAL):
        iri = individual.attrib.get(RDF_ABOUT)
        label = individual.find(RDFS_LABEL)
        if iri and label is not None:
            labels_by_iri[iri] = label.text
    for row in registry_rows():
        assert labels_by_iri[row["site_iri"]] == row["site_label"]


def test_generator_uses_sorted_sources_and_the_stable_registry() -> None:
    assert 'site_iri_registry.tsv' in GENERATOR
    assert '.sort { a, b -> a.name <=> b.name }' in GENERATOR
    assert 'specialSiteIris[fs.label]' in GENERATOR
    assert 'avgLon <=> b.avgLon' in GENERATOR
