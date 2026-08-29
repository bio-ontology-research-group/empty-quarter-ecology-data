#!/usr/bin/env python3
"""Build bounded ecological sensitivity inputs from the Trip-5 control audit.

The primary ecology inputs remain unchanged.  This script removes the
prevalence-enriched candidate ASVs only from the 217 Trip-5 biological
profiles whose extraction-day blank mapping is frozen.  It then rebuilds the
alpha-diversity, genus-count and spatial ASV caches used by the headline
ecology analyses.  All other profiles are byte-for-value identical to the
canonical caches.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import math
import re
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.special import gammaln
from scipy.stats import spearmanr, wilcoxon


SAMPLE_RE = re.compile(
    r"^V(?P<site>\d+)(?P<position>PR|D|S)r(?P<replicate>\d+)"
)
POSITION = {"S": "Surface", "D": "Deep", "PR": "Rhizosphere"}
CONTRASTS = (
    ("Deep", "Surface"),
    ("Rhizosphere", "Surface"),
    ("Rhizosphere", "Deep"),
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def provenance_path(path: Path, root: Path, output_root: Path) -> str:
    """Return a stable package path, including for caller-selected outputs."""
    absolute = path.resolve()
    for base, prefix in ((root.resolve(), ""), (output_root.resolve(), "OUTPUT_ROOT/")):
        try:
            relative = absolute.relative_to(base)
        except ValueError:
            continue
        return prefix + relative.as_posix()
    return absolute.as_posix()


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_tsv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        raise ValueError(f"refusing to write empty table: {path}")
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(rows[0]),
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


def write_deterministic_gzip_frame(frame: pd.DataFrame, path: Path) -> None:
    """Write a gzip-compressed TSV without a timestamp or stored filename."""
    with (
        path.open("wb") as raw_handle,
        gzip.GzipFile(
            filename="", fileobj=raw_handle, mode="wb", mtime=0
        ) as gzip_handle,
        io.TextIOWrapper(gzip_handle, encoding="utf-8", newline="") as text_handle,
    ):
        frame.to_csv(text_handle, sep="\t")


def bh_fdr(values: list[float]) -> list[float]:
    array = np.asarray(values, dtype=float)
    order = np.argsort(array)
    ranked = array[order] * len(array) / (np.arange(len(array)) + 1)
    ranked = np.minimum.accumulate(ranked[::-1])[::-1]
    adjusted = np.empty(len(array), dtype=float)
    adjusted[order] = np.clip(ranked, 0.0, 1.0)
    return adjusted.tolist()


def parse_profile(profile_id: str) -> tuple[int, str]:
    match = SAMPLE_RE.match(profile_id)
    if match is None:
        raise ValueError(f"mapped Trip-5 profile has an unparseable ID: {profile_id}")
    return int(match.group("site")), POSITION[match.group("position")]


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--filtered-table",
        type=Path,
        default=root
        / "analysis/v3/control_audit/trip5_mapped_feature_table_control_filtered.tsv.gz",
    )
    parser.add_argument(
        "--calls",
        type=Path,
        default=root / "analysis/v3/control_audit/trip5_primary_contaminant_calls.tsv",
    )
    parser.add_argument(
        "--removal",
        type=Path,
        default=root / "analysis/v3/control_audit/trip5_removal_fraction_by_profile.tsv",
    )
    parser.add_argument(
        "--taxonomy",
        type=Path,
        default=root / "data/processed/taxonomy/taxon-tables/taxonomy-trips1-5.tsv",
    )
    parser.add_argument(
        "--base-alpha",
        type=Path,
        default=root / "analysis/v2/review/cache/alpha.tsv",
    )
    parser.add_argument(
        "--base-genus",
        type=Path,
        default=root / "analysis/v2/review/cache/genus_counts.tsv",
    )
    parser.add_argument(
        "--base-asv",
        type=Path,
        default=root / "analysis/v2/review/cache/asv_filt_counts.tsv",
    )
    parser.add_argument(
        "--cache-meta",
        type=Path,
        default=root / "analysis/v2/review/cache/meta.json",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=root / "analysis/v3/control_audit/sensitivity_inputs",
    )
    parser.add_argument("--chunk-size", type=int, default=2500)
    args = parser.parse_args()

    inputs = [
        args.filtered_table,
        args.calls,
        args.removal,
        args.taxonomy,
        args.base_alpha,
        args.base_genus,
        args.base_asv,
        args.cache_meta,
    ]
    missing = [str(path) for path in inputs if not path.is_file()]
    if missing:
        raise FileNotFoundError("missing required input(s): " + ", ".join(missing))
    args.output_dir.mkdir(parents=True, exist_ok=True)

    calls = read_tsv(args.calls)
    candidate_ids = {row["feature_id"] for row in calls}
    if len(candidate_ids) != len(calls):
        raise ValueError("candidate contaminant table contains duplicate feature IDs")

    removal = {
        row["profile_id"]: row
        for row in read_tsv(args.removal)
        if row["role"] == "compatible_biological_profile"
    }
    samples = sorted(removal)
    if len(samples) != 217:
        raise ValueError(f"expected 217 mapped profiles, found {len(samples)}")

    alpha = pd.read_csv(args.base_alpha, sep="\t", index_col=0)
    # Keep the literal genus label ``NA``.  Pandas otherwise converts that
    # index value to a missing value; downstream analyses deliberately drop it
    # after loading, but preserving the row here keeps the sensitivity cache
    # structurally identical to the canonical cache.
    genus = pd.read_csv(
        args.base_genus, sep="\t", index_col=0, keep_default_na=False
    )
    missing_alpha = sorted(set(samples) - set(alpha.index))
    missing_genus = sorted(set(samples) - set(genus.columns))
    if missing_alpha or missing_genus:
        raise ValueError(
            f"mapped profiles absent from caches: alpha={missing_alpha}, genus={missing_genus}"
        )

    cache_meta = json.loads(args.cache_meta.read_text(encoding="utf-8"))
    rarefaction_depth = int(cache_meta["rarefaction_depth"])
    pre_depth = alpha.loc[samples, "depth"].to_numpy(dtype=float)
    removed_reads = np.asarray(
        [float(removal[sample]["candidate_contaminant_reads"]) for sample in samples]
    )
    post_depth_expected = pre_depth - removed_reads
    if np.any(post_depth_expected <= 0):
        bad = [samples[i] for i in np.flatnonzero(post_depth_expected <= 0)]
        raise ValueError(f"candidate removal empties profiles: {bad}")

    taxonomy = pd.read_csv(args.taxonomy, sep="\t", index_col=0)
    if "Taxon" not in taxonomy:
        raise ValueError("taxonomy table lacks the Taxon column")

    def genus_name(lineage: object) -> object:
        if not isinstance(lineage, str):
            return np.nan
        fields = lineage.split(";")
        if len(fields) <= 5:
            return np.nan
        value = fields[5].strip()
        return value if value else np.nan

    genus_map = taxonomy["Taxon"].map(genus_name)
    genus_position = {str(name): i for i, name in enumerate(genus.index)}
    rebuilt_genus = np.zeros((len(genus.index), len(samples)), dtype=np.float64)
    post_depth = np.zeros(len(samples), dtype=np.float64)
    post_richness = np.zeros(len(samples), dtype=np.int64)
    post_sum_c_log_c = np.zeros(len(samples), dtype=np.float64)
    post_expected_richness = np.zeros(len(samples), dtype=np.float64)
    observed_features: set[str] = set()

    chunks = pd.read_csv(
        args.filtered_table,
        sep="\t",
        index_col=0,
        skiprows=[0],
        chunksize=args.chunk_size,
    )
    for chunk in chunks:
        if list(chunk.columns) != samples:
            raise ValueError("filtered-table profile order changed during chunked read")
        chunk.index = chunk.index.astype(str)
        observed_features.update(chunk.index)
        values = chunk.to_numpy(dtype=np.float64)
        nonzero = values > 0
        post_depth += values.sum(axis=0)
        post_richness += nonzero.sum(axis=0)
        with np.errstate(divide="ignore", invalid="ignore"):
            post_sum_c_log_c += np.where(
                nonzero, values * np.log(np.where(nonzero, values, 1.0)), 0.0
            ).sum(axis=0)

        rows, columns = np.nonzero(values)
        if rows.size:
            counts = values[rows, columns]
            totals = post_depth_expected[columns]
            remaining = totals - counts
            probability_not_observed = np.zeros(counts.shape, dtype=np.float64)
            calculable = (totals >= rarefaction_depth) & (
                remaining >= rarefaction_depth
            )
            a = (
                gammaln(remaining[calculable] + 1)
                - gammaln(remaining[calculable] - rarefaction_depth + 1)
            )
            b = (
                gammaln(totals[calculable] + 1)
                - gammaln(totals[calculable] - rarefaction_depth + 1)
            )
            probability_not_observed[calculable] = np.exp(a - b)
            eligible = totals >= rarefaction_depth
            np.add.at(
                post_expected_richness,
                columns[eligible],
                1.0 - probability_not_observed[eligible],
            )

        labels = genus_map.reindex(chunk.index).to_numpy()
        valid = pd.notna(labels)
        if valid.any():
            grouped = (
                pd.DataFrame(values[valid], index=labels[valid])
                .groupby(level=0, sort=False)
                .sum()
            )
            for name, row in grouped.iterrows():
                position = genus_position.get(str(name))
                if position is None:
                    raise ValueError(
                        f"filtered table contains genus absent from base cache: {name}"
                    )
                rebuilt_genus[position] += row.to_numpy(dtype=float)

    if not np.allclose(post_depth, post_depth_expected, rtol=0, atol=1e-6):
        differences = np.abs(post_depth - post_depth_expected)
        worst = int(np.argmax(differences))
        raise ValueError(
            f"filtered depth mismatch for {samples[worst]}: "
            f"observed={post_depth[worst]}, expected={post_depth_expected[worst]}"
        )
    if candidate_ids & observed_features:
        raise ValueError("candidate contaminant ASVs remain in filtered table")

    post_shannon = np.log(post_depth) - post_sum_c_log_c / post_depth
    post_expected_richness[post_depth < rarefaction_depth] = np.nan
    with np.errstate(divide="ignore", invalid="ignore"):
        post_pielou = post_shannon / np.log(post_expected_richness)

    adjusted_alpha = alpha.copy()
    adjusted_alpha.loc[samples, "depth"] = post_depth
    adjusted_alpha.loc[samples, "richness_raw"] = post_richness
    adjusted_alpha.loc[samples, "richness_rare"] = post_expected_richness
    adjusted_alpha.loc[samples, "shannon"] = post_shannon
    adjusted_alpha.loc[samples, "pielou"] = post_pielou
    alpha_path = args.output_dir / "alpha.tsv"
    adjusted_alpha.to_csv(alpha_path, sep="\t")

    adjusted_genus = genus.copy()
    adjusted_genus.loc[:, samples] = rebuilt_genus
    original_genus_totals = genus.loc[:, samples].sum(axis=0).to_numpy(dtype=float)
    adjusted_genus_totals = adjusted_genus.loc[:, samples].sum(axis=0).to_numpy(
        dtype=float
    )
    if np.any(adjusted_genus_totals - original_genus_totals > 1e-6):
        raise ValueError("reconstructed genus counts exceed canonical genus counts")
    genus_path = args.output_dir / "genus_counts.tsv.gz"
    write_deterministic_gzip_frame(adjusted_genus, genus_path)

    adjusted_asv = pd.read_csv(
        args.base_asv, sep="\t", index_col=0, keep_default_na=False
    )
    missing_asv_samples = sorted(set(samples) - set(adjusted_asv.columns))
    if missing_asv_samples:
        raise ValueError(
            f"mapped profiles absent from spatial ASV cache: {missing_asv_samples}"
        )
    filtered_spatial_features = sorted(candidate_ids & set(adjusted_asv.index))
    adjusted_asv.loc[filtered_spatial_features, samples] = 0.0
    asv_path = args.output_dir / "asv_filt_counts.tsv.gz"
    write_deterministic_gzip_frame(adjusted_asv, asv_path)

    profile_rows: list[dict[str, object]] = []
    pre_shannon = alpha.loc[samples, "shannon"].to_numpy(dtype=float)
    pre_richness = alpha.loc[samples, "richness_raw"].to_numpy(dtype=float)
    for i, sample in enumerate(samples):
        site, position = parse_profile(sample)
        profile_rows.append(
            {
                "profile_id": sample,
                "site": site,
                "position": position,
                "extraction_blank": removal[sample]["extraction_blank"],
                "reads_before": int(pre_depth[i]),
                "reads_after": int(post_depth[i]),
                "removed_read_fraction": f"{removed_reads[i] / pre_depth[i]:.10g}",
                "richness_before": int(pre_richness[i]),
                "richness_after": int(post_richness[i]),
                "richness_change": int(post_richness[i] - pre_richness[i]),
                "shannon_before": f"{pre_shannon[i]:.10g}",
                "shannon_after": f"{post_shannon[i]:.10g}",
                "shannon_change": f"{post_shannon[i] - pre_shannon[i]:.10g}",
            }
        )
    write_tsv(args.output_dir / "alpha_diversity_sensitivity.tsv", profile_rows)

    profile_frame = pd.DataFrame(profile_rows)
    for column in (
        "shannon_before",
        "shannon_after",
        "shannon_change",
        "removed_read_fraction",
    ):
        profile_frame[column] = pd.to_numeric(profile_frame[column])
    site_position = (
        profile_frame.groupby(["site", "position"], as_index=False)[
            ["shannon_before", "shannon_after"]
        ]
        .mean()
        .set_index(["site", "position"])
    )
    contrast_rows: list[dict[str, object]] = []
    p_values: list[float] = []
    for state in ("before", "after"):
        column = f"shannon_{state}"
        wide = site_position[column].unstack("position")
        for first, second in CONTRASTS:
            paired = wide[[first, second]].dropna()
            difference = paired[first] - paired[second]
            test = wilcoxon(difference, alternative="two-sided")
            p_values.append(float(test.pvalue))
            contrast_rows.append(
                {
                    "state": state,
                    "contrast": f"{first}-{second}",
                    "n_paired_sites": len(paired),
                    "mean_difference": f"{difference.mean():.10g}",
                    "median_difference": f"{difference.median():.10g}",
                    "wilcoxon_p": f"{test.pvalue:.10g}",
                    "bh_q_across_six_sensitivity_tests": "",
                }
            )
    for row, adjusted in zip(contrast_rows, bh_fdr(p_values), strict=True):
        row["bh_q_across_six_sensitivity_tests"] = f"{adjusted:.10g}"
    write_tsv(args.output_dir / "trip5_paired_compartment_sensitivity.tsv", contrast_rows)

    shannon_correlation = spearmanr(pre_shannon, post_shannon)
    richness_correlation = spearmanr(pre_richness, post_richness)
    summary = {
        "scope": (
            "candidate ASVs removed only from 217 Trip-5 profiles with frozen "
            "EB1-EB17 extraction-batch mappings; all other ecology profiles unchanged"
        ),
        "candidate_features": len(candidate_ids),
        "mapped_profiles": len(samples),
        "rarefaction_depth": rarefaction_depth,
        "profiles_below_rarefaction_depth_after_filter": int(
            (post_depth < rarefaction_depth).sum()
        ),
        "removed_read_fraction": {
            "pooled": float(removed_reads.sum() / pre_depth.sum()),
            "median": float(np.median(removed_reads / pre_depth)),
            "maximum": float(np.max(removed_reads / pre_depth)),
        },
        "shannon": {
            "spearman_before_after": float(shannon_correlation.statistic),
            "spearman_p": float(shannon_correlation.pvalue),
            "median_change": float(np.median(post_shannon - pre_shannon)),
            "maximum_absolute_change": float(
                np.max(np.abs(post_shannon - pre_shannon))
            ),
        },
        "raw_richness": {
            "spearman_before_after": float(richness_correlation.statistic),
            "spearman_p": float(richness_correlation.pvalue),
            "median_change": float(np.median(post_richness - pre_richness)),
            "maximum_absolute_change": float(
                np.max(np.abs(post_richness - pre_richness))
            ),
        },
        "genus_assigned_removed_reads": int(
            np.rint((original_genus_totals - adjusted_genus_totals).sum())
        ),
        "spatial_cache_candidate_features_removed": len(filtered_spatial_features),
        "outputs": {
            "alpha": provenance_path(alpha_path, root, args.output_dir),
            "genus": provenance_path(genus_path, root, args.output_dir),
            "asv": provenance_path(asv_path, root, args.output_dir),
        },
        "input_sha256": {
            provenance_path(path, root, args.output_dir): sha256(path)
            for path in inputs
        },
    }
    for output_path in (alpha_path, genus_path, asv_path):
        summary.setdefault("output_sha256", {})[
            provenance_path(output_path, root, args.output_dir)
        ] = sha256(output_path)
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
