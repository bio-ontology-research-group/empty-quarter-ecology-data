#!/usr/bin/env python3
"""Reanalyse compatible public Atacama surveys for manuscript context.

The script does not merge feature tables across deserts.  It asks whether two
patterns measured in the Empty Quarter also appear in public surveys with
different primers and sampling designs:

* association of site-level diversity with soil relative humidity along an
  Atacama aridity gradient; and
* compositional and diversity change with depth in one Atacama soil pit.

Technical replicates are averaged or aggregated before inference, so the
biological site (gradient) or sampled depth (pit) is the independent unit.
The results are contextual comparisons, not a cross-desert meta-analysis and
not evidence that the same mechanism operates in each desert.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats


SEED = 20260804
PERMUTATIONS = 9_999
RAREFACTION_DEPTH = 8_000
RAREFACTION_ITERATIONS = 100
TOP_GENERA = 200
PSEUDOCOUNT = 0.5


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def portable_path(path: Path, project_root: Path) -> str:
    """Prefer a stable project-relative provenance path when possible."""
    try:
        return path.relative_to(project_root).as_posix()
    except ValueError:
        return path.as_posix()


def partial_spearman(
    x: np.ndarray, y: np.ndarray, covariates: np.ndarray
) -> tuple[float, float]:
    """Rank x and y, residualize both on covariates, then correlate."""
    ranked_x = stats.rankdata(np.asarray(x, dtype=float))
    ranked_y = stats.rankdata(np.asarray(y, dtype=float))
    design = np.column_stack(
        [np.ones(len(ranked_x)), np.asarray(covariates, dtype=float)]
    )
    residual_x = ranked_x - design @ np.linalg.lstsq(
        design, ranked_x, rcond=None
    )[0]
    residual_y = ranked_y - design @ np.linalg.lstsq(
        design, ranked_y, rcond=None
    )[0]
    result = stats.pearsonr(residual_x, residual_y)
    return float(result.statistic), float(result.pvalue)


def pseudo_f(coordinates: np.ndarray, groups: np.ndarray) -> float:
    """Euclidean PERMANOVA pseudo-F for a one-factor grouping."""
    coordinates = np.asarray(coordinates, dtype=float)
    groups = np.asarray(groups)
    group_names = np.unique(groups)
    grand_mean = coordinates.mean(axis=0)
    between = 0.0
    within = 0.0
    for name in group_names:
        values = coordinates[groups == name]
        group_mean = values.mean(axis=0)
        between += len(values) * float(np.sum((group_mean - grand_mean) ** 2))
        within += float(np.sum((values - group_mean) ** 2))
    numerator_df = len(group_names) - 1
    denominator_df = len(coordinates) - len(group_names)
    if numerator_df <= 0 or denominator_df <= 0 or within <= 0:
        raise ValueError("Cannot compute the requested pseudo-F")
    return (between / numerator_df) / (within / denominator_df)


def permutation_pseudo_f(
    coordinates: np.ndarray,
    groups: np.ndarray,
    permutations: int,
    seed: int,
) -> tuple[float, float]:
    observed = pseudo_f(coordinates, groups)
    rng = np.random.default_rng(seed)
    exceedances = 0
    for _ in range(permutations):
        permuted = rng.permutation(groups)
        if pseudo_f(coordinates, permuted) >= observed - 1e-12:
            exceedances += 1
    return observed, (exceedances + 1) / (permutations + 1)


def analyse_gradient(path: Path) -> tuple[list[dict[str, object]], dict[str, object]]:
    frame = pd.read_csv(path)
    required = {
        "site",
        "obs_richness",
        "shannon",
        "soilrh",
        "elevation",
        "latitude",
        "longitude",
        "n_tech",
    }
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"{path} is missing columns: {sorted(missing)}")
    cohort = frame.dropna(
        subset=["soilrh", "elevation", "latitude", "longitude"]
    ).copy()
    if len(cohort) != 16 or cohort["site"].nunique() != 16:
        raise ValueError("Expected 16 independent Atacama gradient sites")
    covariates = cohort[["latitude", "longitude", "elevation"]].to_numpy()
    rows: list[dict[str, object]] = []
    for response, label in (
        ("shannon", "Shannon diversity"),
        ("obs_richness", "rarefied observed richness"),
    ):
        raw = stats.spearmanr(cohort["soilrh"], cohort[response])
        partial_rho, partial_p = partial_spearman(
            cohort["soilrh"].to_numpy(),
            cohort[response].to_numpy(),
            covariates,
        )
        rows.extend(
            [
                {
                    "desert": "Atacama",
                    "dataset": "QIITA 10360 / PRJEB17617",
                    "design": "two aridity-gradient transects",
                    "independent_unit": "site",
                    "n_units": len(cohort),
                    "question": f"soil relative humidity versus {label}",
                    "method": "site-level Spearman correlation",
                    "estimate_name": "rho",
                    "estimate": float(raw.statistic),
                    "p_value": float(raw.pvalue),
                    "comparison_boundary": (
                        "V4 closed-reference OTUs; effect direction only, not "
                        "taxon identity or absolute diversity"
                    ),
                },
                {
                    "desert": "Atacama",
                    "dataset": "QIITA 10360 / PRJEB17617",
                    "design": "two aridity-gradient transects",
                    "independent_unit": "site",
                    "n_units": len(cohort),
                    "question": f"soil relative humidity versus {label}",
                    "method": (
                        "partial Spearman correlation adjusted for latitude, "
                        "longitude and elevation"
                    ),
                    "estimate_name": "partial_rho",
                    "estimate": partial_rho,
                    "p_value": partial_p,
                    "comparison_boundary": (
                        "small observational gradient with residual collinearity; "
                        "association is not a causal effect"
                    ),
                },
            ]
        )
    audit = {
        "input_sites": int(len(frame)),
        "analysis_sites": int(len(cohort)),
        "technical_profiles_represented": int(cohort["n_tech"].sum()),
        "excluded_sites": sorted(set(frame["site"]) - set(cohort["site"])),
    }
    return rows, audit


def rarefy_profile(
    counts: np.ndarray, depth: int, rng: np.random.Generator
) -> np.ndarray:
    if counts.sum() < depth:
        raise ValueError("Profile is below the declared rarefaction depth")
    return rng.multivariate_hypergeometric(counts.astype(np.int64), depth)


def analyse_pit(
    counts_path: Path,
    taxonomy_path: Path,
    depth_path: Path,
) -> tuple[list[dict[str, object]], dict[str, object], pd.DataFrame]:
    counts = pd.read_csv(counts_path, sep="\t", index_col=0)
    taxonomy = pd.read_csv(taxonomy_path, sep="\t", index_col=0)
    depths = pd.read_csv(depth_path, sep="\t")
    if not {"sampleID", "depth_cm", "replicate"}.issubset(depths.columns):
        raise ValueError(f"Unexpected depth-map schema in {depth_path}")
    depth_lookup = depths.set_index("sampleID")["depth_cm"]
    samples = [sample for sample in counts.columns if sample in depth_lookup.index]
    totals = counts[samples].sum(axis=0)
    retained = totals[totals >= RAREFACTION_DEPTH].index.tolist()
    if len(retained) != 62:
        raise ValueError("Expected all 62 Atacama pit profiles above 8,000 reads")
    counts = counts[retained]

    genus_column = next(
        (column for column in taxonomy.columns if column.lower() == "genus"),
        None,
    )
    if genus_column is None:
        raise ValueError(f"No genus column found in {taxonomy_path}")
    genera = taxonomy[genus_column].reindex(counts.index).fillna("Unassigned")
    genus_counts = counts.groupby(genera).sum()
    top = genus_counts.sum(axis=1).nlargest(TOP_GENERA).index
    genus_counts = genus_counts.loc[top]

    sample_depth = depth_lookup.reindex(retained).astype(float)
    depth_counts = genus_counts.T.assign(depth_cm=sample_depth).groupby(
        "depth_cm", sort=True
    ).sum()
    log_values = np.log(depth_counts.to_numpy(dtype=float) + PSEUDOCOUNT)
    clr = log_values - log_values.mean(axis=1, keepdims=True)
    depth_values = depth_counts.index.to_numpy(dtype=float)
    zones = np.where(
        depth_values < 50,
        "shallow (<50 cm)",
        np.where(depth_values < 200, "middle (50--<200 cm)", "deep (>=200 cm)"),
    )
    observed_f, composition_p = permutation_pseudo_f(
        clr, zones, PERMUTATIONS, SEED
    )

    rng = np.random.default_rng(SEED)
    alpha_rows: list[dict[str, float | str]] = []
    for sample in retained:
        profile = counts[sample].to_numpy(dtype=np.int64)
        richness_values = []
        shannon_values = []
        for _ in range(RAREFACTION_ITERATIONS):
            rarefied = rarefy_profile(profile, RAREFACTION_DEPTH, rng)
            positive = rarefied[rarefied > 0]
            proportions = positive / positive.sum()
            richness_values.append(float(len(positive)))
            shannon_values.append(
                float(-np.sum(proportions * np.log(proportions)))
            )
        alpha_rows.append(
            {
                "sample": sample,
                "depth_cm": float(sample_depth[sample]),
                "richness": float(np.mean(richness_values)),
                "shannon": float(np.mean(shannon_values)),
            }
        )
    alpha = pd.DataFrame(alpha_rows)
    depth_alpha = (
        alpha.groupby("depth_cm", as_index=False)
        .agg(
            richness=("richness", "mean"),
            shannon=("shannon", "mean"),
            n_profiles=("sample", "size"),
        )
        .sort_values("depth_cm")
    )
    rows: list[dict[str, object]] = [
        {
            "desert": "Atacama",
            "dataset": "PRJEB39249",
            "design": "one soil pit sampled from 2.5 to 420 cm",
            "independent_unit": "sampled depth",
            "n_units": len(depth_alpha),
            "question": "community composition among three depth zones",
            "method": (
                "Euclidean PERMANOVA on top-200-genus CLR profiles; "
                f"{PERMUTATIONS} label permutations"
            ),
            "estimate_name": "pseudo_f",
            "estimate": observed_f,
            "p_value": composition_p,
            "comparison_boundary": (
                "single vertical profile; depth zones are observational and "
                "not equivalent to Empty Quarter soil positions"
            ),
        }
    ]
    for response, label in (
        ("richness", "rarefied observed richness"),
        ("shannon", "Shannon diversity"),
    ):
        result = stats.spearmanr(depth_alpha["depth_cm"], depth_alpha[response])
        rows.append(
            {
                "desert": "Atacama",
                "dataset": "PRJEB39249",
                "design": "one soil pit sampled from 2.5 to 420 cm",
                "independent_unit": "sampled depth",
                "n_units": len(depth_alpha),
                "question": f"depth versus {label}",
                "method": (
                    f"Spearman correlation after {RAREFACTION_ITERATIONS} "
                    "rarefactions per profile and averaging replicates by depth"
                ),
                "estimate_name": "rho",
                "estimate": float(result.statistic),
                "p_value": float(result.pvalue),
                "comparison_boundary": (
                    "intracellular-DNA V4 profiles from one pit; effect direction "
                    "only, not absolute diversity"
                ),
            }
        )
    audit = {
        "profiles_in_depth_map": int(len(depths)),
        "profiles_retained": int(len(retained)),
        "sampled_depths": int(len(depth_alpha)),
        "depth_min_cm": float(depth_alpha["depth_cm"].min()),
        "depth_max_cm": float(depth_alpha["depth_cm"].max()),
        "asvs": int(counts.shape[0]),
        "genera_used_for_composition": int(len(top)),
    }
    return rows, audit, depth_alpha


def format_number(value: float) -> str:
    if math.isnan(value):
        return "NA"
    if abs(value) < 0.001 and value != 0:
        return f"{value:.2e}"
    return f"{value:.3f}"


def main() -> None:
    project_root = Path(__file__).resolve().parents[2]
    staged_comparator_root = project_root / "metadata/comparators/atacama"
    repository_comparator_root = (
        project_root / "analysis/v2/RQ27_Transportability"
    )
    if staged_comparator_root.is_dir():
        gradient_default = staged_comparator_root / "gradient/atacama_per_site.csv"
        pit_default_root = staged_comparator_root / "pit"
    else:
        gradient_default = (
            repository_comparator_root
            / "atacama_gradient/atacama_per_site.csv"
        )
        pit_default_root = repository_comparator_root / "atacama_pit"
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--gradient-sites",
        type=Path,
        default=gradient_default,
    )
    parser.add_argument(
        "--pit-counts",
        type=Path,
        default=pit_default_root / "ASV_table.tsv",
    )
    parser.add_argument(
        "--pit-taxonomy",
        type=Path,
        default=pit_default_root / "ASV_tax.silva_138_2.tsv",
    )
    parser.add_argument(
        "--pit-depth-map",
        type=Path,
        default=pit_default_root / "sample_depth_map.tsv",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("analysis/v3/cross_desert_context"),
    )
    args = parser.parse_args()
    inputs = {
        "atacama_gradient_site_table": args.gradient_sites.resolve(),
        "atacama_pit_asv_table": args.pit_counts.resolve(),
        "atacama_pit_taxonomy": args.pit_taxonomy.resolve(),
        "atacama_pit_depth_map": args.pit_depth_map.resolve(),
    }
    missing = [str(path) for path in inputs.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError("Missing cross-desert inputs:\n" + "\n".join(missing))
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)

    gradient_rows, gradient_audit = analyse_gradient(inputs["atacama_gradient_site_table"])
    pit_rows, pit_audit, depth_alpha = analyse_pit(
        inputs["atacama_pit_asv_table"],
        inputs["atacama_pit_taxonomy"],
        inputs["atacama_pit_depth_map"],
    )
    statistics = pd.DataFrame(gradient_rows + pit_rows)
    statistics.to_csv(output / "comparison_statistics.tsv", sep="\t", index=False)
    depth_alpha.to_csv(output / "atacama_pit_depth_alpha.tsv", sep="\t", index=False)

    manifest = {
        "status": "contextual_comparisons_complete",
        "scope": (
            "Effect-level comparison across incompatible marker-gene surveys; "
            "no feature-table merging and no common-mechanism claim."
        ),
        "parameters": {
            "seed": SEED,
            "permutations": PERMUTATIONS,
            "rarefaction_depth": RAREFACTION_DEPTH,
            "rarefaction_iterations": RAREFACTION_ITERATIONS,
            "top_genera": TOP_GENERA,
            "pseudocount": PSEUDOCOUNT,
        },
        "cohorts": {"atacama_gradient": gradient_audit, "atacama_pit": pit_audit},
        "inputs": {
            name: {
                "path": portable_path(path, project_root),
                "sha256": sha256(path),
                "bytes": path.stat().st_size,
            }
            for name, path in sorted(inputs.items())
        },
        "software": {
            "numpy": np.__version__,
            "pandas": pd.__version__,
            "scipy": __import__("scipy").__version__,
        },
    }
    (output / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    lines = [
        "# Cross-desert quantitative context",
        "",
        "These analyses compare effect directions and study designs; they do not merge "
        "incompatible feature tables or establish a shared mechanism.",
        "",
    ]
    for row in statistics.itertuples(index=False):
        lines.append(
            f"- {row.dataset}: {row.question}; {row.estimate_name}="
            f"{format_number(float(row.estimate))}, p="
            f"{format_number(float(row.p_value))}, n={row.n_units} "
            f"{row.independent_unit}s. Boundary: {row.comparison_boundary}."
        )
    (output / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    checksum_files = [
        output / "atacama_pit_depth_alpha.tsv",
        output / "comparison_statistics.tsv",
        output / "README.md",
        output / "run_manifest.json",
    ]
    (output / "SHA256SUMS").write_text(
        "".join(f"{sha256(path)}  {path.name}\n" for path in checksum_files),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
