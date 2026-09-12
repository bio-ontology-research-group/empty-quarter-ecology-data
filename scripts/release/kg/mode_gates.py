#!/usr/bin/env python3
"""Source-backed asserted/materialized routing gates, independent of core query gates."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time

from rdflib import Graph, RDF, RDFS, URIRef
from query_gates import ROOT, VERSION, GRAPHS, GateError, binding_rows, request_json

PCR = 'https://rubalkhali.science/kb/RAK_0000307'
NEGATIVE = 'https://rubalkhali.science/kb/RAK_0000305'


def source_witness(root=ROOT, expectations=None, controls=None, tbox=None):
    expectations = expectations or root / 'results/kg-release-3.0.0/query_expectations/six_pcr_ntcs.json'
    controls = controls or root / 'ontology/rubalkhali_controls.ttl'
    tbox = tbox or root / 'ontology/rubalkhali.owl'
    rows = json.loads(expectations.read_text())
    if (len(rows) != 6 or {row['identifier'] for row in rows} !=
            {'Negative1', 'Negative2', 'Negative4', 'Negative5', 'Negative6', 'Negative7'}
            or len({row['role'] for row in rows}) != 6
            or any(row['roleClass'] != PCR for row in rows)):
        raise GateError('Expected six distinct, source-identified PCR NTC roles')
    cg = Graph().parse(controls, format='turtle')
    tg = Graph().parse(tbox, format='xml')
    if (URIRef(PCR), RDFS.subClassOf, URIRef(NEGATIVE)) not in tg:
        raise GateError('Source TBox lacks PCR-role negative-control subclass axiom')
    roles = sorted(row['role'] for row in rows)
    for role in roles:
        if (URIRef(role), RDF.type, URIRef(PCR)) not in cg:
            raise GateError(f'Source controls lack PCR type for {role}')
        if any((URIRef(role), RDF.type, URIRef(NEGATIVE)) in graph for graph in (cg, tg)):
            raise GateError(f'Witness is already asserted in its source modules: {role}')
    return {'name': 'six_pcr_negative_role_ancestors', 'roles': roles,
        'asserted_class': PCR, 'inferred_class': NEGATIVE,
        'derivation': 'Each role is explicitly PCR blank role; the source TBox makes PCR blank role a subclass of negative microbiome control role. The ancestor type is absent from the source controls and TBox.',
        'sources': [{'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
                    for path in (expectations, controls, tbox)]}


def witness_query(witness, graph=None):
    dataset = f' FROM <{graph}>' if graph else ''
    values = ' '.join(f'<{role}>' for role in witness['roles'])
    return f'SELECT ?role{dataset} WHERE {{ VALUES ?role {{ {values} }} ?role a <{NEGATIVE}> . }} ORDER BY ?role'


def compare_witness(payload, witness, expected_mode):
    if expected_mode not in GRAPHS:
        raise GateError('Unknown expected graph mode')
    rows = binding_rows(payload, ['role'], {'role': witness['roles'][0]})
    expected = witness['roles'] if expected_mode == 'materialized' else []
    if Counter(row['role'] for row in rows) != Counter(expected):
        raise GateError(f'{expected_mode} inference witness differs: received {len(rows)} rows, expected exactly {len(expected)} role IRIs')
    return rows


def variants():
    # (name, transport, requested mode, explicit FROM mode, protocol graph, expected mode)
    return [
        ('direct_server_default', 'direct', 'asserted', None, None, 'asserted'),
        ('direct_asserted', 'direct', 'asserted', None, 'asserted', 'asserted'),
        ('direct_materialized', 'direct', 'materialized', None, 'materialized', 'materialized'),
        ('direct_from_asserted', 'direct', 'asserted', 'asserted', None, 'asserted'),
        ('direct_from_materialized', 'direct', 'materialized', 'materialized', None, 'materialized'),
        ('api_asserted', 'api', 'asserted', None, None, 'asserted'),
        ('api_materialized', 'api', 'materialized', None, None, 'materialized'),
        ('api_materialized_from_asserted', 'api', 'materialized', 'asserted', None, 'asserted'),
        ('api_asserted_from_materialized', 'api', 'asserted', 'materialized', None, 'materialized'),
    ]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', required=True)
    parser.add_argument('--sparql-url')
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--expectations', type=Path)
    parser.add_argument('--controls', type=Path)
    parser.add_argument('--tbox', type=Path)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--timeout', type=float, default=300)
    args = parser.parse_args(argv)
    base = args.base_url.rstrip('/')
    endpoint = args.sparql_url or base + '/sparql'
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = args.output_dir / 'mode_gates.json'
    if output.exists():
        parser.error('Refusing to overwrite earlier mode-gate evidence')
    report = {'version': VERSION, 'status': 'failed', 'checks': [], 'base_url': base,
        'sparql_url': endpoint, 'started': datetime.now(timezone.utc).isoformat()}
    try:
        witness = source_witness(args.root, args.expectations, args.controls, args.tbox)
        report['source_witness'] = witness
        metadata = request_json(base + '/kg-release.json', args.timeout)
        if metadata.get('version') != VERSION or metadata.get('graphs') != GRAPHS:
            raise GateError('Portal release metadata differs from the mode-gate contract')
        for name, transport, mode, explicit, protocol, expected in variants():
            query = witness_query(witness, GRAPHS[explicit] if explicit else None)
            check = {'name': name, 'mode': mode, 'transport': transport,
                'expected_mode': expected, 'expected_rows': 6 if expected == 'materialized' else 0,
                'status': 'failed', 'query': query, 'rows': None}
            report['checks'].append(check)
            started = time.monotonic()
            if transport == 'api':
                response = request_json(base + '/api/query', args.timeout, payload={'query': query, 'mode': mode})
                if response.get('kg_version') != VERSION or response.get('mode') != mode:
                    raise GateError('API mode/release metadata mismatch')
                result = response.get('data')
            else:
                form = [('query', query), ('format', 'application/sparql-results+json')]
                if protocol:
                    form.append(('default-graph-uri', GRAPHS[protocol]))
                result = request_json(endpoint, args.timeout, form=form)
            (args.output_dir / f'{name}.json').write_text(json.dumps(result, indent=2) + '\n')
            check['rows'] = len(binding_rows(result, ['role'], {'role': witness['roles'][0]}))
            rows = compare_witness(result, witness, expected)
            check.update(status='passed', rows=len(rows), elapsed_seconds=time.monotonic() - started)
            print(f'PASS mode {name}: {len(rows)} exact role IRIs', flush=True)
        report['status'] = 'passed'
    except Exception as error:
        report['error'] = f'{type(error).__name__}: {error}'
        print(report['error'], flush=True)
    finally:
        output.write_text(json.dumps(report, indent=2) + '\n')
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
