#!/usr/bin/env python3
"""Prepare public, credential-free candidate acceptance evidence after all gates."""
import argparse
import hashlib
import json
from pathlib import Path

from cutover import check_gates
from certify_wkt_repair import PUBLIC_FIELDS


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('manifest', 'query', 'mode', 'download', 'browser', 'witness', 'materialization', 'protocol', 'repair'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    report_bytes = {name: getattr(args, name).read_bytes()
                    for name in ('query', 'mode', 'download', 'browser', 'witness', 'materialization', 'protocol', 'repair')}
    reports = {name: json.loads(content) for name, content in report_bytes.items()}
    hashes = {name: hashlib.sha256(content).hexdigest() for name, content in report_bytes.items()}
    manifest = args.manifest.read_bytes()
    check_gates(**reports, manifest=manifest, repair_sha256=hashes['repair'],
                materialization_sha256=hashes['materialization'])
    materialization = reports['materialization']
    query_fields = ('case', 'variant', 'status', 'rows', 'expected_rows', 'query',
                    'query_sha256', 'expected_sha256', 'source_projection', 'elapsed_seconds',
                    'numeric_order_checked')
    # Whitelist result fields. Do not copy admin commands, process arguments,
    # private environment files, absolute workstation paths or correspondence.
    public = {
        'version': '3.0.0', 'status': 'passed',
        'scope': 'Candidate acceptance before production cutover. This immutable report does not claim a later public endpoint state.',
        'manifest_sha256': hashlib.sha256(manifest).hexdigest(),
        'download_validation_software': {key: reports['download']['software'][key]
                                         for key in ('python', 'raptor', 'validator_sha256')},
        'evidence_sha256': hashes,
        'coordinate_import_certificate_sha256': hashes['repair'],
        'coordinate_import_certificate': {key: reports['repair'][key] for key in sorted(PUBLIC_FIELDS)},
        'query_result_gates': [{key: row[key] for key in query_fields if key in row}
                               for row in reports['query']['checks']],
        'protocol_graph_fixture': reports['protocol']['graph_fixture'],
        'protocol_gates': [{key: row[key] for key in
                           ('name', 'passed', 'http_status', 'complete_response', 'triples',
                            'content_type', 'graph_isomorphic', 'literal_datatypes_preserved',
                            'rows', 'result_multiset_preserved') if key in row}
                          for row in reports['protocol']['checks']],
        'inference_mode_gates': reports['mode']['checks'],
        'inference_mode_source_witness': {
            key: value for key, value in reports['mode']['source_witness'].items() if key != 'sources'},
        'inference_mode_source_hashes': [row['sha256'] for row in reports['mode']['source_witness']['sources']],
        'numeric_comparison': {key: reports['query'][key] for key in
                               ('numeric_atol', 'numeric_rtol', 'coordinate_atol')},
        'download_gates': [{key: row[key] for key in ('name', 'bytes', 'sha256', 'rdf_syntax_checked', 'triples', 'graph', 'passed')}
                           for row in reports['download']['files']],
        'auxiliary_download_gates': [{key: row[key] for key in
                                      ('name', 'url', 'sha256', 'bytes', 'http_status', 'full_read', 'passed')}
                                     for row in reports['download']['auxiliary_files']],
        'browser_gates': reports['browser']['checks'],
        'browser_download_gates': reports['browser']['downloads'],
        'entailment_witnesses': reports['witness'],
        'materialization': {key: materialization[key] for key in
                           ('program_version', 'software', 'batch_size', 'status', 'asserted_graph', 'inferred_graph',
                            'asserted_triples', 'inferred_triples', 'asserted_plus_inferred_triples',
                            'rules_sha256', 'execution_rules_sha256', 'generator_sha256', 'scope_limits')},
        'fixed_point_passes': [{'iteration': row['iteration'], 'new_triples': row['new_triples'],
                               'subclass_type_partitions': row.get('subclass_type_partitions'),
                               'rules': [{key: rule[key] for key in ('name', 'new_triples')} for rule in row['rules']]}
                              for row in materialization['passes']],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(public, indent=2) + '\n')
    print(json.dumps({'status': 'passed', 'output': str(args.output), 'sha256': digest(args.output)}))


if __name__ == '__main__':
    main()
