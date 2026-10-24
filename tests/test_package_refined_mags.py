import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import tarfile

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("package_mags", ROOT / "scripts/release/package_refined_mags.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def fixture(tmp_path, bases="8"):
    genomes = tmp_path / "genomes"
    genomes.mkdir()
    (genomes / "rep_sub.fa").write_bytes(b">a\nACGT\n>b\nGGTT\n")
    metadata = tmp_path / "metadata.tsv"
    with metadata.open("w", newline="") as f:
        writer = csv.writer(f, delimiter="\t")
        writer.writerow(["mag", "drep_fasta_basename", "Genome_Size", "Total_Contigs"])
        writer.writerow(["rep_sub", "rep_sub.fa", bases, "2"])
    return genomes, metadata, tmp_path / "out"


def test_portable_archive_contains_exact_sequences_and_checksums(tmp_path):
    genomes, metadata, output = fixture(tmp_path)
    MODULE.build(genomes, metadata, output)
    receipt = json.loads((output / "packaging_receipt.json").read_text())
    assert receipt["archive_members_verified"]
    assert receipt["bases"] == 8
    assert receipt["sha256"] == hashlib.sha256((output / "refined_mags.tar.gz").read_bytes()).hexdigest()
    with tarfile.open(output / "refined_mags.tar.gz") as archive:
        assert set(archive.getnames()) == {"genomes/rep_sub.fa", "genome_manifest.tsv"}
        assert archive.extractfile("genomes/rep_sub.fa").read() == (genomes / "rep_sub.fa").read_bytes()


def test_parent_bin_length_mismatch_rejects_release(tmp_path):
    genomes, metadata, output = fixture(tmp_path, bases="10")
    with pytest.raises(ValueError, match="CheckM2/FASTA mismatch"):
        MODULE.build(genomes, metadata, output)
    assert not (output / "refined_mags.tar.gz").exists()
    assert not (output / "refined_mags.tar.gz.partial").exists()


def test_extra_genome_rejects_release(tmp_path):
    genomes, metadata, output = fixture(tmp_path)
    (genomes / "extra.fa").write_bytes(b">c\nACGT\n")
    with pytest.raises(ValueError, match="FASTA set differs"):
        MODULE.build(genomes, metadata, output)


@pytest.mark.parametrize("data", [b"", b">a\n", b"ACGT\n", b">a\nA\n>a\nT\n"])
def test_malformed_fasta_rejected(data):
    with pytest.raises(ValueError):
        MODULE.fasta_counts(data)
