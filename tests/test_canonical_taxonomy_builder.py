from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

from rdflib import Graph, OWL, RDF, RDFS, URIRef

from scripts.taxonomy.build_canonical_taxonomy import (
    BASE,
    MAPPING_REASON_PROPERTY,
    MAPPING_STATUS_PROPERTY,
    RANK_PROPERTY,
    SOURCE_LINEAGE_PROPERTY,
    HistoricalCandidate,
    build_mapping,
    candidate_names,
    canonical_segment,
    read_historical_mapping,
    stable_project_identifiers,
)
from scripts.taxonomy.ncbi_index import build_ncbi_index
from scripts.validation.audit_taxonomy_mapping import (
    MappingRow,
    NcbiRecord,
    audit_rows,
)


ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "scripts" / "taxonomy" / "build_canonical_taxonomy.py"
NCBI = "http://purl.obolibrary.org/obo/NCBITaxon_"


def write_ncbi_fixture(path: Path) -> None:
    path.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<rdf:RDF
 xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
 xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#"
 xmlns:owl="http://www.w3.org/2002/07/owl#"
 xmlns:ncbitaxon="http://purl.obolibrary.org/obo/ncbitaxon#">
  <owl:Class rdf:about="http://purl.obolibrary.org/obo/NCBITaxon_1">
    <rdfs:label>root</rdfs:label>
  </owl:Class>
  <owl:Class rdf:about="http://purl.obolibrary.org/obo/NCBITaxon_2">
    <rdfs:subClassOf rdf:resource="http://purl.obolibrary.org/obo/NCBITaxon_1"/>
    <ncbitaxon:has_rank rdf:resource="http://purl.obolibrary.org/obo/NCBITaxon_superkingdom"/>
    <rdfs:label>Bacteria</rdfs:label>
  </owl:Class>
  <owl:Class rdf:about="http://purl.obolibrary.org/obo/NCBITaxon_10">
    <rdfs:subClassOf rdf:resource="http://purl.obolibrary.org/obo/NCBITaxon_2"/>
    <ncbitaxon:has_rank rdf:resource="http://purl.obolibrary.org/obo/NCBITaxon_genus"/>
    <rdfs:label>GenusA</rdfs:label>
  </owl:Class>
  <owl:Class rdf:about="http://purl.obolibrary.org/obo/NCBITaxon_11">
    <rdfs:subClassOf rdf:resource="http://purl.obolibrary.org/obo/NCBITaxon_10"/>
    <ncbitaxon:has_rank rdf:resource="http://purl.obolibrary.org/obo/NCBITaxon_species"/>
    <rdfs:label>GenusA shared</rdfs:label>
  </owl:Class>
  <owl:Class rdf:about="http://purl.obolibrary.org/obo/NCBITaxon_12">
    <rdfs:subClassOf rdf:resource="http://purl.obolibrary.org/obo/NCBITaxon_2"/>
    <ncbitaxon:has_rank rdf:resource="http://purl.obolibrary.org/obo/NCBITaxon_species"/>
    <rdfs:label>Othergenus shared</rdfs:label>
    <obo:hasExactSynonym xmlns:obo="http://www.geneontology.org/formats/oboInOwl#">shared</obo:hasExactSynonym>
  </owl:Class>
</rdf:RDF>
""",
        encoding="utf-8",
    )


def write_historical_fixture(path: Path, lineage: tuple[str, ...]) -> None:
    columns = (
        "Taxon String",
        "Rank",
        "Name",
        "Mapped ID",
        "Is RAK",
        "Is Inherited",
    )
    ranks = ("Kingdom", "Phylum", "Class", "Order", "Family", "Genus", "Species")
    rows = [
        ("2", "False", "False"),
        ("RAK_LOCAL_PHYLUM", "True", "False"),
        ("RAK_LOCAL_PHYLUM", "True", "True"),
        ("RAK_LOCAL_PHYLUM", "True", "True"),
        ("RAK_LOCAL_PHYLUM", "True", "True"),
        ("RAK_LOCAL_PHYLUM", "True", "True"),
        ("RAK_LOCAL_PHYLUM", "True", "True"),
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, delimiter="\t")
        writer.writeheader()
        for rank, name, (identifier, is_rak, inherited) in zip(
            ranks, lineage, rows, strict=True
        ):
            writer.writerow(
                {
                    "Taxon String": ";".join(lineage),
                    "Rank": rank,
                    "Name": name,
                    "Mapped ID": identifier,
                    "Is RAK": is_rak,
                    "Is Inherited": inherited,
                }
            )
        # Known historical export artifact: it must be explicitly quarantined,
        # not allowed to abort the canonical rebuild or enter its mapping.
        writer.writerow(
            {
                "Taxon String": "Taxon",
                "Rank": "Kingdom",
                "Name": "Taxon",
                "Mapped ID": "RAK_0010597",
                "Is RAK": "True",
                "Is Inherited": "False",
            }
        )


def test_canonical_segment_normalizes_all_na_spellings() -> None:
    assert canonical_segment("") == "NA"
    assert canonical_segment("NA") == "NA"
    assert canonical_segment("na") == "NA"
    assert canonical_segment("s__Na") == "NA"
    assert canonical_segment("Unclassified") == "NA"
    assert canonical_segment("uncultured") == "NA"


def test_one_token_species_uses_only_the_binomial_candidate() -> None:
    lineage = ("Bacteria", "P", "C", "O", "F", "GenusA", "shared")
    assert candidate_names(lineage, 6) == {"genusa shared"}


def test_historical_ncbi_audit_rejects_rank_valid_wrong_ancestry() -> None:
    names = ("Bacteria", "P", "C", "O", "F", "G", "s")
    ranks = ("Kingdom", "Phylum", "Class", "Order", "Family", "Genus", "Species")
    taxon_string = ";".join(names)
    rows = [
        MappingRow(
            taxon_string=taxon_string,
            rank=rank,
            name=name,
            mapped_id=str(index),
            is_rak=False,
            is_inherited=False,
            expected_label=("G s" if rank == "Species" else name),
        )
        for index, (rank, name) in enumerate(zip(ranks, names), start=1)
    ]
    ncbi_ranks = (
        "superkingdom",
        "phylum",
        "class",
        "order",
        "family",
        "genus",
        "species",
    )
    records = {
        str(index): NcbiRecord(
            identifier=str(index),
            label=("G s" if rank == "species" else names[index - 1]),
            rank=rank,
        )
        for index, rank in enumerate(ncbi_ranks, start=1)
    }

    # All adjacent pairs are compatible except genus 6 under validated
    # family 5. Rank and label checks alone therefore cannot catch the defect.
    def is_descendant(child: str, ancestor: str) -> bool:
        return int(child) >= int(ancestor) and not (
            child == "6" and ancestor == "5"
        )

    violations = audit_rows(rows, records, is_descendant)
    assert any(
        item["code"] == "ncbi_ancestry_mismatch"
        and item["mapped_id"] == "6"
        for item in violations
    )


def test_known_one_rank_historical_artifact_is_quarantined(tmp_path: Path) -> None:
    lineage = ("Bacteria", "LocalP", "NA", "NA", "NA", "NA", "NA")
    historical_path = tmp_path / "mapping.tsv"
    write_historical_fixture(historical_path, lineage)
    mapping, excluded_artifacts = read_historical_mapping(historical_path)
    assert mapping
    assert excluded_artifacts == 1
    assert all(key[0] != "Taxon" for key in mapping)


def test_stable_project_mapping_is_preserved_and_inherited_na_is_contextual(
    tmp_path: Path,
) -> None:
    ncbi_path = tmp_path / "ncbi.owl"
    write_ncbi_fixture(ncbi_path)
    lineage = ("Bacteria", "LocalP", "NA", "NA", "NA", "NA", "NA")
    historical = {
        (";".join(lineage), "domain"): HistoricalCandidate(
            "2", False, False, "Bacteria", None
        ),
        (";".join(lineage), "phylum"): HistoricalCandidate(
            "RAK_LOCAL_PHYLUM", True, False, "LocalP", "2"
        ),
        (";".join(lineage), "class"): HistoricalCandidate(
            "RAK_LOCAL_PHYLUM", True, True, "NA", "RAK_LOCAL_PHYLUM"
        ),
    }
    with build_ncbi_index(
        ncbi_path, tmp_path / "ncbi.sqlite", {"Bacteria", "LocalP"}
    ) as index:
        mapping, _ = build_mapping(
            {lineage},
            historical,
            index,
            stable_project_identifiers(historical),
        )
    rows = mapping[";".join(lineage)]
    assert rows[0]["mapping_status"] == "validated_ncbi"
    assert rows[1]["mapping_status"] == "stable_project"
    assert rows[1]["iri"] == f"{BASE}RAK_LOCAL_PHYLUM"
    assert rows[2]["mapping_status"] == "contextual"
    assert rows[2]["is_inherited"] is True
    assert rows[1]["lineage"] == "Domain: Bacteria; Phylum: LocalP"
    assert rows[2]["lineage"].endswith("Class: unclassified class in LocalP")


def test_shared_prefix_with_conflicting_histories_is_one_contextual_decision(
    tmp_path: Path,
) -> None:
    ncbi_path = tmp_path / "ncbi.owl"
    write_ncbi_fixture(ncbi_path)
    first = ("Bacteria", "SharedP", "C1", "NA", "NA", "NA", "NA")
    second = ("Bacteria", "SharedP", "C2", "NA", "NA", "NA", "NA")
    historical = {
        (";".join(first), "phylum"): HistoricalCandidate(
            "RAK_FIRST", True, False, "SharedP", "2"
        ),
        (";".join(second), "phylum"): HistoricalCandidate(
            "RAK_SECOND", True, False, "SharedP", "2"
        ),
    }
    with build_ncbi_index(
        ncbi_path, tmp_path / "ncbi.sqlite", {"Bacteria", "SharedP"}
    ) as index:
        mapping, _ = build_mapping(
            {first, second},
            historical,
            index,
            stable_project_identifiers(historical),
        )
    first_phylum = mapping[";".join(first)][1]
    second_phylum = mapping[";".join(second)][1]
    assert first_phylum["mapping_status"] == "contextual"
    assert (
        first_phylum["iri"],
        first_phylum["mapping_status"],
        first_phylum["label"],
    ) == (
        second_phylum["iri"],
        second_phylum["mapping_status"],
        second_phylum["label"],
    )
    assert "conflicting historical" in str(first_phylum["reason"])


def test_end_to_end_builder_covers_source_and_writes_clean_module(
    tmp_path: Path,
) -> None:
    source = tmp_path / "taxonomy.tsv"
    feature_table = tmp_path / "feature-table.tsv"
    historical = tmp_path / "mapping.tsv"
    ncbi = tmp_path / "ncbi.owl"
    output = tmp_path / "canonical"
    audit = tmp_path / "audit"
    lineage = ("Bacteria", "LocalP", "NA", "NA", "NA", "NA", "NA")
    source.write_text(
        "Feature ID\tTaxon\tUnused\n"
        "f1\td__Bacteria;p__LocalP;c__;o__;f__;g__;s__;"
        "s__Supplementary species;0.9\t\n",
        encoding="utf-8",
    )
    feature_table.write_text(
        "# Constructed fixture\n#OTU ID\tS1\nf1\t7\n",
        encoding="utf-8",
    )
    write_historical_fixture(historical, lineage)
    write_ncbi_fixture(ncbi)

    result = subprocess.run(
        [
            sys.executable,
            str(BUILDER),
            "--source-taxonomy",
            str(source),
            "--feature-table",
            str(feature_table),
            "--canonical-mapping",
            str(historical),
            "--ncbi-taxonomy",
            str(ncbi),
            "--output-dir",
            str(output),
            "--audit-dir",
            str(audit),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    manifest = json.loads(
        (output / "mapped_taxonomy_corrected.manifest.json").read_text()
    )
    assert manifest["status"] == "passed"
    assert manifest["counts"]["source_taxon_strings"] == 1
    assert manifest["counts"]["mapped_taxon_strings"] == 1
    assert manifest["counts"]["missing_taxon_strings"] == 0
    assert (
        audit / "taxonomy_source_supplementary_species.tsv"
    ).is_file()
    audit_text = (audit / "taxonomy_mapping_audit.json").read_text()
    assert "quarantin" in audit_text.lower()

    graph = Graph()
    graph.parse(output / "ecosystem_module.owl")
    root = URIRef(f"{NCBI}1")
    bacteria = URIRef(f"{NCBI}2")
    local_phylum = URIRef(f"{BASE}RAK_LOCAL_PHYLUM")
    assert (root, RDF.type, OWL.Class) in graph
    assert (bacteria, RDF.type, OWL.Class) in graph
    assert (local_phylum, RDF.type, OWL.Class) in graph
    assert (bacteria, RDFS.subClassOf, root) in graph
    assert (local_phylum, RDFS.subClassOf, bacteria) in graph
    assert (
        local_phylum,
        URIRef(RANK_PROPERTY),
        None,
    ) in graph
    assert (
        local_phylum,
        URIRef(MAPPING_STATUS_PROPERTY),
        None,
    ) in graph
    assert (
        local_phylum,
        URIRef(SOURCE_LINEAGE_PROPERTY),
        None,
    ) in graph
    assert (
        local_phylum,
        URIRef(MAPPING_REASON_PROPERTY),
        None,
    ) in graph
    assert not list(
        graph.triples(
            (None, URIRef(f"{BASE}RAK_2000025"), None)
        )
    )
    assert not list(graph.triples((None, OWL.equivalentClass, None)))
