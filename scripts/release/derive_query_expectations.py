#!/usr/bin/env python3
"""Derive printed-query tuples from source counts and fresh tractable modules.

Does not read the generated taxonomy ABox or contact a SPARQL endpoint.
The process identifier allocation follows the documented sorted profile/run
contract; abundance is independently aggregated from the feature-count TSV.
"""
import argparse
import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
from rdflib import Graph, Namespace, RDF, RDFS, URIRef

B = Namespace("https://rubalkhali.science/kb/")
R = Namespace(str(B) + "RAK_")
S = Namespace("http://semanticscience.org/resource/SIO_")
P = Namespace("http://purl.obolibrary.org/obo/PATO_")


def normalize(raw):
    fields = raw.split(";")
    if len(fields) == 9:
        float(fields[8])
        fields = fields[:7]
    assert len(fields) == 7
    fields = [re.sub(r"^[dkpcofgs]__", "", x.strip(), flags=re.I).strip() for x in fields]
    return ";".join("NA" if x.lower() in ("", "na", "n/a", "unclassified", "uncultured") else x for x in fields)


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": h.hexdigest()}


def write_table(path, columns, rows):
    with path.open("w", newline="") as stream:
        out = csv.DictWriter(stream, columns, delimiter="\t")
        out.writeheader()
        out.writerows(rows)


def select_taxonomy_run(rows, accession):
    """Select the complete run from all source-derived rows, never a preview."""
    label = "FASTQ dataset for " + accession
    selected = [row for row in rows if row["runLabel"] == label]
    if not selected:
        raise ValueError("No source-derived genus rows for " + label)
    return selected


def emitted_lineage(source_lineage):
    """Match generate_taxonomy_abox.groovy lineageFor, retaining raw identity upstream."""
    ranks = ("Domain", "Phylum", "Class", "Order", "Family", "Genus", "Species")
    segments = source_lineage.split(";")
    if not 1 <= len(segments) <= len(ranks):
        raise ValueError("Expected one to seven canonical lineage ranks")
    return "; ".join(rank + ": " + (segment or "NA") for rank, segment in zip(ranks, segments))


def validate_read_counts(counts):
    """Read-count source values must support the explicit integer ORDER BY."""
    if not (np.isfinite(counts).all() and (counts >= 0).all() and (counts == np.floor(counts)).all()):
        raise ValueError("Read counts must be finite, nonnegative integers")


def taxonomy_numeric_order(row):
    return (row["runLabel"], -int(row["count"]), row["lineage"], row["proc"])


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--source", type=Path, required=True)
    cli.add_argument("--mapping", type=Path, required=True)
    cli.add_argument("--ecosystem", type=Path, required=True)
    cli.add_argument("--modules", type=Path, required=True)
    cli.add_argument("--reference-dir", type=Path, required=True,
                     help="Exact four root reference modules loaded in the asserted release union")
    cli.add_argument("--output", type=Path, required=True)
    cli.add_argument("--run-accession", default="ERR16061083",
                     help="Complete genus-profile expectation, selected before any preview limit")
    a = cli.parse_args()
    a.output.mkdir(parents=True, exist_ok=True)
    inputs = [a.mapping, a.ecosystem]
    mapping = json.loads(a.mapping.read_text())
    metadata = a.source / "metadata"
    if not metadata.is_dir():
        metadata = a.source / "data/metadata"
    source_tax = metadata / "taxonomy/taxonomy-trips1-5.tsv"
    feature_table = metadata / "taxonomy/feature-table-trips1-5.tsv"
    sra_sheet = metadata / "sra-submissions/submission-sheet.tsv"
    inputs.extend([source_tax, feature_table, sra_sheet])
    inputs.append(a.source / "scripts/rdf/generate_taxonomy_abox.groovy")
    feature_keys = {}
    keys = set()
    with source_tax.open() as stream:
        for row in csv.DictReader(stream, delimiter="\t"):
            lineage = normalize(row["Taxon"])
            taxon = mapping[lineage][5]["iri"]
            key = (taxon, ";".join(lineage.split(";")[:6]))
            feature_keys[row["Feature ID"]] = key
            keys.add(key)
    keys = sorted(keys)
    write_table(a.output / "taxonomy_lineage_source_projection.tsv", ["taxon", "source_lineage", "emitted_lineage"],
                [dict(taxon=taxon, source_lineage=lineage, emitted_lineage=emitted_lineage(lineage)) for taxon, lineage in keys])
    key_index = {k: i for i, k in enumerate(keys)}
    graph = Graph()
    for name in ("rubalkhali.owl", "rubalkhali_sites.owl", "rubalkhali_measurements.owl",
                 "rubalkhali_samples.owl", "rubalkhali_dna.owl", "rubalkhali_sra.owl", "rubalkhali_xrf.owl"):
        path = a.modules / name
        graph.parse(path, format="xml")
        inputs.append(path)
        print("loaded", name, len(graph), flush=True)
    graph.parse(a.ecosystem, format="turtle")
    for name in ("sio.owl", "envo.owl", "pato.owl", "uo.owl"):
        path = a.reference_dir / name
        graph.parse(path, format="xml")
        inputs.append(path)
        print("loaded reference", name, len(graph), flush=True)
    fastqs = {}
    for subject, label in graph.subject_objects(RDFS.label):
        if str(label).startswith("FASTQ dataset for "):
            fastqs[str(label).removeprefix("FASTQ dataset for ")] = str(subject)
    runs = defaultdict(set)
    with sra_sheet.open() as stream:
        for row in csv.DictReader(stream, delimiter="\t"):
            if row["run_accession"].strip() in fastqs:
                runs[row["sample_name"].strip()].add(row["run_accession"].strip())
    runs = {k: sorted(v) for k, v in runs.items()}
    with feature_table.open() as stream:
        skip = int(stream.readline().startswith("# Constructed"))
    header = pd.read_csv(feature_table, sep="\t", skiprows=skip, nrows=0).columns.tolist()
    profiles = sorted(header[1:])
    values = np.zeros((len(keys), len(profiles)), dtype=np.float64)
    for chunk in pd.read_csv(feature_table, sep="\t", skiprows=skip, chunksize=2000):
        counts = chunk[profiles].to_numpy(dtype=np.float64)
        validate_read_counts(counts)
        idx = [key_index[feature_keys[f]] for f in chunk.iloc[:, 0]]
        np.add.at(values, idx, counts)
    totals = values.sum(axis=0)
    active = [(p, i) for i, p in enumerate(profiles) if totals[i] > 0]
    per_sample = Counter(p.split("_")[-1] for p, _ in active)
    usage = Counter()
    plans = []
    for profile, col in active:
        sample = profile.split("_")[-1]
        if sample not in runs:
            continue
        choices = runs[sample]
        if per_sample[sample] == 1 and len(choices) > 1:
            selected = choices
        else:
            selected = [choices[min(usage[sample], len(choices) - 1)]]
            usage[sample] += 1
        for run in selected:
            plans.append((str(R[f"P{290001 + len(plans)}"]), fastqs[run], run, profile, col))
    taxonomy_rows = []
    pseudo = defaultdict(list)
    for proc, fastq, run, profile, col in plans:
        for idx in np.flatnonzero(values[:, col]):
            taxon, lineage = keys[idx]
            count = float(values[idx, col])
            rel = count / float(totals[col])
            for label in graph.objects(URIRef(taxon), RDFS.label):
                taxonomy_rows.append(dict(proc=proc, fastq=fastq, runLabel="FASTQ dataset for " + run,
                                          lineage=emitted_lineage(lineage), taxon=taxon, taxonLabel=str(label),
                                          count=count, relativeAbundance=rel))
            if taxon == "http://purl.obolibrary.org/obo/NCBITaxon_286":
                pseudo[URIRef(fastq)].append((emitted_lineage(lineage), rel))
    validate_read_counts(values)
    taxonomy_rows.sort(key=taxonomy_numeric_order)
    write_table(a.output / "taxonomy_first100.tsv", ["proc", "fastq", "runLabel", "lineage", "taxon", "taxonLabel", "count", "relativeAbundance"], taxonomy_rows[:100])
    run_rows = select_taxonomy_run(taxonomy_rows, a.run_accession)
    write_table(a.output / ("taxonomy_" + a.run_accession + "_genus.tsv"),
                ["proc", "fastq", "runLabel", "lineage", "taxon", "taxonLabel", "count", "relativeAbundance"], run_rows)
    write_table(a.output / "taxonomy_process_source_map.tsv", ["proc", "fastq", "run", "profile", "mapped_read_total"],
                [dict(proc=p, fastq=f, run=r, profile=pr, mapped_read_total=float(totals[c])) for p, f, r, pr, c in plans])
    # Explicit traversal preserves multiplicity of independent intermediate
    # process paths, matching the printed SELECT without DISTINCT.
    sample_fastqs = defaultdict(list)
    libpreps = set(graph.subjects(RDF.type, R["0000065"]))
    sequencing = set(graph.subjects(RDF.type, R["0000066"]))
    for fastq in pseudo:
        for seq in graph.subjects(S["000229"], fastq):
            if seq not in sequencing:
                continue
            for lib in graph.objects(seq, S["000230"]):
                for prep in graph.subjects(S["000229"], lib):
                    if prep not in libpreps:
                        continue
                    for dna in graph.objects(prep, S["000230"]):
                        for ext in graph.subjects(S["000229"], dna):
                            for sample in graph.objects(ext, S["000230"]):
                                sample_fastqs[sample].append(fastq)
    env_rows = []
    sampling_processes = set(graph.subjects(RDF.type, R["0000024"]))
    for visit in graph.subjects(RDF.type, R["0000003"]):
        for site in graph.objects(visit, S["000291"]):
            temperatures = []
            for process in graph.subjects(S["000068"], visit):
                for value in graph.objects(process, S["000229"]):
                    for temp in graph.objects(value, R["2000003"]):
                        if float(temp) <= 35:
                            continue
                        for quality in graph.objects(value, S["000215"]):
                            if (quality, RDF.type, P["0000146"]) in graph and (quality, S["000011"], site) in graph:
                                temperatures.append((process, value, float(temp)))
            for sampling in graph.subjects(S["000068"], visit):
                if sampling not in sampling_processes or (sampling, S["000291"], site) not in graph:
                    continue
                for collection in graph.objects(sampling, S["000229"]):
                    for sample in graph.objects(collection, S["000059"]):
                        for fastq in sample_fastqs[sample]:
                            for lineage, rel in pseudo[fastq]:
                                for process, value, temp in temperatures:
                                    for visit_label in graph.objects(visit, RDFS.label):
                                        for site_label in graph.objects(site, RDFS.label):
                                            env_rows.append(dict(visit=str(visit), visitLabel=str(visit_label), site=str(site), siteLabel=str(site_label), sample=str(sample), fastq=str(fastq), temperatureProcess=str(process), tempVal=str(value), temp=temp, lineage=lineage, relAbundance=rel))
    env_rows.sort(key=lambda r: tuple(r[k] for k in ("visit", "sample", "fastq", "tempVal", "lineage")))
    write_table(a.output / "environment_pseudomonas_gt35.tsv", ["visit", "visitLabel", "site", "siteLabel", "sample", "fastq", "temperatureProcess", "tempVal", "temp", "lineage", "relAbundance"], env_rows)
    result = dict(status="derived", method=__doc__, lineage_projection="Raw classifier lineage defines aggregation identity; output literals use the frozen RDF producer lineageFor encoding: rank name, colon-space, segment or NA; ranks joined by semicolon-space. taxonomy_lineage_source_projection.tsv retains both forms.", taxonomy_full_rows=len(taxonomy_rows), taxonomy_preview_rows=min(100, len(taxonomy_rows)), taxonomy_run_accession=a.run_accession, taxonomy_run_rows=len(run_rows), taxonomy_run_selection="Exact runLabel selection from the complete source-derived genus table before any preview limit; all rows and projected multiplicities retained", taxonomy_processes=len(plans), environmental_rows=len(env_rows), producer=digest(Path(__file__).resolve()), inputs=[digest(p) for p in inputs])
    (a.output / "source_expectations_manifest.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k not in ("inputs", "method")}), flush=True)


if __name__ == "__main__":
    main()
