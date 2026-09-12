#!/usr/bin/env python3
"""Download every manifested public artifact, check hashes and parse N-Quads."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import re
import threading
from urllib.parse import urljoin
from urllib.request import urlopen
import zlib

VERIFICATION_CODE = frozenset({
    'certify_wkt_repair.py', 'audit_geometry_rule_reachability.py',
    'assemble_publication_metadata.py', 'finalize_graphs.py', 'kg_admin.py',
})
PROOF_FILES = {'certificate': 'wkt-closure-preservation.json',
               'repair_plan': 'wkt-repair-plan.json',
               'source_audit': 'geometry_rule_source_audit.json'}
FRESH_IMPORT_FILES = frozenset({'input-modules-manifest.json', 'asserted-loader-report.json',
    'site-import-adaptations.json', 'native-export-fixture.json', 'prepare_wkt_import.py',
    'source-rebuild-verification.json'})


def auxiliary_entries(manifest):
    coordinate = manifest.get('coordinate_import')
    if not isinstance(coordinate, dict):
        raise ValueError('coordinate import proof inventory required')
    if manifest.get('release_mode') == 'asserted-only':
        if coordinate.get('method') != 'fresh-source-preserving-import':
            raise ValueError('asserted-only release requires fresh source-preserving import proof')
        entries = coordinate.get('files', [])
        if len(entries) != 6 or {r.get('name') for r in entries} != FRESH_IMPORT_FILES:
            raise ValueError('all six fresh import proof files are required')
        for item in entries:
            if (item.get('url') != '/downloads/kg/3.0.0/' + item['name']
                    or re.fullmatch('[0-9a-f]{64}', item.get('sha256', '')) is None
                    or not isinstance(item.get('bytes'), int) or item['bytes'] <= 0):
                raise ValueError('invalid fresh import proof URL/hash/size')
        return entries
    entries = [{'name': name, 'url': coordinate.get(key + '_url'),
                'sha256': coordinate.get(key + '_sha256')} for key, name in PROOF_FILES.items()]
    code = coordinate.get('verification_code')
    if (not isinstance(code, list) or len(code) != 5 or any(not isinstance(row, dict) for row in code)
            or {row.get('name') for row in code} != VERIFICATION_CODE):
        raise ValueError('exactly five unique coordinate verification programs required')
    entries.extend(code)
    for item in entries:
        if item.get('url') != '/downloads/kg/3.0.0/' + item['name']:
            raise ValueError('auxiliary URL must identify its exact immutable release basename')
        digest = item.get('sha256')
        if not isinstance(digest, str) or re.fullmatch('[0-9a-f]{64}', digest) is None:
            raise ValueError('auxiliary SHA256 digest required')
    return entries


def verify_auxiliary(base_url, entries, output_dir):
    results = []
    for item in entries:
        url = urljoin(base_url, item['url'])
        digest, size = hashlib.sha256(), 0
        with urlopen(url, timeout=600) as response:
            if response.status != 200 or response.geturl() != url or response.headers.get('Content-Range'):
                raise RuntimeError('auxiliary file requires a complete HTTP200 response at its exact URL')
            for block in iter(lambda: response.read(1024 * 1024), b''):
                digest.update(block)
                size += len(block)
        if size == 0 or digest.hexdigest() != item['sha256']:
            raise RuntimeError('auxiliary download checksum/empty-content failure: ' + item['name'])
        results.append(dict(name=item['name'], url=item['url'], sha256=digest.hexdigest(),
                            bytes=size, http_status=200, full_read=True, passed=True))
        (output_dir / 'auxiliary_progress.json').write_text(json.dumps(results, indent=2) + '\n')
        print(json.dumps(results[-1]), flush=True)
    return results


def check_manifest_entries(manifest):
    names = set()
    for item in manifest['files']:
        name = item.get('name', '')
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', name) or name in names:
            raise ValueError('artifact names must be unique, safe basenames')
        names.add(name)
        if item.get('url') != '/downloads/kg/3.0.0/' + name:
            raise ValueError('artifact URL must identify its exact immutable release basename')
        if name.endswith('.nq.gz') and item.get('graph') not in {
            f'https://rubalkhali.science/graph/{mode}/3.0.0' for mode in ('asserted', 'inferred', 'materialized')
        }:
            raise ValueError('N-Quads artifact requires an explicit release graph')


def count_serialized_quads(stream, expected_graph, result):
    """Count Raptor-parsed statements, checking its canonical N-Quads contexts.

    Input comments/blank lines never reach this stream. Raptor escapes embedded
    literal newlines and emits one line per parsed statement. Remove subject and
    predicate before checking the graph suffix so a context-free triple whose
    object happens to equal the graph IRI cannot pass.
    """
    suffix = b' <' + expected_graph.encode('ascii') + b'> .\n'
    result['quads'] = 0
    for line in stream:
        fields = line.split(b' ', 2)
        if len(fields) != 3 or not fields[2].endswith(suffix):
            result['error'] = 'parsed quad has an unexpected or absent graph context'
        result['quads'] += 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--manifest-path', default='/downloads/kg/3.0.0/manifest.json')
    args = parser.parse_args()
    software = {
        'python': platform.python_version(),
        'raptor': subprocess.run(['rapper', '--version'], check=True, capture_output=True,
                                 text=True, timeout=10).stdout.strip(),
        'validator_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    if not software['raptor']:
        raise RuntimeError('Raptor version was not reported')
    args.output_dir.mkdir(parents=True, exist_ok=False)
    with urlopen(urljoin(args.base_url, args.manifest_path), timeout=60) as response:
        manifest_bytes = response.read()
    manifest = json.loads(manifest_bytes)
    if manifest.get('version') != '3.0.0' or not manifest.get('files'):
        raise RuntimeError('missing release version or file inventory')
    check_manifest_entries(manifest)
    auxiliary = auxiliary_entries(manifest)
    (args.output_dir / 'manifest.json').write_bytes(manifest_bytes)
    results = []
    for item in manifest['files']:
        url = urljoin(args.base_url, item['url'])
        if not item['url'].startswith('/downloads/kg/3.0.0/'):
            raise RuntimeError('download target outside immutable release')
        digest = hashlib.sha256()
        raw_digest = hashlib.sha256()
        size = 0
        rdf = item['name'].endswith('.nq.gz')
        decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS) if rdf else None
        error_log = (args.output_dir / (item['name'] + '.parser.log')).open('wb') if rdf else None
        process = subprocess.Popen(['rapper', '-i', 'nquads', '-o', 'nquads', '-q', '-', 'https://rubalkhali.science/'],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=error_log) if rdf else None
        parsed = {}
        reader = threading.Thread(target=count_serialized_quads,
                                  args=(process.stdout, item['graph'], parsed), daemon=True) if rdf else None
        if reader:
            reader.start()
        try:
            with urlopen(url, timeout=600) as response:
                if response.status != 200:
                    raise RuntimeError(f'HTTP status {response.status}: {url}')
                for block in iter(lambda: response.read(1024 * 1024), b''):
                    size += len(block)
                    digest.update(block)
                    if rdf:
                        raw = decompressor.decompress(block)
                        raw_digest.update(raw)
                        process.stdin.write(raw)
                        if parsed.get('error'):
                            raise RuntimeError(parsed['error'])
            if rdf:
                raw = decompressor.flush()
                raw_digest.update(raw)
                process.stdin.write(raw)
                process.stdin.close()
                if process.wait(timeout=600) != 0:
                    raise RuntimeError(f'RDF syntax validation failed: {item["name"]}')
                reader.join(timeout=60)
                if reader.is_alive() or parsed.get('error'):
                    raise RuntimeError(parsed.get('error', 'RDF statement-count reader did not finish'))
                if not decompressor.eof or decompressor.unused_data:
                    raise RuntimeError('incomplete or trailing gzip stream')
                if parsed['quads'] != item['triples'] or raw_digest.hexdigest() != item['uncompressed_sha256']:
                    raise RuntimeError(f'RDF count/hash mismatch: {item["name"]}')
            if size != item['bytes'] or digest.hexdigest() != item['sha256']:
                raise RuntimeError(f'download bytes/checksum mismatch: {item["name"]}')
            results.append({'name': item['name'], 'url': url, 'bytes': size,
                            'sha256': digest.hexdigest(), 'rdf_syntax_checked': rdf,
                            'triples': parsed['quads'] if rdf else None,
                            'graph': item['graph'] if rdf else None, 'passed': True})
            (args.output_dir / 'progress.json').write_text(json.dumps(results, indent=2) + '\n')
            print(json.dumps(results[-1]), flush=True)
        finally:
            if process and process.poll() is None:
                process.terminate()
                process.wait(timeout=10)
            if reader:
                reader.join(timeout=10)
                process.stdout.close()
            if error_log:
                error_log.close()
    auxiliary_results = verify_auxiliary(args.base_url, auxiliary, args.output_dir)
    report = {'version': '3.0.0', 'base_url': args.base_url, 'passed': True, 'software': software,
              'manifest_sha256': hashlib.sha256(manifest_bytes).hexdigest(), 'files': results,
              'auxiliary_files': auxiliary_results}
    (args.output_dir / 'report.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
