#!/usr/bin/env python3
"""Classify climate fetch keys by resolving them against the site module.

The Open-Meteo retrieval keyed on the ``Site`` column of the per-trip geodata
sheets.  That column is a field notebook column, not an integer primary key: it
carries the 60 numbered sites, several of the ten *named* site individuals, and
a residue of labels that denote no site at all.

The distinction that matters is not "integer versus not".  It is "does this
label resolve to a sampling-site individual in
``rubalkhali_sites.owl``".  This script applies exactly the resolution that
``scripts/rdf/generate_measurements_abox.groovy`` applies: index every site
individual by its full ``rdfs:label`` and, for labels beginning ``Site ``, also
by the remainder.  Under that rule 66 of the 81 raw keys resolve --- 60
numbered and six named --- which is why the released measurement module holds
12,936 monthly climate records (66 sites x 49 months x four variables).

Keys are classified as:

``canonical_numeric_site``
    resolves to a site individual labelled ``Site <n>``
``canonical_named_site``
    resolves to a named site individual (for example ``Site hot spring``)
``near_site_annotation``
    begins with digits but does not resolve; the offset is unrecorded
``free_text_location``
    does not resolve and carries no numeric stem

Only the 15 unresolved keys are quarantined.  A near-site label is *not*
mapped onto its numeric stem: ``47+grass`` records a reading taken near site
47, not a reading of site 47, and the offset was never written down.

Outputs (under ``data/processed/climate/``):

* ``climate_fetch_key_ledger.tsv`` --- one row per distinct key with its
  disposition and resolved site IRI
* ``monthly_weather_averages_canonical.tsv``, ``daily_weather_canonical.tsv``
  --- site-resolved rows only
* ``climate_key_audit.json`` --- monthly, daily and annual counts, checksums,
  and resolution evidence

The script fails closed: an unreadable input, an absent site module, or a key
that cannot be classified aborts the run.
"""

from __future__ import annotations

import argparse
import csv
import glob
import hashlib
import json
import re
import sys
from pathlib import Path
from xml.etree import ElementTree

RDF = "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}"
OWL = "{http://www.w3.org/2002/07/owl#}"
RDFS = "{http://www.w3.org/2000/01/rdf-schema#}"
SAMPLING_SITE = "https://rubalkhali.science/kb/RAK_0000002"

NUMBERED_LABEL = re.compile(r"^Site \d+$")
NUMERIC_STEM = re.compile(r"^(?P<stem>\d+)(?:\.\d+)?(?P<rest>[^\d].*)?$")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def site_index(module: Path) -> tuple[dict[str, str], dict[str, str]]:
    """Label -> IRI index, replicating the generator's resolution rule.

    Returns (label_to_iri, iri_to_label). Both the full label and, for labels
    beginning "Site ", the remainder are indexed, exactly as
    generate_measurements_abox.groovy does.
    """
    tree = ElementTree.parse(module)
    label_to_iri: dict[str, str] = {}
    iri_to_label: dict[str, str] = {}
    for individual in tree.getroot().findall(f"{OWL}NamedIndividual"):
        iri = individual.get(f"{RDF}about")
        types = {
            element.get(f"{RDF}resource")
            for element in individual.findall(f"{RDF}type")
            if element.get(f"{RDF}resource")
        }
        if iri is None or SAMPLING_SITE not in types:
            continue
        element = individual.find(f"{RDFS}label")
        if element is None or not (element.text or "").strip():
            continue
        label = element.text.strip()
        iri_to_label[iri] = label
        label_to_iri[label] = iri
        if label.startswith("Site "):
            label_to_iri[label[5:]] = iri
    return label_to_iri, iri_to_label


def classify(key: str, label_to_iri: dict[str, str], iri_to_label: dict[str, str]) -> tuple[str, str, str]:
    """Return (disposition, resolved_site_iri, rationale)."""
    stripped = key.strip()
    iri = label_to_iri.get(stripped)
    if iri is not None:
        label = iri_to_label[iri]
        if NUMBERED_LABEL.fullmatch(label):
            return (
                "canonical_numeric_site",
                iri,
                f"resolves to numbered site individual labelled {label!r}",
            )
        return (
            "canonical_named_site",
            iri,
            f"resolves to named site individual labelled {label!r}",
        )
    match = NUMERIC_STEM.fullmatch(stripped)
    if match:
        return (
            "near_site_annotation",
            "",
            f"does not resolve; numeric stem {match.group('stem')} recorded as "
            "provenance only, the offset is unrecorded",
        )
    if stripped:
        return ("free_text_location", "", "does not resolve to any site individual")
    return ("unclassified", "", "empty key")


def read_keys(paths: list[Path], column: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for path in paths:
        with path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle, delimiter="\t"):
                key = (row.get(column) or "").strip()
                counts[key] = counts.get(key, 0) + 1
    return counts


def project_resolved(
    source: Path, destination: Path, column: str, resolved: set[str]
) -> tuple[int, int]:
    with source.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        fieldnames = reader.fieldnames or []
        kept, dropped = [], 0
        for row in reader:
            if (row.get(column) or "").strip() in resolved:
                kept.append(row)
            else:
                dropped += 1
    with destination.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(kept)
    return len(kept), dropped


def annual_projection_counts(
    paths: list[Path], resolved: set[str]
) -> dict[str, int]:
    """Count annual source rows/values retained by exact site-key resolution."""
    value_columns = (
        "AnnualMeanTemp",
        "AnnualTotalPrecip",
        "AnnualTotalRain",
    )
    source_rows = resolved_rows = source_values = resolved_values = 0
    for path in paths:
        with path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle, delimiter="\t"):
                values = sum(bool((row.get(column) or "").strip()) for column in value_columns)
                if not values:
                    continue
                source_rows += 1
                source_values += values
                if (row.get("Site") or "").strip() in resolved:
                    resolved_rows += 1
                    resolved_values += values
    return {
        "source_rows": source_rows,
        "site_resolved_rows": resolved_rows,
        "quarantined_rows": source_rows - resolved_rows,
        "source_measurement_values": source_values,
        "site_resolved_measurement_values": resolved_values,
        "quarantined_measurement_values": source_values - resolved_values,
        "variables_per_complete_row": len(value_columns),
    }


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=root)
    parser.add_argument(
        "--sites-module",
        type=Path,
        default=root / "data/processed/semantics/ontology/rubalkhali_sites.owl",
    )
    args = parser.parse_args()
    project_root = args.project_root.resolve()

    climate_dir = project_root / "data/processed/climate"
    monthly = climate_dir / "monthly_weather_averages.tsv"
    daily = climate_dir / "daily_weather.tsv"
    geodata = sorted(
        Path(path)
        for path in glob.glob(str(project_root / "data/metadata/geodata/trip*_geodata.tsv"))
    )
    for required in (monthly, daily, args.sites_module, *geodata):
        if not required.is_file():
            print(f"FAIL: required input is absent: {required}", file=sys.stderr)
            return 1

    label_to_iri, iri_to_label = site_index(args.sites_module)
    if not iri_to_label:
        print(f"FAIL: no sampling-site individuals in {args.sites_module}", file=sys.stderr)
        return 1

    keys: dict[str, dict[str, int]] = {}
    for label, paths in (("monthly", [monthly]), ("daily", [daily]), ("geodata", geodata)):
        for key, count in read_keys(paths, "Site").items():
            keys.setdefault(key, {})[label] = count

    ledger_rows = []
    unclassified = []
    resolved_keys: set[str] = set()
    for key in sorted(keys):
        disposition, iri, rationale = classify(key, label_to_iri, iri_to_label)
        if disposition == "unclassified":
            unclassified.append(key)
        if iri:
            resolved_keys.add(key)
        ledger_rows.append(
            {
                "fetch_key": key,
                "disposition": disposition,
                "resolved_site_iri": iri,
                "resolved_site_label": iri_to_label.get(iri, ""),
                "rationale": rationale,
                "monthly_rows": keys[key].get("monthly", 0),
                "daily_rows": keys[key].get("daily", 0),
                "geodata_rows": keys[key].get("geodata", 0),
            }
        )
    if unclassified:
        print(f"FAIL: unclassifiable fetch keys: {unclassified}", file=sys.stderr)
        return 1

    ledger = climate_dir / "climate_fetch_key_ledger.tsv"
    with ledger.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=list(ledger_rows[0]), delimiter="\t", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(ledger_rows)

    monthly_canonical = climate_dir / "monthly_weather_averages_canonical.tsv"
    daily_canonical = climate_dir / "daily_weather_canonical.tsv"
    monthly_kept, monthly_dropped = project_resolved(monthly, monthly_canonical, "Site", resolved_keys)
    daily_kept, daily_dropped = project_resolved(daily, daily_canonical, "Site", resolved_keys)
    annual = annual_projection_counts(geodata, resolved_keys)

    by_disposition: dict[str, int] = {}
    for row in ledger_rows:
        by_disposition[row["disposition"]] = by_disposition.get(row["disposition"], 0) + 1

    audit = {
        "sites_module": str(args.sites_module.relative_to(project_root)),
        "sites_module_sha256": sha256(args.sites_module),
        "sampling_site_individuals": len(iri_to_label),
        "resolution_rule": (
            "Index every sampling-site individual by its full rdfs:label and, for "
            "labels beginning 'Site ', also by the remainder. This is the rule in "
            "scripts/rdf/generate_measurements_abox.groovy."
        ),
        "distinct_fetch_keys": len(ledger_rows),
        "keys_by_disposition": by_disposition,
        "site_resolved_keys": len(resolved_keys),
        "named_site_keys": {
            row["fetch_key"]: row["resolved_site_iri"]
            for row in ledger_rows
            if row["disposition"] == "canonical_named_site"
        },
        "unresolved_keys": sorted(
            row["fetch_key"] for row in ledger_rows if not row["resolved_site_iri"]
        ),
        "monthly": {
            "source": str(monthly.relative_to(project_root)),
            "source_sha256": sha256(monthly),
            "resolved_rows": monthly_kept,
            "quarantined_rows": monthly_dropped,
            "resolved_sha256": sha256(monthly_canonical),
        },
        "daily": {
            "source": str(daily.relative_to(project_root)),
            "source_sha256": sha256(daily),
            "resolved_rows": daily_kept,
            "quarantined_rows": daily_dropped,
            "resolved_sha256": sha256(daily_canonical),
        },
        "annual": annual,
        "ledger_sha256": sha256(ledger),
        "note": (
            "The measurement generator uses exact site-key resolution for both "
            "monthly and annual climate records. The unresolved labels are "
            "retained in the source tables and in this ledger and excluded from "
            "the site-resolved graph; coordinate fallback is forbidden for "
            "annual records because it would map near-site observations onto "
            "their stem site."
        ),
    }
    (climate_dir / "climate_key_audit.json").write_text(
        json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    print(
        f"{len(ledger_rows)} fetch keys: "
        f"{by_disposition.get('canonical_numeric_site', 0)} numbered sites, "
        f"{by_disposition.get('canonical_named_site', 0)} named sites, "
        f"{by_disposition.get('near_site_annotation', 0)} near-site annotations, "
        f"{by_disposition.get('free_text_location', 0)} free-text locations"
    )
    print(
        f"monthly {monthly_kept} resolved / {monthly_dropped} quarantined; "
        f"daily {daily_kept} resolved / {daily_dropped} quarantined; "
        f"annual {annual['site_resolved_measurement_values']} resolved / "
        f"{annual['quarantined_measurement_values']} quarantined values"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
