from pathlib import Path

from scripts.validation.audit_taxonomy_mapping import (
    NcbiRecord,
    audit_rows,
    iter_ncbi_records,
    read_mapping,
)


RANKS = ("Kingdom", "Phylum", "Class", "Order", "Family", "Genus", "Species")


def write_mapping(path: Path, taxon_rows: list[tuple[str, list[tuple]]]) -> None:
    lines = [
        "\t".join(
            (
                "Taxon String",
                "Rank",
                "Name",
                "Mapped ID",
                "Is RAK",
                "Is Inherited",
            )
        )
    ]
    for taxon_string, cells in taxon_rows:
        for rank, (name, mapped_id, is_rak, inherited) in zip(RANKS, cells):
            lines.append(
                "\t".join(
                    (
                        taxon_string,
                        rank,
                        name,
                        mapped_id,
                        str(is_rak),
                        str(inherited),
                    )
                )
            )
    path.write_text("\n".join(lines) + "\n")


def write_ncbi(path: Path, records: list[tuple[str, str, str]]) -> None:
    body = []
    for identifier, label, rank in records:
        body.append(
            f"""
  <owl:Class rdf:about="http://purl.obolibrary.org/obo/NCBITaxon_{identifier}">
    <ncbitaxon:has_rank rdf:resource="http://purl.obolibrary.org/obo/NCBITaxon_{rank}"/>
    <rdfs:label>{label}</rdfs:label>
  </owl:Class>"""
        )
    path.write_text(
        """<?xml version="1.0"?>
<rdf:RDF
 xmlns:owl="http://www.w3.org/2002/07/owl#"
 xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
 xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#"
 xmlns:ncbitaxon="http://purl.obolibrary.org/obo/ncbitaxon#">
"""
        + "".join(body)
        + "\n</rdf:RDF>\n"
    )


def test_valid_mapping_passes_authoritative_rank_and_label_audit(tmp_path):
    mapping = tmp_path / "mapping.tsv"
    ncbi = tmp_path / "ncbi.owl"
    names = (
        "Bacteria",
        "Examplephylum",
        "Exampleclass",
        "Exampleorder",
        "Examplefamily",
        "Examplegenus",
        "exampleensis",
    )
    taxon = ";".join(names)
    cells = [
        (name, str(index), False, False)
        for index, name in enumerate(names, start=1)
    ]
    write_mapping(mapping, [(taxon, cells)])
    write_ncbi(
        ncbi,
        [
            (
                str(index),
                (
                    "Examplegenus exampleensis"
                    if rank == "species"
                    else names[index - 1]
                ),
                "superkingdom" if rank == "kingdom" else rank,
            )
            for index, rank in enumerate(
                ("kingdom", "phylum", "class", "order", "family", "genus", "species"),
                start=1,
            )
        ],
    )

    rows = read_mapping(mapping)
    records = iter_ncbi_records(ncbi, {row.mapped_id for row in rows})
    assert audit_rows(rows, records) == []


def test_audit_detects_wrong_species_and_contextual_local_id_reuse(tmp_path):
    mapping = tmp_path / "mapping.tsv"
    first_names = (
        "Bacteria",
        "P1",
        "C1",
        "O1",
        "F1",
        "Mycobacterium",
        "elephantis",
    )
    second_names = ("Bacteria", "P2", "C2", "O2", "F2", "G2", "s2")
    first = [
        (name, f"RAK_A{index}", True, False)
        for index, name in enumerate(first_names, start=1)
    ]
    first[-1] = ("elephantis", "999", False, False)
    second = [
        (name, f"RAK_B{index}", True, False)
        for index, name in enumerate(second_names, start=1)
    ]
    # Reuse one local identifier under a different parent and with a
    # different label.  This is the historical failure mode for generic
    # placeholder labels such as "Incertae Sedis".
    first[4] = ("F1", "RAK_COLLISION", True, False)
    second[4] = ("F2", "RAK_COLLISION", True, False)
    write_mapping(
        mapping,
        [
            (";".join(first_names), first),
            (";".join(second_names), second),
        ],
    )
    rows = read_mapping(mapping)
    records = {
        "999": NcbiRecord(identifier="999", label="Elephantis", rank="genus")
    }

    codes = {item["code"] for item in audit_rows(rows, records)}
    assert "ncbi_rank_mismatch" in codes
    assert "ncbi_label_mismatch" in codes
    assert "project_identifier_context_collision" in codes
    assert "explicit_identifier_rank_or_label_collision" in codes
