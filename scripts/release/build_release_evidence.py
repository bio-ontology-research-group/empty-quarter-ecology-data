#!/usr/bin/env python3
"""Build the cross-paper sample and release evidence ledger.

This script deliberately distinguishes source-record counts from generated-KG
counts and ecology-analysis counts.  It does not silently choose one of these
as the manuscript denominator.  Instead it emits the discrepancies that must
be resolved before a release is frozen.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import pandas as pd
import numpy as np
from rdflib import Graph, URIRef
from rdflib.namespace import RDF, RDFS


TRIP_SHEETS = ("Trip1", "Trip2", "Trip3", "Trip4", "Trip5")
CORE_SITES = {str(site) for site in range(1, 61)}
TRIP1_ONLY_SITES = {"61", "62", "63", "64"}
BASE = "https://rubalkhali.science/kb/"
DC_IDENTIFIER = URIRef("http://purl.org/dc/elements/1.1/identifier")
SAMPLE_CLASS = URIRef("http://semanticscience.org/resource/SIO_001418")
DNA_CLASS = URIRef(BASE + "RAK_0000040")
LIBRARY_CLASS = URIRef(BASE + "RAK_0000060")
FASTQ_CLASS = URIRef(BASE + "RAK_0000063")
GEO_AS_WKT = URIRef("http://www.opengis.net/ont/geosparql#asWKT")


def text(value: Any) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip()


def truthy(value: Any) -> bool:
    return text(value).lower() in {"true", "yes", "1", "y"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalize_analysis_sample(sample: str) -> str:
    """Remove the QIIME export prefix, retaining the field sample identifier."""
    return re.sub(r"^e\d+_", "", text(sample))


def read_feature_samples(path: Path) -> list[str]:
    with path.open(encoding="utf-8") as handle:
        first = handle.readline().rstrip("\n")
        header = first if "\t" in first else handle.readline().rstrip("\n")
    columns = header.split("\t")
    return [normalize_analysis_sample(item) for item in columns[1:] if text(item)]


def read_feature_profile_names(path: Path) -> tuple[list[str], int]:
    """Return original export-column names and the number of header rows."""
    with path.open(encoding="utf-8") as handle:
        first = handle.readline().rstrip("\n")
        second = handle.readline().rstrip("\n")
    if "\t" in first:
        header = first
        skiprows = 0
    elif "\t" in second:
        header = second
        skiprows = 1
    else:
        raise ValueError(f"No tabular header found in {path}")
    return [item for item in header.split("\t")[1:] if text(item)], skiprows


def read_ecology_profile_names(path: Path) -> list[str]:
    frame = pd.read_csv(path, sep="\t", dtype=str)
    sample_column = "Unnamed: 0" if "Unnamed: 0" in frame else frame.columns[0]
    return [text(item) for item in frame[sample_column]]


def read_ecology_samples(path: Path) -> list[str]:
    return [
        normalize_analysis_sample(item)
        for item in read_ecology_profile_names(path)
    ]


def audit_duplicate_profiles(
    feature_path: Path,
    ecology_path: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Compare export columns that collapse to the same field identifier.

    The ``e<digits>_`` prefix is removed for field-sample reconciliation, but
    the original columns may represent distinct profiles.  This audit tests
    their count vectors rather than assuming that repeated normalized IDs are
    identical copies or that they should be averaged.
    """
    profile_names, skiprows = read_feature_profile_names(feature_path)
    grouped: dict[str, list[str]] = defaultdict(list)
    for profile in profile_names:
        grouped[normalize_analysis_sample(profile)].append(profile)
    duplicate_groups = {
        sample_id: profiles
        for sample_id, profiles in grouped.items()
        if len(profiles) > 1
    }
    duplicate_columns = [
        profile
        for profiles in duplicate_groups.values()
        for profile in profiles
    ]
    ecology_names = set(read_ecology_profile_names(ecology_path))
    ecology_normalized = [
        normalize_analysis_sample(item) for item in ecology_names
    ]
    ecology_duplicate_groups = {
        sample_id: count
        for sample_id, count in Counter(ecology_normalized).items()
        if count > 1
    }
    if not duplicate_columns:
        return [], {
            "feature_duplicate_normalized_ids": 0,
            "feature_extra_profiles_from_repeated_ids": 0,
            "feature_exact_equal_profile_pairs": 0,
            "ecology_duplicate_normalized_ids": len(ecology_duplicate_groups),
            "ecology_extra_profiles_from_repeated_ids": sum(
                count - 1 for count in ecology_duplicate_groups.values()
            ),
        }

    frame = pd.read_csv(
        feature_path,
        sep="\t",
        skiprows=skiprows,
        usecols=duplicate_columns,
    )
    rows: list[dict[str, Any]] = []
    for sample_id, profiles in sorted(duplicate_groups.items()):
        for first, second in itertools.combinations(profiles, 2):
            first_values = frame[first].to_numpy(dtype=float)
            second_values = frame[second].to_numpy(dtype=float)
            union = (first_values > 0) | (second_values > 0)
            if (
                union.sum() > 1
                and np.std(first_values[union]) > 0
                and np.std(second_values[union]) > 0
            ):
                correlation = float(
                    np.corrcoef(
                        first_values[union],
                        second_values[union],
                    )[0, 1]
                )
            else:
                correlation = None
            rows.append(
                {
                    "normalized_sample_id": sample_id,
                    "profile_a": first,
                    "profile_b": second,
                    "profile_a_retained_in_ecology": first in ecology_names,
                    "profile_b_retained_in_ecology": second in ecology_names,
                    "depth_a": int(first_values.sum()),
                    "depth_b": int(second_values.sum()),
                    "nonzero_features_a": int((first_values > 0).sum()),
                    "nonzero_features_b": int((second_values > 0).sum()),
                    "shared_nonzero_features": int(
                        ((first_values > 0) & (second_values > 0)).sum()
                    ),
                    "count_vectors_exactly_equal": bool(
                        np.array_equal(first_values, second_values)
                    ),
                    "pearson_count_correlation_on_union": correlation,
                }
            )
    summary = {
        "feature_duplicate_normalized_ids": len(duplicate_groups),
        "feature_extra_profiles_from_repeated_ids": sum(
            len(profiles) - 1 for profiles in duplicate_groups.values()
        ),
        "feature_duplicate_profile_pairs": len(rows),
        "feature_exact_equal_profile_pairs": sum(
            row["count_vectors_exactly_equal"] for row in rows
        ),
        "ecology_duplicate_normalized_ids": len(ecology_duplicate_groups),
        "ecology_extra_profiles_from_repeated_ids": sum(
            count - 1 for count in ecology_duplicate_groups.values()
        ),
        "interpretation": (
            "Repeated normalized identifiers are distinct export profiles, "
            "not byte-identical count-vector copies. Their laboratory or "
            "sequencing mechanism is not documented, so they remain separate "
            "profiles and are aggregated only at the declared biological "
            "analysis unit."
        ),
    }
    return rows, summary


def read_ecology_sites(path: Path) -> list[str]:
    """Return the numeric site attached to every retained ecology profile."""
    frame = pd.read_csv(path, sep="\t", dtype=str)
    if "Site" not in frame:
        raise ValueError(f"Ecology analysis table has no Site column: {path}")
    return [text(item) for item in frame["Site"]]


def read_rdf_count(path: Path, class_iri: URIRef) -> int | None:
    if not path.exists():
        return None
    graph = Graph()
    graph.parse(path)
    return len(set(graph.subjects(RDF.type, class_iri)))


def site_records(path: Path) -> dict[str, dict[str, str]]:
    graph = Graph()
    graph.parse(path)
    records: dict[str, dict[str, str]] = {}
    for subject, label in graph.subject_objects(RDFS.label):
        value = str(label).strip()
        if value.startswith("Site "):
            key = value.removeprefix("Site ").strip()
            records[key] = {
                "label": value,
                "iri": str(subject),
                "wkt": text(next(graph.objects(subject, GEO_AS_WKT), "")),
            }
    return records


def load_site_aliases(
    root: Path,
    sites: dict[str, dict[str, str]],
) -> dict[tuple[str, str], dict[str, str]]:
    path = root / "data/metadata/samples/site_aliases.tsv"
    frame = pd.read_csv(path, sep="\t", dtype=str).fillna("")
    aliases: dict[tuple[str, str], dict[str, str]] = {}
    for _, row in frame.iterrows():
        if text(row["status"]).lower() != "confirmed":
            continue
        trip = text(row["source_sheet"])
        source_site = text(row["source_site_id"])
        target_label = text(row["canonical_site_label"])
        target_key = target_label.removeprefix("Site ").strip()
        target = sites.get(target_key)
        if not target:
            raise ValueError(
                f"Site alias {trip}/{source_site} targets missing label "
                f"{target_label!r}"
            )
        if target["iri"] != text(row["canonical_site_iri"]):
            raise ValueError(
                f"Site alias {trip}/{source_site} IRI disagrees with "
                f"{target_label!r}"
            )
        if target["wkt"] != text(row["canonical_wkt"]):
            raise ValueError(
                f"Site alias {trip}/{source_site} WKT disagrees with "
                f"{target_label!r}"
            )
        match = re.fullmatch(
            r"POINT\(([-+0-9.eE]+) ([-+0-9.eE]+)\)",
            target["wkt"],
        )
        if not match:
            raise ValueError(f"Unsupported canonical WKT: {target['wkt']}")
        longitude, latitude = map(float, match.groups())
        if (
            abs(latitude - float(row["source_latitude"])) > 1e-6
            or abs(longitude - float(row["source_longitude"])) > 1e-6
        ):
            raise ValueError(
                f"Site alias {trip}/{source_site} coordinates do not "
                f"identify {target_label!r}"
            )
        key = (trip, source_site)
        if key in aliases:
            raise ValueError(f"Duplicate confirmed site alias: {key}")
        if text(row["campaign_role"]) != "trip1_only_nonrevisited":
            raise ValueError(
                f"Site alias {trip}/{source_site} changed campaign role"
            )
        aliases[key] = {column: text(value) for column, value in row.items()}
    expected = {("Trip1", site) for site in TRIP1_ONLY_SITES}
    if set(aliases) != expected:
        raise ValueError(
            "Confirmed site-alias set must be exactly Trip1 sites 61–64; "
            f"observed {sorted(aliases)}"
        )
    return aliases


def load_corrections(root: Path) -> dict[tuple[str, str], dict[str, str]]:
    path = root / "data/metadata/samples/sample_corrections.tsv"
    if not path.exists():
        return {}
    frame = pd.read_csv(path, sep="\t", dtype=str).fillna("")
    confirmed = frame[frame["status"].str.lower() == "confirmed"]
    return {
        (text(row["sample_id"]), text(row["field"])): {
            "original_value": text(row["original_value"]),
            "corrected_value": text(row["corrected_value"]),
            "rationale": text(row["rationale"]),
        }
        for _, row in confirmed.iterrows()
    }


def load_sample_records(
    root: Path,
    sites: dict[str, dict[str, str]],
    aliases: dict[tuple[str, str], dict[str, str]],
) -> list[dict[str, Any]]:
    workbook = root / "data/metadata/samples/Sample_Mastersheet.xlsx"
    corrections = load_corrections(root)
    records: list[dict[str, Any]] = []
    for trip in TRIP_SHEETS:
        frame = pd.read_excel(workbook, sheet_name=trip, dtype=str)
        for row_number, row in frame.iterrows():
            sample_id = text(row.get("Name"))
            raw_site = text(row.get("Site"))
            site_fix = corrections.get((sample_id, "site"))
            site = site_fix["corrected_value"] if site_fix else raw_site
            compartment = text(row.get("Compartment"))
            is_control = bool(
                re.search(r"ctrl|control", sample_id, flags=re.I)
                or re.search(r"control", site, flags=re.I)
            )
            metadata_complete = bool(sample_id and site and compartment)
            if is_control:
                campaign_role = "laboratory_control"
            elif trip == "Trip1" and site in TRIP1_ONLY_SITES:
                campaign_role = "trip1_only_nonrevisited"
            elif site in CORE_SITES:
                campaign_role = "core_sites_1_60"
            else:
                campaign_role = "special_or_unresolved_site"
            site_alias = aliases.get((trip, site))
            resolved_site_key = (
                site_alias["canonical_site_label"]
                .removeprefix("Site ")
                .strip()
                if site_alias
                else site
            )
            site_record = sites.get(resolved_site_key)
            site_resolves = site_record is not None
            kg_eligible = bool(
                metadata_complete and not is_control and site_resolves
            )
            if is_control:
                kg_exclusion_reason = "control_requires_explicit_control_model"
            elif not metadata_complete:
                kg_exclusion_reason = "incomplete_sample_metadata"
            elif (
                trip == "Trip1"
                and site in TRIP1_ONLY_SITES
                and not site_resolves
            ):
                kg_exclusion_reason = (
                    "genuine_trip1_site_not_encoded_in_site_module"
                )
            elif not site_resolves:
                kg_exclusion_reason = "site_not_resolved_in_kg"
            else:
                kg_exclusion_reason = ""
            records.append(
                {
                    "source": "Sample_Mastersheet.xlsx",
                    "source_sheet": trip,
                    "source_row": row_number + 2,
                    "trip": trip,
                    "sample_id": sample_id,
                    "site": site,
                    "site_source_value": raw_site,
                    "site_corrected": bool(site_fix),
                    "site_alias_applied": bool(site_alias),
                    "canonical_site_label": (
                        site_record["label"] if site_record else ""
                    ),
                    "canonical_site_iri": (
                        site_record["iri"] if site_record else ""
                    ),
                    "compartment": compartment,
                    "is_control": is_control,
                    "campaign_role": campaign_role,
                    "ecology_repeated_campaign_eligible": bool(
                        not is_control and site in CORE_SITES
                    ),
                    "metadata_complete": metadata_complete,
                    "site_resolves_in_kg": site_resolves,
                    "kg_sample_eligible": kg_eligible,
                    "kg_exclusion_reason": kg_exclusion_reason,
                    "dna_status": text(row.get("DNA")),
                    "dna_kit": text(row.get("DNA Kit")),
                    "dna_concentration": text(row.get("DNA Conc.")),
                    "amplicon_flag": truthy(row.get("16S Sequencing")),
                    "amplicon_sequencer": text(row.get("16S Sequencer")),
                    "wgs_flag": truthy(row.get("WGS Sequencing")),
                    "wgs_library_kit": (
                        corrections[(sample_id, "wgs_library_kit")][
                            "corrected_value"
                        ]
                        if (sample_id, "wgs_library_kit") in corrections
                        else text(row.get("WGS Library Kit"))
                    ),
                }
            )

    plants = pd.read_csv(
        root / "data/metadata/samples/plants.tsv", sep="\t", dtype=str
    )
    for row_number, row in plants.iterrows():
        sample_id = text(row.get("Identifier"))
        site = text(row.get("Site"))
        trip = text(row.get("Trip"))
        compartment = text(row.get("Compartment"))
        metadata_complete = bool(sample_id and site and trip and compartment)
        site_record = sites.get(site)
        site_resolves = site_record is not None
        records.append(
            {
                "source": "plants.tsv",
                "source_sheet": "",
                "source_row": row_number + 2,
                "trip": trip,
                "sample_id": sample_id,
                "site": site,
                "site_source_value": site,
                "site_corrected": False,
                "site_alias_applied": False,
                "canonical_site_label": (
                    site_record["label"] if site_record else ""
                ),
                "canonical_site_iri": (
                    site_record["iri"] if site_record else ""
                ),
                "compartment": compartment,
                "is_control": False,
                "campaign_role": (
                    "core_sites_1_60"
                    if site in CORE_SITES
                    else "special_or_unresolved_site"
                ),
                "ecology_repeated_campaign_eligible": site in CORE_SITES,
                "metadata_complete": metadata_complete,
                "site_resolves_in_kg": site_resolves,
                "kg_sample_eligible": bool(metadata_complete and site_resolves),
                "kg_exclusion_reason": (
                    ""
                    if metadata_complete and site_resolves
                    else "incomplete_sample_metadata"
                    if not metadata_complete
                    else "site_not_resolved_in_kg"
                ),
                "dna_status": "",
                "dna_kit": "",
                "dna_concentration": "",
                "amplicon_flag": False,
                "amplicon_sequencer": "",
                "wgs_flag": False,
                "wgs_library_kit": "",
            }
        )
    return records


def resolve_sra_sample(sample_name: str, known_samples: set[str]) -> str:
    if sample_name in known_samples:
        return sample_name
    base = re.sub(r"(?:O|T|RE|R)$", "", sample_name)
    if base in known_samples:
        return base
    replicate_one = re.sub(r"r\d+$", "r1", base)
    return replicate_one if replicate_one in known_samples else ""


def build_ledger(
    root: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    ontology_dir = root / "data/processed/ontology"
    sites = site_records(ontology_dir / "rubalkhali_sites.owl")
    aliases = load_site_aliases(root, sites)
    records = load_sample_records(root, sites, aliases)
    known_samples = {
        row["sample_id"] for row in records if row["kg_sample_eligible"]
    }

    sra_path = root / "data/metadata/sra-submissions/submission-sheet.tsv"
    sra = pd.read_csv(sra_path, sep="\t", dtype=str)
    sra_run_counts: Counter[str] = Counter()
    unresolved_sra: list[dict[str, str]] = []
    for _, row in sra.iterrows():
        submitted_name = text(row.get("sample_name"))
        resolved_name = resolve_sra_sample(submitted_name, known_samples)
        if resolved_name:
            sra_run_counts[resolved_name] += 1
        else:
            unresolved_sra.append(
                {
                    "sample_name": submitted_name,
                    "run_accession": text(row.get("run_accession")),
                    "biosample_accession": text(row.get("biosample_accession")),
                }
            )

    feature_path = (
        root
        / "data/processed/taxonomy/taxon-tables/feature-table-trips1-5.tsv"
    )
    feature_profiles = read_feature_samples(feature_path)
    feature_samples = set(feature_profiles)
    ecology_path = root / "analysis/v2/review/cache/alpha.tsv"
    ecology_profiles = read_ecology_samples(ecology_path)
    ecology_sites = read_ecology_sites(ecology_path)
    if len(ecology_sites) != len(ecology_profiles):
        raise ValueError(
            "Ecology profile and site columns have different row counts"
        )
    ecology_samples = set(ecology_profiles)

    for row in records:
        sample_id = row["sample_id"]
        row["sra_run_count"] = sra_run_counts[sample_id]
        row["has_sra_run"] = bool(sra_run_counts[sample_id])
        row["in_feature_table"] = sample_id in feature_samples
        row["in_ecology_analysis"] = sample_id in ecology_samples
        row["dna_expected_by_generator"] = bool(
            row["source"] == "Sample_Mastersheet.xlsx"
            and (
                sample_id in set(sra["sample_name"].astype(str))
                or (
                    row["dna_status"]
                    and row["dna_status"].lower() != "false"
                )
            )
            and row["kg_sample_eligible"]
        )

    generated = {
        "samples": read_rdf_count(
            ontology_dir / "rubalkhali_samples.owl", SAMPLE_CLASS
        ),
        "dna_extracts": read_rdf_count(
            ontology_dir / "rubalkhali_dna.owl", DNA_CLASS
        ),
        "amplicon_libraries": read_rdf_count(
            ontology_dir / "rubalkhali_sra.owl", LIBRARY_CLASS
        ),
        "fastq_datasets": read_rdf_count(
            ontology_dir / "rubalkhali_sra.owl", FASTQ_CLASS
        ),
    }

    master = [row for row in records if row["source"] == "Sample_Mastersheet.xlsx"]
    plants = [row for row in records if row["source"] == "plants.tsv"]
    duplicate_profile_rows, duplicate_profile_summary = audit_duplicate_profiles(
        feature_path,
        ecology_path,
    )
    source_counts = {
        "master_rows": len(master),
        "master_controls": sum(row["is_control"] for row in master),
        "master_non_controls": sum(not row["is_control"] for row in master),
        "plant_rows": len(plants),
        "all_source_rows": len(records),
        "metadata_complete_rows": sum(row["metadata_complete"] for row in records),
        "kg_sample_eligible_rows": sum(row["kg_sample_eligible"] for row in records),
        "dna_expected_by_generator": sum(
            row["dna_expected_by_generator"] for row in records
        ),
        "sra_submission_rows": len(sra),
        "sra_unique_submitted_samples": sra["sample_name"].nunique(),
        "sra_resolved_rows": sum(sra_run_counts.values()),
        "sra_unresolved_rows": len(unresolved_sra),
        "feature_table_profiles": len(feature_profiles),
        "feature_table_unique_field_ids": len(feature_samples),
        "ecology_analysis_profiles": len(ecology_profiles),
        "ecology_unique_field_ids": len(ecology_samples),
        "ecology_primary_site_profiles": sum(
            site in CORE_SITES for site in ecology_sites
        ),
        "ecology_numeric_sites": len(
            {site for site in ecology_sites if site.isdigit()}
        ),
        **{
            key: value
            for key, value in duplicate_profile_summary.items()
            if key != "interpretation"
        },
        "trip1_only_site_rows": sum(
            row["campaign_role"] == "trip1_only_nonrevisited"
            for row in records
        ),
        "trip1_only_site_feature_profiles": sum(
            row["campaign_role"] == "trip1_only_nonrevisited"
            and row["in_feature_table"]
            for row in records
        ),
        "trip1_only_site_ecology_profiles": sum(
            row["campaign_role"] == "trip1_only_nonrevisited"
            and row["in_ecology_analysis"]
            for row in records
        ),
        "confirmed_site_aliases": len(aliases),
        "site_alias_sample_rows": sum(
            row["site_alias_applied"] for row in records
        ),
    }

    invalid_rows = [
        {
            "source": row["source"],
            "trip": row["trip"],
            "sample_id": row["sample_id"],
            "site": row["site"],
            "compartment": row["compartment"],
            "is_control": row["is_control"],
            "metadata_complete": row["metadata_complete"],
            "site_resolves_in_kg": row["site_resolves_in_kg"],
            "kg_exclusion_reason": row["kg_exclusion_reason"],
            "campaign_role": row["campaign_role"],
        }
        for row in records
        if not row["kg_sample_eligible"]
    ]
    duplicate_ids = {
        sample_id: count
        for sample_id, count in Counter(
            row["sample_id"] for row in records if row["sample_id"]
        ).items()
        if count > 1
    }
    evidence = {
        "schema_version": "1.0",
        "counting_policy": {
            "source_record": "One row in Sample_Mastersheet.xlsx or plants.tsv.",
            "kg_sample_eligible": (
                "A non-control source row with sample identifier, site, "
                "compartment and either a site label represented in "
                "rubalkhali_sites.owl or a confirmed coordinate-identity "
                "alias to an existing named site individual."
            ),
            "sra_record": "One row/run accession in submission-sheet.tsv.",
            "ecology_sample": "One row in analysis/v2/review/cache/alpha.tsv.",
            "ecology_primary_site_profile": (
                "One retained row in analysis/v2/review/cache/alpha.tsv whose "
                "Site value is an integer from 1 through 60."
            ),
            "trip1_only_nonrevisited": (
                "A genuine sample from numeric sites 61–64, which were sampled "
                "only in Trip 1 and omitted from the revisit frame because the "
                "regions were subsequently inaccessible."
            ),
        },
        "source_counts": source_counts,
        "site_alias_provenance": {
            "path": "data/metadata/samples/site_aliases.tsv",
            "sha256": sha256(
                root / "data/metadata/samples/site_aliases.tsv"
            ),
            "confirmed_aliases": len(aliases),
            "sample_rows_resolved_by_alias": source_counts[
                "site_alias_sample_rows"
            ],
            "policy": (
                "Aliases change only KG site and visit resolution. Numeric "
                "source site IDs and trip1_only_nonrevisited ecology status "
                "are preserved."
            ),
        },
        "generated_kg_counts": generated,
        "unresolved_sra_records": unresolved_sra,
        "invalid_or_unresolved_sample_rows": invalid_rows,
        "duplicate_source_sample_ids": duplicate_ids,
        "profile_duplicate_audit": duplicate_profile_summary,
        "discrepancies": {
            "source_vs_generated_samples": (
                source_counts["kg_sample_eligible_rows"] - (generated["samples"] or 0)
            ),
            "expected_vs_generated_dna": (
                source_counts["dna_expected_by_generator"]
                - (generated["dna_extracts"] or 0)
            ),
            "resolved_sra_vs_generated_fastq": (
                source_counts["sra_resolved_rows"]
                - (generated["fastq_datasets"] or 0)
            ),
            "feature_vs_ecology_profiles": (
                source_counts["feature_table_profiles"]
                - source_counts["ecology_analysis_profiles"]
            ),
        },
    }
    return records, evidence, duplicate_profile_rows


def release_manifest(root: Path, evidence: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = [
        "data/metadata/samples/Sample_Mastersheet.xlsx",
        "data/metadata/samples/plants.tsv",
        "data/metadata/samples/sample_corrections.tsv",
        "data/metadata/samples/site_aliases.tsv",
        "data/metadata/samples/environmental_measurement_corrections.tsv",
        "data/metadata/samplesheets/trip1-2023.tsv",
        "data/metadata/samplesheets/trip2-2023.tsv",
        "data/metadata/samplesheets/trip3-2024.tsv",
        "data/metadata/samplesheets/trip4-2024.tsv",
        "data/metadata/samplesheets/trip5-2025.tsv",
        "data/metadata/obsolete/Trip_Metadata.xlsx",
        "data/processed/metadata/environmental_measurements_curated.tsv",
        "data/processed/metadata/environmental_measurements_audit.json",
        "data/metadata/sra-submissions/submission-sheet.tsv",
        "data/metadata/sra-submissions/submission-sheet-trip5.tsv",
        "data/processed/taxonomy/taxon-tables/feature-table-trips1-5.tsv",
        "analysis/v2/review/cache/alpha.tsv",
        "data/processed/ontology/rubalkhali_sites.owl",
        "data/processed/ontology/rubalkhali_samples.owl",
        "data/processed/ontology/rubalkhali_measurements.owl",
        "data/processed/ontology/rubalkhali_dna.owl",
        "data/processed/ontology/rubalkhali_sra.owl",
        "data/processed/ontology/rubalkhali_xrf.owl",
    ]
    roles = {
        ".xlsx": "source metadata",
        ".tsv": "source or derived tabular data",
        ".owl": "generated knowledge-graph module",
    }
    manifest: list[dict[str, Any]] = []
    for relative in candidates:
        path = root / relative
        if not path.exists():
            continue
        manifest.append(
            {
                "path": relative,
                "role": roles.get(path.suffix.lower(), "release artifact"),
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
                "media_type": {
                    ".xlsx": (
                        "application/vnd.openxmlformats-officedocument."
                        "spreadsheetml.sheet"
                    ),
                    ".tsv": "text/tab-separated-values",
                    ".owl": "application/rdf+xml",
                    ".json": "application/json",
                }.get(path.suffix.lower(), "application/octet-stream"),
                "license": "PENDING_RELEASE_LICENSE",
            }
        )
    evidence["release_manifest_status"] = (
        "PRE-RELEASE: checksums describe the current local working data, not a "
        "published immutable release."
    )
    return manifest


def write_outputs(
    output_dir: Path,
    records: list[dict[str, Any]],
    evidence: dict[str, Any],
    manifest: list[dict[str, Any]],
    duplicate_profile_rows: list[dict[str, Any]],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = output_dir / "sample_ledger.tsv"
    with ledger_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(records[0]),
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(records)

    with (output_dir / "release_evidence.json").open(
        "w", encoding="utf-8"
    ) as handle:
        json.dump(evidence, handle, indent=2, sort_keys=True)
        handle.write("\n")

    with (output_dir / "release_manifest.tsv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(manifest[0]),
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(manifest)

    duplicate_columns = [
        "normalized_sample_id",
        "profile_a",
        "profile_b",
        "profile_a_retained_in_ecology",
        "profile_b_retained_in_ecology",
        "depth_a",
        "depth_b",
        "nonzero_features_a",
        "nonzero_features_b",
        "shared_nonzero_features",
        "count_vectors_exactly_equal",
        "pearson_count_correlation_on_union",
    ]
    with (output_dir / "profile_duplicate_audit.tsv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=duplicate_columns,
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(duplicate_profile_rows)

    summary = evidence["source_counts"]
    generated = evidence["generated_kg_counts"]
    lines = [
        "# Pre-release evidence summary",
        "",
        "These counts are generated from the current local sources. They are not "
        "a frozen release and should not be copied into either manuscript until "
        "the listed discrepancies are adjudicated.",
        "",
        "## Source and analysis counts",
        "",
    ]
    for key, value in summary.items():
        lines.append(f"- `{key}`: {value}")
    lines.extend(["", "## Current generated-KG counts", ""])
    for key, value in generated.items():
        lines.append(f"- `{key}`: {value}")
    lines.extend(["", "## Discrepancies requiring resolution", ""])
    for key, value in evidence["discrepancies"].items():
        lines.append(f"- `{key}`: {value}")
    lines.extend(
        [
            "",
            f"- Invalid/unresolved sample rows: "
            f"{len(evidence['invalid_or_unresolved_sample_rows'])}",
            f"- Unresolved SRA rows: "
            f"{len(evidence['unresolved_sra_records'])}",
            f"- Duplicate source identifiers: "
            f"{len(evidence['duplicate_source_sample_ids'])}",
            f"- Repeated normalized feature identifiers: "
            f"{evidence['profile_duplicate_audit']['feature_duplicate_normalized_ids']}; "
            f"exactly equal count-vector pairs: "
            f"{evidence['profile_duplicate_audit']['feature_exact_equal_profile_pairs']}",
            "",
        ]
    )
    (output_dir / "README.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="Empty Quarter repository root",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Output directory (default: <root>/data/release)",
    )
    args = parser.parse_args()
    root = args.root.resolve()
    output_dir = (
        args.output_dir.resolve()
        if args.output_dir
        else root / "data/release"
    )
    records, evidence, duplicate_profile_rows = build_ledger(root)
    environmental_audit_path = (
        root
        / "data/processed/metadata/environmental_measurements_audit.json"
    )
    environmental_audit = json.loads(
        environmental_audit_path.read_text(encoding="utf-8")
    )
    if environmental_audit.get("status") != "passed":
        raise ValueError(
            f"environmental metadata audit did not pass: "
            f"{environmental_audit_path}"
        )
    evidence["environmental_metadata_audit"] = environmental_audit
    manifest = release_manifest(root, evidence)
    write_outputs(
        output_dir,
        records,
        evidence,
        manifest,
        duplicate_profile_rows,
    )
    print(json.dumps(evidence["source_counts"], indent=2, sort_keys=True))
    print(json.dumps(evidence["generated_kg_counts"], indent=2, sort_keys=True))
    print(f"Wrote {output_dir}")


if __name__ == "__main__":
    main()
