import csv
import hashlib
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_LAYOUT = (ROOT / "data/processed/metadata/controls").is_dir()
SOURCE_CONTROLS = (
    ROOT / "data/metadata/samples/controls"
    if REPOSITORY_LAYOUT
    else ROOT / "evidence/controls"
)
NORMALIZED = (
    ROOT / "data/processed/metadata/controls"
    if REPOSITORY_LAYOUT
    else ROOT / "metadata/controls"
)
ANALYSIS = (
    ROOT / "analysis/v3/control_audit"
    if REPOSITORY_LAYOUT
    else ROOT / "evidence/control-audit"
)
REVISION = ROOT / "revision/controls"


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def resolve_summary_output(relative: str) -> Path:
    repository_path = ROOT / relative
    if repository_path.is_file():
        return repository_path
    packaged = ANALYSIS / "sensitivity_inputs" / Path(relative).name
    if packaged.is_file():
        return packaged
    raise FileNotFoundError(relative)


def test_author_ground_truth_freezes_products_stage_and_assay_boundaries():
    rows = {
        row["record_id"]: row
        for row in read_tsv(SOURCE_CONTROLS / "control_ground_truth.tsv")
    }
    assert set(rows) == {f"CGT-{number:03d}" for number in range(1, 12)}
    assert rows["CGT-001"]["material_or_product"].endswith("D6322")
    assert rows["CGT-002"]["material_form"] == "purified high-molecular-weight DNA"
    assert "extraction" not in rows["CGT-002"]["workflow_stage"].lower()
    assert rows["CGT-003"]["material_or_product"].endswith("D6300")
    assert rows["CGT-003"]["material_form"] == "whole cells"
    assert "extraction" in rows["CGT-003"]["workflow_stage"].lower()
    assert rows["CGT-004"]["control_class"] == "no positive control"
    assert rows["CGT-005"]["assay"] == "shotgun metagenomics"
    assert "not sequenced in the Trip-5 16S assay" in rows["CGT-005"]["limitation"]


def test_extraction_blanks_are_batch_scoped_and_unmapped_blanks_stay_bounded():
    rows = {
        row["record_id"]: row
        for row in read_tsv(SOURCE_CONTROLS / "control_ground_truth.tsv")
    }
    mapped = rows["CGT-007"]
    assert "EB1-EB17" in mapped["control_scope"]
    assert "extraction date/batch" in mapped["limitation"]
    assert "not a field trip" in mapped["limitation"]
    unresolved = rows["CGT-008"]
    assert "characterization-only" in unresolved["limitation"]
    assert "Negative1" in unresolved["control_scope"]
    assert rows["CGT-006"]["status"] == "CONFIRMED_AUTHOR"
    assert "23 sites" in rows["CGT-006"]["limitation"]


def test_explicit_pcr_blank_records_are_present_while_complete_map_is_pending():
    aliases = read_tsv(NORMALIZED / "control_aliases.tsv")
    roles = read_tsv(NORMALIZED / "control_roles.tsv")
    occurrences = read_tsv(NORMALIZED / "control_sequence_occurrences.tsv")
    pcr_bearers = {
        row["bearer_material_id"]
        for row in roles
        if row["role_type"] == "pcr_blank"
    }
    assert len(pcr_bearers) == 4
    represented_labels = {
        row["alias"] for row in aliases if row["entity_id"] in pcr_bearers
    }
    assert {
        "e0555_PCR_Ctrl_Trip1",
        "e0875_NTC_2",
        "e8667_PCRCtrl",
        "PCR Blank",
    } <= represented_labels
    sequenced = {row["facility_run_id"] for row in occurrences}
    assert {
        "IBEX:e0555_PCR_Ctrl_Trip1",
        "IBEX:e0875_NTC_2",
        "IBEX:e8667_PCRCtrl",
    } <= sequenced
    readme = (SOURCE_CONTROLS / "README.md").read_text(encoding="utf-8")
    assert "complete" in readme.lower()
    assert "awaits laboratory" in readme
    assert "confirmation" in readme


def test_ambiguous_e0323_library_is_not_promoted_to_positive_ground_truth():
    aliases = read_tsv(NORMALIZED / "control_aliases.tsv")
    roles = read_tsv(NORMALIZED / "control_roles.tsv")
    assertions = read_tsv(NORMALIZED / "control_assertions.tsv")
    entities = {
        row["entity_id"]
        for row in aliases
        if row["alias"] == "e0323_Ctrl_1_Trip1"
    }
    assert len(entities) == 1
    entity = next(iter(entities))
    assert all(
        row["role_type"] != "positive_microbiome_control"
        for row in roles
        if row["bearer_material_id"] == entity
    )
    assert all(
        not (
            row["subject_iri"] == entity
            and row["status"] == "confirmed"
            and row["predicate_iri"].endswith("SIO_000244")
        )
        for row in assertions
    )


def test_assay_aware_filter_and_positive_recovery_are_frozen():
    summary = json.loads((ANALYSIS / "summary.json").read_text(encoding="utf-8"))
    assert summary["positive_control_profiles"] == 7
    assert summary["positive_controls_in_training"] == 0
    assert summary["training_extraction_blanks"] == [
        f"EB{number}" for number in range(1, 18)
    ]
    assert summary["primary_candidate_contaminant_features"] == 351
    assert summary["mapped_biological_profiles_in_canonical_table"] == 217

    recovery = read_tsv(ANALYSIS / "positive_control_expected_taxon_recovery.tsv")
    assert len(recovery) == 62
    assert {
        row["product_assignment_status"] for row in recovery
    } == {"provisional_from_positive_label_and_trip_design"}
    assert {
        row["profile_id"] for row in recovery
    } == {
        "e0553_Ctrl_2",
        "e0554_Ctrl_3",
        "e0872_TMC1",
        "e0874_Positive",
        "e8294_FPosCtrl1",
        "e8661_FPosCtrl2",
        "e8665_FPosCtrl3",
    }
    profiles = read_tsv(ANALYSIS / "positive_control_profiles.tsv")
    assert {
        row["product_assignment_status"] for row in profiles
    } == {"provisional_from_positive_label_and_trip_design"}
    assert {
        row["profile_id"]
        for row in profiles
        if row["profile_interpretation"].startswith("mock_dominated_")
    } == {"e8661_FPosCtrl2", "e8665_FPosCtrl3"}


def test_bounded_ecology_sensitivity_inputs_match_the_control_calls():
    summary = json.loads(
        (ANALYSIS / "sensitivity_inputs/summary.json").read_text(encoding="utf-8")
    )
    assert summary["candidate_features"] == 351
    assert summary["mapped_profiles"] == 217
    assert summary["profiles_below_rarefaction_depth_after_filter"] == 0
    assert summary["removed_read_fraction"]["median"] < 0.01
    assert summary["removed_read_fraction"]["maximum"] > 0.5
    assert summary["shannon"]["spearman_before_after"] > 0.99
    for relative, digest in summary["output_sha256"].items():
        assert sha256(resolve_summary_output(relative)) == digest


def test_removal_is_reported_by_profile_campaign_compartment_and_batch():
    summary = json.loads((ANALYSIS / "summary.json").read_text(encoding="utf-8"))
    assert summary["removal_summary_dimensions"] == [
        "profile",
        "campaign",
        "compartment",
        "extraction_batch",
    ]

    campaigns = read_tsv(ANALYSIS / "trip5_removal_fraction_by_campaign.tsv")
    assert len(campaigns) == 1
    assert campaigns[0]["group_type"] == "campaign"
    assert campaigns[0]["group_value"] == "5"
    assert int(campaigns[0]["biological_profile_count"]) == 217
    assert abs(
        float(campaigns[0]["pooled_candidate_contaminant_read_fraction"])
        - 0.02186632
    ) < 1e-8

    compartments = {
        row["group_value"]: row
        for row in read_tsv(
            ANALYSIS / "trip5_removal_fraction_by_compartment.tsv"
        )
    }
    assert {
        key: int(row["biological_profile_count"])
        for key, row in compartments.items()
    } == {"Deep": 55, "Rhizosphere": 133, "Surface": 29}

    batches = read_tsv(ANALYSIS / "trip5_extraction_batch_summary.tsv")
    assert len(batches) == 17
    profiles = read_tsv(ANALYSIS / "trip5_removal_fraction_by_profile.tsv")
    assert sum(
        row["role"] == "compatible_biological_profile" for row in profiles
    ) == 217


def test_historical_revision_products_remain_checksum_verifiable():
    if not REVISION.is_dir():
        pytest.skip("development-only historical revision evidence is not packaged")
    for line in (REVISION / "SHA256SUMS").read_text().splitlines():
        digest, name = line.split("  ", 1)
        assert sha256(REVISION / name) == digest
