#!/usr/bin/env python3
"""Fail-closed validation for normalized controls, control analysis, and ABox."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from rdflib import DCTERMS, OWL, RDF, Graph, Literal, Namespace, URIRef

BASE = Namespace("https://rubalkhali.science/kb/")
SIO = Namespace("http://semanticscience.org/resource/")
CONTROL_IRI = re.compile(r"^https://rubalkhali\.science/kb/RAK_CTL_[0-9a-f]{64}$")


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def fail(message: str, failures: list[str]) -> None:
    failures.append(message)


def control_graph_invariant_failures(
    graph: Graph,
    assertions: list[dict[str, str]],
    occurrences: list[dict[str, str]],
) -> list[str]:
    """Return failures for high-risk control-model regression fixtures."""
    failures: list[str] = []
    for subject, obj in graph.subject_objects(OWL.sameAs):
        if str(subject).startswith(str(BASE) + "RAK_CTL_") or str(obj).startswith(
            str(BASE) + "RAK_CTL_"
        ):
            failures.append(
                f"control identity asserted with owl:sameAs: {subject} -> {obj}"
            )

    forbidden_subjects = set(graph.subjects(RDF.type, BASE.RAK_0000300)) | set(
        graph.subjects(RDF.type, BASE.RAK_0000308)
    )
    for subject in forbidden_subjects:
        for parent in graph.objects(subject, SIO.SIO_000068):
            if (parent, RDF.type, BASE.RAK_0000018) in graph:
                failures.append(
                    f"control material/batch directly assigned to expedition: {subject}"
                )

    role_classes = {
        BASE.RAK_0000304,
        BASE.RAK_0000305,
        BASE.RAK_0000306,
        BASE.RAK_0000307,
    }
    role_nodes = {
        role
        for role_class in role_classes
        for role in graph.subjects(RDF.type, role_class)
    }
    for role in role_nodes:
        bearers = set(graph.objects(role, SIO.SIO_000227)) | set(
            graph.subjects(SIO.SIO_000228, role)
        )
        if len(bearers) != 1:
            failures.append(
                f"control role has {len(bearers)} graph bearers: {role}"
            )

    for row in assertions:
        if row.get("status") == "confirmed" or not row.get("object_iri"):
            continue
        triple = (
            URIRef(row["subject_iri"]),
            URIRef(row["predicate_iri"]),
            URIRef(row["object_iri"]),
        )
        if triple in graph:
            failures.append(
                f"non-confirmed assertion was promoted: {row.get('assertion_id', '')}"
            )

    for row in occurrences:
        index = row.get("index_code", "")
        if not index:
            continue
        for subject in graph.subjects(DCTERMS.identifier, Literal(index)):
            failures.append(
                f"index code was promoted to a graph entity: {index} ({subject})"
            )
    return failures


def string_sentinel_failures(
    tables: dict[str, list[dict[str, str]]],
) -> list[str]:
    sentinels = {"unknown", "na", "n/a", "?"}
    failures: list[str] = []
    for name, rows in tables.items():
        for row_no, row in enumerate(rows, start=2):
            for field, value in row.items():
                if value.strip().lower() in sentinels:
                    failures.append(
                        f"string sentinel {value!r} in {name}:{row_no}:{field}"
                    )
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="Project tree containing the generated graph and audit evidence.",
    )
    args = parser.parse_args()
    root = args.project_root.resolve()
    repository_layout = (root / "data/processed/metadata/controls").is_dir()
    if repository_layout:
        normalized = root / "data/processed/metadata/controls"
        graph_path = (
            root / "data/processed/semantics/ontology/rubalkhali_controls.ttl"
        )
        analysis = root / "analysis/v3/control_audit"
        ground_truth = (
            root / "data/metadata/samples/controls/control_ground_truth.tsv"
        )
    else:
        normalized = root / "metadata/controls"
        graph_path = root / "ontology/rubalkhali_controls.ttl"
        analysis = root / "evidence/control-audit"
        ground_truth = root / "evidence/controls/control_ground_truth.tsv"
    sensitivity_inputs = analysis / "sensitivity_inputs"
    required = [
        ground_truth,
        normalized / "control_entity_registry.tsv",
        normalized / "control_roles.tsv",
        normalized / "laboratory_processes.tsv",
        normalized / "control_sequence_occurrences.tsv",
        normalized / "control_composition.tsv",
        normalized / "control_assertions.tsv",
        normalized / "control_metadata_dispositions.tsv",
        graph_path,
        analysis / "summary.json",
        analysis / "control_analysis_roles.tsv",
        analysis / "positive_control_profiles.tsv",
        analysis / "trip5_primary_contaminant_calls.tsv",
        analysis / "trip5_removal_fraction_by_profile.tsv",
        analysis / "trip5_mapped_feature_table_control_filtered.tsv.gz",
        analysis / "positive_control_expected_taxon_recovery.tsv",
        analysis / "positive_control_expected_asv_occurrences.tsv",
        analysis / "positive_control_spillover_summary.tsv",
        analysis / "positive_control_spillover_summary.json",
        sensitivity_inputs / "alpha.tsv",
        sensitivity_inputs / "genus_counts.tsv.gz",
        sensitivity_inputs / "asv_filt_counts.tsv.gz",
        sensitivity_inputs / "summary.json",
    ]
    failures: list[str] = []
    for path in required:
        if not path.is_file():
            fail(f"missing required control artifact: {path.relative_to(root)}", failures)
    if failures:
        print("\n".join("FAIL: " + item for item in failures), file=sys.stderr)
        return 1

    registry = read_tsv(normalized / "control_entity_registry.tsv")
    aliases = read_tsv(normalized / "control_aliases.tsv")
    roles = read_tsv(normalized / "control_roles.tsv")
    processes = read_tsv(normalized / "laboratory_processes.tsv")
    occurrences = read_tsv(normalized / "control_sequence_occurrences.tsv")
    composition = read_tsv(normalized / "control_composition.tsv")
    assertions = read_tsv(normalized / "control_assertions.tsv")
    dispositions = read_tsv(normalized / "control_metadata_dispositions.tsv")
    ground_truth_rows = read_tsv(ground_truth)
    g = Graph().parse(graph_path)

    if {row["record_id"] for row in ground_truth_rows} != {
        f"CGT-{number:03d}" for number in range(1, 12)
    }:
        fail("control ground-truth ledger is incomplete or has duplicate IDs", failures)
    allowed_ground_truth_status = {
        "CONFIRMED_AUTHOR",
        "CONFIRMED_CLASS_AUTHOR",
        "UNRESOLVED_INVENTORY",
    }
    if any(
        row["status"] not in allowed_ground_truth_status
        for row in ground_truth_rows
    ):
        fail("control ground-truth ledger contains an unsupported status", failures)
    ground_truth_text = "\n".join(
        "\t".join(row.values()) for row in ground_truth_rows
    )
    for fragment in [
        "D6322",
        "D6300",
        "Trip 4 positive-control design\tno positive control",
        "EB1-EB17",
        "shotgun metagenomics",
        "Sterile bags carried in the field",
    ]:
        if fragment not in ground_truth_text:
            fail(f"ground-truth fact absent: {fragment}", failures)

    registered: set[str] = set()
    canonical_to_iri: dict[str, str] = {}
    for row in registry:
        iri = row["entity_id"]
        canonical = row["canonical_key"]
        expected_canonical = (
            f"{row['entity_kind']}|{row['stable_key_type']}|{row['stable_key']}"
        )
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        if canonical != expected_canonical:
            fail(f"canonical key mismatch for {iri}", failures)
        if row["iri_scheme_version"] != "control-key-v1":
            fail(f"unsupported control IRI scheme for {iri}", failures)
        if row["key_sha256"] != digest or iri != str(BASE) + "RAK_CTL_" + digest:
            fail(f"digest/IRI mismatch for {iri}", failures)
        if not CONTROL_IRI.fullmatch(iri):
            fail(f"invalid control IRI form: {iri}", failures)
        if iri in registered:
            fail(f"duplicate control IRI in registry: {iri}", failures)
        if canonical in canonical_to_iri and canonical_to_iri[canonical] != iri:
            fail(f"one canonical key maps to multiple IRIs: {canonical}", failures)
        registered.add(iri)
        canonical_to_iri[canonical] = iri
    graph_control_iris = {
        str(term)
        for triple in g
        for term in triple
        if isinstance(term, URIRef) and str(term).startswith(str(BASE) + "RAK_CTL_")
    }
    if graph_control_iris != registered:
        fail(
            "generated control IRIs and registry differ: "
            f"unregistered={sorted(graph_control_iris - registered)[:3]}, "
            f"unserialized={sorted(registered - graph_control_iris)[:3]}",
            failures,
        )
    eb1_entities = {row["entity_id"] for row in aliases if row["alias"] == "EB1"}
    if len(eb1_entities) < 2:
        fail("reused EB1 labels are not preserved as aliases of distinct entities", failures)
    e0323 = {
        row["entity_id"]
        for row in aliases
        if row["alias"] == "e0323_Ctrl_1_Trip1"
    }
    if len(e0323) != 1:
        fail("ambiguous e0323 control is not represented exactly once", failures)
    else:
        e0323_id = next(iter(e0323))
        e0323_roles = {
            row["role_type"]
            for row in roles
            if row["bearer_material_id"] == e0323_id
        }
        if "positive_microbiome_control" in e0323_roles:
            fail("ambiguous e0323 library was promoted to a positive control", failures)
        if any(
            row["subject_iri"] == e0323_id
            and row["predicate_iri"] == str(SIO.SIO_000244)
            and row["status"] == "confirmed"
            for row in assertions
        ):
            fail("ambiguous e0323 library was linked to a product", failures)

    normalized_tables = {
        path.name: read_tsv(path) for path in normalized.glob("*.tsv")
    }
    failures.extend(string_sentinel_failures(normalized_tables))
    failures.extend(
        control_graph_invariant_failures(g, assertions, occurrences)
    )

    bearer_count: Counter[str] = Counter()
    for row in roles:
        role = URIRef(row["role_id"])
        bearer = URIRef(row["bearer_material_id"])
        bearer_count[row["role_id"]] += 1
        if (bearer, SIO.SIO_000228, role) not in g or (role, SIO.SIO_000227, bearer) not in g:
            fail(f"missing reciprocal role/bearer edges for {role}", failures)
        process = row["realized_in_process_id"]
        if process:
            process_iri = URIRef(process)
            if (process_iri, SIO.SIO_000355, role) not in g or (
                role, SIO.SIO_000356, process_iri
            ) not in g:
                fail(f"missing reciprocal realizes edges for {role}", failures)
            if row["role_type"] == "extraction_blank" and (
                process_iri, RDF.type, BASE.RAK_0000309
            ) not in g:
                fail(f"extraction blank realized outside extraction: {role}", failures)
            if row["role_type"] == "pcr_blank" and (
                process_iri, RDF.type, BASE.RAK_0000311
            ) not in g:
                fail(f"PCR blank realized outside PCR: {role}", failures)
    for role, count in bearer_count.items():
        if count != 1:
            fail(f"role {role} has {count} normalized bearers", failures)

    # No control material or laboratory batch may be assigned to an expedition,
    # and batches must never have targets (which would trigger the RAK chain).
    forbidden_subjects = set(g.subjects(RDF.type, BASE.RAK_0000300)) | set(
        g.subjects(RDF.type, BASE.RAK_0000308)
    )
    for subject in forbidden_subjects:
        if any(g.objects(subject, SIO.SIO_000291)):
            fail(f"control material/batch has a target: {subject}", failures)
        for parent in g.objects(subject, SIO.SIO_000068):
            if (parent, RDF.type, BASE.RAK_0000018) in g:
                fail(f"control material/batch directly assigned to expedition: {subject}", failures)

    memberships: defaultdict[str, set[str]] = defaultdict(set)
    for row in processes:
        if row["batch_id"] and row["process_id"].startswith(str(BASE)):
            memberships[row["process_id"]].add(row["batch_id"])
    for process, batches in memberships.items():
        if len(batches) > 1:
            fail(f"process promoted into multiple laboratory batches: {process}", failures)

    # Provisional/unresolved/rejected assertions must not be promoted as direct
    # domain triples in the asserted control module.
    for row in assertions:
        if row["status"] != "confirmed" and row["object_iri"]:
            triple = (
                URIRef(row["subject_iri"]),
                URIRef(row["predicate_iri"]),
                URIRef(row["object_iri"]),
            )
            if triple in g:
                fail(f"non-confirmed assertion was promoted: {row['assertion_id']}", failures)
        assertion = URIRef(row["assertion_id"])
        evidence = URIRef(row["evidence_id"])
        if (
            assertion,
            SIO.SIO_000772,
            evidence,
        ) not in g or (evidence, SIO.SIO_000773, assertion) not in g:
            fail(
                f"missing reciprocal evidence edges for {row['assertion_id']}",
                failures,
            )

    # The seven July positive-labelled libraries are compatible with their
    # trip-level products, but no frozen source confirms each library/product
    # identity. Keep those links reified and provisional rather than promoting
    # them as domain triples.
    provisional_product_assertions = [
        row
        for row in assertions
        if row["predicate_iri"] == str(SIO.SIO_000244)
        and row["status"] == "provisional"
    ]
    if len(provisional_product_assertions) != 7:
        fail(
            "expected seven provisional July library/product assertions",
            failures,
        )
    provisional_product_subjects = {
        row["subject_iri"] for row in provisional_product_assertions
    }
    expected_positive_aliases = {
        "e0553_Ctrl_2",
        "e0554_Ctrl_3",
        "e0872_TMC1",
        "e0874_Positive",
        "e8294_FPosCtrl1",
        "e8661_FPosCtrl2",
        "e8665_FPosCtrl3",
    }
    alias_to_entity = {
        row["alias"]: row["entity_id"]
        for row in aliases
        if row["alias"] in expected_positive_aliases
    }
    if set(alias_to_entity) != expected_positive_aliases:
        fail("positive-labelled library aliases are incomplete", failures)
    elif set(alias_to_entity.values()) != provisional_product_subjects:
        fail(
            "provisional product assertions do not match the seven "
            "positive-labelled libraries",
            failures,
        )
    product_disposition_subjects = {
        row["about_entity_id"]
        for row in dispositions
        if row["metadata_field"] == "positive_control_product_identity"
        and row["disposition"] == "unresolved"
    }
    if product_disposition_subjects != provisional_product_subjects:
        fail(
            "positive-labelled library/product uncertainty is not fully "
            "represented by unresolved dispositions",
            failures,
        )

    for row in composition:
        if row["assertion_status"] != "confirmed":
            fail(f"non-confirmed row in frozen composition: {row['taxon_iri']}", failures)
        if row["expected_value"] and (
            not row["expected_unit_iri"] or not row["composition_basis"]
        ):
            fail(f"numeric composition lacks unit/basis: {row['taxon_iri']}", failures)
        triple = (
            URIRef(row["composition_specification_id"]),
            BASE.RAK_2000092,
            URIRef(row["taxon_iri"]),
        )
        if triple not in g:
            fail(f"confirmed expected taxon missing from graph: {row['taxon_iri']}", failures)
        expected_assertions = [
            assertion
            for assertion in assertions
            if assertion["assertion_id"] == row["assertion_id"]
            and assertion["subject_iri"] == row["composition_specification_id"]
            and assertion["predicate_iri"] == str(BASE.RAK_2000092)
            and assertion["object_iri"] == row["taxon_iri"]
            and assertion["status"] == "confirmed"
        ]
        if len(expected_assertions) != 1:
            fail(
                "expected-taxon triple does not have exactly one confirmed "
                f"reified assertion: {row['taxon_iri']}",
                failures,
            )
        elif (
            URIRef(expected_assertions[0]["assertion_id"]),
            RDF.type,
            BASE.RAK_0000317,
        ) not in g:
            fail(
                f"expected-taxon assertion lacks its specific class: {row['taxon_iri']}",
                failures,
            )
        product = URIRef(row["control_material_or_product_id"])
        specification = URIRef(row["composition_specification_id"])
        if (
            product,
            SIO.SIO_000339,
            specification,
        ) not in g or (specification, SIO.SIO_000338, product) not in g:
            fail(
                f"missing reciprocal product/specification edges for {row['product']}",
                failures,
            )
        if not list(g.objects(specification, DCTERMS.source)):
            fail(
                f"composition specification lacks source provenance: {specification}",
                failures,
            )
        if list(g.objects(specification, SIO.SIO_000772)):
            fail(
                "composition specification incorrectly uses proposition-level "
                f"SIO_000772 evidence: {specification}",
                failures,
            )

    for row in assertions:
        if (
            row["status"] == "confirmed"
            and row["predicate_iri"] == str(SIO.SIO_000244)
        ):
            subject = URIRef(row["subject_iri"])
            product = URIRef(row["object_iri"])
            if (product, SIO.SIO_000245, subject) not in g:
                fail(
                    f"confirmed product link lacks SIO_000245 inverse: {subject}",
                    failures,
                )

    for row in dispositions:
        disposition = URIRef(row["disposition_id"])
        about = URIRef(row["about_entity_id"])
        evidence = URIRef(row["evidence_id"])
        if (
            disposition,
            SIO.SIO_000332,
            about,
        ) not in g or (about, SIO.SIO_000629, disposition) not in g:
            fail(
                f"missing reciprocal disposition/about edges for {disposition}",
                failures,
            )
        if (
            disposition,
            SIO.SIO_000772,
            evidence,
        ) not in g or (evidence, SIO.SIO_000773, disposition) not in g:
            fail(
                f"missing reciprocal disposition/evidence edges for {disposition}",
                failures,
            )

    run_accessions = [row["run_accession"] for row in occurrences if row["run_accession"]]
    if len(run_accessions) != len(set(run_accessions)):
        fail("control run accessions are not unique", failures)
    for row in occurrences:
        if not row["read_1_file"] or not row["read_2_file"]:
            fail(f"control occurrence lacks paired raw-file references: {row['fastq_entity_id']}", failures)
        fastq = URIRef(row["fastq_entity_id"])
        if (fastq, RDF.type, BASE.RAK_0000318) not in g:
            fail(f"control FASTQ lacks control-derived type: {fastq}", failures)
        lane_match = re.search(r"_L(\d{3})_", row["read_1_file"])
        if lane_match and row["lane"] != lane_match.group(1):
            fail(
                f"normalized lane differs from FASTQ path for {row['fastq_entity_id']}",
                failures,
            )
    trip4_occurrences = [
        row
        for row in occurrences
        if row["source_snapshot_id"]
        == "data/metadata/samplesheets/additional_fastqs_v2.tsv"
    ]
    if len(trip4_occurrences) != 6:
        fail(
            "expected six Trip-4 control occurrences sourced from "
            "additional_fastqs_v2.tsv",
            failures,
        )

    with (analysis / "summary.json").open(encoding="utf-8") as handle:
        summary = json.load(handle)
    if summary["positive_controls_in_training"] != 0:
        fail("analysis summary reports positive controls in contaminant training", failures)
    if summary["training_extraction_blanks"] != [f"EB{i}" for i in range(1, 18)]:
        fail("training set is not exactly mapped Trip-5 EB1-EB17", failures)
    analysis_roles = read_tsv(analysis / "control_analysis_roles.tsv")
    positive_analysis_profiles = {
        row["profile_id"]
        for row in analysis_roles
        if row["control_role"] == "positive_control"
    }
    if len(positive_analysis_profiles) != 7:
        fail("expected exactly seven unambiguously positive 16S profiles", failures)
    positive_profiles = read_tsv(analysis / "positive_control_profiles.tsv")
    recovery_rows = read_tsv(
        analysis / "positive_control_expected_taxon_recovery.tsv"
    )
    expected_assignment_status = (
        "provisional_from_positive_label_and_trip_design"
    )
    for table_name, table in (
        ("positive_control_profiles.tsv", positive_profiles),
        ("positive_control_expected_taxon_recovery.tsv", recovery_rows),
    ):
        if not table or any(
            row.get("product_assignment_status") != expected_assignment_status
            for row in table
        ):
            fail(
                f"{table_name} does not bound every library/product mapping "
                "as provisional",
                failures,
            )
    mock_dominated = {
        row["profile_id"]
        for row in positive_profiles
        if row.get("profile_interpretation", "").startswith("mock_dominated_")
    }
    if mock_dominated != {"e8661_FPosCtrl2", "e8665_FPosCtrl3"}:
        fail(
            "declared positive-profile interpretation does not identify "
            "exactly the two mock-dominated profiles",
            failures,
        )
    for row in analysis_roles:
        if row["control_role"] == "positive_control" and "training" in row["use"] and "never" not in row["use"]:
            fail(f"positive control used for contaminant training: {row['profile_id']}", failures)
    calls = read_tsv(analysis / "trip5_primary_contaminant_calls.tsv")
    if len(calls) != summary["primary_candidate_contaminant_features"]:
        fail("candidate-call count differs from summary", failures)
    if summary["mapped_biological_profiles_in_canonical_table"] != 217:
        fail("unexpected mapped Trip-5 biological profile denominator", failures)
    filtered = analysis / "trip5_mapped_feature_table_control_filtered.tsv.gz"
    digest = hashlib.sha256()
    with filtered.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    if digest.hexdigest() != summary["filtered_sensitivity_table_sha256"]:
        fail("filtered sensitivity-table checksum differs from summary", failures)
    with gzip.open(filtered, "rt", encoding="utf-8") as handle:
        handle.readline()
        filtered_header = handle.readline().rstrip("\n").split("\t")
    if len(filtered_header) - 1 != 217:
        fail("filtered sensitivity table does not contain 217 mapped profiles", failures)

    sensitivity_summary = json.loads(
        (sensitivity_inputs / "summary.json").read_text(encoding="utf-8")
    )
    if sensitivity_summary["candidate_features"] != len(calls):
        fail("sensitivity input uses a different candidate-feature set", failures)
    if sensitivity_summary["mapped_profiles"] != 217:
        fail("sensitivity input uses an unexpected profile universe", failures)
    if sensitivity_summary["profiles_below_rarefaction_depth_after_filter"] != 0:
        fail("control filtering pushed a mapped profile below rarefaction depth", failures)
    for relative, expected in sensitivity_summary["output_sha256"].items():
        path = root / relative
        if not path.is_file():
            path = sensitivity_inputs / Path(relative).name
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            fail(f"control-sensitivity checksum differs: {relative}", failures)

    spillover_summary = json.loads(
        (analysis / "positive_control_spillover_summary.json").read_text(
            encoding="utf-8"
        )
    )
    if spillover_summary["positive_profiles"] != 7:
        fail("positive-control spillover audit has an unexpected denominator", failures)
    if spillover_summary["negative_profiles"] != 9:
        fail("positive-control spillover audit has an unexpected negative set", failures)
    spillover_rows = read_tsv(
        analysis / "positive_control_expected_asv_occurrences.tsv"
    )
    if len(spillover_rows) != spillover_summary["occurrence_rows"]:
        fail("positive-control spillover occurrence count differs", failures)
    if any(
        row["interpretation"]
        != "exact_ASV_overlap_descriptive_only_not_proof_of_index_hopping"
        for row in spillover_rows
    ):
        fail("positive-control spillover interpretation is not bounded", failures)

    # Known source conflicts must stay explicit.
    disposition_text = "\n".join(row["description"] for row in dispositions)
    for fragment in [
        "more than one Trip-4 extraction blank",
        "no positive control travelled with Trip 4",
        "shotgun metagenomics",
        "sterile-bag field-control inventory was requested",
        "e0323_Ctrl_1_Trip1",
    ]:
        if fragment not in disposition_text:
            fail(f"required explicit disposition absent: {fragment}", failures)

    if failures:
        for message in failures:
            print("FAIL:", message, file=sys.stderr)
        return 1
    print(
        "PASS: control validation "
        f"({len(registry)} entities, {len(g):,} triples, {len(roles)} roles, "
        f"{len(occurrences)} sequence occurrences, {len(calls)} candidate ASVs)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
