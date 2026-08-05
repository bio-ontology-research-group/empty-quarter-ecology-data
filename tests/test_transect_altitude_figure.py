from pathlib import Path

import pytest

from scripts.analysis.transect_altitude_figure import (
    haversine_km,
    read_profile,
    render,
    write_profile,
)


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data/metadata/geodata/site_altitudes.tsv"


def test_canonical_transect_profile_is_complete_and_grounded() -> None:
    rows = read_profile(SOURCE)
    assert [row["site"] for row in rows] == list(range(1, 61))
    assert rows[0]["distance_km"] == 0.0
    assert rows[-1]["distance_km"] == pytest.approx(
        1043.223055,
        abs=0.000001,
    )
    assert min(row["altitude_m"] for row in rows) == 73.0
    assert max(row["altitude_m"] for row in rows) == 975.0


def test_manuscript_distinguishes_cumulative_path_from_endpoint_distance() -> None:
    rows = read_profile(SOURCE)
    endpoint_distance = haversine_km(
        float(rows[0]["latitude"]),
        float(rows[0]["longitude"]),
        float(rows[-1]["latitude"]),
        float(rows[-1]["longitude"]),
    )
    assert endpoint_distance == pytest.approx(1014.649793, abs=0.000001)

    paper = ROOT / "data-paper"
    abstract = (paper / "sn-article.tex").read_text(encoding="utf-8")
    methods = (paper / "02_methods.tex").read_text(encoding="utf-8")
    assert "1,043~km cumulative path" in abstract
    assert "1,015~km end to end" in abstract
    assert "1,043-km\ncumulative path" in methods
    assert "1,015~km apart end to end" in methods
    assert "spanning 1,043 km" not in methods


def test_profile_and_figure_render_byte_deterministically(
    tmp_path: Path,
) -> None:
    rows = read_profile(SOURCE)
    first_profile = tmp_path / "first.tsv"
    second_profile = tmp_path / "second.tsv"
    first_figure = tmp_path / "first.png"
    second_figure = tmp_path / "second.png"

    write_profile(rows, first_profile)
    write_profile(rows, second_profile)
    render(rows, first_figure)
    render(rows, second_figure)

    assert first_profile.read_bytes() == second_profile.read_bytes()
    assert first_figure.read_bytes() == second_figure.read_bytes()
