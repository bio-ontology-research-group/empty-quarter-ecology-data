#!/usr/bin/env python3
"""Disk-backed, streaming index over the pinned NCBI Taxonomy OWL file."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from xml.etree import ElementTree as etree


NCBI_PREFIX = "http://purl.obolibrary.org/obo/NCBITaxon_"
OWL_CLASS = "{http://www.w3.org/2002/07/owl#}Class"
RDF_ABOUT = "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}about"
RDF_RESOURCE = (
    "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}resource"
)
RDFS_LABEL = "{http://www.w3.org/2000/01/rdf-schema#}label"
RDFS_SUBCLASS = "{http://www.w3.org/2000/01/rdf-schema#}subClassOf"
NCBI_RANK = "{http://purl.obolibrary.org/obo/ncbitaxon#}has_rank"
NUMERIC_ID = re.compile(r"\d+\Z")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def norm_label(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).strip().lower()
    value = re.sub(r"^[dkpcofgs]__", "", value)
    value = re.sub(r'^["\']|["\']$', "", value)
    value = re.sub(r"^(?:candidatus|ca\.)\s+", "", value)
    value = re.sub(r"\s+", " ", value)
    return value


@dataclass(frozen=True)
class IndexedTaxon:
    identifier: str
    label: str | None
    rank: str | None
    rank_iri: str | None
    parent: str | None
    names: frozenset[str]


class NcbiIndex:
    """Query interface for a temporary SQLite representation of NCBITaxon."""

    SCHEMA_VERSION = "ncbi-sqlite-v1"

    def __init__(self, path: Path):
        self.path = path
        self.connection = sqlite3.connect(str(path))
        self._ancestry_cache: dict[tuple[str, str], bool] = {}

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "NcbiIndex":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def metadata(self) -> dict[str, str]:
        return dict(self.connection.execute("SELECT key, value FROM metadata"))

    def taxon(self, identifier: str) -> IndexedTaxon | None:
        row = self.connection.execute(
            "SELECT identifier, label, rank, rank_iri, parent "
            "FROM taxa WHERE identifier = ?",
            (identifier,),
        ).fetchone()
        if row is None:
            return None
        names = frozenset(
            item[0]
            for item in self.connection.execute(
                "SELECT normalized_name FROM names WHERE identifier = ?",
                (identifier,),
            )
        )
        if row[1]:
            names = names | {norm_label(row[1])}
        return IndexedTaxon(
            identifier=str(row[0]),
            label=row[1],
            rank=row[2],
            rank_iri=row[3],
            parent=str(row[4]) if row[4] is not None else None,
            names=names,
        )

    def candidates(
        self, normalized_names: Iterable[str], expected_ranks: set[str]
    ) -> list[IndexedTaxon]:
        names = sorted(set(normalized_names))
        if not names:
            return []
        placeholders = ",".join("?" for _ in names)
        rank_placeholders = ",".join("?" for _ in expected_ranks)
        identifiers = {
            str(row[0])
            for row in self.connection.execute(
                "SELECT DISTINCT n.identifier FROM names n "
                "JOIN taxa t ON t.identifier = n.identifier "
                f"WHERE n.normalized_name IN ({placeholders}) "
                f"AND t.rank IN ({rank_placeholders})",
                (*names, *sorted(expected_ranks)),
            )
        }
        return [
            record
            for identifier in sorted(identifiers, key=int)
            if (record := self.taxon(identifier)) is not None
        ]

    def parent(self, identifier: str) -> str | None:
        row = self.connection.execute(
            "SELECT parent FROM taxa WHERE identifier = ?", (identifier,)
        ).fetchone()
        if row is None or row[0] is None:
            return None
        return str(row[0])

    def is_descendant(self, child: str, ancestor: str) -> bool:
        key = (child, ancestor)
        cached = self._ancestry_cache.get(key)
        if cached is not None:
            return cached
        current = child
        seen: set[str] = set()
        result = False
        while current and current not in seen:
            if current == ancestor:
                result = True
                break
            seen.add(current)
            current = self.parent(current)
        self._ancestry_cache[key] = result
        return result

    def ancestor_closure(self, identifiers: Iterable[str]) -> set[str]:
        closure: set[str] = set()
        for identifier in identifiers:
            current: str | None = identifier
            branch: set[str] = set()
            while current and current not in closure:
                if current in branch:
                    raise ValueError(
                        f"cycle in NCBI ancestry at NCBITaxon_{current}"
                    )
                branch.add(current)
                closure.add(current)
                current = self.parent(current)
        return closure


def wanted_names_digest(wanted_names: set[str]) -> str:
    digest = hashlib.sha256()
    for name in sorted(wanted_names):
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def _initialize(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        PRAGMA journal_mode=OFF;
        PRAGMA synchronous=OFF;
        PRAGMA temp_store=MEMORY;
        CREATE TABLE metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE taxa (
            identifier INTEGER PRIMARY KEY,
            parent INTEGER,
            label TEXT,
            rank TEXT,
            rank_iri TEXT
        );
        CREATE TABLE names (
            normalized_name TEXT NOT NULL,
            identifier INTEGER NOT NULL,
            UNIQUE (normalized_name, identifier)
        );
        CREATE INDEX names_by_identifier ON names(identifier);
        """
    )


def _cache_matches(
    database_path: Path,
    owl_path: Path,
    wanted_names: set[str],
) -> bool:
    if not database_path.exists():
        return False
    try:
        with sqlite3.connect(str(database_path)) as connection:
            metadata = dict(
                connection.execute("SELECT key, value FROM metadata")
            )
        return (
            metadata.get("schema_version") == NcbiIndex.SCHEMA_VERSION
            and metadata.get("owl_sha256") == sha256(owl_path)
            and metadata.get("wanted_names_sha256")
            == wanted_names_digest(wanted_names)
            and metadata.get("status") == "complete"
        )
    except (sqlite3.Error, OSError):
        return False


def build_ncbi_index(
    owl_path: Path,
    database_path: Path,
    wanted_names: Iterable[str],
) -> NcbiIndex:
    """Build or reuse a complete parent/rank index and focused name index."""

    wanted = {norm_label(name) for name in wanted_names if norm_label(name)}
    if _cache_matches(database_path, owl_path, wanted):
        return NcbiIndex(database_path)
    if database_path.exists():
        database_path.unlink()
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(database_path))
    _initialize(connection)
    owl_digest = hashlib.sha256()
    # Hashing separately makes the index construction logic easy to test and
    # avoids trusting file timestamps for cache validity.
    with owl_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            owl_digest.update(chunk)

    taxa_batch: list[tuple[int, int | None, str | None, str | None, str | None]] = []
    names_batch: list[tuple[str, int]] = []
    class_count = 0
    indexed_name_count = 0
    parser = etree.iterparse(str(owl_path), events=("start", "end"))
    stack: list[etree.Element] = []
    root: etree.Element | None = None
    for event, element in parser:
        if event == "start":
            stack.append(element)
            if root is None:
                root = element
            continue
        if element.tag == OWL_CLASS:
            about = element.get(RDF_ABOUT, "")
            if about.startswith(NCBI_PREFIX):
                identifier_text = about.removeprefix(NCBI_PREFIX)
                if NUMERIC_ID.fullmatch(identifier_text):
                    identifier = int(identifier_text)
                    parent: int | None = None
                    label: str | None = None
                    rank: str | None = None
                    rank_iri: str | None = None
                    names: set[str] = set()
                    for child in element:
                        resource = child.get(RDF_RESOURCE, "")
                        if child.tag == RDFS_LABEL and child.text:
                            label = child.text.strip()
                            names.add(norm_label(label))
                        elif child.tag == RDFS_SUBCLASS and resource.startswith(
                            NCBI_PREFIX
                        ):
                            parent_text = resource.removeprefix(NCBI_PREFIX)
                            if NUMERIC_ID.fullmatch(parent_text):
                                parent = int(parent_text)
                        elif child.tag == NCBI_RANK:
                            rank_iri = resource or None
                            rank = (
                                resource.rsplit("_", 1)[-1].lower()
                                if resource
                                else None
                            )
                        elif (
                            child.tag.rsplit("}", 1)[-1]
                            .lower()
                            .endswith("synonym")
                            and child.text
                        ):
                            names.add(norm_label(child.text.strip()))
                    taxa_batch.append(
                        (identifier, parent, label, rank, rank_iri)
                    )
                    for name in sorted(names & wanted):
                        names_batch.append((name, identifier))
                        indexed_name_count += 1
                    class_count += 1
        if len(stack) == 2 and root is not None:
            root.remove(element)
        stack.pop()
        if len(taxa_batch) >= 25_000:
            connection.executemany(
                "INSERT INTO taxa(identifier,parent,label,rank,rank_iri) "
                "VALUES (?,?,?,?,?)",
                taxa_batch,
            )
            connection.executemany(
                "INSERT OR IGNORE INTO names(normalized_name,identifier) "
                "VALUES (?,?)",
                names_batch,
            )
            connection.commit()
            taxa_batch.clear()
            names_batch.clear()
    if taxa_batch:
        connection.executemany(
            "INSERT INTO taxa(identifier,parent,label,rank,rank_iri) "
            "VALUES (?,?,?,?,?)",
            taxa_batch,
        )
        connection.executemany(
            "INSERT OR IGNORE INTO names(normalized_name,identifier) "
            "VALUES (?,?)",
            names_batch,
        )
    metadata = {
        "schema_version": NcbiIndex.SCHEMA_VERSION,
        "status": "complete",
        "owl_path": str(owl_path),
        "owl_sha256": owl_digest.hexdigest(),
        "wanted_names_sha256": wanted_names_digest(wanted),
        "wanted_names_count": str(len(wanted)),
        "numeric_class_count": str(class_count),
        "indexed_name_assertions": str(indexed_name_count),
    }
    connection.executemany(
        "INSERT INTO metadata(key,value) VALUES (?,?)",
        sorted(metadata.items()),
    )
    connection.commit()
    connection.close()
    return NcbiIndex(database_path)


def describe_index(index: NcbiIndex) -> str:
    return json.dumps(index.metadata(), sort_keys=True)
