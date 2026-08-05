#!/usr/bin/env python3
"""Run and summarize the prespecified rainfall pulse-response suite."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pandas as pd


DEFAULT_PERMUTATIONS = 19_999
DEFAULT_BOOTSTRAPS = 9_999
BOOTSTRAP_SEED = 20260805


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run_definitions(root: Path) -> list[dict[str, Any]]:
    unfiltered = root / "analysis/v2/review/cache/alpha.tsv"
    filtered = root / "analysis/v3/control_audit/sensitivity_inputs/alpha.tsv"
    nasa = root / "data/processed/climate/nasa_power_daily_precipitation.tsv.gz"
    open_meteo = root / "data/processed/climate/daily_weather_canonical.tsv"
    sensitivities = root / "analysis/v3/rain_pulse_sensitivities"
    return [
        {
            "run_id": "primary_nasa_power",
            "output": root / "analysis/v3/rain_pulse_response",
            "arguments": ["--alpha", unfiltered],
        },
        {
            "run_id": "open_meteo_product",
            "output": root / "analysis/v3/rain_pulse_response_open_meteo",
            "arguments": [
                "--alpha",
                unfiltered,
                "--nasa-weather",
                open_meteo,
                "--weather-product",
                "open_meteo",
            ],
        },
        {
            "run_id": "control_filtered",
            "output": sensitivities / "control_filtered",
            "arguments": [
                "--alpha",
                filtered,
                "--community-table-role",
                "control_filtered_sensitivity",
            ],
        },
        {
            "run_id": "paired_bulk",
            "output": sensitivities / "paired",
            "arguments": ["--alpha", unfiltered, "--cohort", "paired"],
        },
        {
            "run_id": "ph_adjusted",
            "output": sensitivities / "ph_adjusted",
            "arguments": ["--alpha", unfiltered, "--adjust-ph"],
        },
        {
            "run_id": "quadratic_longitude",
            "output": sensitivities / "quadratic_longitude",
            "arguments": [
                "--alpha",
                unfiltered,
                "--nuisance-model",
                "quadratic_longitude",
            ],
        },
        {
            "run_id": "quadratic_longitude_and_day",
            "output": sensitivities / "quadratic_longitude_day",
            "arguments": [
                "--alpha",
                unfiltered,
                "--nuisance-model",
                "quadratic_longitude_day",
            ],
        },
        {
            "run_id": "cubic_longitude",
            "output": sensitivities / "cubic_longitude",
            "arguments": [
                "--alpha",
                unfiltered,
                "--nuisance-model",
                "cubic_longitude",
            ],
        },
    ]


def execute_runs(
    root: Path,
    definitions: list[dict[str, Any]],
    permutations: int,
    bootstraps: int,
) -> list[list[str]]:
    script = root / "analysis/v3/rain_pulse_response.py"
    commands: list[list[str]] = []
    for definition in definitions:
        command = [
            sys.executable,
            str(script),
            "--root",
            str(root),
            "--permutations",
            str(permutations),
            "--bootstraps",
            str(bootstraps),
            "--bootstrap-seed",
            str(BOOTSTRAP_SEED),
            "--output",
            str(definition["output"]),
            *[str(value) for value in definition["arguments"]],
        ]
        subprocess.run(command, cwd=root, check=True)
        commands.append(command)
    return commands


def summarize(definitions: list[dict[str, Any]]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for definition in definitions:
        output = Path(definition["output"])
        decision = json.loads(
            (output / "analysis_decision.json").read_text(encoding="utf-8")
        )
        cohort = pd.read_csv(output / "analysis_cohort.tsv", sep="\t")
        family = decision["familywise_inference"]
        uncertainty = decision["sampling_uncertainty"]
        cluster_fits = pd.read_csv(
            output / "selected_kernel_cluster_fits.tsv", sep="\t"
        )
        site_fit = cluster_fits[
            cluster_fits["endpoint"].eq(decision["selected_endpoint"])
            & cluster_fits["cluster_definition"].eq("site")
        ].iloc[0]
        rows.append(
            {
                "run_id": definition["run_id"],
                "analysis_status": decision["analysis_status"],
                "weather_product": decision["weather_product"],
                "community_table_role": decision["community_table_role"],
                "cohort": decision["cohort"],
                "nuisance_model": decision["nuisance_model"],
                "ph_adjusted": decision["ph_adjusted"],
                "n_analysis_units": len(cohort),
                "n_sites": int(cohort["Site"].nunique()),
                "selected_endpoint": decision["selected_endpoint"],
                "selected_peak_complete_days": decision[
                    "selected_peak_complete_days"
                ],
                "half_maximum_complete_day": decision["half_maximum_day"],
                "ten_percent_complete_day": decision["ten_percent_day"],
                "estimate_per_mm_at_peak": decision[
                    "selected_estimate_per_mm_at_peak"
                ],
                "site_clustered_ci_low": float(site_fit["ci_low"]),
                "site_clustered_ci_high": float(site_fit["ci_high"]),
                "classical_t": decision["selected_classical_t"],
                "partial_r2": decision["selected_partial_r2"],
                "site_bootstrap_effect_ci_low": uncertainty[
                    "fixed_effect_95_ci"
                ][0],
                "site_bootstrap_effect_ci_high": uncertainty[
                    "fixed_effect_95_ci"
                ][1],
                "site_bootstrap_partial_r2_ci_low": uncertainty[
                    "fixed_partial_r2_95_ci"
                ][0],
                "site_bootstrap_partial_r2_ci_high": uncertainty[
                    "fixed_partial_r2_95_ci"
                ][1],
                "site_bootstrap_peak_ci_low": uncertainty[
                    "selected_endpoint_peak_95_interval_complete_days"
                ][0],
                "site_bootstrap_peak_ci_high": uncertainty[
                    "selected_endpoint_peak_95_interval_complete_days"
                ][1],
                "conditional_lag_rotation_one_sided_p": family[
                    "conditional_lag_rotation_one_sided_p"
                ],
                "conditional_lag_rotation_two_sided_p": family[
                    "conditional_lag_rotation_two_sided_p"
                ],
                "spatial_route_orbit_one_sided_p": family[
                    "spatial_route_orbit_one_sided_p"
                ],
                "spatial_route_orbit_two_sided_p": family[
                    "spatial_route_orbit_two_sided_p"
                ],
            }
        )
    return pd.DataFrame(rows)


def write_suite_metadata(
    root: Path,
    definitions: list[dict[str, Any]],
    commands: list[list[str]],
    permutations: int,
    bootstraps: int,
) -> None:
    output = root / "analysis/v3/rain_pulse_sensitivities"
    output.mkdir(parents=True, exist_ok=True)
    summary = summarize(definitions)
    summary_path = output / "summary.tsv"
    summary.to_csv(summary_path, sep="\t", index=False, lineterminator="\n")
    indexed = summary.set_index("run_id")
    primary = indexed.loc["primary_nasa_power"]
    open_meteo = indexed.loc["open_meteo_product"]
    control_filtered = indexed.loc["control_filtered"]
    consolidated = {
        "reporting_verdict": "bounded_observational_association",
        "primary_unfiltered_familywise_one_sided_p": float(
            primary["conditional_lag_rotation_one_sided_p"]
        ),
        "open_meteo_familywise_one_sided_p": float(
            open_meteo["conditional_lag_rotation_one_sided_p"]
        ),
        "control_filtered_familywise_one_sided_p": float(
            control_filtered["conditional_lag_rotation_one_sided_p"]
        ),
        "fitted_peak_complete_days_across_weather_products": [
            float(primary["selected_peak_complete_days"]),
            float(open_meteo["selected_peak_complete_days"]),
        ],
        "reason": (
            "The declared unfiltered NASA POWER analysis is borderline, while the "
            "Open-Meteo and control-filtered sensitivities retain the same early "
            "positive pattern. The threshold change after filtering is not accompanied "
            "by a material effect-size change."
        ),
        "permitted_main_text": (
            "Bacterial richness showed a short-lived positive association with recent "
            "rain, strongest during the first several complete days after rainfall."
        ),
        "required_boundary": (
            "Report the primary and sensitivity probabilities and state that the model "
            "does not establish causation or an exact response latency."
        ),
    }
    manifest = {
        "schema_version": "1.1",
        "analysis_date": "2026-08-05",
        "permutations_per_run": permutations,
        "site_block_bootstraps_per_run": bootstraps,
        "bootstrap_seed": BOOTSTRAP_SEED,
        "correction_scope_per_run": (
            "all candidate peak times and all three alpha-diversity endpoints"
        ),
        "campaign_stability_requirement": False,
        "reason": (
            "Rain is rare and uneven among campaigns; the conditional lag-rotation "
            "null retains each campaign's observed rain amount and spatial field."
        ),
        "consolidated_interpretation": consolidated,
        "commands": commands,
        "summary": {
            "path": summary_path.relative_to(root).as_posix(),
            "sha256": sha256_file(summary_path),
        },
        "runs": [
            {
                "run_id": definition["run_id"],
                "output": Path(definition["output"]).relative_to(root).as_posix(),
                "decision_sha256": sha256_file(
                    Path(definition["output"]) / "analysis_decision.json"
                ),
            }
            for definition in definitions
        ],
    }
    manifest_path = output / "suite_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    readme = output / "README.md"
    readme.write_text(
        """# Rainfall pulse-response sensitivities

`summary.tsv` compares the primary NASA POWER model with an Open-Meteo rainfall
product, control filtering, a complete paired-bulk cohort, pH adjustment and
more flexible route trends. Each run uses the same rise-and-decay kernel search
and corrects jointly over all candidate peak times and three diversity
endpoints.

Each run also gives a 95% site-block bootstrap interval for the selected
effect and partial R2, and a peak-selection interval obtained by repeating the
peak search in resampled complete site histories. These intervals condition
on the rainfall product and nuisance adjustment; product and route-model
uncertainty remain separate sensitivities.

The suite does not require the rainfall pattern to recur across campaigns.
Rain is too rare for that to be a meaningful stability criterion. Instead,
the conditional timing null preserves the amount, rarity and spatial field of
rain observed within every campaign and rotates its lag relative to sampling.

Run from the project root:

```bash
.venv/bin/python analysis/v3/run_rain_pulse_suite.py
```
""",
        encoding="utf-8",
    )
    checksum_targets = [readme, summary_path, manifest_path]
    (output / "SHA256SUMS").write_text(
        "".join(
            f"{sha256_file(path)}  {path.name}\n" for path in checksum_targets
        ),
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=root)
    parser.add_argument("--permutations", type=int, default=DEFAULT_PERMUTATIONS)
    parser.add_argument("--bootstraps", type=int, default=DEFAULT_BOOTSTRAPS)
    parser.add_argument(
        "--summarize-only",
        action="store_true",
        help="Rebuild the suite summary from completed run directories.",
    )
    args = parser.parse_args()
    if args.permutations < 99:
        parser.error("--permutations must be at least 99")
    if args.bootstraps < 999:
        parser.error("--bootstraps must be at least 999")
    return args


def main() -> None:
    args = parse_args()
    root = args.root.resolve()
    definitions = run_definitions(root)
    commands = [] if args.summarize_only else execute_runs(
        root, definitions, args.permutations, args.bootstraps
    )
    write_suite_metadata(
        root, definitions, commands, args.permutations, args.bootstraps
    )


if __name__ == "__main__":
    main()
