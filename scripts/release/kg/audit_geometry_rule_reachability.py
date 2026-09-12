#!/usr/bin/env python3
"""Read-only source inventory for the candidate's geometry repair assessment."""
import argparse
import hashlib
import json
from pathlib import Path
import re

from rdflib import Graph, Namespace, RDF, OWL
from materialize import dump_json

ROOT = Path('/data/empty-quarter-releases/kg-3.0.0-engine7-20260910')
SOURCE = ROOT / 'inputs/scientific'
OUTPUT = ROOT / 'evidence/geometry_rule_source_audit.json'
TOKENS = (b'asWKT', b'hasGeometry', b'hasSerialization', b'wktLiteral')


def checked_records(manifest, source):
    records = manifest['records']
    if len(records) != 16:
        raise ValueError('Expected exactly 16 source modules')
    names = [record['file'] for record in records]
    if not all(isinstance(name, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', name) for name in names):
        raise ValueError('Source module filename must be a safe basename')
    if len(set(names)) != 16:
        raise ValueError('Source module filenames must be unique')
    for record in records:
        name = record['file']
        if not re.fullmatch(r'[0-9a-f]{64}', record['sha256']):
            raise ValueError('Invalid source SHA-256')
        path = source / name
        if path.is_symlink() or not path.is_file():
            raise ValueError('Source module must be a regular nonsymlink file: ' + name)
    return records


def checked_geometry_inventory(graph, geo):
    facts = list(graph.triples((None, geo.asWKT, None)))
    points = [row for row in facts if re.fullmatch(r'POINT\s*\([^()]+\)', str(row[2]))]
    polygons = [row for row in facts if str(row[2]).startswith('POLYGON(')]
    if len(facts) != 71 or len(points) != 70 or len(polygons) != 1:
        raise ValueError('Expected exactly 71 geometry facts: 70 points and one polygon')
    if len({s for s, p, o in facts}) != 71:
        raise ValueError('Expected one geometry fact per source subject')
    return facts


def audit(source_directory, output):
    if output.exists() or output.is_symlink():
        raise FileExistsError('Refusing to overwrite source-audit evidence')
    manifest_bytes = (source_directory / 'manifest.json').read_bytes()
    manifest = json.loads(manifest_bytes)
    records = []
    for record in checked_records(manifest, source_directory):
        source = source_directory / record['file']
        digest = hashlib.sha256()
        counts = {token.decode(): 0 for token in TOKENS}
        # Line streaming preserves token boundaries and never loads taxonomy in memory.
        with source.open('rb') as handle:
            for line in handle:
                digest.update(line)
                for token in TOKENS:
                    counts[token.decode()] += line.count(token)
        actual_hash = digest.hexdigest()
        if actual_hash != record['sha256']:
            raise ValueError('Manifest mismatch: ' + record['file'])
        item = {'file': record['file'], 'sha256': actual_hash, 'token_occurrences': counts}
        records.append(item)
        print(json.dumps(item), flush=True)
    matching = [r['file'] for r in records if any(r['token_occurrences'].values())]
    if matching != ['rubalkhali_sites.owl']:
        raise ValueError('Geometry vocabulary occurs outside the expected sites module')
    graph = Graph().parse(str(source_directory / 'rubalkhali_sites.owl'), format='xml')
    geo = Namespace('http://www.opengis.net/ont/geosparql#')
    declarations = list(graph.predicate_objects(geo.asWKT))
    incoming = list(graph.subject_predicates(geo.asWKT))
    if declarations != [(RDF.type, OWL.AnnotationProperty)] or incoming:
        raise ValueError('asWKT has unexpected subject/object schema connections')
    geometry_facts = checked_geometry_inventory(graph, geo)
    result = {
        'manifest_sha256': hashlib.sha256(manifest_bytes).hexdigest(),
        'module_count': len(records), 'records': records,
        'geometry_vocabulary_modules': matching,
        'asWKT_subject_statements': [[str(p), str(o)] for p, o in declarations],
        'asWKT_object_occurrences': len(incoming),
        'asWKT_fact_count': len(geometry_facts),
        'hasGeometry_fact_count': len(list(graph.triples((None, geo.hasGeometry, None)))),
        'property_schema_paths_from_asWKT': [],
        'scope': 'Hash-verified complete source vocabulary scan and parsed sites-module schema connections. This evidence establishes absence of explicit asWKT subproperty, inverse, chain-operand, domain/range or restriction references. It does not itself query inferred schema or authorize release graph edits.',
        'status': 'passed',
    }
    dump_json(output, result)
    print(json.dumps({k: v for k, v in result.items() if k != 'records'}), flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=SOURCE,
                        help='Directory containing manifest.json and exactly 16 original modules')
    parser.add_argument('--output', type=Path, default=OUTPUT,
                        help='New audit report; existing reports are never overwritten')
    args = parser.parse_args(argv)
    audit(args.source, args.output)


if __name__ == '__main__':
    main()
