#!/usr/bin/env python3
"""Asserted-only availability, graph isolation and corrected pH identity gates."""
import argparse
import hashlib
import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from rdflib import Graph, URIRef
from query_gates import binding_rows, request_json

GRAPH = 'https://rubalkhali.science/graph/asserted/3.0.0'
PH_SHA = '4c3af7c30633822e7ce86cedd54247dbaba69a598cc9014cbc2c0cfab8a14811'

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--base-url', required=True)
    p.add_argument('--ph-source', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    base = args.base_url.rstrip('/')
    report = dict(version='3.0.0', release_mode='asserted-only', base_url=base, passed=False, checks=[])
    def query(text):
        return request_json(base + '/sparql', 300, form=[('query', text), ('format', 'application/sparql-results+json')])
    def checked(name):
        report['checks'].append(dict(name=name, passed=True))
    try:
        metadata = request_json(base + '/kg-release.json', 60)
        if metadata.get('release_mode') != 'asserted-only' or metadata.get('graphs') != {'asserted': GRAPH}:
            raise ValueError('Portal must advertise only the asserted graph')
        checked('only_asserted_advertised')
        payload = json.dumps({'query': 'ASK {}', 'mode': 'materialized'}).encode()
        try:
            urlopen(Request(base + '/api/query', data=payload, headers={'Content-Type': 'application/json'}), timeout=60)
        except HTTPError as error:
            if error.code != 400 or 'unavailable' not in error.read().decode():
                raise ValueError('Unavailable mode was not explicitly rejected')
        else:
            raise ValueError('Unreleased materialization mode accepted')
        checked('materialized_mode_rejected')
        for name in ('inferred', 'materialized'):
            iri = 'https://rubalkhali.science/graph/' + name + '/3.0.0'
            rows = binding_rows(query('SELECT ?s FROM <' + iri + '> WHERE {?s ?p ?o} LIMIT 1'), ['s'])
            if rows:
                raise ValueError('Unreleased graph is exposed: ' + name)
            checked(name + '_graph_absent')
        rows = binding_rows(query('SELECT (COUNT(*) AS ?n) WHERE {?s ?p ?o}'), ['n'])
        if rows != [{'n': '45706977'}]:
            raise ValueError('Default dataset cardinality differs from complete asserted load')
        checked('asserted_default_count')
        source = args.ph_source.read_bytes()
        if hashlib.sha256(source).hexdigest() != PH_SHA:
            raise ValueError('pH source differs from approved v1.0.1')
        graph = Graph().parse(data=source, format='turtle')
        predicate = URIRef('http://semanticscience.org/resource/SIO_000291')
        expected = sorted((str(s), str(o)) for s, o in graph.subject_objects(predicate))
        if len(expected) != 712:
            raise ValueError('Expected all712 pH physical specimen links')
        q = ('SELECT ?process ?sample FROM <' + GRAPH + '> WHERE { ?process <' + str(predicate)
             + '> ?sample . FILTER(STRSTARTS(STR(?process), "https://rubalkhali.science/kb/RAK_PH_PROCESS_")) }')
        rows = binding_rows(query(q), ['process', 'sample'])
        if sorted((r['process'], r['sample']) for r in rows) != expected:
            raise ValueError('pH specimen identities differ from the corrected source')
        checked('all_712_ph_specimen_links_exact')
        report.update(passed=True, ph_source_sha256=PH_SHA, asserted_triples=45706977)
    except Exception as error:
        report['error'] = type(error).__name__ + ': ' + str(error)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report['passed'] else 1)

if __name__ == '__main__':
    main()
