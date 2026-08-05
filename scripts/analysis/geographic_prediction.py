#!/usr/bin/env python3
"""Collection-order alias audit and leakage-free geographic prediction.

Two questions are answered here, both about the manuscript's strongest
result -- the transect composition gradient.

1.  *Design boundary.*  Every campaign traversed the transect in one
    direction, so elapsed collection time and transect position may be
    aliased.  The alias audit quantifies that directly from the field
    samplesheets, which carry a date and a clock time per site visit.

2.  *Out-of-sample skill.*  The staged spatial analysis reports an
    in-sample partial R-squared with whole-site permutations and campaign
    omission.  Campaign omission is an influence analysis; it does not show
    that a gradient learned elsewhere predicts unseen sites.  This module
    holds out contiguous transect blocks and whole campaigns together,
    selects taxa inside training folds only, and scores predictions on
    within-compartment differences between held-out sites so that no
    held-out campaign intercept is ever estimated.

Two nulls are reported.  Whole-site coordinate relabelling reruns the
entire outer validation, including training-fold feature selection, under
permuted site coordinates.  Because an unrestricted site permutation does
not preserve spatial autocorrelation, a cyclic-shift/reflection null on the
ordered transect is reported alongside it and is the stricter of the two.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import pandas as pd
from scipy import stats

from spatial_turnover_rescue import (
    load_coordinates,
    load_grouped_counts,
    sha256_file,
    write_tsv,
)

CAMPAIGN_SAMPLESHEETS = {
    1: "trip1-2023.tsv",
    2: "trip2-2023.tsv",
    3: "trip3-2024.tsv",
    4: "trip4-2024.tsv",
    5: "trip5-2025.tsv",
}
# Only campaigns 1, 3 and 4 traversed all 60 core sites; campaign 2 covered
# eight sites at one end of the route and campaign 5 is partial.  The primary
# campaign-generalization population is therefore restricted, with the full
# five-campaign fit retained as a sensitivity.
PRIMARY_CAMPAIGNS = (1, 3, 4)
ALL_CAMPAIGNS = (1, 2, 3, 4, 5)
N_BLOCKS = 6


def provenance_path(path: Path, root: Path) -> str:
    """Return a stable project-relative path without resolving symlinks."""
    candidate = path if path.is_absolute() else root / path
    try:
        return candidate.absolute().relative_to(root.absolute()).as_posix()
    except ValueError:
        return candidate.absolute().as_posix()


def load_collection_order(root: Path) -> pd.DataFrame:
    """Parse site visit timestamps from the field samplesheets.

    The samplesheets are read positionally on their first three columns.
    ``trip2-2023.tsv`` carries a nine-name header over ten-field data rows
    (the ``pressure`` column is present in the data but absent from the
    header), which makes a name-based read silently promote ``site`` to the
    frame index.  Reading positionally, after asserting that the header's
    first three names are ``site``, ``date`` and ``time``, keeps every
    campaign usable without editing the source samplesheet.
    """
    rows = []
    for campaign, filename in CAMPAIGN_SAMPLESHEETS.items():
        path = root / "data" / "metadata" / "samplesheets" / filename
        if not path.exists():
            raise FileNotFoundError(
                f"Collection-order audit requires {path}; it is absent."
            )
        header = path.read_text(encoding="utf-8").split("\n", 1)[0].split("\t")
        if [name.strip() for name in header[:3]] != ["site", "date", "time"]:
            raise ValueError(
                f"{path} does not start with site/date/time columns: {header[:3]}"
            )
        frame = pd.read_csv(
            path,
            sep="\t",
            dtype=str,
            header=None,
            skiprows=1,
            usecols=[0, 1, 2],
            names=["site", "date", "time"],
            index_col=False,
        )
        frame = frame.dropna(subset=["site", "date", "time"])
        frame = frame[frame["site"].astype(str).str.fullmatch(r"[0-9]+")].copy()
        frame["site"] = frame["site"].astype(int)
        frame = frame[frame["site"].between(1, 60)]
        stamp = pd.to_datetime(
            frame["date"].str.strip() + " " + frame["time"].str.strip(),
            format="%d/%m/%Y %H:%M",
            errors="coerce",
        )
        frame = frame.assign(collected_at=stamp).dropna(subset=["collected_at"])
        frame = frame.sort_values("collected_at")
        for row in frame.itertuples():
            rows.append(
                {
                    "campaign": campaign,
                    "site": int(row.site),
                    "collected_at": row.collected_at,
                }
            )
    return pd.DataFrame(rows)


def collection_order_alias(
    order: pd.DataFrame, coordinates: pd.DataFrame
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Correlate elapsed collection time with transect position per campaign."""
    transect = coordinates.set_index("site")["transect_km"]
    rows = []
    for campaign, part in order.groupby("campaign", sort=True):
        part = part.drop_duplicates(subset="site", keep="first").copy()
        part = part[part["site"].isin(transect.index)]
        if len(part) < 3:
            continue
        elapsed = (
            part["collected_at"] - part["collected_at"].min()
        ).dt.total_seconds() / 3600.0
        position = transect.loc[part["site"]].to_numpy(dtype=float)
        spearman = stats.spearmanr(elapsed.to_numpy(), position)
        pearson = stats.pearsonr(elapsed.to_numpy(), position)
        rows.append(
            {
                "campaign": int(campaign),
                "n_sites_with_timestamp": int(len(part)),
                "first_visit": part["collected_at"].min().isoformat(),
                "last_visit": part["collected_at"].max().isoformat(),
                "elapsed_hours": float(elapsed.max()),
                "spearman_rho_elapsed_vs_transect": float(spearman.statistic),
                "spearman_p": float(spearman.pvalue),
                "pearson_r_elapsed_vs_transect": float(pearson.statistic),
                "abs_spearman_rho": float(abs(spearman.statistic)),
            }
        )
    if not rows:
        raise ValueError("No campaign yielded usable collection timestamps")
    magnitudes = [row["abs_spearman_rho"] for row in rows]
    summary = {
        "campaigns_audited": len(rows),
        "min_abs_spearman_rho": float(min(magnitudes)),
        "max_abs_spearman_rho": float(max(magnitudes)),
        "campaigns_with_abs_rho_at_least_0_99": int(
            sum(value >= 0.99 for value in magnitudes)
        ),
        "alias_status": (
            "collection_order_aliased_with_transect_position"
            if min(magnitudes) >= 0.95
            else "collection_order_partially_aliased"
        ),
    }
    return rows, summary


def contiguous_blocks(order_index: np.ndarray, n_blocks: int) -> np.ndarray:
    """Assign each ordered position to one of ``n_blocks`` contiguous blocks."""
    return np.floor(
        np.arange(len(order_index)) * n_blocks / len(order_index)
    ).astype(int)


def training_taxa(
    counts: pd.DataFrame,
    metadata: pd.DataFrame,
    training_mask: np.ndarray,
    prevalence_threshold: float,
    taxon_count: int,
) -> list[str]:
    """Rank taxa using training groups only, so selection cannot leak."""
    matrix = counts.loc[:, training_mask]
    prevalence = (matrix > 0).mean(axis=1)
    eligible = prevalence[prevalence >= prevalence_threshold].index
    if len(eligible) < taxon_count:
        raise ValueError(
            f"Training fold retained only {len(eligible)} eligible taxa; "
            f"{taxon_count} are required."
        )
    relative = matrix.div(matrix.sum(axis=0), axis=1)
    ranking = (
        relative.loc[eligible]
        .mean(axis=1)
        .sort_values(ascending=False, kind="mergesort")
    )
    return ranking.index.tolist()[:taxon_count]


def clr_matrix(
    counts: pd.DataFrame, taxa: Sequence[str], pseudocount: float
) -> np.ndarray:
    matrix = counts.loc[list(taxa)].T.to_numpy(dtype=float)
    logged = np.log(matrix + pseudocount)
    return logged - logged.mean(axis=1, keepdims=True)


def fold_skill(
    clr: np.ndarray,
    metadata: pd.DataFrame,
    training_mask: np.ndarray,
    holdout_mask: np.ndarray,
    site_position: dict[int, float],
) -> tuple[float, float, int] | None:
    """Fit the quadratic transect trend on training groups and score pairs.

    Returns ``(sse, sst, n_pairs)`` for the held-out fold, or ``None`` when
    the fold contains no scorable within-campaign, within-compartment site
    pair.
    """
    train_meta = metadata.loc[training_mask]
    train_values = clr[training_mask]
    positions = train_meta["site"].map(site_position).to_numpy(dtype=float)
    mean = float(positions.mean())
    scale = float(positions.std(ddof=1))
    if not np.isfinite(scale) or scale <= 0:
        return None
    standardized = (positions - mean) / scale

    # Campaign-by-compartment intercepts are nuisance parameters; they are
    # removed by centring the training response within each such stratum,
    # which is exactly what the held-out difference scoring assumes.
    centred = train_values.copy()
    strata = train_meta.groupby(["campaign", "compartment"], sort=True).indices
    design_linear = standardized.copy()
    design_quadratic = standardized**2
    for indices in strata.values():
        index = np.asarray(indices, dtype=int)
        centred[index] -= centred[index].mean(axis=0, keepdims=True)
        design_linear[index] -= design_linear[index].mean()
        design_quadratic[index] -= design_quadratic[index].mean()
    design = np.column_stack([design_linear, design_quadratic])
    coefficients = np.linalg.lstsq(design, centred, rcond=None)[0]

    hold_meta = metadata.loc[holdout_mask].reset_index(drop=True)
    hold_values = clr[holdout_mask]
    sse = 0.0
    sst = 0.0
    n_pairs = 0
    for _, indices in hold_meta.groupby(
        ["campaign", "compartment"], sort=True
    ).groups.items():
        index = np.asarray(list(indices), dtype=int)
        if len(index) < 2:
            continue
        sites = hold_meta.loc[index, "site"].to_numpy()
        z = np.array(
            [(site_position[int(site)] - mean) / scale for site in sites]
        )
        for a in range(len(index)):
            for b in range(a + 1, len(index)):
                if sites[a] == sites[b]:
                    continue
                observed = hold_values[index[a]] - hold_values[index[b]]
                predicted = (
                    coefficients[0] * (z[a] - z[b])
                    + coefficients[1] * (z[a] ** 2 - z[b] ** 2)
                )
                sse += float(np.square(observed - predicted).sum())
                sst += float(np.square(observed).sum())
                n_pairs += 1
    if n_pairs == 0 or sst <= 0:
        return None
    return sse, sst, n_pairs


def cross_validate(
    counts: pd.DataFrame,
    metadata: pd.DataFrame,
    site_position: dict[int, float],
    campaigns: Sequence[int],
    prevalence_threshold: float,
    taxon_count: int,
    pseudocount: float,
    n_blocks: int,
    collect_folds: bool = False,
) -> tuple[float, float, list[dict[str, Any]]]:
    """Contiguous-block by campaign cross-validation; returns pooled skill."""
    ordered_sites = [
        site for site, _ in sorted(site_position.items(), key=lambda kv: kv[1])
    ]
    block_of = {
        site: int(block)
        for site, block in zip(
            ordered_sites, contiguous_blocks(np.arange(len(ordered_sites)), n_blocks)
        )
    }
    campaign_values = metadata["campaign"].to_numpy()
    site_values = metadata["site"].to_numpy()
    block_values = np.array([block_of[int(site)] for site in site_values])
    in_scope = np.isin(campaign_values, list(campaigns))

    fold_rows: list[dict[str, Any]] = []
    fold_skills: list[float] = []
    pooled_sse = 0.0
    pooled_sst = 0.0
    for campaign in campaigns:
        for block in range(n_blocks):
            holdout = in_scope & (campaign_values == campaign) & (
                block_values == block
            )
            if holdout.sum() < 2:
                continue
            training = in_scope & (campaign_values != campaign) & (
                block_values != block
            )
            if training.sum() < 20:
                continue
            try:
                taxa = training_taxa(
                    counts,
                    metadata,
                    training,
                    prevalence_threshold,
                    taxon_count,
                )
            except ValueError:
                continue
            clr = clr_matrix(counts, taxa, pseudocount)
            scored = fold_skill(
                clr, metadata, training, holdout, site_position
            )
            if scored is None:
                continue
            sse, sst, n_pairs = scored
            skill = 1.0 - sse / sst
            fold_skills.append(skill)
            pooled_sse += sse
            pooled_sst += sst
            if collect_folds:
                fold_rows.append(
                    {
                        "held_out_campaign": int(campaign),
                        "held_out_block": int(block),
                        "n_training_groups": int(training.sum()),
                        "n_heldout_groups": int(holdout.sum()),
                        "n_scored_pairs": int(n_pairs),
                        "fold_skill_r2": skill,
                    }
                )
    if not fold_skills:
        raise ValueError("No estimable cross-validation fold")
    equal_weight = float(np.mean(fold_skills))
    pooled = 1.0 - pooled_sse / pooled_sst
    return equal_weight, pooled, fold_rows


def site_level_block_cv(
    counts: pd.DataFrame,
    metadata: pd.DataFrame,
    site_position: dict[int, float],
    campaigns: Sequence[int],
    prevalence_threshold: float,
    taxon_count: int,
    pseudocount: float,
    n_blocks: int,
    collect_folds: bool = False,
) -> tuple[float, list[dict[str, Any]]]:
    """Contiguous-block holdout on the site-averaged response.

    This arm matches the estimand of the staged in-sample spatial model:
    campaign-and-compartment-centred CLR values averaged to one vector per
    site.  Centring means and taxon selection come from training groups
    only, and the out-of-sample denominator is taken about the training
    mean, so a held-out block contributes nothing to its own baseline.
    """
    ordered_sites = [
        site for site, _ in sorted(site_position.items(), key=lambda kv: kv[1])
    ]
    block_of = {
        site: int(block)
        for site, block in zip(
            ordered_sites,
            contiguous_blocks(np.arange(len(ordered_sites)), n_blocks),
        )
    }
    campaign_values = metadata["campaign"].to_numpy()
    site_values = metadata["site"].to_numpy()
    block_values = np.array([block_of[int(site)] for site in site_values])
    in_scope = np.isin(campaign_values, list(campaigns))

    fold_rows: list[dict[str, Any]] = []
    sse_total = 0.0
    sst_total = 0.0
    for block in range(n_blocks):
        training = in_scope & (block_values != block)
        holdout = in_scope & (block_values == block)
        if holdout.sum() < 2 or training.sum() < 20:
            continue
        try:
            taxa = training_taxa(
                counts, metadata, training, prevalence_threshold, taxon_count
            )
        except ValueError:
            continue
        clr = clr_matrix(counts, taxa, pseudocount)
        centred = clr.copy()
        compartment_values = metadata["compartment"].to_numpy()
        # Apply training-derived stratum means to every group, including
        # held-out ones, so no held-out observation informs its own centre.
        strata = sorted(
            {
                (int(campaign), str(compartment))
                for campaign, compartment in zip(
                    campaign_values[training], compartment_values[training]
                )
            }
        )
        for campaign, compartment in strata:
            same_all = (campaign_values == campaign) & (
                compartment_values == compartment
            )
            centre = centred[same_all & training].mean(axis=0, keepdims=True)
            centred[same_all] -= centre
        site_vectors: dict[int, np.ndarray] = {}
        site_is_training: dict[int, bool] = {}
        for site in np.unique(site_values[in_scope]):
            rows_for_site = in_scope & (site_values == site)
            site_vectors[int(site)] = centred[rows_for_site].mean(axis=0)
            site_is_training[int(site)] = bool(block_of[int(site)] != block)
        train_sites = [s for s, flag in site_is_training.items() if flag]
        hold_sites = [s for s, flag in site_is_training.items() if not flag]
        if len(train_sites) < 5 or len(hold_sites) < 2:
            continue
        train_positions = np.array(
            [site_position[s] for s in train_sites], dtype=float
        )
        mean = float(train_positions.mean())
        scale = float(train_positions.std(ddof=1))
        z_train = (train_positions - mean) / scale
        design_train = np.column_stack(
            [np.ones(len(z_train)), z_train, z_train**2]
        )
        y_train = np.vstack([site_vectors[s] for s in train_sites])
        coefficients = np.linalg.lstsq(design_train, y_train, rcond=None)[0]
        baseline = y_train.mean(axis=0)
        z_hold = (
            np.array([site_position[s] for s in hold_sites], dtype=float) - mean
        ) / scale
        design_hold = np.column_stack(
            [np.ones(len(z_hold)), z_hold, z_hold**2]
        )
        y_hold = np.vstack([site_vectors[s] for s in hold_sites])
        predicted = design_hold @ coefficients
        sse = float(np.square(y_hold - predicted).sum())
        sst = float(np.square(y_hold - baseline).sum())
        if sst <= 0:
            continue
        sse_total += sse
        sst_total += sst
        if collect_folds:
            fold_rows.append(
                {
                    "held_out_block": int(block),
                    "n_training_sites": len(train_sites),
                    "n_heldout_sites": len(hold_sites),
                    "n_training_groups": int(training.sum()),
                    "extrapolation_block": block in (0, n_blocks - 1),
                    "fold_skill_r2": 1.0 - sse / sst,
                }
            )
    if sst_total <= 0:
        raise ValueError("No estimable site-level block fold")
    return 1.0 - sse_total / sst_total, fold_rows


def cyclic_reflection_maps(ordered_sites: Sequence[int]) -> list[dict[int, int]]:
    """All non-identity cyclic shifts and reflections of the ordered route."""
    n = len(ordered_sites)
    maps = []
    for reflected in (False, True):
        base = list(ordered_sites[::-1]) if reflected else list(ordered_sites)
        for shift in range(n):
            rotated = base[shift:] + base[:shift]
            mapping = {
                site: rotated[index]
                for index, site in enumerate(ordered_sites)
            }
            if all(key == value for key, value in mapping.items()):
                continue
            maps.append(mapping)
    return maps


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--project-root", type=Path, default=Path(__file__).resolve().parents[2]
    )
    parser.add_argument("--counts", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--minimum-group-reads", type=int, default=2000)
    parser.add_argument("--prevalence", type=float, default=0.20)
    parser.add_argument("--pseudocount", type=float, default=0.5)
    parser.add_argument("--taxon-count", type=int, default=200)
    parser.add_argument("--site-permutations", type=int, default=499)
    parser.add_argument("--seed", type=int, default=20260728)
    args = parser.parse_args()

    root = args.project_root.resolve()
    counts_path = args.counts or (
        root / "analysis" / "v2" / "review" / "cache" / "genus_counts.tsv"
    )
    if not counts_path.exists():
        raise FileNotFoundError(
            f"Geographic prediction requires the grouped genus cache at "
            f"{counts_path}; it is absent."
        )
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)

    coordinates = load_coordinates(root)
    order = load_collection_order(root)
    alias_rows, alias_summary = collection_order_alias(order, coordinates)
    write_tsv(
        output / "collection_order_alias.tsv",
        alias_rows,
        [
            "campaign",
            "n_sites_with_timestamp",
            "first_visit",
            "last_visit",
            "elapsed_hours",
            "spearman_rho_elapsed_vs_transect",
            "spearman_p",
            "pearson_r_elapsed_vs_transect",
            "abs_spearman_rho",
        ],
    )

    counts, metadata, input_info = load_grouped_counts(
        counts_path, args.minimum_group_reads
    )
    site_position = {
        int(row.site): float(row.transect_km)
        for row in coordinates.itertuples()
    }
    ordered_sites = [
        site for site, _ in sorted(site_position.items(), key=lambda kv: kv[1])
    ]

    observed_equal, observed_pooled, fold_rows = cross_validate(
        counts,
        metadata,
        site_position,
        PRIMARY_CAMPAIGNS,
        args.prevalence,
        args.taxon_count,
        args.pseudocount,
        N_BLOCKS,
        collect_folds=True,
    )
    write_tsv(
        output / "prediction_folds.tsv",
        fold_rows,
        [
            "held_out_campaign",
            "held_out_block",
            "n_training_groups",
            "n_heldout_groups",
            "n_scored_pairs",
            "fold_skill_r2",
        ],
    )

    sensitivity_equal, sensitivity_pooled, _ = cross_validate(
        counts,
        metadata,
        site_position,
        ALL_CAMPAIGNS,
        args.prevalence,
        args.taxon_count,
        args.pseudocount,
        N_BLOCKS,
    )

    observed_site_level, site_fold_rows = site_level_block_cv(
        counts,
        metadata,
        site_position,
        ALL_CAMPAIGNS,
        args.prevalence,
        args.taxon_count,
        args.pseudocount,
        N_BLOCKS,
        collect_folds=True,
    )
    write_tsv(
        output / "site_level_block_folds.tsv",
        site_fold_rows,
        [
            "held_out_block",
            "n_training_sites",
            "n_heldout_sites",
            "n_training_groups",
            "extrapolation_block",
            "fold_skill_r2",
        ],
    )

    def evaluate(mapping: dict[int, float]) -> tuple[float | None, float | None]:
        try:
            group_skill, _, _ = cross_validate(
                counts,
                metadata,
                mapping,
                PRIMARY_CAMPAIGNS,
                args.prevalence,
                args.taxon_count,
                args.pseudocount,
                N_BLOCKS,
            )
        except ValueError:
            group_skill = None
        try:
            site_skill, _ = site_level_block_cv(
                counts,
                metadata,
                mapping,
                ALL_CAMPAIGNS,
                args.prevalence,
                args.taxon_count,
                args.pseudocount,
                N_BLOCKS,
            )
        except ValueError:
            site_skill = None
        return group_skill, site_skill

    rng = np.random.default_rng(args.seed)
    sites = np.array(ordered_sites)
    positions = np.array([site_position[site] for site in sites])
    null_draws: dict[str, dict[str, list[float]]] = {
        "whole_site_relabelling": {"group": [], "site": []},
        "cyclic_shift_reflection": {"group": [], "site": []},
    }
    for _ in range(args.site_permutations):
        permuted = rng.permutation(len(sites))
        mapping = {
            int(site): float(positions[permuted[index]])
            for index, site in enumerate(sites)
        }
        group_skill, site_skill = evaluate(mapping)
        if group_skill is not None:
            null_draws["whole_site_relabelling"]["group"].append(group_skill)
        if site_skill is not None:
            null_draws["whole_site_relabelling"]["site"].append(site_skill)
    for mapping_sites in cyclic_reflection_maps(ordered_sites):
        relabelled = {
            int(site): float(site_position[mapping_sites[site]])
            for site in ordered_sites
        }
        group_skill, site_skill = evaluate(relabelled)
        if group_skill is not None:
            null_draws["cyclic_shift_reflection"]["group"].append(group_skill)
        if site_skill is not None:
            null_draws["cyclic_shift_reflection"]["site"].append(site_skill)

    null_rows = []
    for null_name, draws in null_draws.items():
        for arm, observed in (
            ("group_level_campaign_by_block", observed_equal),
            ("site_level_block", observed_site_level),
        ):
            key = "group" if arm.startswith("group") else "site"
            array = np.asarray(draws[key], dtype=float)
            if array.size == 0:
                continue
            p_value = (1 + int(np.sum(array >= observed))) / (array.size + 1)
            null_rows.append(
                {
                    "arm": arm,
                    "null": null_name,
                    "n_maps": int(array.size),
                    "observed_skill": observed,
                    "null_median_skill": float(np.median(array)),
                    "null_p95_skill": float(np.quantile(array, 0.95)),
                    "null_max_skill": float(array.max()),
                    "p_value": float(p_value),
                }
            )
    write_tsv(
        output / "prediction_nulls.tsv",
        null_rows,
        [
            "arm",
            "null",
            "n_maps",
            "observed_skill",
            "null_median_skill",
            "null_p95_skill",
            "null_max_skill",
            "p_value",
        ],
    )

    p_by_null = {
        f"{row['arm']}::{row['null']}": row["p_value"] for row in null_rows
    }
    site_ps = [
        row["p_value"] for row in null_rows if row["arm"] == "site_level_block"
    ]
    group_ps = [
        row["p_value"]
        for row in null_rows
        if row["arm"] == "group_level_campaign_by_block"
    ]
    strict_p = max(site_ps) if site_ps else 1.0
    strict_group_p = max(group_ps) if group_ps else 1.0
    positive_folds = sum(row["fold_skill_r2"] > 0 for row in fold_rows)
    positive_site_folds = sum(
        row["fold_skill_r2"] > 0 for row in site_fold_rows
    )
    # The requested design is a contiguous site block AND a whole campaign
    # held out together.  That is the group-level arm, and it alone decides
    # the overall status.  The site-block-only arm keeps the same campaigns
    # on both sides of the split, so it cannot answer the campaign-transport
    # question and is reported as a sensitivity.
    joint_supported = bool(
        observed_equal > 0
        and positive_folds == len(fold_rows)
        and strict_group_p < 0.05
    )
    site_block_supported = bool(
        observed_site_level > 0
        and positive_site_folds == len(site_fold_rows)
        and strict_p < 0.05
    )
    joint_sentence = (
        "The primary test holds out a whole campaign and a contiguous "
        "transect block together and scores within-compartment differences "
        "between held-out sites. It "
        + (
            "supported cross-campaign, cross-block transport of the transect "
            f"gradient (equal-weight R2 {observed_equal:.4f}, pooled "
            f"{observed_pooled:.4f}, {positive_folds}/{len(fold_rows)} folds "
            f"positive, strictest null p = {strict_group_p:.4g})."
            if joint_supported
            else "did not support cross-campaign, cross-block transport of "
            f"the transect gradient (equal-weight R2 {observed_equal:.4f}, "
            f"pooled {observed_pooled:.4f}, {positive_folds}/{len(fold_rows)} "
            f"folds positive, strictest null p = {strict_group_p:.4g})."
        )
    )
    site_sentence = (
        "As a sensitivity, holding out a contiguous site block alone while "
        "keeping the same campaigns on both sides of the split "
        + (
            "did predict the site-averaged composition of the held-out block "
            f"(out-of-block R2 {observed_site_level:.4f}, "
            f"{positive_site_folds}/{len(site_fold_rows)} blocks positive, "
            f"strictest null p = {strict_p:.4g}). This sensitivity does not "
            "hold out a campaign and therefore does not demonstrate transport "
            "to an unseen campaign."
            if site_block_supported
            else "also failed "
            f"(out-of-block R2 {observed_site_level:.4f}, strictest null "
            f"p = {strict_p:.4g})."
        )
    )
    if joint_supported and site_block_supported:
        status = "joint_campaign_block_supported"
    elif joint_supported:
        status = "joint_campaign_block_supported_site_block_sensitivity_not_supported"
    elif site_block_supported:
        status = (
            "joint_campaign_block_not_supported_"
            "site_block_sensitivity_supported"
        )
    else:
        status = "joint_campaign_block_and_site_block_both_not_supported"
    verdict = {
        "schema_version": "1.1",
        "status": status,
        "primary_arm": "group_level_campaign_by_block",
        "primary_arm_supported": joint_supported,
        "sensitivity_arm": "site_level_block",
        "sensitivity_arm_supported": site_block_supported,
        "arm_definitions": {
            "group_level_campaign_by_block": (
                "Requested design: a whole campaign and a contiguous transect "
                "block are excluded together; taxa are selected inside the "
                "training fold only; scoring uses within-compartment CLR "
                "differences between held-out sites, so no held-out campaign "
                "intercept is ever estimated."
            ),
            "site_level_block": (
                "Sensitivity only: a contiguous site block is excluded, but "
                "every campaign remains on both sides of the split, so this "
                "arm cannot test transport to an unseen campaign."
            ),
        },
        "collection_order_alias": alias_summary,
        "primary_campaigns": list(PRIMARY_CAMPAIGNS),
        "n_blocks": N_BLOCKS,
        "group_level_equal_weight_skill": observed_equal,
        "group_level_pooled_skill": observed_pooled,
        "n_group_level_folds": len(fold_rows),
        "n_group_level_folds_with_positive_skill": int(positive_folds),
        "site_level_block_skill": observed_site_level,
        "n_site_level_folds": len(site_fold_rows),
        "n_site_level_folds_with_positive_skill": int(positive_site_folds),
        "all_campaign_group_level_equal_weight_skill": sensitivity_equal,
        "all_campaign_group_level_pooled_skill": sensitivity_pooled,
        "null_p_values": p_by_null,
        "strictest_group_level_null_p_value": strict_group_p,
        "strictest_site_level_null_p_value": strict_p,
        "permitted_wording": f"{joint_sentence} {site_sentence}",
        "prohibited_wording": (
            "Do not report the site-block-only sensitivity as the geographic "
            "prediction result, and do not describe geographic prediction as "
            "succeeding: the requested campaign-plus-block design is the "
            "primary arm and it is not supported. Do not describe any "
            "out-of-block skill as evidence for a geographic driver. Elapsed "
            "collection time and transect position are aliased in every "
            "campaign, so a repeated pattern cannot be separated from a "
            "repeated collection order or from order-dependent instrument "
            "effects."
        ),
        "input": {
            **input_info,
            "counts_path": provenance_path(counts_path, root),
            "counts_sha256": sha256_file(counts_path),
            "prevalence_threshold": args.prevalence,
            "pseudocount": args.pseudocount,
            "taxon_count": args.taxon_count,
            "site_permutations": args.site_permutations,
            "seed": args.seed,
        },
    }
    (output / "claim_verdict.json").write_text(
        json.dumps(verdict, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    readme = [
        "# Geographic prediction and collection-order alias",
        "",
        f"**Status: `{status}`**",
        "",
        "## Primary arm — whole campaign and contiguous block held out together",
        "",
        "This is the requested leakage-free design: a whole campaign and a "
        "contiguous transect block are excluded together, taxa are selected "
        "inside the training fold only, and scoring uses within-compartment "
        "CLR differences between held-out sites so that no held-out campaign "
        "intercept is estimated.",
        "",
        f"- Supported: **{joint_supported}**",
        f"- Equal-weight cross-validated R2: {observed_equal:.4f}",
        f"- Pooled cross-validated R2: {observed_pooled:.4f}",
        f"- Folds with positive skill: {positive_folds}/{len(fold_rows)}",
        f"- Strictest null p value: {strict_group_p:.4g}",
        "",
        "## Sensitivity arm — contiguous site block only",
        "",
        "Every campaign remains on both sides of this split, so it cannot "
        "test transport to an unseen campaign. It does not determine the "
        "status above.",
        "",
        f"- Supported: **{site_block_supported}**",
        f"- Out-of-block R2: {observed_site_level:.4f}",
        f"- Blocks with positive skill: "
        f"{positive_site_folds}/{len(site_fold_rows)}",
        f"- Strictest null p value: {strict_p:.4g}",
        "",
        "## Collection-order alias",
        "",
        f"- Campaigns audited: {alias_summary['campaigns_audited']}",
        "- Absolute Spearman correlation between elapsed collection time and "
        f"transect position: {alias_summary['min_abs_spearman_rho']:.4f} to "
        f"{alias_summary['max_abs_spearman_rho']:.4f}",
        f"- Status: {alias_summary['alias_status']}",
        "",
        "## Permitted and prohibited wording",
        "",
        verdict["permitted_wording"],
        "",
        verdict["prohibited_wording"],
        "",
        "Evidence files: `collection_order_alias.tsv`, `prediction_folds.tsv`,",
        "`site_level_block_folds.tsv`, `prediction_nulls.tsv`,",
        "`claim_verdict.json`.",
        "",
    ]
    (output / "README.md").write_text("\n".join(readme), encoding="utf-8")

    digests = []
    for path in sorted(output.glob("*")):
        if path.name == "SHA256SUMS" or path.is_dir():
            continue
        digests.append(f"{sha256_file(path)}  {path.name}")
    (output / "SHA256SUMS").write_text("\n".join(digests) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
