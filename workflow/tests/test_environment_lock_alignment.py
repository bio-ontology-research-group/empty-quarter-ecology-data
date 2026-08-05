from pathlib import Path
import re

import yaml


ROOT = Path(__file__).resolve().parents[2]
CAPTURE = (
    ROOT / "workflow/bin/capture_execution_environment.sh"
).read_text(encoding="utf-8")


def test_direct_python_versions_match_between_recipe_and_lock_input() -> None:
    dependencies = yaml.safe_load(
        (ROOT / "workflow/environment.yml").read_text(encoding="utf-8")
    )["dependencies"]
    conda = {}
    for entry in dependencies:
        if not isinstance(entry, str) or "=" not in entry:
            continue
        name, version = entry.split("=", 1)
        conda[name.lower().replace("_", "-")] = version

    requested = {}
    for line in (
        ROOT / "workflow/requirements.in"
    ).read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==(.+)", line.strip())
        if match:
            requested[
                match.group(1).lower().replace("_", "-")
            ] = match.group(2)

    # `graphviz` is the native executable in Conda and the Python binding in
    # requirements.in; `python-graphviz` below pins that binding in Conda.
    overlap = (set(conda) & set(requested)) - {"graphviz"}
    assert overlap
    assert {
        name: (conda[name], requested[name])
        for name in overlap
        if conda[name] != requested[name]
    } == {}
    assert "python-graphviz=0.20.3" in dependencies


def test_phylogeny_tool_versions_are_captured_in_the_executed_environment() -> None:
    assert "mafft FastTree" in CAPTURE
    assert 'mafft)' in CAPTURE
    assert 'FastTree)' in CAPTURE


def test_python_package_capture_does_not_require_pip() -> None:
    assert "from importlib.metadata import distributions" in CAPTURE
    assert "python_package_inventory_method=importlib-metadata" in CAPTURE
    assert "could not enumerate installed Python distributions" in CAPTURE
    assert 'print(f"freetype\\t{ft2font.__freetype_version__}")' in CAPTURE
    assert '"figure_runtime.tsv"' in CAPTURE


def test_explicit_linux_lock_pins_the_figure_runtime() -> None:
    lock = (ROOT / "environment/conda-linux-64.lock").read_text(
        encoding="utf-8"
    )
    assert "\n@EXPLICIT\n" in lock
    assert "/python-3.11.14-" in lock
    assert "/matplotlib-3.9.4-" in lock
    assert "/freetype-2.14.3-" in lock
    package_urls = [
        line for line in lock.splitlines() if line.startswith("https://")
    ]
    assert len(package_urls) > 200
    assert all("#" in line for line in package_urls)


def test_pip_overlay_is_hash_locked_and_does_not_replace_conda_dependencies() -> None:
    overlay = (ROOT / "environment/pip-overlay.lock.txt").read_text(
        encoding="utf-8"
    )
    assert "pingouin==0.5.5" in overlay
    assert "pandas-flavor==0.8.1" in overlay
    assert overlay.count("--hash=sha256:") == 4
    assert "--no-deps --require-hashes" in (
        ROOT / "Makefile"
    ).read_text(encoding="utf-8")
    assert "conda_explicit_lock_sha256" in CAPTURE
    assert "pip_overlay_lock_sha256" in CAPTURE
