#!/usr/bin/env python3
"""Gate and reversibly switch only the existing Rub al-Khali nginx entry point."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from urllib.parse import urlencode
from urllib.request import urlopen

ROOT = Path('/data/empty-quarter-releases/kg-3.0.0-engine7-20260910')
CONFIG = Path('/data/empty-quarter/viz/nginx.conf')
BASELINE_SHA256 = '2709bf5e290f94b31a8e51961c1e37f8674fc54c419215d1e18f26eefe988b61'
OLD_WEB_ID = 'de652ae9d16c1db817b5f7538375dbaec3900bcbdb81b64d1af2c74eafbb6f2b'
GRAPHS = {mode: f'https://rubalkhali.science/graph/{mode}/3.0.0'
          for mode in ('asserted', 'inferred', 'materialized')}
CASE_ROWS = dict(field_xrf_site10=46, taxonomy_ERR16061083_genus=48,
                 environment_pseudomonas_gt35=360, sites70=70, six_pcr_ntcs=6,
                 taxonomy_api_ERR16061083_top20=20)
PROTOCOL_CHECKS = {
    'default_excludes_fixture_graph', 'explicit_from_overrides_default',
    'protocol_dataset_overrides_default', 'explicit_named_dataset',
    'empty_from_does_not_fall_back_to_asserted', 'empty_protocol_dataset_does_not_fall_back',
    'wkt_datatype', 'anonymous_update_denied',
}
GRAPH_FORMAT_CHECKS = {
    'construct_turtle_roundtrip': 'text/turtle',
    'construct_ntriples_roundtrip': 'application/n-triples',
    'construct_rdfxml_roundtrip': 'application/rdf+xml',
    'construct_jsonld_roundtrip': 'application/ld+json',
}
SELECT_LITERAL_CHECKS = {
    'select_json_literal_roundtrip': 'application/sparql-results+json',
    'select_xml_literal_roundtrip': 'application/sparql-results+xml',
}
GRAPH_FIXTURE_SHA256 = '1d7d1e512c6d40728ba8d0a3b0563711f2c262dbe4d469a9858de8b935426191'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def check_gates(query, mode, download, browser, witness, materialization, protocol,
                repair, manifest, repair_sha256, materialization_sha256):
    """Reject incomplete, stale or failed evidence before any production write."""
    protocol_checks = protocol.get('checks', [])
    required_protocol = PROTOCOL_CHECKS | set(GRAPH_FORMAT_CHECKS) | set(SELECT_LITERAL_CHECKS)
    if (protocol.get('version') != '3.0.0' or protocol.get('passed') is not True
            or len(protocol_checks) != len(required_protocol)
            or {row.get('name') for row in protocol_checks} != required_protocol
            or any(row.get('passed') is not True for row in protocol_checks)):
        raise ValueError('all 14 protocol and RDF serialization gates are required')
    if protocol.get('graph_fixture') != {
            'sha256': GRAPH_FIXTURE_SHA256, 'triples': 6, 'graph': 'urn:eq:release-test:export'}:
        raise ValueError('protocol evidence must use the exact source RDF fixture')
    for row in protocol_checks:
        if row['name'] == 'anonymous_update_denied':
            if row.get('http_status', 0) < 400:
                raise ValueError('anonymous updates must be denied')
            continue
        if row.get('http_status') != 200 or row.get('complete_response') is not True:
            raise ValueError('protocol evidence includes incomplete or failed RDF responses')
        if row['name'] in GRAPH_FORMAT_CHECKS and (
                row.get('triples') != 6
                or row.get('content_type') != GRAPH_FORMAT_CHECKS[row['name']]
                or row.get('graph_isomorphic') is not True
                or row.get('literal_datatypes_preserved') is not True):
            raise ValueError('all advertised RDF formats must preserve the source graph and datatypes')
        if row['name'] in SELECT_LITERAL_CHECKS and (
                row.get('rows') != 6
                or row.get('content_type') != SELECT_LITERAL_CHECKS[row['name']]
                or row.get('result_multiset_preserved') is not True
                or row.get('literal_datatypes_preserved') is not True):
            raise ValueError('SELECT results must preserve actual literal terms, not only DATATYPE answers')
    if query.get('version') != '3.0.0' or query.get('status') != 'passed':
        raise ValueError('query release gate failed')
    checks = query.get('checks', [])
    if len(checks) != 31 or any(c.get('status') != 'passed'
            or c.get('rows') != CASE_ROWS.get(c.get('case'), -1)
            or c.get('expected_rows') != CASE_ROWS.get(c.get('case'), -1) for c in checks):
        raise ValueError('all 31 exact query-result gates are required')
    cases = ('field_xrf_site10', 'taxonomy_ERR16061083_genus', 'environment_pseudomonas_gt35', 'sites70', 'six_pcr_ntcs')
    variants = ('direct_server_default', 'direct_asserted', 'api_asserted', 'direct_explicit_from',
                'api_explicit_from_asserted', 'api_explicit_from_materialized')
    required = {(case, variant) for case in cases for variant in variants}
    required.add(('taxonomy_api_ERR16061083_top20', 'api_rank_genus_limit20'))
    if {(c.get('case'), c.get('variant')) for c in checks} != required:
        raise ValueError('query evidence omits or duplicates an exact case/transport gate')
    if any(c.get('numeric_order_checked') is not True for c in checks
           if c['case'] in ('taxonomy_ERR16061083_genus', 'taxonomy_api_ERR16061083_top20')):
        raise ValueError('taxonomy profile and top-20 API require explicit numeric ordering gates')
    expected_modes = {
        'direct_server_default': 0, 'direct_asserted': 0, 'direct_materialized': 6,
        'direct_from_asserted': 0, 'direct_from_materialized': 6,
        'api_asserted': 0, 'api_materialized': 6,
        'api_materialized_from_asserted': 0, 'api_asserted_from_materialized': 6,
    }
    mode_checks = mode.get('checks', [])
    if (mode.get('version') != '3.0.0' or mode.get('status') != 'passed'
            or len(mode_checks) != 9 or {c['name'] for c in mode_checks} != set(expected_modes)
            or any(c.get('status') != 'passed' or c.get('rows') != expected_modes[c['name']]
                   or c.get('expected_rows') != expected_modes[c['name']] for c in mode_checks)):
        raise ValueError('all nine inference-specific graph-mode gates are required')
    if not download.get('passed') or download.get('manifest_sha256') != sha(manifest):
        raise ValueError('download evidence does not match this manifest')
    release = json.loads(manifest)
    if release.get('version') != '3.0.0' or release.get('graphs') != GRAPHS:
        raise ValueError('manifest must identify the exact three versioned release graphs')
    counts = release['counts']
    if (counts['asserted'] != 45706821 or counts['inferred'] < 0
            or counts['materialized'] != counts['asserted'] + counts['inferred']):
        raise ValueError('manifest graph cardinalities violate the release contract')
    coordinate_import = release.get('coordinate_import', {})
    if coordinate_import.get('certificate_url') != '/downloads/kg/3.0.0/wkt-closure-preservation.json':
        raise ValueError('versioned coordinate repair certificate URL required')
    plan_sha256 = coordinate_import.get('repair_plan_sha256')
    if any(not isinstance(value, str) or re.fullmatch('[0-9a-f]{64}', value) is None
           for value in (repair_sha256, materialization_sha256, plan_sha256)):
        raise ValueError('coordinate repair and materialization SHA256 digests required')
    if coordinate_import.get('certificate_sha256') != repair_sha256:
        raise ValueError('manifest certificate hash differs from actual repair report bytes')
    if release.get('evidence', {}).get('materialization_report_sha256') != materialization_sha256:
        raise ValueError('manifest materialization hash differs from actual report bytes')
    # Rollback remains independent of the RDF/certificate runtime.
    from certify_wkt_repair import validate_certificate
    validate_certificate(repair, materialization_sha256, plan_sha256,
                         {key: counts[key] for key in ('asserted', 'inferred')})
    if any(repair.get(key) != materialization.get(key) for key in ('rules_sha256', 'generator_sha256')):
        raise ValueError('coordinate repair certificate and materialization rule program differ')
    from verify_downloads import auxiliary_entries
    auxiliary = auxiliary_entries(release)
    if coordinate_import['source_audit_sha256'] != repair['source_audit_sha256']:
        raise ValueError('published source audit differs from the repair certificate')
    checker = next(row for row in auxiliary if row['name'] == 'certify_wkt_repair.py')
    if checker['sha256'] != repair['checker_sha256']:
        raise ValueError('published verification checker differs from the repair certificate')
    downloaded_auxiliary = download.get('auxiliary_files', [])
    if (len(downloaded_auxiliary) != 8
            or {row.get('name') for row in downloaded_auxiliary} != {row['name'] for row in auxiliary}):
        raise ValueError('all eight unique coordinate proof downloads are required')
    for expected in auxiliary:
        actual_auxiliary = next(row for row in downloaded_auxiliary if row['name'] == expected['name'])
        if (actual_auxiliary.get('passed') is not True or actual_auxiliary.get('http_status') != 200
                or actual_auxiliary.get('full_read') is not True
                or type(actual_auxiliary.get('bytes')) is not int or actual_auxiliary['bytes'] <= 0
                or any(actual_auxiliary.get(key) != expected[key] for key in ('url', 'sha256'))):
            raise ValueError('coordinate proof download is incomplete or differs from manifest')
    for key in ('asserted', 'inferred'):
        if materialization.get(key + '_graph') != GRAPHS[key] or materialization.get(key + '_triples') != counts[key]:
            raise ValueError('materialization evidence belongs to different graphs or counts')
    if materialization.get('asserted_plus_inferred_triples') != counts['materialized']:
        raise ValueError('materialization union count differs from manifest')
    entries = release['files']
    actual = download.get('files', [])
    required_files = {f'rubalkhali-kg-3.0.0-{name}' for name in
                      ('source.tar.gz', 'modules.tar.gz', 'asserted.nq.gz', 'inferred.nq.gz', 'materialized.nq.gz')}
    if (len(entries) != 5 or len(actual) != 5 or {f['name'] for f in entries} != required_files
            or {f['name'] for f in actual} != required_files):
        raise ValueError('incomplete artifact download inventory')
    for key, graph in GRAPHS.items():
        entry = next(f for f in entries if f['name'] == f'rubalkhali-kg-3.0.0-{key}.nq.gz')
        if entry.get('graph') != graph or entry.get('triples') != counts[key]:
            raise ValueError('N-Quads inventory graph/count differs from manifest')
    for entry in entries:
        result = next(f for f in actual if f['name'] == entry['name'])
        if not result.get('passed') or any(result.get(k) != entry[k] for k in ('bytes', 'sha256')):
            raise ValueError('artifact download mismatch')
        if entry['name'].endswith('.nq.gz') and (not result.get('rdf_syntax_checked')
                or result.get('triples') != entry['triples'] or result.get('graph') != entry['graph']):
            raise ValueError('full RDF parse and count required')
    if browser.get('status') != 'passed' or browser.get('materialized_aggregate') != 'checked populated':
        raise ValueError('completed materialized browser check required')
    names = {c['name'] for c in browser.get('checks', []) if c.get('status') == 'passed'}
    if not {'asserted', 'clicked_light_elements', 'All sampling sites and their GPS coordinates',
            'Biomes associated with each site', 'DNA extraction records and concentrations',
            'Provenance: soil sample → DNA → library → sequencing run',
            'Genus-level composition and abundance for ERR16061083',
            'Pseudomonas abundance at hot sites (cross-domain join)',
            'Sequencing QC metrics for a specific sample',
            'unscoped_materialized_inference_witness'} <= names:
        raise ValueError('all-example browser evidence required')
    browser_counts = {'asserted': 46, 'clicked_light_elements': 71,
                      'All sampling sites and their GPS coordinates': 70,
                      'Genus-level composition and abundance for ERR16061083': 48,
                      'Pseudomonas abundance at hot sites (cross-domain join)': 360}
    for name, expected in browser_counts.items():
        matching = [row for row in browser['checks'] if row['name'] == name]
        if len(matching) != 1 or matching[0].get('rows') != expected:
            raise ValueError('browser source-result cardinality differs: ' + name)
        if (name == 'Genus-level composition and abundance for ERR16061083'
                and matching[0].get('numeric_order_checked') is not True):
            raise ValueError('browser taxonomy profile must verify numeric ordering')
    for name in ('Biomes associated with each site', 'DNA extraction records and concentrations',
                 'Provenance: soil sample → DNA → library → sequencing run',
                 'Sequencing QC metrics for a specific sample'):
        if not any(c['name'] == name and c.get('rows', 0) > 0 for c in browser['checks']):
            raise ValueError('browser example returned no records: ' + name)
    witness_rows = [c for c in browser['checks'] if c['name'] == 'unscoped_materialized_inference_witness']
    source_roles = mode.get('source_witness', {}).get('roles', [])
    if (len(source_roles) != 6 or len(set(source_roles)) != 6 or len(witness_rows) != 1
            or witness_rows[0].get('mode') != 'materialized' or witness_rows[0].get('rows') != 6
            or witness_rows[0].get('expected_rows') != 6
            or sorted(witness_rows[0].get('expected_role_iris', [])) != sorted(source_roles)):
        raise ValueError('browser must prove the six source-derived materialized role identities')
    links = browser.get('downloads')
    if (not isinstance(links, list) or len(links) != len(entries)
            or {row['name'] for row in links} != required_files
            or any(row.get('bounded_range_status') != 206 or row.get('bytes') != next(f['bytes'] for f in entries if f['name'] == row['name']) for row in links)):
        raise ValueError('browser download links required')
    if witness.get('status') != 'passed' or witness.get('asserted_inferred_overlap') != 0:
        raise ValueError('source-backed entailment witnesses required')
    if materialization.get('status') != 'fixed_point_reached' or materialization['passes'][-1]['new_triples'] != 0:
        raise ValueError('complete finite-rule fixed point required')


def run(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout


def verify_live_counts(counts):
    actual = {}
    for mode, graph in GRAPHS.items():
        query = f'SELECT (COUNT(?s) AS ?n) FROM NAMED <{graph}> WHERE {{GRAPH <{graph}> {{?s ?p ?o}}}}'
        data = urlencode({'query': query, 'format': 'application/sparql-results+json'}).encode()
        with urlopen('http://127.0.0.1:18897/sparql', data=data, timeout=300) as response:
            if response.status != 200 or any(response.headers.get(name) for name in ('X-SQL-State', 'X-SQL-Message', 'X-SPARQL-MaxRows')):
                raise RuntimeError('candidate live-count query failed or returned partial data')
            rows = json.load(response)['results']['bindings']
        if len(rows) != 1:
            raise RuntimeError('candidate live-count query returned an invalid result shape')
        actual[mode] = int(rows[0]['n']['value'])
    if actual != counts:
        raise RuntimeError('live candidate graph counts changed after acceptance')
    return actual


def write_config(data):
    # Preserve the inode: the running production container bind-mounts this file.
    with CONFIG.open('wb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['activate', 'rollback'])
    parser.add_argument('--query', type=Path)
    parser.add_argument('--mode', type=Path)
    parser.add_argument('--download', type=Path)
    parser.add_argument('--browser', type=Path)
    parser.add_argument('--witness', type=Path)
    parser.add_argument('--materialization', type=Path)
    parser.add_argument('--protocol', type=Path)
    parser.add_argument('--repair', type=Path)
    args = parser.parse_args()
    evidence = ROOT / 'evidence/cutover'
    baseline = evidence / 'nginx.before.conf'
    proposed = (Path(__file__).parent / 'nginx.cutover.conf').read_bytes()
    if run('docker', 'inspect', 'viz_web_1', '--format', '{{.Id}}').strip() != OLD_WEB_ID:
        raise RuntimeError('production web container changed; re-audit required')
    if args.operation == 'rollback':
        original = baseline.read_bytes()
        if sha(original) != BASELINE_SHA256 or CONFIG.read_bytes() != proposed:
            raise RuntimeError('rollback baseline/current configuration mismatch')
        write_config(original)
        run('docker', 'exec', 'viz_web_1', 'nginx', '-t')
        run('docker', 'exec', 'viz_web_1', 'nginx', '-s', 'reload')
        (evidence / 'rollback.json').write_text(json.dumps({'status': 'restored', 'sha256': sha(original)}) + '\n')
        return
    reports, report_hashes = {}, {}
    for name in ('query', 'mode', 'download', 'browser', 'witness', 'materialization', 'protocol', 'repair'):
        path = getattr(args, name)
        if path is None or ROOT not in path.resolve().parents:
            raise ValueError(f'explicit release-local {name} evidence required')
        content = path.read_bytes()
        reports[name] = json.loads(content)
        report_hashes[name] = sha(content)
    manifest = (ROOT / 'publication/kg/3.0.0/manifest.json').read_bytes()
    check_gates(**reports, manifest=manifest, repair_sha256=report_hashes['repair'],
                materialization_sha256=report_hashes['materialization'])
    live_counts = verify_live_counts(json.loads(manifest)['counts'])
    with urlopen('http://127.0.0.1:18897/downloads/kg/3.0.0/manifest.json', timeout=30) as response:
        if response.read() != manifest:
            raise RuntimeError('candidate HTTP manifest differs from validated artifact inventory')
    original = CONFIG.read_bytes()
    if sha(original) != BASELINE_SHA256:
        raise RuntimeError('production configuration changed; re-audit required')
    candidate = json.loads(run('docker', 'inspect', 'eq_kg_3_0_0_web'))[0]
    if not candidate['State']['Running'] or 'eqkg300web' not in candidate['NetworkSettings']['Networks']['viz_default']['Aliases']:
        raise RuntimeError('candidate entry point unavailable')
    evidence.mkdir(exist_ok=False)
    baseline.write_bytes(original)
    record = {'status': 'prepared', 'candidate_id': candidate['Id'], 'candidate_image': candidate['Image'],
              'baseline_sha256': sha(original), 'activated_sha256': sha(proposed),
              'live_counts_before_activation': live_counts,
              'gates': {name: {'path': str(getattr(args, name)), 'sha256': report_hashes[name]} for name in reports}}
    (evidence / 'activation.json').write_text(json.dumps(record, indent=2) + '\n')
    try:
        write_config(proposed)
        run('docker', 'exec', 'viz_web_1', 'nginx', '-t')
        run('docker', 'exec', 'viz_web_1', 'nginx', '-s', 'reload')
        record['status'] = 'activated; public acceptance gates pending'
    except Exception:
        write_config(original)
        run('docker', 'exec', 'viz_web_1', 'nginx', '-t')
        run('docker', 'exec', 'viz_web_1', 'nginx', '-s', 'reload')
        record['status'] = 'automatically rolled back after activation error'
        raise
    finally:
        (evidence / 'activation.json').write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps(record, indent=2))


if __name__ == '__main__':
    main()
