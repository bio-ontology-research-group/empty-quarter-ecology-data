from __future__ import annotations

import csv
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from rdflib import Graph, Literal, Namespace, RDF, RDFS, URIRef


ROOT = Path(__file__).resolve().parents[1]
GENERATOR = ROOT / "scripts" / "rdf" / "generate_taxonomy_abox.groovy"
STREAMING_VALIDATOR = (
    ROOT / "scripts" / "validation" / "validate_taxonomy_abox_streaming.py"
)
BASE = Namespace("https://rubalkhali.science/kb/")
SIO = Namespace("http://semanticscience.org/resource/")
NCBI = Namespace("http://purl.obolibrary.org/obo/NCBITaxon_")
RANKS = ("domain", "phylum", "class", "order", "family", "genus", "species")
RANK_LABELS = tuple(rank.capitalize() for rank in RANKS)


def checksum_record(path: Path) -> dict[str, object]:
    return {
        "path": str(path),
        "bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def contextual_iri(seed: int) -> str:
    return f"{BASE}RAK_CTX_{seed:024x}"


def mapping_rows(
    segments: tuple[str, ...],
    iris: tuple[str, ...],
    *,
    contextual_indices: frozenset[int] = frozenset(),
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    display: list[str] = []
    for index, (rank, source_name, iri) in enumerate(
        zip(RANKS, segments, iris, strict=True)
    ):
        label = (
            f"unclassified {rank} under {segments[index - 1]}"
            if source_name == "NA"
            else source_name
        )
        display.append(label)
        rows.append(
            {
                "rank": rank,
                "source_name": source_name,
                "label": label,
                "iri": iri,
                "mapping_status": (
                    "contextual"
                    if index in contextual_indices
                    else (
                        "validated_ncbi"
                        if iri.startswith(str(NCBI))
                        else "stable_project"
                    )
                ),
                "reason": "fixture",
                "source_lineage": ";".join(segments[: index + 1]),
                "lineage": "; ".join(
                    f"{RANK_LABELS[position]}: {value}"
                    for position, value in enumerate(display)
                ),
                "parent_iri": None if index == 0 else iris[index - 1],
                "original_id": None,
                "is_inherited": False,
            }
        )
    return rows


def write_fixture(directory: Path) -> dict[str, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    taxonomy = directory / "taxonomy.tsv"
    feature_table = directory / "feature-table.tsv"
    mapping_json = directory / "mapped_taxonomy_corrected.json"
    mapping_tsv = directory / "mapped_taxonomy_corrected.tsv"
    ledger = directory / "taxonomy_mapping_ledger.tsv"
    module = directory / "ecosystem_module.owl"
    sra_sheet = directory / "submission-sheet.tsv"
    sra_ontology = directory / "rubalkhali_sra.owl"
    manifest = directory / "mapped_taxonomy_corrected.manifest.json"
    output = directory / "rubalkhali_taxonomy_abox.ttl"

    first = ("Bacteria", "P1", "C1", "O1", "F1", "G1", "NA")
    second = ("Bacteria", "P2", "C2", "O2", "F2", "G2", "asserted2")
    first_iris = (
        str(NCBI["2"]),
        str(NCBI["1224"]),
        f"{BASE}RAK_TEST_C1",
        f"{BASE}RAK_TEST_O1",
        f"{BASE}RAK_TEST_F1",
        f"{BASE}RAK_TEST_G1",
        contextual_iri(1),
    )
    second_iris = (
        str(NCBI["2"]),
        str(NCBI["1224"]),
        f"{BASE}RAK_TEST_C2",
        f"{BASE}RAK_TEST_O2",
        f"{BASE}RAK_TEST_F2",
        f"{BASE}RAK_TEST_G2",
        f"{BASE}RAK_TEST_S2",
    )
    corrected = {
        ";".join(first): mapping_rows(
            first, first_iris, contextual_indices=frozenset({6})
        ),
        ";".join(second): mapping_rows(second, second_iris),
    }
    mapping_json.write_text(
        json.dumps(corrected, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    mapping_tsv.write_text("fixture\n", encoding="utf-8")
    ledger.write_text("fixture\n", encoding="utf-8")
    module.write_text(
        f"""@prefix owl: <http://www.w3.org/2002/07/owl#> .
<{BASE}ecosystem_module.owl> a owl:Ontology .
""",
        encoding="utf-8",
    )

    # Feature f1 has a supplementary-only species in field 8; it must remain
    # unclassified. Feature f2 has a conflicting field-8 species; the asserted
    # first-seven species must win. f3 exercises the seven-field encoding and
    # aggregates with f1.
    taxonomy.write_text(
        "Feature ID\tTaxon\tUnused\n"
        "f1\td__Bacteria;p__P1;c__C1;o__O1;f__F1;g__G1;"
        ";supplementary_only;0.99\t\n"
        "f2\tBacteria;P2;C2;O2;F2;G2;asserted2;"
        "conflicting_species;0.80\t\n"
        "f3\tBacteria;P1;C1;O1;F1;G1;unclassified\t\n",
        encoding="utf-8",
    )
    feature_table.write_text(
        "# Constructed fixture\n"
        "#OTU ID\tEB1\te1_S1\n"
        "f1\t4\t10\n"
        "f2\t0\t5\n"
        "f3\t0\t3\n",
        encoding="utf-8",
    )
    with sra_sheet.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            delimiter="\t",
            fieldnames=("sample_name", "run_accession"),
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerow({"sample_name": "S1", "run_accession": "ERR000001"})
        # Released submission metadata retain extraction-blank accessions, but
        # the FASTQ ontology deliberately excludes those controls.
        writer.writerow({"sample_name": "EB1", "run_accession": "ERR000099"})
    sra_ontology.write_text(
        f"""<?xml version="1.0"?>
<rdf:RDF
  xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
  xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#"
  xmlns:owl="http://www.w3.org/2002/07/owl#">
  <owl:Ontology rdf:about="{BASE}rubalkhali_sra.owl"/>
  <owl:NamedIndividual rdf:about="{BASE}RAK_7790001">
    <rdfs:label>FASTQ dataset for ERR000001</rdfs:label>
  </owl:NamedIndividual>
</rdf:RDF>
""",
        encoding="utf-8",
    )
    manifest.write_text(
        json.dumps(
            {
                "status": "passed",
                "schema_version": "taxonomy-mapping-v1",
                "artifacts": {
                    "corrected_json": checksum_record(mapping_json),
                    "corrected_tsv": checksum_record(mapping_tsv),
                    "ledger": checksum_record(ledger),
                    "ecosystem_module": checksum_record(module),
                },
                "inputs": {
                    "source_taxonomy": checksum_record(taxonomy),
                    "feature_table": checksum_record(feature_table),
                    "canonical_mapping": {"path": "fixture", "sha256": "0" * 64},
                    "ncbi_taxonomy": {"path": "fixture", "sha256": "1" * 64},
                },
                "counts": {
                    "source_taxon_strings": 2,
                    "mapped_taxon_strings": 2,
                    "missing_taxon_strings": 0,
                    "mapping_rows": 14,
                },
                "checks": {
                    "ancestry": {"status": "passed"},
                    "coverage": {"status": "passed"},
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return {
        "taxonomy": taxonomy,
        "feature_table": feature_table,
        "mapping_json": mapping_json,
        "manifest": manifest,
        "module": module,
        "sra_sheet": sra_sheet,
        "sra_ontology": sra_ontology,
        "output": output,
    }


def run_generator(paths: dict[str, Path], output: Path | None = None):
    output = output or paths["output"]
    command = [
        "groovy",
        str(GENERATOR),
        "--mapping-json",
        str(paths["mapping_json"]),
        "--mapping-manifest",
        str(paths["manifest"]),
        "--taxonomy-tsv",
        str(paths["taxonomy"]),
        "--feature-table",
        str(paths["feature_table"]),
        "--sra-sheet",
        str(paths["sra_sheet"]),
        "--sra-ontology",
        str(paths["sra_ontology"]),
        "--import-module",
        str(paths["module"]),
        "--import-iri",
        f"{BASE}ecosystem_module.owl",
        "--output",
        str(output),
    ]
    env = os.environ.copy()
    env.setdefault("JAVA_OPTS", "-Xmx2g")
    return subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=180,
        check=False,
    )


@pytest.fixture(scope="module")
def generated_fixture(tmp_path_factory):
    paths = write_fixture(tmp_path_factory.mktemp("taxonomy-generator"))
    result = run_generator(paths)
    assert result.returncode == 0, result.stdout + result.stderr
    graph = Graph()
    graph.parse(paths["output"], format="turtle")
    return paths, graph


def absolute_values_by_rank(graph: Graph) -> dict[str, list[float]]:
    result: dict[str, list[float]] = {rank: [] for rank in RANK_LABELS}
    for value in graph.subjects(RDF.type, BASE.RAK_0000076):
        label = str(graph.value(value, RDFS.label))
        rank = label.rsplit("(", 1)[1].removesuffix(")")
        result[rank].append(float(graph.value(value, BASE.RAK_2000026)))
    return result


def test_source_lineage_variants_are_split_and_counts_are_conserved(
    generated_fixture,
):
    _, graph = generated_fixture
    by_rank = absolute_values_by_rank(graph)
    assert by_rank["Domain"] == [18.0]
    assert sorted(by_rank["Phylum"]) == [5.0, 13.0]
    for values in by_rank.values():
        assert sum(values) == pytest.approx(18.0)

    relative_values = [
        float(number)
        for value in graph.subjects(RDF.type, BASE.RAK_0000073)
        if str(graph.value(value, RDFS.label)).endswith("(Phylum)")
        for number in graph.objects(value, BASE.RAK_2000020)
    ]
    assert sorted(relative_values) == pytest.approx([5 / 18, 13 / 18])
    assert sum(relative_values) == pytest.approx(1.0)


def test_bacteria_and_unclassified_species_use_audited_iris(generated_fixture):
    _, graph = generated_fixture
    bearers = {
        bearer
        for quality in graph.subjects(RDF.type, BASE.RAK_0000078)
        for bearer in graph.objects(quality, SIO.SIO_000011)
    }
    assert NCBI["2"] in bearers
    assert URIRef(contextual_iri(1)) in bearers
    # The historical synonym-collision result must never reappear.
    assert NCBI["629395"] not in bearers


def test_sheet_only_recognized_control_is_excluded_from_processes(
    generated_fixture,
):
    _, graph = generated_fixture
    process_labels = {
        str(graph.value(process, RDFS.label))
        for process in graph.subjects(RDF.type, BASE.RAK_0000071)
    }
    assert process_labels == {
        "16S amplicon processing of S1 (ERR000001)"
    }
    assert not any("EB1" in label for label in process_labels)


def test_each_value_has_one_rank_truncated_source_lineage(generated_fixture):
    _, graph = generated_fixture
    for value_class in (BASE.RAK_0000076, BASE.RAK_0000073):
        for value in graph.subjects(RDF.type, value_class):
            lineages = list(graph.objects(value, BASE.RAK_2000025))
            assert len(lineages) == 1
            label = str(graph.value(value, RDFS.label))
            rank = label.rsplit("(", 1)[1].removesuffix(")")
            segments = str(lineages[0]).split("; ")
            assert len(segments) == RANK_LABELS.index(rank) + 1
            assert segments[-1].startswith(f"{rank}: ")
    species_lineages = {
        str(graph.value(value, BASE.RAK_2000025))
        for value in graph.subjects(RDF.type, BASE.RAK_0000076)
        if str(graph.value(value, RDFS.label)).endswith("(Species)")
    }
    assert "Species: NA" in "\n".join(species_lineages)
    assert "supplementary_only" not in "\n".join(species_lineages)
    assert "conflicting_species" not in "\n".join(species_lineages)
    assert "Species: asserted2" in "\n".join(species_lineages)


def test_generation_is_byte_deterministic(generated_fixture):
    paths, _ = generated_fixture
    second = paths["output"].with_name("second.ttl")
    result = run_generator(paths, second)
    assert result.returncode == 0, result.stdout + result.stderr
    assert paths["output"].read_bytes() == second.read_bytes()


def test_streamed_graph_matches_semantic_golden_fixture(generated_fixture):
    _, graph = generated_fixture
    # This blank-node-free canonical triple digest was established against the
    # former OWLAPI materialization. It guards the streaming refactor against
    # silently adding, dropping, or changing any fixture axiom.
    canonical = "".join(
        sorted(
            f"{subject.n3()} {predicate.n3()} {obj.n3()} .\n"
            for subject, predicate, obj in graph
        )
    ).encode("utf-8")
    assert len(graph) == 488
    assert (
        hashlib.sha256(canonical).hexdigest()
        == "40494dd75ba3dbfc8757afd33bb41b4b92a96cdb4369577399ce1401a45c2017"
    )


def test_generated_fixture_passes_complete_streaming_validator(
    generated_fixture, tmp_path
):
    paths, _ = generated_fixture
    report = tmp_path / "streaming-validation.json"
    result = subprocess.run(
        [
            sys.executable,
            str(STREAMING_VALIDATOR),
            "--input",
            str(paths["output"]),
            "--output",
            str(report),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["status"] == "passed"
    assert payload["turtle_parser"]["triple_count"] == 488
    assert payload["structural_results"]["violations"]["total"] == 0


def test_stale_corrected_mapping_manifest_fails_closed(tmp_path):
    paths = write_fixture(tmp_path / "stale")
    with paths["mapping_json"].open("a", encoding="utf-8") as handle:
        handle.write(" ")
    result = run_generator(paths)
    assert result.returncode != 0
    assert "Stale corrected mapping JSON" in result.stderr
    assert not paths["output"].exists()


def test_missing_taxon_mapping_fails_closed_even_with_fresh_source_hash(tmp_path):
    paths = write_fixture(tmp_path / "missing")
    with paths["taxonomy"].open("a", encoding="utf-8") as handle:
        handle.write("f4\tBacteria;P3;C3;O3;F3;G3;s3\t\n")
    manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
    manifest["inputs"]["source_taxonomy"] = checksum_record(paths["taxonomy"])
    manifest["counts"]["source_taxon_strings"] = 3
    paths["manifest"].write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    result = run_generator(paths)
    assert result.returncode != 0
    assert "coverage mismatch" in result.stderr
    assert not paths["output"].exists()


def test_sheet_only_non_control_run_fails_closed(tmp_path):
    paths = write_fixture(tmp_path / "missing-fastq")
    with paths["sra_sheet"].open("a", encoding="utf-8") as handle:
        handle.write("BIO_MISSING\tERR999999\n")
    result = run_generator(paths)
    assert result.returncode != 0
    assert (
        "SRA sheet run ERR999999 for non-control sample BIO_MISSING "
        "has no FASTQ individual"
    ) in result.stderr
    assert not paths["output"].exists()
