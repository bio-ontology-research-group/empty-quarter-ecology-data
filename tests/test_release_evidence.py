from pathlib import Path

import pandas as pd
import pytest
from rdflib import Graph, Literal, URIRef

from scripts.release.build_release_evidence import (
    build_ledger,
    normalize_analysis_sample,
    resolve_sra_sample,
)


ROOT = Path(__file__).resolve().parents[1]
BASE = "https://rubalkhali.science/kb/"
DC_IDENTIFIER = URIRef("http://purl.org/dc/elements/1.1/identifier")
IS_DERIVED_FROM = URIRef(
    "http://semanticscience.org/resource/SIO_000244"
)
HAS_MEMBER = URIRef("http://semanticscience.org/resource/SIO_000059")
IS_OUTPUT_OF = URIRef("http://semanticscience.org/resource/SIO_000232")
IS_PART_OF = URIRef("http://semanticscience.org/resource/SIO_000068")
EXPECTED_TRIP1_SITE_ALIASES = {
    "61": (
        "Site water well (location 2)",
        f"{BASE}RAK_1000067",
    ),
    "62": ("Site road (location 1)", f"{BASE}RAK_1000068"),
    "63": ("Site road (location 2)", f"{BASE}RAK_1000069"),
    "64": ("Site camground", f"{BASE}RAK_1000070"),
}


def test_analysis_sample_prefix_is_removed():
    assert normalize_analysis_sample("e0325_10Dr2") == "10Dr2"
    assert normalize_analysis_sample("V4Dr3") == "V4Dr3"


def test_sra_alias_resolution_matches_generator_policy():
    known = {"V1Dr1", "V2Sr1"}
    assert resolve_sra_sample("V1Dr1O", known) == "V1Dr1"
    assert resolve_sra_sample("V2Sr3R", known) == "V2Sr1"
    assert resolve_sra_sample("not-a-sample", known) == ""


def test_current_release_evidence_is_internally_reconciled():
    if not (
        ROOT
        / "data/processed/taxonomy/taxon-tables/feature-table-trips1-5.tsv"
    ).is_file():
        pytest.skip("checksum-pinned bulk feature table is not installed")
    records, evidence, duplicate_profiles = build_ledger(ROOT)
    assert "generated_at_utc" not in evidence
    counts = evidence["source_counts"]
    generated = evidence["generated_kg_counts"]

    assert len(records) == counts["all_source_rows"]
    assert counts["sra_submission_rows"] == (
        counts["sra_resolved_rows"] + counts["sra_unresolved_rows"]
    )
    assert generated["fastq_datasets"] == counts["sra_resolved_rows"]
    assert generated["amplicon_libraries"] == counts["sra_resolved_rows"]
    assert generated["samples"] == counts["kg_sample_eligible_rows"]
    assert generated["dna_extracts"] == counts["dna_expected_by_generator"]
    assert counts["ecology_analysis_profiles"] <= counts["feature_table_profiles"]
    assert counts["ecology_unique_field_ids"] <= counts["ecology_analysis_profiles"]
    assert counts["ecology_primary_site_profiles"] == 1227
    assert counts["ecology_numeric_sites"] == 64
    assert counts["feature_duplicate_normalized_ids"] == 29
    assert counts["feature_duplicate_profile_pairs"] == 29
    assert counts["feature_exact_equal_profile_pairs"] == 0
    assert counts["ecology_duplicate_normalized_ids"] == 28
    assert len(duplicate_profiles) == 29
    assert not any(
        row["count_vectors_exactly_equal"] for row in duplicate_profiles
    )
    assert (
        counts["ecology_primary_site_profiles"]
        + counts["trip1_only_site_ecology_profiles"]
        == counts["ecology_analysis_profiles"]
    )

    ledger = pd.DataFrame(records)
    assert ledger["sample_id"].ne("").all()
    corrected = ledger[ledger["sample_id"].isin(["F46Dr2", "S46Dr2", "V46Dr2"])]
    assert set(corrected["site"]) == {"46"}
    assert corrected["site_corrected"].all()
    assert set(corrected["wgs_library_kit"]) == {"NEBNext"}

    trip1_only = ledger[
        ledger["campaign_role"] == "trip1_only_nonrevisited"
    ]
    assert set(trip1_only["site"]) == {"61", "62", "63", "64"}
    assert set(trip1_only["trip"]) == {"Trip1"}
    assert len(trip1_only) == counts["trip1_only_site_rows"] == 36
    assert not trip1_only["ecology_repeated_campaign_eligible"].any()
    assert trip1_only["site_alias_applied"].all()
    assert trip1_only["site_resolves_in_kg"].all()
    assert trip1_only["kg_sample_eligible"].all()
    assert set(trip1_only["kg_exclusion_reason"]) == {""}
    assert counts["confirmed_site_aliases"] == 4
    assert counts["site_alias_sample_rows"] == 36
    for source_site, (label, iri) in EXPECTED_TRIP1_SITE_ALIASES.items():
        rows = trip1_only[trip1_only["site"] == source_site]
        assert set(rows["canonical_site_label"]) == {label}
        assert set(rows["canonical_site_iri"]) == {iri}

    controls = ledger[ledger["is_control"]]
    assert not controls["kg_sample_eligible"].any()
    assert len(evidence["invalid_or_unresolved_sample_rows"]) == len(controls) == 34


def test_trip1_alias_samples_link_to_canonical_sites_and_visits():
    graph = Graph()
    graph.parse(
        ROOT
        / "data/processed/ontology/rubalkhali_samples.owl"
    )
    trip1_samples = pd.read_excel(
        ROOT / "data/metadata/samples/Sample_Mastersheet.xlsx",
        sheet_name="Trip1",
        dtype=str,
    ).fillna("")
    for source_site, (_, target_iri) in EXPECTED_TRIP1_SITE_ALIASES.items():
        sample_ids = set(
            trip1_samples.loc[
                trip1_samples["Site"].astype(str) == source_site,
                "Name",
            ].astype(str)
        )
        assert len(sample_ids) == 9
        for sample_id in sample_ids:
            subjects = set(
                graph.subjects(DC_IDENTIFIER, Literal(sample_id))
            )
            assert len(subjects) == 1
            subject = next(iter(subjects))
            assert (
                subject,
                IS_DERIVED_FROM,
                URIRef(target_iri),
            ) in graph
        # Coordinate resolution generates a named Trip1 visit for each
        # canonical site. Sample labels retain the numeric source identifier,
        # while the sampling process links to that visit.
        representative = next(
            graph.subjects(
                DC_IDENTIFIER,
                Literal(sorted(sample_ids)[0]),
            )
        )
        collections = set(graph.subjects(HAS_MEMBER, representative))
        assert len(collections) == 1
        processes = set(
            graph.objects(next(iter(collections)), IS_OUTPUT_OF)
        )
        assert len(processes) == 1
        assert any(graph.objects(next(iter(processes)), IS_PART_OF))


def test_curated_release_tables_have_field_dictionary_coverage():
    dictionary = pd.read_csv(
        ROOT / "data-paper/zenodo/metadata/DATA_DICTIONARY.tsv",
        sep="\t",
    )
    for relative in (
        "metadata/climate/monthly_weather_averages.tsv",
        "ontology/mapped_taxonomy_corrected.tsv",
    ):
        table = pd.read_csv(
            ROOT / "data-paper/zenodo" / relative,
            sep="\t",
            nrows=1,
        )
        described = set(
            dictionary.loc[
                dictionary["path"] == relative,
                "field_or_pattern",
            ]
        )
        assert set(table.columns) <= described
