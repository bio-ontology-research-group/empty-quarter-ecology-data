#!/usr/bin/env python3
"""Check native N-Quads round-trip values, language, Unicode and blank nodes."""
import argparse
from decimal import Decimal
import json
from pathlib import Path
import re

from rdflib import ConjunctiveGraph, Graph, Literal, URIRef
from rdflib.compare import isomorphic


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--export', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    source = Graph().parse(str(Path(__file__).with_name('export_fixture.ttl')), format='turtle')
    dataset = ConjunctiveGraph()
    dataset.parse(str(args.export), format='nquads')
    contexts = list(dataset.contexts())
    graph_iri = URIRef('urn:eq:release-test:export')
    if len(contexts) != 1 or contexts[0].identifier != graph_iri:
        raise RuntimeError('exported graph identity changed')
    exported = dataset.get_context(graph_iri)
    subject = URIRef('urn:eq:export:subject')
    double = exported.value(subject, URIRef('urn:eq:export:double'))
    expected = source.value(subject, URIRef('urn:eq:export:double'))
    if double.datatype != expected.datatype or double.toPython() != expected.toPython():
        raise RuntimeError('binary64 numeric value changed')
    if abs(Decimal(str(double)) - Decimal('0.03035258267')) > Decimal('1e-17'):
        raise RuntimeError('double lost scientific precision')
    wkt = URIRef('http://www.opengis.net/ont/geosparql#wktLiteral')
    for graph in (source, exported):
        for s, p, o in list(graph):
            if isinstance(o, Literal) and o.datatype == wkt:
                graph.remove((s, p, o))
                graph.add((s, p, Literal(re.sub(r'POINT\s*\(', 'POINT(', str(o)), datatype=wkt)))
    if len(exported) != 6 or not isomorphic(source, exported):
        raise RuntimeError('fixture structure, Unicode, language or literal value changed')
    report = {'passed': True, 'triples': 6, 'graph': str(graph_iri),
              'binary64_preserved': True, 'blank_nodes_unicode_language_preserved': True,
              'wkt_datatype_preserved': True,
              'lexical_canonicalization': 'Native storage serializes double values and WKT in its own lexical form; original source modules are also distributed unchanged.'}
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
