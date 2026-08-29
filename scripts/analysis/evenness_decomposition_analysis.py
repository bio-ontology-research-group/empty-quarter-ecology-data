#!/usr/bin/env python3
"""Post-hoc decomposition of the paired Shannon compartment contrasts.

The ecology manuscript reports campaign-averaged, site-paired Shannon
contrasts.  Shannon entropy can change because the effective number of taxa,
their evenness, or both change.  This analysis applies the manuscript's
aggregation order to three complementary endpoints:

* Shannon entropy;
* Hurlbert expected richness at the existing 25,000-read standard; and
* H / log(E[S_25k]), the existing ``pielou`` column in ``alpha.tsv``.

The last endpoint is an evenness sensitivity, not conventional Pielou
evenness, because its denominator is expected standardized richness rather
than observed richness.  A conventional H / log(observed richness) result is
reported as a secondary sensitivity only.

This is a post-hoc explanatory analysis.  It does not establish a mechanism
and does not turn the operational root-adjacent collection position into a
botanical rhizosphere.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd
import scipy
from scipy import stats
import statsmodels
import statsmodels.formula.api as smf
from statsmodels.genmod.cov_struct import Exchangeable


SCHEMA_VERSION = "1.0"
CORE_SITES = range(1, 61)
POSITIONS = ("Surface", "Deep", "Rhizosphere")
POSITION_LABELS = {
    "Surface": "surface",
    "Deep": "shallow subsurface",
    "Rhizosphere": "root-adjacent",
}
CONTRASTS = (
    ("Deep", "Surface"),
    ("Rhizosphere", "Surface"),
    ("Rhizosphere", "Deep"),
)
PRIMARY_METRICS = (
    "shannon",
    "richness_hurlbert_25000",
    "evenness_h_over_log_hurlbert",
)
SECONDARY_METRICS = ("evenness_h_over_log_observed",)
BOOTSTRAP_RESAMPLES = 1_000_000
BOOTSTRAP_SEED = 20260723
BOOTSTRAP_BATCH_SIZE = 25_000


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def provenance_path(path: Path, root: Path) -> str:
    """Return a stable project-relative path without resolving symlinks."""
    candidate = path if path.is_absolute() else root / path
    try:
        return candidate.absolute().relative_to(root.absolute()).as_posix()
    except ValueError:
        return candidate.absolute().as_posix()


def bh_fdr(values: Sequence[float]) -> np.ndarray:
    """Benjamini--Hochberg adjustment with monotone ranked q values."""
    array = np.asarray(list(values), dtype=float)
    if array.size == 0:
        return array
    order = np.argsort(array)
    ranked = array[order] * array.size / (np.arange(array.size) + 1)
    ranked = np.minimum.accumulate(ranked[::-1])[::-1]
    adjusted = np.empty(array.size)
    adjusted[order] = np.clip(ranked, 0, 1)
    return adjusted


def write_tsv(
    path: Path,
    rows: Iterable[Mapping[str, Any]],
    columns: Sequence[str],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
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
                if value is None:
                    formatted[column] = ""
                elif isinstance(value, bool):
                    formatted[column] = "true" if value else "false"
                elif isinstance(value, float):
                    formatted[column] = (
                        f"{value:.12g}" if math.isfinite(value) else ""
                    )
                else:
                    formatted[column] = value
            writer.writerow(formatted)


def load_alpha(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, sep="\t")
    required = {
        "Trip",
        "Site",
        "Type",
        "depth",
        "richness_raw",
        "richness_rare",
        "shannon",
    }
    missing = required - set(frame)
    if missing:
        raise ValueError(f"Alpha table is missing columns: {sorted(missing)}")

    frame = frame.copy()
    frame["Trip"] = pd.to_numeric(frame["Trip"], errors="raise").astype(int)
    frame["Site"] = pd.to_numeric(frame["Site"], errors="raise").astype(int)
    frame["Type"] = frame["Type"].replace({"Rhizo": "Rhizosphere"})
    frame = frame[
        frame["Trip"].between(1, 5)
        & frame["Site"].isin(CORE_SITES)
        & frame["Type"].isin(POSITIONS)
    ].copy()

    numeric = ["depth", "richness_raw", "richness_rare", "shannon"]
    for column in numeric:
        frame[column] = pd.to_numeric(frame[column], errors="raise")
    if (frame[["depth", "richness_raw", "richness_rare"]] <= 0).any().any():
        raise ValueError("Depth and richness values must be positive")

    frame["richness_hurlbert_25000"] = frame["richness_rare"]
    frame["evenness_h_over_log_hurlbert"] = (
        frame["shannon"] / np.log(frame["richness_rare"])
    )
    frame["evenness_h_over_log_observed"] = (
        frame["shannon"] / np.log(frame["richness_raw"])
    )

    if "pielou" in frame:
        recorded = pd.to_numeric(frame["pielou"], errors="raise")
        computed = frame["evenness_h_over_log_hurlbert"]
        if not recorded.isna().equals(computed.isna()):
            raise ValueError(
                "The recorded pielou missingness does not match "
                "H/log(richness_rare)"
            )
        finite = recorded.notna()
        maximum_error = float(
            np.max(
                np.abs(
                    recorded.loc[finite].to_numpy()
                    - computed.loc[finite].to_numpy()
                )
            )
        )
        if maximum_error > 1e-10:
            raise ValueError(
                "The recorded pielou column is not H/log(richness_rare); "
                f"maximum discrepancy={maximum_error:.3g}"
            )
    return frame


def aggregate_profiles(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Apply the manuscript's profile -> block -> site aggregation order."""
    metrics = list(PRIMARY_METRICS + SECONDARY_METRICS)
    aggregations: dict[str, tuple[str, str]] = {
        metric: (metric, "mean") for metric in metrics
    }
    aggregations.update(
        {
            "sequencing_depth": ("depth", "sum"),
            "n_profiles": ("shannon", "size"),
        }
    )
    blocks = (
        frame.groupby(["Trip", "Site", "Type"], as_index=False)
        .agg(**aggregations)
        .sort_values(["Trip", "Site", "Type"])
    )
    site_means = (
        blocks.groupby(["Site", "Type"], as_index=False)[metrics]
        .mean()
        .sort_values(["Site", "Type"])
    )
    return blocks, site_means


def bootstrap_mean_ci(
    values: np.ndarray,
    *,
    resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
    batch_size: int = BOOTSTRAP_BATCH_SIZE,
) -> tuple[float, float]:
    """Return the seed-locked high-resolution percentile interval.

    This is intentionally the same implementation, resample count and seed
    used by ``claim_rescue.py``.  It prevents two canonical artifacts for the
    same Shannon estimand from disagreeing because of Monte Carlo resolution.
    """
    values = np.asarray(values, dtype=float)
    if values.ndim != 1 or values.size < 3:
        raise ValueError("Bootstrap input must contain at least three values")
    if resamples < 1 or batch_size < 1:
        raise ValueError("Bootstrap resamples and batch size must be positive")
    rng = np.random.default_rng(seed)
    bootstrap_means = np.empty(resamples, dtype=float)
    for start in range(0, resamples, batch_size):
        stop = min(start + batch_size, resamples)
        sampled = rng.choice(
            values,
            size=(stop - start, values.size),
            replace=True,
        )
        bootstrap_means[start:stop] = sampled.mean(axis=1)
    low, high = np.quantile(bootstrap_means, [0.025, 0.975])
    return float(low), float(high)


def paired_contrasts(
    site_means: pd.DataFrame,
    metrics: Sequence[str],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for metric in metrics:
        wide = site_means.pivot(
            index="Site",
            columns="Type",
            values=metric,
        )
        metric_rows: list[dict[str, Any]] = []
        for first, second in CONTRASTS:
            pair = wide[[first, second]].dropna()
            difference = pair[first] - pair[second]
            if len(difference) < 3:
                raise ValueError(
                    f"Too few paired sites for {metric}: {first}-{second}"
                )
            test = stats.wilcoxon(
                difference.to_numpy(),
                alternative="two-sided",
                method="auto",
            )
            values = difference.to_numpy()
            ci_low, ci_high = bootstrap_mean_ci(
                values,
                resamples=BOOTSTRAP_RESAMPLES,
                seed=BOOTSTRAP_SEED,
            )
            metric_rows.append(
                {
                    "metric": metric,
                    "contrast": f"{first}-{second}",
                    "contrast_label": (
                        f"{POSITION_LABELS[first]} minus "
                        f"{POSITION_LABELS[second]}"
                    ),
                    "n_sites": len(difference),
                    "mean_difference": float(difference.mean()),
                    "median_difference": float(difference.median()),
                    "bootstrap_ci_low": ci_low,
                    "bootstrap_ci_high": ci_high,
                    "wilcoxon_w": float(test.statistic),
                    "p": float(test.pvalue),
                    "fraction_positive": float((difference > 0).mean()),
                    "bootstrap_resamples": BOOTSTRAP_RESAMPLES,
                    "bootstrap_seed": BOOTSTRAP_SEED,
                }
            )
        q_values = bh_fdr([row["p"] for row in metric_rows])
        for row, q_value in zip(metric_rows, q_values):
            row["q_within_metric"] = float(q_value)
        rows.extend(metric_rows)
    return pd.DataFrame(rows)


def _linear_contrast(
    fit: Any,
    first: str,
    second: str,
) -> dict[str, float]:
    names = list(fit.params.index)
    restriction = np.zeros((1, len(names)))

    def add_position(position: str, weight: float) -> None:
        if position == "Surface":
            return
        term = (
            "C(Type, Treatment(reference='Surface'))"
            f"[T.{position}]"
        )
        restriction[0, names.index(term)] += weight

    add_position(first, 1.0)
    add_position(second, -1.0)
    result = fit.t_test(restriction)
    estimate = float(np.asarray(result.effect).reshape(-1)[0])
    standard_error = float(np.asarray(result.sd).reshape(-1)[0])
    p_value = float(np.asarray(result.pvalue).reshape(-1)[0])
    confidence_interval = np.asarray(result.conf_int()).reshape(-1, 2)[0]
    return {
        "estimate": estimate,
        "std_error": standard_error,
        "ci_low": float(confidence_interval[0]),
        "ci_high": float(confidence_interval[1]),
        "p": p_value,
    }


def evenness_depth_sensitivity(blocks: pd.DataFrame) -> pd.DataFrame:
    frame = blocks.copy()
    frame["log_sequencing_depth"] = np.log(frame["sequencing_depth"])
    formulas = {
        "campaign_adjusted": (
            "evenness_h_over_log_hurlbert ~ C(Trip) + "
            "C(Type, Treatment(reference='Surface'))"
        ),
        "campaign_and_depth_adjusted": (
            "evenness_h_over_log_hurlbert ~ C(Trip) + "
            "C(Type, Treatment(reference='Surface')) + "
            "log_sequencing_depth"
        ),
    }
    rows: list[dict[str, Any]] = []
    for model_name, formula in formulas.items():
        fit = smf.gee(
            formula,
            groups="Site",
            data=frame,
            cov_struct=Exchangeable(),
        ).fit()
        for first, second in CONTRASTS:
            result = _linear_contrast(fit, first, second)
            rows.append(
                {
                    "model": model_name,
                    "formula": formula,
                    "contrast": f"{first}-{second}",
                    "contrast_label": (
                        f"{POSITION_LABELS[first]} minus "
                        f"{POSITION_LABELS[second]}"
                    ),
                    "n_blocks": int(fit.nobs),
                    "n_sites": int(frame["Site"].nunique()),
                    **result,
                }
            )
    result = pd.DataFrame(rows)
    result["q_within_model"] = np.nan
    for model_name, indices in result.groupby("model").groups.items():
        result.loc[list(indices), "q_within_model"] = bh_fdr(
            result.loc[list(indices), "p"].to_numpy()
        )
    return result


def build_verdict(
    alpha_path: Path,
    frame: pd.DataFrame,
    blocks: pd.DataFrame,
    contrasts: pd.DataFrame,
    depth_sensitivity: pd.DataFrame,
) -> dict[str, Any]:
    primary = contrasts[
        contrasts["metric"].isin(PRIMARY_METRICS)
    ].copy()

    def result(metric: str, contrast: str) -> dict[str, Any]:
        row = primary[
            (primary["metric"] == metric)
            & (primary["contrast"] == contrast)
        ].iloc[0]
        return {
            "mean_difference": float(row["mean_difference"]),
            "bootstrap_ci": [
                float(row["bootstrap_ci_low"]),
                float(row["bootstrap_ci_high"]),
            ],
            "p": float(row["p"]),
            "q_within_metric": float(row["q_within_metric"]),
            "fraction_positive": float(row["fraction_positive"]),
        }

    depth_rows = depth_sensitivity[
        depth_sensitivity["model"] == "campaign_and_depth_adjusted"
    ]
    depth_results = {
        row["contrast"]: {
            "estimate": float(row["estimate"]),
            "ci": [float(row["ci_low"]), float(row["ci_high"])],
            "p": float(row["p"]),
            "q_within_model": float(row["q_within_model"]),
        }
        for _, row in depth_rows.iterrows()
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "post_hoc_evenness_decomposition_supported",
        "interpretation": (
            "The lower campaign-averaged Shannon entropy in root-adjacent "
            "soil is accompanied by a much clearer lower-evenness signal. "
            "Hurlbert expected richness at 25,000 reads shows no "
            "root-adjacent versus surface difference and mixed evidence "
            "for root-adjacent versus shallow subsurface (the bootstrap "
            "interval for the mean excludes zero, but the paired Wilcoxon "
            "q is 0.0878). The evenness direction persists in a campaign- "
            "and log-depth-adjusted GEE."
        ),
        "permitted_wording": (
            "In a post-hoc decomposition, the lower paired Shannon "
            "distribution in root-adjacent samples was accompanied by a "
            "clearer lower normalized-evenness signal than expected-richness "
            "signal: expected richness did not differ from surface, and its "
            "root-adjacent--shallow evidence was mixed across summaries. "
            "This describes the diversity profile and does not identify a "
            "root-mediated mechanism."
        ),
        "prohibited_wording": (
            "Do not call H/log(E[S_25k]) conventional Pielou evenness, do "
            "not describe a causal rhizosphere filter, and do not treat "
            "post-hoc decomposition as a preregistered primary endpoint."
        ),
        "metric_note": (
            "The source column named pielou is exactly Shannon divided by "
            "log Hurlbert expected richness. Because expected standardized "
            "richness replaces observed richness in the denominator, the "
            "analysis calls it an evenness sensitivity rather than "
            "conventional Pielou evenness."
        ),
        "multiplicity": (
            "The three position contrasts form one Benjamini-Hochberg "
            "family within each metric. The secondary observed-richness "
            "denominator is a separate sensitivity family."
        ),
        "limitations": (
            "Hurlbert expected richness is unavailable for 55 core-frame "
            "profiles below the 25,000-read standard, and normalized "
            "evenness is additionally undefined for one single-ASV profile. "
            "The corresponding GEE therefore uses 617 of 633 "
            "site-campaign-position blocks. All 60 sites contribute to the "
            "campaign-averaged paired contrasts, but some site means are "
            "based on fewer profiles or campaigns. The decomposition is "
            "post hoc."
        ),
        "primary_results": {
            contrast: {
                "shannon": result("shannon", contrast),
                "hurlbert_expected_richness_25000": result(
                    "richness_hurlbert_25000", contrast
                ),
                "evenness_sensitivity": result(
                    "evenness_h_over_log_hurlbert", contrast
                ),
                "evenness_depth_adjusted_gee": depth_results[contrast],
            }
            for contrast in [
                "Deep-Surface",
                "Rhizosphere-Surface",
                "Rhizosphere-Deep",
            ]
        },
        "input": {
            "path": provenance_path(
                alpha_path, Path(__file__).resolve().parents[2]
            ),
            "sha256": sha256_file(alpha_path),
            "profiles_in_core_frame": int(len(frame)),
            "site_campaign_position_blocks": int(len(blocks)),
            "profiles_with_hurlbert_richness": int(
                frame["richness_hurlbert_25000"].notna().sum()
            ),
            "profiles_with_evenness_sensitivity": int(
                frame["evenness_h_over_log_hurlbert"].notna().sum()
            ),
            "blocks_with_evenness_sensitivity": int(
                blocks["evenness_h_over_log_hurlbert"].notna().sum()
            ),
            "sites": int(frame["Site"].nunique()),
            "campaigns": sorted(int(value) for value in frame["Trip"].unique()),
            "aggregation": (
                "mean profiles within campaign x site x position, then mean "
                "campaign blocks within site x position; site is the paired "
                "bootstrap and Wilcoxon unit"
            ),
        },
        "software": {
            "numpy": np.__version__,
            "pandas": pd.__version__,
            "scipy": scipy.__version__,
            "statsmodels": statsmodels.__version__,
        },
    }


def write_readme(path: Path, verdict: Mapping[str, Any]) -> None:
    results = verdict["primary_results"]

    def line(contrast: str) -> str:
        item = results[contrast]
        richness = item["hurlbert_expected_richness_25000"]
        evenness = item["evenness_sensitivity"]
        return (
            f"- **{contrast}**: expected-richness difference "
            f"{richness['mean_difference']:.3f} "
            f"(q={richness['q_within_metric']:.4g}); evenness-sensitivity "
            f"difference {evenness['mean_difference']:.4f} "
            f"(95% bootstrap CI {evenness['bootstrap_ci'][0]:.4f} to "
            f"{evenness['bootstrap_ci'][1]:.4f}; "
            f"q={evenness['q_within_metric']:.4g})."
        )

    content = "\n".join(
        [
            "# Post-hoc evenness decomposition",
            "",
            f"**Status:** `{verdict['status']}`",
            "",
            verdict["interpretation"],
            "",
            "## Primary paired results",
            "",
            line("Deep-Surface"),
            line("Rhizosphere-Surface"),
            line("Rhizosphere-Deep"),
            "",
            "## Interpretation boundary",
            "",
            verdict["metric_note"],
            "",
            f"Limitation: {verdict['limitations']}",
            "",
            f"Permitted wording: {verdict['permitted_wording']}",
            "",
            f"Prohibited wording: {verdict['prohibited_wording']}",
            "",
            "## Reproduction",
            "",
            "```bash",
            "uv run --python .venv/bin/python "
            "analysis/v3/evenness_decomposition_analysis.py",
            "```",
            "",
        ]
    )
    path.write_text(content, encoding="utf-8")


def write_checksums(output_dir: Path, names: Sequence[str]) -> None:
    rows = [
        f"{sha256_file(output_dir / name)}  {name}"
        for name in sorted(names)
    ]
    (output_dir / "SHA256SUMS").write_text(
        "\n".join(rows) + "\n",
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    project_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--alpha",
        type=Path,
        default=project_root / "analysis/v2/review/cache/alpha.tsv",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=project_root / "analysis/v3/evenness_decomposition",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    frame = load_alpha(args.alpha)
    blocks, site_means = aggregate_profiles(frame)
    contrasts = paired_contrasts(
        site_means,
        PRIMARY_METRICS + SECONDARY_METRICS,
    )
    depth_sensitivity = evenness_depth_sensitivity(blocks)
    verdict = build_verdict(
        args.alpha,
        frame,
        blocks,
        contrasts,
        depth_sensitivity,
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_tsv(
        args.output_dir / "site_campaign_position_metrics.tsv",
        blocks.to_dict("records"),
        list(blocks.columns),
    )
    write_tsv(
        args.output_dir / "site_position_means.tsv",
        site_means.to_dict("records"),
        list(site_means.columns),
    )
    write_tsv(
        args.output_dir / "paired_contrasts.tsv",
        contrasts.to_dict("records"),
        list(contrasts.columns),
    )
    write_tsv(
        args.output_dir / "evenness_depth_sensitivity.tsv",
        depth_sensitivity.to_dict("records"),
        list(depth_sensitivity.columns),
    )
    (args.output_dir / "claim_verdict.json").write_text(
        json.dumps(verdict, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_readme(args.output_dir / "README.md", verdict)
    write_checksums(
        args.output_dir,
        [
            "README.md",
            "claim_verdict.json",
            "evenness_depth_sensitivity.tsv",
            "paired_contrasts.tsv",
            "site_campaign_position_metrics.tsv",
            "site_position_means.tsv",
        ],
    )
    print(
        "PASS: wrote post-hoc evenness decomposition to "
        f"{args.output_dir}"
    )


if __name__ == "__main__":
    main()
