#!/usr/bin/env python3
"""Bounded paired endpoint analysis for the Trip-5 PMA experiment.

The input count table contains nine matched treated/untreated aliquot pairs.
This module reports only two direct endpoints:

* Hurlbert expected richness at the minimum library size across the 18
  biological samples; and
* Shannon diversity calculated from each full count vector.

Paired two-sided exact Wilcoxon tests use the aliquot pair as the unit of
analysis.  The result does not estimate a relic-DNA fraction, cell viability,
or a survey-wide mechanism.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import json
import math
import re
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd
from scipy import stats
from scipy.special import gammaln


SCHEMA_VERSION = "1.0"
PAIR_RE = re.compile(
    r"^(?P<pair_id>C\d+[RS]\d+)(?P<treatment>UT|T)$"
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def relative_path(path: Path, root: Path) -> str:
    """Return a stable project-relative path without following symlinks."""
    candidate = path if path.is_absolute() else root / path
    try:
        return candidate.absolute().relative_to(root.absolute()).as_posix()
    except ValueError:
        return candidate.absolute().as_posix()


def write_tsv(
    path: Path,
    rows: Iterable[Mapping[str, Any]],
    columns: Sequence[str],
) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(columns),
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        for row in rows:
            formatted: dict[str, Any] = {}
            for column in columns:
                value = row.get(column)
                if isinstance(value, float):
                    formatted[column] = (
                        f"{value:.12g}" if math.isfinite(value) else ""
                    )
                elif isinstance(value, bool):
                    formatted[column] = "true" if value else "false"
                elif value is None:
                    formatted[column] = ""
                else:
                    formatted[column] = value
            writer.writerow(formatted)


def expected_rarefied_richness(
    counts: np.ndarray,
    depth: int,
) -> float:
    """Return exact expected richness in a hypergeometric rarefied sample."""
    values = np.asarray(counts, dtype=np.int64)
    if values.ndim != 1 or np.any(values < 0):
        raise ValueError("Counts must be a one-dimensional non-negative vector")
    library_size = int(values.sum())
    if depth <= 0 or depth > library_size:
        raise ValueError(
            f"Rarefaction depth {depth} is outside 1..{library_size}"
        )
    positive = values[values > 0]
    can_be_absent = library_size - positive >= depth
    log_probability_absent = np.full(len(positive), -np.inf, dtype=float)
    # log[C(N-n_i, d) / C(N, d)]; the d! terms cancel.
    log_probability_absent[can_be_absent] = (
        gammaln(library_size - positive[can_be_absent] + 1)
        - gammaln(library_size - positive[can_be_absent] - depth + 1)
        - gammaln(library_size + 1)
        + gammaln(library_size - depth + 1)
    )
    return float(np.sum(-np.expm1(log_probability_absent)))


def shannon_entropy(counts: np.ndarray) -> float:
    values = np.asarray(counts, dtype=float)
    if values.ndim != 1 or np.any(values < 0):
        raise ValueError("Counts must be a one-dimensional non-negative vector")
    positive = values[values > 0]
    if not len(positive):
        return float("nan")
    proportions = positive / positive.sum()
    return float(-np.sum(proportions * np.log(proportions)))


def paired_columns(columns: Sequence[str]) -> list[dict[str, str]]:
    pairs: dict[str, dict[str, str]] = {}
    for column in columns:
        match = PAIR_RE.fullmatch(str(column))
        if match is None:
            continue
        pair_id = match.group("pair_id")
        treatment = match.group("treatment")
        key = "untreated_sample" if treatment == "UT" else "treated_sample"
        if key in pairs.setdefault(pair_id, {}):
            raise ValueError(f"Duplicate {key} for pair {pair_id}")
        pairs[pair_id][key] = str(column)
    incomplete = {
        pair_id: values
        for pair_id, values in pairs.items()
        if set(values) != {"treated_sample", "untreated_sample"}
    }
    if incomplete:
        raise ValueError(f"Incomplete PMA pairs: {incomplete}")
    return [
        {"pair_id": pair_id, **pairs[pair_id]}
        for pair_id in sorted(pairs)
    ]


def exact_paired_wilcoxon(differences: np.ndarray) -> dict[str, float]:
    values = np.asarray(differences, dtype=float)
    if not len(values) or np.any(~np.isfinite(values)):
        raise ValueError("Wilcoxon differences must be finite and non-empty")
    if np.any(values == 0):
        raise ValueError(
            "Exact Wilcoxon calculation requires non-zero paired differences"
        )
    result = stats.wilcoxon(
        values,
        alternative="two-sided",
        zero_method="wilcox",
        correction=False,
        method="exact",
    )
    return {"statistic": float(result.statistic), "p_value": float(result.pvalue)}


def analyse_pma(
    counts_path: Path,
    rarefaction_depth: int | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    counts = pd.read_csv(counts_path, sep="\t", index_col=0)
    pairs = paired_columns([str(column) for column in counts.columns])
    if len(pairs) != 9:
        raise ValueError(f"Expected nine complete PMA pairs; found {len(pairs)}")
    sample_columns = [
        item[key]
        for item in pairs
        for key in ("treated_sample", "untreated_sample")
    ]
    biological = counts[sample_columns].apply(
        pd.to_numeric, errors="raise"
    )
    values = biological.to_numpy(dtype=float)
    if np.any(~np.isfinite(values)) or np.any(values < 0):
        raise ValueError("PMA count matrix contains invalid values")
    if not np.allclose(values, np.rint(values)):
        raise ValueError("PMA count matrix must contain integer counts")
    biological = biological.astype(np.int64)
    library_sizes = biological.sum(axis=0)
    depth = (
        int(library_sizes.min())
        if rarefaction_depth is None
        else int(rarefaction_depth)
    )
    if depth > int(library_sizes.min()):
        raise ValueError(
            "Rarefaction depth exceeds at least one paired-sample library"
        )

    rows: list[dict[str, Any]] = []
    for pair in pairs:
        treated_sample = pair["treated_sample"]
        untreated_sample = pair["untreated_sample"]
        treated = biological[treated_sample].to_numpy(dtype=np.int64)
        untreated = biological[untreated_sample].to_numpy(dtype=np.int64)
        treated_rarefied = expected_rarefied_richness(treated, depth)
        untreated_rarefied = expected_rarefied_richness(untreated, depth)
        treated_shannon = shannon_entropy(treated)
        untreated_shannon = shannon_entropy(untreated)
        rows.append(
            {
                "pair_id": pair["pair_id"],
                "treated_sample": treated_sample,
                "untreated_sample": untreated_sample,
                "treated_reads": int(treated.sum()),
                "untreated_reads": int(untreated.sum()),
                "rarefaction_depth": depth,
                "treated_observed_asvs": int(np.count_nonzero(treated)),
                "untreated_observed_asvs": int(np.count_nonzero(untreated)),
                "treated_expected_rarefied_richness": treated_rarefied,
                "untreated_expected_rarefied_richness": untreated_rarefied,
                "rarefied_richness_difference_treated_minus_untreated": (
                    treated_rarefied - untreated_rarefied
                ),
                "treated_shannon": treated_shannon,
                "untreated_shannon": untreated_shannon,
                "shannon_difference_treated_minus_untreated": (
                    treated_shannon - untreated_shannon
                ),
            }
        )

    richness_differences = np.asarray(
        [
            row[
                "rarefied_richness_difference_treated_minus_untreated"
            ]
            for row in rows
        ]
    )
    shannon_differences = np.asarray(
        [
            row["shannon_difference_treated_minus_untreated"]
            for row in rows
        ]
    )
    richness_test = exact_paired_wilcoxon(richness_differences)
    shannon_test = exact_paired_wilcoxon(shannon_differences)
    summary: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "analysis_unit": "paired aliquot",
        "n_pairs": len(rows),
        "rarefaction": {
            "method": "Hurlbert exact expected richness",
            "depth": depth,
            "depth_basis": (
                "minimum library size among the 18 paired biological samples"
                if rarefaction_depth is None
                else "user-specified"
            ),
            "random_rarefaction": False,
        },
        "richness_endpoint": {
            "treated_mean": float(
                np.mean(
                    [
                        row["treated_expected_rarefied_richness"]
                        for row in rows
                    ]
                )
            ),
            "untreated_mean": float(
                np.mean(
                    [
                        row["untreated_expected_rarefied_richness"]
                        for row in rows
                    ]
                )
            ),
            "mean_difference_treated_minus_untreated": float(
                np.mean(richness_differences)
            ),
            "pairs_with_lower_treated_value": int(
                np.sum(richness_differences < 0)
            ),
            "wilcoxon_two_sided_exact": richness_test,
        },
        "shannon_endpoint": {
            "logarithm": "natural",
            "treated_mean": float(
                np.mean([row["treated_shannon"] for row in rows])
            ),
            "untreated_mean": float(
                np.mean([row["untreated_shannon"] for row in rows])
            ),
            "mean_difference_treated_minus_untreated": float(
                np.mean(shannon_differences)
            ),
            "wilcoxon_two_sided_exact": shannon_test,
        },
        "status": "paired_endpoints_only",
        "permitted_wording": (
            "In nine paired Trip-5 aliquots, PMA treatment reduced expected "
            "rarefied richness, while no Shannon-diversity difference was "
            "detected."
        ),
        "not_supported": [
            "a quantitative relic-DNA fraction",
            "equivalence or proof of no Shannon effect",
            "cell viability",
            "survey-wide relic-DNA uniformity",
            "a mechanism for patterns across campaigns or compartments",
        ],
    }
    return rows, summary


def write_outputs(
    project_root: Path,
    counts_path: Path,
    output_dir: Path,
    rarefaction_depth: int | None,
) -> dict[str, Any]:
    rows, summary = analyse_pma(counts_path, rarefaction_depth)
    output_dir.mkdir(parents=True, exist_ok=True)
    pair_columns = [
        "pair_id",
        "treated_sample",
        "untreated_sample",
        "treated_reads",
        "untreated_reads",
        "rarefaction_depth",
        "treated_observed_asvs",
        "untreated_observed_asvs",
        "treated_expected_rarefied_richness",
        "untreated_expected_rarefied_richness",
        "rarefied_richness_difference_treated_minus_untreated",
        "treated_shannon",
        "untreated_shannon",
        "shannon_difference_treated_minus_untreated",
    ]
    write_tsv(output_dir / "pma_pair_endpoints.tsv", rows, pair_columns)

    script_path = Path(__file__).resolve()
    summary["input"] = {
        "path": relative_path(counts_path, project_root),
        "bytes": counts_path.stat().st_size,
        "sha256": sha256_file(counts_path),
    }
    summary["provenance"] = {
        "script": relative_path(script_path, project_root),
        "script_sha256": sha256_file(script_path),
        "seed": None,
        "random_operations": False,
        "software": {
            package: importlib.metadata.version(package)
            for package in ("numpy", "pandas", "scipy")
        },
    }
    (output_dir / "pma_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_tsv(
        output_dir / "input_manifest.tsv",
        [
            {
                "role": "Trip-5 PMA ASV counts",
                "path": relative_path(counts_path, project_root),
                "bytes": counts_path.stat().st_size,
                "sha256": sha256_file(counts_path),
            }
        ],
        ["role", "path", "bytes", "sha256"],
    )
    richness = summary["richness_endpoint"]
    shannon = summary["shannon_endpoint"]
    readme = [
        "# Paired Trip-5 PMA endpoints",
        "",
        str(summary["permitted_wording"]),
        "",
        f"- Pairs: {summary['n_pairs']}",
        f"- Exact expected-richness depth: {summary['rarefaction']['depth']:,} reads",
        "- Expected rarefied richness, treated versus untreated mean: "
        f"{richness['treated_mean']:.1f} versus "
        f"{richness['untreated_mean']:.1f}",
        "- Richness paired exact Wilcoxon: "
        f"W={richness['wilcoxon_two_sided_exact']['statistic']:.0f}, "
        f"p={richness['wilcoxon_two_sided_exact']['p_value']:.6g}",
        "- Shannon, treated versus untreated mean: "
        f"{shannon['treated_mean']:.2f} versus "
        f"{shannon['untreated_mean']:.2f}",
        "- Shannon paired exact Wilcoxon: "
        f"W={shannon['wilcoxon_two_sided_exact']['statistic']:.0f}, "
        f"p={shannon['wilcoxon_two_sided_exact']['p_value']:.6g}",
        "",
        "The richness endpoint is an exact expectation, not a random rarefaction; "
        "no seed is used. A nonsignificant Shannon test is reported as no "
        "detected difference, not as equivalence.",
        "",
        "These endpoints do not quantify a relic-DNA fraction, establish cell "
        "viability, or support a survey-wide mechanism.",
        "",
    ]
    (output_dir / "README.md").write_text(
        "\n".join(readme), encoding="utf-8"
    )
    checksum_lines = [
        f"{sha256_file(path)}  {path.name}"
        for path in sorted(output_dir.iterdir())
        if path.is_file() and path.name != "SHA256SUMS"
    ]
    (output_dir / "SHA256SUMS").write_text(
        "\n".join(checksum_lines) + "\n", encoding="utf-8"
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
    )
    parser.add_argument("--counts", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--rarefaction-depth", type=int, default=None)
    args = parser.parse_args()

    project_root = args.project_root.resolve()
    counts_path = (
        args.counts.absolute()
        if args.counts is not None
        else project_root / "relic-dna" / "ASV_table.tsv"
    )
    output_dir = (
        args.output_dir.resolve()
        if args.output_dir is not None
        else project_root / "analysis" / "v3" / "pma_endpoint_results"
    )
    write_outputs(
        project_root,
        counts_path,
        output_dir,
        args.rarefaction_depth,
    )


if __name__ == "__main__":
    main()
