#!/usr/bin/env python3
"""Prepare audited MAG metadata; sequence and analysis release remains gated."""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import math
from collections import Counter
from pathlib import Path


SOURCE = "evidence/mag-catalogue-20261024/source"
DEST = "metadata/metagenome/canonical"

FIELDS = {
    "sample": ("string", "not applicable", "Source library/sample code; retained verbatim."),
    "trip": ("integer", "not applicable", "Sampling campaign number, 1 through 5."),
    "site": ("string", "not applicable", "Source site code; 61 distinct codes do not establish 61 distinct physical sites."),
    "code": ("string", "not applicable", "Source compartment code from the paired-read inventory."),
    "replicate": ("integer", "not applicable", "Source field-replicate number."),
    "compartment": ("string", "not applicable", "Original compartment label; Rhizosphere denotes root-adjacent soil."),
    "study_accession": ("string", "not applicable", "Author-confirmed ENA shotgun study PRJEB125153; not yet public on 2026-10-24."),
    "secondary_study_accession": ("string", "not applicable", "Secondary ENA study accession ERP204894."),
    "run_accession": ("string", "not applicable", "ENA run accession; crosswalk remains to be supplied."),
    "mag": ("string", "not applicable", "Identifier of a representative in the actual refined dRep output."),
    "strategy": ("string", "not applicable", "Source binning strategy: single_sample or self_supervised."),
    "bin": ("string", "not applicable", "Parent bin label retained from the pickup catalogue membership table."),
    "refined_sub": ("integer", "not applicable", "1 identifies a refined _sub representative; 0 identifies other representatives."),
    "drep_fasta_basename": ("string", "not applicable", "FASTA basename in the actual dRep output; sequence delivery is blocked."),
    "legacy_link_target": ("string", "not applicable", "Pickup link provenance: per_sample_bin or drep_genome. Parent-bin links require sequence reconciliation."),
    "Completeness": ("decimal", "percent", "CheckM2 completeness estimate for the refined dRep sequence."),
    "Contamination": ("decimal", "percent", "CheckM2 contamination estimate for the refined dRep sequence."),
    "Genome_Size": ("integer", "bp", "Refined-bin genome size from CheckM2."),
    "Total_Contigs": ("integer", "contigs", "Refined-bin contig count from CheckM2."),
    "gtdb_r232_classification": ("string", "not applicable", "Unmodified GTDB-Tk R232 lineage from the exact representative-ID match."),
    "path": ("path", "not applicable", "Portable member path inside refined_mags.tar.gz."),
    "bytes": ("integer", "bytes", "Exact uncompressed FASTA size."),
    "sha256": ("hexadecimal string", "not applicable", "SHA-256 of the exact uncompressed FASTA bytes."),
    "contigs": ("integer", "contigs", "FASTA sequence count, checked against refined-bin CheckM2."),
    "bases": ("integer", "bp", "FASTA sequence length sum, checked against refined-bin CheckM2."),
}


def read_table(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def index_rows(rows, key):
    result = {}
    for row in rows:
        identifier = row[key]
        if not identifier or identifier in result:
            raise ValueError(f"missing or duplicate {key}: {identifier!r}")
        result[identifier] = row
    return result


def derive(membership, libraries, context, quality, legacy):
    mags = index_rows(membership, "mag")
    libs = index_rows(libraries, "sample")
    contexts = index_rows(context, "sample")
    qualities = index_rows(quality, "Name")
    old = index_rows(legacy, "sample")
    if set(libs) != set(contexts):
        raise ValueError("library list and sample metadata differ")
    if not set(old) <= set(libs):
        raise ValueError("legacy libraries absent from the read-bearing library list")
    library_rows = []
    for sample, row in sorted(libs.items()):
        for key in ("trip", "site", "replicate"):
            if row[key] != contexts[sample][key]:
                raise ValueError(f"library context disagrees: {sample} {key}")
        library_rows.append({
            **{key: row[key] for key in ("sample", "trip", "site", "code", "replicate")},
            "compartment": contexts[sample]["compartment"],
            "study_accession": "PRJEB125153",
            "secondary_study_accession": "ERP204894",
            "run_accession": "",
        })
    representatives = []
    for mag, row in sorted(mags.items()):
        if row["sample"] not in libs or mag not in qualities:
            raise ValueError(f"missing library or refined-bin quality: {mag}")
        q = qualities[mag]
        completeness, contamination = float(q["Completeness"]), float(q["Contamination"])
        if not (math.isfinite(completeness) and math.isfinite(contamination)
                and 50 <= completeness <= 100 and 0 <= contamination <= 10):
            raise ValueError(f"quality outside recorded dRep thresholds: {mag}")
        for key in ("Genome_Size", "Total_Contigs"):
            if int(q[key]) <= 0:
                raise ValueError(f"invalid {key}: {mag}")
        if row["refined_sub"] not in ("0", "1"):
            raise ValueError(f"invalid refined_sub: {mag}")
        library = libs[row["sample"]]
        representatives.append({
            **{key: row[key] for key in ("mag", "sample", "strategy", "bin", "refined_sub")},
            "trip": library["trip"], "site": library["site"],
            "drep_fasta_basename": mag + ".fa",
            "legacy_link_target": row["link_target"],
            **{key: q[key] for key in ("Completeness", "Contamination", "Genome_Size", "Total_Contigs")},
        })
    summary = {
        "release_status": "REFINED_SELECTED_PACKAGING_PENDING",
        "sequence_selection": "actual refined dRep representatives; Robert Hoehndorf, 2026-10-24",
        "study_accession": "PRJEB125153", "secondary_study_accession": "ERP204894",
        "accession_evidence": "Robert Hoehndorf, 2026-10-24; study not yet public",
        "representatives": len(mags), "read_bearing_libraries": len(libs),
        "site_codes": len({r["site"] for r in libraries}),
        "libraries_per_trip": dict(sorted(Counter(r["trip"] for r in libraries).items())),
        "legacy_libraries_per_trip": dict(sorted(Counter(r["trip"] for r in legacy).items())),
        "refined_sub_representatives": sum(r["refined_sub"] == "1" for r in membership),
        "quality_scope": "05_refine/_checkm2_refined; actual dRep representatives, not linked parent bins",
        "sequence_release": False, "annotation_release": False, "recruitment_release": False,
        "blocking_items": [
            "Complete checksum-verified packaging of the selected actual refined dRep sequences.",
            "Verify taxonomy and functional annotations against the chosen sequence content.",
            "Rebuild recruitment against the actual refined sequences; existing parent-bin-reference coverage is excluded.",
            "Complete run/sample accession mapping and ENA MAG submission metadata.",
            "Confirm run-specific versions and parameters across all assembly/binning strategies.",
        ],
    }
    return library_rows, representatives, summary


def write_table(path, rows):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def attach_taxonomy(representatives, source):
    taxonomy_dir = source / "taxonomy_r232"
    checksums = {}
    for line in (taxonomy_dir / "CHECKSUMS.sha256").read_text().splitlines():
        digest, path = line.split(maxsplit=1)
        checksums[Path(path).name] = digest
    tables = []
    for domain in ("ar53", "bac120"):
        name = f"gtdbtk.{domain}.summary.tsv"
        path = taxonomy_dir / name
        if hashlib.sha256(path.read_bytes()).hexdigest() != checksums[name]:
            raise ValueError(f"GTDB source checksum differs: {name}")
        tables.extend(read_table(path))
    taxonomy = index_rows(tables, "user_genome")
    if set(taxonomy) != {r["mag"] for r in representatives}:
        raise ValueError("GTDB R232 and representative identifier sets differ")
    for row in representatives:
        row["gtdb_r232_classification"] = taxonomy[row["mag"]]["classification"]


def register(root):
    """Extend only this task's dictionary and manifest rows, retaining other dispositions."""
    dictionary_path = root / "metadata/DATA_DICTIONARY.tsv"
    dictionary = [r for r in read_table(dictionary_path) if not r["path"].startswith(DEST + "/")]
    for path in sorted((root / DEST).glob("*.tsv")):
        for field in read_table(path)[0]:
            datatype, unit, description = FIELDS[field]
            dictionary.append({"path": str(path.relative_to(root)), "field_or_pattern": field,
                               "data_type": datatype, "unit": unit,
                               "missing_convention": "blank: unresolved" if field == "run_accession" else "never blank",
                               "description": description})
    write_table(dictionary_path, dictionary)
    spec = importlib.util.spec_from_file_location("release_manifest", root / "scripts/manuscript/update_pre_release_manifest.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    manifest = root / "PRE_RELEASE_MANIFEST.tsv"
    rows = {r["path"]: r for r in read_table(manifest)}
    paths = [p for folder in (root / DEST, root / "evidence/mag-catalogue-20261024")
             for p in folder.rglob("*") if p.is_file() and p.name != "refined_mags.tar.gz"]
    paths += [root / "evidence/mag-catalogue-20261024/README.md", dictionary_path,
              root / "scripts/release/prepare_mag_metadata.py", root / "tests/test_mag_metadata.py",
              root / "scripts/release/package_refined_mags.py", root / "tests/test_package_refined_mags.py",
              root / "scripts/release/rebuild_refined_mag_analyses.py",
              root / "scripts/release/rebuild_refined_mag_analyses.sbatch",
              root / "tests/test_rebuild_refined_mag_analyses.py",
              root / "scripts/manuscript/update_pre_release_manifest.py"]
    for path in paths:
        relative = str(path.relative_to(root))
        if relative not in rows or relative.startswith((DEST + "/", "evidence/mag-catalogue-20261024/")):
            classification = module.ADDITIONS.get(relative) or module.classify(relative)
            if classification is None:
                raise ValueError(f"unclassified MAG preparation artifact: {relative}")
            category, status, scope = classification
            licence, gate = module.license_disposition(relative)
            rows[relative] = {"path": relative, "category": category, "release_status": status,
                              "record_scope": scope, "bytes": "", "sha256": "",
                              "license_status": licence, "license_gate": gate}
        rows[relative].update(bytes=str(path.stat().st_size), sha256=module.sha256(path))
    receipt_path = root / DEST / "packaging_receipt.json"
    if receipt_path.exists():
        receipt = json.loads(receipt_path.read_text())
        relative = DEST + "/refined_mags.tar.gz"
        licence, gate = module.license_disposition(relative)
        rows[relative] = {"path": relative, "category": "mag-sequences", "release_status": "canonical-candidate",
                          "record_scope": "5438 actual refined dRep FASTAs; every archived member verified against its checksum and refined-bin quality lengths",
                          "bytes": str(receipt["bytes"]), "sha256": receipt["sha256"],
                          "license_status": licence, "license_gate": gate}
        bulk_path = root / "BULK_ARTIFACTS.tsv"
        bulk = {r["path"]: r for r in read_table(bulk_path)}
        bulk[relative] = {"path": relative, "role": "canonical-input", "bytes": str(receipt["bytes"]),
                          "sha256": receipt["sha256"], "distribution": "private-ibex-staging",
                          "required_for": "refined-mag-catalogue;refined-mag-analyses"}
        write_table(bulk_path, list(bulk.values()))
    module.write_manifest(manifest, list(rows.values()))


def prepare(root):
    source, dest = root / SOURCE, root / DEST
    names = ("catalog_membership.tsv", "samples551.tsv", "metagenome_sample_meta.tsv",
             "checkm2_refined_quality_report.tsv", "metagenome_sample_meta_150.tsv")
    libraries, representatives, summary = derive(*(read_table(source / name) for name in names))
    if (len(libraries), len(representatives)) != (551, 5438):
        raise ValueError("source snapshot differs from the reviewed 551-library / 5438-representative inventory")
    attach_taxonomy(representatives, source)
    summary["taxonomy"] = {"tool": "GTDB-Tk", "version": "2.7.2", "database": "R232",
                           "representatives": len(representatives), "source_checksums_verified": True}
    summary["blocking_items"][1] = "Verify functional annotations against the chosen sequence content; R232 taxonomy matches refined representative IDs."
    receipt_path = dest / "packaging_receipt.json"
    if receipt_path.exists():
        receipt = json.loads(receipt_path.read_text())
        if (receipt["representatives"] != len(representatives)
                or not receipt["archive_members_verified"] or not receipt["quality_lengths_verified"]):
            raise ValueError("invalid sequence packaging receipt")
        manifest = read_table(dest / "genome_manifest.tsv")
        manifest_by_mag = index_rows(manifest, "mag")
        if set(manifest_by_mag) != {r["mag"] for r in representatives}:
            raise ValueError("packaged genome IDs differ from metadata")
        for row in representatives:
            entry = manifest_by_mag[row["mag"]]
            if (entry["bases"], entry["contigs"]) != (row["Genome_Size"], row["Total_Contigs"]):
                raise ValueError(f"packaged genome quality differs: {row['mag']}")
        summary["release_status"] = "SEQUENCE_CANDIDATE_ANALYSES_PENDING"
        summary["sequence_release"] = True
        summary["public_release"] = False
        summary["blocking_items"].pop(0)
        summary["blocking_items"].append("Publish the verified private-staging archive with an immutable public/reviewer locator.")
        summary["sequence_archive"] = receipt
    summary["source_sha256"] = {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(source.rglob("*")) if p.is_file()
    }
    dest.mkdir(parents=True, exist_ok=True)
    write_table(dest / "library_metadata.tsv", libraries)
    write_table(dest / "refined_representatives.tsv", representatives)
    if receipt_path.exists() and receipt["metadata_sha256"] != hashlib.sha256((dest / "refined_representatives.tsv").read_bytes()).hexdigest():
        raise ValueError("packaging receipt refers to different representative metadata")
    (dest / "release_status.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps({k: summary[k] for k in ("release_status", "representatives", "read_bearing_libraries")}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--register", action="store_true", help="update scoped data dictionary and pre-release manifest rows")
    args = parser.parse_args()
    prepare(args.root)
    if args.register:
        register(args.root)
