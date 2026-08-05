#!/usr/bin/env python3
"""Freeze a completed tractable semantic-validation run with exact hashes."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path


MODULES = (
    "ecosystem_module.owl",
    "rubalkhali.owl",
    "rubalkhali_controls.owl",
    "rubalkhali_dna.owl",
    "rubalkhali_kb.owl",
    "rubalkhali_measurements.owl",
    "rubalkhali_qc.owl",
    "rubalkhali_samples.owl",
    "rubalkhali_sites.owl",
    "rubalkhali_sra.owl",
    "rubalkhali_xrf.owl",
)

VALIDATORS = (
    "validate_original.sh",
    "validate_labels.groovy",
    "validate_consistency.groovy",
    "validate_rdf.groovy",
    "check_iri_registry.py",
    "validate_controls.py",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def extract_int(pattern: str, text: str) -> int:
    match = re.search(pattern, text)
    if match is None:
        raise SystemExit(f"validation log lacks required pattern: {pattern}")
    return int(match.group(1))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--executed-at", required=True)
    parser.add_argument("--wall-time-seconds", type=float, required=True)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("revision/evidence"),
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[2]
    source_log = args.log.resolve()
    text = source_log.read_text(encoding="utf-8")
    required_passes = (
        "✅ PASSED: XRF Integrity",
        "✅ PASSED: XRF Field/Laboratory Semantics",
        "✅ PASSED: Logical Consistency",
        "✅ PASSED: ShEx Validation",
        "✅ PASSED: Label Uniqueness",
        "✅ PASSED: IRI Registry",
        "✅ PASSED: Laboratory Controls",
        "ALL ORIGINAL DATA VALIDATIONS PASSED",
    )
    absent = [line for line in required_passes if line not in text]
    if absent:
        raise SystemExit(f"validation run is incomplete: {absent}")

    ontology_dir = root / "data/processed/semantics/ontology"
    missing_modules = [
        name for name in MODULES if not (ontology_dir / name).is_file()
    ]
    if missing_modules:
        raise SystemExit(f"semantic modules are absent: {missing_modules}")

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    date_token = args.executed_at[:10].replace("-", "")
    frozen_log = output_dir / f"semantic_validation_{date_token}.log"
    frozen_json = output_dir / f"semantic_validation_{date_token}.json"
    frozen_checksums = (
        output_dir / f"semantic_validation_{date_token}.SHA256SUMS"
    )
    shutil.copyfile(source_log, frozen_log)

    module_hashes = {
        f"ontology/{name}": sha256(ontology_dir / name)
        for name in MODULES
    }
    script_hashes = {
        f"scripts/validation/{name}": sha256(
            root / "scripts/validation" / name
        )
        for name in VALIDATORS
    }
    summary = {
        "schema_version": "1.1",
        "status": "passed",
        "executed_at": args.executed_at,
        "command": (
            "VALIDATE_LIVE=0 bash "
            "scripts/validation/validate_original.sh"
        ),
        "wall_time_seconds": args.wall_time_seconds,
        "checks": {
            "xrf_integrity": "passed",
            "field_laboratory_xrf_semantics": "passed",
            "elk_lite_consistency": "passed",
            "shex_tractable_modules": "passed",
            "label_uniqueness": "passed",
            "iri_registry": "passed",
            "laboratory_controls": "passed",
        },
        "elk_lite": {
            "axioms": extract_int(
                r"Total axioms loaded:\s*(\d+)", text
            ),
            "distinct_ontology_iris": extract_int(
                r"Distinct OntologyIRIs:\s*(\d+)", text
            ),
            "consistent": True,
            "class_hierarchy_precomputed": False,
        },
        "label_gate": {
            "files": extract_int(r"Loaded\s+(\d+)\s+files:", text),
            "triples": extract_int(
                r"Total triples in merged graph:\s*(\d+)", text
            ),
            "labelled_rak_subjects": extract_int(
                r"(\d+)\s+RAK_ subjects carry rdfs:label", text
            ),
            "multiple_distinct_label_violations": 0,
            "shex_nonconformant_subjects": 0,
        },
        "scope_limit": (
            "The multi-gigabyte taxonomy ABox is excluded from ELK, "
            "ShEx and label-uniqueness loading here; its full-file "
            "streaming and Raptor validations remain those of the "
            "checksum-identified workflow snapshot. The generated "
            "laboratory-control module is included in this run."
        ),
        "log": {
            "path": (
                "evidence/semantic-validation/"
                f"{frozen_log.name}"
            ),
            "sha256": sha256(frozen_log),
        },
        "module_sha256": module_hashes,
        "script_sha256": script_hashes,
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
        "PASS: froze semantic validation "
        f"({summary['elk_lite']['axioms']} axioms, "
        f"{summary['label_gate']['triples']} triples, "
        f"{summary['label_gate']['labelled_rak_subjects']} labels)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
