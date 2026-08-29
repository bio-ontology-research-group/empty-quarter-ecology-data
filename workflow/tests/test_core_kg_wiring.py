from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = (ROOT / "workflow/main.nf").read_text(encoding="utf-8")
RUNNER = (
    ROOT / "workflow/bin/run_core_kg_generation.sh"
).read_text(encoding="utf-8")
KG_VALIDATOR = (
    ROOT / "workflow/bin/run_kg_validation.sh"
).read_text(encoding="utf-8")
ENVIRONMENT = (
    ROOT / "workflow/environment.yml"
).read_text(encoding="utf-8")
RAPTOR_BOOTSTRAP = (
    ROOT / "workflow/bin/bootstrap_raptor.sh"
).read_text(encoding="utf-8")


def test_core_modules_are_generated_before_release_and_query() -> None:
    assert "process GENERATE_CORE_KG_MODULES" in WORKFLOW
    assert (
        "RELEASE_EVIDENCE(\n"
        "        project_root_ch,\n"
        "        ENVIRONMENTAL_METADATA.out,\n"
        "        GENERATE_CORE_KG_MODULES.out"
    ) in WORKFLOW
    assert (
        "COMPETENCY_QUERY_VALIDATION(\n"
        "        project_root_ch,\n"
        "        GENERATE_CORE_KG_MODULES.out"
    ) in WORKFLOW


def test_taxonomy_and_validation_consume_generated_core_bundle() -> None:
    assert (
        "'${core_kg_modules}/rubalkhali_sra.owl'"
        in WORKFLOW
    )
    assert (
        "KG_VALIDATE(\n"
        "            project_root_ch,\n"
        "            GENERATE_CORE_KG_MODULES.out"
    ) in WORKFLOW
    assert "core_kg_bundle" in KG_VALIDATOR
    assert "core_kg_manifest.json" in KG_VALIDATOR


def test_runner_regenerates_every_tractable_abox_in_dependency_order() -> None:
    expected = [
        "generate_site_ontology.groovy",
        "generate_measurements_abox.groovy",
        "generate_samples_abox.groovy",
        "generate_xrf_abox.groovy",
        "generate_dna_abox.groovy",
        "generate_sra_abox.groovy",
        "generate_qc_abox.groovy",
        "generate_controls_abox.py",
        "generate_ph_dataset.py",
    ]
    offsets = [RUNNER.index(name) for name in expected]
    assert offsets == sorted(offsets)
    assert 'cmp "$generated" "$canonical"' in RUNNER


def test_curated_ontology_declarations_are_machine_audited() -> None:
    assert "ontology_declaration_audit.json" in RUNNER
    assert '"total": 333' in RUNNER
    assert '"project_local": 297' in RUNNER
    assert '"total": 20' in RUNNER
    assert '"total": 35' in RUNNER
    assert "ontology_declaration_audit.json" in KG_VALIDATOR


def test_fail_closed_turtle_parser_is_pinned_and_checked_early() -> None:
    assert "raptor2=2.0.16" not in ENVIRONMENT
    assert "raptor2-2.0.16.tar.gz" in RAPTOR_BOOTSTRAP
    assert (
        "089db78d7ac982354bdbf39d973baf09581e6904ac4c92a98c5caadb3de44680"
        in RAPTOR_BOOTSTRAP
    )
    assert "--enable-parsers=turtle" in RAPTOR_BOOTSTRAP
    assert "command -v rapper" in KG_VALIDATOR
    assert 'rapper_version=$(rapper -v 2>&1 | head -1)' in KG_VALIDATOR
    assert '"$rapper_version" != "2.0.16"' in KG_VALIDATOR


def test_manuscript_semantics_gates_run_against_generated_modules() -> None:
    assert "validate_site_biome_completeness.py" in KG_VALIDATOR
    assert "--module data/processed/semantics/ontology/rubalkhali_sites.owl" in KG_VALIDATOR
    assert "verify_manuscript_listings.py" in KG_VALIDATOR
    assert "--ontology-dir data/processed/semantics/ontology" in KG_VALIDATOR
    assert "site_biome_completeness.json" in KG_VALIDATOR
    assert "manuscript_listing_verification.json" in KG_VALIDATOR
    assert "rubalkhali_controls.ttl" in KG_VALIDATOR
    assert "rubalkhali_ph_eq_ph_shared_v1_0_0.ttl" in KG_VALIDATOR
    assert "validate_controls.py" in KG_VALIDATOR
