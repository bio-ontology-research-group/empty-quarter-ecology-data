#!/usr/bin/env python3
"""Build the conservative, auditable Trips 1--5 taxonomy mapping.

The source of truth is the ordered seven-rank SILVA lineage.  Some Trip-5
records append an independent species assignment and confidence as fields
eight and nine; those fields are preserved in an audit ledger but never
promoted into the asserted lineage.

External identity is fail-closed.  An NCBI identifier is retained only when
an exact preferred label/synonym, rank, uniqueness, and all available
higher-rank NCBI ancestors agree.  Every other row receives a deterministic
lineage-and-rank-scoped project IRI.  No inherited identifier, lexical
equivalence, mixed-taxonomy synonym index, or global "last match wins" map is
used.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import tempfile
from collections import Counter
from dataclasses import dataclass
from html import escape as xml_escape
from pathlib import Path
from typing import Iterable, Sequence

from rdflib import Graph, OWL, RDF, RDFS, URIRef

try:
    from scripts.taxonomy.ncbi_index import (
        NCBI_PREFIX,
        IndexedTaxon,
        NcbiIndex,
        build_ncbi_index,
        norm_label,
        sha256,
    )
except ModuleNotFoundError:  # Nextflow stages this directory in isolation.
    from ncbi_index import (  # type: ignore[no-redef]
        NCBI_PREFIX,
        IndexedTaxon,
        NcbiIndex,
        build_ncbi_index,
        norm_label,
        sha256,
    )


SCHEMA_VERSION = "taxonomy-mapping-v1"
BASE = "https://rubalkhali.science/kb/"
CONTEXT_PREFIX = f"{BASE}RAK_CTX_"
ONTOLOGY_IRI = f"{BASE}ecosystem_module.owl"
SOURCE_LINEAGE_PROPERTY = f"{BASE}taxonomy_source_lineage"
SOURCE_NAME_PROPERTY = f"{BASE}taxonomy_source_name"
RANK_PROPERTY = f"{BASE}taxonomy_rank"
MAPPING_STATUS_PROPERTY = f"{BASE}taxonomy_mapping_status"
MAPPING_REASON_PROPERTY = f"{BASE}taxonomy_mapping_reason"
NCBI_RANK_PROPERTY = "http://purl.obolibrary.org/obo/ncbitaxon#has_rank"
RANKS = ("domain", "phylum", "class", "order", "family", "genus", "species")
OLD_RANKS = ("Kingdom", "Phylum", "Class", "Order", "Family", "Genus", "Species")
EXPECTED_NCBI_RANKS = {
    "domain": {"superkingdom", "domain"},
    "phylum": {"phylum"},
    "class": {"class"},
    "order": {"order"},
    "family": {"family"},
    "genus": {"genus"},
    "species": {"species"},
}
CONFIDENCE = re.compile(
    r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$"
)
RANK_PREFIX = re.compile(r"(?i)^[dkpcofgs]__")
NUMERIC_ID = re.compile(r"^\d+$")


def file_record(path: Path) -> dict[str, object]:
    return {
        "path": str(path),
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
    }


def output_record(path: Path) -> dict[str, object]:
    return {
        "file": path.name,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
    }


def canonical_segment(raw: str) -> str:
    value = RANK_PREFIX.sub("", raw.strip()).strip()
    if not value or value.lower() in {
        "na",
        "n/a",
        "unclassified",
        "uncultured",
    }:
        return "NA"
    return value


@dataclass(frozen=True)
class SourceRecord:
    feature_id: str
    lineage: tuple[str, ...]
    raw_taxon: str
    encoding: str
    supplementary_species: str
    confidence: str

    @property
    def taxon_string(self) -> str:
        return ";".join(self.lineage)


def parse_source_taxon(feature_id: str, raw: str) -> SourceRecord:
    fields = [field.strip() for field in raw.split(";")]
    supplementary_species = ""
    confidence = ""
    if len(fields) == 9 and CONFIDENCE.fullmatch(fields[8]):
        encoding = "seven_ranks_plus_species_assignment_and_confidence"
        supplementary_species = fields[7]
        confidence = fields[8]
        asserted = fields[:7]
    elif len(fields) == 7:
        encoding = "seven_ranks"
        asserted = fields
    else:
        raise ValueError(
            f"feature {feature_id!r}: expected seven ranks or seven ranks plus "
            f"supplementary species and numeric confidence; found "
            f"{len(fields)} fields in {raw!r}"
        )
    lineage = tuple(canonical_segment(value) for value in asserted)
    return SourceRecord(
        feature_id=feature_id,
        lineage=lineage,
        raw_taxon=raw,
        encoding=encoding,
        supplementary_species=supplementary_species,
        confidence=confidence,
    )


def read_source_taxonomy(
    path: Path,
) -> tuple[
    dict[str, tuple[str, ...]],
    set[tuple[str, ...]],
    list[SourceRecord],
    Counter[str],
]:
    feature_to_lineage: dict[str, tuple[str, ...]] = {}
    lineages: set[tuple[str, ...]] = set()
    supplementary: list[SourceRecord] = []
    encodings: Counter[str] = Counter()
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if not {"Feature ID", "Taxon"}.issubset(reader.fieldnames or ()):
            raise ValueError(
                f"{path}: expected Feature ID and Taxon columns, found "
                f"{reader.fieldnames}"
            )
        for row_number, row in enumerate(reader, start=2):
            feature_id = row["Feature ID"].strip()
            if not feature_id:
                raise ValueError(f"{path}:{row_number}: blank Feature ID")
            if feature_id in feature_to_lineage:
                raise ValueError(
                    f"{path}:{row_number}: duplicate Feature ID {feature_id!r}"
                )
            record = parse_source_taxon(feature_id, row["Taxon"])
            feature_to_lineage[feature_id] = record.lineage
            lineages.add(record.lineage)
            encodings[record.encoding] += 1
            asserted_species = record.lineage[6]
            extra = canonical_segment(record.supplementary_species)
            if (
                record.supplementary_species.strip()
                and extra != asserted_species
            ):
                supplementary.append(record)
    if not feature_to_lineage:
        raise ValueError(f"{path}: no source taxonomy records")
    return feature_to_lineage, lineages, supplementary, encodings


def read_feature_table(
    path: Path, source_features: set[str]
) -> tuple[int, int, set[str], set[str]]:
    """Return feature rows, profile columns, and source-missing feature IDs."""

    row_count = 0
    seen: set[str] = set()
    missing: set[str] = set()
    with path.open(encoding="utf-8") as handle:
        first = handle.readline()
        if not first:
            raise ValueError(f"{path}: empty feature table")
        header = handle.readline() if first.startswith("# Constructed") else first
        columns = header.rstrip("\r\n").split("\t")
        if not columns or columns[0] != "#OTU ID":
            raise ValueError(f"{path}: expected #OTU ID as the first column")
        profile_count = len(columns) - 1
        if profile_count <= 0:
            raise ValueError(f"{path}: feature table has no profile columns")
        for line_number, line in enumerate(handle, start=3):
            feature_id = line.split("\t", 1)[0].strip()
            if not feature_id:
                raise ValueError(
                    f"{path}:{line_number}: blank feature identifier"
                )
            if feature_id in seen:
                raise ValueError(
                    f"{path}:{line_number}: duplicate feature {feature_id!r}"
                )
            seen.add(feature_id)
            row_count += 1
            if feature_id not in source_features:
                missing.add(feature_id)
    if row_count == 0:
        raise ValueError(f"{path}: no feature rows")
    return row_count, profile_count, missing, seen


@dataclass(frozen=True)
class HistoricalCandidate:
    identifier: str
    is_project: bool
    is_inherited: bool
    name: str
    parent_identifier: str | None


def read_historical_mapping(
    path: Path,
) -> tuple[dict[tuple[str, str], HistoricalCandidate], int]:
    candidates: dict[tuple[str, str], HistoricalCandidate] = {}
    header_artifacts = 0
    last_explicit: dict[str, str] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        expected = {
            "Taxon String",
            "Rank",
            "Name",
            "Mapped ID",
            "Is RAK",
            "Is Inherited",
        }
        if set(reader.fieldnames or ()) != expected:
            raise ValueError(
                f"{path}: expected historical columns {sorted(expected)}, "
                f"found {reader.fieldnames}"
            )
        for row_number, row in enumerate(reader, start=2):
            try:
                rank = RANKS[OLD_RANKS.index(row["Rank"].strip())]
            except ValueError as error:
                raise ValueError(
                    f"{path}:{row_number}: invalid rank {row['Rank']!r}"
                ) from error
            raw_lineage = tuple(
                canonical_segment(value)
                for value in row["Taxon String"].split(";")
            )
            if (
                row["Taxon String"].strip() == "Taxon"
                and row["Rank"].strip() == "Kingdom"
                and row["Name"].strip() == "Taxon"
            ):
                # Historical preprocessing accidentally included the source
                # header as a one-rank project taxon.  It is not biological
                # evidence and is recorded by the audit, not mapped.
                header_artifacts += 1
                continue
            if len(raw_lineage) != 7:
                raise ValueError(
                    f"{path}:{row_number}: historical lineage has "
                    f"{len(raw_lineage)} ranks"
                )
            key = (";".join(raw_lineage), rank)
            if key in candidates:
                raise ValueError(
                    f"{path}:{row_number}: duplicate historical row {key}"
                )
            candidates[key] = HistoricalCandidate(
                identifier=row["Mapped ID"].strip(),
                is_project=row["Is RAK"].strip().lower() == "true",
                is_inherited=row["Is Inherited"].strip().lower() == "true",
                name=row["Name"].strip(),
                parent_identifier=last_explicit.get(key[0]),
            )
            if not candidates[key].is_inherited:
                last_explicit[key[0]] = candidates[key].identifier
    return candidates, header_artifacts


def stable_project_identifiers(
    historical: dict[tuple[str, str], HistoricalCandidate],
) -> set[str]:
    """Return explicit local IDs used in one rank/name/parent context."""

    contexts: dict[str, set[tuple[str, str, str | None]]] = {}
    for (_taxon_string, rank), item in historical.items():
        if not item.is_project or item.is_inherited:
            continue
        contexts.setdefault(item.identifier, set()).add(
            (rank, norm_label(item.name), item.parent_identifier)
        )
    return {
        identifier
        for identifier, observed in contexts.items()
        if len(observed) == 1
    }


def candidate_names(
    lineage: Sequence[str], rank_index: int
) -> set[str]:
    source_name = lineage[rank_index]
    if source_name == "NA":
        return set()
    if rank_index == 6 and " " not in source_name:
        genus = lineage[5]
        if genus == "NA":
            return set()
        # NCBI species labels are binomials.  Treating a bare epithet as an
        # exact name can select an unrelated homonym.
        names = {norm_label(f"{genus} {source_name}")}
    else:
        names = {norm_label(source_name)}
    return {name for name in names if name}


def contextual_iri(rank: str, source_lineage: str) -> str:
    payload = (
        f"{SCHEMA_VERSION}\0{rank}\0{source_lineage}".encode("utf-8")
    )
    return CONTEXT_PREFIX + hashlib.sha256(payload).hexdigest()[:24]


def contextual_label(
    lineage: Sequence[str], rank_index: int
) -> str:
    source_name = lineage[rank_index]
    if source_name != "NA":
        return source_name
    ancestor = next(
        (name for name in reversed(lineage[:rank_index]) if name != "NA"),
        "unresolved lineage",
    )
    return f"unclassified {RANKS[rank_index]} in {ancestor}"


def compatible_candidates(
    index: NcbiIndex,
    names: set[str],
    rank: str,
    preceding_ncbi: Sequence[str],
) -> list[IndexedTaxon]:
    candidates = index.candidates(names, EXPECTED_NCBI_RANKS[rank])
    return [
        item
        for item in candidates
        if all(index.is_descendant(item.identifier, ancestor) for ancestor in preceding_ncbi)
    ]


def reason_for_context(
    source_name: str,
    historical: HistoricalCandidate | None,
    all_candidates: Sequence[IndexedTaxon],
    compatible: Sequence[IndexedTaxon],
) -> str:
    if source_name == "NA":
        return "source rank is unclassified; inherited identifiers are not asserted"
    if historical is not None and historical.is_inherited:
        return "historical row inherited an ancestor identifier; inheritance was retired"
    if historical is not None and historical.is_project:
        return "historical project identifier was not lineage-scoped; replaced conservatively"
    if historical is not None and not NUMERIC_ID.fullmatch(historical.identifier):
        return "historical candidate identifier is not a valid NCBI numeric identifier"
    if not all_candidates:
        return "no exact rank-compatible NCBI preferred-label or synonym match"
    if not compatible:
        return "exact NCBI name candidates conflict with validated higher-rank ancestry"
    return (
        f"{len(compatible)} ancestry-compatible exact NCBI candidates remain; "
        "external identity is ambiguous"
    )


def build_mapping(
    lineages: Iterable[tuple[str, ...]],
    historical: dict[tuple[str, str], HistoricalCandidate],
    index: NcbiIndex,
    stable_project_ids: set[str],
) -> tuple[dict[str, list[dict[str, object]]], list[dict[str, object]]]:
    source_lineages = sorted(set(lineages))
    historical_by_prefix: dict[
        tuple[int, tuple[str, ...]], list[HistoricalCandidate]
    ] = {}
    for (taxon_string, rank), candidate in historical.items():
        rank_index = RANKS.index(rank)
        segments = tuple(taxon_string.split(";"))
        key = (rank_index, segments[: rank_index + 1])
        historical_by_prefix.setdefault(key, []).append(candidate)

    prefix_keys = {
        (rank_index, lineage[: rank_index + 1])
        for lineage in source_lineages
        for rank_index in range(len(RANKS))
    }
    prefix_rows: dict[
        tuple[int, tuple[str, ...]], dict[str, object]
    ] = {}
    prefix_meta: dict[
        tuple[int, tuple[str, ...]], dict[str, object]
    ] = {}
    contextual_contexts: dict[str, tuple[str, str]] = {}
    for rank_index, prefix in sorted(
        prefix_keys, key=lambda item: (item[0], item[1])
    ):
        rank = RANKS[rank_index]
        source_name = prefix[-1]
        source_lineage = ";".join(prefix)
        parent_row = (
            prefix_rows[(rank_index - 1, prefix[:-1])]
            if rank_index
            else None
        )
        parent_iri = (
            str(parent_row["iri"]) if parent_row is not None else None
        )
        preceding_ncbi = [
            str(prefix_rows[(ancestor_index, prefix[: ancestor_index + 1])][
                "iri"
            ]).removeprefix(NCBI_PREFIX)
            for ancestor_index in range(rank_index)
            if prefix_rows[(ancestor_index, prefix[: ancestor_index + 1])][
                "mapping_status"
            ]
            == "validated_ncbi"
        ]
        old_candidates = historical_by_prefix.get(
            (rank_index, prefix), []
        )
        historical_signatures = {
            (
                item.identifier,
                item.is_project,
                item.is_inherited,
                norm_label(item.name),
                item.parent_identifier,
            )
            for item in old_candidates
        }
        historical_conflict = len(historical_signatures) > 1
        old = (
            old_candidates[0]
            if old_candidates and not historical_conflict
            else None
        )
        original_ids = sorted(
            {item.identifier for item in old_candidates}
        )
        names = candidate_names(prefix, rank_index)
        all_candidates = (
            index.candidates(names, EXPECTED_NCBI_RANKS[rank])
            if names
            else []
        )
        compatible = [
            item
            for item in all_candidates
            if all(
                index.is_descendant(item.identifier, ancestor)
                for ancestor in preceding_ncbi
            )
        ]
        selected: IndexedTaxon | None = None
        if historical_conflict:
            mapping_status = "contextual"
            reason = (
                "shared canonical rank prefix has conflicting historical "
                "identifier, type, label, or parent evidence"
            )
        elif source_name == "NA" or (
            old is not None and old.is_inherited
        ):
            mapping_status = "contextual"
            reason = reason_for_context(
                source_name, old, all_candidates, compatible
            )
        elif (
            old is not None
            and old.is_project
            and old.identifier in stable_project_ids
        ):
            final_iri = BASE + old.identifier
            final_label = source_name
            mapping_status = "stable_project"
            reason = (
                "historical project identifier has one normalized "
                "rank/name/nearest-explicit-parent context"
            )
        elif old is not None and old.is_project:
            mapping_status = "contextual"
            reason = (
                "historical project identifier is reused in incompatible "
                "rank, label, or parent contexts"
            )
        elif old is not None:
            historical_record = (
                index.taxon(old.identifier)
                if NUMERIC_ID.fullmatch(old.identifier)
                else None
            )
            historical_valid = (
                historical_record is not None
                and historical_record.rank in EXPECTED_NCBI_RANKS[rank]
                and bool(historical_record.names & names)
                and all(
                    index.is_descendant(
                        historical_record.identifier, ancestor
                    )
                    for ancestor in preceding_ncbi
                )
            )
            if historical_valid:
                selected = historical_record
                mapping_status = "validated_ncbi"
                reason = (
                    "historical NCBI identifier resolves with exact "
                    "label/synonym, expected rank, and compatible "
                    "validated ancestry"
                )
            else:
                mapping_status = "contextual"
                if historical_record is None:
                    reason = (
                        "historical NCBI identifier is absent or invalid "
                        "in the pinned taxonomy"
                    )
                elif historical_record.rank not in EXPECTED_NCBI_RANKS[rank]:
                    reason = (
                        "historical NCBI identifier has the wrong rank"
                    )
                elif not (historical_record.names & names):
                    reason = (
                        "historical NCBI identifier has no exact source "
                        "label or synonym"
                    )
                else:
                    reason = (
                        "historical NCBI identifier conflicts with "
                        "validated higher-rank ancestry"
                    )
        elif len(compatible) == 1:
            selected = compatible[0]
            mapping_status = "validated_ncbi"
            reason = (
                "new lineage has one exact rank-compatible NCBI "
                "label/synonym match with compatible validated ancestry"
            )
        else:
            mapping_status = "contextual"
            reason = reason_for_context(
                source_name, old, all_candidates, compatible
            )

        if mapping_status == "validated_ncbi":
            assert selected is not None
            final_iri = NCBI_PREFIX + selected.identifier
            final_label = selected.label or source_name
        elif mapping_status == "contextual":
            final_iri = contextual_iri(rank, source_lineage)
            context = (rank, source_lineage)
            previous = contextual_contexts.setdefault(final_iri, context)
            if previous != context:
                raise ValueError(
                    f"contextual IRI collision: {final_iri} represents "
                    f"{previous} and {context}"
                )
            final_label = contextual_label(prefix, rank_index)
        display_component = (
            f"{OLD_RANKS[rank_index].replace('Kingdom', 'Domain')}: "
            f"{final_label}"
        )
        display_lineage = (
            f"{parent_row['lineage']}; {display_component}"
            if parent_row is not None
            else display_component
        )
        row = {
            "rank": rank,
            "source_name": source_name,
            "source_lineage": source_lineage,
            "lineage": display_lineage,
            "iri": final_iri,
            "label": final_label,
            "mapping_status": mapping_status,
            "reason": reason,
            "original_id": "|".join(original_ids) or None,
            "is_inherited": any(
                item.is_inherited for item in old_candidates
            ),
            "parent_iri": parent_iri,
        }
        prefix_rows[(rank_index, prefix)] = row
        prefix_meta[(rank_index, prefix)] = {
            "historical_candidate_id": "|".join(original_ids),
            "historical_candidate_type": (
                "conflict"
                if historical_conflict
                else "none"
                if old is None
                else "inherited"
                if old.is_inherited
                else "project"
                if old.is_project
                else "ncbi"
            ),
            "historical_prefix_evidence_count": len(old_candidates),
            "historical_prefix_conflict": historical_conflict,
            "candidate_names": "|".join(sorted(names)),
            "rank_compatible_candidate_count": len(all_candidates),
            "rank_compatible_candidate_ids": "|".join(
                item.identifier for item in all_candidates
            ),
            "ancestry_compatible_candidate_count": len(compatible),
            "ancestry_compatible_candidate_ids": "|".join(
                item.identifier for item in compatible
            ),
        }

    mapping: dict[str, list[dict[str, object]]] = {}
    for lineage in source_lineages:
        mapping[";".join(lineage)] = [
            dict(prefix_rows[(rank_index, lineage[: rank_index + 1])])
            for rank_index in range(len(RANKS))
        ]
    demoted_project_ids = stabilize_project_contexts(mapping)
    decisions: list[dict[str, object]] = []
    for taxon_string, rows in mapping.items():
        lineage = tuple(taxon_string.split(";"))
        for rank_index, row in enumerate(rows):
            meta = dict(
                prefix_meta[
                    (rank_index, lineage[: rank_index + 1])
                ]
            )
            if (
                row["mapping_status"] == "contextual"
                and row["original_id"] in demoted_project_ids
            ):
                meta["historical_candidate_type"] = (
                    "project_demoted_after_corrected_parent_audit"
                )
            decisions.append(
                {
                    "taxon_string": taxon_string,
                    "rank": row["rank"],
                    "source_name": row["source_name"],
                    "source_lineage": row["source_lineage"],
                    **meta,
                    "final_iri": row["iri"],
                    "final_label": row["label"],
                    "mapping_status": row["mapping_status"],
                    "reason": row["reason"],
                    "parent_iri": row["parent_iri"] or "",
                    "supplementary_species_policy": (
                        "provenance_only_never_promoted"
                    ),
                }
            )
    return mapping, decisions


def stabilize_project_contexts(
    mapping: dict[str, list[dict[str, object]]],
) -> set[str]:
    """Demote local IDs that acquire multiple corrected contexts.

    Correcting a parent can expose a collision not visible in the historical
    identifier table.  Demotion can in turn change a child's parent, so the
    audit is repeated to a fixed point.
    """

    demoted: set[str] = set()
    while True:
        contexts: dict[str, set[tuple[str, str, str | None]]] = {}
        for rows in mapping.values():
            for row in rows:
                if row["mapping_status"] != "stable_project":
                    continue
                contexts.setdefault(str(row["iri"]), set()).add(
                    (
                        str(row["rank"]),
                        norm_label(str(row["label"])),
                        (
                            str(row["parent_iri"])
                            if row["parent_iri"] is not None
                            else None
                        ),
                    )
                )
        collided = {
            iri for iri, observed in contexts.items() if len(observed) > 1
        }
        if not collided:
            return demoted
        demoted.update(iri.removeprefix(BASE) for iri in collided)
        for rows in mapping.values():
            segments = [str(row["source_name"]) for row in rows]
            for index_rank, row in enumerate(rows):
                if (
                    row["mapping_status"] == "stable_project"
                    and row["iri"] in collided
                ):
                    row["iri"] = contextual_iri(
                        str(row["rank"]), str(row["source_lineage"])
                    )
                    row["label"] = contextual_label(segments, index_rank)
                    row["mapping_status"] = "contextual"
                    row["reason"] = (
                        "historical project identifier acquired multiple "
                        "rank/label/corrected-parent contexts; demoted "
                        "fail-closed"
                    )
            parent: str | None = None
            display: list[str] = []
            for index_rank, row in enumerate(rows):
                row["parent_iri"] = parent
                parent = str(row["iri"])
                display.append(
                    f"{OLD_RANKS[index_rank].replace('Kingdom', 'Domain')}: "
                    f"{row['label']}"
                )
                row["lineage"] = "; ".join(display)


def write_mapping_json(
    path: Path, mapping: dict[str, list[dict[str, object]]]
) -> None:
    path.write_text(
        json.dumps(mapping, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def write_mapping_tsv(
    path: Path, mapping: dict[str, list[dict[str, object]]]
) -> None:
    columns = (
        "Taxon String",
        "Rank",
        "Name",
        "Mapped ID",
        "Is RAK",
        "Is Inherited",
    )
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, delimiter="\t")
        writer.writeheader()
        for taxon_string in sorted(mapping):
            for index, row in enumerate(mapping[taxon_string]):
                iri = str(row["iri"])
                writer.writerow(
                    {
                        "Taxon String": taxon_string,
                        "Rank": OLD_RANKS[index],
                        "Name": row["source_name"],
                        "Mapped ID": (
                            iri.removeprefix(NCBI_PREFIX)
                            if iri.startswith(NCBI_PREFIX)
                            else iri.removeprefix(BASE)
                        ),
                        "Is RAK": str(not iri.startswith(NCBI_PREFIX)),
                        "Is Inherited": "False",
                    }
                )


def write_decisions(path: Path, decisions: Sequence[dict[str, object]]) -> None:
    columns = tuple(decisions[0])
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, delimiter="\t")
        writer.writeheader()
        writer.writerows(decisions)


def write_supplementary_species_ledger(
    path: Path,
    supplementary: Sequence[SourceRecord],
    feature_table_features: set[str],
) -> Counter[str]:
    columns = (
        "feature_id",
        "raw_taxon",
        "canonical_seven_rank_lineage",
        "first7_species",
        "supplementary_species",
        "confidence",
        "disposition",
        "feature_table_present",
    )
    dispositions: Counter[str] = Counter()
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, delimiter="\t")
        writer.writeheader()
        for record in sorted(supplementary, key=lambda item: item.feature_id):
            disposition = (
                "conflict_preserved_not_promoted"
                if record.lineage[6] != "NA"
                else "extra_only_preserved_not_promoted"
            )
            dispositions[disposition] += 1
            writer.writerow(
                {
                    "feature_id": record.feature_id,
                    "raw_taxon": record.raw_taxon,
                    "canonical_seven_rank_lineage": record.taxon_string,
                    "first7_species": record.lineage[6],
                    "supplementary_species": record.supplementary_species,
                    "confidence": record.confidence,
                    "disposition": disposition,
                    "feature_table_present": str(
                        record.feature_id in feature_table_features
                    ).lower(),
                }
            )
    return dispositions


def turtle_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def local_module_rows(
    mapping: dict[str, list[dict[str, object]]]
) -> list[dict[str, object]]:
    unique: dict[str, dict[str, object]] = {}
    for rows in mapping.values():
        for row in rows:
            if row["mapping_status"] not in {
                "contextual",
                "stable_project",
            }:
                continue
            iri = str(row["iri"])
            signature = (
                str(row["rank"]),
                str(row["label"]),
                (
                    str(row["parent_iri"])
                    if row["parent_iri"] is not None
                    else None
                ),
                str(row["mapping_status"]),
            )
            if iri not in unique:
                unique[iri] = {
                    "iri": iri,
                    "rank": signature[0],
                    "label": signature[1],
                    "parent_iri": signature[2],
                    "mapping_status": signature[3],
                    "source_lineages": set(),
                    "source_names": set(),
                    "reasons": set(),
                }
            previous = unique[iri]
            previous_signature = (
                previous["rank"],
                previous["label"],
                previous["parent_iri"],
                previous["mapping_status"],
            )
            if previous_signature != signature:
                raise ValueError(
                    f"local module collision for {iri}: "
                    f"{previous_signature} versus {signature}"
                )
            previous["source_lineages"].add(str(row["source_lineage"]))
            previous["source_names"].add(str(row["source_name"]))
            previous["reasons"].add(str(row["reason"]))
    for row in unique.values():
        row["source_lineages"] = sorted(row["source_lineages"])
        row["source_names"] = sorted(row["source_names"])
        row["reasons"] = sorted(row["reasons"])
    return [unique[iri] for iri in sorted(unique)]


def ncbi_module_rows(
    mapping: dict[str, list[dict[str, object]]],
    index: NcbiIndex,
) -> list[dict[str, object]]:
    referenced = {
        str(row["iri"]).removeprefix(NCBI_PREFIX)
        for rows in mapping.values()
        for row in rows
        if row["mapping_status"] == "validated_ncbi"
    }
    closure = index.ancestor_closure(referenced)
    result: list[dict[str, object]] = []
    for identifier in sorted(closure, key=int):
        record = index.taxon(identifier)
        if record is None:
            raise ValueError(
                f"NCBI closure identifier {identifier} is not indexed"
            )
        parent = (
            record.parent
            if record.parent
            and record.parent != identifier
            and record.parent in closure
            else None
        )
        result.append(
            {
                "identifier": identifier,
                "iri": NCBI_PREFIX + identifier,
                "label": record.label,
                "rank_iri": record.rank_iri,
                "parent_iri": NCBI_PREFIX + parent if parent else None,
            }
        )
    return result


def _write_turtle_statements(
    handle: object,
    subject: str,
    statements: Sequence[tuple[str, str]],
) -> None:
    handle.write(f"<{subject}> ")  # type: ignore[attr-defined]
    for index, (predicate, value) in enumerate(statements):
        separator = " ;\n    " if index < len(statements) - 1 else " .\n\n"
        handle.write(  # type: ignore[attr-defined]
            f"{predicate} {value}{separator}"
        )


def write_turtle_module(
    path: Path,
    local_rows: Sequence[dict[str, object]],
    ncbi_rows: Sequence[dict[str, object]],
) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("@prefix owl: <http://www.w3.org/2002/07/owl#> .\n")
        handle.write(
            "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n\n"
        )
        handle.write(f"<{ONTOLOGY_IRI}> a owl:Ontology .\n")
        for property_iri in (
            SOURCE_LINEAGE_PROPERTY,
            SOURCE_NAME_PROPERTY,
            RANK_PROPERTY,
            MAPPING_STATUS_PROPERTY,
            MAPPING_REASON_PROPERTY,
        ):
            handle.write(
                f"<{property_iri}> a owl:AnnotationProperty .\n"
            )
        handle.write("\n")
        for row in ncbi_rows:
            statements: list[tuple[str, str]] = [
                ("a", "owl:Class"),
            ]
            if row["label"]:
                statements.append(
                    ("rdfs:label", turtle_string(str(row["label"])))
                )
            if row["parent_iri"]:
                statements.append(
                    ("rdfs:subClassOf", f"<{row['parent_iri']}>")
                )
            if row["rank_iri"]:
                statements.append(
                    (f"<{NCBI_RANK_PROPERTY}>", f"<{row['rank_iri']}>")
                )
            _write_turtle_statements(
                handle, str(row["iri"]), statements
            )
        for row in local_rows:
            statements = [
                ("a", "owl:Class"),
                ("rdfs:label", turtle_string(str(row["label"]))),
            ]
            parent = row["parent_iri"]
            if parent:
                statements.append(("rdfs:subClassOf", f"<{parent}>"))
            statements.extend(
                (
                    (f"<{RANK_PROPERTY}>", turtle_string(str(row["rank"]))),
                    (
                        f"<{MAPPING_STATUS_PROPERTY}>",
                        turtle_string(str(row["mapping_status"])),
                    ),
                )
            )
            for value in row["source_names"]:
                statements.append(
                    (f"<{SOURCE_NAME_PROPERTY}>", turtle_string(str(value)))
                )
            for value in row["source_lineages"]:
                statements.append(
                    (
                        f"<{SOURCE_LINEAGE_PROPERTY}>",
                        turtle_string(str(value)),
                    )
                )
            for value in row["reasons"]:
                statements.append(
                    (
                        f"<{MAPPING_REASON_PROPERTY}>",
                        turtle_string(str(value)),
                    )
                )
            _write_turtle_statements(
                handle, str(row["iri"]), statements
            )


def write_rdfxml_module(
    path: Path,
    local_rows: Sequence[dict[str, object]],
    ncbi_rows: Sequence[dict[str, object]],
) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        handle.write(
            '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" '
            'xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#" '
            'xmlns:owl="http://www.w3.org/2002/07/owl#" '
            'xmlns:ncbitaxon="http://purl.obolibrary.org/obo/ncbitaxon#" '
            f'xmlns:rak="{BASE}">\n'
        )
        handle.write(
            f'  <owl:Ontology rdf:about="{xml_escape(ONTOLOGY_IRI, quote=True)}"/>\n'
        )
        for property_iri in (
            SOURCE_LINEAGE_PROPERTY,
            SOURCE_NAME_PROPERTY,
            RANK_PROPERTY,
            MAPPING_STATUS_PROPERTY,
            MAPPING_REASON_PROPERTY,
        ):
            handle.write(
                "  <owl:AnnotationProperty "
                f'rdf:about="{xml_escape(property_iri, quote=True)}"/>\n'
            )
        for row in ncbi_rows:
            iri = xml_escape(str(row["iri"]), quote=True)
            handle.write(f'  <owl:Class rdf:about="{iri}">\n')
            if row["label"]:
                handle.write(
                    f"    <rdfs:label>{xml_escape(str(row['label']))}"
                    "</rdfs:label>\n"
                )
            if row["parent_iri"]:
                parent = xml_escape(str(row["parent_iri"]), quote=True)
                handle.write(
                    f'    <rdfs:subClassOf rdf:resource="{parent}"/>\n'
                )
            if row["rank_iri"]:
                rank_iri = xml_escape(str(row["rank_iri"]), quote=True)
                handle.write(
                    f'    <ncbitaxon:has_rank rdf:resource="{rank_iri}"/>\n'
                )
            handle.write("  </owl:Class>\n")
        for row in local_rows:
            iri = xml_escape(str(row["iri"]), quote=True)
            label = xml_escape(str(row["label"]))
            handle.write(f'  <owl:Class rdf:about="{iri}">\n')
            handle.write(f"    <rdfs:label>{label}</rdfs:label>\n")
            if row["parent_iri"]:
                parent = xml_escape(str(row["parent_iri"]), quote=True)
                handle.write(
                    f'    <rdfs:subClassOf rdf:resource="{parent}"/>\n'
                )
            handle.write(
                f"    <rak:taxonomy_rank>{xml_escape(str(row['rank']))}"
                "</rak:taxonomy_rank>\n"
            )
            handle.write(
                "    <rak:taxonomy_mapping_status>"
                f"{xml_escape(str(row['mapping_status']))}"
                "</rak:taxonomy_mapping_status>\n"
            )
            for value in row["source_names"]:
                handle.write(
                    "    <rak:taxonomy_source_name>"
                    f"{xml_escape(str(value))}"
                    "</rak:taxonomy_source_name>\n"
                )
            for value in row["source_lineages"]:
                handle.write(
                    "    <rak:taxonomy_source_lineage>"
                    f"{xml_escape(str(value))}"
                    "</rak:taxonomy_source_lineage>\n"
                )
            for value in row["reasons"]:
                handle.write(
                    "    <rak:taxonomy_mapping_reason>"
                    f"{xml_escape(str(value))}"
                    "</rak:taxonomy_mapping_reason>\n"
                )
            handle.write("  </owl:Class>\n")
        handle.write("</rdf:RDF>\n")


def validate_module_serializations(
    turtle_path: Path,
    rdfxml_path: Path,
    mapping: dict[str, list[dict[str, object]]],
    local_rows: Sequence[dict[str, object]],
    ncbi_rows: Sequence[dict[str, object]],
) -> dict[str, int]:
    turtle_graph = Graph().parse(turtle_path, format="turtle")
    rdfxml_graph = Graph().parse(rdfxml_path, format="xml")
    if set(turtle_graph) != set(rdfxml_graph):
        raise ValueError(
            "Turtle and RDF/XML ecosystem modules are not graph-equivalent"
        )
    forbidden = {
        OWL.equivalentClass,
        OWL.sameAs,
        URIRef("http://www.w3.org/2004/02/skos/core#closeMatch"),
    }
    if any(predicate in forbidden for _, predicate, _ in turtle_graph):
        raise ValueError("ecosystem module contains a forbidden identity axiom")
    expected_local = {URIRef(str(row["iri"])) for row in local_rows}
    expected_ncbi = {URIRef(str(row["iri"])) for row in ncbi_rows}
    referenced = {
        URIRef(str(row["iri"]))
        for rows in mapping.values()
        for row in rows
    }
    declared = set(turtle_graph.subjects(RDF.type, OWL.Class))
    if not expected_local | expected_ncbi <= declared:
        raise ValueError("ecosystem module omits expected class declarations")
    if not referenced <= declared:
        raise ValueError("ecosystem module omits a mapped class")
    for subject, parent in turtle_graph.subject_objects(RDFS.subClassOf):
        if str(subject).startswith(NCBI_PREFIX) and not str(parent).startswith(
            NCBI_PREFIX
        ):
            raise ValueError(
                f"NCBI class {subject} was reparented under local {parent}"
            )
    return {
        "triples": len(turtle_graph),
        "local_classes": len(expected_local),
        "ncbi_classes": len(expected_ncbi),
        "mapped_classes": len(referenced),
    }


def validate_mapping_contract(
    mapping: dict[str, list[dict[str, object]]],
    source_lineages: set[tuple[str, ...]],
    index: NcbiIndex,
) -> list[str]:
    errors: list[str] = []
    expected_keys = {";".join(lineage) for lineage in source_lineages}
    if set(mapping) != expected_keys:
        errors.append("corrected mapping keys do not exactly cover source lineages")
    seen_contexts: dict[str, tuple[str, str]] = {}
    prefix_decisions: dict[
        tuple[str, str], tuple[str, str, str]
    ] = {}
    for taxon_string, rows in mapping.items():
        segments = taxon_string.split(";")
        if len(rows) != 7:
            errors.append(f"{taxon_string}: expected seven rows")
            continue
        accepted_ncbi: list[str] = []
        for index_rank, row in enumerate(rows):
            if row["rank"] != RANKS[index_rank]:
                errors.append(f"{taxon_string}: rank order mismatch")
            if row["source_name"] != segments[index_rank]:
                errors.append(f"{taxon_string}: source-name mismatch")
            expected_source_lineage = ";".join(
                segments[: index_rank + 1]
            )
            if row["source_lineage"] != expected_source_lineage:
                errors.append(f"{taxon_string}: source-lineage mismatch")
            expected_parent = rows[index_rank - 1]["iri"] if index_rank else None
            if row["parent_iri"] != expected_parent:
                errors.append(f"{taxon_string}: parent_iri mismatch")
            expected_display = "; ".join(
                f"{OLD_RANKS[position].replace('Kingdom', 'Domain')}: "
                f"{rows[position]['label']}"
                for position in range(index_rank + 1)
            )
            if row["lineage"] != expected_display:
                errors.append(f"{taxon_string}: display-lineage mismatch")
            if not isinstance(row["is_inherited"], bool):
                errors.append(f"{taxon_string}: is_inherited is not boolean")
            iri = str(row["iri"])
            prefix_key = (str(row["rank"]), str(row["source_lineage"]))
            prefix_signature = (
                iri,
                str(row["mapping_status"]),
                str(row["label"]),
            )
            previous_prefix = prefix_decisions.setdefault(
                prefix_key, prefix_signature
            )
            if previous_prefix != prefix_signature:
                errors.append(
                    f"{taxon_string}: shared prefix has inconsistent decision"
                )
            if row["mapping_status"] == "validated_ncbi":
                identifier = iri.removeprefix(NCBI_PREFIX)
                record = index.taxon(identifier)
                if record is None:
                    errors.append(f"{taxon_string}: missing final NCBI identifier")
                    continue
                if record.rank not in EXPECTED_NCBI_RANKS[RANKS[index_rank]]:
                    errors.append(f"{taxon_string}: final NCBI rank mismatch")
                names = candidate_names(segments, index_rank)
                if not (record.names & names):
                    errors.append(f"{taxon_string}: final NCBI label mismatch")
                if not all(
                    index.is_descendant(identifier, ancestor)
                    for ancestor in accepted_ncbi
                ):
                    errors.append(f"{taxon_string}: final NCBI ancestry mismatch")
                accepted_ncbi.append(identifier)
            elif row["mapping_status"] == "contextual":
                expected = contextual_iri(
                    RANKS[index_rank], ";".join(segments[: index_rank + 1])
                )
                if iri != expected:
                    errors.append(f"{taxon_string}: unstable contextual IRI")
                context = (RANKS[index_rank], str(row["source_lineage"]))
                previous = seen_contexts.setdefault(iri, context)
                if previous != context:
                    errors.append(f"{taxon_string}: contextual IRI collision")
            elif row["mapping_status"] == "stable_project":
                if not iri.startswith(f"{BASE}RAK_") or iri.startswith(
                    CONTEXT_PREFIX
                ):
                    errors.append(
                        f"{taxon_string}: invalid stable project IRI"
                    )
            else:
                errors.append(f"{taxon_string}: unsupported mapping status")
    return errors


def write_sha256s(directory: Path) -> None:
    paths = sorted(
        path
        for path in directory.rglob("*")
        if path.is_file() and path.name != "SHA256SUMS"
    )
    with (directory / "SHA256SUMS").open(
        "w", encoding="utf-8", newline="\n"
    ) as handle:
        for path in paths:
            handle.write(f"{sha256(path)}  {path.relative_to(directory)}\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-taxonomy", type=Path, required=True)
    parser.add_argument("--feature-table", type=Path, required=True)
    parser.add_argument("--canonical-mapping", type=Path, required=True)
    parser.add_argument("--ncbi-taxonomy", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--audit-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    for path in (
        args.source_taxonomy,
        args.feature_table,
        args.canonical_mapping,
        args.ncbi_taxonomy,
    ):
        if not path.is_file():
            raise SystemExit(f"required input is not a file: {path}")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    args.audit_dir.mkdir(parents=True, exist_ok=True)

    (
        feature_to_lineage,
        source_lineages,
        supplementary,
        encodings,
    ) = read_source_taxonomy(args.source_taxonomy)
    (
        feature_rows,
        profiles,
        feature_missing,
        feature_table_features,
    ) = read_feature_table(
        args.feature_table, set(feature_to_lineage)
    )
    if feature_missing:
        raise SystemExit(
            f"feature table contains {len(feature_missing)} features absent "
            "from the source taxonomy"
        )
    historical, historical_header_artifacts = read_historical_mapping(
        args.canonical_mapping
    )
    stable_ids = stable_project_identifiers(historical)
    historical_explicit_project = [
        item
        for item in historical.values()
        if item.is_project and not item.is_inherited
    ]
    historical_stable_project_rows = sum(
        item.identifier in stable_ids
        for item in historical_explicit_project
    )
    historical_collided_project_ids = {
        item.identifier
        for item in historical_explicit_project
        if item.identifier not in stable_ids
    }

    corrected_json = args.output_dir / "mapped_taxonomy_corrected.json"
    corrected_tsv = args.output_dir / "mapped_taxonomy_corrected.tsv"
    decisions_tsv = args.audit_dir / "taxonomy_mapping_decisions.tsv"
    source_species_tsv = (
        args.audit_dir / "taxonomy_source_supplementary_species.tsv"
    )
    legacy_source_species_tsv = (
        args.audit_dir / "taxonomy_source_extra_species_audit.tsv"
    )
    module_owl = args.output_dir / "ecosystem_module.owl"
    module_ttl = args.output_dir / "ecosystem_module.ttl"

    wanted_names: set[str] = set()
    for lineage in source_lineages:
        for rank_index in range(7):
            wanted_names.update(candidate_names(lineage, rank_index))

    with tempfile.TemporaryDirectory(prefix="eq-ncbi-index-") as temp:
        index_path = Path(temp) / "ncbi.sqlite"
        with build_ncbi_index(
            args.ncbi_taxonomy, index_path, wanted_names
        ) as index:
            mapping, decisions = build_mapping(
                source_lineages, historical, index, stable_ids
            )
            errors = validate_mapping_contract(mapping, source_lineages, index)
            local_rows = local_module_rows(mapping)
            ncbi_rows = ncbi_module_rows(mapping, index)
            index_metadata = index.metadata()
    if errors:
        raise SystemExit(
            "corrected mapping failed its internal audit:\n"
            + "\n".join(f"- {error}" for error in errors[:50])
        )

    write_mapping_json(corrected_json, mapping)
    write_mapping_tsv(corrected_tsv, mapping)
    write_decisions(decisions_tsv, decisions)

    # Every feature-table feature is already proven to be a source feature.
    dispositions = write_supplementary_species_ledger(
        source_species_tsv, supplementary, feature_table_features
    )
    write_supplementary_species_ledger(
        legacy_source_species_tsv, supplementary, feature_table_features
    )
    write_turtle_module(module_ttl, local_rows, ncbi_rows)
    write_rdfxml_module(module_owl, local_rows, ncbi_rows)
    module_counts = validate_module_serializations(
        module_ttl, module_owl, mapping, local_rows, ncbi_rows
    )

    status_counts = Counter(
        str(row["mapping_status"])
        for rows in mapping.values()
        for row in rows
    )
    reasons = Counter(str(item["reason"]) for item in decisions)
    prefix_decisions = {
        (
            str(item["rank"]),
            str(item["source_lineage"]),
            str(item["final_iri"]),
            str(item["mapping_status"]),
            str(item["final_label"]),
        )
        for item in decisions
    }
    prefix_status_counts = Counter(
        status for _, _, _, status, _ in prefix_decisions
    )
    actual_stable_ids = {
        str(row["iri"]).removeprefix(BASE)
        for rows in mapping.values()
        for row in rows
        if row["mapping_status"] == "stable_project"
    }
    source_schema_report = {
        "status": "passed",
        "policy": {
            "canonical_assertion": "first seven ordered SILVA ranks",
            "supplementary_species": "provenance only; never promoted",
            "qiime_provenance": {
                "merge_action": "qiime2 feature-table merge_taxa",
                "merged_taxonomy_uuid": "642c0001-64af-4ff5-86ea-a9f75df0d133",
                "legacy_import_uuid": "09e2524d",
                "trip5_fixed_import_uuid": "6e85df16",
                "source_components": [
                    "ASV_tax.silva_138_2.tsv",
                    "ASV_tax_species.silva_138_2.tsv",
                ],
                "interpretation": (
                    "the appended field is a separate species assignment, "
                    "not an eighth taxonomic rank"
                ),
            },
        },
        "counts": {
            "source_rows": len(feature_to_lineage),
            "source_taxon_strings": len(source_lineages),
            "encodings": dict(sorted(encodings.items())),
            "supplementary_nonidentical_species_calls": len(supplementary),
            "supplementary_dispositions": dict(sorted(dispositions.items())),
            "feature_table_rows": feature_rows,
            "feature_table_profiles": profiles,
            "feature_table_features_missing_taxonomy": len(feature_missing),
            "source_features_absent_from_feature_table": len(
                set(feature_to_lineage) - feature_table_features
            ),
        },
        "inputs": {
            "source_taxonomy": file_record(args.source_taxonomy),
            "feature_table": file_record(args.feature_table),
        },
        "artifact": output_record(source_species_tsv),
    }
    source_schema_json = (
        args.audit_dir / "taxonomy_source_schema_audit.json"
    )
    source_schema_json.write_text(
        json.dumps(source_schema_report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    mapping_audit = {
        "status": "passed",
        "policy": {
            "external_identity": (
                "unique exact NCBI label/synonym + rank + compatible ancestry"
            ),
            "fallback": "deterministic lineage-and-rank contextual class",
            "inherited_identifiers": "retired",
            "gtdb_inaturalist_equivalence": "excluded",
        },
        "checks": {
            "coverage": {"status": "passed", "violations": 0},
            "rank": {"status": "passed", "violations": 0},
            "label": {"status": "passed", "violations": 0},
            "ancestry": {"status": "passed", "violations": 0},
            "contextual_iri_collisions": {
                "status": "passed",
                "violations": 0,
            },
            "supplementary_species_not_promoted": {
                "status": "passed",
                "violations": 0,
            },
            "shared_prefix_consistency": {
                "status": "passed",
                "violations": 0,
            },
            "ecosystem_module": {
                "status": "passed",
                "violations": 0,
                **module_counts,
            },
        },
        "counts": {
            "source_rows": len(feature_to_lineage),
            "source_taxon_strings": len(source_lineages),
            "mapping_rows": len(decisions),
            "unique_rank_prefix_decisions": len(prefix_decisions),
            "validated_ncbi_rows": status_counts["validated_ncbi"],
            "stable_project_rows": status_counts["stable_project"],
            "contextual_rows": status_counts["contextual"],
            "validated_ncbi_prefixes": prefix_status_counts[
                "validated_ncbi"
            ],
            "stable_project_prefixes": prefix_status_counts[
                "stable_project"
            ],
            "contextual_prefixes": prefix_status_counts["contextual"],
            "unique_final_ncbi_identifiers": len(
                {
                    str(row["iri"])
                    for rows in mapping.values()
                    for row in rows
                    if row["mapping_status"] == "validated_ncbi"
                }
            ),
            "unique_contextual_identifiers": sum(
                row["mapping_status"] == "contextual"
                for row in local_rows
            ),
            "unique_stable_project_identifiers": len(actual_stable_ids),
            "historical_stable_project_rows_before_parent_audit": (
                historical_stable_project_rows
            ),
            "historical_stable_project_identifiers_before_parent_audit": (
                len(stable_ids)
            ),
            "historical_collided_project_identifiers": len(
                historical_collided_project_ids
            ),
            "historical_collided_project_rows": sum(
                item.identifier in historical_collided_project_ids
                for item in historical_explicit_project
            ),
            "stable_project_identifiers_demoted_by_corrected_parent_audit": (
                len(stable_ids - actual_stable_ids)
            ),
            "historical_taxon_strings": len(
                {key[0] for key in historical}
            ),
            "historical_header_artifacts_quarantined": (
                historical_header_artifacts
            ),
            "decision_reasons": dict(sorted(reasons.items())),
            "violations": 0,
        },
        "ncbi_index": index_metadata,
        "inputs": {
            "historical_mapping": file_record(args.canonical_mapping),
            "ncbi_taxonomy": file_record(args.ncbi_taxonomy),
        },
        "artifacts": {
            "decision_ledger": output_record(decisions_tsv),
            "corrected_json": output_record(corrected_json),
            "corrected_tsv": output_record(corrected_tsv),
            "ecosystem_module_owl": output_record(module_owl),
            "ecosystem_module_ttl": output_record(module_ttl),
            "supplementary_species_ledger": output_record(
                source_species_tsv
            ),
            "legacy_supplementary_species_ledger": output_record(
                legacy_source_species_tsv
            ),
        },
    }
    mapping_audit_json = args.audit_dir / "taxonomy_mapping_audit.json"
    mapping_audit_json.write_text(
        json.dumps(mapping_audit, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "status": "passed",
        "policy": mapping_audit["policy"],
        "checks": mapping_audit["checks"],
        "counts": {
            "source_taxon_strings": len(source_lineages),
            "mapped_taxon_strings": len(mapping),
            "missing_taxon_strings": 0,
            "mapping_rows": len(decisions),
            "feature_table_rows": feature_rows,
            "feature_table_profiles": profiles,
            "feature_table_features_missing_taxonomy": 0,
            "validated_ncbi_rows": status_counts["validated_ncbi"],
            "stable_project_rows": status_counts["stable_project"],
            "contextual_rows": status_counts["contextual"],
            "unique_rank_prefix_decisions": len(prefix_decisions),
            "unique_stable_project_identifiers": len(actual_stable_ids),
            "supplementary_species_calls_preserved": len(supplementary),
            "historical_header_artifacts_quarantined": (
                historical_header_artifacts
            ),
            "ecosystem_module_local_classes": module_counts[
                "local_classes"
            ],
            "ecosystem_module_ncbi_classes": module_counts[
                "ncbi_classes"
            ],
        },
        "inputs": {
            "source_taxonomy": file_record(args.source_taxonomy),
            "feature_table": file_record(args.feature_table),
            "historical_mapping": file_record(args.canonical_mapping),
            "ncbi_taxonomy": file_record(args.ncbi_taxonomy),
        },
        "artifacts": {
            "corrected_json": output_record(corrected_json),
            "corrected_tsv": output_record(corrected_tsv),
            "ecosystem_module": output_record(module_owl),
            "ecosystem_module_ttl": output_record(module_ttl),
            "mapping_audit": output_record(mapping_audit_json),
            "decision_ledger": output_record(decisions_tsv),
            "source_schema_audit": output_record(source_schema_json),
            "supplementary_species_ledger": output_record(
                source_species_tsv
            ),
            "legacy_supplementary_species_ledger": output_record(
                legacy_source_species_tsv
            ),
        },
    }
    manifest_path = (
        args.output_dir / "mapped_taxonomy_corrected.manifest.json"
    )
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_sha256s(args.output_dir)
    write_sha256s(args.audit_dir)
    print(
        json.dumps(
            {
                "status": "passed",
                "source_taxon_strings": len(source_lineages),
                "mapping_rows": len(decisions),
                "validated_ncbi_rows": status_counts["validated_ncbi"],
                "stable_project_rows": status_counts["stable_project"],
                "contextual_rows": status_counts["contextual"],
                "supplementary_species_calls": len(supplementary),
                "manifest": str(manifest_path),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
