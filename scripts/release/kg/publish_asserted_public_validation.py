#!/usr/bin/env python3
"""Publish immutable public acceptance evidence only after all five suites pass.

Uses the asserted cutover's unchanged substantive validation contracts in an
isolated module instance pinned to https://rubalkhali.science. It cannot activate
or deploy a service, and never rewrites the candidate-only validation record.
Run with the pinned Python 3.11 runtime.
"""
import argparse
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import re
from urllib.request import urlopen

import asserted_cutover

PUBLIC_ORIGIN = 'https://rubalkhali.science'
OUTPUT_NAME = 'post-deployment-validation.json'


def public_response(url, data=None, timeout=300):
    """Reject redirects, partial responses and noncanonical origins."""
    asserted_cutover.require(url.startswith(PUBLIC_ORIGIN + '/'), 'Canonical public HTTPS origin required')
    response = urlopen(url, data=data, timeout=timeout)
    if (response.status != 200 or response.geturl() != url
            or response.headers.get('Content-Range')):
        response.close()
        raise ValueError('Public response must be complete HTTP 200 at its exact HTTPS URL')
    return response


def public_checker():
    """Reuse validation code without changing the candidate activation globals."""
    spec = importlib.util.spec_from_file_location('_asserted_public_checker', asserted_cutover.__file__)
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    checker.BASE_URL = PUBLIC_ORIGIN
    checker.urlopen = public_response
    return checker


def validate_public_bundle(reports, manifest_bytes, auxiliary_bytes, private_loader_bytes):
    checker = public_checker()
    # The core contract validates each suite's origin and each full download URL.
    # Also bind the optional direct-query transport field when it is reported.
    endpoint = reports.get('query', {}).get('sparql_url')
    checker.require(endpoint is None or endpoint == PUBLIC_ORIGIN + '/sparql',
                    'Public query suite used a different direct endpoint')
    return checker.check_gates(reports, manifest_bytes, auxiliary_bytes, private_loader_bytes)


def sanitized_proof(reports, report_bytes, manifest_bytes, live_counts):
    """Construct a scalar-field whitelist, excluding paths, requests and raw rows."""
    queries = []
    for row in reports['query']['checks']:
        public = {key: row[key] for key in ('case', 'variant', 'status', 'rows', 'expected_rows', 'expected_sha256')}
        if asserted_cutover.valid_sha(row.get('query_sha256')):
            public['query_sha256'] = row['query_sha256']
        if row['case'] in ('taxonomy_ERR16061083_genus', 'taxonomy_api_ERR16061083_top20'):
            public['numeric_order_checked'] = True
        queries.append(public)
    protocol = []
    for row in reports['protocol']['checks']:
        public = {key: row[key] for key in ('name', 'passed', 'http_status')}
        if row['name'] != 'anonymous_update_denied':
            public['complete_response'] = True
        if row['name'] in asserted_cutover.GRAPH_FORMAT_CHECKS:
            public.update(triples=6, content_type=asserted_cutover.GRAPH_FORMAT_CHECKS[row['name']],
                          graph_isomorphic=True, literal_datatypes_preserved=True)
        if row['name'] in asserted_cutover.SELECT_LITERAL_CHECKS:
            public.update(rows=6, content_type=asserted_cutover.SELECT_LITERAL_CHECKS[row['name']],
                          result_multiset_preserved=True, literal_datatypes_preserved=True)
        protocol.append(public)
    browser = []
    for row in reports['browser']['checks']:
        if row['name'] not in asserted_cutover.BROWSER_ROWS:
            continue
        public = {key: row[key] for key in ('name', 'status', 'rows')}
        if row['name'] == 'Genus-level composition and abundance for ERR16061083':
            public['numeric_order_checked'] = True
        browser.append(public)
    files = []
    for row in reports['downloads']['files']:
        public = {key: row[key] for key in ('name', 'bytes', 'sha256', 'passed')}
        public['url'] = PUBLIC_ORIGIN + '/downloads/kg/3.0.0/' + row['name']
        if row['name'].endswith('.nq.gz'):
            public.update(rdf_syntax_checked=True, triples=asserted_cutover.COUNT, graph=asserted_cutover.GRAPH)
        files.append(public)
    software = {}
    for key in ('python', 'raptor'):
        value = reports['downloads'].get('software', {}).get(key)
        if isinstance(value, str) and re.fullmatch(r'\d+(?:\.\d+){1,3}', value):
            software[key] = value
    validator = reports['downloads'].get('software', {}).get('validator_sha256')
    if asserted_cutover.valid_sha(validator):
        software['validator_sha256'] = validator
    return {
        'version': '3.0.0', 'release_mode': 'asserted-only', 'status': 'passed',
        'public_acceptance_passed': True, 'public_origin': PUBLIC_ORIGIN,
        'verified_at_utc': datetime.now(timezone.utc).isoformat(),
        'scope': 'All five public acceptance suites passed for the exact published asserted-only manifest. '
                 'The manifest and three graph counts were rechecked over public HTTPS before this record was written. '
                 'This is a dated acceptance record, not an entailment certificate or a claim of perpetual availability.',
        'manifest_sha256': asserted_cutover.sha(manifest_bytes),
        'evidence_sha256': {name: asserted_cutover.sha(raw) for name, raw in report_bytes.items()},
        'live_graph_counts': live_counts,
        'query_result_gates': queries,
        'protocol_graph_fixture': {'sha256': asserted_cutover.GRAPH_FIXTURE_SHA256,
                                  'triples': 6, 'graph': 'urn:eq:release-test:export'},
        'protocol_gates': protocol,
        'isolation_gates': [{'name': row['name'], 'passed': True} for row in reports['isolation']['checks']],
        'ph_source_sha256': asserted_cutover.PH_SHA256,
        'browser_gates': browser,
        'browser_download_gates': [{key: row[key] for key in ('name', 'bytes', 'bounded_range_status')}
                                   for row in reports['browser']['downloads']],
        'download_gates': files,
        'auxiliary_download_gates': [{key: row[key] for key in
            ('name', 'url', 'bytes', 'sha256', 'passed', 'http_status', 'full_read')}
            for row in reports['downloads']['auxiliary_files']],
        'download_validation_software': software,
        'privacy_scope': 'Field-whitelisted result summaries and original report hashes; no private report paths, '
                         'browser request parameters, raw response bodies, credentials or operator configuration.',
    }


def publish(root, gates_dir):
    root, gates_dir = root.resolve(), gates_dir.resolve()
    asserted_cutover.require(gates_dir.is_relative_to(root / 'evidence'), 'Release-local public evidence directory required')
    publication = root / 'publication/kg/3.0.0'
    output = publication / OUTPUT_NAME
    if output.exists() or output.is_symlink():
        raise FileExistsError(output)
    raw = {}
    for name, relative in asserted_cutover.REPORTS.items():
        path = (gates_dir / relative).resolve()
        asserted_cutover.require(path.is_relative_to(gates_dir), 'Public report escapes evidence directory')
        raw[name] = path.read_bytes()
    reports = {name: json.loads(content) for name, content in raw.items()}
    manifest = (publication / 'manifest.json').read_bytes()
    auxiliary = {row['name']: (publication / row['name']).read_bytes()
                 for row in asserted_cutover.auxiliary_entries(json.loads(manifest))}
    loader = (root / 'evidence/asserted_load/report.json').read_bytes()
    validate_public_bundle(reports, manifest, auxiliary, loader)
    asserted_cutover.require((root / 'inputs/scientific/manifest.json').read_bytes()
                            == auxiliary['input-modules-manifest.json'],
                            'Public source inventory differs from loaded scientific source')
    manifest_url = PUBLIC_ORIGIN + '/downloads/kg/3.0.0/manifest.json'
    with public_response(manifest_url, timeout=60) as response:
        # Read one extra byte so a prefix match cannot certify a larger response.
        served = response.read(len(manifest) + 1)
    asserted_cutover.require(served == manifest, 'Public manifest bytes differ from validated local manifest')
    live = public_checker().verify_live_counts()
    proof = sanitized_proof(reports, raw, manifest, live)
    # Exclusive creation preserves the candidate-only validation and any previous
    # post-deployment acceptance record. No service configuration is touched.
    with output.open('x') as stream:
        json.dump(proof, stream, indent=2)
        stream.write('\n')
    return {'status': 'published-public-acceptance', 'url': PUBLIC_ORIGIN + '/downloads/kg/3.0.0/' + OUTPUT_NAME,
            'sha256': asserted_cutover.sha(output.read_bytes()), 'public_acceptance_passed': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=asserted_cutover.ROOT)
    parser.add_argument('--gates-dir', type=Path)
    args = parser.parse_args()
    print(json.dumps(publish(args.root, args.gates_dir or args.root / 'evidence/public'), indent=2))


if __name__ == '__main__':
    main()
