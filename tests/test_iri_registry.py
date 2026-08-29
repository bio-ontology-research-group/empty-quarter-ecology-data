"""
Tests for the IRI registry / collision detector.

Two layers of defense ensure RAK IRIs are minted at exactly one site with one
canonical label:

1. Static check (this test): scan scripts/rdf Groovy and Python generators for
   declarations and uses,
   and assert no IRI is declared with two different labels, no IRI is used as
   both a class and a property, and no class/property IRI is referenced without
   being declared in a defineX call.

2. Runtime check: scripts/validation/validate_labels.groovy walks the generated
   ontology files and asserts every RAK_ subject has exactly one rdfs:label.

This test only covers (1); (2) lives in the validate_original.sh suite.
"""

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_SCRIPT = REPO_ROOT / "scripts" / "validation" / "check_iri_registry.py"


def test_iri_registry_has_no_violations():
    """Every RAK class/property must be declared exactly once with one label."""
    assert REGISTRY_SCRIPT.exists(), f"registry script missing: {REGISTRY_SCRIPT}"
    result = subprocess.run(
        [sys.executable, str(REGISTRY_SCRIPT)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        "IRI registry detected collisions:\n"
        f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )


def test_iri_registry_detects_injected_collision(tmp_path):
    """Sanity check: the detector must fail when a real collision is present."""
    fake = REPO_ROOT / "scripts" / "rdf" / "_zzz_test_iri_collision.groovy"
    try:
        fake.write_text(
            'defineClass("RAK_0000070", "duplicate-of-bioinformatic-workflow", "")\n'
        )
        result = subprocess.run(
            [sys.executable, str(REGISTRY_SCRIPT)],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0, (
            "Registry should have flagged the injected collision but did not:\n"
            f"{result.stdout}"
        )
        assert "label-conflict" in result.stdout
        assert "RAK_0000070" in result.stdout
    finally:
        fake.unlink(missing_ok=True)


def test_runtime_label_validator_excludes_retired_taxonomy_modules():
    """Standalone and workflow label gates must select the same module set."""
    source = (
        REPO_ROOT / "scripts/validation/validate_labels.groovy"
    ).read_text(encoding="utf-8")
    for retired in (
        "rubalkhali_taxonomy_rak.owl",
        "ncbitaxon_module.owl",
        "ncbitaxon_module.ttl",
        "rubalkhali_taxonomy_abox.owl",
        "rubalkhali_taxonomy_abox.ttl",
    ):
        assert f'"{retired}"' in source
    assert "sibling serialization already loaded" in source
    assert 'a.name.endsWith(".owl")' in source
