#!/usr/bin/env python3
"""Create a new materialized union and export only the three release graphs."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
from urllib.parse import urlencode
from urllib.request import urlopen

from kg_admin import execute
from certify_wkt_repair import validate_certificate

BASE = 'https://rubalkhali.science/graph/'
VERSION = '3.0.0'


def repair_evidence(materialization_path, certificate_path, plan_path):
    """Bind historical closure and its separate, source-backed repair proof."""
    materialization_bytes = Path(materialization_path).read_bytes()
    certificate_bytes = Path(certificate_path).read_bytes()
    plan_bytes = Path(plan_path).read_bytes()
    materialization = json.loads(materialization_bytes)
    certificate = json.loads(certificate_bytes)
    hashes = {
        'materialization_report_sha256': hashlib.sha256(materialization_bytes).hexdigest(),
        'coordinate_repair_certificate_sha256': hashlib.sha256(certificate_bytes).hexdigest(),
        'coordinate_repair_plan_sha256': hashlib.sha256(plan_bytes).hexdigest(),
    }
    validate_certificate(certificate, hashes['materialization_report_sha256'],
                         hashes['coordinate_repair_plan_sha256'],
                         {mode: materialization[mode + '_triples'] for mode in ('asserted', 'inferred')})
    if any(certificate[key] != materialization[key] for key in ('rules_sha256', 'generator_sha256')):
        raise ValueError('Repair certificate and original materialization program differ')
    return hashes


def validate_materialization(materialization):
    if (materialization.get('status') != 'fixed_point_reached'
            or not materialization.get('passes') or materialization['passes'][-1]['new_triples'] != 0
            or not materialization['passes'][-1].get('rules')
            or any(rule['new_triples'] != 0 for rule in materialization['passes'][-1]['rules'])):
        raise RuntimeError('complete fixed point required')
    for mode in ('asserted', 'inferred'):
        if materialization.get(mode + '_graph') != BASE + mode + '/' + VERSION:
            raise RuntimeError('materialization evidence belongs to a different graph')
    if (materialization.get('asserted_triples') != 45706821 or materialization.get('inferred_triples', -1) < 0
            or materialization.get('asserted_plus_inferred_triples') != materialization['asserted_triples'] + materialization['inferred_triples']):
        raise RuntimeError('materialization counts differ from the frozen release contract')


def query(endpoint, query_text):
    params = urlencode({'query': query_text, 'format': 'application/sparql-results+json'})
    with urlopen(endpoint + '?' + params, timeout=600) as response:
        for header in ('X-SQL-State', 'X-SQL-Message', 'X-SPARQL-MaxRows'):
            if response.headers.get(header):
                raise RuntimeError(f'partial/error response: {header}')
        return json.load(response)['results']['bindings']


def count(endpoint, graph):
    rows = query(endpoint, f'SELECT (COUNT(?s) AS ?n) FROM NAMED <{graph}> WHERE {{GRAPH <{graph}> {{?s ?p ?o}}}}')
    return int(rows[0]['n']['value'])


def sql(container, statement, log):
    if log.exists():
        raise FileExistsError(log)
    result, failed = execute(container, statement, timeout=14400)
    log.write_text(result)
    if failed:
        raise RuntimeError(f'SQL failed: {log}')


def union_sql(graphs):
    # Logged row-autocommit avoids one transaction spanning the entire union.
    # Only the new isolated target is changed; all inclusions are checked below.
    return (f'SPARQL DEFINE sql:log-enable 3 COPY GRAPH <{graphs["asserted"]}> TO GRAPH <{graphs["materialized"]}>;\n'
            f'SPARQL DEFINE sql:log-enable 3 ADD GRAPH <{graphs["inferred"]}> TO GRAPH <{graphs["materialized"]}>;\nCHECKPOINT;\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--container', required=True)
    parser.add_argument('--endpoint', required=True)
    parser.add_argument('--materialization-dir', type=Path, required=True)
    parser.add_argument('--repair-certificate', type=Path, required=True)
    parser.add_argument('--repair-plan', type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    if root.parent != Path('/data/empty-quarter-releases'):
        raise ValueError('explicit isolated release root required')
    materialization_dir = args.materialization_dir.resolve()
    if materialization_dir.parent != root:
        raise ValueError('materialization evidence must belong to this release')
    materialization = json.loads((materialization_dir / 'materialization.json').read_text())
    validate_materialization(materialization)
    for path in (args.repair_certificate, args.repair_plan):
        if root not in path.resolve().parents:
            raise ValueError('Repair evidence must belong to this isolated release')
    repair_hashes = repair_evidence(materialization_dir / 'materialization.json',
                                   args.repair_certificate, args.repair_plan)
    graphs = {mode: BASE + mode + '/' + VERSION for mode in ('asserted', 'inferred', 'materialized')}
    expected = {mode: materialization[f'{mode}_triples'] for mode in ('asserted', 'inferred')}
    for mode in expected:
        if count(args.endpoint, graphs[mode]) != expected[mode]:
            raise RuntimeError(f'{mode} graph changed after materialization')
    if count(args.endpoint, graphs['materialized']) != 0:
        raise RuntimeError('refusing to replace an existing materialized graph')
    out = root / 'evidence/graph_exports'
    out.mkdir(exist_ok=False)
    statement = union_sql(graphs)
    (out / 'union.sql').write_text(statement)
    sql(args.container, statement, out / 'union.log')
    expected['materialized'] = sum(expected.values())
    actual = count(args.endpoint, graphs['materialized'])
    if actual != expected['materialized']:
        raise RuntimeError('materialized union count differs from asserted + exclusive delta')
    for mode in ('asserted', 'inferred'):
        missing = query(args.endpoint, f'SELECT (COUNT(?s) AS ?n) FROM NAMED <{graphs[mode]}> FROM NAMED <{graphs["materialized"]}> WHERE {{GRAPH <{graphs[mode]}> {{?s ?p ?o}} FILTER NOT EXISTS {{GRAPH <{graphs["materialized"]}> {{?s ?p ?o}}}}}}')
        if int(missing[0]['n']['value']) != 0:
            raise RuntimeError(f'materialized graph lost {mode} facts')
    sql(args.container, (Path(__file__).parent / 'export_graph.sql').read_text(), out / 'install_exporter.log')
    release = root / 'publication/kg/3.0.0'
    release.mkdir(parents=True, exist_ok=True)
    records = []
    for mode, graph in graphs.items():
        prefix = f'kg-3.0.0-{mode}-'
        if list((root / 'exports').glob(prefix + '*.nq')):
            raise RuntimeError('refusing to overwrite previous graph export')
        sql(args.container, f"DB.DBA.EQ_EXPORT_GRAPH ('{graph}', '/release-exports/{prefix}', 250000000);\n", out / f'{mode}.log')
        parts = sorted((root / 'exports').glob(prefix + '*.nq'))
        if not parts:
            raise RuntimeError('graph export produced no files')
        subprocess.run(['docker', 'exec', '-u', '0', args.container, 'chmod', '0644',
                        *('/release-exports/' + part.name for part in parts)], check=True)
        name = f'rubalkhali-kg-3.0.0-{mode}.nq.gz'
        target = release / name
        if target.exists():
            raise FileExistsError(target)
        lines = 0
        raw_hash = hashlib.sha256()
        with target.open('xb') as dest, gzip.GzipFile(filename='', mode='wb', fileobj=dest, compresslevel=1, mtime=0) as compressed:
            for part in parts:
                with part.open('rb') as source:
                    for block in iter(lambda: source.read(8 * 1024 * 1024), b''):
                        lines += block.count(b'\n')
                        raw_hash.update(block)
                        compressed.write(block)
        if lines != expected[mode]:
            raise RuntimeError(f'{mode} export line count {lines} != {expected[mode]}')
        digest = hashlib.sha256()
        with target.open('rb') as source:
            for block in iter(lambda: source.read(8 * 1024 * 1024), b''):
                digest.update(block)
        records.append({'name': name, 'url': f'/downloads/kg/3.0.0/{name}',
                        'bytes': target.stat().st_size, 'sha256': digest.hexdigest(),
                        'uncompressed_sha256': raw_hash.hexdigest(), 'triples': lines,
                        'graph': graph, 'description': f'KG 3.0.0 {mode} graph; gzip-compressed N-Quads.'})
        (out / 'progress.json').write_text(json.dumps(records, indent=2) + '\n')
        print(json.dumps(records[-1]), flush=True)
    report = {'version': VERSION, 'passed': True, 'counts': expected,
              **repair_hashes,
              'union_write_mode': 'Logged per-row autocommit (sql:log-enable 3); isolated target verified before publication.',
              'asserted_missing_from_union': 0, 'inferred_missing_from_union': 0, 'files': records,
              'rdf_syntax_validation': 'pending; required before publication'}
    (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
