#!/usr/bin/env python3
"""Fail-closed, reversible activation of the separately validated asserted KG.

This does not certify entailment or post-cutover public acceptance. The older
materialized-release cutover contract remains unchanged. Run with the pinned
Python 3.11 runtime (Path.is_relative_to is required).
"""
import argparse
import json
from pathlib import Path
import re
from urllib.parse import urlencode
from urllib.request import urlopen

from cutover import (BASELINE_SHA256, CONFIG, OLD_WEB_ID, CASE_ROWS,
                     PROTOCOL_CHECKS, GRAPH_FORMAT_CHECKS, SELECT_LITERAL_CHECKS,
                     GRAPH_FIXTURE_SHA256, run, sha, write_config)
from verify_downloads import auxiliary_entries, check_manifest_entries

ROOT = Path('/data/empty-quarter-releases/kg-3.0.0-asserted-20260912')
BASE_URL = 'http://127.0.0.1:18901'
CANDIDATE = 'eq_kg_3_0_0_asserted_web'
ALIAS = 'eqkg300assertedweb'
GRAPH = 'https://rubalkhali.science/graph/asserted/3.0.0'
COUNT = 45706977
PH_SHA256 = '4c3af7c30633822e7ce86cedd54247dbaba69a598cc9014cbc2c0cfab8a14811'
REPORTS = {'query': 'query/query_gates.json', 'protocol': 'protocol.json',
           'isolation': 'isolation.json', 'browser': 'browser/browser_gates.json',
           'downloads': 'downloads/report.json'}
ISOLATION_CHECKS = {'only_asserted_advertised', 'materialized_mode_rejected',
                    'inferred_graph_absent', 'materialized_graph_absent',
                    'asserted_default_count', 'all_712_ph_specimen_links_exact'}
BROWSER_ROWS = {'asserted': 46, 'clicked_light_elements': 71,
                'All sampling sites and their GPS coordinates': 70,
                'Genus-level composition and abundance for ERR16061083': 48,
                'Pseudomonas abundance at hot sites (cross-domain join)': 360,
                'Biomes associated with each site': None,
                'DNA extraction records and concentrations': None,
                'Provenance: soil sample → DNA → library → sequencing run': None,
                'Sequencing QC metrics for a specific sample': None}
FILE_NAMES = {f'rubalkhali-kg-3.0.0-{suffix}' for suffix in
              ('source.tar.gz', 'modules.tar.gz', 'asserted.nq.gz')}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def valid_sha(value):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) is not None


def unique_rows(rows, key, expected, label):
    require(isinstance(rows, list) and len(rows) == len(expected)
            and {row.get(key) for row in rows} == set(expected),
            'Incomplete or duplicate ' + label)
    return {row[key]: row for row in rows}


def check_protocol(protocol):
    expected = PROTOCOL_CHECKS | set(GRAPH_FORMAT_CHECKS) | set(SELECT_LITERAL_CHECKS)
    checks = unique_rows(protocol.get('checks'), 'name', expected, 'protocol checks')
    require(protocol.get('version') == '3.0.0' and protocol.get('passed') is True,
            'Passing versioned protocol report required')
    require(protocol.get('graph_fixture') == {
        'sha256': GRAPH_FIXTURE_SHA256, 'triples': 6, 'graph': 'urn:eq:release-test:export'},
        'Exact source RDF protocol fixture required')
    for name, row in checks.items():
        require(row.get('passed') is True, 'Failed protocol gate: ' + name)
        if name == 'anonymous_update_denied':
            require(type(row.get('http_status')) is int and row['http_status'] >= 400,
                    'Anonymous update must be denied')
            continue
        require(row.get('http_status') == 200 and row.get('complete_response') is True,
                'Incomplete protocol response: ' + name)
        if name in GRAPH_FORMAT_CHECKS:
            require(row.get('triples') == 6 and row.get('content_type') == GRAPH_FORMAT_CHECKS[name]
                    and row.get('graph_isomorphic') is True
                    and row.get('literal_datatypes_preserved') is True,
                    'RDF graph format did not preserve source terms: ' + name)
        if name in SELECT_LITERAL_CHECKS:
            require(row.get('rows') == 6 and row.get('content_type') == SELECT_LITERAL_CHECKS[name]
                    and row.get('result_multiset_preserved') is True
                    and row.get('literal_datatypes_preserved') is True,
                    'SELECT format did not preserve source terms: ' + name)


def check_gates(reports, manifest_bytes, auxiliary_bytes, private_loader_bytes):
    """Validate the actual report and proof bytes without touching production."""
    release = json.loads(manifest_bytes)
    require(release.get('version') == '3.0.0' and release.get('release_mode') == 'asserted-only'
            and release.get('graphs') == {'asserted': GRAPH}
            and release.get('counts') == {'asserted': COUNT}
            and release.get('available_modes') == ['asserted']
            and release.get('default_graph') == GRAPH
            and release.get('query_time_inference') is False,
            'Exact asserted-only manifest contract required')
    require(set(reports) == set(REPORTS), 'All five acceptance reports required')
    for name, report in reports.items():
        target = report.get('endpoint') if name == 'protocol' else report.get('base_url')
        require(target == BASE_URL + '/sparql' if name == 'protocol' else target == BASE_URL,
                'Evidence targets a different candidate: ' + name)
    query = reports['query']
    require(query.get('version') == '3.0.0' and query.get('release_mode') == 'asserted-only'
            and query.get('status') == 'passed', 'Failed asserted query report')
    cases = set(CASE_ROWS) - {'taxonomy_api_ERR16061083_top20'}
    variants = ('direct_server_default', 'direct_asserted', 'api_asserted',
                'direct_explicit_from', 'api_explicit_from_asserted')
    expected = {(case, variant) for case in cases for variant in variants}
    expected.add(('taxonomy_api_ERR16061083_top20', 'api_rank_genus_limit20'))
    checks = query.get('checks', [])
    require(len(checks) == 26 and {(r.get('case'), r.get('variant')) for r in checks} == expected,
            'All 26 unique exact query-result gates required')
    for row in checks:
        require(row.get('status') == 'passed' and row.get('rows') == CASE_ROWS[row['case']]
                and row.get('expected_rows') == CASE_ROWS[row['case']], 'Query result differs from source')
        require(valid_sha(row.get('expected_sha256')), 'Source expectation hash required')
        if row['case'] in ('taxonomy_ERR16061083_genus', 'taxonomy_api_ERR16061083_top20'):
            require(row.get('numeric_order_checked') is True, 'Numeric taxonomy ordering required')
    check_protocol(reports['protocol'])
    isolation = reports['isolation']
    isolation_checks = unique_rows(isolation.get('checks'), 'name', ISOLATION_CHECKS, 'isolation gates')
    require(isolation.get('version') == '3.0.0' and isolation.get('release_mode') == 'asserted-only'
            and isolation.get('passed') is True and isolation.get('asserted_triples') == COUNT
            and isolation.get('ph_source_sha256') == PH_SHA256
            and all(row.get('passed') is True for row in isolation_checks.values()),
            'Complete source-backed asserted isolation gates required')

    check_manifest_entries(release)
    entries = unique_rows(release.get('files'), 'name', FILE_NAMES, 'release artifacts')
    download = reports['downloads']
    require(download.get('version') == '3.0.0' and download.get('passed') is True
            and download.get('manifest_sha256') == sha(manifest_bytes),
            'Downloads must bind this exact manifest')
    actual = unique_rows(download.get('files'), 'name', FILE_NAMES, 'full downloads')
    for name, entry in entries.items():
        row = actual[name]
        require(type(entry.get('bytes')) is int and entry['bytes'] > 0 and valid_sha(entry.get('sha256'))
                and row.get('passed') is True and row.get('url') == BASE_URL + entry['url']
                and all(row.get(key) == entry[key] for key in ('bytes', 'sha256')),
                'Incomplete or mismatched artifact download: ' + name)
        if name.endswith('.nq.gz'):
            require(entry.get('graph') == GRAPH and entry.get('triples') == COUNT
                    and valid_sha(entry.get('uncompressed_sha256'))
                    and row.get('rdf_syntax_checked') is True
                    and row.get('graph') == GRAPH and row.get('triples') == COUNT,
                    'Full asserted RDF parse and count required')
    auxiliary = auxiliary_entries(release)
    require(set(auxiliary_bytes) == {row['name'] for row in auxiliary}, 'All six actual proof files required')
    downloaded = unique_rows(download.get('auxiliary_files'), 'name', auxiliary_bytes, 'proof downloads')
    for entry in auxiliary:
        row, content = downloaded[entry['name']], auxiliary_bytes[entry['name']]
        require(sha(content) == entry['sha256'] and len(content) == entry['bytes']
                and row.get('passed') is True and row.get('full_read') is True and row.get('http_status') == 200
                and all(row.get(key) == entry[key] for key in ('url', 'bytes', 'sha256')),
                'Fresh import proof bytes differ: ' + entry['name'])
    modules_bytes = auxiliary_bytes['input-modules-manifest.json']
    modules = json.loads(modules_bytes)
    records = modules.get('records', [])
    require(modules.get('version') == '3.0.0' and modules.get('module_count') == 16
            and len(records) == 16 and len({row.get('file') for row in records}) == 16
            and all(row.get('load_graph') == GRAPH and valid_sha(row.get('sha256')) for row in records),
            'Exactly sixteen distinct current asserted source modules required')
    by_name = {row['file']: row for row in records}
    require(by_name.get('rubalkhali_ph_eq_ph_shared_v1_0_1.ttl', {}).get('sha256') == PH_SHA256
            and 'rubalkhali_ph_eq_ph_shared_v1_0_0.ttl' not in by_name, 'Only confirmed pH successor allowed')
    loader = json.loads(auxiliary_bytes['asserted-loader-report.json'])
    private_loader = json.loads(private_loader_bytes)
    for item in (loader, private_loader):
        require(item.get('passed') is True and item.get('version') == '3.0.0'
                and item.get('module_count') == 16 and item.get('graph') == GRAPH
                and item.get('triples') == COUNT and item.get('input_manifest_sha256') == sha(modules_bytes),
                'Fresh loader must bind all sixteen modules and exact asserted count')
    evidence = release.get('evidence', {})
    require(evidence.get('input_manifest_sha256') == sha(modules_bytes)
            and evidence.get('private_loader_report_sha256') == sha(private_loader_bytes)
            and evidence.get('source_rebuild_report_sha256') == sha(auxiliary_bytes['source-rebuild-verification.json'])
            and evidence.get('native_export_fixture_sha256') == sha(auxiliary_bytes['native-export-fixture.json']),
            'Manifest must bind actual loader, source, rebuild and export fixture bytes')
    adaptations = json.loads(auxiliary_bytes['site-import-adaptations.json'])
    require(len(adaptations) == 1 and adaptations[0].get('typed_point_whitespace_changes') == 70
            and adaptations[0].get('coordinate_digits_changed') is False
            and adaptations[0].get('original_source_preserved') is True
            and adaptations[0].get('source_sha256') == by_name.get('rubalkhali_sites.owl', {}).get('sha256'),
            'Fresh source-preserving seventy-point WKT adaptation required')
    rebuild = json.loads(auxiliary_bytes['source-rebuild-verification.json'])
    rebuilt = unique_rows(rebuild.get('checks'), 'file', by_name, 'source replay modules')
    require(rebuild.get('passed') is True and rebuild.get('mode') == '--all'
            and all(row.get('passed') is True
                    and row.get('sha256') == row.get('expected_sha256') == by_name[name]['sha256']
                    for name, row in rebuilt.items()), 'Full current source replay required')
    fixture = json.loads(auxiliary_bytes['native-export-fixture.json'])
    require(fixture.get('passed') is True and fixture.get('triples') == 6
            and all(fixture.get(key) is True for key in ('binary64_preserved',
                'blank_nodes_unicode_language_preserved', 'wkt_datatype_preserved')),
            'Native export must preserve source RDF terms')
    browser = reports['browser']
    require(browser.get('status') == 'passed' and browser.get('release_mode') == 'asserted-only',
            'Passing asserted-only browser report required')
    browser_checks = browser.get('checks', [])
    require(len({row.get('name') for row in browser_checks}) == len(browser_checks)
            and all(row.get('status') == 'passed' for row in browser_checks),
            'Duplicate or failed browser checks')
    lookup = {row['name']: row for row in browser_checks}
    require(set(BROWSER_ROWS) <= set(lookup), 'All nine browser examples required')
    for name, count in BROWSER_ROWS.items():
        row = lookup[name]
        require(type(row.get('rows')) is int and (row['rows'] == count if count is not None else row['rows'] > 0),
                'Browser source-result cardinality differs: ' + name)
    require(lookup['Genus-level composition and abundance for ERR16061083'].get('numeric_order_checked') is True,
            'Browser taxonomy numeric ordering required')
    require('unscoped_materialized_inference_witness' not in lookup,
            'Materialized browser evidence cannot certify asserted-only release')
    links = unique_rows(browser.get('downloads'), 'name', FILE_NAMES, 'browser download ranges')
    require(all(row.get('bounded_range_status') == 206 and row.get('bytes') == entries[name]['bytes']
                for name, row in links.items()), 'All three browser download links must serve ranges')
    return release


def load_bundle(gates_dir):
    gates_dir = gates_dir.resolve()
    require(gates_dir.is_relative_to(ROOT / 'evidence'), 'Release-local acceptance directory required')
    content, paths = {}, {}
    for name, relative in REPORTS.items():
        path = (gates_dir / relative).resolve()
        require(path.is_relative_to(gates_dir), 'Report escapes acceptance directory')
        content[name], paths[name] = path.read_bytes(), str(path)
    publication = ROOT / 'publication/kg/3.0.0'
    manifest = (publication / 'manifest.json').read_bytes()
    auxiliary = {row['name']: (publication / row['name']).read_bytes()
                 for row in auxiliary_entries(json.loads(manifest))}
    loader = (ROOT / 'evidence/asserted_load/report.json').read_bytes()
    release = check_gates({name: json.loads(raw) for name, raw in content.items()}, manifest, auxiliary, loader)
    require((ROOT / 'inputs/scientific/manifest.json').read_bytes() == auxiliary['input-modules-manifest.json'],
            'Published input inventory differs from loaded scientific source')
    return release, manifest, {'manifest_sha256': sha(manifest),
        'private_loader_report_sha256': sha(loader),
        'auxiliary_sha256': {name: sha(raw) for name, raw in auxiliary.items()},
        'gates': {name: {'path': paths[name], 'sha256': sha(raw), 'manifest_sha256': sha(manifest)}
                  for name, raw in content.items()}}


def verify_live_counts():
    actual = {}
    for mode in ('asserted', 'inferred', 'materialized'):
        graph = f'https://rubalkhali.science/graph/{mode}/3.0.0'
        query = f'SELECT (COUNT(?s) AS ?n) FROM NAMED <{graph}> WHERE {{GRAPH <{graph}> {{?s ?p ?o}}}}'
        data = urlencode({'query': query, 'format': 'application/sparql-results+json'}).encode()
        with urlopen(BASE_URL + '/sparql', data=data, timeout=300) as response:
            require(response.status == 200 and not any(response.headers.get(name)
                    for name in ('X-SQL-State', 'X-SQL-Message', 'X-SPARQL-MaxRows')),
                    'Live candidate count failed or returned partial data')
            rows = json.load(response)['results']['bindings']
        require(len(rows) == 1, 'Invalid live count result shape')
        actual[mode] = int(rows[0]['n']['value'])
    require(actual == {'asserted': COUNT, 'inferred': 0, 'materialized': 0},
            'Live candidate graph contents changed after acceptance')
    return actual


def proposed_config():
    template = (Path(__file__).parent / 'nginx.cutover.conf').read_bytes()
    require(template.count(b'http://eqkg300web:80') == 1, 'Unexpected reviewed nginx template')
    return template.replace(b'http://eqkg300web:80', ('http://' + ALIAS + ':80').encode())


def reload_nginx():
    run('docker', 'exec', 'viz_web_1', 'nginx', '-t')
    run('docker', 'exec', 'viz_web_1', 'nginx', '-s', 'reload')


def write_record(path, record):
    path.write_text(json.dumps(record, indent=2) + '\n')


def write_candidate_validation(record):
    """Publish only whitelisted facts; never rewrite this pre-cutover record."""
    validation = {
        'version': '3.0.0', 'release_mode': 'asserted-only',
        'scope': 'Candidate-only acceptance before production cutover; no public deployment acceptance is claimed.',
        'candidate_acceptance_passed': True, 'public_acceptance_passed': False,
        'manifest_sha256': record['manifest_sha256'],
        'check_counts': {'queries': 26, 'protocol': 14, 'isolation': 6,
                         'browser_examples': 9, 'browser_download_ranges': 3,
                         'full_downloads': 3, 'fresh_import_proof_downloads': 6},
        'gates': {name: {'passed': True, 'report_sha256': record['gates'][name]['sha256']}
                  for name in REPORTS},
        'live_graph_counts': record['live_counts_before_activation'],
        'post_deployment_evidence': 'Any later public acceptance is recorded separately in post-deployment-validation.json.',
    }
    path = ROOT / 'publication/kg/3.0.0/validation.json'
    with path.open('x') as stream:
        json.dump(validation, stream, indent=2)
        stream.write('\n')


def activate(gates_dir):
    _, manifest, record = load_bundle(gates_dir)
    record['live_counts_before_activation'] = verify_live_counts()
    with urlopen(BASE_URL + '/downloads/kg/3.0.0/manifest.json', timeout=30) as response:
        require(response.status == 200 and response.read() == manifest, 'Candidate HTTP manifest differs')
    require(run('docker', 'inspect', 'viz_web_1', '--format', '{{.Id}}').strip() == OLD_WEB_ID,
            'Production web container changed; re-audit required')
    original, proposed = CONFIG.read_bytes(), proposed_config()
    require(sha(original) == BASELINE_SHA256, 'Production configuration changed; re-audit required')
    candidate = json.loads(run('docker', 'inspect', CANDIDATE))[0]
    require(candidate['State']['Running'] is True
            and ALIAS in candidate['NetworkSettings']['Networks']['viz_default']['Aliases'],
            'Asserted candidate unavailable on production network')
    evidence = ROOT / 'evidence/asserted_cutover'
    evidence.mkdir(exist_ok=False)
    (evidence / 'nginx.before.conf').write_bytes(original)
    (evidence / 'nginx.activated.conf').write_bytes(proposed)
    record.update(status='prepared; public acceptance not performed', version='3.0.0',
                  release_mode='asserted-only', candidate_id=candidate['Id'], candidate_image=candidate['Image'],
                  baseline_sha256=sha(original), activated_sha256=sha(proposed),
                  public_acceptance_passed=False)
    path = evidence / 'activation.json'
    write_record(path, record)
    write_candidate_validation(record)
    try:
        write_config(proposed)
        reload_nginx()
        record['status'] = 'activated; public acceptance gates pending'
    except Exception:
        record['status'] = 'activation failed; automatic rollback pending'
        try:
            write_config(original)
            reload_nginx()
            record['status'] = 'automatically rolled back after activation error'
        except Exception as recovery:
            record['status'] = 'activation and automatic rollback failed; operator recovery required'
            record['rollback_error'] = str(recovery)
        raise
    finally:
        write_record(path, record)
    return record


def rollback():
    require(run('docker', 'inspect', 'viz_web_1', '--format', '{{.Id}}').strip() == OLD_WEB_ID,
            'Production web container changed; re-audit required')
    evidence = ROOT / 'evidence/asserted_cutover'
    original, activated = ((evidence / name).read_bytes() for name in ('nginx.before.conf', 'nginx.activated.conf'))
    record = json.loads((evidence / 'activation.json').read_bytes())
    require(sha(original) == BASELINE_SHA256 and CONFIG.read_bytes() == activated
            and sha(activated) == record['activated_sha256'], 'Rollback baseline/current configuration mismatch')
    write_config(original)
    reload_nginx()
    result = {'status': 'restored', 'sha256': sha(original)}
    write_record(evidence / 'rollback.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['activate', 'rollback'])
    parser.add_argument('--gates-dir', type=Path, default=ROOT / 'evidence/candidate')
    args = parser.parse_args()
    print(json.dumps(activate(args.gates_dir) if args.operation == 'activate' else rollback(), indent=2))


if __name__ == '__main__':
    main()
