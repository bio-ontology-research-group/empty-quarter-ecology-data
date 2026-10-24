#!/usr/bin/env python3
"""Reference construction and fail-closed checks for refined-MAG analyses."""

import argparse
from collections import Counter
import csv
import hashlib
import json
import math
from pathlib import Path
import subprocess

from package_refined_mags import sha256


def table(path):
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def unique(rows, key):
    result = {r[key]: r for r in rows}
    if len(result) != len(rows) or "" in result:
        raise ValueError(f"duplicate or missing {key}")
    return result


def build_reference(genomes, manifest, output):
    rows = unique(table(manifest), "mag")
    output.mkdir(parents=True, exist_ok=True)
    reference = output / "refined.fa"
    if reference.exists():
        raise ValueError("reference already exists; use a fresh directory")
    with reference.open("wb") as fasta, (output / "genomes.tsv").open("w") as definition:
        for mag, row in sorted(rows.items()):
            path = genomes / (mag + ".fa")
            if sha256(path) != row["sha256"]:
                raise ValueError(f"FASTA changed since packaging: {mag}")
            with path.open("rb") as source:
                for line in source:
                    if line.startswith(b">"):
                        original = line[1:].split()[0].decode("ascii")
                        name = mag + "|" + original
                        fasta.write((">" + name + "\n").encode())
                        definition.write(mag + "\t" + name + "\n")
                    else:
                        fasta.write(line)
    receipt = {"genomes": len(rows), "reference_sha256": sha256(reference),
               "definition_sha256": sha256(output / "genomes.tsv"),
               "source_manifest_sha256": sha256(manifest),
               "contig_policy": "prefix every original ID with MAG|; retain every contig"}
    (output / "reference_receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")


def validate_coverage(path, sample, genomes):
    rows = table(path)
    by_name = unique(rows, "Genome")
    if set(by_name) != set(genomes):
        raise ValueError(f"coverage genome set differs for {sample}")
    for mag, row in by_name.items():
        for metric in ("Mean", "Covered Fraction", "Trimmed Mean", "Read Count", "Length"):
            value = float(row[f"{sample} {metric}"])
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"invalid {metric}: {sample}/{mag}")
            if metric == "Covered Fraction" and value > 1:
                raise ValueError("covered fraction exceeds one")
            if metric == "Read Count" and not value.is_integer():
                raise ValueError("non-integer read count")
            if metric == "Length" and value != int(genomes[mag]["bases"]):
                raise ValueError(f"coverage reference length differs: {sample}/{mag}")


def annotation_receipt(work, mag, directory):
    genomes = unique(table(work / "release/genome_manifest.tsv"), "mag")
    files = [directory / "bakta" / (mag + suffix) for suffix in (".faa", ".gff3", ".fna")]
    files += [directory / "eggnog" / (mag + ".emapper.annotations"),
              directory / "bakta.version.txt", directory / "eggnog.version.txt"]
    if any(not p.is_file() or not p.stat().st_size for p in files):
        raise ValueError(f"missing annotation output: {mag}")
    # Parse annotations before marking the task complete, including header checks.
    with files[0].open() as handle:
        proteins = {line[1:].split()[0] for line in handle if line.startswith(">")}
    for row in annotation_rows(files[3]):
        if row["query"] not in proteins:
            raise ValueError(f"eggNOG query absent from source proteome: {mag}/{row['query']}")
    receipt = {"mag": mag, "source_sha256": genomes[mag]["sha256"],
               "files": {str(p.relative_to(directory)): sha256(p) for p in files},
               "bakta_db": "/ibex/reference/KSL/bakta/6.0/db",
               "eggnog_db": "/ibex/reference/KSL/eggnog-mapper/2.1.12"}
    existing = directory / "DONE.json"
    if existing.exists() and json.loads(existing.read_text()) != receipt:
        raise ValueError(f"completed annotation changed: {mag}")
    (directory / "DONE.json").write_text(json.dumps(receipt, indent=2) + "\n")


def annotation_rows(path):
    with path.open() as handle:
        header = None
        queries = set()
        for line in handle:
            if line.startswith("#query\t"):
                header = line.rstrip("\n").lstrip("#").split("\t")
                if not {"query", "KEGG_ko", "CAZy", "PFAMs", "Preferred_name"} <= set(header):
                    raise ValueError("unexpected eggNOG header")
            elif line.startswith("#") or not line.strip():
                continue
            else:
                if header is None:
                    raise ValueError("missing eggNOG header")
                values = line.rstrip("\n").split("\t")
                if len(values) != len(header) or values[0] in queries:
                    raise ValueError("malformed or duplicate eggNOG query")
                queries.add(values[0])
                yield dict(zip(header, values))
        if header is None:
            raise ValueError("missing eggNOG header")


def feature_counts(path):
    counts = {name: Counter() for name in ("ko", "cazy", "pfam", "prefname")}
    annotated = with_ko = 0
    for row in annotation_rows(path):
        annotated += 1
        for name, column in (("ko", "KEGG_ko"), ("cazy", "CAZy"), ("pfam", "PFAMs"), ("prefname", "Preferred_name")):
            values = set(row[column].split(",")) - {"", "-"}
            if name == "ko":
                values = {v[3:] if v.startswith("ko:") else v for v in values}
                with_ko += bool(values)
            counts[name].update(values)
    return counts, annotated, with_ko


def finish(work):
    genomes = unique(table(work / "release/genome_manifest.tsv"), "mag")
    samples = unique(table(work / "samples551.tsv"), "sample")
    if len(genomes) != 5438 or len(samples) != 551:
        raise ValueError("release cardinality differs")
    cov = work / "coverage"
    if {p.stem for p in cov.glob("*.tsv")} != set(samples):
        raise ValueError("coverage is incomplete or has unexpected samples")
    for sample in samples:
        validate_coverage(cov / (sample + ".tsv"), sample, genomes)
    provenance = []
    for mag, genome in genomes.items():
        directory = work / "annotations" / mag
        receipt = json.loads((directory / "DONE.json").read_text())
        if receipt["source_sha256"] != genome["sha256"]:
            raise ValueError(f"annotation source differs: {mag}")
        for name, checksum in receipt["files"].items():
            if sha256(directory / name) != checksum:
                raise ValueError(f"annotation bytes changed: {mag}/{name}")
        provenance.append({"genome": mag, "fasta_sha256": genome["sha256"],
                           "bakta_version": (directory / "bakta.version.txt").read_text().strip().replace("\n", "; "),
                           "eggnog_version": (directory / "eggnog.version.txt").read_text().strip().replace("\n", "; "),
                           "annotation_sha256": receipt["files"]["eggnog/" + mag + ".emapper.annotations"]})
    output = work / "functional"
    output.mkdir(exist_ok=True)
    with (output / "annotation_provenance.tsv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(provenance[0]), delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(provenance)
    handles = {name: (output / f"genome_{name}_long.tsv").open("w") for name in ("ko", "cazy", "pfam", "prefname")}
    try:
        for name, handle in handles.items():
            handle.write(f"genome\t{name}\tcount\n")
        with (output / "genome_ngenes.tsv").open("w") as genes:
            genes.write("genome\tn_genes_predicted\tn_genes_annotated\tn_with_ko\n")
            for mag in sorted(genomes):
                directory = work / "annotations" / mag
                counts, annotated, with_ko = feature_counts(directory / "eggnog" / (mag + ".emapper.annotations"))
                with (directory / "bakta" / (mag + ".faa")).open() as proteins:
                    predicted = sum(line.startswith(">") for line in proteins)
                if annotated > predicted:
                    raise ValueError(f"more annotated queries than predicted proteins: {mag}")
                genes.write(f"{mag}\t{predicted}\t{annotated}\t{with_ko}\n")
                for name, features in counts.items():
                    for feature, count in sorted(features.items()):
                        handles[name].write(f"{mag}\t{feature}\t{count}\n")
    finally:
        for handle in handles.values():
            handle.close()
    artifacts = []
    for name, members in (
        ("refined_functional_tables.tar.gz", ["functional"]),
        ("refined_coverm_profiles.tar.gz", ["coverage", "reference/reference_receipt.json", "reference/genomes.tsv", "samples551.tsv"]),
    ):
        target = work / "release" / name
        with target.open("wb") as handle:
            proc = subprocess.Popen(["tar", "--sort=name", "--mtime=@0", "--owner=0", "--group=0", "--numeric-owner",
                                     "-C", str(work), "-cf", "-", *members], stdout=subprocess.PIPE)
            gz = subprocess.run(["gzip", "-n", "-1"], stdin=proc.stdout, stdout=handle)
            proc.stdout.close()
            if proc.wait() or gz.returncode:
                raise ValueError("analysis packaging failed")
        subprocess.run(["gzip", "-t", str(target)], check=True)
        artifacts.append({"artifact": name, "bytes": target.stat().st_size, "sha256": sha256(target)})
    receipt = {"status": "COMPLETE", "genomes": len(genomes), "libraries": len(samples), "artifacts": artifacts}
    (work / "release/analysis_receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("reference", "coverage", "annotation-receipt", "finish"))
    parser.add_argument("--work", required=True, type=Path)
    parser.add_argument("--genomes", type=Path)
    parser.add_argument("--sample")
    parser.add_argument("--mag")
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--complete", action="store_true")
    args = parser.parse_args()
    if args.mode == "reference":
        build_reference(args.genomes, args.work / "release/genome_manifest.tsv", args.work / "reference")
    elif args.mode == "coverage":
        suffix = ".tsv" if args.complete else ".tsv.partial"
        validate_coverage(args.work / "coverage" / (args.sample + suffix), args.sample,
                          unique(table(args.work / "release/genome_manifest.tsv"), "mag"))
    elif args.mode == "annotation-receipt":
        annotation_receipt(args.work, args.mag, args.directory)
    else:
        finish(args.work)
