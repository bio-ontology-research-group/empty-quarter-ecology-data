#!/usr/bin/env python3
"""Fail-closed audit of the XRF analyte-to-chemical-identifier mapping.

The audit resolves every configured ChEBI identifier against the repository's
pinned ChEBI OWL file and every PubChem CID against a dated API snapshot.  It
checks existence, obsolescence, label presence, neutral charge, formula
composition, and the intended atom-versus-oxide entity type.  The output TSV
is also the source ledger consumed by ``data-paper/scripts/generate_xrf_table.py``.

Network access is used only with ``--fetch-pubchem``.  Normal reproducible runs
read the checked-in snapshot and therefore do not depend on a live service.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import math
import re
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

RDF_ABOUT = "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}about"
OWL_CLASS = "{http://www.w3.org/2002/07/owl#}Class"
OWL_ONTOLOGY = "{http://www.w3.org/2002/07/owl#}Ontology"
OWL_DEPRECATED = "{http://www.w3.org/2002/07/owl#}deprecated"
RDFS_LABEL = "{http://www.w3.org/2000/01/rdf-schema#}label"
CHEMROF_FORMULA = "{https://w3id.org/chemrof/}generalized_empirical_formula"
CHEMROF_CHARGE = "{https://w3id.org/chemrof/}charge"
OBO_DATE = (
    "{http://www.geneontology.org/formats/oboInOwl#}date"
)
OWL_VERSION_INFO = "{http://www.w3.org/2002/07/owl#}versionInfo"
CHEBI_PREFIX = "http://purl.obolibrary.org/obo/CHEBI_"
PUBCHEM_PREFIX = "https://pubchem.ncbi.nlm.nih.gov/compound/"

FORMULA_TOKEN = re.compile(r"([A-Z][a-z]?)([0-9]*)")
OXIDE = re.compile(r"^(?:[A-Z][a-z]?[0-9]*)+O[0-9]*$")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_formula(value: str | None) -> Counter[str] | None:
    """Parse the simple elemental formulae used by this mapping.

    ChEBI represents some ionic products with dot-separated components and
    leading coefficients (for example ``2K.O`` and ``Ca.O``).  This parser
    intentionally rejects parentheses and other complex notation because no
    released XRF channel requires it.
    """

    if not value:
        return None
    value = value.strip().replace("·", ".")
    if not value:
        return None
    composition: Counter[str] = Counter()
    for component in value.split("."):
        match = re.fullmatch(r"([0-9]*)(.*)", component)
        if not match:
            return None
        coefficient = int(match.group(1) or "1")
        body = match.group(2)
        tokens = list(FORMULA_TOKEN.finditer(body))
        if not tokens or "".join(item.group(0) for item in tokens) != body:
            return None
        for token in tokens:
            composition[token.group(1)] += coefficient * int(token.group(2) or "1")
    return composition or None


def reduced(composition: Counter[str] | None) -> Counter[str] | None:
    if not composition:
        return composition
    divisor = math.gcd(*composition.values())
    return Counter({element: count // divisor for element, count in composition.items()})


def formula_relation(expected: str, observed: str | None) -> str:
    expected_composition = parse_formula(expected)
    observed_composition = parse_formula(observed)
    if observed_composition is None:
        return "not_asserted"
    if expected_composition == observed_composition:
        return "exact"
    if reduced(expected_composition) == reduced(observed_composition):
        return "empirical_equivalent"
    return "mismatch"


def extract_identifier(value: str | None, prefix: str) -> str | None:
    if value is None:
        return None
    if not value.startswith(prefix):
        raise ValueError(f"identifier does not use expected prefix {prefix}: {value}")
    identifier = value.removeprefix(prefix)
    if not identifier.isdigit():
        raise ValueError(f"identifier is not numeric: {value}")
    return identifier


def read_chebi(
    path: Path, target_iris: set[str]
) -> tuple[dict[str, dict[str, str | bool | None]], dict[str, str]]:
    """Stream only the requested classes from the large pinned ChEBI OWL."""

    records: dict[str, dict[str, str | bool | None]] = {}
    metadata: dict[str, str] = {}
    for _event, element in ET.iterparse(path, events=("end",)):
        if element.tag == OWL_ONTOLOGY:
            date_node = element.find(OBO_DATE)
            version_node = element.find(OWL_VERSION_INFO)
            metadata = {
                "version": (version_node.text or "").strip() if version_node is not None else "",
                "date": (date_node.text or "").strip() if date_node is not None else "",
            }
            element.clear()
        elif element.tag == OWL_CLASS:
            iri = element.attrib.get(RDF_ABOUT)
            if iri in target_iris:
                label_node = element.find(RDFS_LABEL)
                formula_node = element.find(CHEMROF_FORMULA)
                charge_node = element.find(CHEMROF_CHARGE)
                deprecated_node = element.find(OWL_DEPRECATED)
                records[iri] = {
                    "label": (
                        (label_node.text or "").strip() if label_node is not None else ""
                    ),
                    "formula": (
                        (formula_node.text or "").strip()
                        if formula_node is not None
                        else None
                    ),
                    "charge": (
                        (charge_node.text or "").strip()
                        if charge_node is not None
                        else None
                    ),
                    "deprecated": (
                        (deprecated_node.text or "").strip().casefold() == "true"
                        if deprecated_node is not None
                        else False
                    ),
                }
            element.clear()
        elif element.tag.endswith("Axiom"):
            element.clear()
    return records, metadata


def fetch_pubchem(cids: list[str]) -> dict[str, Any]:
    properties: dict[str, dict[str, Any]] = {}
    fields = "Title,MolecularFormula,Charge,IUPACName,InChIKey"
    for offset in range(0, len(cids), 40):
        batch = cids[offset : offset + 40]
        endpoint = (
            "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/"
            + ",".join(batch)
            + f"/property/{fields}/JSON"
        )
        request = urllib.request.Request(
            endpoint,
            headers={"User-Agent": "empty-quarter-xrf-audit/1.0"},
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                payload = json.load(response)
        except (urllib.error.URLError, TimeoutError) as error:
            raise RuntimeError(f"PubChem request failed for {batch}: {error}") from error
        for record in payload["PropertyTable"]["Properties"]:
            properties[str(record["CID"])] = record
    missing = sorted(set(cids).difference(properties))
    if missing:
        raise RuntimeError("PubChem response omitted CID(s): " + ", ".join(missing))
    return {
        "retrieved_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "endpoint_template": (
            "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/"
            "{comma-separated-CIDs}/property/"
            f"{fields}/JSON"
        ),
        "properties": properties,
    }


def validate_charge(value: Any) -> bool:
    return str(value).strip() in {"0", "0.0"}


def audit(
    mapping_path: Path,
    chebi_path: Path,
    snapshot_path: Path,
    reviewed_by: str,
    reviewed_date: str,
) -> dict[str, Any]:
    with mapping_path.open(encoding="utf-8") as handle:
        document = yaml.safe_load(handle)
    mappings = document["mappings"]

    chebi_iris = {
        entry["chebi"]
        for entry in mappings.values()
        if isinstance(entry, dict) and entry.get("chebi")
    }
    chebi_records, chebi_metadata = read_chebi(chebi_path, chebi_iris)
    with snapshot_path.open(encoding="utf-8") as handle:
        pubchem_snapshot = json.load(handle)
    pubchem_records = pubchem_snapshot["properties"]

    rows: list[dict[str, str]] = []
    errors: list[str] = []
    for analyte, entry in mappings.items():
        expected_formula = "" if analyte == "LE" else analyte
        entity_type = (
            "instrument_pseudoanalyte"
            if analyte == "LE"
            else ("neutral oxide" if OXIDE.fullmatch(analyte) else "neutral atom")
        )
        chebi_iri = entry.get("chebi")
        pubchem_url = entry.get("pubchem")
        chebi_id = extract_identifier(chebi_iri, CHEBI_PREFIX)
        pubchem_cid = extract_identifier(pubchem_url, PUBCHEM_PREFIX)
        notes: list[str] = []

        chebi_label = ""
        chebi_formula = ""
        chebi_charge = ""
        chebi_status = "not_mapped"
        if chebi_iri:
            record = chebi_records.get(chebi_iri)
            if record is None:
                chebi_status = "missing_identifier"
            else:
                chebi_label = str(record["label"] or "")
                chebi_formula = str(record["formula"] or "")
                chebi_charge = str(record["charge"] or "")
                relation = formula_relation(expected_formula, chebi_formula)
                allowed_relation = entry.get("chebi_formula_relation", "exact")
                formula_ok = relation == allowed_relation
                if relation == "not_asserted":
                    formula_ok = bool(
                        entry.get("chebi_formula_unavailable")
                        and chebi_label.casefold()
                        == str(entry.get("chebi_expected_label", "")).casefold()
                    )
                    if formula_ok:
                        notes.append("ChEBI formula absent; exact label gate applied")
                charge_ok = validate_charge(chebi_charge)
                if (
                    not chebi_charge
                    and entry.get("chebi_charge_unavailable")
                    and entity_type == "neutral oxide"
                ):
                    charge_ok = True
                    notes.append("ChEBI charge absent; neutral exact-label gate applied")
                type_ok = bool(chebi_label) and charge_ok
                if entity_type == "neutral atom":
                    type_ok = (
                        type_ok
                        and parse_formula(chebi_formula) == Counter({analyte: 1})
                    )
                if record["deprecated"]:
                    chebi_status = "deprecated"
                elif not formula_ok:
                    chebi_status = f"formula_{relation}"
                elif not type_ok:
                    chebi_status = "entity_type_or_charge_mismatch"
                else:
                    chebi_status = "verified"

        pubchem_title = ""
        pubchem_formula = ""
        pubchem_charge = ""
        pubchem_status = "not_mapped"
        if pubchem_cid:
            record = pubchem_records.get(pubchem_cid)
            if record is None:
                pubchem_status = "missing_identifier"
            else:
                pubchem_title = str(record.get("Title", ""))
                pubchem_formula = str(record.get("MolecularFormula", ""))
                pubchem_charge = str(record.get("Charge", ""))
                relation = formula_relation(expected_formula, pubchem_formula)
                type_ok = bool(pubchem_title) and validate_charge(pubchem_charge)
                if entity_type == "neutral atom":
                    type_ok = (
                        type_ok
                        and parse_formula(pubchem_formula) == Counter({analyte: 1})
                    )
                if relation != "exact":
                    pubchem_status = f"formula_{relation}"
                elif not type_ok:
                    pubchem_status = "entity_type_or_charge_mismatch"
                else:
                    pubchem_status = "verified"

        if analyte == "LE":
            overall_status = (
                "verified"
                if chebi_iri is None
                and pubchem_url is None
                and entry.get("semantic_status") == "instrument_pseudoanalyte"
                else "failed"
            )
        elif (
            entry.get("semantic_status") == "local_formula_only"
            and chebi_iri is None
            and pubchem_url is None
            and bool(entry.get("definition"))
        ):
            overall_status = "verified"
            notes.append("No formula-matching external identifier; local formula retained")
        else:
            applicable = [
                status
                for status in (chebi_status, pubchem_status)
                if status != "not_mapped"
            ]
            overall_status = (
                "verified"
                if applicable and all(status == "verified" for status in applicable)
                else "failed"
            )
        if overall_status != "verified":
            errors.append(
                f"{analyte}: ChEBI={chebi_status}; PubChem={pubchem_status}"
            )

        evidence = "; ".join(
            value for value in (chebi_iri or "", pubchem_url or "") if value
        )
        rows.append(
            {
                "analyte": analyte,
                "formula": expected_formula,
                "entity_type": entity_type,
                "chebi": f"CHEBI:{chebi_id}" if chebi_id else "",
                "chebi_label": chebi_label,
                "chebi_formula": chebi_formula,
                "chebi_charge": chebi_charge,
                "chebi_status": chebi_status,
                "pubchem": f"CID:{pubchem_cid}" if pubchem_cid else "",
                "pubchem_label": pubchem_title,
                "pubchem_formula": pubchem_formula,
                "pubchem_charge": pubchem_charge,
                "pubchem_status": pubchem_status,
                "status": overall_status,
                "evidence_url": evidence,
                "reviewed_by": reviewed_by,
                "reviewed_date": reviewed_date,
                "notes": "; ".join(notes),
            }
        )

    return {
        "status": "passed" if not errors else "failed",
        "errors": errors,
        "metadata": {
            "mapping_path": str(mapping_path),
            "mapping_sha256": sha256(mapping_path),
            "chebi_path": str(chebi_path),
            "chebi_sha256": sha256(chebi_path),
            "chebi_version": chebi_metadata.get("version", ""),
            "chebi_date": chebi_metadata.get("date", ""),
            "pubchem_snapshot_path": str(snapshot_path),
            "pubchem_snapshot_sha256": sha256(snapshot_path),
            "pubchem_retrieved_at": pubchem_snapshot.get("retrieved_at", ""),
            "reviewed_by": reviewed_by,
            "reviewed_date": reviewed_date,
            "row_count": len(rows),
        },
        "rows": rows,
    }


def write_outputs(result: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "xrf_chemical_mapping_audit.json"
    json_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    columns = [
        "analyte",
        "formula",
        "entity_type",
        "chebi",
        "chebi_label",
        "chebi_formula",
        "chebi_charge",
        "chebi_status",
        "pubchem",
        "pubchem_label",
        "pubchem_formula",
        "pubchem_charge",
        "pubchem_status",
        "status",
        "evidence_url",
        "reviewed_by",
        "reviewed_date",
        "notes",
    ]
    with (output_dir / "xrf_chemical_mapping_audit.tsv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.DictWriter(handle, delimiter="\t", fieldnames=columns)
        writer.writeheader()
        writer.writerows(result["rows"])

    checksum_path = output_dir / "SHA256SUMS"
    outputs = [
        output_dir / "xrf_chemical_mapping_audit.json",
        output_dir / "xrf_chemical_mapping_audit.tsv",
    ]
    checksum_path.write_text(
        "".join(f"{sha256(path)}  {path.name}\n" for path in outputs),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mapping",
        type=Path,
        default=Path("config/codes/xrf_chemical_mapping.yml"),
    )
    parser.add_argument(
        "--chebi",
        type=Path,
        default=Path("data/ontologies/chebi.owl"),
    )
    parser.add_argument(
        "--pubchem-snapshot",
        type=Path,
        default=Path("config/codes/xrf_pubchem_snapshot.json"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/release/xrf_chemical_mapping_audit"),
    )
    parser.add_argument("--fetch-pubchem", action="store_true")
    parser.add_argument(
        "--reviewed-by",
        default="automated pinned-source audit",
    )
    parser.add_argument(
        "--reviewed-date",
        default=None,
    )
    args = parser.parse_args()

    with args.mapping.open(encoding="utf-8") as handle:
        mapping_document = yaml.safe_load(handle)
    mappings = mapping_document["mappings"]
    reviewed_date = args.reviewed_date or str(
        mapping_document.get("metadata", {}).get(
            "audit_date", dt.date.today().isoformat()
        )
    )
    if args.fetch_pubchem:
        cids = sorted(
            {
                extract_identifier(entry.get("pubchem"), PUBCHEM_PREFIX)
                for entry in mappings.values()
                if entry.get("pubchem")
            },
            key=int,
        )
        snapshot = fetch_pubchem(cids)
        args.pubchem_snapshot.parent.mkdir(parents=True, exist_ok=True)
        args.pubchem_snapshot.write_text(
            json.dumps(snapshot, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    if not args.pubchem_snapshot.exists():
        parser.error(
            f"PubChem snapshot missing: {args.pubchem_snapshot}; "
            "run once with --fetch-pubchem"
        )

    result = audit(
        args.mapping,
        args.chebi,
        args.pubchem_snapshot,
        args.reviewed_by,
        reviewed_date,
    )
    write_outputs(result, args.output_dir)
    if result["errors"]:
        for error in result["errors"]:
            print(error, file=sys.stderr)
        return 1
    print(
        f"PASS: {result['metadata']['row_count']} XRF analyte mappings verified "
        f"against ChEBI {result['metadata']['chebi_version']} and the PubChem snapshot"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
