from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = (ROOT / "workflow/main.nf").read_text(encoding="utf-8")
BUILDER = (
    ROOT / "workflow/bin/build_papers.sh"
).read_text(encoding="utf-8")
SNAPSHOT = (
    ROOT / "workflow/bin/capture_source_snapshot.py"
).read_text(encoding="utf-8")
STAGER = (
    ROOT / "scripts/controls/stage_control_release.py"
).read_text(encoding="utf-8")


def test_transect_figure_is_generated_and_consumed() -> None:
    assert "process DATA_PAPER_FIGURES" in WORKFLOW
    assert "transect_altitude_figure.py" in WORKFLOW
    assert "DATA_PAPER_FIGURES(project_root_ch)" in WORKFLOW
    assert "DATA_PAPER_FIGURES.out" in WORKFLOW
    assert "data_paper_figures" in BUILDER
    assert (
        'cp "$data_paper_figures/transect_altitude.png"'
        in BUILDER
    )


def test_staged_transect_png_is_not_mislabelled_as_source() -> None:
    authoritative_block = SNAPSHOT.split(
        "DATA_PAPER_AUTHORITATIVE_FILES = (", 1
    )[1].split(")", 1)[0]
    assert "transect_altitude.png" not in authoritative_block


def test_knowledge_representation_supplement_is_staged_and_snapshotted() -> None:
    assert '"$project_root/data-paper/kr_supplement.tex"' in BUILDER
    authoritative_block = SNAPSHOT.split(
        "DATA_PAPER_AUTHORITATIVE_FILES = (", 1
    )[1].split(")", 1)[0]
    assert '"kr_supplement.tex"' in authoritative_block
    assert "08_declarations.tex" not in BUILDER
    assert "08_declarations.tex" not in authoritative_block


def test_current_ecology_figure_names_are_staged_and_built() -> None:
    current = (
        "fig1_landscape.pdf",
        "fig2_soil_position.pdf",
        "fig3_function_controls.pdf",
        "figS_campaign_rainfall.pdf",
    )
    for name in current:
        assert name in WORKFLOW
        assert name in BUILDER
    retired = (
        "fig2_compartment_campaign.pdf",
        "fig3_environment_spatial.pdf",
        "fig3_compartment_campaign.pdf",
        "fig1_study_design.pdf",
        "fig2_environment_spatial.pdf",
        "fig3_soil_position.pdf",
        "fig4_climate_associations.pdf",
        "fig4_network_function.pdf",
        "fig5_function_controls.pdf",
    )
    for name in retired:
        assert name not in WORKFLOW
        assert name not in BUILDER


def test_ecology_supplement_inputs_are_staged_and_snapshotted() -> None:
    required = (
        "ph_shared_v1.tex",
        "generated/ph_shared_v1_values.tex",
        "generated/ph_shared_v1_values.manifest.json",
    )
    authoritative_block = SNAPSHOT.split(
        "ECOLOGY_PAPER_AUTHORITATIVE_FILES = (", 1
    )[1].split(")", 1)[0]
    for name in required:
        assert name in BUILDER
        assert f'"{name}"' in authoritative_block


def test_data_supplement_runs_the_full_bibliography_build() -> None:
    assert 'build_tex "$task_root/data-paper" supplement' in BUILDER
    assert 'cp "$task_root/data-paper/supplement.blg"' in BUILDER
    assert 'data-paper-supplement.blg' in BUILDER
    assert (
        'pdflatex -interaction=nonstopmode -halt-on-error supplement.tex'
        not in BUILDER
    )


def test_release_staging_removes_transient_build_noise() -> None:
    assert "remove_staged_build_noise(stage)" in STAGER
    assert '"__pycache__"' in STAGER
    assert '".pytest_cache"' in STAGER


def test_data_supplement_listing_overflows_fail_the_build() -> None:
    assert "data_supplement_listing_overflows" in BUILDER
    assert "data_supplement_listing_overflow_count.txt" in BUILDER
    assert "data supplement contains" in BUILDER
