#!/usr/bin/env python3
"""Create a separately hashed loader copy that avoids Virtuoso's float32 POINT fast path.

Source RDF is never overwritten. Only whitespace between POINT and '(' in typed
GeoSPARQL wktLiteral values changes; coordinate digits, datatypes and IRIs do not.
The copy is an import adapter, not a replacement scientific source artifact.
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re

WKT = 'http://www.opengis.net/ont/geosparql#wktLiteral'
NQ_POINT = re.compile(r'"POINT\(([^"\\]*)"\^\^<' + re.escape(WKT) + r'>')
XML_POINT = re.compile(r'(<[\w:]+\b[^<>]*\b[\w:]*datatype=["\x27]' + re.escape(WKT) + r'["\x27][^<>]*>)POINT\(')


def adapt_line(line, rdf_format):
    if rdf_format == 'xml':
        return XML_POINT.subn(lambda m: m.group(1) + 'POINT (', line)
    if rdf_format in ('nq', 'nt'):
        return NQ_POINT.subn(lambda m: m.group(0).replace('"POINT(', '"POINT (', 1), line)
    raise ValueError('only XML, N-Quads and N-Triples are supported')


def prepare(source, output, rdf_format):
    source, output = Path(source), Path(output)
    if source.resolve() == output.resolve() or output.exists():
        raise ValueError('output must be a new, separate loader copy')
    source_digest = hashlib.sha256()
    with source.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            source_digest.update(chunk)
    opener = gzip.open if source.suffix == '.gz' else open
    digest, decoded_digest, count, size = hashlib.sha256(), hashlib.sha256(), 0, 0
    with opener(source, 'rt', encoding='utf-8', newline='') as inp, output.open('xb') as out:
        for line in inp:
            decoded_digest.update(line.encode('utf-8'))
            converted, changed = adapt_line(line, rdf_format)
            data = converted.encode('utf-8')
            out.write(data)
            digest.update(data)
            count += changed
            size += len(data)
    return dict(source=str(source), source_sha256=source_digest.hexdigest(),
                source_decoded_sha256=decoded_digest.hexdigest(), output=str(output),
                output_sha256=digest.hexdigest(), output_bytes=size,
                rdf_format=rdf_format, typed_point_whitespace_changes=count,
                coordinate_digits_changed=False, datatype_changed=False,
                original_source_preserved=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--format', choices=['xml', 'nq', 'nt'], required=True)
    p.add_argument('--report', type=Path, required=True)
    a = p.parse_args()
    paths = [a.source.resolve(), a.output.resolve(), a.report.resolve()]
    if len(set(paths)) != 3 or a.report.exists() or a.report.is_symlink():
        p.error('source, output and report must be distinct; report must be new and not a symlink')
    report = prepare(a.source, a.output, a.format)
    with a.report.open('x') as handle:
        handle.write(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
