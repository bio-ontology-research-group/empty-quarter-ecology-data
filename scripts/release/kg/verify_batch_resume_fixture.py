#!/usr/bin/env python3
"""Force three-triple live batches and resume a genuine pass-limit failure."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

from rdflib import Graph, Namespace, RDF, RDFS, URIRef
from materialize import Endpoint, dump_json, iri, materialize_local


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--endpoint', required=True)
    parser.add_argument('--sql-command-file', type=Path, required=True)
    parser.add_argument('--graph-prefix', required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'urn:eq:release-test:[A-Za-z0-9:._-]+', args.graph_prefix):
        raise ValueError('Only isolated fixture graph namespaces allowed')
    if args.output_dir.exists():
        raise FileExistsError('Refusing to overwrite fixture evidence')
    a, i = args.graph_prefix + ':asserted', args.graph_prefix + ':inferred'
    endpoint = Endpoint(args.endpoint, json.loads(args.sql_command_file.read_text()), 7200)
    if endpoint.count(a) or endpoint.count(i):
        raise ValueError('Fixture graphs must be empty')
    graph = Graph()
    ex = Namespace('urn:eq:release-test:batch:')
    for n in range(4):
        graph.add((ex[f'item{n}'], RDF.type, ex.Child))
        graph.add((ex[f'item{n}'], RDF.type, ex.Other))
    graph.add((ex.Child, RDFS.subClassOf, ex.Parent))
    graph.add((ex.Other, RDFS.subClassOf, ex.Parent))
    graph.add((ex.Parent, RDFS.subClassOf, ex.Ancestor))
    expected, _ = materialize_local(graph, batch_size=0)
    nt = graph.serialize(format='nt')
    if isinstance(nt, bytes):
        nt = nt.decode()
    escaped = nt.replace('\\', '\\\\').replace("'", "''")
    endpoint.sql(f"DB.DBA.TTLP('{escaped}', '', '{a}', 0);\nCOMMIT WORK;")
    args.output_dir.mkdir()
    generator = Path(__file__).with_name('materialize.py')
    base = [sys.executable, str(generator), '--endpoint', args.endpoint,
            '--sql-command-file', str(args.sql_command_file), '--asserted-graph', a,
            '--inferred-graph', i, '--batch-size', '3', '--staging-only']
    failed = args.output_dir / 'expected-failure'
    first = subprocess.run(base + ['--output-dir', str(failed), '--max-passes', '1'],
                           capture_output=True, text=True)
    (args.output_dir / 'expected-failure.log').write_text(first.stdout + first.stderr)
    failed_report = json.loads((failed / 'materialization.json').read_text())
    if first.returncode == 0 or failed_report['status'] != 'failed' or 'Pass limit reached' not in failed_report['error']:
        raise ValueError('Expected genuine operational pass-limit failure')
    resumed = args.output_dir / 'resumed'
    subprocess.run(base + ['--output-dir', str(resumed), '--resume-report',
                          str(failed / 'materialization.json'), '--resume-generator', str(generator)], check=True)
    rows = endpoint.query(f'SELECT ?s ?p ?o WHERE {{ GRAPH {iri(i)} {{ ?s ?p ?o }} }}')['results']['bindings']
    actual = {(URIRef(row['s']['value']), URIRef(row['p']['value']), URIRef(row['o']['value'])) for row in rows}
    report = json.loads((resumed / 'materialization.json').read_text())
    batches = [r['batch_additions'] for p in failed_report['passes'] for r in p['rules']]
    checks = {'batch_bound': all(0 <= n <= 3 for b in batches for n in b),
              'forced_multiple_batches': any(len(b) > 2 for b in batches),
              'every_rule_terminal_zero': all(b[-1] == 0 for b in batches),
              'resumed_delta_equals_unbounded_reference': actual == set(expected),
              'original_failure_preserved': json.loads((failed / 'materialization.json').read_text()) == failed_report,
              'resumed_fixed_point': report['status'] == 'fixed_point_reached' and report['passes'][-1]['new_triples'] == 0}
    result = {'checks': checks, 'expected_inferred_triples': len(expected),
              'actual_inferred_triples': len(actual),
              'generator_sha256': hashlib.sha256(generator.read_bytes()).hexdigest(),
              'status': 'passed' if all(checks.values()) else 'failed'}
    dump_json(args.output_dir / 'verification.json', result)
    print(json.dumps(result), flush=True)
    if not all(checks.values()):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
