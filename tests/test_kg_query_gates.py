"""Independent tuple-comparison and fail-closed release-gate regressions."""
import importlib.util
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("kg_query_gates", ROOT / "scripts/release/kg/query_gates.py")
gates = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = gates
SPEC.loader.exec_module(gates)


def payload(rows, columns=None, literal_type="literal"):
    columns = columns or list(rows[0])
    return {"head": {"vars": columns}, "results": {"bindings": [
        {key: {"type": "uri" if value.startswith("http") else literal_type, "value": value}
         for key, value in row.items()} for row in rows]}}


def simple():
    return gates.Case("fixture", "SELECT ?id ?value WHERE {}", ["id", "value"],
                      [{"id": "a", "value": "1.23456789012345"}], numeric=("value",))


@pytest.mark.parametrize("kind", ["literal", "typed-literal"])
def test_numeric_literal_serializations_equivalent(kind):
    case = simple()
    rows = gates.binding_rows(payload(case.expected, literal_type=kind), case.columns)
    gates.compare_rows(case, rows)


def test_uri_cannot_be_replaced_by_same_text_literal():
    expected = {"site": "https://example.org/site"}
    data = payload([expected])
    data['results']['bindings'][0]['site']['type'] = 'literal'
    with pytest.raises(gates.GateError, match="Wrong RDF term kind"):
        gates.binding_rows(data, ['site'], expected)


def test_decimal_full_precision_and_tolerance():
    case = simple()
    gates.compare_rows(case, [{"id": "a", "value": "1.23456789012346"}])
    with pytest.raises(gates.GateError, match="numeric tuple mismatch"):
        gates.compare_rows(case, [{"id": "a", "value": "1.23457"}])


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity", "not numeric"])
def test_nonfinite_and_invalid_numeric_fail(value):
    with pytest.raises(gates.GateError):
        gates.compare_rows(simple(), [{"id": "a", "value": value}])


def test_extra_row_never_collapses_to_a_set():
    case = simple()
    with pytest.raises(gates.GateError, match="exactly 1"):
        gates.compare_rows(case, case.expected * 2)


def test_equal_cardinality_wrong_duplicate_multiplicity_fails():
    case = simple()
    case.expected.append({"id": "b", "value": "1.23456789012345"})
    with pytest.raises(gates.GateError):
        gates.compare_rows(case, [case.expected[0], case.expected[0]])


def test_matching_retains_numeric_multiset_not_just_categories():
    case = simple()
    case.expected.append({"id": "a", "value": "2"})
    gates.compare_rows(case, list(reversed(case.expected)))
    with pytest.raises(gates.GateError, match="numeric tuple mismatch"):
        gates.compare_rows(case, [case.expected[0], case.expected[0]])


def test_taxonomy_order_rejects_same_multiset_in_lexical_count_order():
    rows = [{'runLabel': 'FASTQ dataset for ERR16061083', 'count': str(count),
             'lineage': 'lineage', 'proc': 'urn:process'} for count in [509, 68, 8]]
    case = gates.Case('taxonomy_ERR16061083_genus', '', list(rows[0]), rows, numeric=('count',))
    gates.compare_rows(case, rows)
    with pytest.raises(gates.GateError, match='integer read-count ORDER BY'):
        gates.compare_rows(case, list(reversed(rows)))


def test_taxonomy_api_limit_selects_numeric_top20_not_first_source_rows():
    rows = [{'runLabel': 'FASTQ dataset for ERR16061083', 'count': str(count),
             'lineage': 'lineage', 'proc': 'urn:process'} for count in range(1, 49)]
    case = gates.Case('taxonomy_ERR16061083_genus', '', list(rows[0]), rows, numeric=('count',))
    selected = gates.taxonomy_api_case(case)
    assert [int(row['count']) for row in selected.expected] == list(range(48, 28, -1))


@pytest.mark.parametrize('count', ['0.5', '-1', 'NaN'])
def test_taxonomy_order_requires_nonnegative_integral_counts(count):
    with pytest.raises(gates.GateError):
        gates.taxonomy_order_key(dict(runLabel='run', count=count, lineage='lineage', proc='urn:proc'))


def test_perfect_matching_avoids_greedy_tolerance_failure():
    case = simple()
    case.expected = [{"id": "a", "value": "0"}, {"id": "a", "value": "-1e-12"}]
    gates.compare_rows(case, [{"id": "a", "value": "-0.5e-12"}, {"id": "a", "value": "0.5e-12"}])


def test_coordinate_precision_and_axis_swap():
    case = gates.Case("sites", "", ["site", "wkt"],
        [{"site": "s", "wkt": "POINT(45.166511388888885 19.149770555555556)"}], coordinates=("wkt",))
    gates.compare_rows(case, [{"site": "s", "wkt": "POINT (45.16651138888889 19.14977055555556)"}])
    for wkt in ("POINT(19.149770555555556 45.166511388888885)", "POINT(45.1665 19.1498)"):
        with pytest.raises(gates.GateError):
            gates.compare_rows(case, [{"site": "s", "wkt": wkt}])


def test_wrong_control_role_fails():
    case = gates.Case("controls", "", ["material", "roleClass"],
        [{"material": "urn:material", "roleClass": "urn:PCR"}])
    with pytest.raises(gates.GateError, match="categorical tuples differ"):
        gates.compare_rows(case, [{"material": "urn:material", "roleClass": "urn:extraction"}])


@pytest.mark.parametrize("headers", [
    {"X-SQL-State": "S1TAT"}, {"X-SPARQL-MaxRows": "100"},
    {"X-SQL-Message": "Query timeout"}, {"X-Result-Truncated": "true"},
])
def test_partial_response_headers_fail(headers):
    with pytest.raises(gates.GateError, match="Partial"):
        gates.response_json(200, {"Content-Type": "application/json", **headers}, b'{}')


@pytest.mark.parametrize("status, content_type, body", [
    (504, "application/json", b'{}'), (200, "text/html", b'{}'),
    (200, "application/json", b'{"head":'), (200, "application/json", b'{"error":"timeout"}'),
])
def test_http_and_json_errors_fail(status, content_type, body):
    with pytest.raises(gates.GateError):
        gates.response_json(status, {"Content-Type": content_type}, body)


def test_missing_bound_fields_and_wrong_headers_fail():
    case = simple()
    for data in (payload([{"id": "a"}], columns=case.columns),
                 payload(case.expected, columns=["id"]), {"head": [], "results": {}}):
        with pytest.raises(gates.GateError):
            gates.binding_rows(data, case.columns)


def test_frozen_cases_and_query_limits():
    cases = gates.load_cases(ROOT, ROOT / "results/kg-release-3.0.0/query_expectations", ROOT / "paper")
    assert [len(case.expected) for case in cases] == [46, 48, 360, 70, 6]
    taxon = cases[1].query
    assert taxon.endswith("ORDER BY ?runLabel DESC(xsd:double(?count)) ?lineage ?proc")
    assert 'VALUES ?runLabel { "FASTQ dataset for ERR16061083" }' in taxon
    assert "LIMIT" not in taxon and "DISTINCT" not in taxon
    assert {row["runLabel"] for row in cases[1].expected} == {"FASTQ dataset for ERR16061083"}
    assert gates.scoped_query(taxon).endswith(taxon[taxon.index("WHERE {"):])
    assert gates.scoped_query(taxon).count(f"FROM <{gates.GRAPHS['asserted']}>") == 1
    archived = (ROOT / 'scripts/release/kg/taxonomy_all_runs.rq').read_text()
    assert 'ORDER BY ?runLabel DESC(xsd:double(?count)) ?lineage ?proc' in archived
    assert 'VALUES ?runLabel' not in archived and '\nLIMIT ' not in archived


def test_driver_all_transports_and_fail_closed_version(monkeypatch, tmp_path):
    cases = gates.load_cases(ROOT, ROOT / "results/kg-release-3.0.0/query_expectations", ROOT / "paper")
    by_query = {query: case for case in cases for query in (case.query, gates.scoped_query(case.query))}
    observed = []
    def mock_request(url, timeout, form=None, payload=None):
        observed.append((url, form, payload))
        assert timeout == 300
        if url.endswith('/kg-release.json'):
            return {"version": gates.VERSION, "graphs": gates.GRAPHS}
        if url.endswith('/api/data/stats'):
            return {"version": gates.VERSION, "graph": gates.GRAPHS['asserted']}
        if '/api/data/taxonomy?' in url:
            case = gates.taxonomy_api_case(cases[1])
            return {"data": [{"process": row['proc'], "fastq": row['fastq'], "run_label": row['runLabel'],
                "lineage": row['lineage'], "taxon_iri": row['taxon'], "taxon": row['taxonLabel'],
                "count": int(float(row['count'])), "relative_abundance": float(row['relativeAbundance'])}
                for row in case.expected]}
        query = dict(form)['query'] if form else payload['query']
        if query.startswith('SELECT ?version FROM'):
            return globals()['payload']([{"version": gates.VERSION}])
        case = by_query[query]
        result = globals()['payload'](case.expected)
        if form is not None:
            return result
        return {"kg_version": gates.VERSION, "mode": payload['mode'], "data": result}
    monkeypatch.setattr(gates, 'request_json', mock_request)
    assert gates.main(['--base-url', 'http://fixture', '--output-dir', str(tmp_path)]) == 0
    report = json.loads((tmp_path / 'query_gates.json').read_text())
    assert len(report['checks']) == 31
    ordered = [check for check in report['checks'] if check['case'] in {
        'taxonomy_ERR16061083_genus', 'taxonomy_api_ERR16061083_top20'}]
    assert len(ordered) == 7
    assert all(check.get('numeric_order_checked') is True for check in ordered)
    assert len([x for x in report['checks'] if x['variant'] == 'direct_server_default']) == 5
    assert len([x for x in report['checks'] if x['variant'] == 'api_explicit_from_materialized']) == 5
    monkeypatch.setattr(gates, 'request_json', lambda *args, **kwargs: {"version": "2.0.6", "graphs": gates.GRAPHS})
    assert gates.main(['--base-url', 'http://fixture', '--output-dir', str(tmp_path / 'wrong')]) == 1
    assert json.loads((tmp_path / 'wrong/query_gates.json').read_text())['status'] == 'failed'
