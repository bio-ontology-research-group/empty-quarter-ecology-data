#!/usr/bin/env python3
"""Benchmark the 9 competency questions against the Virtuoso endpoint.

Runs each query N times, records wall-clock latency, reports
median, mean, p95, and result-row count. Output is a TSV written to
stdout (and also to data-paper/metrics/cq_latencies.tsv when invoked
from the data-paper directory).
"""
from __future__ import annotations

import json
import statistics
import sys
import time
import urllib.parse
import urllib.request

ENDPOINT = "http://localhost:8895/sparql"
N = 10

PREFIXES = """PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX owl: <http://www.w3.org/2002/07/owl#>
PREFIX sio: <http://semanticscience.org/resource/SIO_>
PREFIX rak: <https://rubalkhali.science/kb/RAK_>
PREFIX geo: <http://www.opengis.net/ont/geosparql#>
PREFIX uo: <http://purl.obolibrary.org/obo/UO_>
PREFIX pato: <http://purl.obolibrary.org/obo/PATO_>
PREFIX ncbitaxon: <http://purl.obolibrary.org/obo/NCBITaxon_>
"""

QUERIES: list[tuple[str, str, str]] = [
    (
        "CQ1", "Field XRF measurements for Site 10",
        """SELECT ?processLabel ?analyte ?concentration ?unitLabel WHERE {
  ?sample a rak:0000021 ; rdfs:label ?sampleLabel .
  FILTER(REGEX(?sampleLabel, "Site 10"))
  ?value sio:000232 ?process .
  ?process rdfs:label ?processLabel .
  FILTER(REGEX(?processLabel, "Field", "i"))
  ?sample sio:000008 ?quality .
  ?quality sio:000215 ?value .
  ?value rak:2000012 ?concentration .
  ?value sio:000221 ?unit .
  ?unit rdfs:label ?unitLabel .
  ?quality a ?qualityClass .
  ?qualityClass rdfs:label ?analyte .
  FILTER(?qualityClass != rak:0000029)
} ORDER BY ?processLabel ?analyte LIMIT 100""",
    ),
    (
        "CQ2", "All sampling sites and GPS coordinates",
        """SELECT ?site ?label ?wkt WHERE {
  ?site a rak:0000002 ; rdfs:label ?label .
  OPTIONAL { ?site geo:asWKT ?wkt . }
} ORDER BY ?label""",
    ),
    (
        "CQ3", "Biomes per site (OWL restriction inspection)",
        """SELECT DISTINCT ?siteLabel ?biomeLabel WHERE {
  ?site a rak:0000002 ; rdfs:label ?siteLabel .
  ?site a [ a owl:Restriction ;
            owl:onProperty rak:2000001 ;
            owl:someValuesFrom ?biomeClass ] .
  ?biomeClass rdfs:label ?biomeLabel .
} ORDER BY ?siteLabel""",
    ),
    (
        "CQ4", "Light Elements percentages across XRF runs",
        """SELECT ?processLabel ?lePercentage WHERE {
  ?quality a rak:0000032 .
  ?quality sio:000215 ?value .
  ?value rak:2000012 ?lePercentage .
  ?value sio:000232 ?process .
  ?process rdfs:label ?processLabel .
} ORDER BY DESC(?lePercentage)""",
    ),
    (
        "CQ5", "DNA extraction records and concentrations",
        """SELECT ?soilSampleLabel ?dnaExtractLabel ?agentLabel ?protocolLabel ?kitLabel ?concentrationValue WHERE {
  ?dnaExtract a rak:0000040 ; rdfs:label ?dnaExtractLabel .
  ?extProcess sio:000229 ?dnaExtract ;
              sio:000230 ?soilSample ;
              sio:000139 ?agent .
  ?soilSample rdfs:label ?soilSampleLabel .
  ?agent rdfs:label ?agentLabel .
  OPTIONAL { ?extProcess sio:000339 ?protocol . ?protocol rdfs:label ?protocolLabel . }
  OPTIONAL { ?extProcess rak:2000014 ?kit . ?kit rdfs:label ?kitLabel . }
  OPTIONAL { ?measProcess sio:000291 ?dnaExtract ; sio:000229 ?quantity .
             ?quantity rak:2000015 ?concentrationValue . }
} ORDER BY ?soilSampleLabel""",
    ),
    (
        "CQ6", "Provenance: soil → DNA → library → run",
        """SELECT ?soilSample ?library ?bioSample ?run WHERE {
  ?extProcess sio:000230 ?soilInd ; sio:000229 ?dnaInd .
  ?soilInd rdfs:label ?soilSample .
  ?libPrep sio:000230 ?dnaInd ; sio:000229 ?libInd .
  ?libInd rdfs:label ?library ; rdfs:seeAlso ?bioSample .
  ?seqProcess sio:000230 ?libInd ; sio:000229 ?fastqInd .
  ?fastqInd rdfs:seeAlso ?run .
} ORDER BY ?soilSample LIMIT 25""",
    ),
    (
        "CQ7", "Taxonomic composition and abundance per run",
        """SELECT DISTINCT ?run ?taxonLabel ?count ?relativeAbundance WHERE {
  ?proc a rak:0000071 ; sio:000230 ?fastq ; sio:000229 ?dsAbs , ?dsRel .
  ?dsAbs a rak:0000074 . ?dsRel a rak:0000075 .
  ?fastq rdfs:label ?runLabel .
  BIND(REPLACE(?runLabel, "FASTQ dataset for ", "") AS ?run)
  ?dsAbs sio:000059 ?valAbs . ?valAbs rak:2000021 ?count .
  ?valAbs sio:000215 ?qualAbs . ?qualAbs sio:000011 ?taxon .
  ?taxon rdfs:label ?taxonLabel .
  ?qualRel sio:000011 ?taxon ; a rak:0000072 ; sio:000214 ?valRel .
  ?valRel rak:2000020 ?relativeAbundance .
  FILTER(?taxon != ?fastq)
} ORDER BY ?run DESC(?count) LIMIT 100""",
    ),
    (
        "CQ8", "Pseudomonas at sites with temperature > 35 °C",
        """SELECT ?siteLabel ?temp ?relAbundance WHERE {
  ?site a rak:0000002 ; rdfs:label ?siteLabel .
  ?tempProcess sio:000291 ?site ; sio:000229 ?tempVal .
  ?tempVal rak:2000012 ?temp ; sio:000215 ?tempQual .
  ?tempQual a pato:0000146 .
  FILTER(?temp > 35.0)
  ?sample sio:000252 ?site .
  ?ext sio:000230 ?sample ; a rak:0000041 ; sio:000229 ?dna .
  ?libPrep sio:000230 ?dna ; a rak:0000062 ; sio:000229 ?lib .
  ?seq sio:000230 ?lib ; a rak:0000064 ; sio:000229 ?fastq .
  ?bioinf a rak:0000071 ; sio:000230 ?fastq ; sio:000229 ?dsRel .
  ?dsRel a rak:0000075 ; sio:000059 ?valRel .
  ?valRel rak:2000020 ?relAbundance ; sio:000215 ?qualRel .
  ?qualRel sio:000011 ncbitaxon:286 .
}""",
    ),
    (
        "CQ9", "Sequencing QC metrics for sample 10Dr2",
        """SELECT ?datasetLabel ?metric ?value ?unit WHERE {
  ?dataset a rak:0000063 ; rdfs:label ?datasetLabel .
  FILTER(CONTAINS(?datasetLabel, "10Dr2"))
  ?quality sio:000218 ?dataset ; a ?qualityType ; rdfs:label ?metric .
  ?measure sio:000215 ?quality ; sio:000221 ?unitEntity .
  ?unitEntity rdfs:label ?unit .
  { ?measure rak:2000071 ?value . }
  UNION { ?measure rak:2000072 ?value . }
  UNION { ?measure rak:2000074 ?value . }
  UNION { ?measure rak:2000075 ?value . }
} ORDER BY ?metric""",
    ),
]


def run_query(q: str) -> tuple[float, int, str | None]:
    """Run a single query, return (latency_seconds, row_count, error)."""
    body = urllib.parse.urlencode({"query": PREFIXES + q, "format": "application/sparql-results+json"}).encode()
    req = urllib.request.Request(ENDPOINT, data=body,
                                  headers={"Accept": "application/sparql-results+json"})
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            payload = resp.read()
        dt = time.perf_counter() - t0
        data = json.loads(payload)
        rows = len(data.get("results", {}).get("bindings", []))
        return dt, rows, None
    except Exception as e:
        return time.perf_counter() - t0, 0, str(e)[:120]


def main() -> None:
    print("id\tdescription\trows\tn\tmedian_s\tmean_s\tp95_s\tmin_s\tmax_s\tnotes", flush=True)
    for cq_id, desc, q in QUERIES:
        latencies: list[float] = []
        rows = 0
        note = ""
        # warm-up
        dt, rows, err = run_query(q)
        if err:
            print(f"{cq_id}\t{desc}\t0\t0\tNA\tNA\tNA\tNA\tNA\tERROR: {err}", flush=True)
            continue
        for _ in range(N):
            dt, rows, err = run_query(q)
            if err:
                note = f"ERROR after {len(latencies)} runs: {err}"
                break
            latencies.append(dt)
        if not latencies:
            print(f"{cq_id}\t{desc}\t{rows}\t0\tNA\tNA\tNA\tNA\tNA\t{note}", flush=True)
            continue
        latencies_sorted = sorted(latencies)
        p95_idx = max(0, int(round(0.95 * (len(latencies) - 1))))
        print(
            f"{cq_id}\t{desc}\t{rows}\t{len(latencies)}\t"
            f"{statistics.median(latencies):.4f}\t"
            f"{statistics.mean(latencies):.4f}\t"
            f"{latencies_sorted[p95_idx]:.4f}\t"
            f"{min(latencies):.4f}\t{max(latencies):.4f}\t{note}",
            flush=True,
        )


if __name__ == "__main__":
    main()
