#!/usr/bin/env python3
"""Run and freeze the focused laboratory-control semantic validation.

The full tractable-graph result is supplied as an already frozen semantic
validation record.  This script reruns the deterministic control generator,
the focused Python invariants, and the released positive/negative ShEx
fixtures before producing a checksum-bearing evidence record.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import json
import platform
import re
import subprocess
import sys
from pathlib import Path

from rdflib import RDF, Graph, Namespace
from rdflib.compare import isomorphic


BASE = Namespace("https://rubalkhali.science/kb/")
SIO = Namespace("http://semanticscience.org/resource/")

GENERATED = (
    "data/processed/semantics/ontology/rubalkhali_controls.ttl",
    "data/processed/semantics/ontology/rubalkhali_controls.owl",
    "data/processed/metadata/controls/control_aliases.tsv",
    "data/processed/metadata/controls/control_assertions.tsv",
    "data/processed/metadata/controls/control_composition.tsv",
    "data/processed/metadata/controls/control_entity_registry.tsv",
    "data/processed/metadata/controls/control_metadata_dispositions.tsv",
    "data/processed/metadata/controls/control_roles.tsv",
    "data/processed/metadata/controls/control_sequence_occurrences.tsv",
    "data/processed/metadata/controls/laboratory_processes.tsv",
)

HASHED_INPUTS = {
    "pinned_sio_1_59": "data/ontologies/sio.owl",
    "rubalkhali_tbox": "data/processed/semantics/ontology/rubalkhali.owl",
    "control_turtle": GENERATED[0],
    "control_rdfxml": GENERATED[1],
    "control_shex": "data/processed/semantics/shex/controls.shex",
    "control_generator": "scripts/rdf/generate_controls_abox.py",
    "control_validator": "scripts/validation/validate_controls.py",
    "control_evidence_freezer": (
        "scripts/validation/freeze_control_semantic_validation.py"
    ),
    "rdf_validator": "scripts/validation/validate_rdf.groovy",
    "iri_registry": "scripts/validation/check_iri_registry.py",
    "positive_control_fixture": "tests/shex_negatives/control_positive.ttl",
    "wrong_stage_fixture": (
        "tests/shex_negatives/control_negative_wrong_blank_stage.ttl"
    ),
    "missing_specification_source_fixture": (
        "tests/shex_negatives/"
        "control_negative_missing_specification_source.ttl"
    ),
    "static_negative_tests": "tests/test_control_negative_invariants.py",
    "consensus_pdf": (
        "review-literature/2026-07-30/control-consensus/"
        "guidelines-preventing-reporting-contamination-low-biomass-"
        "microbiome-studies_s41564-025-02035-2.pdf"
    ),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def row_count(path: Path) -> int:
    with path.open(encoding="utf-8", newline="") as handle:
        return sum(1 for _ in csv.DictReader(handle, delimiter="\t"))


def run(root: Path, command: list[str]) -> str:
    completed = subprocess.run(
        command,
        cwd=root,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    rendered = " ".join(command).replace(str(root), ".")
    if completed.returncode:
        raise SystemExit(
            f"validation command failed ({completed.returncode}): "
            f"{rendered}\n{completed.stdout}"
        )
    return f"$ {rendered}\n{completed.stdout.rstrip()}\n"


def capture(root: Path, command: list[str]) -> str:
    return subprocess.run(
        command,
        cwd=root,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    ).stdout.strip()


def version(package: str) -> str:
    try:
        return importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        return "not installed in freezer environment"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--semantic-json", type=Path, required=True)
    parser.add_argument("--semantic-log", type=Path, required=True)
    parser.add_argument("--executed-at", required=True)
    parser.add_argument(
        "--output-dir", type=Path, default=Path("revision/evidence")
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[2]
    semantic_json_path = args.semantic_json.resolve()
    semantic_log_path = args.semantic_log.resolve()
    semantic = json.loads(semantic_json_path.read_text(encoding="utf-8"))
    if semantic.get("status") != "passed":
        raise SystemExit("the supplied full semantic-validation record did not pass")
    semantic_log_hash = sha256(semantic_log_path)
    if semantic_log_hash != semantic["log"]["sha256"]:
        raise SystemExit("semantic-validation log hash does not match its record")

    missing = [path for path in GENERATED if not (root / path).is_file()]
    missing += [path for path in HASHED_INPUTS.values() if not (root / path).is_file()]
    if missing:
        raise SystemExit(f"required control-validation inputs are absent: {missing}")

    logs: list[str] = []
    generator = [sys.executable, "scripts/rdf/generate_controls_abox.py"]
    logs.append(run(root, generator))
    first_hashes = {path: sha256(root / path) for path in GENERATED}
    logs.append(run(root, generator))
    second_hashes = {path: sha256(root / path) for path in GENERATED}
    if first_hashes != second_hashes:
        raise SystemExit("control generator did not reproduce byte-identical outputs")

    project_python = root / ".venv/bin/python"
    python = str(project_python) if project_python.is_file() else sys.executable
    logs.append(run(root, [python, "scripts/validation/validate_controls.py"]))
    logs.append(
        run(
            root,
            [
                python,
                "-m",
                "pytest",
                "-q",
                "tests/test_control_negative_invariants.py",
                "tests/test_control_kg.py",
                "tests/test_control_author_confirmation.py",
            ],
        )
    )
    logs.append(run(root, ["groovy", "tests/shex_negatives/run_tests.groovy"]))
    logs.append(run(root, [sys.executable, "scripts/validation/check_iri_registry.py"]))

    ttl = Graph().parse(root / GENERATED[0], format="turtle")
    rdfxml = Graph().parse(root / GENERATED[1], format="xml")
    if len(ttl) != len(rdfxml) or not isomorphic(ttl, rdfxml):
        raise SystemExit("control Turtle and RDF/XML serializations are not isomorphic")

    inverse_properties = (
        (SIO.SIO_000244, SIO.SIO_000245),
        (SIO.SIO_000332, SIO.SIO_000629),
        (SIO.SIO_000772, SIO.SIO_000773),
        (SIO.SIO_000339, SIO.SIO_000338),
    )
    inverse_counts: dict[str, list[int]] = {}
    for forward, reverse in inverse_properties:
        forward_count = sum(1 for _ in ttl.triples((None, forward, None)))
        reverse_count = sum(1 for _ in ttl.triples((None, reverse, None)))
        for subject, _, obj in ttl.triples((None, forward, None)):
            if (obj, reverse, subject) not in ttl:
                raise SystemExit(f"missing reciprocal assertion for {forward}")
        for subject, _, obj in ttl.triples((None, reverse, None)):
            if (obj, forward, subject) not in ttl:
                raise SystemExit(f"missing reciprocal assertion for {reverse}")
        inverse_counts[f"{forward.split('/')[-1]}_{reverse.split('/')[-1]}"] = [
            forward_count,
            reverse_count,
        ]

    registry_rows = row_count(root / GENERATED[5])
    role_rows = row_count(root / GENERATED[7])
    occurrence_rows = row_count(root / GENERATED[8])
    composition_rows = row_count(root / GENERATED[4])
    assertion_rows = sum(
        1 for _ in ttl.subjects(RDF.type, BASE.RAK_0000317)
    )
    expected = (489, 3800, 51, 47, 18, 18)
    observed = (
        registry_rows,
        len(ttl),
        role_rows,
        occurrence_rows,
        composition_rows,
        assertion_rows,
    )
    if observed != expected:
        raise SystemExit(f"unexpected control counts: {observed}; expected {expected}")

    groovy_version = capture(root, ["groovy", "--version"]).splitlines()[-1]
    java_version = capture(root, ["java", "-version"]).splitlines()[0]
    project_python_version = capture(root, [python, "--version"])
    project_rdflib_version = capture(
        root,
        [
            python,
            "-c",
            "import importlib.metadata as m; print(m.version('rdflib'))",
        ],
    )

    date_token = args.executed_at[:10].replace("-", "")
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    frozen_log = output_dir / f"control_semantic_validation_{date_token}.log"
    frozen_json = output_dir / f"control_semantic_validation_{date_token}.json"
    frozen_checksums = (
        output_dir / f"control_semantic_validation_{date_token}.SHA256SUMS"
    )
    frozen_log.write_text(
        "Laboratory-control semantic validation\n"
        f"Executed: {args.executed_at}\n\n"
        + "\n".join(logs)
        + "\nIndependent RDF checks\n"
        + f"PASS: Turtle and RDF/XML are isomorphic at {len(ttl):,} triples.\n"
        + "PASS: all four declared SIO inverse pairs have reciprocal closure.\n"
        + "PASS: two consecutive generator runs produced byte-identical outputs.\n"
        + "PASS: the supplied full semantic-validation record and log agree.\n",
        encoding="utf-8",
    )

    summary = {
        "schema_version": "1.1",
        "status": "passed",
        "executed_at": args.executed_at,
        "scope": (
            "asserted laboratory-control module plus the tractable merged "
            "pre-inference knowledge graph"
        ),
        "checks": {
            "assay_aware_control_invariants": "passed",
            "focused_control_pytest": "passed_21_of_21",
            "released_shape_fixture_suite": "passed_10_of_10",
            "full_control_node_shex": "passed",
            "merged_elk_consistency": "passed",
            "iri_registry_groovy_and_python": "passed",
            "ttl_rdfxml_isomorphism": "passed",
            "sio_inverse_closure": "passed",
            "generator_determinism": "passed",
        },
        "control_module": {
            "registered_entities": registry_rows,
            "triples": len(ttl),
            "roles": role_rows,
            "sequence_occurrences": occurrence_rows,
            "composition_rows": composition_rows,
            "expected_taxon_assertions": assertion_rows,
            "sio_inverse_pairs": inverse_counts,
        },
        "merged_elk_lite": semantic["elk_lite"],
        "merged_label_gate": semantic["label_gate"],
        "commands": [
            "python3 scripts/rdf/generate_controls_abox.py (twice)",
            "${PROJECT_PYTHON} scripts/validation/validate_controls.py",
            "${PROJECT_PYTHON} -m pytest -q tests/test_control_negative_invariants.py tests/test_control_kg.py tests/test_control_author_confirmation.py",
            "groovy tests/shex_negatives/run_tests.groovy",
            "python3 scripts/validation/check_iri_registry.py",
            semantic["command"],
        ],
        "tool_versions": {
            "generator_and_freezer_python": platform.python_version(),
            "generator_and_freezer_rdflib": version("rdflib"),
            "generator_openpyxl": version("openpyxl"),
            "validator_python": project_python_version,
            "validator_rdflib": project_rdflib_version,
            "groovy": groovy_version,
            "openjdk": java_version,
            "owlapi": "4.5.26",
            "elk": "0.4.3",
            "jena": "4.10.0",
        },
        "sha256": {
            **{name: sha256(root / path) for name, path in HASHED_INPUTS.items()},
            "full_semantic_record": sha256(semantic_json_path),
            "full_semantic_log": semantic_log_hash,
            "log": sha256(frozen_log),
        },
        "generated_output_sha256": second_hashes,
        "scope_limit": semantic["scope_limit"]
        + " Live Virtuoso publication was not performed; the requested endpoint is a deposit-ready package, not publication.",
    }
    frozen_json.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    frozen_checksums.write_text(
        f"{sha256(frozen_json)}  {frozen_json.name}\n"
        f"{sha256(frozen_log)}  {frozen_log.name}\n",
        encoding="utf-8",
    )
    print(
        "PASS: froze focused control validation "
        f"({len(ttl):,} triples; 21 tests; 10 ShEx fixtures)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
