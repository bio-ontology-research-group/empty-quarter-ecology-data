#!/usr/bin/env python3
"""Read-only release gates against independently frozen source-result tuples.

Checks the exact printed SELECTs, including their ORDER BY and LIMIT clauses.
Numeric comparisons use Decimal, atol=rtol=1e-12; WKT coordinates use atol=1e-10.
No expected value is learned from the endpoint being tested.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, localcontext
import hashlib
import json
from pathlib import Path
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[3]
VERSION = "3.0.0"
GRAPHS = {mode: f"https://rubalkhali.science/graph/{mode}/{VERSION}"
          for mode in ("asserted", "materialized")}
ATOL = RTOL = Decimal("1e-12")
COORD_ATOL = Decimal("1e-10")


class GateError(RuntimeError):
    pass


@dataclass
class Case:
    name: str
    query: str
    columns: list[str]
    expected: list[dict[str, str]]
    numeric: tuple[str, ...] = ()
    coordinates: tuple[str, ...] = ()
    source: Path | None = None


def decimal(value):
    try:
        result = Decimal(value)
    except (InvalidOperation, TypeError, ValueError) as error:
        raise GateError(f"Invalid numeric value {value!r}") from error
    if not result.is_finite():
        raise GateError(f"Nonfinite numeric value {value!r}")
    return result


def coordinates(value):
    match = re.fullmatch(r"\s*POINT\s*\(\s*([^\s()]+)\s+([^\s()]+)\s*\)\s*", value, re.I)
    if not match:
        raise GateError(f"Expected two-dimensional POINT WKT, got {value!r}")
    return tuple(decimal(part) for part in match.groups())


def binding_rows(payload, columns, expected_terms=None):
    if not isinstance(payload, dict) or "error" in payload or "errors" in payload:
        raise GateError("SPARQL response is not a successful JSON object")
    if not isinstance(payload.get("head"), dict) or not isinstance(payload.get("results"), dict):
        raise GateError("Missing SELECT head/results objects")
    head = payload["head"].get("vars")
    if not isinstance(head, list) or len(head) != len(set(head)) or set(head) != set(columns):
        raise GateError(f"Unexpected SELECT columns: {head!r}; expected {columns!r}")
    bindings = payload.get("results", {}).get("bindings")
    if not isinstance(bindings, list):
        raise GateError("Missing SPARQL results.bindings array")
    rows = []
    for binding in bindings:
        if not isinstance(binding, dict) or set(binding) != set(columns):
            raise GateError(f"Unbound, missing or extra result fields: {binding!r}")
        row = {}
        for column in columns:
            term = binding[column]
            if (not isinstance(term, dict) or term.get("type") not in
                    {"uri", "bnode", "literal", "typed-literal"} or not isinstance(term.get("value"), str)):
                raise GateError(f"Malformed RDF term in {column}: {term!r}")
            if expected_terms is not None:
                expected_uri = expected_terms[column].startswith(("http://", "https://", "urn:"))
                allowed_types = {"uri"} if expected_uri else {"literal", "typed-literal"}
                if term["type"] not in allowed_types:
                    raise GateError(f"Wrong RDF term kind in {column}: {term['type']}")
            # JSON literal and typed-literal are serialization variants, not
            # different numbers. Preserve lexical values until Decimal parsing.
            row[column] = term["value"]
        rows.append(row)
    return rows


def compare_rows(case, actual):
    """Compare multisets, retaining multiplicity and matching numeric tuples."""
    if len(actual) != len(case.expected):
        raise GateError(f"{case.name}: {len(actual)} rows, expected exactly {len(case.expected)}")
    if not case.expected:
        raise GateError(f"{case.name}: empty source expectation is not an acceptance gate")
    categorical = [c for c in case.columns if c not in (*case.numeric, *case.coordinates)]

    def group(rows):
        grouped = defaultdict(list)
        for row in rows:
            if set(row) != set(case.columns):
                raise GateError(f"{case.name}: row columns differ from the frozen table")
            key = tuple(row[c] for c in categorical)
            values = [(decimal(row[c]), ATOL, RTOL) for c in case.numeric]
            for column in case.coordinates:
                values.extend((v, COORD_ATOL, Decimal(0)) for v in coordinates(row[column]))
            grouped[key].append(values)
        return grouped

    expected_groups, actual_groups = group(case.expected), group(actual)
    if set(expected_groups) != set(actual_groups):
        missing = sorted(set(expected_groups) - set(actual_groups))[:3]
        extra = sorted(set(actual_groups) - set(expected_groups))[:3]
        raise GateError(f"{case.name}: categorical tuples differ; missing={missing!r}; extra={extra!r}")

    def matches(expected, actual):
        with localcontext() as context:
            context.prec = 80
            return all(abs(a[0] - e[0]) <= e[1] + e[2] * abs(e[0])
                       for e, a in zip(expected, actual))

    for key, expected in expected_groups.items():
        actual_values = actual_groups[key]
        if len(expected) != len(actual_values):
            raise GateError(f"{case.name}: duplicate multiplicity differs for {key!r}")
        # A perfect bipartite matching avoids greedy matching errors when
        # several repeated categorical tuples fall within numeric tolerance.
        adjacency = [[j for j, a in enumerate(actual_values) if matches(e, a)] for e in expected]
        assigned = {}
        def augment(i, seen):
            for j in adjacency[i]:
                if j in seen:
                    continue
                seen.add(j)
                if j not in assigned or augment(assigned[j], seen):
                    assigned[j] = i
                    return True
            return False
        if not all(augment(i, set()) for i in range(len(expected))):
            raise GateError(f"{case.name}: numeric tuple mismatch for {key!r}; expected={expected[:3]!r}; actual={actual_values[:3]!r}")
    if case.name in {'taxonomy_ERR16061083_genus', 'taxonomy_api_ERR16061083_top20'}:
        keys = [taxonomy_order_key(row) for row in actual]
        if keys != sorted(keys):
            raise GateError(f'{case.name}: rows violate descending integer read-count ORDER BY')


def taxonomy_order_key(row):
    count = decimal(row['count'])
    if count != count.to_integral_value() or count < 0:
        raise GateError('Taxonomic read count must be a nonnegative integer')
    return row['runLabel'], -count, row['lineage'], row['proc']


def read_table(path, expected_count):
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        rows, columns = list(reader), reader.fieldnames
    if not columns or len(rows) != expected_count or any(None in row or None in row.values() for row in rows):
        raise GateError(f"Invalid frozen expectation table {path}; required rows={expected_count}")
    return columns, rows


def printed_queries(path):
    source = path.read_text()
    found = {}
    for match in re.finditer(r"\\begin\{lstlisting\}\[(.*?)\]\s*(.*?)\\end\{lstlisting\}", source, re.S):
        label = re.search(r"label=\{(lst:sparql_[^}]+)\}", match[1])
        if label:
            if label[1] in found:
                raise GateError(f"Duplicate printed query {label[1]}")
            found[label[1]] = match[2].strip()
    required = {"lst:sparql_xrf", "lst:sparql_taxon", "lst:sparql_env_tax"}
    if set(found) != required:
        raise GateError(f"Expected exactly the three printed SELECTs, found {sorted(found)}")
    return found


def scoped_query(query):
    # The frozen printed SELECTs have a top-level WHERE and no FROM clauses.
    # Preserve their projection, body, ORDER BY and LIMIT exactly.
    matches = list(re.finditer(r"(?m)^WHERE\s*\{", query))
    if len(matches) != 1:
        raise GateError("Cannot unambiguously scope the printed SELECT")
    position = matches[0].start()
    return query[:position] + f"FROM <{GRAPHS['asserted']}>\n" + query[position:]


def load_cases(root, expectations, paper):
    queries = printed_queries(paper / "05_validation.tex")
    archived = root / "evidence/competency-query/field_xrf_site10.rq"
    if queries["lst:sparql_xrf"].split() != archived.read_text().split():
        raise GateError("Printed XRF query differs from its frozen executable source")
    specs = [
        ("field_xrf_site10", "lst:sparql_xrf", root / "evidence/competency-query/field_xrf_site10_results.tsv", 46, ("concentration",)),
        ("taxonomy_ERR16061083_genus", "lst:sparql_taxon", expectations / "taxonomy_ERR16061083_genus.tsv", 48, ("count", "relativeAbundance")),
        ("environment_pseudomonas_gt35", "lst:sparql_env_tax", expectations / "environment_pseudomonas_gt35.tsv", 360, ("temp", "relAbundance")),
    ]
    cases = []
    for name, label, path, count, numeric in specs:
        columns, rows = read_table(path, count)
        cases.append(Case(name, queries[label], columns, rows, numeric=numeric, source=path))
    path = expectations / "sites70.tsv"
    columns, rows = read_table(path, 70)
    sites = """SELECT ?site ?siteLabel ?wkt
WHERE {
  ?site a <https://rubalkhali.science/kb/RAK_0000002> .
  OPTIONAL { ?site <http://www.w3.org/2000/01/rdf-schema#label> ?siteLabel . }
  OPTIONAL { ?site <http://www.opengis.net/ont/geosparql#asWKT> ?wkt . }
}
ORDER BY ?site"""
    cases.append(Case("sites70", sites, columns, rows, coordinates=("wkt",), source=path))
    path = expectations / "six_pcr_ntcs.json"
    controls = json.loads(path.read_text())
    columns = ["material", "identifier", "label", "role", "roleClass", "realizedIn"]
    if len(controls) != 6 or {r["identifier"] for r in controls} != {f"Negative{i}" for i in (1, 2, 4, 5, 6, 7)}:
        raise GateError("Expected exactly the six canonical PCR no-template controls")
    identifiers = " ".join(json.dumps(row["identifier"]) for row in controls)
    query = f"""SELECT ?material ?identifier ?label ?role ?roleClass ?realizedIn
WHERE {{
  VALUES ?identifier {{ {identifiers} }}
  ?material <http://purl.org/dc/terms/identifier> ?identifier .
  OPTIONAL {{ ?material <http://www.w3.org/2000/01/rdf-schema#label> ?label . }}
  OPTIONAL {{
    ?material <http://semanticscience.org/resource/SIO_000228> ?role .
    OPTIONAL {{ ?role a ?roleClass . }}
    OPTIONAL {{ ?role <http://semanticscience.org/resource/SIO_000356> ?realizedIn . }}
  }}
}}
ORDER BY ?identifier ?role ?roleClass"""
    rows = [{column: row[column] for column in columns} for row in controls]
    cases.append(Case("six_pcr_ntcs", query, columns, rows, source=path))
    return cases


def response_json(status, headers, body):
    if status != 200:
        raise GateError(f"HTTP {status}, expected 200")
    headers = {key.lower(): str(value) for key, value in headers.items()}
    for name, value in headers.items():
        if name in {"x-sparql-maxrows", "x-sql-message"} or (name == "x-sql-state" and value not in {"00000", "0"}):
            raise GateError(f"Partial/error query response header: {name}={value}")
        if any(word in name for word in ("truncated", "incomplete")) and value.lower() not in {"false", "0", "no"}:
            raise GateError(f"Partial response header: {name}={value}")
    if not any(mime in headers.get("content-type", "").lower() for mime in ("application/json", "application/sparql-results+json")):
        raise GateError("Response has no JSON content type")
    try:
        result = json.loads(body)
    except (ValueError, UnicodeDecodeError) as error:
        raise GateError("Invalid or truncated response JSON") from error
    if not isinstance(result, dict) or "error" in result or "errors" in result:
        raise GateError("Response JSON contains an error or is not an object")
    return result


def request_json(url, timeout, form=None, payload=None):
    headers = {"Accept": "application/sparql-results+json, application/json"}
    data = None
    if form is not None:
        data = urlencode(form).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    try:
        with urlopen(Request(url, data=data, headers=headers), timeout=timeout) as response:
            return response_json(response.status, dict(response.headers), response.read())
    except (HTTPError, URLError, TimeoutError, OSError) as error:
        raise GateError(f"Request failed for {url}: {type(error).__name__}: {error}") from error


def taxonomy_api_case(taxonomy_case):
    rows = sorted([row for row in taxonomy_case.expected if row["runLabel"] == "FASTQ dataset for ERR16061083"],
                  key=taxonomy_order_key)[:20]
    if len(rows) != 20:
        raise GateError("Frozen taxonomy table does not cover the first run's top twenty rows")
    return Case("taxonomy_api_ERR16061083_top20", "", taxonomy_case.columns, rows,
                numeric=taxonomy_case.numeric, source=taxonomy_case.source)


def taxonomy_api_rows(response):
    mapping = {"proc": "process", "fastq": "fastq", "runLabel": "run_label",
               "lineage": "lineage", "taxon": "taxon_iri", "taxonLabel": "taxon",
               "count": "count", "relativeAbundance": "relative_abundance"}
    data = response.get("data")
    if not isinstance(data, list):
        raise GateError("Taxonomy API has no data array")
    rows = []
    for row in data:
        if not isinstance(row, dict) or set(row) != set(mapping.values()):
            raise GateError("Taxonomy API fields differ from the lineage-resolved schema")
        if any(row[key] is None for key in mapping.values()):
            raise GateError("Taxonomy API has an unbound result field")
        rows.append({column: str(row[key]) for column, key in mapping.items()})
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True, help="Portal/API origin, without /api")
    parser.add_argument("--sparql-url", help="Direct endpoint, defaults to BASE/sparql")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--expectations", type=Path)
    parser.add_argument("--paper", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument("--asserted-only", action="store_true", help="Require an asserted-only release; no materialized mode")
    args = parser.parse_args(argv)
    base = args.base_url.rstrip("/")
    endpoint = args.sparql_url or base + "/sparql"
    expectations = args.expectations or args.root / "results/kg-release-3.0.0/query_expectations"
    paper = args.paper or args.root / "paper"
    args.output_dir.mkdir(parents=True, exist_ok=True)
    report = {"version": VERSION, "started": datetime.now(timezone.utc).isoformat(),
              "base_url": base, "sparql_url": endpoint, "timeout_seconds": args.timeout,
              "numeric_atol": str(ATOL), "numeric_rtol": str(RTOL),
              "coordinate_atol": str(COORD_ATOL), "checks": [], "status": "failed"}
    report["release_mode"] = "asserted-only" if args.asserted_only else "materialized"
    try:
        cases = load_cases(args.root, expectations, paper)
        metadata = request_json(base + "/kg-release.json", args.timeout)
        expected_graphs = {"asserted": GRAPHS["asserted"]} if args.asserted_only else GRAPHS
        if metadata.get("version") != VERSION or metadata.get("graphs") != expected_graphs:
            raise GateError("Portal metadata has the wrong release version or graph contract")
        stats = request_json(base + "/api/data/stats", args.timeout)
        if str(stats.get("version", "")).lstrip("v") != VERSION or stats.get("graph") != GRAPHS["asserted"]:
            raise GateError("API stats do not identify the expected asserted release")
        version_query = (f"SELECT ?version FROM <{GRAPHS['asserted']}> WHERE {{ "
            "<https://rubalkhali.science/kb/> <http://purl.org/pav/version> ?version . }")
        version_rows = binding_rows(request_json(endpoint, args.timeout,
            form=[("query", version_query), ("format", "application/sparql-results+json")]), ["version"])
        if len(version_rows) != 1 or version_rows[0]["version"].lstrip("v") != VERSION:
            raise GateError("Asserted graph does not contain singleton current release metadata")
        report["release_metadata"] = {"portal": metadata, "api": {k: stats[k] for k in ("version", "graph")},
                                      "graph": version_rows}
        for case in cases:
            variants = [
                ("direct_server_default", case.query, "direct", "asserted", False),
                ("direct_asserted", case.query, "direct", "asserted", True),
                ("api_asserted", case.query, "api", "asserted", False),
                ("direct_explicit_from", scoped_query(case.query), "direct", "asserted", False),
                ("api_explicit_from_asserted", scoped_query(case.query), "api", "asserted", False),
                ("api_explicit_from_materialized", scoped_query(case.query), "api", "materialized", False),
            ]
            if args.asserted_only:
                variants = [v for v in variants if v[3] == "asserted"]
            for variant, query, transport, mode, protocol_asserted in variants:
                started = time.monotonic()
                report["active_check"] = {"case": case.name, "variant": variant, "query": query}
                if transport == "direct":
                    form = [("query", query), ("format", "application/sparql-results+json")]
                    if protocol_asserted:
                        form.append(("default-graph-uri", GRAPHS["asserted"]))
                    result = request_json(endpoint, args.timeout, form=form)
                else:
                    response = request_json(base + "/api/query", args.timeout, payload={"query": query, "mode": mode})
                    if response.get("kg_version") != VERSION or response.get("mode") != mode:
                        raise GateError(f"{case.name}/{variant}: API mode/version contract differs")
                    result = response.get("data")
                raw_path = args.output_dir / f"{case.name}__{variant}.json"
                raw_path.write_text(json.dumps(result, indent=2) + "\n")
                rows = binding_rows(result, case.columns, case.expected[0])
                compare_rows(case, rows)
                check = {"case": case.name, "variant": variant, "rows": len(rows),
                         "expected_rows": len(case.expected), "status": "passed",
                         "query": query, "query_sha256": hashlib.sha256(query.encode()).hexdigest(),
                         "expected_file": str(case.source),
                         "expected_sha256": hashlib.sha256(case.source.read_bytes()).hexdigest(),
                         "response_file": raw_path.name, "elapsed_seconds": time.monotonic() - started}
                report["checks"].append(check)
                if case.name == 'taxonomy_ERR16061083_genus':
                    check['numeric_order_checked'] = True
                print(f"PASS {case.name}/{variant}: {len(rows)} exact multiset rows", flush=True)
        case = taxonomy_api_case(next(case for case in cases if case.name == "taxonomy_ERR16061083_genus"))
        report["active_check"] = {"case": case.name, "variant": "api_rank_genus_limit20"}
        url = base + "/api/data/taxonomy?" + urlencode({"run_label": "ERR16061083", "rank": "Genus", "limit": 20})
        response = request_json(url, args.timeout)
        (args.output_dir / "taxonomy_api_ERR16061083_top20.json").write_text(json.dumps(response, indent=2) + "\n")
        rows = taxonomy_api_rows(response)
        compare_rows(case, rows)
        report["checks"].append({"case": case.name, "variant": "api_rank_genus_limit20", "rows": len(rows),
            "expected_rows": 20, "status": "passed", "request_url": url,
            "expected_file": str(case.source), "expected_sha256": hashlib.sha256(case.source.read_bytes()).hexdigest(),
            "source_projection": "Top20 integer read counts for runLabel=FASTQ dataset for ERR16061083; lineage/process tie-breakers",
            "numeric_order_checked": True,
            "response_file": "taxonomy_api_ERR16061083_top20.json"})
        print("PASS taxonomy_api_ERR16061083_top20: 20 exact multiset rows", flush=True)
        report["status"] = "passed"
        report.pop("active_check", None)
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
        print(report["error"], flush=True)
    finally:
        report["finished"] = datetime.now(timezone.utc).isoformat()
        (args.output_dir / "query_gates.json").write_text(json.dumps(report, indent=2) + "\n")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
