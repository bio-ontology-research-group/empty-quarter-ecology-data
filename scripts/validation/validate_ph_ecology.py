#!/usr/bin/env python3
"""Validate frozen pH normalization, graph, ecology analysis, and KG wiring."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
from datetime import date
from pathlib import Path
from typing import Any

from rdflib import DCTERMS, OWL, RDF, XSD, Graph, Namespace, URIRef


BASE = Namespace("https://rubalkhali.science/kb/")
SIO = Namespace("http://semanticscience.org/resource/")
PATO = Namespace("http://purl.obolibrary.org/obo/PATO_")
UO = Namespace("http://purl.obolibrary.org/obo/UO_")
SCHEMA_VERSION = "ph-measurement-v1"
DEFAULT_DATASET_VERSION = "EQ-PH-ECOLOGY-v1.0.0"
SHAPE_BASE = "https://rubalkhali.science/schema/ph_measurements"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def exactly_one(graph: Graph, subject: URIRef, predicate: URIRef) -> URIRef:
    values = list(graph.objects(subject, predicate))
    if len(values) != 1:
        raise AssertionError(f"Expected one {predicate} for {subject}; found {len(values)}")
    return URIRef(values[0])


def write_shape_map(path: Path, entries: list[tuple[URIRef, str]]) -> None:
    path.write_text(
        "".join(
            f"<{node}>@<{SHAPE_BASE}#{shape}>\n" for node, shape in entries
        ),
        encoding="utf-8",
    )


def run_shex(
    root: Path,
    graph_path: Path,
    shape_path: Path,
    shape_map: Path,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "bash",
            str(root / "scripts/validation/shexvalidate.sh"),
            str(graph_path),
            str(shape_path),
            str(shape_map),
        ],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )


def write_sorted_ntriples(graph: Graph, path: Path) -> None:
    serialized = graph.serialize(format="nt")
    lines = sorted(line for line in serialized.splitlines() if line.strip())
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def validate(
    root: Path,
    ph_dir: Path,
    expected_dataset_version: str | None = None,
) -> dict[str, Any]:
    normalized = ph_dir / "normalized"
    kg = ph_dir / "kg"
    graph_path = kg / "rubalkhali_ph_measurements.ttl"
    shape_path = kg / "ph_measurements.shex"
    summary = json.loads((ph_dir / "summary.json").read_text(encoding="utf-8"))
    ecology = json.loads((ph_dir / "ecology/summary.json").read_text(encoding="utf-8"))
    audit = read_tsv(normalized / "ph_observation_audit.tsv")
    accepted = read_tsv(normalized / "ph_accepted_measurements.tsv")
    registry = read_tsv(normalized / "ph_entity_registry.tsv")
    graph = Graph().parse(graph_path, format="turtle")
    dataset_version = summary["dataset_version"]
    dataset_purpose = summary["dataset_purpose"]
    canonical_release = dataset_purpose == "shared-manuscripts"

    if expected_dataset_version is not None:
        assert dataset_version == expected_dataset_version
    assert summary["status"] == (
        "FROZEN_" + dataset_purpose.upper().replace("-", "_")
    )
    assert ecology["status"] == "FROZEN_ECOLOGY_ANALYSIS"
    assert ecology["dataset_version"] == dataset_version
    assert summary["release_gate"]["ecology_analysis_frozen"]
    assert summary["release_gate"].get("canonical_kg_import_allowed", False) == (
        canonical_release
    )
    assert ecology["release_gate"]["ecology_analysis_frozen"]
    assert ecology["release_gate"]["ecology_manuscript_claim_allowed"]
    assert len(audit) == summary["counts"]["source_rows"]
    assert len(accepted) == summary["counts"]["admitted_rows"]
    assert {row["disposition"] for row in accepted} == {"ADMITTED_MEASUREMENT"}
    assert len({row["sample_id"] for row in accepted}) == len(accepted)

    as_of = date.fromisoformat(summary["as_of"])
    for row in accepted:
        assert row["metadata_match"] == "True"
        assert row["calibration_pass"] == "True"
        assert row["slope_pass"] == "True"
        assert row["ph10_check_pass"] == "True"
        assert row["value_range_pass"] == "True"
        assert row["kg_eligible"] == "True"
        assert 0.0 <= float(row["ph_value"]) <= 14.0
        assert 95.0 <= float(row["slope_percent"]) <= 102.0
        assert abs(float(row["ph10_check"]) - 10.0) <= 0.1000001
        assert date.fromisoformat(row["measurement_date"]) <= as_of

    source_path = root / summary["source"]["path"]
    assert source_path.stat().st_size == summary["source"]["bytes"]
    assert sha256_file(source_path) == summary["source"]["sha256"]
    assert ecology["source_workbook_sha256"] == summary["source"]["sha256"]

    freeze_manifest_path = (
        root
        / "data/metadata/samples/ph/versions"
        / dataset_version
        / "manifest.json"
    )
    freeze_manifest = json.loads(freeze_manifest_path.read_text(encoding="utf-8"))
    assert freeze_manifest["dataset_version"] == dataset_version
    assert freeze_manifest["status"] == "FROZEN"
    assert freeze_manifest["purpose"] == dataset_purpose
    assert not freeze_manifest["source_complete"]
    assert freeze_manifest["source"]["sha256"] == summary["source"]["sha256"]
    assert freeze_manifest["source"]["bytes"] == summary["source"]["bytes"]
    assert not freeze_manifest["version_policy"]["ecology_analysis_may_change"]
    if canonical_release:
        assert freeze_manifest["measurement_campaign_closed"]
        assert freeze_manifest["collection_status"] == "COMPLETE_AS_AVAILABLE"
        assert freeze_manifest["version_policy"][
            "both_manuscripts_use_this_exact_version"
        ]
    else:
        assert freeze_manifest["version_policy"][
            "successor_data_paper_version_may_add_measurements"
        ]

    version_rows = read_tsv(root / "data/metadata/samples/ph/version_registry.tsv")
    version_row = next(
        row for row in version_rows if row["dataset_version"] == dataset_version
    )
    assert version_row["status"] == "FROZEN"
    assert version_row["purpose"] == dataset_purpose
    assert version_row["sha256"] == summary["source"]["sha256"]

    for row in read_tsv(ph_dir / "ecology/input_manifest.tsv"):
        path = Path(row["path"])
        if not path.is_absolute():
            path = root / path
        assert path.stat().st_size == int(row["bytes"])
        assert sha256_file(path) == row["sha256"]

    for line in (ph_dir / "ecology/SHA256SUMS").read_text(encoding="utf-8").splitlines():
        expected, name = line.split(maxsplit=1)
        assert sha256_file(ph_dir / "ecology" / name) == expected

    for row in registry:
        digest = hashlib.sha256(row["canonical_key"].encode("utf-8")).hexdigest()
        assert row["canonical_key"].startswith(SCHEMA_VERSION + "|")
        assert row["key_sha256"] == digest
        assert row["entity_iri"].endswith("_" + digest)

    processes = set(graph.subjects(RDF.type, SIO.SIO_001054))
    values = set(graph.subjects(RDF.type, SIO.SIO_001089))
    qualities = set(graph.subjects(RDF.type, PATO.PATO_0001842))
    assert len(processes) == len(values) == len(qualities) == len(accepted)
    assert len(set(graph.subjects(RDF.type, SIO.SIO_000070))) == len(values)

    for process in processes:
        specimen_input = exactly_one(graph, process, SIO.SIO_000230)
        specimen_target = exactly_one(graph, process, SIO.SIO_000291)
        assert specimen_input == specimen_target
        value = exactly_one(graph, process, SIO.SIO_000229)
        assert value in values
        assert (value, SIO.SIO_000232, process) in graph
        assert len(list(graph.objects(process, SIO.SIO_000339))) == 1
        assert len(list(graph.objects(process, SIO.SIO_000132))) == 1
        assert len(list(graph.objects(process, SIO.SIO_000068))) == 1
        assert len(list(graph.objects(process, SIO.SIO_000772))) == 1
        measurement_dates = list(graph.objects(process, DCTERMS.date))
        assert len(measurement_dates) == 1
        assert measurement_dates[0].datatype == XSD.date
        assert date.fromisoformat(str(measurement_dates[0])) <= as_of

    for value in values:
        numeric = list(graph.objects(value, SIO.SIO_000300))
        assert len(numeric) == 1
        assert numeric[0].datatype == XSD.double
        assert 0.0 <= float(numeric[0]) <= 14.0
        assert list(graph.objects(value, SIO.SIO_000221)) == [UO.UO_0000196]
        quality = exactly_one(graph, value, SIO.SIO_000215)
        process = exactly_one(graph, value, SIO.SIO_000232)
        assert quality in qualities
        assert process in processes
        assert (quality, SIO.SIO_000216, value) in graph
        specimen = exactly_one(graph, quality, SIO.SIO_000011)
        assert (specimen, SIO.SIO_000008, quality) in graph

    protocol = exactly_one(graph, next(iter(processes)), SIO.SIO_000339)
    device = exactly_one(graph, next(iter(processes)), SIO.SIO_000132)
    sessions = set(graph.subjects(RDF.type, SIO.SIO_000994))
    entries = [(node, "PHMeasurementProcessShape") for node in sorted(processes, key=str)]
    entries += [(node, "PHMeasurementValueShape") for node in sorted(values, key=str)]
    entries += [(node, "AcidityQualityShape") for node in sorted(qualities, key=str)]
    entries += [(protocol, "PHProtocolShape"), (device, "PHDeviceShape")]
    entries += [(node, "PHSessionShape") for node in sorted(sessions, key=str)]
    positive_shape_map = kg / "ph_validation.shexmap"
    write_shape_map(positive_shape_map, entries)
    shex = run_shex(root, graph_path, shape_path, positive_shape_map)
    (kg / "shex_validation.log").write_text(
        shex.stdout + ("\nSTDERR\n" + shex.stderr if shex.stderr else ""),
        encoding="utf-8",
    )
    if shex.returncode != 0:
        raise AssertionError(f"Positive ShEx validation failed: {shex.stderr or shex.stdout}")

    # Negative contract test: omitting the pH unit must be rejected.
    first_value = sorted(values, key=str)[0]
    first_quality = exactly_one(graph, first_value, SIO.SIO_000215)
    first_process = exactly_one(graph, first_value, SIO.SIO_000232)
    first_protocol = exactly_one(graph, first_process, SIO.SIO_000339)
    first_device = exactly_one(graph, first_process, SIO.SIO_000132)
    first_session = exactly_one(graph, first_process, SIO.SIO_000068)
    negative = Graph()
    for subject in (
        first_value,
        first_quality,
        first_process,
        first_protocol,
        first_device,
        first_session,
    ):
        for triple in graph.triples((subject, None, None)):
            negative.add(triple)
    negative.remove((first_value, SIO.SIO_000221, UO.UO_0000196))
    negative_path = kg / "ph_negative_missing_unit.ttl"
    negative_shape_map = kg / "ph_negative_missing_unit.shexmap"
    negative_log = kg / "ph_negative_missing_unit.log"
    write_sorted_ntriples(negative, negative_path)
    write_shape_map(
        negative_shape_map,
        [(first_value, "PHMeasurementValueShape")],
    )
    negative_shex = run_shex(
        root,
        negative_path,
        shape_path,
        negative_shape_map,
    )
    negative_log.write_text(
        negative_shex.stdout
        + ("\nSTDERR\n" + negative_shex.stderr if negative_shex.stderr else ""),
        encoding="utf-8",
    )
    if negative_shex.returncode != 1 or not negative_shex.stdout.startswith("FAIL"):
        raise AssertionError(
            "Missing-unit ShEx fixture was not rejected as a schema violation: "
            f"return code {negative_shex.returncode}; "
            f"output {negative_shex.stdout[:200]!r}"
        )

    released_kb = Graph().parse(
        root / "data/processed/semantics/ontology/rubalkhali_kb.owl"
    )
    versioned_ontology = URIRef(summary["ontology_iri"])
    imported = (None, OWL.imports, versioned_ontology) in released_kb
    assert imported == canonical_release

    canonical_ttl_matches = False
    canonical_owl_matches = False
    if canonical_release:
        module_stem = str(versioned_ontology).rsplit("/", 1)[-1].removesuffix(
            ".owl"
        )
        ontology_dir = root / "data/processed/semantics/ontology"
        canonical_ttl = ontology_dir / f"{module_stem}.ttl"
        canonical_owl = ontology_dir / f"{module_stem}.owl"
        assert canonical_ttl.is_file() and canonical_owl.is_file()
        canonical_ttl_graph = Graph().parse(canonical_ttl, format="turtle")
        canonical_owl_graph = Graph().parse(canonical_owl, format="xml")
        canonical_ttl_matches = canonical_ttl_graph.isomorphic(graph)
        canonical_owl_matches = canonical_owl_graph.isomorphic(graph)
        assert canonical_ttl_matches and canonical_owl_matches

    report = {
        "status": (
            "PASS_FROZEN_SHARED_KG"
            if canonical_release
            else "PASS_FROZEN_ECOLOGY"
        ),
        "dataset_version": dataset_version,
        "source_sha256_verified": True,
        "frozen_version_manifest_verified": True,
        "analysis_input_manifest_verified": True,
        "analysis_output_checksums_verified": True,
        "accepted_rows": len(accepted),
        "measurement_processes": len(processes),
        "measurement_values": len(values),
        "acidity_qualities": len(qualities),
        "sessions": len(sessions),
        "shex_positive_validation": "PASS",
        "shex_positive_shape_map_entries": len(entries),
        "shex_positive_shape_map_sha256": sha256_file(positive_shape_map),
        "shex_negative_missing_unit": "REJECTED_AS_EXPECTED",
        "shex_negative_fixture_triples": len(negative),
        "shex_negative_fixture_sha256": sha256_file(negative_path),
        "shex_negative_shape_map_sha256": sha256_file(negative_shape_map),
        "shex_negative_log_sha256": sha256_file(negative_log),
        "released_kg_imports_dataset_version": imported,
        "canonical_turtle_graph_matches": canonical_ttl_matches,
        "canonical_rdfxml_graph_matches": canonical_owl_matches,
        "ecology_summary_status": ecology["status"],
        "ecology_manuscript_use_allowed": True,
        "canonical_kg_import_allowed": canonical_release,
    }
    (ph_dir / "validation_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--project-root", type=Path, default=Path(__file__).resolve().parents[2]
    )
    parser.add_argument("--ph-dir", type=Path, required=True)
    parser.add_argument("--expected-dataset-version")
    args = parser.parse_args()
    report = validate(
        args.project_root.resolve(),
        args.ph_dir.resolve(),
        args.expected_dataset_version,
    )
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
