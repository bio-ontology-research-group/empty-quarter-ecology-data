#!/usr/bin/env python3
"""Compare canonical and control-adjusted ecology headline outputs."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def provenance_path(path: Path, root: Path, output_root: Path) -> str:
    absolute = path.resolve()
    for base, prefix in ((root.resolve(), ""), (output_root.resolve(), "OUTPUT_ROOT/")):
        try:
            relative = absolute.relative_to(base)
        except ValueError:
            continue
        return prefix + relative.as_posix()
    return absolute.as_posix()


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--canonical-root", type=Path, default=root / "analysis/v3"
    )
    parser.add_argument(
        "--sensitivity-root",
        type=Path,
        default=root / "analysis/v3/control_sensitivity",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=root / "analysis/v3/control_sensitivity",
    )
    args = parser.parse_args()
    canonical = args.canonical_root
    sensitivity = args.sensitivity_root
    args.output_dir.mkdir(parents=True, exist_ok=True)

    files = {
        "spatial_before": canonical
        / "spatial_turnover_rescue/results/claim_verdict.json",
        "spatial_after": sensitivity / "spatial_turnover/claim_verdict.json",
        "prediction_before": canonical / "geographic_prediction/claim_verdict.json",
        "prediction_after": sensitivity
        / "geographic_prediction/claim_verdict.json",
        "composition_before": canonical
        / "compartment_composition/claim_verdict.json",
        "composition_after": sensitivity
        / "compartment_composition/claim_verdict.json",
        "depth_before": canonical / "depth_extraction/claim_verdict.json",
        "depth_after": sensitivity / "depth_extraction/claim_verdict.json",
        "evenness_before": canonical
        / "evenness_decomposition/claim_verdict.json",
        "evenness_after": sensitivity
        / "evenness_decomposition/claim_verdict.json",
        "xrf_before": canonical / "xrf_community_clr/claim_verdict.json",
        "xrf_after": sensitivity / "xrf_community_clr/claim_verdict.json",
        "resolution_before": canonical
        / "spatial_resolution_sensitivity/claim_verdict.json",
        "resolution_after": sensitivity
        / "spatial_resolution/claim_verdict.json",
        "distance_before": canonical
        / "distance_decay_turnover/claim_verdict.json",
        "distance_after": sensitivity
        / "distance_decay_turnover/claim_verdict.json",
        "claims_before": canonical / "results/claim_ledger.json",
        "claims_after": sensitivity / "claim_rescue/claim_ledger.json",
        "paired_before": canonical / "results/paired_compartment_effects.tsv",
        "paired_after": sensitivity
        / "claim_rescue/paired_compartment_effects.tsv",
        "rain_before": canonical / "results/rain_window_models.tsv",
        "rain_after": sensitivity / "claim_rescue/rain_window_models.tsv",
    }
    missing = [str(path) for path in files.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError("missing comparison input(s): " + ", ".join(missing))

    spatial_before = load_json(files["spatial_before"])
    spatial_after = load_json(files["spatial_after"])
    prediction_before = load_json(files["prediction_before"])
    prediction_after = load_json(files["prediction_after"])
    composition_before = load_json(files["composition_before"])
    composition_after = load_json(files["composition_after"])
    depth_before = load_json(files["depth_before"])
    depth_after = load_json(files["depth_after"])
    evenness_before = load_json(files["evenness_before"])
    evenness_after = load_json(files["evenness_after"])
    xrf_before = load_json(files["xrf_before"])
    xrf_after = load_json(files["xrf_after"])
    resolution_before = load_json(files["resolution_before"])
    resolution_after = load_json(files["resolution_after"])
    distance_before = load_json(files["distance_before"])
    distance_after = load_json(files["distance_after"])
    claims_before = {
        row["claim"]: row["status"] for row in load_json(files["claims_before"])
    }
    claims_after = {
        row["claim"]: row["status"] for row in load_json(files["claims_after"])
    }
    paired_before = pd.read_csv(files["paired_before"], sep="\t")
    paired_after = pd.read_csv(files["paired_after"], sep="\t")
    rain_before = pd.read_csv(files["rain_before"], sep="\t")
    rain_after = pd.read_csv(files["rain_after"], sep="\t")

    rows: list[dict[str, object]] = []

    def add(
        claim: str,
        metric: str,
        before: float | int,
        after: float | int,
        before_verdict: str,
        after_verdict: str,
    ) -> None:
        rows.append(
            {
                "claim": claim,
                "metric": metric,
                "canonical_value": f"{before:.10g}",
                "control_adjusted_value": f"{after:.10g}",
                "absolute_change": f"{abs(float(after) - float(before)):.10g}",
                "canonical_verdict": before_verdict,
                "control_adjusted_verdict": after_verdict,
                "verdict_stable": str(before_verdict == after_verdict).lower(),
            }
        )

    add(
        "broad geographic composition structure",
        "partial_r2",
        spatial_before["primary_partial_r2"],
        spatial_after["primary_partial_r2"],
        spatial_before["status"],
        spatial_after["status"],
    )
    add(
        "broad geographic composition structure",
        "permutation_p",
        spatial_before["primary_permutation_p"],
        spatial_after["primary_permutation_p"],
        spatial_before["status"],
        spatial_after["status"],
    )
    for metric in (
        "group_level_equal_weight_skill",
        "group_level_pooled_skill",
        "site_level_block_skill",
    ):
        add(
            "leakage-free geographic prediction",
            metric,
            prediction_before[metric],
            prediction_after[metric],
            prediction_before["status"],
            prediction_after["status"],
        )
    add(
        "paired compartment composition",
        "omnibus_pseudo_f",
        composition_before["omnibus"]["pseudo_f"],
        composition_after["omnibus"]["pseudo_f"],
        composition_before["status"],
        composition_after["status"],
    )
    add(
        "paired compartment composition",
        "omnibus_permutation_p",
        composition_before["omnibus"]["permutation_p"],
        composition_after["omnibus"]["permutation_p"],
        composition_before["status"],
        composition_after["status"],
    )
    for contrast in (
        "Deep-Surface",
        "Rhizosphere-Surface",
        "Rhizosphere-Deep",
    ):
        add(
            "paired compartment composition",
            f"{contrast}_standardized_displacement",
            composition_before["contrasts"][contrast]["standardized_displacement"],
            composition_after["contrasts"][contrast]["standardized_displacement"],
            composition_before["contrasts"][contrast]["status"],
            composition_after["contrasts"][contrast]["status"],
        )

    for contrast in ("Rhizosphere-Surface", "Rhizosphere-Deep"):
        before_row = paired_before[
            (paired_before["trip"].astype(str) == "all")
            & (paired_before["metric"] == "shannon")
            & (paired_before["comparison"] == contrast)
        ].iloc[0]
        after_row = paired_after[
            (paired_after["trip"].astype(str) == "all")
            & (paired_after["metric"] == "shannon")
            & (paired_after["comparison"] == contrast)
        ].iloc[0]
        add(
            "paired Shannon distribution",
            f"{contrast}_mean_difference",
            before_row["mean_difference"],
            after_row["mean_difference"],
            claims_before["root selective filter"],
            claims_after["root selective filter"],
        )
        add(
            "paired Shannon distribution",
            f"{contrast}_q",
            before_row["q_within_metric"],
            after_row["q_within_metric"],
            claims_before["root selective filter"],
            claims_after["root selective filter"],
        )

    add(
        "campaign-by-position depth sensitivity",
        "unadjusted_wald_p",
        depth_before["campaign_by_position_interaction"]["unadjusted_wald_p"],
        depth_after["campaign_by_position_interaction"]["unadjusted_wald_p"],
        depth_before["status"],
        depth_after["status"],
    )
    add(
        "campaign-by-position depth sensitivity",
        "depth_adjusted_wald_p",
        depth_before["campaign_by_position_interaction"][
            "depth_adjusted_wald_p"
        ],
        depth_after["campaign_by_position_interaction"][
            "depth_adjusted_wald_p"
        ],
        depth_before["status"],
        depth_after["status"],
    )
    add(
        "depth-adjusted root-adjacent contrast",
        "Rhizosphere-Deep_estimate",
        depth_before["contrasts"]["Rhizosphere-Deep"]["depth_adjusted_estimate"],
        depth_after["contrasts"]["Rhizosphere-Deep"]["depth_adjusted_estimate"],
        depth_before["contrasts"]["Rhizosphere-Deep"]["status"],
        depth_after["contrasts"]["Rhizosphere-Deep"]["status"],
    )

    for contrast in ("Rhizosphere-Surface", "Rhizosphere-Deep"):
        add(
            "post-hoc normalized evenness",
            f"{contrast}_mean_difference",
            evenness_before["primary_results"][contrast][
                "evenness_sensitivity"
            ]["mean_difference"],
            evenness_after["primary_results"][contrast][
                "evenness_sensitivity"
            ]["mean_difference"],
            evenness_before["status"],
            evenness_after["status"],
        )

    add(
        "antecedent rainfall family",
        "tests_with_q_global_below_0.05",
        int((rain_before["q_global"] < 0.05).sum()),
        int((rain_after["q_global"] < 0.05).sum()),
        claims_before["antecedent-rainfall response in any compartment"],
        claims_after["antecedent-rainfall response in any compartment"],
    )
    add(
        "laboratory-XRF conditional composition association",
        "partial_r2",
        xrf_before["primary"]["partial_r2"],
        xrf_after["primary"]["partial_r2"],
        xrf_before["status"],
        xrf_after["status"],
    )
    add(
        "laboratory-XRF conditional composition association",
        "permutation_p",
        xrf_before["primary"]["permutation_p"],
        xrf_after["primary"]["permutation_p"],
        xrf_before["status"],
        xrf_after["status"],
    )
    add(
        "ASV-resolution geographic sensitivity",
        "minimum_partial_r2",
        resolution_before["asv_partial_r2_range"][0],
        resolution_after["asv_partial_r2_range"][0],
        resolution_before["status"],
        resolution_after["status"],
    )
    add(
        "ASV-resolution geographic sensitivity",
        "maximum_partial_r2",
        resolution_before["asv_partial_r2_range"][1],
        resolution_after["asv_partial_r2_range"][1],
        resolution_before["status"],
        resolution_after["status"],
    )
    add(
        "paired distance-decay slopes",
        "omnibus_p",
        distance_before["omnibus_p"],
        distance_after["omnibus_p"],
        distance_before["status"],
        distance_after["status"],
    )

    output_table = args.output_dir / "headline_result_sensitivity.tsv"
    with output_table.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(rows[0]),
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)

    changed = [
        row["claim"] + "::" + row["metric"]
        for row in rows
        if row["verdict_stable"] != "true"
    ]
    summary = {
        "scope": (
            "The primary 351-ASV candidate set is removed only from 217 "
            "Trip-5 profiles with frozen extraction-batch mappings. The "
            "remaining 1,020 ecological profiles are unchanged."
        ),
        "headline_metrics_compared": len(rows),
        "verdict_changes": changed,
        "all_headline_verdicts_stable": not changed,
        "conclusion": (
            "No headline scientific verdict changed under the bounded "
            "Trip-5 control filter."
            if not changed
            else "At least one headline verdict changed; inspect the table."
        ),
        "comparison_table": provenance_path(output_table, root, args.output_dir),
        "input_sha256": {
            name: sha256(path) for name, path in sorted(files.items())
        },
    }
    summary_path = args.output_dir / "headline_result_sensitivity.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
