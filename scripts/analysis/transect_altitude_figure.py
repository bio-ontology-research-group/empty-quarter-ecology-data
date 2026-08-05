#!/usr/bin/env python3
"""Build the data descriptor's transect-altitude figure deterministically."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import ft2font  # noqa: E402


EXPECTED_SITES = set(range(1, 61))
EXPECTED_FIGURE_RUNTIME = {
    "python": "3.11.14",
    "matplotlib": "3.9.4",
    "freetype": "2.14.3",
}


def require_figure_runtime() -> dict[str, str]:
    """Fail before canonical rendering when native font metrics differ."""
    observed = {
        "python": sys.version.split()[0],
        "matplotlib": matplotlib.__version__,
        "freetype": ft2font.__freetype_version__,
    }
    if observed != EXPECTED_FIGURE_RUNTIME:
        raise RuntimeError(
            "Figure runtime differs from environment/conda-linux-64.lock: "
            f"expected {EXPECTED_FIGURE_RUNTIME}, observed {observed}"
        )
    return observed


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def haversine_km(
    latitude_1: float,
    longitude_1: float,
    latitude_2: float,
    longitude_2: float,
) -> float:
    radius_km = 6371.0
    delta_latitude = math.radians(latitude_2 - latitude_1)
    delta_longitude = math.radians(longitude_2 - longitude_1)
    latitude_1_rad = math.radians(latitude_1)
    latitude_2_rad = math.radians(latitude_2)
    a = (
        math.sin(delta_latitude / 2) ** 2
        + math.cos(latitude_1_rad)
        * math.cos(latitude_2_rad)
        * math.sin(delta_longitude / 2) ** 2
    )
    return radius_km * 2 * math.asin(math.sqrt(a))


def read_profile(path: Path) -> list[dict[str, float | int]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        required = {"Site", "Latitude", "Longitude", "Altitude"}
        missing = required.difference(reader.fieldnames or ())
        if missing:
            raise ValueError(
                f"{path}: missing column(s): {', '.join(sorted(missing))}"
            )
        rows: list[dict[str, float | int]] = []
        for source_row, row in enumerate(reader, start=2):
            site_text = (row["Site"] or "").strip()
            if not site_text.isdigit():
                continue
            site = int(site_text)
            if site not in EXPECTED_SITES:
                continue
            try:
                latitude = float(row["Latitude"])
                longitude = float(row["Longitude"])
                altitude = float(row["Altitude"])
                if not all(
                    math.isfinite(value)
                    for value in (latitude, longitude, altitude)
                ):
                    raise ValueError("non-finite value")
                rows.append(
                    {
                        "site": site,
                        "latitude": latitude,
                        "longitude": longitude,
                        "altitude_m": altitude,
                    }
                )
            except (TypeError, ValueError) as error:
                raise ValueError(
                    f"{path}:{source_row}: invalid coordinate or altitude"
                ) from error

    sites = [int(row["site"]) for row in rows]
    if len(sites) != len(set(sites)):
        raise ValueError(f"{path}: duplicate primary-transect site")
    if set(sites) != EXPECTED_SITES:
        missing = sorted(EXPECTED_SITES.difference(sites))
        extra = sorted(set(sites).difference(EXPECTED_SITES))
        raise ValueError(
            f"{path}: primary-transect sites differ; "
            f"missing={missing}, extra={extra}"
        )
    rows.sort(key=lambda row: int(row["site"]))

    cumulative_distance = 0.0
    for index, row in enumerate(rows):
        if index:
            previous = rows[index - 1]
            cumulative_distance += haversine_km(
                float(previous["latitude"]),
                float(previous["longitude"]),
                float(row["latitude"]),
                float(row["longitude"]),
            )
        row["distance_km"] = cumulative_distance
    return rows


def write_profile(
    rows: list[dict[str, float | int]],
    path: Path,
) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(
            (
                "site",
                "latitude",
                "longitude",
                "altitude_m",
                "cumulative_distance_km",
            )
        )
        for row in rows:
            writer.writerow(
                (
                    row["site"],
                    f"{float(row['latitude']):.10f}",
                    f"{float(row['longitude']):.10f}",
                    f"{float(row['altitude_m']):.3f}",
                    f"{float(row['distance_km']):.6f}",
                )
            )


def render(
    rows: list[dict[str, float | int]],
    output: Path,
) -> None:
    matplotlib.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 10,
            "axes.titlesize": 12,
            "axes.labelsize": 10,
            "figure.dpi": 100,
            "savefig.dpi": 100,
        }
    )
    figure, axis = plt.subplots(figsize=(10, 5), dpi=100)
    distances = [float(row["distance_km"]) for row in rows]
    altitudes = [float(row["altitude_m"]) for row in rows]
    axis.plot(
        distances,
        altitudes,
        marker="o",
        linestyle="-",
        color="blue",
    )
    for row in rows:
        site = int(row["site"])
        if site == 1 or site % 10 == 0:
            axis.annotate(
                str(site),
                (float(row["distance_km"]), float(row["altitude_m"])),
                textcoords="offset points",
                xytext=(0, 10),
                ha="center",
            )
    axis.set_xlabel("Distance along transect (km)")
    axis.set_ylabel("Altitude (m)")
    axis.set_title("Altitude Profile of Rub al-Khali Transect (Sites 1-60)")
    axis.grid(True)
    figure.tight_layout()
    figure.savefig(
        output,
        format="png",
        metadata={"Software": "Empty Quarter reproducibility workflow"},
    )
    plt.close(figure)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    input_path = args.input.resolve()
    output_dir = args.output_dir.resolve()
    figure_runtime = require_figure_runtime()
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = read_profile(input_path)
    profile_path = output_dir / "transect_altitude_profile.tsv"
    figure_path = output_dir / "transect_altitude.png"
    write_profile(rows, profile_path)
    render(rows, figure_path)

    summary = {
        "schema_version": "1.0",
        "status": "passed",
        "input": {
            "file": input_path.name,
            "repository_path": (
                "data/metadata/geodata/site_altitudes.tsv"
            ),
            "bytes": input_path.stat().st_size,
            "sha256": sha256(input_path),
        },
        "cohort": {
            "site_range": "1-60",
            "sites": len(rows),
            "start_site": int(rows[0]["site"]),
            "end_site": int(rows[-1]["site"]),
        },
        "total_transect_distance_km": round(
            float(rows[-1]["distance_km"]), 6
        ),
        "altitude_m": {
            "minimum": min(float(row["altitude_m"]) for row in rows),
            "maximum": max(float(row["altitude_m"]) for row in rows),
        },
        "figure_runtime": {
            "schema_version": "figure-runtime-v1",
            **figure_runtime,
        },
        "outputs": {
            "figure": {
                "file": figure_path.name,
                "bytes": figure_path.stat().st_size,
                "sha256": sha256(figure_path),
            },
            "profile": {
                "file": profile_path.name,
                "bytes": profile_path.stat().st_size,
                "sha256": sha256(profile_path),
            },
        },
    }
    (output_dir / "transect_altitude_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        "PASS: generated 60-site transect profile; "
        f"distance={summary['total_transect_distance_km']:.2f} km"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
