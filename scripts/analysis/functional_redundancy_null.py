#!/usr/bin/env python3
"""Test encoded-functional convergence against a resolution-matched null.

Genome relative-abundance profiles (coverM) are projected through the observed
genome-by-KO annotation matrix (eggNOG). The null randomly reassigns the intact
KO profiles among genomes. It therefore preserves the number and identity of
genomes, every genome's annotation richness, KO prevalence, feature resolution,
and the sample abundance matrix. An observed functional turnover below this
null supports convergence of *genome-resolved encoded functions*; it does not
measure transcription, activity, flux, or the unassembled/unmapped read tail.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import importlib.metadata
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import TextIO

import numpy as np
from scipy.spatial.distance import pdist


KO_RE = re.compile(r"K\d{5}")
SAMPLE_RE = re.compile(r"^(?:[TFSV])?\d+(?P<compartment>PR|P|D|S)r\d+")
COMPARTMENT = {
    "D": "Deep",
    "S": "Surface",
    "P": "Rhizosphere",
    "PR": "Rhizosphere",
}
SEED = 20260723


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def text_reader(path: Path) -> TextIO:
    return (
        gzip.open(path, "rt", encoding="utf-8", errors="replace")
        if path.suffix == ".gz"
        else path.open(encoding="utf-8", errors="replace")
    )


def normalise_genome(value: str) -> str:
    name = Path(str(value)).name
    for suffix in (".fasta.gz", ".fna.gz", ".fa.gz", ".fasta", ".fna", ".fa"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def sample_compartment(sample: str) -> str:
    match = SAMPLE_RE.match(sample)
    if not match:
        return "Unparsed"
    return COMPARTMENT[match.group("compartment")]


def parse_genome_kos(
    path: Path,
) -> dict[str, Counter[str]]:
    profiles: dict[str, Counter[str]] = defaultdict(Counter)
    with text_reader(path) as handle:
        for line in handle:
            if not line or line.startswith("#"):
                continue
            columns = line.rstrip("\n").split("\t")
            if len(columns) < 12:
                continue
            genome = columns[0].split("@@", 1)[0]
            for ko in set(KO_RE.findall(columns[11])):
                profiles[genome][ko] += 1
    return dict(profiles)


def match_genome(name: str, known: set[str]) -> str | None:
    name = normalise_genome(name)
    if name in known:
        return name
    if f"{name}sta" in known:
        return f"{name}sta"
    if name.endswith("sta") and name[:-3] in known:
        return name[:-3]
    return None


def load_abundance(
    directory: Path,
    genomes: list[str],
) -> tuple[np.ndarray, list[str], list[str], np.ndarray]:
    genome_index = {genome: index for index, genome in enumerate(genomes)}
    known = set(genomes)
    rows: list[np.ndarray] = []
    samples: list[str] = []
    compartments: list[str] = []
    mapped_fractions: list[float] = []
    for path in sorted(directory.glob("*.tsv")):
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.reader(handle, delimiter="\t")
            header = next(reader)
            value_index = next(
                index
                for index, value in enumerate(header)
                if "relative abundance" in value.lower()
            )
            row = np.zeros(len(genomes), dtype=np.float32)
            total = 0.0
            matched = 0.0
            for fields in reader:
                if len(fields) <= value_index:
                    continue
                try:
                    abundance = float(fields[value_index])
                except ValueError:
                    continue
                total += abundance
                if fields[0].lower() == "unmapped":
                    continue
                genome = match_genome(fields[0], known)
                if genome is None:
                    continue
                row[genome_index[genome]] += abundance
                matched += abundance
        if matched <= 0:
            continue
        row /= matched
        sample = path.stem
        rows.append(row)
        samples.append(sample)
        compartments.append(sample_compartment(sample))
        mapped_fractions.append(matched / total if total else 0.0)
    return (
        np.vstack(rows),
        samples,
        compartments,
        np.asarray(mapped_fractions),
    )


def annotation_matrix(
    profiles: dict[str, Counter[str]],
    genomes: list[str],
    max_kos: int,
) -> tuple[np.ndarray, list[str]]:
    prevalence: Counter[str] = Counter()
    for profile in profiles.values():
        prevalence.update(profile.keys())
    kos = [
        ko
        for ko, _ in sorted(
            prevalence.items(),
            key=lambda item: (-item[1], item[0]),
        )[:max_kos]
    ]
    ko_index = {ko: index for index, ko in enumerate(kos)}
    matrix = np.zeros((len(genomes), len(kos)), dtype=np.float32)
    for row, genome in enumerate(genomes):
        for ko, count in profiles[genome].items():
            column = ko_index.get(ko)
            if column is not None:
                matrix[row, column] = count
    return matrix, kos


def functional_profiles(
    abundance: np.ndarray,
    annotations: np.ndarray,
    genome_normalised: bool,
) -> np.ndarray:
    basis = annotations.copy()
    if genome_normalised:
        denominator = basis.sum(axis=1, keepdims=True)
        basis = np.divide(
            basis,
            denominator,
            out=np.zeros_like(basis),
            where=denominator > 0,
        )
    profile = abundance @ basis
    denominator = profile.sum(axis=1, keepdims=True)
    return np.divide(
        profile,
        denominator,
        out=np.zeros_like(profile),
        where=denominator > 0,
    )


def median_bray(frame: np.ndarray, indices: np.ndarray) -> float:
    if len(indices) < 3:
        return float("nan")
    return float(np.median(pdist(frame[indices], metric="braycurtis")))


def run_null(
    abundance: np.ndarray,
    annotations: np.ndarray,
    compartments: list[str],
    permutations: int,
    genome_normalised: bool,
    seed: int = SEED,
) -> list[dict[str, float | int | str]]:
    groups = {"All": np.arange(len(abundance))}
    for compartment in ("Surface", "Deep", "Rhizosphere"):
        groups[compartment] = np.flatnonzero(
            np.asarray(compartments) == compartment
        )
    taxonomic = {
        name: median_bray(abundance, indices)
        for name, indices in groups.items()
    }
    observed_profile = functional_profiles(
        abundance,
        annotations,
        genome_normalised=genome_normalised,
    )
    observed = {
        name: median_bray(observed_profile, indices)
        for name, indices in groups.items()
    }
    null: dict[str, list[float]] = {name: [] for name in groups}
    rng = np.random.default_rng(seed)
    for _ in range(permutations):
        permuted = annotations[rng.permutation(len(annotations))]
        profile = functional_profiles(
            abundance,
            permuted,
            genome_normalised=genome_normalised,
        )
        for name, indices in groups.items():
            null[name].append(median_bray(profile, indices))

    rows = []
    for name, indices in groups.items():
        distribution = np.asarray(null[name])
        valid_distribution = distribution[np.isfinite(distribution)]
        estimable = (
            np.isfinite(observed[name])
            and np.isfinite(taxonomic[name])
            and len(valid_distribution) == permutations
        )
        lower_tail_p = (
            (1 + np.sum(valid_distribution <= observed[name]))
            / (len(valid_distribution) + 1)
            if estimable
            else float("nan")
        )
        upper_tail_p = (
            (1 + np.sum(valid_distribution >= observed[name]))
            / (len(valid_distribution) + 1)
            if estimable
            else float("nan")
        )
        rows.append(
            {
                "annotation_basis": (
                    "within_genome_relative"
                    if genome_normalised
                    else "ko_copy_count"
                ),
                "group": name,
                "n_samples": len(indices),
                "taxonomic_median_bray": taxonomic[name],
                "observed_functional_median_bray": observed[name],
                "functional_taxonomic_ratio": (
                    observed[name] / taxonomic[name]
                    if taxonomic[name] > 0
                    else float("nan")
                ),
                "null_median": (
                    float(np.median(valid_distribution))
                    if estimable
                    else float("nan")
                ),
                "null_q025": (
                    float(np.quantile(valid_distribution, 0.025))
                    if estimable
                    else float("nan")
                ),
                "null_q975": (
                    float(np.quantile(valid_distribution, 0.975))
                    if estimable
                    else float("nan")
                ),
                "lower_tail_p": float(lower_tail_p),
                "upper_tail_p": float(upper_tail_p),
                "permutations": permutations,
            }
        )
    return rows


def analyse(
    coverm_dir: Path,
    eggnog_annotations: Path,
    output_dir: Path,
    permutations: int,
    max_kos: int,
) -> dict[str, object]:
    profiles = parse_genome_kos(eggnog_annotations)
    genomes = sorted(profiles)
    abundance, samples, compartments, mapped = load_abundance(
        coverm_dir,
        genomes,
    )
    annotations, kos = annotation_matrix(
        profiles,
        genomes,
        max_kos=max_kos,
    )
    rows = run_null(
        abundance,
        annotations,
        compartments,
        permutations,
        genome_normalised=False,
    ) + run_null(
        abundance,
        annotations,
        compartments,
        permutations,
        genome_normalised=True,
    )
    results = sorted(
        rows,
        key=lambda row: (row["annotation_basis"], row["group"]),
    )
    all_rows = [row for row in results if row["group"] == "All"]
    convergence_supported = all(
        row["lower_tail_p"] <= 0.05
        and row["observed_functional_median_bray"] < row["null_q025"]
        for row in all_rows
    )
    differentiation_supported = all(
        row["upper_tail_p"] <= 0.05
        and row["observed_functional_median_bray"] > row["null_q975"]
        for row in all_rows
    )
    convergence_status = (
        "encoded_functional_convergence_beyond_label_null"
        if convergence_supported
        else "not_robust_to_resolution_matched_null"
    )
    null_direction = (
        "below_lower_tail"
        if convergence_supported
        else "above_upper_tail"
        if differentiation_supported
        else "inside_null_interval"
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    columns = list(results[0])
    with (output_dir / "functional_redundancy_null.tsv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=columns,
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(results)
    sample_rows = [
        {
            "sample": sample,
            "compartment": compartment,
            "annotated_genome_fraction_of_coverm_total": fraction,
        }
        for sample, compartment, fraction in zip(
            samples, compartments, mapped
        )
    ]
    with (output_dir / "sample_coverage.tsv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(sample_rows[0]),
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(sample_rows)

    summary: dict[str, object] = {
        "schema_version": "1.0",
        "status": convergence_status,
        "null_direction": null_direction,
        "counts": {
            "genomes": len(genomes),
            "samples": len(samples),
            "kos_retained": len(kos),
            "permutations": permutations,
        },
        "mean_annotated_genome_fraction_of_coverm_total": float(mapped.mean()),
        "permitted_wording": (
            "Genome-resolved encoded KO profiles converge more than expected "
            "when intact genome annotations are randomly reassigned among the "
            "same abundance profiles."
            if convergence_supported
            else (
                "Encoded-functional turnover was lower than taxonomic turnover, "
                "but it exceeded the intact-genome-label null; the reconstructed "
                "fraction therefore does not support functional convergence."
                if differentiation_supported
                else "Encoded-functional turnover was lower than taxonomic "
                "turnover, but not beyond the resolution-matched genome-label null."
            )
        ),
        "limitations": [
            "The analysis covers only reads assigned to the dereplicated genome catalog.",
            "It tests encoded potential, not direct read-level function, expression, activity, or flux.",
            "The null reassigns intact annotation profiles and is not a metabolic-network null.",
        ],
    }
    (output_dir / "functional_redundancy_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n"
    )
    input_files = [eggnog_annotations] + sorted(coverm_dir.glob("*.tsv"))
    input_manifest = [
        {
            "role": (
                "genome_ko_annotations"
                if path == eggnog_annotations
                else "genome_relative_abundance"
            ),
            "path": str(path),
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
        }
        for path in input_files
    ]
    with (output_dir / "input_manifest.tsv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(input_manifest[0]),
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(input_manifest)
    provenance = {
        "script": str(Path(__file__).resolve()),
        "script_sha256": sha256(Path(__file__).resolve()),
        "seed": SEED,
        "parameters": {
            "permutations": permutations,
            "max_kos": max_kos,
        },
        "software": {
            package: importlib.metadata.version(package)
            for package in ("numpy", "scipy")
        },
    }
    (output_dir / "provenance.json").write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n"
    )
    (output_dir / "README.md").write_text(
        "\n".join(
            [
                "# Resolution-matched encoded-function null",
                "",
                f"- Convergence status: `{convergence_status}`",
                f"- Null direction: `{null_direction}`",
                f"- Genomes: {len(genomes)}",
                f"- Metagenomes: {len(samples)}",
                f"- Retained KOs: {len(kos)}",
                "- Mean coverM total assigned to genomes with KO annotations: "
                f"{mapped.mean():.3f}",
                "",
                str(summary["permitted_wording"]),
                "",
                "This is genome-resolved encoded potential. It is not a direct-read, "
                "expression, activity, or flux measurement.",
                "",
            ]
        )
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--coverm-dir", type=Path, required=True)
    parser.add_argument("--eggnog-annotations", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--permutations", type=int, default=199)
    parser.add_argument("--max-kos", type=int, default=2000)
    args = parser.parse_args()
    analyse(
        args.coverm_dir.resolve(),
        args.eggnog_annotations.resolve(),
        args.output_dir.resolve(),
        permutations=args.permutations,
        max_kos=args.max_kos,
    )


if __name__ == "__main__":
    main()
