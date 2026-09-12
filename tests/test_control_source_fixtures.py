"""Small graph fixtures; these do not regenerate the released graph."""
from pathlib import Path

from openpyxl import Workbook
from rdflib import Graph, RDF

from scripts.rdf.generate_controls_abox import BASE, Builder


def test_pcr_ntc_never_gets_an_extraction_process(tmp_path: Path) -> None:
    ontology = tmp_path / "data/processed/semantics/ontology"
    ontology.mkdir(parents=True)
    Graph().serialize(ontology / "rubalkhali_dna.owl", format="xml")
    samples = tmp_path / "data/metadata/samples"
    samples.mkdir(parents=True)
    book = Workbook()
    book.active.append(["Blank", "Date", "Index", "N", "Samples"])
    book.save(samples / "Sequenced_Samples_by_EB_FifthTrip.xlsx")
    snapshots = samples / "controls/source_snapshots"
    snapshots.mkdir(parents=True)
    (snapshots / "ibex_trip5_16s_samplesheet.tsv").write_text(
        "sampleID\tforwardReads\treverseReads\n"
        "Negative1\tNTC_UDP001_R1.fastq.gz\tNTC_UDP001_R2.fastq.gz\n"
        "EB18\tEB_UDP002_R1.fastq.gz\tEB_UDP002_R2.fastq.gz\n"
    )
    submissions = tmp_path / "data/metadata/sra-submissions"
    submissions.mkdir(parents=True)
    (submissions / "submission-sheet.tsv").write_text("sample_name\n")
    builder = Builder(tmp_path)
    builder.build_trip5()
    assert sorted(row["role_type"] for row in builder.roles) == ["extraction_blank", "pcr_blank"]
    extraction_keys = [key for key in builder.entities if key[1] == "control_extraction"]
    assert len(extraction_keys) == 1
    assert "EB18" in extraction_keys[0][2]
    assert not any("Negative1" in key[2] for key in extraction_keys)
    assert len(set(builder.graph.subjects(RDF.type, BASE.RAK_0000311))) == 2
    assert any(row["disposition"] == "not_applicable" for row in builder.dispositions)
