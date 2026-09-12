#!/usr/bin/env python3
"""Fresh asserted-only serving database, separate from ongoing inference."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

from kg_admin import execute
from load_asserted import count

ROOT = Path('/data/empty-quarter-releases/kg-3.0.0-asserted-20260912')
PREDECESSOR = Path('/data/empty-quarter-releases/kg-3.0.0-ph101-20260912')
CONTAINER = 'eq_kg_3_0_0_asserted'
ENDPOINT = 'http://127.0.0.1:18900/sparql'
GRAPH = 'https://rubalkhali.science/graph/asserted/3.0.0'
CODE = Path(__file__).resolve().parent

def run(*args):
    subprocess.run(list(map(str, args)), check=True)

def sql(statement, name):
    path = ROOT / 'evidence' / name
    if path.exists():
        raise FileExistsError(path)
    result, failed = execute(CONTAINER, statement, timeout=14400)
    path.write_text(result)
    if failed:
        raise RuntimeError('SQL failed; inspect ' + str(path))

def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()

def main():
    report = json.loads((PREDECESSOR / 'evidence/asserted_load/report.json').read_text())
    if report['passed'] is not True or report['triples'] != 45706977:
        raise ValueError('Confirmed fresh source load required')
    run(sys.executable, CODE / 'stage_database.py', '--root', ROOT, '--name', CONTAINER, '--port', '18900')
    shutil.copytree(CODE, ROOT / 'release-code')
    shutil.copytree(PREDECESSOR / 'inputs/scientific', ROOT / 'inputs/scientific')
    for attempt in range(120):
        try:
            if count(ENDPOINT) != 0:
                raise ValueError('Fresh target must be empty')
            break
        except OSError:
            time.sleep(2)
    else:
        raise TimeoutError('Fresh serving database not ready')
    run(sys.executable, CODE / 'load_asserted.py', '--root', ROOT, '--container', CONTAINER, '--endpoint', ENDPOINT)
    if count(ENDPOINT) != report['triples']:
        raise ValueError('Serving asserted graph differs in cardinality')
    # Native serializer proof remains a requirement for asserted-only exports.
    sql((CODE / 'export_graph.sql').read_text(), 'install_exporter.log')
    shutil.copy2(CODE / 'export_fixture.ttl', ROOT / 'inputs/export_fixture.ttl')
    sql((CODE / 'export_fixture.sql').read_text(), 'export_fixture.log')
    run('docker', 'exec', '-u', '0', CONTAINER, 'chmod', '0644', '/release-exports/export-fixture-000001.nq')
    run(sys.executable, CODE / 'verify_export_fixture.py', '--export', ROOT / 'exports/export-fixture-000001.nq',
        '--output', ROOT / 'evidence/export_fixture.json')
    sql("DB.DBA.EQ_EXPORT_GRAPH ('" + GRAPH + "', '/release-exports/asserted-', 250000000);\n", 'export_asserted.log')
    parts = sorted((ROOT / 'exports').glob('asserted-*.nq'))
    if not parts:
        raise ValueError('No asserted export parts')
    run('docker', 'exec', '-u', '0', CONTAINER, 'chmod', '0644', *('/release-exports/' + p.name for p in parts))
    output = ROOT / 'publication/kg/3.0.0'
    output.mkdir(parents=True)
    name = 'rubalkhali-kg-3.0.0-asserted.nq.gz'
    target = output / name
    raw_hash, lines = hashlib.sha256(), 0
    with target.open('xb') as dest, gzip.GzipFile(filename='', mode='wb', fileobj=dest, compresslevel=1, mtime=0) as compressed:
        for part in parts:
            with part.open('rb') as source:
                for block in iter(lambda: source.read(8 * 1024 * 1024), b''):
                    raw_hash.update(block)
                    lines += block.count(b'\n')
                    compressed.write(block)
    if lines != report['triples'] or count(ENDPOINT) != lines:
        raise ValueError('Asserted export count mismatch')
    entry = dict(name=name, url='/downloads/kg/3.0.0/' + name, bytes=target.stat().st_size,
        sha256=sha(target), uncompressed_sha256=raw_hash.hexdigest(), triples=lines, graph=GRAPH,
        description='Deduplicated asserted graph; no inferred triples or query-time inference.')
    evidence = dict(version='3.0.0', release_mode='asserted-only', passed=True, files=[entry],
        input_manifest_sha256=sha(ROOT / 'inputs/scientific/manifest.json'),
        loader_report_sha256=sha(ROOT / 'evidence/asserted_load/report.json'),
        export_fixture_sha256=sha(ROOT / 'evidence/export_fixture.json'), production_mutated=False)
    (ROOT / 'evidence/asserted_export.json').write_text(json.dumps(evidence, indent=2) + '\n')
    print(json.dumps(evidence), flush=True)

if __name__ == '__main__':
    if sys.argv[1:] == ['--detach']:
        with (CODE / 'asserted_stage.log').open('x') as log:
            proc = subprocess.Popen([sys.executable, '-u', __file__], stdin=subprocess.DEVNULL,
                stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        print(json.dumps({'pid': proc.pid, 'log': str(CODE / 'asserted_stage.log')}))
    else:
        status = 1
        try:
            main()
            status = 0
        finally:
            (CODE / 'asserted_stage.exitcode').write_text(str(status) + '\n')
