"""Cross-module regression guards for sample-process visit links."""

from pathlib import Path
from xml.etree import ElementTree


ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "data/processed/ontology/rubalkhali_samples.owl"
MEASUREMENTS = ROOT / "data/processed/ontology/rubalkhali_measurements.owl"
STAGED_SAMPLES = ROOT / "data-paper/zenodo/ontology/rubalkhali_samples.owl"

OWL_NAMED_INDIVIDUAL = "{http://www.w3.org/2002/07/owl#}NamedIndividual"
RDF_ABOUT = "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}about"
RDF_RESOURCE = "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}resource"
SIO_IS_PART_OF = "{http://semanticscience.org/resource/}SIO_000068"
SIO_HAS_TARGET = "{http://semanticscience.org/resource/}SIO_000291"


def named_individuals(path: Path) -> set[str]:
    root = ElementTree.parse(path).getroot()
    return {
        iri
        for element in root.iter(OWL_NAMED_INDIVIDUAL)
        if (iri := element.attrib.get(RDF_ABOUT))
    }


def sample_visit_targets(path: Path) -> list[str]:
    root = ElementTree.parse(path).getroot()
    return [
        target
        for element in root.iter(SIO_IS_PART_OF)
        if (target := element.attrib.get(RDF_RESOURCE))
    ]


def individual_resource_targets(path: Path, predicate: str) -> dict[str, list[str]]:
    root = ElementTree.parse(path).getroot()
    targets: dict[str, list[str]] = {}
    for individual in root.iter(OWL_NAMED_INDIVIDUAL):
        subject = individual.attrib.get(RDF_ABOUT)
        if not subject:
            continue
        values = [
            target
            for element in individual.findall(predicate)
            if (target := element.attrib.get(RDF_RESOURCE))
        ]
        if values:
            targets[subject] = values
    return targets


def test_every_sample_process_visit_target_exists_in_measurement_module() -> None:
    targets = sample_visit_targets(SAMPLES)
    measurement_individuals = named_individuals(MEASUREMENTS)
    assert len(targets) == 1004
    assert len(set(targets)) == 252
    assert set(targets) <= measurement_individuals


def test_every_linked_visit_targets_the_sample_process_site() -> None:
    sample_visits = individual_resource_targets(SAMPLES, SIO_IS_PART_OF)
    sample_sites = individual_resource_targets(SAMPLES, SIO_HAS_TARGET)
    visit_sites = individual_resource_targets(MEASUREMENTS, SIO_HAS_TARGET)
    links = [
        (process, visit)
        for process, visits in sample_visits.items()
        for visit in visits
    ]

    assert len(links) == 1004
    for process, visit in links:
        assert len(sample_sites.get(process, [])) == 1
        assert len(visit_sites.get(visit, [])) == 1
        assert sample_sites[process][0] == visit_sites[visit][0]


def test_staged_sample_module_is_the_current_canonical_byte_stream() -> None:
    assert STAGED_SAMPLES.read_bytes() == SAMPLES.read_bytes()
