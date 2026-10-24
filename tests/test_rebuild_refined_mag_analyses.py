import csv
import hashlib
import importlib.util
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/release"))
SPEC = importlib.util.spec_from_file_location("rebuild_mags", ROOT / "scripts/release/rebuild_refined_mag_analyses.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_reference_keeps_duplicate_original_contig_names(tmp_path):
    genomes = tmp_path / "genomes"
    genomes.mkdir()
    data = b">shared\nACGT\n"
    for name in ("A", "B"):
        (genomes / (name + ".fa")).write_bytes(data)
    manifest = tmp_path / "manifest.tsv"
    with manifest.open("w", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(["mag", "sha256"])
        for name in ("A", "B"):
            writer.writerow([name, hashlib.sha256(data).hexdigest()])
    MODULE.build_reference(genomes, manifest, tmp_path / "ref")
    assert (tmp_path / "ref/refined.fa").read_bytes() == b">A|shared\nACGT\n>B|shared\nACGT\n"
    assert (tmp_path / "ref/genomes.tsv").read_text() == "A\tA|shared\nB\tB|shared\n"


@pytest.mark.parametrize("length,frac,valid", [("4", "0.5", True), ("3", "0.5", False), ("4", "NaN", False), ("4", "2", False)])
def test_coverage_requires_exact_reference_lengths_and_finite_fractions(tmp_path, length, frac, valid):
    path = tmp_path / "S.tsv"
    path.write_text("Genome\tS Mean\tS Covered Fraction\tS Trimmed Mean\tS Read Count\tS Length\n"
                    f"A\t1\t{frac}\t1\t2\t{length}\n")
    if valid:
        MODULE.validate_coverage(path, "S", {"A": {"bases": "4"}})
    else:
        with pytest.raises(ValueError):
            MODULE.validate_coverage(path, "S", {"A": {"bases": "4"}})


def test_feature_counts_use_named_columns_and_unique_genes(tmp_path):
    path = tmp_path / "annotations"
    path.write_text("## emapper-2.1.13\n#query\tKEGG_ko\tCAZy\tPFAMs\tPreferred_name\n"
                    "g1\tko:K00001,ko:K00001\tGH1\tPF1,PF2\tfoo\n"
                    "g2\t-\t-\tPF1\t-\n")
    counts, annotated, ko = MODULE.feature_counts(path)
    assert counts["ko"] == {"K00001": 1}
    assert counts["pfam"] == {"PF1": 2, "PF2": 1}
    assert (annotated, ko) == (2, 1)
    with path.open("a") as handle:
        handle.write("g1\t-\t-\t-\t-\n")
    with pytest.raises(ValueError, match="duplicate"):
        MODULE.feature_counts(path)


def test_mapping_bam_basename_preserves_coverm_sample_labels():
    script = (ROOT / "scripts/release/rebuild_refined_mag_analyses.sbatch").read_text()
    assert 'coverm genome -b "$scratch/$sample.bam"' in script


@pytest.mark.parametrize("mode,tasks,total", [("map", 110, 551), ("annotate", 272, 5438)])
def test_packed_jobs_cover_each_nonpilot_index_once(tmp_path, mode, tasks, total):
    wrapper = tmp_path / "bash"
    wrapper.write_text('#!/bin/sh\nprintf "%s %s\\n" "$SLURM_ARRAY_TASK_ID" "$2"\n')
    wrapper.chmod(0o755)
    indices = []
    for task in range(1, tasks + 1):
        env = dict(os.environ, EQ_MAG_WORK=str(tmp_path), SLURM_ARRAY_TASK_ID=str(task),
                   PATH=str(tmp_path) + os.pathsep + os.environ["PATH"])
        result = subprocess.check_output(["/bin/bash", str(ROOT / "scripts/release/rebuild_refined_mag_analyses.sbatch"),
                                          mode + "-packed"], env=env, text=True)
        for line in result.splitlines():
            index, actual_mode = line.split()
            assert actual_mode == mode
            indices.append(int(index))
    assert indices == list(range(2, total + 1))


def test_annotation_receipt_rejects_changes_after_completion(tmp_path):
    release = tmp_path / "release"
    release.mkdir()
    (release / "genome_manifest.tsv").write_text("mag\tsha256\nA\tabc\n")
    directory = tmp_path / "annotation"
    (directory / "bakta").mkdir(parents=True)
    (directory / "eggnog").mkdir()
    for suffix in (".faa", ".gff3", ".fna"):
        (directory / "bakta" / ("A" + suffix)).write_text(">g1\nACGT\n")
    annotation = directory / "eggnog/A.emapper.annotations"
    annotation.write_text("#query\tKEGG_ko\tCAZy\tPFAMs\tPreferred_name\ng1\t-\t-\t-\t-\n")
    for tool in ("bakta", "eggnog"):
        (directory / (tool + ".version.txt")).write_text("test version\n")
    MODULE.annotation_receipt(tmp_path, "A", directory)
    MODULE.annotation_receipt(tmp_path, "A", directory)
    annotation.write_text(annotation.read_text().replace("g1\t-", "g1\tko:K00001"))
    with pytest.raises(ValueError, match="completed annotation changed"):
        MODULE.annotation_receipt(tmp_path, "A", directory)
