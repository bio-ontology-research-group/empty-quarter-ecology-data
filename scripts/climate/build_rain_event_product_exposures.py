#!/usr/bin/env python3
"""Build four-day Trip 1 rainfall exposures from independent products.

The ecology analysis uses NASA POWER for the complete 1--60-day window scan.
This script provides a fixed-window product sensitivity for the selected
four-complete-day exposure.  It extracts nearest-grid estimates from CHIRPS,
CMORPH and IMERG raw files and combines them with the canonical POWER and
Open-Meteo resources already held by the project.

Raw satellite files are deliberately not copied into the repository.  Their
filenames, official download URLs, byte sizes and SHA-256 hashes are recorded
alongside the small derived exposure table.  Re-running the script against
byte-identical downloads must reproduce that table exactly.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib.util
import json
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

import h5py
import numpy as np
import pandas as pd
import rasterio
from rasterio.io import MemoryFile


ANALYSIS_DATE = "2026-08-04"
WINDOW_START = 1
WINDOW_END = 4
TRIP = 1
PRODUCT_METADATA = {
    "NASA_POWER_PRECTOTCORR": {
        "version": "NASA POWER daily point API snapshot",
        "resolution": "product grid returned by the point API",
        "units": "mm day-1",
        "source": "https://power.larc.nasa.gov/",
    },
    "Open_Meteo_precipitation_sum": {
        "version": "Open-Meteo historical API canonical snapshot",
        "resolution": "site-specific API response",
        "units": "mm day-1",
        "source": "https://open-meteo.com/",
    },
    "CHIRPS_v2.0": {
        "version": "CHIRPS v2.0 final daily",
        "resolution": "0.05 degree",
        "units": "mm day-1",
        "source": "https://www.chc.ucsb.edu/data/chirps",
    },
    "CMORPH_V1.0_ADJ": {
        "version": "CMORPH V1.0 bias-adjusted daily",
        "resolution": "0.25 degree",
        "units": "mm day-1",
        "source": "https://doi.org/10.25921/w9va-q159",
    },
    "GPM_3IMERGDF_07B": {
        "version": "GPM IMERG Final daily V07B",
        "resolution": "0.1 degree",
        "units": "mm day-1",
        "source": "https://doi.org/10.5067/GPM/IMERGDF/DAY/07",
    },
}


def load_rain_module(root: Path):
    path = root / "analysis/v3/rain_response_window.py"
    specification = importlib.util.spec_from_file_location(
        "rain_response_window_for_product_extraction", path
    )
    if specification is None or specification.loader is None:
        raise RuntimeError(f"Cannot load rainfall utilities from {path}")
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def date_from_filename(path: Path) -> pd.Timestamp:
    match = re.search(r"(20[0-9]{6})", path.name)
    if match is not None:
        return pd.to_datetime(match.group(1), format="%Y%m%d", errors="raise")
    dotted = re.search(r"(20[0-9]{2})\.([0-9]{2})\.([0-9]{2})", path.name)
    if dotted is not None:
        return pd.Timestamp(
            year=int(dotted.group(1)),
            month=int(dotted.group(2)),
            day=int(dotted.group(3)),
        )
    raise ValueError(f"No supported date in filename: {path.name}")


def required_dates(sites: pd.DataFrame) -> list[pd.Timestamp]:
    dates = {
        pd.Timestamp(row.Date) - pd.Timedelta(days=lag)
        for row in sites.itertuples(index=False)
        for lag in range(WINDOW_START, WINDOW_END + 1)
    }
    return sorted(dates)


def official_url(product: str, day: pd.Timestamp, filename: str) -> str:
    if product == "CHIRPS_v2.0":
        return (
            "https://data.chc.ucsb.edu/products/CHIRPS-2.0/"
            f"global_daily/tifs/p05/{day.year}/{filename}"
        )
    if product == "CMORPH_V1.0_ADJ":
        return (
            "https://www.ncei.noaa.gov/data/"
            "cmorph-high-resolution-global-precipitation-estimates/access/"
            f"daily/0.25deg/{day.year}/{day.month:02d}/{filename}"
        )
    if product == "GPM_3IMERGDF_07B":
        return (
            "https://data.gesdisc.earthdata.nasa.gov/data/GPM_L3/"
            f"GPM_3IMERGDF.07/{day.year}/{day.dayofyear:03d}/{filename}"
        )
    raise ValueError(f"No raw-file URL template for {product}")


def select_daily_files(
    directory: Path,
    glob_pattern: str,
    dates: Iterable[pd.Timestamp],
    *,
    minimum_size: int = 10_000,
) -> dict[pd.Timestamp, Path]:
    wanted = set(dates)
    candidates: dict[pd.Timestamp, list[Path]] = {day: [] for day in wanted}
    for path in sorted(directory.glob(glob_pattern)):
        if path.stat().st_size < minimum_size:
            continue
        day = date_from_filename(path)
        if day in wanted:
            candidates[day].append(path)
    selected: dict[pd.Timestamp, Path] = {}
    for day in sorted(wanted):
        matches = candidates[day]
        if len(matches) != 1:
            raise ValueError(
                f"Expected one usable {glob_pattern} file for {day.date()}, "
                f"found {[path.name for path in matches]}"
            )
        selected[day] = matches[0]
    return selected


def nearest_index(values: np.ndarray, target: float) -> int:
    return int(np.abs(np.asarray(values, dtype=float) - float(target)).argmin())


def extract_chirps(path: Path, sites: pd.DataFrame) -> tuple[np.ndarray, list[str]]:
    with gzip.open(path, "rb") as handle:
        payload = handle.read()
    with MemoryFile(payload) as memory_file, memory_file.open() as raster:
        coordinates = [
            (float(row.Longitude), float(row.Latitude))
            for row in sites.itertuples(index=False)
        ]
        values = np.asarray([float(value[0]) for value in raster.sample(coordinates)])
        grid_ids: list[str] = []
        for longitude, latitude in coordinates:
            row, column = raster.index(longitude, latitude)
            x, y = raster.xy(row, column)
            grid_ids.append(f"CHIRPS_{float(y):.5f}_{float(x):.5f}")
    if np.any(~np.isfinite(values)) or np.any(values < 0):
        raise ValueError(f"Invalid CHIRPS precipitation in {path}")
    return values, grid_ids


def extract_cmorph(path: Path, sites: pd.DataFrame) -> tuple[np.ndarray, list[str]]:
    with h5py.File(path, "r") as handle:
        latitude = np.asarray(handle["lat"][:], dtype=float)
        longitude = np.asarray(handle["lon"][:], dtype=float)
        raw = handle["cmorph"]
        scale = float(np.asarray(raw.attrs["scale_factor"]).reshape(-1)[0])
        missing = int(np.asarray(raw.attrs["missing_value"]).reshape(-1)[0])
        values: list[float] = []
        grid_ids: list[str] = []
        for row in sites.itertuples(index=False):
            latitude_index = nearest_index(latitude, row.Latitude)
            longitude_index = nearest_index(longitude, row.Longitude % 360.0)
            value = int(raw[0, latitude_index, longitude_index])
            if value == missing:
                raise ValueError(f"Missing CMORPH value in {path} for site {row.Site}")
            values.append(value * scale)
            grid_ids.append(
                f"CMORPH_{latitude[latitude_index]:.3f}_"
                f"{longitude[longitude_index]:.3f}"
            )
    result = np.asarray(values, dtype=float)
    if np.any(~np.isfinite(result)) or np.any(result < 0):
        raise ValueError(f"Invalid CMORPH precipitation in {path}")
    return result, grid_ids


def extract_imerg(path: Path, sites: pd.DataFrame) -> tuple[np.ndarray, list[str]]:
    with h5py.File(path, "r") as handle:
        latitude = np.asarray(handle["lat"][:], dtype=float)
        longitude = np.asarray(handle["lon"][:], dtype=float)
        raw = handle["precipitation"]
        fill = float(np.asarray(raw.attrs["_FillValue"]).reshape(-1)[0])
        values: list[float] = []
        grid_ids: list[str] = []
        for row in sites.itertuples(index=False):
            latitude_index = nearest_index(latitude, row.Latitude)
            longitude_index = nearest_index(longitude, row.Longitude)
            value = float(raw[0, longitude_index, latitude_index])
            if math.isclose(value, fill):
                raise ValueError(f"Missing IMERG value in {path} for site {row.Site}")
            values.append(value)
            grid_ids.append(
                f"IMERG_{latitude[latitude_index]:.2f}_"
                f"{longitude[longitude_index]:.2f}"
            )
    result = np.asarray(values, dtype=float)
    if np.any(~np.isfinite(result)) or np.any(result < 0):
        raise ValueError(f"Invalid IMERG precipitation in {path}")
    return result, grid_ids


def raw_product_exposures(
    product: str,
    files: dict[pd.Timestamp, Path],
    sites: pd.DataFrame,
    extractor: Callable[[Path, pd.DataFrame], tuple[np.ndarray, list[str]]],
) -> tuple[np.ndarray, list[str], list[dict[str, Any]]]:
    daily: dict[pd.Timestamp, np.ndarray] = {}
    daily_grid_ids: dict[pd.Timestamp, list[str]] = {}
    sources: list[dict[str, Any]] = []
    for day, path in sorted(files.items()):
        daily[day], daily_grid_ids[day] = extractor(path, sites)
        sources.append(
            {
                "product_id": product,
                "date": str(day.date()),
                "filename": path.name,
                "byte_size": path.stat().st_size,
                "sha256": sha256_file(path),
                "official_url": official_url(product, day, path.name),
            }
        )
    exposure = np.empty(len(sites), dtype=float)
    grid_ids: list[str] = []
    for index, row in enumerate(sites.itertuples(index=False)):
        days = [
            pd.Timestamp(row.Date) - pd.Timedelta(days=lag)
            for lag in range(WINDOW_START, WINDOW_END + 1)
        ]
        identifiers = {daily_grid_ids[day][index] for day in days}
        if len(identifiers) != 1:
            raise ValueError(f"{product} grid cell changed across days for site {row.Site}")
        exposure[index] = sum(float(daily[day][index]) for day in days)
        grid_ids.append(identifiers.pop())
    return exposure, grid_ids, sources


def canonical_product_exposure(
    sites: pd.DataFrame, weather: Any, rain_module: Any
) -> tuple[np.ndarray, list[str]]:
    values = rain_module.exposure_matrix(
        sites, weather, ((WINDOW_START, WINDOW_END),)
    )[:, 0]
    return values, [weather.grid_ids[int(site)] for site in sites["Site"]]


def exposure_rows(
    sites: pd.DataFrame,
    product: str,
    values: np.ndarray,
    grid_ids: list[str],
) -> list[dict[str, Any]]:
    metadata = PRODUCT_METADATA[product]
    rows: list[dict[str, Any]] = []
    for row, value, grid_id in zip(sites.itertuples(index=False), values, grid_ids):
        rows.append(
            {
                "trip": TRIP,
                "site": int(row.Site),
                "collection_date": str(pd.Timestamp(row.Date).date()),
                "latitude": float(row.Latitude),
                "longitude": float(row.Longitude),
                "window_start_complete_days": WINDOW_START,
                "window_end_complete_days": WINDOW_END,
                "product_id": product,
                "product_version": metadata["version"],
                "product_resolution": metadata["resolution"],
                "grid_id": grid_id,
                "precipitation_mm": float(value),
                "extraction_method": "nearest product grid cell",
            }
        )
    return rows


def run(args: argparse.Namespace) -> None:
    root = args.root.resolve()
    rain = load_rain_module(root)
    sites = rain.load_geodata(root)
    sites = sites[sites["Trip"] == TRIP].sort_values("Site").reset_index(drop=True)
    if sites["Site"].tolist() != list(range(1, 61)):
        raise ValueError("Trip 1 geodata must contain the ordered 60-site route")
    dates = required_dates(sites)

    power = rain.load_nasa(args.power)
    open_meteo = rain.load_open_meteo(args.open_meteo)
    rows: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    for product, weather in (
        ("NASA_POWER_PRECTOTCORR", power),
        ("Open_Meteo_precipitation_sum", open_meteo),
    ):
        values, grid_ids = canonical_product_exposure(sites, weather, rain)
        rows.extend(exposure_rows(sites, product, values, grid_ids))
        sources.append(
            {
                "product_id": product,
                "date": f"{dates[0].date()}..{dates[-1].date()}",
                "filename": args.power.name if product.startswith("NASA") else args.open_meteo.name,
                "byte_size": weather.source_path.stat().st_size,
                "sha256": sha256_file(weather.source_path),
                "official_url": PRODUCT_METADATA[product]["source"],
            }
        )

    raw_specs = (
        (
            "CHIRPS_v2.0",
            args.chirps_dir,
            "chirps-v2.0.*.tif.gz",
            extract_chirps,
        ),
        (
            "CMORPH_V1.0_ADJ",
            args.cmorph_dir,
            "CMORPH_V1.0_ADJ_0.25deg-DLY_00Z_*.nc",
            extract_cmorph,
        ),
        (
            "GPM_3IMERGDF_07B",
            args.imerg_dir,
            "3B-DAY.MS.MRG.3IMERG.*.V07B.nc4",
            extract_imerg,
        ),
    )
    for product, directory, pattern, extractor in raw_specs:
        files = select_daily_files(directory, pattern, dates)
        values, grid_ids, product_sources = raw_product_exposures(
            product, files, sites, extractor
        )
        rows.extend(exposure_rows(sites, product, values, grid_ids))
        sources.extend(product_sources)

    exposure = pd.DataFrame(rows).sort_values(["product_id", "site"])
    if len(exposure) != 5 * 60 or exposure["precipitation_mm"].isna().any():
        raise ValueError("The product exposure table is incomplete")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    exposure.to_csv(args.output, sep="\t", index=False, lineterminator="\n")
    source_frame = pd.DataFrame(sources).sort_values(["product_id", "date", "filename"])
    source_frame.to_csv(args.sources, sep="\t", index=False, lineterminator="\n")

    manifest = {
        "schema_version": "1.0",
        "analysis_date": ANALYSIS_DATE,
        "created_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "estimand": "Trip 1 rain during four complete calendar days before collection",
        "window_start_complete_days": WINDOW_START,
        "window_end_complete_days": WINDOW_END,
        "sampling_day_included": False,
        "spatial_extraction": "nearest product grid cell",
        "products": PRODUCT_METADATA,
        "output": {
            "path": args.output.resolve().relative_to(root).as_posix(),
            "sha256": sha256_file(args.output),
            "n_records": len(exposure),
        },
        "source_ledger": {
            "path": args.sources.resolve().relative_to(root).as_posix(),
            "sha256": sha256_file(args.sources),
            "n_records": len(source_frame),
        },
    }
    args.manifest.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=root)
    parser.add_argument(
        "--power",
        type=Path,
        default=root / "data/processed/climate/nasa_power_daily_precipitation.tsv.gz",
    )
    parser.add_argument(
        "--open-meteo",
        type=Path,
        default=root / "data/processed/climate/daily_weather_canonical.tsv",
    )
    parser.add_argument("--chirps-dir", type=Path, required=True)
    parser.add_argument("--cmorph-dir", type=Path, required=True)
    parser.add_argument("--imerg-dir", type=Path, required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=root / "data/processed/climate/rain_event_product_exposures.tsv",
    )
    parser.add_argument(
        "--sources",
        type=Path,
        default=root / "data/processed/climate/rain_event_product_sources.tsv",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=root / "data/processed/climate/rain_event_product_exposures.manifest.json",
    )
    return parser.parse_args()


if __name__ == "__main__":
    run(parse_args())
