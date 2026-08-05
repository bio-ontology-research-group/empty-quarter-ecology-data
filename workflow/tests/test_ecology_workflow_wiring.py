from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RUNNER = (
    ROOT / "workflow/bin/run_ecology_core.sh"
).read_text(encoding="utf-8")
MANIFEST = (
    ROOT / "workflow/analysis_manifest.tsv"
).read_text(encoding="utf-8")
MAIN = (ROOT / "workflow/main.nf").read_text(encoding="utf-8")
RAIN_RUNNER = (
    ROOT / "workflow/bin/run_rain_pulse_suite.sh"
).read_text(encoding="utf-8")
CONFIG = (ROOT / "workflow/nextflow.config").read_text(encoding="utf-8")
SOURCE_STAGE = ROOT / "data-paper/zenodo"
STAGE = SOURCE_STAGE if SOURCE_STAGE.is_dir() else ROOT


CORE_ANALYSES = (
    "geographic_prediction",
    "spatial_resolution_sensitivity",
    "distance_decay_turnover",
    "evenness_decomposition",
)


def test_core_runner_removes_every_copied_cache_and_output() -> None:
    cleanup = RUNNER.split("rm -rf \\", 1)[1].split("\n\n", 1)[0]
    assert "analysis/v2/review/cache" in cleanup
    assert "analysis/v3/results" in cleanup
    for name in CORE_ANALYSES:
        assert f"analysis/v3/{name}" in cleanup


def test_core_runner_uses_packaged_analysis_sources() -> None:
    for name in ("common.py", "corrected.py", "build_cache.py", "build_tree.py"):
        assert f"scripts/analysis/{name}" in RUNNER
    assert '"$project_root"/scripts/analysis/*.py' in RUNNER
    assert 'cp -a "$project_root/evidence/ph/ecology"' in RUNNER


def test_missing_spatial_and_evenness_analyses_are_regenerated_and_published() -> None:
    build_offset = RUNNER.index("run_step build_cache")
    claim_offset = RUNNER.index("run_step claim_rescue")
    for name in CORE_ANALYSES:
        run_offset = RUNNER.index(f"run_step {name}")
        assert build_offset < run_offset < claim_offset
        assert f'"$OLDPWD/$output_dir/{name}"' in RUNNER
        assert f"analysis/v3/{name}" in MANIFEST


def test_asv_cache_and_tree_are_rebuilt_before_spatial_sensitivity() -> None:
    expected_order = (
        "run_step build_cache",
        "run_step build_asv_filter",
        "mafft --retree 2 --maxiterate 0",
        "FastTree -nt -gtr -quiet",
        "run_step midpoint_root",
        "run_step spatial_resolution_sensitivity",
    )
    offsets = [RUNNER.index(item) for item in expected_order]
    assert offsets == sorted(offsets)
    assert "analysis/v3/midpoint_root_tree.py" in RUNNER
    for name in (
        "asv_filt_counts.tsv",
        "asv_filt.fasta",
        "asv_filt_aln.fasta",
        "asv_filt_tree.nwk",
        "asv_filt_tree_rooted.nwk",
    ):
        assert name in RUNNER


def test_core_claim_ledger_cannot_import_copied_advanced_verdicts() -> None:
    claim_command = RUNNER.split("run_step claim_rescue", 1)[1].split(
        "\n\n", 1
    )[0]
    assert "--skip-downstream" in claim_command


def test_collection_order_inputs_are_declared_in_the_core_sandbox() -> None:
    assert (
        'ln -s "$project_root/data/metadata/samplesheets"'
        in RUNNER
    )
    assert '"$task_root/data/metadata/samplesheets"' in RUNNER


def test_control_analysis_is_a_declared_downstream_core_process() -> None:
    assert "process CONTROL_ANALYSIS" in MAIN
    assert "CONTROL_ANALYSIS(project_root_ch, ECOLOGY_CORE.out)" in MAIN
    assert "run_control_analysis.sh" in MAIN
    assert "Assay-aware control audit and contamination sensitivity" in MANIFEST


def test_environment_and_picrust_results_feed_the_submission_figures() -> None:
    assert "process ENVIRONMENT_ASSOCIATIONS" in MAIN
    assert "process PICRUST2_ECOLOGY" in MAIN
    assert "--alpha-table '${ecology_core}/cache/alpha.tsv'" in MAIN
    assert "--environment-dir '${environment_associations}'" in MAIN
    assert "--rain-dir '${rain_pulse}/rain_pulse_response'" in MAIN
    assert "--picrust-dir '${picrust2_ecology}'" in MAIN
    assert "--control-dir '${control_analysis}/control_audit'" in MAIN
    assert "--pma-dir '${ecology_core}/pma_endpoints'" in MAIN
    assert "Site-level climate and collection-weather associations" in MANIFEST
    assert "PICRUSt2 pathway ecology" in MANIFEST
    for figure in (
        "fig1_landscape.pdf",
        "fig3_function_controls.pdf",
    ):
        assert figure in MAIN


def test_rainfall_pulse_is_regenerated_before_figure_build() -> None:
    assert "process RAIN_PULSE_SUITE" in MAIN
    assert "run_rain_pulse_suite.sh" in MAIN
    assert "RAIN_PULSE_SUITE.out" in MAIN
    for source in (
        "rain_response_window.py",
        "rain_pulse_response.py",
        "run_rain_pulse_suite.py",
    ):
        assert source in RAIN_RUNNER
        assert f"analysis/v3/{source}" in MANIFEST
    assert "--permutations 19999" in RAIN_RUNNER
    assert "--bootstraps 9999" in RAIN_RUNNER
    assert "Short-term rainfall pulse and sensitivity suite" in MANIFEST


def test_pma_default_uses_the_staged_canonical_input() -> None:
    expected = (
        "data-paper/zenodo/metadata/relic-dna/PMA_ASV_table.tsv"
    )
    assert expected in MAIN
    assert expected in CONFIG
    assert "relic-dna/ASV_table.tsv" not in CONFIG.replace(expected, "")


def test_nonretired_manifest_implementations_have_package_paths() -> None:
    import csv

    with (ROOT / "workflow/analysis_manifest.tsv").open(
        newline="", encoding="utf-8"
    ) as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    assert "package_path" in rows[0]
    for row in rows:
        if row["status"] == "retired":
            assert row["package_path"] == "NOT_INCLUDED_RETIRED"
            continue
        for package_path in row["package_path"].split(";"):
            assert package_path
            if package_path.startswith(("EXTERNAL:", "BULK:")):
                continue
            assert (STAGE / package_path).is_file(), (
                row["analysis"], package_path
            )
