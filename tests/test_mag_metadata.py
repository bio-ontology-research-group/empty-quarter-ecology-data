import importlib.util
import hashlib
import shutil
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("mag_metadata", ROOT / "scripts/release/prepare_mag_metadata.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def inputs():
    return (
        [{"mag": "A_sub", "sample": "S", "strategy": "single_sample", "bin": "B",
          "refined_sub": "1", "link_target": "per_sample_bin"}],
        [{"sample": "S", "trip": "1", "site": "2", "code": "D", "replicate": "1"}],
        [{"sample": "S", "trip": "1", "site": "2", "replicate": "1", "compartment": "Deep"}],
        [{"Name": "A_sub", "Completeness": "90", "Contamination": "2",
          "Genome_Size": "1000000", "Total_Contigs": "100"}],
        [{"sample": "S", "trip": "1"}],
    )


def test_parent_link_does_not_release_refined_genome_or_analyses():
    libraries, reps, status = MODULE.derive(*inputs())
    assert libraries[0]["run_accession"] == ""
    assert libraries[0]["study_accession"] == "PRJEB125153"
    assert reps[0]["drep_fasta_basename"] == "A_sub.fa"
    assert status["release_status"] == "REFINED_SELECTED_PACKAGING_PENDING"
    assert not any(status[k] for k in ("sequence_release", "annotation_release", "recruitment_release"))


def test_duplicate_ids_fail():
    args = inputs()
    args[0].append(args[0][0].copy())
    with pytest.raises(ValueError, match="duplicate"):
        MODULE.derive(*args)


def test_unmatched_quality_fails():
    args = inputs()
    args[3][0]["Name"] = "B"
    with pytest.raises(ValueError, match="missing library or refined-bin quality"):
        MODULE.derive(*args)


def test_trip_disagreement_fails():
    args = inputs()
    args[2][0]["trip"] = "5"
    with pytest.raises(ValueError, match="context disagrees"):
        MODULE.derive(*args)


@pytest.mark.parametrize("field,value", [("Completeness", "NaN"), ("Completeness", "49"),
                                         ("Contamination", "inf"), ("Contamination", "11")])
def test_out_of_scope_quality_fails(field, value):
    args = inputs()
    args[3][0][field] = value
    with pytest.raises(ValueError, match="thresholds"):
        MODULE.derive(*args)


def test_real_snapshot_is_metadata_only():
    source = ROOT / MODULE.SOURCE
    names = ("catalog_membership.tsv", "samples551.tsv", "metagenome_sample_meta.tsv",
             "checkm2_refined_quality_report.tsv", "metagenome_sample_meta_150.tsv")
    libraries, reps, status = MODULE.derive(*(MODULE.read_table(source / name) for name in names))
    assert (len(libraries), len(reps)) == (551, 5438)
    assert status["refined_sub_representatives"] == 1010
    assert status["legacy_libraries_per_trip"] == {"1": 58, "2": 15, "3": 77}
    MODULE.attach_taxonomy(reps, source)
    assert sum(r["gtdb_r232_classification"].startswith("d__Bacteria;") for r in reps) == 4847
    assert sum(r["gtdb_r232_classification"].startswith("d__Archaea;") for r in reps) == 591


def test_changed_taxonomy_fails_checksum(tmp_path):
    shutil.copytree(ROOT / MODULE.SOURCE / "taxonomy_r232", tmp_path / "taxonomy_r232")
    (tmp_path / "taxonomy_r232/gtdbtk.ar53.summary.tsv").write_text("changed\n")
    with pytest.raises(ValueError, match="checksum differs"):
        MODULE.attach_taxonomy([], tmp_path)


def test_scoped_registration_is_idempotent_and_describes_every_field(tmp_path):
    for folder in ("evidence/mag-catalogue-20261024", MODULE.DEST):
        shutil.copytree(ROOT / folder, tmp_path / folder)
    for name in ("metadata/DATA_DICTIONARY.tsv", "PRE_RELEASE_MANIFEST.tsv", "BULK_ARTIFACTS.tsv",
                 "scripts/release/prepare_mag_metadata.py", "tests/test_mag_metadata.py",
                 "scripts/release/package_refined_mags.py", "tests/test_package_refined_mags.py",
                 "scripts/release/rebuild_refined_mag_analyses.py", "scripts/release/rebuild_refined_mag_analyses.sbatch",
                 "tests/test_rebuild_refined_mag_analyses.py",
                 "scripts/release/stage_mag_zenodo.py", "tests/test_stage_mag_zenodo.py",
                 "scripts/manuscript/update_pre_release_manifest.py"):
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, target)
    MODULE.register(tmp_path)
    first = (tmp_path / "PRE_RELEASE_MANIFEST.tsv").read_bytes()
    MODULE.register(tmp_path)
    assert (tmp_path / "PRE_RELEASE_MANIFEST.tsv").read_bytes() == first
    dictionary = MODULE.read_table(tmp_path / "metadata/DATA_DICTIONARY.tsv")
    for table in (tmp_path / MODULE.DEST).glob("*.tsv"):
        described = {r["field_or_pattern"] for r in dictionary if r["path"] == str(table.relative_to(tmp_path))}
        assert set(MODULE.read_table(table)[0]) == described
    manifest = MODULE.read_table(tmp_path / "PRE_RELEASE_MANIFEST.tsv")
    for row in manifest:
        if row["path"].startswith(MODULE.DEST + "/"):
            if row["path"].endswith(".tar.gz"):
                assert row["release_status"] == "canonical-candidate"
                continue
            path = tmp_path / row["path"]
            assert row["release_status"] == "audit-evidence"
            assert row["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()


def accession_inputs():
    libraries = [{"sample": "S"}, {"sample": "T"}]
    reps = [{"mag": "S__self_SemiBin_1"}]
    runs = [{"sample_id": "S", "biosample_accession": "ERS1", "ena_experiment": "ERX2", "ena_run": "ERR2"},
            {"sample_id": "S", "biosample_accession": "ERS1", "ena_experiment": "ERX1", "ena_run": "ERR1"},
            {"sample_id": "T", "biosample_accession": "ERS3", "ena_experiment": "ERX3", "ena_run": "ERR3"}]
    assemblies = [{"sample_id": "S", "biosample_accession": "ERS1", "ena_analysis": "ERZ1"}]
    quality = {"has_5S": "1", "has_16S": "1", "has_23S": "1", "n_trna_aa": "18"}
    bins = [{"bin": "S__self_SemiBin_1", "sample": "S", "is_representative": "1", "completeness": "95",
             "contamination": "1", "binned_sample_accession": "ERS10", "ena_analysis_binned": "ERZ10",
             "mag_sample_accession": "ERS20", "ena_analysis_mag": "ERZ20", "gca_mag": "", **quality},
            {"bin": "S__self_SemiBin_2", "sample": "S", "is_representative": "0", "completeness": "60",
             "contamination": "4", "binned_sample_accession": "ERS11", "ena_analysis_binned": "ERZ11",
             "mag_sample_accession": "", "ena_analysis_mag": "", "gca_mag": "", **quality}]
    emails = [{"assembly_name": "S__self_SemiBin_1_MAG", "assembly_accession": "GCA_1", "study_id": "PRJEB125153",
               "sample_id": "ERS20", "contig_accessions": "C1-C9", "chromosome_accessions": ""}]
    return libraries, reps, runs, assemblies, bins, emails


def test_accessions_fold_runs_assemblies_and_notified_gca():
    libraries, reps, *rest = accession_inputs()
    genomes = MODULE.attach_accessions(libraries, reps, *rest)
    assert libraries[0]["run_accession"] == "ERR1;ERR2"
    assert libraries[0]["experiment_accession"] == "ERX1;ERX2"
    assert (libraries[0]["assembly_accession"], libraries[1]["assembly_accession"]) == ("ERZ1", "")
    assert [g["mimag_tier"] for g in genomes] == ["high", "medium"]
    assert genomes[0]["gca_accession"] == "GCA_1" and genomes[1]["gca_accession"] == ""


def test_conflicting_gca_sources_fail():
    args = accession_inputs()
    args[4][0]["gca_mag"] = "GCA_2.1"
    with pytest.raises(ValueError, match="disagree"):
        MODULE.attach_accessions(*args)


def test_representative_without_mag_deposit_fails_unless_at_contamination_limit():
    args = accession_inputs()
    args[4][0].update(mag_sample_accession="", ena_analysis_mag="")
    args[5].clear()
    with pytest.raises(ValueError, match="missing its MAG deposit"):
        MODULE.attach_accessions(*args)
    args[4][0]["contamination"] = "10"
    genomes = MODULE.attach_accessions(*args)
    assert genomes[0]["mimag_tier"] == "below-medium"


def test_real_deposit_snapshot_accounts_for_every_object():
    source = ROOT / MODULE.SOURCE
    names = ("catalog_membership.tsv", "samples551.tsv", "metagenome_sample_meta.tsv",
             "checkm2_refined_quality_report.tsv", "metagenome_sample_meta_150.tsv")
    libraries, reps, _ = MODULE.derive(*(MODULE.read_table(source / name) for name in names))
    ena = ROOT / MODULE.ENA_SOURCE
    genomes = MODULE.attach_accessions(libraries, reps, *(MODULE.read_table(ena / name) for name in (
        "wgs_runs.tsv", "wgs_assemblies.tsv", "wgs_bins.tsv", "ena_mag_accession_emails.tsv")))
    assert sum(len(r["run_accession"].split(";")) for r in libraries) == 554
    assert sum(bool(r["assembly_accession"]) for r in libraries) == 549
    assert len(genomes) == 12434
    assert sum(bool(g["gca_accession"]) for g in genomes) == 5437
    tiers = [g["mimag_tier"] for g in genomes if g["is_representative"] == "1"]
    assert (tiers.count("high"), tiers.count("medium"), tiers.count("below-medium")) == (126, 5311, 1)
