#!/usr/bin/env python3
"""Verify the public protocol proxy's datasets, numeric output and read-only access."""
import argparse
from decimal import Decimal
import hashlib
import io
import json
from pathlib import Path
import re
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from rdflib import Graph, Literal, URIRef
from rdflib.compare import isomorphic
from rdflib.query import Result

FIXTURE_SHA256 = "1d7d1e512c6d40728ba8d0a3b0563711f2c262dbe4d469a9858de8b935426191"
GRAPH = "urn:eq:release-test:export"
GRAPH_FORMATS = dict(turtle=("text/turtle", "turtle"), ntriples=("application/n-triples", "nt"),
                     rdfxml=("application/rdf+xml", "xml"), jsonld=("application/ld+json", "json-ld"))


def complete_headers(headers):
    for name, value in headers.items():
        name = name.lower()
        if name in {"x-sql-message", "x-sparql-maxrows"} or (
                name == "x-sql-state" and value not in {"00000", "0"}):
            raise RuntimeError("Partial/error response: " + name + "=" + value)
        if any(word in name for word in ("truncated", "incomplete")) and value.lower() not in {"false", "0", "no"}:
            raise RuntimeError("Partial response: " + name + "=" + value)


def fetch(endpoint, query, extra=(), mime="application/sparql-results+json"):
    request = Request(endpoint, data=urlencode([
        ("query", query), ("format", mime), *extra
    ]).encode(), headers={"Accept": mime})
    try:
        with urlopen(request, timeout=30) as response:
            complete_headers(response.headers)
            return response.status, response.read().decode(), response.headers.get_content_type()
    except HTTPError as error:
        complete_headers(error.headers)
        return error.code, error.read().decode(), error.headers.get_content_type()


def select_rows(status, body, mime):
    if status != 200 or mime not in {"application/sparql-results+json", "application/json"}:
        raise RuntimeError("Successful JSON SELECT response required")
    payload = json.loads(body)
    if "error" in payload or "errors" in payload or not isinstance(payload.get("head", {}).get("vars"), list):
        raise RuntimeError("Malformed SELECT result")
    rows = payload.get("results", {}).get("bindings")
    if not isinstance(rows, list):
        raise RuntimeError("Missing SELECT bindings")
    return rows


def graph_roundtrip(body, fmt, source):
    actual = Graph().parse(data=body, format=GRAPH_FORMATS[fmt][1])
    if len(actual) != 6:
        raise RuntimeError("Graph response must preserve all six fixture statements")
    subject = URIRef("urn:eq:export:subject")
    expected_types = {"double": "http://www.w3.org/2001/XMLSchema#double",
                      "integer": "http://www.w3.org/2001/XMLSchema#integer",
                      "wkt": "http://www.opengis.net/ont/geosparql#wktLiteral"}
    for name, datatype in expected_types.items():
        value = actual.value(subject, URIRef("urn:eq:export:" + name))
        if not isinstance(value, Literal) or value.datatype != URIRef(datatype):
            raise RuntimeError("Graph serialization changed literal datatype: " + name)
    def normalized(graph):
        output = Graph()
        for s, p, o in graph:
            if isinstance(o, Literal) and o.datatype == URIRef(expected_types["wkt"]):
                o = Literal(re.sub(r"POINT\s*\(", "POINT(", str(o)), datatype=o.datatype)
            output.add((s, p, o))
        return output
    if not isomorphic(normalized(actual), normalized(source)):
        raise RuntimeError("Graph serialization changed source RDF terms")
    return dict(triples=6, graph_isomorphic=True, literal_datatypes_preserved=True)


def select_roundtrip(body, fmt, source):
    result = Result.parse(io.BytesIO(body.encode('utf-8')), format=fmt)
    if result.type != 'SELECT' or [str(var) for var in result.vars] != ['s', 'p', 'o']:
        raise RuntimeError('SELECT serialization changed projected variables')
    rows = list(result)
    if len(rows) != 6 or any(len(row.asdict()) != 3 for row in rows):
        raise RuntimeError('SELECT serialization changed complete six-row result')
    actual = Graph()
    for row in rows:
        actual.add(tuple(row))
    graph_roundtrip(actual.serialize(format='nt'), 'ntriples', source)
    return dict(rows=6, literal_datatypes_preserved=True, result_multiset_preserved=True)


def run_checks(endpoint, checks, source):
    graph = "urn:eq:release-test:export"
    subject = "<urn:eq:export:subject> <urn:eq:export:double> ?o"
    plans = [
        ("default_excludes_fixture_graph", f"SELECT ?o WHERE {{ {subject} }}", [], 0),
        ("explicit_from_overrides_default", f"SELECT ?o FROM <{graph}> WHERE {{ {subject} }}", [], 1),
        ("protocol_dataset_overrides_default", f"SELECT ?o WHERE {{ {subject} }}", [("default-graph-uri", graph)], 1),
        ("explicit_named_dataset", f"SELECT ?o FROM NAMED <{graph}> WHERE {{ GRAPH <{graph}> {{ {subject} }} }}", [], 1),
        ("empty_from_does_not_fall_back_to_asserted", "SELECT ?o FROM <urn:eq:release-test:absent-dataset> WHERE {?s ?p ?o} LIMIT 1", [], 0),
        ("empty_protocol_dataset_does_not_fall_back", "SELECT ?o WHERE {?s ?p ?o} LIMIT 1", [("default-graph-uri", "urn:eq:release-test:absent-dataset")], 0),
    ]
    for name, query, extra, expected in plans:
        status, body, mime = fetch(endpoint, query, extra)
        rows = select_rows(status, body, mime)
        passed = status == 200 and len(rows) == expected
        if passed and rows:
            value = rows[0]["o"]
            passed = (value.get("datatype") == "http://www.w3.org/2001/XMLSchema#double"
                      and abs(Decimal(value["value"]) - Decimal("0.03035258267")) < Decimal("1e-17"))
        checks.append({"name": name, "query": query, "http_status": status,
                       "rows": rows, "passed": passed, "complete_response": True})
    query = f"SELECT (DATATYPE(?o) AS ?datatype) FROM <{graph}> WHERE {{ <urn:eq:export:subject> <urn:eq:export:wkt> ?o }}"
    status, body, mime = fetch(endpoint, query)
    rows = select_rows(status, body, mime)
    checks.append({"name": "wkt_datatype", "http_status": status, "rows": rows,
                   "complete_response": True,
                   "passed": status == 200 and len(rows) == 1 and rows[0]["datatype"]["value"] == "http://www.opengis.net/ont/geosparql#wktLiteral"})
    # Valid empty update has no data effect even if the server is misconfigured.
    status, body, _ = fetch(endpoint, "INSERT DATA {}")
    read_only_proxy = (status == 400 and body == '{"detail":"Only SELECT, ASK, CONSTRUCT and DESCRIBE queries are supported"}')
    checks.append({"name": "anonymous_update_denied", "http_status": status,
                   "response": body, "passed": read_only_proxy or (status >= 400 and any(
                       word in body.lower() for word in ("access denied", "permission", "not authorized", "denied")))})
    for fmt, (mime, _) in GRAPH_FORMATS.items():
        query = "CONSTRUCT {?s ?p ?o} FROM <" + GRAPH + "> WHERE {?s ?p ?o}"
        status, body, content_type = fetch(endpoint, query, mime=mime)
        row = dict(name="construct_" + fmt + "_roundtrip", http_status=status, content_type=content_type,
                   complete_response=True, passed=False)
        checks.append(row)
        if status != 200 or content_type != mime:
            raise RuntimeError("Graph response format/status mismatch")
        row.update(graph_roundtrip(body, fmt, source), passed=True)
    for fmt, mime in [('json', 'application/sparql-results+json'), ('xml', 'application/sparql-results+xml')]:
        query = 'SELECT ?s ?p ?o FROM <' + GRAPH + '> WHERE {?s ?p ?o} ORDER BY ?p'
        status, body, content_type = fetch(endpoint, query, mime=mime)
        row = dict(name='select_' + fmt + '_literal_roundtrip', http_status=status,
                   content_type=content_type, complete_response=True, passed=False)
        checks.append(row)
        if status != 200 or content_type != mime:
            raise RuntimeError('SELECT response format/status mismatch')
        row.update(select_roundtrip(body, fmt, source), passed=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, default=Path(__file__).with_name("export_fixture.ttl"))
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    checks = []
    report = {"version": "3.0.0", "endpoint": args.endpoint, "passed": False, "checks": checks}
    try:
        digest = hashlib.sha256(args.fixture.read_bytes()).hexdigest()
        if digest != FIXTURE_SHA256:
            raise RuntimeError("Fixture source differs from frozen six-statement expectation")
        source = Graph().parse(args.fixture, format="turtle")
        if len(source) != 6:
            raise RuntimeError("Fixture source must have six statements")
        report["graph_fixture"] = dict(sha256=digest, triples=6, graph=GRAPH)
        run_checks(args.endpoint, checks, source)
        report["passed"] = len(checks) == 14 and all(c["passed"] for c in checks)
    except Exception as error:
        report["error"] = type(error).__name__ + ": " + str(error)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
