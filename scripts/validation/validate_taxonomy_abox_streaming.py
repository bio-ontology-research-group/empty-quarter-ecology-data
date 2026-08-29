#!/usr/bin/env python3
"""Fail-closed, memory-bounded validation of the taxonomy ABox.

The taxonomy ABox is too large to load into an in-memory RDF graph.  This
validator therefore performs two independent, complete passes:

1. Raptor ``rapper`` parses the entire file as Turtle in count-only mode.
   A non-zero exit status, warning/error, or missing triple count fails the
   gate.
2. A constant-state scanner reads every source byte and every OWLAPI-formatted
   Turtle triple.  It checks the generated process, dataset, abundance-quality
   and abundance-value records, including reciprocal links and sequence
   continuity.  Order-independent multiset fingerprints compare relationships
   whose two directions occur far apart in the file.

This is full Turtle syntax validation plus project-specific structural
validation.  It is deliberately *not* described as full ShEx validation.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass, field
import hashlib
import json
import math
import os
from pathlib import Path
import re
import resource
import shutil
import subprocess
import tempfile
import time
from typing import Any


BASE = "https://rubalkhali.science/kb/"
RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
RDFS = "http://www.w3.org/2000/01/rdf-schema#"
OWL = "http://www.w3.org/2002/07/owl#"
SIO = "http://semanticscience.org/resource/"
PATO = "http://purl.obolibrary.org/obo/PATO_"
XSD = "http://www.w3.org/2001/XMLSchema#"

RDF_TYPE = RDF + "type"
RDFS_LABEL = RDFS + "label"
OWL_NAMED_INDIVIDUAL = OWL + "NamedIndividual"
SIO_HAS_ATTRIBUTE = SIO + "SIO_000008"
SIO_IS_ATTRIBUTE_OF = SIO + "SIO_000011"
SIO_HAS_MEMBER = SIO + "SIO_000059"
SIO_IS_MEASUREMENT_VALUE_OF = SIO + "SIO_000215"
SIO_HAS_MEASUREMENT_VALUE = SIO + "SIO_000216"
SIO_HAS_OUTPUT = SIO + "SIO_000229"
SIO_HAS_INPUT = SIO + "SIO_000230"
SIO_IS_SPECIFIED_BY = SIO + "SIO_000339"

WORKFLOW_CLASS = BASE + "RAK_0000071"
RELATIVE_QUALITY_CLASS = BASE + "RAK_0000072"
RELATIVE_VALUE_CLASS = BASE + "RAK_0000073"
ABSOLUTE_DATASET_CLASS = BASE + "RAK_0000074"
RELATIVE_DATASET_CLASS = BASE + "RAK_0000075"
ABSOLUTE_VALUE_CLASS = BASE + "RAK_0000076"
ABSOLUTE_QUALITY_CLASS = BASE + "RAK_0000078"
AMOUNT_QUALITY_CLASS = PATO + "0000070"
CONCENTRATION_QUALITY_CLASS = PATO + "0000033"
RELATIVE_VALUE_PROPERTY = BASE + "RAK_2000020"
LINEAGE_PROPERTY = BASE + "RAK_2000025"
ABSOLUTE_VALUE_PROPERTY = BASE + "RAK_2000026"
PROTOCOL_IRI = BASE + "RAK_L000012"
XSD_DOUBLE = XSD + "double"

PROCESS_START = 290001
DATASET_START = 7740001
RANKS = ("Domain", "Phylum", "Class", "Order", "Family", "Genus", "Species")

PROCESS_RE = re.compile(rf"^{re.escape(BASE)}RAK_P(\d{{6}})$")
DATASET_RE = re.compile(rf"^{re.escape(BASE)}RAK_(77[45]\d{{4}})$")
QUALITY_RE = re.compile(rf"^{re.escape(BASE)}RAK_Q(\d{{8}})$")
VALUE_RE = re.compile(rf"^{re.escape(BASE)}RAK_V(\d{{8}})$")
FASTQ_RE = re.compile(rf"^{re.escape(BASE)}RAK_(779\d{{4}})$")
RAPPER_COUNT_RE = re.compile(r"Parsing returned ([0-9]+) triples")
LITERAL_RE = re.compile(
    r'^"((?:[^"\\]|\\.)*)"(?:@([A-Za-z0-9-]+)|\^\^(.+))?$'
)

PREFIXES = {
    "rdf": RDF,
    "rdfs": RDFS,
    "owl": OWL,
    "xsd": XSD,
    "xml": "http://www.w3.org/XML/1998/namespace",
}
PREDICATE_QNAMES = {"rdf:type", "rdfs:label", "owl:imports"}
LITERAL_PREDICATES = {
    RDFS_LABEL,
    LINEAGE_PROPERTY,
    ABSOLUTE_VALUE_PROPERTY,
    RELATIVE_VALUE_PROPERTY,
}
MASK128 = (1 << 128) - 1


class MultisetFingerprint:
    """Order-independent, constant-memory fingerprint of a string multiset."""

    __slots__ = ("count", "total", "xor")

    def __init__(self) -> None:
        self.count = 0
        self.total = 0
        self.xor = 0

    def add(self, value: str) -> None:
        digest = hashlib.blake2b(
            value.encode("utf-8"), digest_size=16
        ).digest()
        number = int.from_bytes(digest, "big")
        self.count += 1
        self.total = (self.total + number) & MASK128
        self.xor ^= number

    def as_dict(self) -> dict[str, Any]:
        return {
            "count": self.count,
            "sum_blake2b128_mod_2_128": f"{self.total:032x}",
            "xor_blake2b128": f"{self.xor:032x}",
        }

    def equals(self, other: "MultisetFingerprint") -> bool:
        return (
            self.count == other.count
            and self.total == other.total
            and self.xor == other.xor
        )


@dataclass
class SubjectBlock:
    subject: str
    kind: str
    number: int | None = None
    predicates: Counter[str] = field(default_factory=Counter)
    types: set[str] = field(default_factory=set)
    output_objects: list[str] = field(default_factory=list)
    input_objects: list[str] = field(default_factory=list)
    protocol_objects: list[str] = field(default_factory=list)
    bearer_objects: list[str] = field(default_factory=list)
    measurement_objects: list[str] = field(default_factory=list)
    inverse_measurement_objects: list[str] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)
    lineages: list[str] = field(default_factory=list)
    absolute_values: list[tuple[str, str | None]] = field(default_factory=list)
    relative_values: list[tuple[str, str | None]] = field(default_factory=list)
    member_count: int = 0
    has_attribute_count: int = 0


class TaxonomyABoxScanner:
    def __init__(self, max_examples: int = 25) -> None:
        self.max_examples = max_examples
        self.violation_counts: Counter[str] = Counter()
        self.violation_examples: list[dict[str, Any]] = []
        self.warning_counts: Counter[str] = Counter()
        self.warning_examples: list[dict[str, Any]] = []
        self.line_number = 0
        self.bytes_read = 0
        self.lines_read = 0
        self.triples_scanned = 0
        self.subject_blocks = 0
        self.sha256 = hashlib.sha256()
        self.current: SubjectBlock | None = None
        self.current_predicate: str | None = None

        self.category_counts: Counter[str] = Counter()
        self.selected_predicate_counts: Counter[str] = Counter()
        self.next_numbers = {
            "process": PROCESS_START,
            "dataset": DATASET_START,
            "quality": 1,
            "value": 1,
        }

        self.attribute_forward = MultisetFingerprint()
        self.attribute_inverse = MultisetFingerprint()
        self.value_forward = MultisetFingerprint()
        self.value_inverse = MultisetFingerprint()
        self.dataset_members = MultisetFingerprint()
        self.value_subjects = MultisetFingerprint()
        self.process_outputs = MultisetFingerprint()
        self.dataset_subjects = MultisetFingerprint()
        self.process_inputs = MultisetFingerprint()
        self.fastq_subjects = MultisetFingerprint()
        self.members_by_kind_rank = {
            (kind, rank): MultisetFingerprint()
            for kind in ("Absolute", "Relative")
            for rank in RANKS
        }
        self.values_by_kind_rank = {
            (kind, rank): MultisetFingerprint()
            for kind in ("Absolute", "Relative")
            for rank in RANKS
        }

        self.numeric = {
            "absolute": {
                "count": 0,
                "minimum": None,
                "maximum": None,
                "sum": 0.0,
            },
            "relative": {
                "count": 0,
                "minimum": None,
                "maximum": None,
                "sum": 0.0,
            },
        }
        self.protocol_subject_seen = False

    def violation(
        self, code: str, message: str, subject: str | None = None
    ) -> None:
        self.violation_counts[code] += 1
        if len(self.violation_examples) < self.max_examples:
            self.violation_examples.append(
                {
                    "code": code,
                    "line": self.line_number,
                    "subject": subject,
                    "message": message,
                }
            )

    def warning(
        self, code: str, message: str, subject: str | None = None
    ) -> None:
        self.warning_counts[code] += 1
        if len(self.warning_examples) < self.max_examples:
            self.warning_examples.append(
                {
                    "code": code,
                    "line": self.line_number,
                    "subject": subject,
                    "message": message,
                }
            )

    @staticmethod
    def expand(token: str) -> str:
        token = token.strip()
        if token.startswith("<") and token.endswith(">"):
            return token[1:-1]
        if ":" in token:
            prefix, local = token.split(":", 1)
            if prefix in PREFIXES:
                return PREFIXES[prefix] + local
        return token

    @staticmethod
    def first_token(text: str) -> tuple[str, str]:
        text = text.lstrip()
        if not text:
            raise ValueError("missing token")
        if text.startswith("<"):
            end = text.find(">")
            if end < 0:
                raise ValueError("unterminated IRI token")
            return text[: end + 1], text[end + 1 :].lstrip()
        match = re.match(r"(\S+)(?:\s+(.*))?$", text)
        if not match:
            raise ValueError("cannot split token")
        return match.group(1), (match.group(2) or "")

    def parse_literal(self, token: str) -> tuple[str, str | None] | None:
        match = LITERAL_RE.match(token)
        if not match:
            return None
        lexical = match.group(1)
        datatype_token = match.group(3)
        datatype = (
            self.expand(datatype_token) if datatype_token is not None else None
        )
        return lexical, datatype

    def classify(self, subject: str) -> tuple[str, int | None]:
        for kind, pattern in (
            ("process", PROCESS_RE),
            ("dataset", DATASET_RE),
            ("quality", QUALITY_RE),
            ("value", VALUE_RE),
            ("fastq", FASTQ_RE),
        ):
            match = pattern.match(subject)
            if match:
                return kind, int(match.group(1))
        if subject == PROTOCOL_IRI:
            return "protocol", None
        return "other", None

    def start_subject(self, subject: str) -> None:
        if self.current is not None and self.current.subject == subject:
            return
        if self.current is not None:
            self.finalize_subject()
        kind, number = self.classify(subject)
        self.current = SubjectBlock(subject=subject, kind=kind, number=number)
        self.current_predicate = None
        self.subject_blocks += 1

    def add_triple(self, predicate: str, object_token: str) -> None:
        block = self.current
        if block is None:
            self.violation(
                "scanner_object_without_subject",
                "encountered an object without a current subject",
            )
            return
        literal = (
            self.parse_literal(object_token)
            if predicate in LITERAL_PREDICATES
            else None
        )
        obj = (
            object_token
            if predicate in LITERAL_PREDICATES
            else self.expand(object_token)
        )
        block.predicates[predicate] += 1
        self.selected_predicate_counts[predicate] += 1
        self.triples_scanned += 1

        if predicate == RDF_TYPE:
            block.types.add(obj)
        elif predicate == RDFS_LABEL:
            if literal is None:
                self.violation(
                    "label_not_literal",
                    "rdfs:label object is not a literal",
                    block.subject,
                )
            else:
                block.labels.append(literal[0])
        elif predicate == SIO_HAS_ATTRIBUTE:
            block.has_attribute_count += 1
            quality_match = QUALITY_RE.match(obj)
            if not quality_match:
                self.violation(
                    "has_attribute_target_not_quality",
                    f"SIO_000008 target is not a taxonomy quality: {obj}",
                    block.subject,
                )
            self.attribute_inverse.add(block.subject + "\0" + obj)
        elif predicate == SIO_IS_ATTRIBUTE_OF:
            block.bearer_objects.append(obj)
            self.attribute_forward.add(obj + "\0" + block.subject)
        elif predicate == SIO_HAS_MEASUREMENT_VALUE:
            block.measurement_objects.append(obj)
            self.value_forward.add(block.subject + "\0" + obj)
        elif predicate == SIO_IS_MEASUREMENT_VALUE_OF:
            block.inverse_measurement_objects.append(obj)
            self.value_inverse.add(obj + "\0" + block.subject)
        elif predicate == SIO_HAS_OUTPUT:
            block.output_objects.append(obj)
            self.process_outputs.add(obj)
        elif predicate == SIO_HAS_INPUT:
            block.input_objects.append(obj)
            self.process_inputs.add(obj)
        elif predicate == SIO_IS_SPECIFIED_BY:
            block.protocol_objects.append(obj)
        elif predicate == SIO_HAS_MEMBER:
            block.member_count += 1
            value_match = VALUE_RE.match(obj)
            if not value_match:
                self.violation(
                    "dataset_member_not_value",
                    f"SIO_000059 target is not a taxonomy value: {obj}",
                    block.subject,
                )
            else:
                self.dataset_members.add(obj)
                if block.kind == "dataset" and block.number is not None:
                    offset = block.number - DATASET_START
                    if offset < 0:
                        self.violation(
                            "dataset_id_before_reserved_range",
                            f"dataset ID {block.number} is below {DATASET_START}",
                            block.subject,
                        )
                    else:
                        expected_kind = (
                            "Absolute" if offset % 2 == 0 else "Relative"
                        )
                        expected_rank = RANKS[(offset % 14) // 2]
                        value_number = int(value_match.group(1))
                        expected_parity = 1 if expected_kind == "Absolute" else 0
                        if value_number % 2 != expected_parity:
                            self.violation(
                                "dataset_value_parity_mismatch",
                                f"{expected_kind} dataset contains {obj}",
                                block.subject,
                            )
                        self.members_by_kind_rank[
                            (expected_kind, expected_rank)
                        ].add(obj)
        elif predicate == LINEAGE_PROPERTY:
            if literal is None:
                self.violation(
                    "lineage_not_literal",
                    "lineage object is not a literal",
                    block.subject,
                )
            else:
                block.lineages.append(literal[0])
        elif predicate == ABSOLUTE_VALUE_PROPERTY:
            if literal is None:
                self.violation(
                    "absolute_value_not_literal",
                    "absolute abundance is not a literal",
                    block.subject,
                )
            else:
                block.absolute_values.append(literal)
        elif predicate == RELATIVE_VALUE_PROPERTY:
            if literal is None:
                self.violation(
                    "relative_value_not_literal",
                    "relative abundance is not a literal",
                    block.subject,
                )
            else:
                block.relative_values.append(literal)

    def sequence_check(self, kind: str, number: int, subject: str) -> None:
        expected = self.next_numbers[kind]
        if number != expected:
            self.violation(
                f"{kind}_id_not_contiguous",
                f"expected {expected}, encountered {number}",
                subject,
            )
            self.next_numbers[kind] = number + 1
        else:
            self.next_numbers[kind] += 1

    def exact_predicates(
        self,
        block: SubjectBlock,
        expected: dict[str, int | tuple[int, int | None]],
    ) -> None:
        for predicate, count_rule in expected.items():
            count = block.predicates[predicate]
            if isinstance(count_rule, int):
                valid = count == count_rule
                description = str(count_rule)
            else:
                minimum, maximum = count_rule
                valid = count >= minimum and (
                    maximum is None or count <= maximum
                )
                description = (
                    f"{minimum}..*" if maximum is None
                    else f"{minimum}..{maximum}"
                )
            if not valid:
                self.violation(
                    "predicate_cardinality",
                    f"{predicate} count {count}; expected {description}",
                    block.subject,
                )
        unexpected = sorted(set(block.predicates) - set(expected))
        if unexpected:
            self.violation(
                "unexpected_predicate",
                "unexpected predicates: " + ", ".join(unexpected),
                block.subject,
            )

    def finalize_process(self, block: SubjectBlock) -> None:
        assert block.number is not None
        self.sequence_check("process", block.number, block.subject)
        self.category_counts["processes"] += 1
        self.exact_predicates(
            block,
            {
                RDF_TYPE: 2,
                SIO_HAS_OUTPUT: 14,
                SIO_HAS_INPUT: 1,
                SIO_IS_SPECIFIED_BY: 1,
                RDFS_LABEL: 1,
            },
        )
        expected_types = {OWL_NAMED_INDIVIDUAL, WORKFLOW_CLASS}
        if block.types != expected_types:
            self.violation(
                "process_types",
                f"types {sorted(block.types)}; expected {sorted(expected_types)}",
                block.subject,
            )
        output_numbers = []
        for obj in block.output_objects:
            match = DATASET_RE.match(obj)
            if not match:
                self.violation(
                    "process_output_not_dataset",
                    f"process output is not a taxonomy dataset: {obj}",
                    block.subject,
                )
            else:
                output_numbers.append(int(match.group(1)))
        start = DATASET_START + (block.number - PROCESS_START) * 14
        if output_numbers != list(range(start, start + 14)):
            self.violation(
                "process_dataset_range",
                f"outputs {output_numbers}; expected {start}..{start + 13}",
                block.subject,
            )
        if len(block.input_objects) == 1 and not FASTQ_RE.match(
            block.input_objects[0]
        ):
            self.violation(
                "process_input_not_fastq",
                f"input is not in the FASTQ IRI range: {block.input_objects[0]}",
                block.subject,
            )
        if block.protocol_objects != [PROTOCOL_IRI]:
            self.violation(
                "process_protocol",
                f"protocol links are {block.protocol_objects}",
                block.subject,
            )
        if len(block.labels) == 1 and not re.match(
            r"^16S amplicon processing of .+ \(ERR[0-9]+\)$",
            block.labels[0],
        ):
            self.violation(
                "process_label_pattern",
                f"unexpected label: {block.labels[0]}",
                block.subject,
            )

    def finalize_dataset(self, block: SubjectBlock) -> None:
        assert block.number is not None
        self.sequence_check("dataset", block.number, block.subject)
        self.category_counts["datasets"] += 1
        self.dataset_subjects.add(block.subject)
        self.exact_predicates(
            block,
            {RDF_TYPE: 2, SIO_HAS_MEMBER: (1, None), RDFS_LABEL: 1},
        )
        offset = block.number - DATASET_START
        expected_kind = "Absolute" if offset % 2 == 0 else "Relative"
        expected_rank = RANKS[(offset % 14) // 2]
        expected_class = (
            ABSOLUTE_DATASET_CLASS
            if expected_kind == "Absolute"
            else RELATIVE_DATASET_CLASS
        )
        expected_types = {OWL_NAMED_INDIVIDUAL, expected_class}
        if block.types != expected_types:
            self.violation(
                "dataset_types",
                f"types {sorted(block.types)}; expected {sorted(expected_types)}",
                block.subject,
            )
        if len(block.labels) == 1:
            expected_prefix = (
                f"Taxon {expected_kind.lower()} abundance dataset for "
            )
            expected_suffix = f" ({expected_rank})"
            if not (
                block.labels[0].startswith(expected_prefix)
                and block.labels[0].endswith(expected_suffix)
            ):
                self.violation(
                    "dataset_label_pattern",
                    (
                        f"unexpected {expected_kind}/{expected_rank} label: "
                        f"{block.labels[0]}"
                    ),
                    block.subject,
                )

    def finalize_quality(self, block: SubjectBlock) -> None:
        assert block.number is not None
        self.sequence_check("quality", block.number, block.subject)
        self.category_counts["qualities"] += 1
        self.exact_predicates(
            block,
            {
                RDF_TYPE: 3,
                SIO_IS_ATTRIBUTE_OF: 2,
                SIO_HAS_MEASUREMENT_VALUE: 1,
            },
        )
        absolute = block.number % 2 == 1
        expected_types = {
            OWL_NAMED_INDIVIDUAL,
            AMOUNT_QUALITY_CLASS if absolute else CONCENTRATION_QUALITY_CLASS,
            ABSOLUTE_QUALITY_CLASS if absolute else RELATIVE_QUALITY_CLASS,
        }
        if block.types != expected_types:
            self.violation(
                "quality_types",
                f"types {sorted(block.types)}; expected {sorted(expected_types)}",
                block.subject,
            )
        expected_value = BASE + f"RAK_V{block.number:08d}"
        if block.measurement_objects != [expected_value]:
            self.violation(
                "quality_value_link",
                (
                    f"measurement links {block.measurement_objects}; "
                    f"expected [{expected_value}]"
                ),
                block.subject,
            )
        fastq_count = sum(bool(FASTQ_RE.match(obj)) for obj in block.bearer_objects)
        if fastq_count != 1 or len(set(block.bearer_objects)) != 2:
            self.violation(
                "quality_bearers",
                (
                    "expected two distinct bearers including one FASTQ; "
                    f"found {block.bearer_objects}"
                ),
                block.subject,
            )

    def update_numeric(
        self, kind: str, lexical: str, datatype: str | None, subject: str
    ) -> None:
        if datatype != XSD_DOUBLE:
            self.violation(
                "abundance_datatype",
                f"{kind} abundance datatype is {datatype}, expected {XSD_DOUBLE}",
                subject,
            )
        try:
            value = float(lexical)
        except ValueError:
            self.violation(
                "abundance_not_numeric",
                f"cannot parse {kind} abundance {lexical!r}",
                subject,
            )
            return
        if not math.isfinite(value) or value <= 0:
            self.violation(
                "abundance_out_of_bounds",
                f"{kind} abundance must be finite and >0; found {value}",
                subject,
            )
        if kind == "absolute" and not value.is_integer():
            self.violation(
                "absolute_abundance_not_integral",
                f"absolute abundance is not integral: {value}",
                subject,
            )
        if kind == "relative" and value > 1.0:
            self.violation(
                "relative_abundance_above_one",
                f"relative abundance exceeds 1: {value}",
                subject,
            )
        stats = self.numeric[kind]
        stats["count"] += 1
        stats["sum"] += value
        stats["minimum"] = (
            value if stats["minimum"] is None else min(stats["minimum"], value)
        )
        stats["maximum"] = (
            value if stats["maximum"] is None else max(stats["maximum"], value)
        )

    def finalize_value(self, block: SubjectBlock) -> None:
        assert block.number is not None
        self.sequence_check("value", block.number, block.subject)
        self.category_counts["values"] += 1
        self.value_subjects.add(block.subject)
        absolute = block.number % 2 == 1
        numeric_predicate = (
            ABSOLUTE_VALUE_PROPERTY if absolute else RELATIVE_VALUE_PROPERTY
        )
        self.exact_predicates(
            block,
            {
                RDF_TYPE: 2,
                SIO_IS_MEASUREMENT_VALUE_OF: 1,
                LINEAGE_PROPERTY: 1,
                numeric_predicate: 1,
                RDFS_LABEL: 1,
            },
        )
        expected_types = {
            OWL_NAMED_INDIVIDUAL,
            ABSOLUTE_VALUE_CLASS if absolute else RELATIVE_VALUE_CLASS,
        }
        if block.types != expected_types:
            self.violation(
                "value_types",
                f"types {sorted(block.types)}; expected {sorted(expected_types)}",
                block.subject,
            )
        expected_quality = BASE + f"RAK_Q{block.number:08d}"
        if block.inverse_measurement_objects != [expected_quality]:
            self.violation(
                "value_quality_link",
                (
                    f"measurement links {block.inverse_measurement_objects}; "
                    f"expected [{expected_quality}]"
                ),
                block.subject,
            )
        numeric_values = (
            block.absolute_values if absolute else block.relative_values
        )
        if len(numeric_values) == 1:
            self.update_numeric(
                "absolute" if absolute else "relative",
                numeric_values[0][0],
                numeric_values[0][1],
                block.subject,
            )

        expected_kind = "Absolute" if absolute else "Relative"
        label_rank = None
        if len(block.labels) == 1:
            match = re.match(
                rf"^{expected_kind} abundance of .+ in .+ "
                rf"\(({'|'.join(RANKS)})\)$",
                block.labels[0],
            )
            if match:
                label_rank = match.group(1)
                self.values_by_kind_rank[(expected_kind, label_rank)].add(
                    block.subject
                )
            else:
                self.violation(
                    "value_label_pattern",
                    f"unexpected label: {block.labels[0]}",
                    block.subject,
                )
        if len(block.lineages) == 1:
            segments = block.lineages[0].split("; ")
            prefixes = [segment.split(": ", 1)[0] for segment in segments]
            if prefixes != list(RANKS[: len(prefixes)]):
                self.violation(
                    "lineage_rank_order",
                    f"lineage rank prefixes are {prefixes}",
                    block.subject,
                )
            if label_rank is not None:
                expected_length = RANKS.index(label_rank) + 1
                if (
                    len(segments) != expected_length
                    or prefixes[-1:] != [label_rank]
                ):
                    self.violation(
                        "lineage_label_rank_mismatch",
                        (
                            f"label rank {label_rank}, lineage has "
                            f"{len(segments)} segments ending in "
                            f"{prefixes[-1:]}"
                        ),
                        block.subject,
                    )

    def finalize_fastq(self, block: SubjectBlock) -> None:
        self.category_counts["fastq_bearer_subjects"] += 1
        self.fastq_subjects.add(block.subject)
        if OWL_NAMED_INDIVIDUAL not in block.types:
            self.violation(
                "fastq_not_named_individual",
                "FASTQ bearer lacks owl:NamedIndividual",
                block.subject,
            )
        if block.has_attribute_count < 1:
            self.violation(
                "fastq_without_taxonomy_quality",
                "FASTQ bearer has no taxonomy quality",
                block.subject,
            )

    def finalize_protocol(self, block: SubjectBlock) -> None:
        self.category_counts["protocol_subjects"] += 1
        self.protocol_subject_seen = True
        self.exact_predicates(block, {RDF_TYPE: 1, RDFS_LABEL: 1})
        if block.types != {OWL_NAMED_INDIVIDUAL}:
            self.violation(
                "protocol_types",
                f"unexpected protocol types: {sorted(block.types)}",
                block.subject,
            )
        if block.labels != ["16S amplicon processing protocol"]:
            self.violation(
                "protocol_label",
                f"unexpected protocol label: {block.labels}",
                block.subject,
            )

    def finalize_other(self, block: SubjectBlock) -> None:
        if block.has_attribute_count:
            self.category_counts["other_bearer_subjects"] += 1
            if OWL_NAMED_INDIVIDUAL not in block.types:
                self.violation(
                    "bearer_not_named_individual",
                    "quality bearer lacks owl:NamedIndividual",
                    block.subject,
                )

    def finalize_subject(self) -> None:
        block = self.current
        if block is None:
            return
        {
            "process": self.finalize_process,
            "dataset": self.finalize_dataset,
            "quality": self.finalize_quality,
            "value": self.finalize_value,
            "fastq": self.finalize_fastq,
            "protocol": self.finalize_protocol,
            "other": self.finalize_other,
        }[block.kind](block)
        self.current = None
        self.current_predicate = None

    def scan_line(self, raw: bytes) -> None:
        self.line_number += 1
        self.lines_read += 1
        self.bytes_read += len(raw)
        self.sha256.update(raw)
        try:
            line = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            self.violation(
                "invalid_utf8",
                f"UTF-8 decode failure: {exc}",
                self.current.subject if self.current else None,
            )
            return
        stripped = line.strip()
        if (
            not stripped
            or stripped.startswith("#")
            or stripped.startswith("@prefix ")
            or stripped.startswith("@base ")
        ):
            return

        leading_space = bool(line[:1].isspace())
        try:
            if not leading_space:
                subject_token, rest = self.first_token(stripped)
                subject = self.expand(subject_token)
                self.start_subject(subject)
                predicate_token, object_and_terminal = self.first_token(rest)
                self.current_predicate = self.expand(predicate_token)
            else:
                first, rest = self.first_token(stripped)
                if first in PREDICATE_QNAMES:
                    self.current_predicate = self.expand(first)
                    object_and_terminal = rest
                elif first.startswith("<") and rest not in {",", ";", "."}:
                    self.current_predicate = self.expand(first)
                    object_and_terminal = rest
                else:
                    object_and_terminal = stripped
            if self.current_predicate is None:
                raise ValueError("object continuation has no predicate")
            terminal = object_and_terminal[-1:]
            if terminal not in {",", ";", "."}:
                raise ValueError("triple line has no Turtle terminator")
            object_token = object_and_terminal[:-1].rstrip()
            if not object_token:
                raise ValueError("triple line has no object")
            self.add_triple(self.current_predicate, object_token)
            if terminal in {";", "."}:
                self.current_predicate = None
        except (ValueError, IndexError) as exc:
            self.violation(
                "scanner_unrecognized_line",
                f"{exc}: {stripped[:300]}",
                self.current.subject if self.current else None,
            )

    def scan(self, path: Path) -> dict[str, Any]:
        started = time.monotonic()
        with path.open("rb", buffering=8 * 1024 * 1024) as handle:
            for raw in handle:
                self.scan_line(raw)
        self.finalize_subject()
        elapsed = time.monotonic() - started
        self.finalize_global_checks()
        return {
            "duration_seconds": round(elapsed, 3),
            "validator_peak_rss_kib": resource.getrusage(
                resource.RUSAGE_SELF
            ).ru_maxrss,
            "bytes_read": self.bytes_read,
            "lines_read": self.lines_read,
            "triples_scanned": self.triples_scanned,
            "subject_blocks": self.subject_blocks,
            "sha256": self.sha256.hexdigest(),
        }

    def compare_fingerprint(
        self,
        code: str,
        description: str,
        left: MultisetFingerprint,
        right: MultisetFingerprint,
    ) -> None:
        if not left.equals(right):
            self.violation(
                code,
                (
                    f"{description} fingerprints differ: "
                    f"{left.as_dict()} versus {right.as_dict()}"
                ),
            )

    def finalize_global_checks(self) -> None:
        processes = self.category_counts["processes"]
        datasets = self.category_counts["datasets"]
        qualities = self.category_counts["qualities"]
        values = self.category_counts["values"]
        if min(processes, datasets, qualities, values) == 0:
            self.violation(
                "required_category_empty",
                (
                    "one or more generated categories are empty: "
                    f"P={processes}, datasets={datasets}, Q={qualities}, V={values}"
                ),
            )
        if datasets != processes * 14:
            self.violation(
                "process_dataset_count",
                f"{processes} processes imply {processes * 14} datasets; found {datasets}",
            )
        if qualities != values:
            self.violation(
                "quality_value_count",
                f"found {qualities} qualities and {values} values",
            )
        if qualities % 2:
            self.violation(
                "quality_count_not_even",
                f"quality count is odd: {qualities}",
            )
        if not self.protocol_subject_seen:
            self.violation(
                "protocol_subject_missing",
                f"missing protocol subject {PROTOCOL_IRI}",
            )
        self.compare_fingerprint(
            "attribute_inverse_mismatch",
            "quality→bearer and bearer→quality",
            self.attribute_forward,
            self.attribute_inverse,
        )
        self.compare_fingerprint(
            "measurement_inverse_mismatch",
            "quality→value and value→quality",
            self.value_forward,
            self.value_inverse,
        )
        self.compare_fingerprint(
            "dataset_membership_mismatch",
            "dataset members and value subjects",
            self.dataset_members,
            self.value_subjects,
        )
        self.compare_fingerprint(
            "process_output_mismatch",
            "process outputs and dataset subjects",
            self.process_outputs,
            self.dataset_subjects,
        )
        self.compare_fingerprint(
            "process_input_mismatch",
            "process inputs and FASTQ bearer subjects",
            self.process_inputs,
            self.fastq_subjects,
        )
        for key in self.members_by_kind_rank:
            self.compare_fingerprint(
                "dataset_value_rank_mismatch",
                f"dataset membership and value labels for {key[0]} {key[1]}",
                self.members_by_kind_rank[key],
                self.values_by_kind_rank[key],
            )

    def report(self) -> dict[str, Any]:
        fingerprints = {
            "quality_to_bearer": self.attribute_forward.as_dict(),
            "bearer_to_quality": self.attribute_inverse.as_dict(),
            "quality_to_value": self.value_forward.as_dict(),
            "value_to_quality": self.value_inverse.as_dict(),
            "dataset_members": self.dataset_members.as_dict(),
            "value_subjects": self.value_subjects.as_dict(),
            "process_outputs": self.process_outputs.as_dict(),
            "dataset_subjects": self.dataset_subjects.as_dict(),
            "process_inputs": self.process_inputs.as_dict(),
            "fastq_subjects": self.fastq_subjects.as_dict(),
        }
        return {
            "category_counts": dict(sorted(self.category_counts.items())),
            "selected_predicate_counts": {
                key: self.selected_predicate_counts[key]
                for key in (
                    RDF_TYPE,
                    RDFS_LABEL,
                    SIO_HAS_ATTRIBUTE,
                    SIO_IS_ATTRIBUTE_OF,
                    SIO_HAS_MEMBER,
                    SIO_IS_MEASUREMENT_VALUE_OF,
                    SIO_HAS_MEASUREMENT_VALUE,
                    SIO_HAS_OUTPUT,
                    SIO_HAS_INPUT,
                    SIO_IS_SPECIFIED_BY,
                    RELATIVE_VALUE_PROPERTY,
                    LINEAGE_PROPERTY,
                    ABSOLUTE_VALUE_PROPERTY,
                )
            },
            "numeric_summaries": self.numeric,
            "relationship_fingerprints": fingerprints,
            "rank_fingerprints_match": {
                f"{kind.lower()}_{rank.lower()}": (
                    self.members_by_kind_rank[(kind, rank)].equals(
                        self.values_by_kind_rank[(kind, rank)]
                    )
                )
                for kind in ("Absolute", "Relative")
                for rank in RANKS
            },
            "violations": {
                "total": sum(self.violation_counts.values()),
                "by_code": dict(sorted(self.violation_counts.items())),
                "examples": self.violation_examples,
                "examples_truncated": (
                    sum(self.violation_counts.values())
                    > len(self.violation_examples)
                ),
            },
            "warnings": {
                "total": sum(self.warning_counts.values()),
                "by_code": dict(sorted(self.warning_counts.items())),
                "examples": self.warning_examples,
                "examples_truncated": (
                    sum(self.warning_counts.values())
                    > len(self.warning_examples)
                ),
            },
        }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def process_rss_kib(pid: int) -> int | None:
    status = Path(f"/proc/{pid}/status")
    try:
        for line in status.read_text(encoding="utf-8").splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1])
    except (FileNotFoundError, ProcessLookupError, PermissionError, ValueError):
        return None
    return None


def run_raptor(path: Path, executable: str) -> dict[str, Any]:
    version_result = subprocess.run(
        [executable, "--version"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    version = version_result.stdout.strip().splitlines()[0]
    started = time.monotonic()
    peak_rss_kib = 0
    with tempfile.TemporaryFile(mode="w+b") as stderr_handle:
        process = subprocess.Popen(
            [executable, "-i", "turtle", "-c", str(path)],
            stdout=subprocess.DEVNULL,
            stderr=stderr_handle,
        )
        while process.poll() is None:
            rss = process_rss_kib(process.pid)
            if rss is not None:
                peak_rss_kib = max(peak_rss_kib, rss)
            time.sleep(0.2)
        exit_code = process.wait()
        stderr_handle.seek(0)
        stderr = stderr_handle.read().decode("utf-8", errors="replace")
    elapsed = time.monotonic() - started
    match = RAPPER_COUNT_RE.search(stderr)
    triple_count = int(match.group(1)) if match else None
    error_lines = [
        line
        for line in stderr.splitlines()
        if re.search(r"\b(?:error|warning|failed)\b", line, flags=re.I)
    ]
    return {
        "tool": "Raptor rapper",
        "version": version,
        "command": [executable, "-i", "turtle", "-c", str(path)],
        "duration_seconds": round(elapsed, 3),
        "peak_rss_kib": peak_rss_kib or None,
        "exit_code": exit_code,
        "triple_count": triple_count,
        "diagnostic_lines": error_lines[:25],
        "diagnostic_lines_truncated": len(error_lines) > 25,
        "passed": exit_code == 0 and triple_count is not None and not error_lines,
    }


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=Path(
            "data/processed/ontology/rubalkhali_taxonomy_abox.ttl"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "data/release/taxonomy_abox_streaming_validation.json"
        ),
    )
    parser.add_argument(
        "--rapper",
        default=None,
        help="Path to Raptor rapper (default: resolve from PATH)",
    )
    parser.add_argument("--max-examples", type=int, default=25)
    args = parser.parse_args()

    input_path = args.input.resolve()
    output_path = args.output.resolve()
    script_path = Path(__file__).resolve()
    started = time.monotonic()
    report: dict[str, Any] = {
        "schema_version": "1.0",
        "validator": {
            "name": "taxonomy-abox-streaming-structural-validator",
            "script": str(script_path),
            "script_sha256": sha256_file(script_path),
            "memory_model": (
                "Constant-size per-subject counters and fixed-size multiset "
                "fingerprints; no RDF graph or unbounded identifier set is "
                "materialized."
            ),
        },
        "input": {"path": str(input_path)},
        "coverage": {
            "turtle_syntax": {
                "method": "Raptor streaming Turtle parser",
                "scope": "entire input file",
                "complete_when_status_passed": True,
            },
            "project_structural_invariants": {
                "method": (
                    "complete source-line scan plus exact per-record checks "
                    "and order-independent relationship fingerprints"
                ),
                "scope": (
                    "every process, taxonomy dataset, abundance quality, "
                    "abundance value, membership and reciprocal attribute/"
                    "measurement link emitted by the current generator"
                ),
                "complete_when_status_passed": True,
            },
            "shex": {
                "status": "not_run",
                "coverage_fraction": 0.0,
                "reason": (
                    "This gate does not load the multi-gigabyte graph and "
                    "does not claim full ShEx validation."
                ),
            },
        },
    }
    execution_errors: list[str] = []

    if not input_path.is_file():
        execution_errors.append(f"input file does not exist: {input_path}")
    if args.rapper:
        rapper = shutil.which(args.rapper)
        if rapper is None:
            candidate = Path(args.rapper)
            if candidate.is_file() and os.access(candidate, os.X_OK):
                rapper = str(candidate.resolve())
    else:
        rapper = shutil.which("rapper")
    if not rapper:
        execution_errors.append(
            "Raptor rapper is required for full Turtle syntax validation"
        )

    scanner: TaxonomyABoxScanner | None = None
    if not execution_errors:
        stat = input_path.stat()
        report["input"].update(
            {
                "bytes": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
            }
        )
        scanner = TaxonomyABoxScanner(max_examples=args.max_examples)
        scan_result: dict[str, Any] | None = None
        try:
            scan_result = scanner.scan(input_path)
            report["input"]["sha256"] = scan_result["sha256"]
            report["structural_scan"] = scan_result
            report["structural_results"] = scanner.report()
        except Exception as exc:  # fail closed and preserve a partial report
            execution_errors.append(
                f"structural scanner raised {type(exc).__name__}: {exc}"
            )
            report["structural_scan"] = {
                "status": "execution_error",
                "bytes_read": scanner.bytes_read,
                "lines_read": scanner.lines_read,
                "triples_scanned": scanner.triples_scanned,
                "validator_peak_rss_kib": resource.getrusage(
                    resource.RUSAGE_SELF
                ).ru_maxrss,
            }
            report["structural_results"] = scanner.report()

        raptor_result: dict[str, Any] | None = None
        try:
            raptor_result = run_raptor(input_path, str(rapper))
            report["turtle_parser"] = raptor_result
        except Exception as exc:  # fail closed and preserve scanner evidence
            execution_errors.append(
                f"Raptor execution raised {type(exc).__name__}: {exc}"
            )
            report["turtle_parser"] = {
                "passed": False,
                "status": "execution_error",
            }

        if scan_result is not None and scan_result["bytes_read"] != stat.st_size:
            execution_errors.append(
                f"scanner read {scan_result['bytes_read']} of {stat.st_size} bytes"
            )
        if raptor_result is None or not raptor_result["passed"]:
            execution_errors.append("Raptor did not complete a clean Turtle parse")
        if scan_result is not None and (
            raptor_result is None
            or raptor_result["triple_count"] is None
            or scan_result["triples_scanned"] != raptor_result["triple_count"]
        ):
            execution_errors.append(
                "source scanner and Raptor triple counts differ: "
                f"{scan_result['triples_scanned']} versus "
                f"{None if raptor_result is None else raptor_result.get('triple_count')}"
            )

    violation_total = (
        sum(scanner.violation_counts.values()) if scanner is not None else 0
    )
    passed = not execution_errors and violation_total == 0
    report["execution_errors"] = execution_errors
    report["status"] = "passed" if passed else "failed"
    report["total_duration_seconds"] = round(
        time.monotonic() - started, 3
    )
    report["deterministic_result_fields"] = [
        "input.bytes",
        "input.sha256",
        "structural_scan.bytes_read",
        "structural_scan.lines_read",
        "structural_scan.triples_scanned",
        "structural_results.category_counts",
        "structural_results.selected_predicate_counts",
        "structural_results.relationship_fingerprints",
        "structural_results.violations",
        "turtle_parser.triple_count",
        "status",
    ]
    atomic_write_json(output_path, report)
    print(
        json.dumps(
            {
                "status": report["status"],
                "input_bytes": report.get("input", {}).get("bytes"),
                "input_sha256": report.get("input", {}).get("sha256"),
                "triples": report.get("structural_scan", {}).get(
                    "triples_scanned"
                ),
                "violations": violation_total,
                "execution_errors": execution_errors,
                "report": str(output_path),
                "duration_seconds": report["total_duration_seconds"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
