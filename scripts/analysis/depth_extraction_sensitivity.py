#!/usr/bin/env python3
"""Depth and extraction-protocol sensitivity for the alpha-diversity claims.

The canonical paired analysis in ``claim_rescue.py`` contrasts Shannon
diversity between sampling positions without adjusting for sequencing depth or
for the recorded DNA extraction protocol.  This script re-fits those contrasts
after both adjustments and records exactly how much extraction metadata could
be recovered.

Extraction metadata are incomplete and partly confounded with campaign, so the
output is a robustness analysis, not an identified batch correction.  Campaign,
processing context and missing metadata remain coupled and the script must not
be described as removing laboratory batch effects.

Steps:

1. rebuild the campaign x site x position table from the canonical alpha
   cache, keeping the core sites 1--60 used for repeated-campaign inference;
2. join the release ledger by (campaign, profile identifier), with a declared
   Trip-5 suffix fallback for the O/T/R/RE extraction variants, and report the
   join coverage, missingness and ambiguous mappings;
3. fit the canonical campaign-by-position site-clustered GEE without and with
   log sequencing depth, plus the additive models used for the reported
   contrasts;
4. add the prespecified extraction sensitivities (kit as recorded with an
   explicit missing category, complete cases only, and protocol-matched pairs);
5. recompute campaign-averaged paired contrasts on depth-adjusted Shannon with
   the existing site bootstrap and Benjamini-Hochberg family; and
6. emit a machine-readable verdict for the compartment wording.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd
import patsy
import statsmodels.formula.api as smf
from scipy import stats
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
PRIMARY_CONTRAST = "Rhizosphere-Deep"
SECONDARY_CONTRAST = "Rhizosphere-Surface"
PROFILE_RE = re.compile(r"^e\d+_")
TRIP5_SUFFIX_RE = re.compile(r"(RE|R|O|T)$")
NOT_RECORDED = "not_recorded"
AMBIGUOUS = "ambiguous_suffix_mapping"
MIXED = "mixed_within_group"
TYPE_TERM = 'C(Type, Treatment(reference="Surface"))'


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
                if value is None or (
                    isinstance(value, float) and not math.isfinite(value)
                ):
                    formatted[column] = ""
                elif isinstance(value, bool):
                    formatted[column] = "true" if value else "false"
                elif isinstance(value, float):
                    formatted[column] = f"{value:.10g}"
                else:
                    formatted[column] = value
            writer.writerow(formatted)


def bh_fdr(values: Sequence[float]) -> np.ndarray:
    array = np.asarray(list(values), dtype=float)
    if array.size == 0:
        return array
    order = np.argsort(array)
    ranked = array[order] * array.size / (np.arange(array.size) + 1)
    ranked = np.minimum.accumulate(ranked[::-1])[::-1]
    adjusted = np.empty(array.size)
    adjusted[order] = np.clip(ranked, 0, 1)
    return adjusted


def load_alpha(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, sep="\t", index_col=0)
    required = {"Trip", "Site", "Type", "depth", "shannon"}
    missing = required - set(frame)
    if missing:
        raise ValueError(f"Alpha table is missing columns: {sorted(missing)}")
    frame = frame[frame["Trip"].between(1, 5)].copy()
    frame["profile_id"] = frame.index.astype(str)
    frame["specimen_id"] = frame["profile_id"].str.replace(
        PROFILE_RE, "", regex=True
    )
    frame["Trip"] = frame["Trip"].astype(int)
    frame["Site"] = frame["Site"].astype(int)
    frame["Type"] = frame["Type"].replace({"Rhizo": "Rhizosphere"})
    frame = frame[frame["Type"].isin(POSITIONS)]
    return frame.reset_index(drop=True)


def load_extraction_ledger(path: Path) -> pd.DataFrame:
    ledger = pd.read_csv(path, sep="\t", dtype=str)
    ledger = ledger[ledger["is_control"].str.lower() != "true"].copy()
    ledger["Trip"] = (
        ledger["trip"].str.replace("Trip", "", regex=False).astype(int)
    )
    ledger["dna_kit"] = ledger["dna_kit"].fillna("").str.strip()
    duplicated = ledger.duplicated(["Trip", "sample_id"], keep=False)
    if duplicated.any():
        raise ValueError(
            "Non-control ledger rows are not unique per (campaign, sample): "
            f"{sorted(set(ledger.loc[duplicated, 'sample_id']))[:10]}"
        )
    return ledger[["Trip", "sample_id", "dna_kit"]]


def join_extraction(
    alpha: pd.DataFrame,
    ledger: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Attach the recorded extraction kit to each sequencing profile."""
    lookup = {
        (int(row.Trip), str(row.sample_id)): str(row.dna_kit)
        for row in ledger.itertuples()
    }
    resolutions: list[str] = []
    kits: list[str] = []
    targets: list[str] = []
    # Trip-5 O/T/R/RE profiles are different extraction or library variants of
    # one field specimen, so a suffix-stripped match identifies the specimen
    # but not the variant's own protocol.
    collapsed: dict[tuple[int, str], int] = {}
    for row in alpha.itertuples():
        key = (int(row.Trip), str(row.specimen_id))
        if key in lookup:
            resolutions.append("exact")
            targets.append(row.specimen_id)
            kits.append(lookup[key] or NOT_RECORDED)
            continue
        stripped = TRIP5_SUFFIX_RE.sub("", str(row.specimen_id))
        fallback = (int(row.Trip), stripped)
        if stripped != row.specimen_id and fallback in lookup:
            resolutions.append("suffix_fallback")
            targets.append(stripped)
            kits.append(AMBIGUOUS)
            collapsed[fallback] = collapsed.get(fallback, 0) + 1
            continue
        resolutions.append("unmatched")
        targets.append("")
        kits.append(NOT_RECORDED)
    joined = alpha.copy()
    joined["ledger_resolution"] = resolutions
    joined["ledger_specimen_id"] = targets
    joined["dna_kit"] = kits
    audit = {
        "profiles": int(len(joined)),
        "exact_joins": int((joined["ledger_resolution"] == "exact").sum()),
        "suffix_fallback_joins": int(
            (joined["ledger_resolution"] == "suffix_fallback").sum()
        ),
        "unmatched_profiles": int(
            (joined["ledger_resolution"] == "unmatched").sum()
        ),
        "ambiguous_specimens": int(
            sum(1 for count in collapsed.values() if count > 1)
        ),
        "profiles_with_recorded_kit": int(
            (~joined["dna_kit"].isin([NOT_RECORDED, AMBIGUOUS])).sum()
        ),
        "profiles_without_recorded_kit": int(
            joined["dna_kit"].isin([NOT_RECORDED, AMBIGUOUS]).sum()
        ),
        "recorded_kits": sorted(
            set(joined["dna_kit"]) - {NOT_RECORDED, AMBIGUOUS}
        ),
    }
    return joined, audit


def aggregate_groups(joined: pd.DataFrame) -> pd.DataFrame:
    """One row per campaign x site x position, with a group-level kit label."""

    def group_kit(values: pd.Series) -> str:
        recorded = {
            value
            for value in values
            if value not in (NOT_RECORDED, AMBIGUOUS, "")
        }
        if len(recorded) == 1 and not values.isin([AMBIGUOUS]).any():
            return recorded.pop()
        if len(recorded) > 1:
            return MIXED
        if values.isin([AMBIGUOUS]).any():
            return AMBIGUOUS
        return NOT_RECORDED

    grouped = (
        joined.groupby(["Trip", "Site", "Type"], as_index=False)
        .agg(
            shannon=("shannon", "mean"),
            sequencing_depth=("depth", "sum"),
            n_profiles=("shannon", "size"),
            dna_kit=("dna_kit", group_kit),
        )
        .sort_values(["Trip", "Site", "Type"])
    )
    grouped = grouped[grouped["Site"].isin(CORE_SITES)].copy()
    grouped["log_sequencing_depth"] = np.log(grouped["sequencing_depth"])
    grouped["kit_recorded"] = ~grouped["dna_kit"].isin(
        [NOT_RECORDED, AMBIGUOUS, MIXED]
    )
    return grouped.reset_index(drop=True)


def fit_gee(frame: pd.DataFrame, formula: str, maxiter: int = 200):
    # Extraction kit is nearly aliased with campaign, so the exchangeable GEE
    # is started from the ordinary least-squares solution of the same design
    # rather than from zero.  Convergence is asserted, never assumed.
    start = smf.ols(formula, data=frame).fit().params.to_numpy()
    fit = smf.gee(
        formula,
        groups="Site",
        data=frame,
        cov_struct=Exchangeable(),
    ).fit(maxiter=maxiter, start_params=start)
    if not getattr(fit, "converged", True):
        raise ValueError(f"GEE did not converge for formula: {formula}")
    return fit


def rank_deficiency(frame: pd.DataFrame, formula: str) -> int:
    """Columns of the design that are exactly aliased by other columns."""
    design = patsy.dmatrices(formula, frame, return_type="dataframe")[1]
    return int(design.shape[1] - np.linalg.matrix_rank(design.to_numpy()))


def interaction_wald_p(fit) -> float:
    rows = [i for i, term in enumerate(fit.params.index) if ":" in term]
    if not rows:
        return math.nan
    restriction = np.zeros((len(rows), len(fit.params)))
    for row, column in enumerate(rows):
        restriction[row, column] = 1
    return float(fit.wald_test(restriction, scalar=True).pvalue)


def position_contrasts(fit, model: str, n_observations: int, n_sites: int):
    """Position contrasts from an additive model with a Surface reference."""
    names = list(fit.params.index)
    index = {}
    for position in ("Deep", "Rhizosphere"):
        term = f"{TYPE_TERM}[T.{position}]"
        if term not in names:
            raise ValueError(f"Model {model} lacks the term {term}")
        index[position] = names.index(term)
    rows = []
    for first, second in CONTRASTS:
        vector = np.zeros(len(names))
        if first != "Surface":
            vector[index[first]] += 1
        if second != "Surface":
            vector[index[second]] -= 1
        test = fit.t_test(vector)
        interval = np.asarray(test.conf_int()).ravel()
        rows.append(
            {
                "model": model,
                "contrast": f"{first}-{second}",
                "n_observations": n_observations,
                "n_sites": n_sites,
                "estimate": float(np.ravel(test.effect)[0]),
                "std_error": float(np.ravel(test.sd)[0]),
                "ci_low": float(interval[0]),
                "ci_high": float(interval[1]),
                "p": float(np.ravel(test.pvalue)[0]),
            }
        )
    return rows


def coefficient_rows(fit, model: str) -> list[dict[str, Any]]:
    interval = fit.conf_int()
    return [
        {
            "model": model,
            "term": term,
            "estimate": float(fit.params[term]),
            "std_error": float(fit.bse[term]),
            "z": float(fit.tvalues[term]),
            "p": float(fit.pvalues[term]),
            "ci_low": float(interval.loc[term, 0]),
            "ci_high": float(interval.loc[term, 1]),
        }
        for term in fit.params.index
    ]


def protocol_matched_subset(
    frame: pd.DataFrame,
    first: str,
    second: str,
) -> pd.DataFrame:
    """Blocks whose two positions share one recorded extraction protocol."""
    pair = frame[frame["Type"].isin((first, second)) & frame["kit_recorded"]]
    wide = pair.pivot_table(
        index=["Trip", "Site"],
        columns="Type",
        values="dna_kit",
        aggfunc="first",
    )
    if first not in wide or second not in wide:
        return pair.iloc[0:0]
    matched = wide.dropna(subset=[first, second])
    matched = matched[matched[first] == matched[second]]
    keys = set(matched.index)
    mask = [
        (row.Trip, row.Site) in keys for row in pair.itertuples()
    ]
    return pair.loc[np.asarray(mask)]


def paired_contrasts(
    frame: pd.DataFrame,
    metric: str,
    label: str,
    bootstrap: int,
    seed: int,
) -> list[dict[str, Any]]:
    """Campaign-averaged paired site contrasts with a site bootstrap."""
    averaged = frame.groupby(["Site", "Type"], as_index=False)[metric].mean()
    wide = averaged.pivot_table(index="Site", columns="Type", values=metric)
    rows = []
    for offset, (first, second) in enumerate(CONTRASTS):
        if first not in wide or second not in wide:
            continue
        pair = wide[[first, second]].dropna()
        difference = (pair[first] - pair[second]).to_numpy(dtype=float)
        if len(difference) < 3:
            continue
        test = stats.wilcoxon(difference)
        rng = np.random.default_rng(seed + offset)
        indices = rng.integers(
            0, len(difference), size=(bootstrap, len(difference))
        )
        boot = difference[indices].mean(axis=1)
        rows.append(
            {
                "adjustment": label,
                "metric": metric,
                "contrast": f"{first}-{second}",
                "n_sites": int(len(difference)),
                "mean_difference": float(difference.mean()),
                "median_difference": float(np.median(difference)),
                "ci_low": float(np.quantile(boot, 0.025)),
                "ci_high": float(np.quantile(boot, 0.975)),
                "wilcoxon_w": float(test.statistic),
                "p": float(test.pvalue),
                "fraction_positive": float((difference > 0).mean()),
            }
        )
    return rows


def interval_excludes_zero(row: Mapping[str, Any]) -> bool:
    return not (row["ci_low"] <= 0 <= row["ci_high"])


def build_verdict(
    contrast_rows: Sequence[Mapping[str, Any]],
    paired_rows: Sequence[Mapping[str, Any]],
    interaction: Mapping[str, float],
    audit: Mapping[str, Any],
) -> dict[str, Any]:
    by_model: dict[str, dict[str, Mapping[str, Any]]] = {}
    for row in contrast_rows:
        by_model.setdefault(row["model"], {})[row["contrast"]] = row

    sensitivity_models = [
        model
        for model in by_model
        if model not in ("additive_unadjusted",)
    ]
    contrasts: dict[str, Any] = {}
    for first, second in CONTRASTS:
        contrast = f"{first}-{second}"
        depth_row = by_model["additive_depth_adjusted"][contrast]
        stable_models = {
            model: interval_excludes_zero(rows[contrast])
            for model, rows in by_model.items()
            if contrast in rows
        }
        directions = {
            model: float(np.sign(rows[contrast]["estimate"]))
            for model, rows in by_model.items()
            if contrast in rows
        }
        direction_stable = len(set(directions.values())) == 1
        supported_everywhere = all(stable_models.values())
        paired_depth = next(
            (
                row
                for row in paired_rows
                if row["contrast"] == contrast
                and row["adjustment"] == "depth_adjusted"
            ),
            None,
        )
        if supported_everywhere and direction_stable:
            status = "supported"
        elif stable_models.get("additive_depth_adjusted") and direction_stable:
            status = "sensitivity_dependent"
        elif direction_stable:
            status = "direction_only"
        else:
            status = "not_supported"
        contrasts[contrast] = {
            "label": (
                f"{POSITION_LABELS[first]} minus {POSITION_LABELS[second]}"
            ),
            "status": status,
            "depth_adjusted_estimate": depth_row["estimate"],
            "depth_adjusted_ci": [depth_row["ci_low"], depth_row["ci_high"]],
            "depth_adjusted_p": depth_row["p"],
            "interval_excludes_zero_by_model": stable_models,
            "direction_stable_across_models": direction_stable,
            "paired_depth_adjusted": (
                None
                if paired_depth is None
                else {
                    "n_sites": paired_depth["n_sites"],
                    "mean_difference": paired_depth["mean_difference"],
                    "ci": [paired_depth["ci_low"], paired_depth["ci_high"]],
                    "p": paired_depth["p"],
                    "q": paired_depth.get("q_within_adjustment"),
                }
            ),
        }

    primary = contrasts[PRIMARY_CONTRAST]
    secondary = contrasts[SECONDARY_CONTRAST]
    if primary["status"] == "supported":
        status = "compartment_wording_retained"
    elif primary["status"] == "sensitivity_dependent":
        status = "compartment_wording_retained_with_sensitivity_caveat"
    else:
        status = "compartment_wording_requires_revision"

    sentences = [
        "After adjusting for log sequencing depth in the site-clustered GEE, "
        f"the {primary['label']} Shannon contrast was "
        f"{primary['depth_adjusted_estimate']:.3f} "
        f"(95% CI {primary['depth_adjusted_ci'][0]:.3f} to "
        f"{primary['depth_adjusted_ci'][1]:.3f})."
    ]
    if secondary["status"] in ("sensitivity_dependent", "direction_only"):
        sentences.append(
            f"The {secondary['label']} contrast is sensitivity-dependent: its "
            "direction is stable but its interval or adjusted test changes "
            "across the prespecified extraction models, so it is reported as "
            "such rather than as a general result."
        )
    elif secondary["status"] == "supported":
        sentences.append(
            f"The {secondary['label']} contrast retained an interval "
            "excluding zero in every prespecified depth and extraction model."
        )
    else:
        sentences.append(
            f"The {secondary['label']} contrast was not supported after "
            "adjustment and must not be reported as a general difference."
        )
    unadjusted_p = float(interaction["unadjusted_wald_p"])
    adjusted_p = float(interaction["depth_adjusted_wald_p"])
    interaction_changes = (unadjusted_p < 0.05) != (adjusted_p < 0.05)
    if interaction_changes:
        status = f"{status}_with_interaction_dependence"
        sentences.append(
            "The campaign-by-position interaction changed materially with "
            f"depth adjustment (Wald p = {unadjusted_p:.3g} unadjusted, "
            f"{adjusted_p:.3g} after log sequencing depth). Report that "
            "dependence in the Results and abstract; do not present either "
            "model as the single campaign-by-position result."
        )
    sentences.append(
        "Extraction metadata are incomplete and partly confounded with "
        f"campaign ({audit['profiles_with_recorded_kit']} of "
        f"{audit['profiles']} profiles carry a recorded kit), so these fits "
        "are a robustness check and do not remove laboratory batch effects."
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "campaign_by_position_interaction_changes_with_depth": (
            interaction_changes
        ),
        "permitted_wording": " ".join(sentences),
        "prohibited_wording": (
            "Do not describe the extraction sensitivity as removal of all "
            "laboratory batch effects; campaign, processing context and "
            "missing extraction metadata remain coupled."
        ),
        "campaign_by_position_interaction": dict(interaction),
        "contrasts": contrasts,
        "join_audit": dict(audit),
        "multiplicity_family": (
            "The three position contrasts form one Benjamini-Hochberg family "
            "within each adjustment; GEE contrast intervals are reported "
            "without further correction and read together with that family."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
    )
    parser.add_argument("--alpha", type=Path, default=None)
    parser.add_argument("--sample-ledger", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--bootstrap", type=int, default=5000)
    parser.add_argument("--seed", type=int, default=20260725)
    args = parser.parse_args()

    root = args.project_root.resolve()
    alpha_path = args.alpha or root / "analysis/v2/review/cache/alpha.tsv"
    ledger_path = (
        args.sample_ledger or root / "data/release/sample_ledger.tsv"
    )
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)

    alpha = load_alpha(alpha_path)
    ledger = load_extraction_ledger(ledger_path)
    joined, audit = join_extraction(alpha, ledger)
    groups = aggregate_groups(joined)

    audit["core_site_groups"] = int(len(groups))
    audit["core_site_groups_with_recorded_kit"] = int(
        groups["kit_recorded"].sum()
    )
    audit["core_sites"] = int(groups["Site"].nunique())
    kit_by_campaign = (
        pd.crosstab(groups["Trip"], groups["dna_kit"])
        .reset_index()
        .to_dict(orient="records")
    )

    write_tsv(
        output / "profile_extraction_join_audit.tsv",
        joined[
            [
                "profile_id",
                "specimen_id",
                "Trip",
                "Site",
                "Type",
                "depth",
                "shannon",
                "ledger_resolution",
                "ledger_specimen_id",
                "dna_kit",
            ]
        ].to_dict(orient="records"),
        [
            "profile_id",
            "specimen_id",
            "Trip",
            "Site",
            "Type",
            "depth",
            "shannon",
            "ledger_resolution",
            "ledger_specimen_id",
            "dna_kit",
        ],
    )
    write_tsv(
        output / "group_analysis_table.tsv",
        groups.to_dict(orient="records"),
        [
            "Trip",
            "Site",
            "Type",
            "n_profiles",
            "shannon",
            "sequencing_depth",
            "log_sequencing_depth",
            "dna_kit",
            "kit_recorded",
        ],
    )
    write_tsv(
        output / "extraction_kit_by_campaign.tsv",
        kit_by_campaign,
        list(kit_by_campaign[0]) if kit_by_campaign else ["Trip"],
    )

    interaction_fit = fit_gee(
        groups, f"shannon ~ C(Trip) * {TYPE_TERM}"
    )
    interaction_depth_fit = fit_gee(
        groups,
        f"shannon ~ C(Trip) * {TYPE_TERM} + log_sequencing_depth",
    )
    interaction = {
        "unadjusted_wald_p": interaction_wald_p(interaction_fit),
        "depth_adjusted_wald_p": interaction_wald_p(interaction_depth_fit),
    }

    complete = groups[groups["kit_recorded"]].copy()
    # Within the complete cases QIACube occurs only in campaigns 4 and 5 and
    # those campaigns record no other kit, so the kit term is exactly aliased
    # with campaign there.  The complete-case sensitivity is therefore split:
    # a cohort restriction without the kit term, and a kit-adjusted fit
    # restricted to the campaigns in which more than one kit was recorded.
    kit_varying_campaigns = sorted(
        int(trip)
        for trip, block in complete.groupby("Trip")
        if block["dna_kit"].nunique() >= 2
    )
    kit_varying = complete[complete["Trip"].isin(kit_varying_campaigns)].copy()
    base = f"shannon ~ C(Trip) + {TYPE_TERM} + log_sequencing_depth"
    model_specifications: list[tuple[str, pd.DataFrame, str]] = [
        ("additive_unadjusted", groups, f"shannon ~ C(Trip) + {TYPE_TERM}"),
        ("additive_depth_adjusted", groups, base),
        ("depth_and_kit_as_recorded", groups, f"{base} + C(dna_kit)"),
        ("complete_case_cohort", complete, base),
        (
            "depth_and_kit_kit_varying_campaigns",
            kit_varying,
            f"{base} + C(dna_kit)",
        ),
    ]

    coefficients: list[dict[str, Any]] = []
    contrast_rows: list[dict[str, Any]] = []
    identifiability: list[dict[str, Any]] = [
        {
            "model": "depth_and_kit_complete_cases_not_identified",
            "n_observations": int(len(complete)),
            "n_sites": int(complete["Site"].nunique()),
            "aliased_columns": rank_deficiency(
                complete, f"{base} + C(dna_kit)"
            ),
            "note": (
                "Extraction kit is exactly aliased with campaign in the "
                "complete-case cohort; replaced by complete_case_cohort and "
                "depth_and_kit_kit_varying_campaigns."
            ),
        }
    ]
    for model, frame, formula in model_specifications:
        deficiency = rank_deficiency(frame, formula)
        identifiability.append(
            {
                "model": model,
                "n_observations": int(len(frame)),
                "n_sites": int(frame["Site"].nunique()),
                "aliased_columns": deficiency,
                "note": formula,
            }
        )
        if deficiency:
            raise ValueError(
                f"Model {model} is rank deficient by {deficiency} columns"
            )
        fit = fit_gee(frame, formula)
        coefficients.extend(coefficient_rows(fit, model))
        contrast_rows.extend(
            position_contrasts(
                fit,
                model,
                int(fit.nobs),
                int(frame["Site"].nunique()),
            )
        )
    coefficients.extend(
        coefficient_rows(interaction_fit, "interaction_unadjusted")
    )
    coefficients.extend(
        coefficient_rows(interaction_depth_fit, "interaction_depth_adjusted")
    )

    matched_rows: list[dict[str, Any]] = []
    for first, second in CONTRASTS:
        subset = protocol_matched_subset(groups, first, second)
        contrast = f"{first}-{second}"
        if subset["Site"].nunique() < 5 or subset["Type"].nunique() < 2:
            matched_rows.append(
                {
                    "model": "protocol_matched_pairs",
                    "contrast": contrast,
                    "n_observations": int(len(subset)),
                    "n_sites": int(subset["Site"].nunique()),
                    "estimate": math.nan,
                    "std_error": math.nan,
                    "ci_low": math.nan,
                    "ci_high": math.nan,
                    "p": math.nan,
                }
            )
            continue
        # The reference level is the second position of the contrast, so the
        # remaining C(Type) coefficient is the contrast itself.
        reference_term = f'C(Type, Treatment(reference="{second}"))'
        formula = (
            f"shannon ~ C(Trip) + {reference_term} + log_sequencing_depth"
        )
        fit = fit_gee(subset, formula)
        names = list(fit.params.index)
        vector = np.zeros(len(names))
        vector[names.index(f"{reference_term}[T.{first}]")] += 1
        test = fit.t_test(vector)
        interval = np.asarray(test.conf_int()).ravel()
        matched_rows.append(
            {
                "model": "protocol_matched_pairs",
                "contrast": contrast,
                "n_observations": int(fit.nobs),
                "n_sites": int(subset["Site"].nunique()),
                "estimate": float(np.ravel(test.effect)[0]),
                "std_error": float(np.ravel(test.sd)[0]),
                "ci_low": float(interval[0]),
                "ci_high": float(interval[1]),
                "p": float(np.ravel(test.pvalue)[0]),
            }
        )
        coefficients.extend(
            coefficient_rows(fit, f"protocol_matched_{contrast}")
        )
    contrast_rows.extend(
        row for row in matched_rows if math.isfinite(row["estimate"])
    )
    all_contrast_rows = contrast_rows + [
        row for row in matched_rows if not math.isfinite(row["estimate"])
    ]

    depth_model = smf.ols(
        "shannon ~ log_sequencing_depth", data=groups
    ).fit(cov_type="cluster", cov_kwds={"groups": groups["Site"]})
    adjusted = groups.copy()
    adjusted["shannon_depth_adjusted"] = (
        groups["shannon"] - depth_model.params["log_sequencing_depth"]
        * (
            groups["log_sequencing_depth"]
            - groups["log_sequencing_depth"].mean()
        )
    )

    paired_rows = paired_contrasts(
        groups, "shannon", "unadjusted", args.bootstrap, args.seed
    )
    paired_rows += paired_contrasts(
        adjusted,
        "shannon_depth_adjusted",
        "depth_adjusted",
        args.bootstrap,
        args.seed + 17,
    )
    matched_complete = adjusted[adjusted["kit_recorded"]]
    paired_rows += paired_contrasts(
        matched_complete,
        "shannon_depth_adjusted",
        "depth_adjusted_complete_kit_cases",
        args.bootstrap,
        args.seed + 29,
    )
    frame_paired = pd.DataFrame(paired_rows)
    frame_paired["q_within_adjustment"] = np.concatenate(
        [
            bh_fdr(block["p"].tolist())
            for _, block in frame_paired.groupby("adjustment", sort=False)
        ]
    )
    paired_rows = frame_paired.to_dict(orient="records")

    write_tsv(
        output / "model_identifiability.tsv",
        identifiability,
        ["model", "n_observations", "n_sites", "aliased_columns", "note"],
    )
    write_tsv(
        output / "gee_coefficients.tsv",
        coefficients,
        [
            "model",
            "term",
            "estimate",
            "std_error",
            "z",
            "p",
            "ci_low",
            "ci_high",
        ],
    )
    write_tsv(
        output / "adjusted_position_contrasts.tsv",
        all_contrast_rows,
        [
            "model",
            "contrast",
            "n_observations",
            "n_sites",
            "estimate",
            "std_error",
            "ci_low",
            "ci_high",
            "p",
        ],
    )
    write_tsv(
        output / "paired_contrasts_after_depth_adjustment.tsv",
        paired_rows,
        [
            "adjustment",
            "metric",
            "contrast",
            "n_sites",
            "mean_difference",
            "median_difference",
            "ci_low",
            "ci_high",
            "wilcoxon_w",
            "p",
            "q_within_adjustment",
            "fraction_positive",
        ],
    )

    verdict = build_verdict(contrast_rows, paired_rows, interaction, audit)
    verdict["extraction_identifiability"] = {
        "kit_varying_campaigns": kit_varying_campaigns,
        "complete_case_kit_aliased_with_campaign": True,
        "detail": identifiability,
    }
    verdict["input"] = {
        "alpha_path": provenance_path(alpha_path, root),
        "alpha_sha256": sha256_file(alpha_path),
        "sample_ledger_path": provenance_path(ledger_path, root),
        "sample_ledger_sha256": sha256_file(ledger_path),
        "core_sites": "1-60",
        "bootstrap_resamples": args.bootstrap,
        "seed": args.seed,
        "depth_slope_per_log_read": float(
            depth_model.params["log_sequencing_depth"]
        ),
        "depth_slope_p": float(
            depth_model.pvalues["log_sequencing_depth"]
        ),
    }
    (output / "claim_verdict.json").write_text(
        json.dumps(verdict, indent=2) + "\n", encoding="utf-8"
    )

    readme = [
        "# Sequencing-depth and extraction-protocol sensitivity",
        "",
        f"- Status: `{verdict['status']}`",
        f"- Profiles joined to the release ledger: "
        f"{audit['exact_joins']} exact, "
        f"{audit['suffix_fallback_joins']} by Trip-5 suffix fallback, "
        f"{audit['unmatched_profiles']} unmatched",
        f"- Profiles with a recorded extraction kit: "
        f"{audit['profiles_with_recorded_kit']} / {audit['profiles']}",
        f"- Campaign-by-position interaction Wald p: "
        f"{interaction['unadjusted_wald_p']:.4g} unadjusted, "
        f"{interaction['depth_adjusted_wald_p']:.4g} depth-adjusted",
        "",
    ]
    for contrast, value in verdict["contrasts"].items():
        readme.extend(
            [
                f"## {contrast} ({value['label']})",
                "",
                f"- Status: `{value['status']}`",
                f"- Depth-adjusted GEE estimate: "
                f"{value['depth_adjusted_estimate']:.4f} "
                f"(95% CI {value['depth_adjusted_ci'][0]:.4f} to "
                f"{value['depth_adjusted_ci'][1]:.4f}; "
                f"p = {value['depth_adjusted_p']:.4g})",
                "- Interval excludes zero by model: "
                + ", ".join(
                    f"{model}={value}"
                    for model, value in value[
                        "interval_excludes_zero_by_model"
                    ].items()
                ),
                f"- Direction stable across models: "
                f"{value['direction_stable_across_models']}",
                "",
            ]
        )
    readme.extend(
        [
            "## Permitted wording",
            "",
            verdict["permitted_wording"],
            "",
            "## Prohibited wording",
            "",
            verdict["prohibited_wording"],
            "",
        ]
    )
    (output / "README.md").write_text("\n".join(readme), encoding="utf-8")

    checksum_lines = [
        f"{sha256_file(path)}  {path.name}"
        for path in sorted(
            item
            for item in output.iterdir()
            if item.is_file() and item.name != "SHA256SUMS"
        )
    ]
    (output / "SHA256SUMS").write_text(
        "\n".join(checksum_lines) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
