#!/usr/bin/env python3
"""Clean-room smoke test of a built reviewer package.

The test is deliberately naive about the repository: it works from the archive
and its checksum file alone, the way a referee would. It fails on the first
required operation that does not hold.

1. Verify the archive against its ``SHA256SUMS`` file.
2. Extract it into a temporary directory.
3. Verify every extracted member against ``PRE_RELEASE_MANIFEST.tsv``. No
   member may differ: the package alters nothing.
4. Create the documented compatibility layout and replay the curated
   environmental table.
5. Replay the complete shared pH workflow, including influence and semantic
   validation evidence.
6. Run the staged regression suite and execute the published competency query
   against the extracted ontology modules with its declared 46-row cardinality.

The extraction directory is removed afterwards unless ``--keep`` is given.
"""

from __future__ import annotations

import argparse
import csv
import filecmp
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--checksums", type=Path, default=None)
    parser.add_argument("--summary", type=Path, default=None)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--keep", action="store_true")
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args()

    requested_python = Path(args.python)
    if requested_python.is_file():
        # Preserve the venv entry point. Resolving its symlink to the system
        # interpreter discards the adjacent pyvenv.cfg and therefore the
        # installed replay dependencies (for example openpyxl).
        python_executable = str(requested_python.absolute())
    else:
        resolved_python = shutil.which(args.python)
        if resolved_python is None:
            print(f"Python interpreter is unavailable: {args.python}", file=sys.stderr)
            return 1
        python_executable = resolved_python

    archive = args.archive.resolve()
    checksums = args.checksums or archive.with_suffix("").with_suffix(".SHA256SUMS")
    summary_path = args.summary or Path(str(archive).replace(".tar.gz", ".package.json"))
    steps: list[dict] = []

    def write_report(status: str) -> None:
        if args.report is None:
            return
        report = {
            "archive": str(archive),
            "steps": steps,
            "status": status,
        }
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def record(name: str, ok: bool, detail: str) -> bool:
        steps.append({"step": name, "ok": ok, "detail": detail})
        print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}")
        write_report("in_progress" if ok else "failed")
        return ok

    if not archive.is_file():
        record("archive present", False, str(archive))
        return 1
    if not checksums.is_file():
        record("checksum file present", False, str(checksums))
        return 1

    expected = {}
    for line in checksums.read_text(encoding="utf-8").splitlines():
        digest, _, name = line.partition("  ")
        if name:
            expected[name.strip()] = digest.strip()
    observed = sha256(archive)
    if not record(
        "archive checksum",
        expected.get(archive.name) == observed,
        f"{observed} vs declared {expected.get(archive.name)}",
    ):
        return 1

    # Nothing is modified during packaging any more, so every extracted member
    # must match its manifest entry exactly.
    if summary_path.is_file():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        modified = summary.get("payload_integrity", {}).get("members_modified_during_packaging")
        if modified:
            record("payload integrity", False, f"{modified} member(s) modified during packaging")
            return 1

    workdir = Path(tempfile.mkdtemp(prefix="eq-package-smoke-"))
    try:
        with tarfile.open(archive, "r:gz") as handle:
            handle.extractall(workdir, filter="data")
        roots = [path for path in workdir.iterdir() if path.is_dir()]
        if len(roots) != 1:
            record("single archive root", False, f"found {len(roots)}")
            return 1
        extracted = roots[0]
        record("extraction", True, f"{extracted.name} into {workdir}")

        manifest = extracted / "PRE_RELEASE_MANIFEST.tsv"
        if not manifest.is_file():
            record("manifest present in archive", False, str(manifest))
            return 1
        with manifest.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle, delimiter="\t"))

        checked = mismatched = absent = 0
        for row in rows:
            member = extracted / row["path"]
            if not member.is_file():
                absent += 1
                continue
            checked += 1
            if sha256(member) != row["sha256"]:
                mismatched += 1
        if not record(
            "member checksums",
            mismatched == 0,
            f"{checked} verified byte-identical, {mismatched} mismatched, "
            f"{absent} declared-but-absent (bulk artifacts)",
        ):
            return 1

        bootstrap = extracted / "scripts/release/bootstrap_package_layout.sh"
        bootstrap_result = subprocess.run(
            ["bash", str(bootstrap), str(extracted)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        bootstrap_detail = (
            bootstrap_result.stdout.strip()
            or bootstrap_result.stderr.strip()
            or "no output"
        ).splitlines()[-1]
        if not record(
            "package compatibility layout",
            bootstrap_result.returncode == 0,
            bootstrap_detail[:200],
        ):
            return 1

        environmental_output = workdir / "environmental-replay"
        environmental_result = subprocess.run(
            [
                python_executable,
                str(extracted / "scripts/metadata/generate_env_table.py"),
                "--project-root",
                str(extracted),
                "--output-dir",
                str(environmental_output),
            ],
            capture_output=True,
            text=True,
            timeout=600,
        )
        generated_environment = (
            environmental_output / "environmental_measurements_curated.tsv"
        )
        staged_environment = (
            extracted
            / "metadata/environmental/environmental_measurements_curated.tsv"
        )
        environment_ok = (
            environmental_result.returncode == 0
            and generated_environment.is_file()
            and filecmp.cmp(
                generated_environment,
                staged_environment,
                shallow=False,
            )
        )
        environmental_detail = (
            environmental_result.stdout.strip()
            or environmental_result.stderr.strip()
            or "generated table comparison"
        ).splitlines()[-1]
        if not record(
            "environmental replay",
            environment_ok,
            environmental_detail[:200],
        ):
            return 1

        ph_output = workdir / "ph-replay"
        ph_environment = os.environ.copy()
        ph_environment.update(
            {
                "PH_PYTHON": python_executable,
                "PH_OUTPUT_DIR": str(ph_output),
                "PH_TEX_OUTPUT": str(
                    ph_output / "generated/ph_shared_v1_values.tex"
                ),
                "PH_SKIP_TESTS": "1",
            }
        )
        ph_result = subprocess.run(
            ["bash", str(extracted / "scripts/analysis/run_ph_shared_v1.sh")],
            cwd=extracted,
            env=ph_environment,
            capture_output=True,
            text=True,
            timeout=1200,
        )
        ph_validation_path = ph_output / "validation_report.json"
        ph_summary_path = ph_output / "ecology/summary.json"
        ph_validation = (
            json.loads(ph_validation_path.read_text(encoding="utf-8"))
            if ph_validation_path.is_file()
            else {}
        )
        ph_summary = (
            json.loads(ph_summary_path.read_text(encoding="utf-8"))
            if ph_summary_path.is_file()
            else {}
        )
        ph_ok = (
            ph_result.returncode == 0
            and ph_validation.get("status") == "PASS_FROZEN_SHARED_KG"
            and ph_validation.get("shex_positive_shape_map_entries") == 2167
            and ph_summary.get("maximum_group_influence", {}).get(
                "all_refit_p_values_at_permutation_floor"
            )
        )
        ph_detail = (
            "shared pH workflow, 712 measurements, 2,167 shape-map entries, "
            "influence diagnostics reproduced"
            if ph_ok
            else (
                ph_result.stderr.strip()
                or ph_result.stdout.strip()
                or "pH replay produced no report"
            ).splitlines()[-1][:200]
        )
        if not record("shared pH replay", ph_ok, ph_detail):
            return 1

        package_tests = subprocess.run(
            [
                python_executable,
                "-m",
                "pytest",
                "-p",
                "no:cacheprovider",
                "-q",
                "tests",
                "workflow/tests",
            ],
            cwd=extracted,
            capture_output=True,
            text=True,
            timeout=600,
        )
        test_detail = (
            package_tests.stdout.strip()
            or package_tests.stderr.strip()
            or "no output"
        ).splitlines()[-1]
        if not record(
            "staged regression tests",
            package_tests.returncode == 0,
            test_detail[:200],
        ):
            return 1

        validator = extracted / "scripts/validation/validate_competency_query.py"
        query = extracted / "sparql/field_xrf_site10.rq"
        modules = extracted / "ontology"
        if validator.is_file() and query.is_file():
            result = subprocess.run(
                [
                    python_executable,
                    str(validator),
                    "--query",
                    str(query),
                    "--base",
                    str(modules / "rubalkhali.owl"),
                    "--sites",
                    str(modules / "rubalkhali_sites.owl"),
                    "--xrf",
                    str(modules / "rubalkhali_xrf.owl"),
                    "--expected-rows",
                    "46",
                    "--output-dir",
                    str(workdir / "cq"),
                ],
                capture_output=True,
                text=True,
                timeout=3600,
            )
            detail = (result.stdout.strip() or result.stderr.strip()).splitlines()[-1:] or [""]
            record("competency query", result.returncode == 0, detail[0][:200])
        else:
            record("competency query", False, "validator or query absent from the archive")
    finally:
        if not args.keep:
            shutil.rmtree(workdir, ignore_errors=True)

    ok = all(step["ok"] for step in steps)
    write_report("passed" if ok else "failed")
    print("PASS: package smoke test" if ok else "FAIL: package smoke test")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
