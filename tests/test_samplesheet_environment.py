"""Regression tests for field environmental-metadata curation."""

from __future__ import annotations

from collections import Counter
import csv
import importlib.util
import json
from pathlib import Path
import xml.etree.ElementTree as ET

from rdflib import Graph, RDF, RDFS, URIRef


ROOT = Path(__file__).resolve().parents[1]
BASE = "https://rubalkhali.science/kb/"
GENERATOR_PATH = ROOT / "data-paper/scripts/generate_env_table.py"
SPEC = importlib.util.spec_from_file_location(
    "generate_env_table", GENERATOR_PATH
)
assert SPEC and SPEC.loader
GENERATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GENERATOR)


def curated_rows() -> list[dict[str, str]]:
    path = (
        ROOT
        / "data/processed/metadata/environmental_measurements_curated.tsv"
    )
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def test_generated_environmental_artifacts_are_current() -> None:
    rows, audit, corrections = GENERATOR.curate(ROOT)
    assert len(rows) == 274
    assert len(corrections) == 24
    assert (
        GENERATOR.render_curated_tsv(rows)
        == (
            ROOT
            / "data/processed/metadata/environmental_measurements_curated.tsv"
        ).read_text(encoding="utf-8")
    )
    assert (
        GENERATOR.render_latex(rows, corrections)
        == (ROOT / "data-paper/env_table.tex").read_text(encoding="utf-8")
    )
    checked_audit = json.loads(
        (
            ROOT
            / "data/processed/metadata/environmental_measurements_audit.json"
        ).read_text(encoding="utf-8")
    )
    for key in (
        "status",
        "method",
        "correction_ledger",
        "range_checks",
        "source_files",
        "curated_records",
        "row_qc_status_counts",
        "campaign_date_audit",
    ):
        assert checked_audit[key] == audit[key]


def test_trip2_shift_is_explicit_and_note_does_not_leak() -> None:
    rows = [
        row
        for row in curated_rows()
        if row["source_file"] == "trip2-2023.tsv"
    ]
    assert [row["temperature_c"] for row in rows] == [
        "34.5",
        "36.7",
        "37.0",
        "38.6",
        "39.2",
        "41.2",
        "41.3",
        "41.9",
    ]
    assert all(not row["pressure_mbar"] for row in rows)
    assert all(not row["relative_humidity_pct"] for row in rows)
    assert rows[-1]["notes"] == "trip terminated due to extreme temperature"
    assert all("confirmed_shifted_column" in row["qc_status"] for row in rows)


def test_trip3_campaign_and_fractional_humidity_provenance() -> None:
    rows = curated_rows()
    trip3 = [row for row in rows if row["expedition"] == "Trip 3 (2024)"]
    assert len(trip3) == 65
    assert min(row["date"] for row in trip3) == "17/02/2024"
    assert max(row["date"] for row in trip3) == "21/02/2024"
    site21 = [row for row in trip3 if row["site"] == "21"]
    assert len(site21) == 1
    assert site21[0]["relative_humidity_pct"] == "31.321"

    auxiliary = [
        row
        for row in rows
        if row["record_role"] == "trip1_auxiliary_or_revisit_record"
    ]
    assert len(auxiliary) == 15
    assert {row["date"][-4:] for row in auxiliary} == {"2023"}
    assert all(
        row["expedition"] == "Trip 1 auxiliary/revisit (2023)"
        for row in auxiliary
    )


def test_invalid_site40_humidity_is_quarantined() -> None:
    row = next(
        row
        for row in curated_rows()
        if row["source_file"] == "trip5-2025.tsv" and row["site"] == "40"
    )
    assert row["relative_humidity_pct"] == ""
    assert row["qc_status"] == "quarantined_out_of_range"


def test_all_curated_measurements_are_in_declared_ranges() -> None:
    columns = {
        "temperature_c": "temperature",
        "pressure_mbar": "pressure",
        "relative_humidity_pct": "humidity",
    }
    for row in curated_rows():
        for column, field in columns.items():
            if not row[column]:
                continue
            lower, upper = GENERATOR.RANGES[field]
            assert lower <= float(row[column]) <= upper


def test_rdf_contains_no_out_of_range_field_humidity() -> None:
    path = (
        ROOT / "data/processed/ontology/rubalkhali_measurements.owl"
    )
    humidity_tag = (
        "{https://rubalkhali.science/kb/}RAK_2000005"
    )
    values: list[float] = []
    for _, element in ET.iterparse(path, events=("end",)):
        if element.tag == humidity_tag and element.text:
            values.append(float(element.text))
        element.clear()
    assert values
    assert all(0.0 <= value <= 100.0 for value in values)
    assert 194.0 not in values


def test_rdf_pressure_values_are_converted_from_hpa_to_pascal() -> None:
    canonical = (
        ROOT / "data/processed/ontology/rubalkhali_measurements.owl"
    )
    staged = (
        ROOT / "data-paper/zenodo/ontology/rubalkhali_measurements.owl"
    )
    canonical_generator = ROOT / "scripts/rdf/generate_measurements_abox.groovy"
    staged_generator = (
        ROOT
        / "data-paper/zenodo/scripts/rdf/generate_measurements_abox.groovy"
    )
    assert canonical.read_bytes() == staged.read_bytes()
    assert canonical_generator.read_bytes() == staged_generator.read_bytes()

    pressure_tag = f"{{{BASE}}}RAK_2000004"
    individual_tag = "{http://www.w3.org/2002/07/owl#}NamedIndividual"
    unit_tag = "{http://semanticscience.org/resource/}SIO_000221"
    resource_attr = (
        "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}resource"
    )
    values: list[float] = []
    units: list[str] = []
    root = ET.parse(canonical).getroot()
    for element in root.iter(individual_tag):
        pressure = element.find(pressure_tag)
        if pressure is not None and pressure.text:
            values.append(float(pressure.text))
            unit = element.find(unit_tag)
            assert unit is not None
            units.append(unit.attrib[resource_attr])

    # Auxiliary/revisit labels describe offset or special-purpose locations.
    # Coordinates alone do not establish identity with a catalogue site, so
    # only the exact catalogue label 19.5 is represented in the ABox.
    unresolved = {
        (row["source_file"], row["source_row"])
        for row in curated_rows()
        if row["record_role"] == "trip1_auxiliary_or_revisit_record"
        and row["site"] != "19.5"
    }
    assert len(unresolved) == 14
    expected = Counter(
        float(row["pressure_mbar"]) * 100.0
        for row in curated_rows()
        if row["pressure_mbar"]
        and (row["source_file"], row["source_row"]) not in unresolved
    )
    assert len(values) == 187
    assert Counter(values) == expected
    assert min(values) >= 80_000.0
    assert max(values) <= 110_000.0
    assert set(units) == {"http://purl.obolibrary.org/obo/UO_0000110"}


def test_ambiguous_named_trip1_sites_resolve_by_exact_coordinates() -> None:
    graph = Graph()
    graph.parse(
        ROOT / "data/processed/ontology/rubalkhali_measurements.owl"
    )
    visit_class = URIRef(f"{BASE}RAK_0000003")
    has_target = URIRef(
        "http://semanticscience.org/resource/SIO_000291"
    )
    expected = {
        "Site water well (location 2)": f"{BASE}RAK_1000067",
        "Site road (location 1)": f"{BASE}RAK_1000068",
        "Site road (location 2)": f"{BASE}RAK_1000069",
        "Site camground": f"{BASE}RAK_1000070",
    }
    for site_label, target in expected.items():
        visits = {
            subject
            for subject in graph.subjects(RDF.type, visit_class)
            for label in graph.objects(subject, RDFS.label)
            if str(label).startswith(
                f"Visit to {site_label} during Trip1 "
            )
        }
        assert len(visits) == 1
        visit = next(iter(visits))
        assert (visit, has_target, URIRef(target)) in graph


def test_auxiliary_rows_require_an_exact_site_label() -> None:
    graph = Graph()
    graph.parse(
        ROOT / "data/processed/ontology/rubalkhali_measurements.owl"
    )
    visit_class = URIRef(f"{BASE}RAK_0000003")
    labels = [
        str(label)
        for visit in graph.subjects(RDF.type, visit_class)
        for label in graph.objects(visit, RDFS.label)
    ]

    # 259 primary rows plus the one auxiliary row with the exact label 19.5.
    assert len(labels) == 260
    assert any(
        label.startswith(
            "Visit to Site 19.5 during Trip1 2023 on 2023-03-18"
        )
        for label in labels
    )
