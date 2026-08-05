import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
STAGE = (
    ROOT / "data-paper/zenodo"
    if (ROOT / "data-paper/zenodo").is_dir()
    else ROOT
)


def fields(path: Path) -> set[str]:
    with path.open(newline="", encoding="utf-8") as handle:
        return set(next(csv.reader(handle, delimiter="\t")))


def test_curated_release_tables_have_field_dictionary_coverage() -> None:
    dictionary_path = STAGE / "metadata/DATA_DICTIONARY.tsv"
    with dictionary_path.open(newline="", encoding="utf-8") as handle:
        dictionary = list(csv.DictReader(handle, delimiter="\t"))
    for relative in (
        "metadata/climate/monthly_weather_averages.tsv",
        "ontology/mapped_taxonomy_corrected.tsv",
    ):
        described = {
            row["field_or_pattern"]
            for row in dictionary
            if row["path"] == relative
        }
        assert fields(STAGE / relative) <= described
