#!/usr/bin/env python3
"""Rebuild the four companion-analysis input bundles staged for release.

The bundles are large derived inputs consumed by the advanced ecology stage of
``workflow/main.nf`` (``--coverm_dir``, ``--eggnog_annotations``,
``--measured_function_inputs``, ``--pma_asv_table``).  They are rebuilt here
from named, checked sources so the staged release is reconstructible instead of
depending on files that happen to survive in a scratch directory.

Every source is declared explicitly and the script fails closed: a missing
source, an unreadable source, or a content hash that disagrees with the
authoritative workflow run aborts the build without writing a partial bundle.

Archives are written deterministically (sorted member order, zeroed member
metadata, gzip header without a timestamp) so a rebuild from identical sources
yields identical bytes.

Usage::

    python3 data-paper/scripts/build_companion_release_inputs.py \
        --project-root /home/leechuck/Public/software/empty-quarter

``--verify-only`` recomputes and reports digests without rewriting anything.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib

import os
import shutil
import sys
import tarfile
from pathlib import Path

CHUNK = 8 * 1024 * 1024

# Authoritative workflow run whose recorded per-file digests are used to verify
# the rebuilt CoverM bundle contents.
AUTHORITATIVE_RUN = Path("results/reproducibility-v051-20260724-ws")
FUNCTIONAL_INPUT_MANIFEST = (
    AUTHORITATIVE_RUN / "06_functional_redundancy/functional_redundancy/input_manifest.tsv"
)
MEASURED_INPUT_MANIFEST = (
    AUTHORITATIVE_RUN
    / "04_ecology_advanced/ecology_advanced/measured_function_summary/input_manifest.tsv"
)

# Six member files of measured_function_inputs.tar.gz, in the repository-relative
# layout that workflow/bin/run_ecology_advanced.sh extracts and requires.
MEASURED_FUNCTION_MEMBERS = (
    "analysis/v2/review/measured_function/measured_ko_by_sample.tsv.gz",
    "analysis/v2/review/measured_function/measured_marker_by_sample.tsv",
    "analysis/v2/review/measured_function/genome_cfix_taxonomy.tsv",
    "analysis/v2/review/measured_function/filtered_genomes.tsv",
    "data/processed/functional/picrust2/merged/ko_metagenome_unstrat.tsv",
    "data/processed/functional/picrust2/merged/sample_metadata.tsv",
)

COVERM_SOURCE = Path.home() / ".cache/empty-quarter-inputs/eq_regen/coverm"
EGGNOG_SOURCE = Path.home() / ".cache/empty-quarter-inputs/eq_regen/eggnog/eq.emapper.annotations"
PMA_SOURCE = Path("relic-dna/ASV_table.tsv")

STAGE_COVERM = "metadata/metagenome/coverm_profiles.tar.gz"
STAGE_EGGNOG = "metadata/metagenome/eq.emapper.annotations.gz"
STAGE_MEASURED = "metadata/metagenome/measured_function_inputs.tar.gz"
STAGE_PMA = "metadata/relic-dna/PMA_ASV_table.tsv"
STAGE_SUMS = "evidence/companion-analysis/derived_input_archives.SHA256SUMS"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def fail(message: str) -> "None":
    raise SystemExit(f"FAIL: {message}")


def recorded_coverm_digests(project_root: Path) -> dict[str, str]:
    """Per-profile digests recorded by the authoritative functional-null run."""
    manifest = project_root / FUNCTIONAL_INPUT_MANIFEST
    if not manifest.is_file():
        fail(f"authoritative input manifest is absent: {manifest}")
    digests: dict[str, str] = {}
    with manifest.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            if row["role"] != "genome_relative_abundance":
                continue
            digests[Path(row["path"]).name] = row["sha256"]
    if not digests:
        fail(f"no genome_relative_abundance rows in {manifest}")
    return digests


def deterministic_tar_gz(members: list[tuple[str, Path]], destination: Path) -> None:
    """Write ``members`` as [(arcname, source)] into a byte-stable tar.gz."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    with temporary.open("wb") as sink:
        with gzip.GzipFile(fileobj=sink, mode="wb", compresslevel=9, mtime=0) as gz:
            with tarfile.open(fileobj=gz, mode="w|", format=tarfile.GNU_FORMAT) as archive:
                for arcname, source in sorted(members, key=lambda item: item[0]):
                    info = tarfile.TarInfo(arcname)
                    info.size = source.stat().st_size
                    info.mtime = 0
                    info.mode = 0o644
                    info.uid = 0
                    info.gid = 0
                    info.uname = ""
                    info.gname = ""
                    info.type = tarfile.REGTYPE
                    with source.open("rb") as handle:
                        archive.addfile(info, handle)
    temporary.replace(destination)


def build_coverm(project_root: Path, stage: Path, verify_only: bool) -> Path:
    destination = stage / STAGE_COVERM
    if not COVERM_SOURCE.is_dir():
        fail(f"CoverM profile directory is absent: {COVERM_SOURCE}")
    profiles = sorted(p for p in COVERM_SOURCE.iterdir() if p.is_file())
    if not profiles:
        fail(f"CoverM profile directory is empty: {COVERM_SOURCE}")

    recorded = recorded_coverm_digests(project_root)
    observed = {p.name: sha256(p) for p in profiles}
    if set(observed) != set(recorded):
        only_source = sorted(set(observed) - set(recorded))
        only_recorded = sorted(set(recorded) - set(observed))
        fail(
            "CoverM profile set differs from the authoritative run "
            f"(source-only={only_source[:5]}, run-only={only_recorded[:5]})"
        )
    mismatched = [name for name, digest in observed.items() if digest != recorded[name]]
    if mismatched:
        fail(f"CoverM profile digests differ from the authoritative run: {sorted(mismatched)[:5]}")

    if not verify_only:
        deterministic_tar_gz(
            [(f"coverm/{p.name}", p) for p in profiles],
            destination,
        )
    print(f"  coverm: {len(profiles)} profiles verified against {FUNCTIONAL_INPUT_MANIFEST}")
    return destination


def build_eggnog(stage: Path, verify_only: bool) -> Path:
    destination = stage / STAGE_EGGNOG
    if not EGGNOG_SOURCE.is_file():
        fail(f"eggNOG annotation table is absent: {EGGNOG_SOURCE}")
    if not verify_only:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        with EGGNOG_SOURCE.open("rb") as source, temporary.open("wb") as sink:
            with gzip.GzipFile(fileobj=sink, mode="wb", compresslevel=9, mtime=0) as gz:
                shutil.copyfileobj(source, gz, CHUNK)
        temporary.replace(destination)
    print(f"  eggnog: compressed from {EGGNOG_SOURCE}")
    return destination


def recorded_measured_digests(project_root: Path) -> dict[str, str]:
    """Per-member digests recorded by the authoritative measured-function run."""
    manifest = project_root / MEASURED_INPUT_MANIFEST
    if not manifest.is_file():
        fail(f"authoritative measured-function manifest is absent: {manifest}")
    with manifest.open(newline="", encoding="utf-8") as handle:
        digests = {row["path"]: row["sha256"] for row in csv.DictReader(handle, delimiter="\t")}
    if not digests:
        fail(f"no rows in {manifest}")
    return digests


def build_measured_function(project_root: Path, stage: Path, verify_only: bool) -> Path:
    destination = stage / STAGE_MEASURED
    recorded = recorded_measured_digests(project_root)
    members = []
    for relative in MEASURED_FUNCTION_MEMBERS:
        source = project_root / relative
        if not source.is_file():
            fail(f"measured-function input is absent: {source}")
        if relative not in recorded:
            fail(f"measured-function input is not in the authoritative manifest: {relative}")
        observed = sha256(source)
        if observed != recorded[relative]:
            fail(
                f"measured-function input differs from the authoritative run: {relative} "
                f"(observed {observed}, recorded {recorded[relative]})"
            )
        members.append((relative, source))
    if not verify_only:
        deterministic_tar_gz(members, destination)
    print(f"  measured-function: {len(members)} members")
    return destination


def build_pma(project_root: Path, stage: Path, verify_only: bool) -> Path:
    destination = stage / STAGE_PMA
    source = project_root / PMA_SOURCE
    if not source.is_file():
        fail(f"PMA ASV table is absent: {source}")
    if not verify_only:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    print(f"  pma: copied from {PMA_SOURCE}")
    return destination


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
    )
    parser.add_argument(
        "--stage",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "zenodo",
    )
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument(
        "--skip-eggnog",
        action="store_true",
        help="skip the 1.4 GB eggNOG recompression when it is already staged",
    )
    args = parser.parse_args()

    project_root = args.project_root.resolve()
    stage = args.stage.resolve()
    if not stage.is_dir():
        fail(f"release staging tree is absent: {stage}")

    print(f"Rebuilding companion inputs into {stage}")
    built = [
        build_coverm(project_root, stage, args.verify_only),
        build_measured_function(project_root, stage, args.verify_only),
        build_pma(project_root, stage, args.verify_only),
    ]
    eggnog = stage / STAGE_EGGNOG
    if args.skip_eggnog:
        if not eggnog.is_file():
            fail(f"--skip-eggnog given but {STAGE_EGGNOG} is not staged")
        print("  eggnog: reusing staged archive (--skip-eggnog)")
        built.append(eggnog)
    else:
        built.append(build_eggnog(stage, args.verify_only))

    sums_path = stage / STAGE_SUMS
    lines = []
    for path in sorted(built, key=lambda p: str(p.relative_to(stage))):
        if not path.is_file():
            fail(f"expected bundle was not produced: {path}")
        lines.append(f"{sha256(path)}  {path.relative_to(stage)}\n")
    if not args.verify_only:
        sums_path.parent.mkdir(parents=True, exist_ok=True)
        sums_path.write_text("".join(lines), encoding="utf-8")

    for line in lines:
        print("  " + line.rstrip())
    print(f"PASS: {len(built)} companion bundles present under {stage}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
