import csv
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from rdflib import OWL, RDF, Graph, Namespace, URIRef


ROOT = Path(__file__).resolve().parents[1]
PH = ROOT / "analysis/v3/ph_shared_v1"
VERSION = "EQ-PH-SHARED-v1.0.0"
SOURCE_SHA256 = "701db2a771b257da09bb276c8ca29df4408ba5986bd515821ccea275a8c692c1"
ONTOLOGY_IRI = URIRef(
    "https://rubalkhali.science/kb/rubalkhali_ph_eq_ph_shared_v1_0_0.owl"
)
SIO = Namespace("http://semanticscience.org/resource/")
PATO = Namespace("http://purl.obolibrary.org/obo/PATO_")
UO = Namespace("http://purl.obolibrary.org/obo/UO_")


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def test_shared_freeze_accounts_for_every_source_row() -> None:
    summary = json.loads((PH / "summary.json").read_text(encoding="utf-8"))
    assert summary["status"] == "FROZEN_SHARED_MANUSCRIPTS"
    assert summary["dataset_version"] == VERSION
    assert summary["dataset_purpose"] == "shared-manuscripts"
    assert summary["measurement_campaign_closed"]
    assert summary["collection_status"] == "COMPLETE_AS_AVAILABLE"
    assert not summary["source_complete"]
    assert summary["source"]["sha256"] == SOURCE_SHA256
    assert summary["counts"] == {
        "admitted_rows": 712,
        "dispositions": {
            "ADMITTED_MEASUREMENT": 712,
            "NOT_MEASURED_DEPLETED": 45,
            "PENDING_MEASUREMENT": 356,
            "QUARANTINED_DATE": 36,
            "QUARANTINED_QC": 19,
        },
        "rdf_measurement_processes": 712,
        "rdf_ph_values": 712,
        "sessions": 29,
        "source_rows": 1168,
    }
    assert summary["release_gate"]["ecology_analysis_frozen"]
    assert summary["release_gate"]["canonical_kg_import_allowed"]


def test_known_trip4_unavailable_rows_are_not_imputed() -> None:
    audit = {
        row["sample_id"]: row
        for row in read_tsv(PH / "normalized/ph_observation_audit.tsv")
    }
    assert audit["S28Sr1"]["notes"] == "Missed to prepare"
    assert audit["S28Sr1"]["disposition"] == "PENDING_MEASUREMENT"
    assert audit["S28Sr1"]["ph_value"] == ""
    assert audit["S57Dr1"]["notes"] == "Depleted"
    assert audit["S57Dr1"]["disposition"] == "NOT_MEASURED_DEPLETED"
    assert audit["S57Dr1"]["ph_value"] == ""
    trip4_qc = [
        row
        for row in audit.values()
        if row["trip"] == "4" and row["disposition"] == "QUARANTINED_QC"
    ]
    assert len(trip4_qc) == 19
    assert all(row["kg_eligible"] == "False" for row in trip4_qc)


def test_shared_graph_uses_sio_pattern_and_is_canonical() -> None:
    generated_ttl = Graph().parse(
        PH / "kg/rubalkhali_ph_measurements.ttl", format="turtle"
    )
    generated_owl = Graph().parse(
        PH / "kg/rubalkhali_ph_measurements.owl", format="xml"
    )
    canonical_ttl = Graph().parse(
        ROOT
        / "data/processed/semantics/ontology/rubalkhali_ph_eq_ph_shared_v1_0_0.ttl",
        format="turtle",
    )
    canonical_owl = Graph().parse(
        ROOT
        / "data/processed/semantics/ontology/rubalkhali_ph_eq_ph_shared_v1_0_0.owl",
        format="xml",
    )
    assert generated_ttl.isomorphic(generated_owl)
    assert generated_ttl.isomorphic(canonical_ttl)
    assert generated_ttl.isomorphic(canonical_owl)

    processes = set(generated_ttl.subjects(RDF.type, SIO.SIO_001054))
    values = set(generated_ttl.subjects(RDF.type, SIO.SIO_001089))
    qualities = set(generated_ttl.subjects(RDF.type, PATO.PATO_0001842))
    assert len(processes) == len(values) == len(qualities) == 712
    for value in values:
        assert (value, RDF.type, SIO.SIO_000070) in generated_ttl
        assert (value, SIO.SIO_000221, UO.UO_0000196) in generated_ttl
        assert len(list(generated_ttl.objects(value, SIO.SIO_000215))) == 1
        assert len(list(generated_ttl.objects(value, SIO.SIO_000232))) == 1

    root_graph = Graph().parse(
        ROOT / "data/processed/semantics/ontology/rubalkhali_kb.owl"
    )
    assert (None, OWL.imports, ONTOLOGY_IRI) in root_graph

    shape = (
        ROOT / "data/processed/semantics/shex/ph_measurements.shex"
    ).read_text(encoding="utf-8")
    assert "sio:SIO_000232 @<#PHMeasurementProcessShape>" in shape
    assert "sio:SIO_000216 @<#PHMeasurementValueShape>" in shape


def test_shared_sh_ex_evidence_enumerates_nodes_and_negative_fixture() -> None:
    kg = PH / "kg"
    shape_map = kg / "ph_validation.shexmap"
    entries = shape_map.read_text(encoding="utf-8").splitlines()
    assert len(entries) == 2167
    assert len(set(entries)) == 2167
    assert all(
        "https://rubalkhali.science/schema/ph_measurements#" in row
        for row in entries
    )

    negative = Graph().parse(kg / "ph_negative_missing_unit.ttl", format="turtle")
    negative_values = set(negative.subjects(RDF.type, SIO.SIO_001089))
    assert len(negative_values) == 1
    negative_value = next(iter(negative_values))
    assert (negative_value, SIO.SIO_000221, UO.UO_0000196) not in negative
    assert (kg / "ph_negative_missing_unit.log").read_text(
        encoding="utf-8"
    ).startswith("FAIL\n")

    report = json.loads((PH / "validation_report.json").read_text(encoding="utf-8"))
    assert report["shex_positive_shape_map_entries"] == 2167
    assert report["shex_positive_shape_map_sha256"] == hashlib.sha256(
        shape_map.read_bytes()
    ).hexdigest()
    assert report["shex_negative_fixture_triples"] == 37
    assert report["shex_negative_missing_unit"] == "REJECTED_AS_EXPECTED"


def test_ecology_analysis_uses_all_admitted_available_measurements() -> None:
    summary = json.loads(
        (PH / "ecology/summary.json").read_text(encoding="utf-8")
    )
    assert summary["dataset_version"] == VERSION
    assert summary["schema_version"] == "ph-shared-v1.1.0"
    assert summary["counts"]["accepted_ph_specimens"] == 712
    assert summary["counts"]["accepted_specimens_with_ecology_profile"] == 702
    assert summary["counts"]["site_campaign_position_groups"] == 562
    assert summary["counts"]["composition_groups"] == 558
    assert summary["counts"]["sites"] == 60
    assert summary["alpha_primary"]["p"] == pytest.approx(0.4826812247105965)
    assert summary["composition_primary"]["partial_r2"] == pytest.approx(
        0.0027425505215512153
    )
    assert summary["composition_primary"]["p"] == pytest.approx(0.126)
    geography = summary["geographic_same_cohort"]
    assert geography["without_ph_adjustment_partial_r2"] == pytest.approx(
        0.3582660386791946
    )
    assert geography["with_ph_adjustment_partial_r2"] == pytest.approx(
        0.19592506350977723
    )
    influence = summary["maximum_group_influence"]
    assert influence["trip"] == 4
    assert influence["site"] == 60
    assert influence["compartment"] == "Rhizosphere"
    assert influence["ph"] == pytest.approx(9.98)
    assert influence["n_ph_specimens"] == 1
    assert influence["exclude_group_ph_transect_partial_r2"] == pytest.approx(
        0.8261999717823737
    )
    assert influence["exclude_group_geography_after_partial_r2"] == pytest.approx(
        0.18712856915178622
    )
    assert influence["exclude_site_ph_transect_partial_r2"] == pytest.approx(
        0.832700411321767
    )
    assert influence["all_refit_p_values_at_permutation_floor"]

    geographic = read_tsv(PH / "ecology/ph_geographic_adjustment.tsv")
    assert {int(row["n_sites"]) for row in geographic} == {60}
    assert {int(row["residual_df"]) for row in geographic} == {57}

    paired = {
        row["comparison"]: row
        for row in read_tsv(PH / "ecology/ph_paired_position_contrasts.tsv")
    }
    assert int(paired["Deep-Surface"]["n_nonzero_sites"]) == 60
    assert int(paired["Rhizosphere-Surface"]["n_nonzero_sites"]) == 60
    assert int(paired["Rhizosphere-Deep"]["n_nonzero_sites"]) == 59


def test_predecessor_comparison_has_only_unchanged_and_added_rows() -> None:
    report = json.loads(
        (PH / "version_comparison/summary.json").read_text(encoding="utf-8")
    )
    assert report["counts"] == {"ADDED_IN_SUCCESSOR": 59, "UNCHANGED": 653}
    assert not report["material_review_required"]


def test_generator_is_byte_reproducible(tmp_path: Path) -> None:
    rerun = tmp_path / "ph-shared"
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/rdf/generate_ph_dataset.py"),
            "--workbook",
            str(
                ROOT
                / "data/metadata/samples/ph/versions"
                / VERSION
                / "ph_measurements.xlsx"
            ),
            "--project-root",
            str(ROOT),
            "--output-dir",
            str(rerun),
            "--as-of",
            "2026-08-03",
            "--dataset-version",
            VERSION,
            "--dataset-status",
            "FROZEN",
            "--dataset-purpose",
            "shared-manuscripts",
            "--measurement-campaign-closed",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    for relative in (
        "normalized/ph_observation_audit.tsv",
        "normalized/ph_accepted_measurements.tsv",
        "normalized/ph_measurement_sessions.tsv",
        "normalized/ph_entity_registry.tsv",
        "kg/rubalkhali_ph_measurements.ttl",
        "kg/rubalkhali_ph_measurements.owl",
    ):
        assert (rerun / relative).read_bytes() == (PH / relative).read_bytes()
    rerun_summary = json.loads((rerun / "summary.json").read_text(encoding="utf-8"))
    staged_summary = json.loads((PH / "summary.json").read_text(encoding="utf-8"))
    # A package compatibility symlink changes only the displayed source path;
    # all scientific fields and source bytes remain identical.
    rerun_summary["source"].pop("path", None)
    staged_summary["source"].pop("path", None)
    assert rerun_summary == staged_summary


def test_shared_ph_version_is_provenance_not_article_prose() -> None:
    configured_ecology = os.environ.get("EQ_ECOLOGY_PAPER")
    ecology_root = (
        Path(configured_ecology)
        if configured_ecology
        else ROOT / "empty-quarter-amplicon"
    )
    if not (ecology_root / "main.tex").is_file():
        if configured_ecology:
            pytest.fail(
                "configured active ecology main.tex is missing: "
                f"{ecology_root / 'main.tex'}"
            )
        pytest.skip("submission manuscripts are not part of the data package")
    ecology_main = (ecology_root / "main.tex").read_text(
        encoding="utf-8"
    )
    ecology_supplement = (
        ecology_root / "supplement.tex"
    ).read_text(encoding="utf-8")
    ecology_ph = (ecology_root / "ph_shared_v1.tex").read_text(
        encoding="utf-8"
    )
    data_paper = "\n".join(
        (ROOT / "data-paper" / name).read_text(encoding="utf-8")
        for name in (
            "sn-article.tex",
            "02_methods.tex",
            "03_knowledge_representation.tex",
            "04_data_records.tex",
            "05_validation.tex",
            "06_usage.tex",
        )
    )
    assert "\\input{ph_shared_v1.tex}" not in ecology_main
    assert "\\input{" not in ecology_main
    assert "\\include{" not in ecology_main
    assert "\\input{ph_shared_v1.tex}" in ecology_supplement
    assert "ph_ecology_v1.tex" not in ecology_main + ecology_supplement
    assert "\\PHEcology" not in ecology_main + ecology_supplement + ecology_ph
    assert VERSION not in ecology_main
    assert VERSION in ecology_ph
    assert (
        "Transect, same cohort before pH & $\\PHGeographySites$ sites"
        in ecology_supplement
    )
    assert VERSION in data_paper
    assert "EQ-PH-DATA-" not in ecology_main + ecology_supplement + data_paper

    generated = ecology_root / "generated/ph_shared_v1_values.tex"
    manifest = json.loads(
        (generated.with_suffix(".manifest.json")).read_text(encoding="utf-8")
    )
    assert manifest["dataset_version"] == VERSION
    assert hashlib.sha256(generated.read_bytes()).hexdigest() == manifest[
        "output"
    ]["sha256"]


def test_release_readme_documents_shared_ph_scope() -> None:
    readme = ROOT / "data-paper/zenodo/README.md"
    if not readme.is_file():
        readme = ROOT / "README.md"
    text = readme.read_text(encoding="utf-8")
    for required in (
        VERSION,
        "1,168 source rows",
        "712 admitted",
        "356 rows without a measurement",
        "45 depleted",
        "36 rows with ambiguous measurement dates",
        "19 numeric rows",
        "evidence/ph/",
        "incomplete and non-random",
        "29 session individuals are",
        "reconstructed",
    ):
        assert required in text


def test_package_layout_exposes_all_inputs_for_shared_ph_driver() -> None:
    bootstrap = ROOT / "scripts/release/bootstrap_package_layout.sh"
    driver = ROOT / "scripts/analysis/run_ph_shared_v1.sh"
    bootstrap_text = bootstrap.read_text(encoding="utf-8")
    driver_text = driver.read_text(encoding="utf-8")
    assert "analysis/v3/spatial_turnover_rescue" in bootstrap_text
    assert "analysis/v3/xrf_community_rescue" in bootstrap_text
    assert "PH_OUTPUT_DIR" in driver_text
    assert "PH_TEX_OUTPUT" in driver_text
    assert "PH_SKIP_TESTS" in driver_text
    predecessor = ROOT / "analysis/v3/ph_ecology_v1"
    for relative in (
        "summary.json",
        "normalized/ph_observation_audit.tsv",
        "kg/rubalkhali_ph_measurements.ttl",
        "ecology/summary.json",
    ):
        assert (predecessor / relative).is_file()
