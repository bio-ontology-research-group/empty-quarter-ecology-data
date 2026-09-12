#!/usr/bin/env python3
"""Detached source rebuild and fresh inference; no production cutover."""
import datetime
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import time

JOB = Path('/data/empty-quarter-rebuild-20260912.soesx5')
ROOT = Path('/data/empty-quarter-releases/kg-3.0.0-ph101-20260912')
NAME = 'eq_kg_3_0_0_ph101'
ENDPOINT = 'http://127.0.0.1:18898/sparql'
RUNTIME = Path('/tmp/eq-validation-20260805.HFq85v/conda-env2')
SOURCE = JOB / 'source'
CODE = JOB / 'kg-code'

def stage(value):
    (JOB / 'stage').write_text(value + '\n')
    print(datetime.datetime.now(datetime.timezone.utc).isoformat(), value, flush=True)

def run(*args, **kwargs):
    print('RUN', ' '.join(map(str, args)), flush=True)
    subprocess.run(list(map(str, args)), check=True, **kwargs)

def main():
    if SOURCE.exists() or ROOT.exists():
        raise FileExistsError('Fresh source and database directories required')
    os.environ.update(CONDA_PREFIX=str(RUNTIME), JAVA_HOME=str(RUNTIME / 'lib/jvm'),
        PATH=str(RUNTIME / 'bin') + ':/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
        JAVA_OPTS='-Xms2g -Xmx32g', OMP_NUM_THREADS='4', OPENBLAS_NUM_THREADS='4', MKL_NUM_THREADS='4')
    stage('verify_and_extract_frozen_source')
    archive = Path('/data/empty-quarter-releases/kg-3.0.0-engine7-20260910/rubalkhali-kg-3.0.0-source-r7.tar.gz')
    expected = 'c032d8894284c163fbc44627ab9fd36aa8a676d30b811ef3e74ae51fbc6acf10'
    if hashlib.sha256(archive.read_bytes()).hexdigest() != expected:
        raise ValueError('Predecessor archive transfer hash mismatch')
    SOURCE.mkdir()
    run('tar', '-xzf', archive, '--strip-components=1', '-C', SOURCE)
    run('sha256sum', '-c', 'SOURCE_SHA256SUMS', cwd=SOURCE)
    shutil.copytree(JOB / 'local_overlay/scripts', SOURCE / 'scripts', dirs_exist_ok=True)
    shutil.copytree(JOB / 'local_overlay/metadata', SOURCE / 'data/metadata', dirs_exist_ok=True)
    shutil.copy2(JOB / 'ph_reference_complete.ttl', SOURCE / 'expected/ph_v1_0_1_reference.ttl')
    run(RUNTIME / 'bin/python3', JOB / 'prepare_successor_manifest.py', SOURCE)
    stage('rebuilding_all_16_source_modules')
    run('bash', SOURCE / 'scripts/release/rebuild_public_sources.sh', SOURCE, JOB / 'rebuilt')
    check = json.loads((JOB / 'rebuilt/rebuild_verification.json').read_text())
    if not check['passed'] or len(check['checks']) != 16:
        raise ValueError('Complete sixteen-module replay gate required')
    stage('creating_fresh_isolated_database')
    run('/usr/bin/python3', CODE / 'stage_database.py', '--root', ROOT, '--name', NAME, '--port', '18898')
    shutil.copytree(CODE, ROOT / 'entailment-code')
    sys.path.insert(0, str(CODE))
    from kg_admin import execute
    from materialize import Endpoint
    sql_command = ['docker', 'exec', '-i', NAME, 'sh', '-c',
        'exec isql localhost:1111 dba "$DBA_PASSWORD" VERBOSE=OFF PROMPT=OFF']
    command_file = ROOT / 'entailment-code/staging_sql_command.json'
    command_file.write_text(json.dumps(sql_command) + '\n')
    endpoint = Endpoint(ENDPOINT, sql_command, 7200)
    for attempt in range(120):
        try:
            endpoint.count('urn:eq:release-test:startup')
            break
        except Exception:
            time.sleep(2)
    else:
        raise TimeoutError('Fresh database did not become ready')
    # Verify runtime limits before loading or materializing, not only environment declarations.
    output, failed = execute(NAME, "SELECT sys_stat('txn_after_image_limit') AS txn_limit;\n")
    (ROOT / 'evidence/runtime_limits.log').write_text(output)
    if failed or re.findall(r'^\s*(\d+)\s*$', output, re.M) != ['250000000']:
        raise ValueError('Required transaction runtime limit not established')
    output, failed = execute(NAME, "SELECT __dbf_set('hash_join_enable', 1);\n")
    (ROOT / 'evidence/hash_join_runtime.log').write_text(output)
    if failed:
        raise ValueError('Could not establish hash join runtime flag')
    config = subprocess.check_output(['docker', 'exec', '-u', '0', NAME, 'cat', '/database/virtuoso.ini'], text=True)
    for key, expected_value in [('hash_join_enable', 1), ('MaxConstructTriples', 100000000), ('MaxMemInUse', 17179869184)]:
        if re.findall(r'^\s*' + key + r'\s*=\s*(\d+)\s*$', config, re.M) != [str(expected_value)]:
            raise ValueError('Required persistent configuration missing: ' + key)
    inputs = ROOT / 'inputs/scientific'
    inputs.mkdir()
    manifest = json.loads((SOURCE / 'expected/fresh_modules_manifest.json').read_text())
    for row in manifest['records']:
        shutil.copy2(JOB / 'rebuilt/data/processed/ontology' / row['file'], inputs / row['file'])
    (inputs / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    (inputs / 'SHA256SUMS').write_text(''.join(r['sha256'] + '  ' + r['file'] + '\n' for r in manifest['records']))
    shutil.copy2(SOURCE / 'expected/catalog-v001.xml', inputs / 'catalog-v001.xml')
    stage('fresh_asserted_load_with_wkt_adapter')
    run('/usr/bin/python3', CODE / 'load_asserted.py', '--root', ROOT, '--container', NAME, '--endpoint', ENDPOINT)
    stage('real_engine_entailment_fixtures')
    for script, name in [('verify_staging_fixture.py', 'fixture'), ('verify_batch_resume_fixture.py', 'batchfixture')]:
        run('/usr/bin/python3', CODE / script, '--endpoint', ENDPOINT, '--sql-command-file', command_file,
            '--graph-prefix', 'urn:eq:release-test:ph101-' + name, '--output-dir', ROOT / 'evidence' / name)
    stage('fresh_materialization_to_zero_addition_pass')
    run('/usr/bin/python3', CODE / 'materialize.py', '--endpoint', ENDPOINT, '--sql-command-file', command_file,
        '--asserted-graph', 'https://rubalkhali.science/graph/asserted/3.0.0',
        '--inferred-graph', 'https://rubalkhali.science/graph/inferred/3.0.0',
        '--batch-size', '500000', '--output-dir', ROOT / 'materialization', '--staging-only')
    run('/usr/bin/python3', CODE / 'verify_release_witnesses.py', '--endpoint', ENDPOINT,
        '--asserted-graph', 'https://rubalkhali.science/graph/asserted/3.0.0',
        '--inferred-graph', 'https://rubalkhali.science/graph/inferred/3.0.0',
        '--controls', inputs / 'rubalkhali_controls.ttl', '--output', ROOT / 'evidence/witness.json')
    stage('inference_complete_awaiting_export_and_deployment_gates')

if __name__ == '__main__':
    if sys.argv[1:] == ['--detach']:
        with (JOB / 'controller.log').open('x') as log:
            child = subprocess.Popen(['/usr/bin/python3', '-u', __file__], stdin=subprocess.DEVNULL,
                stdout=log, stderr=subprocess.STDOUT, start_new_session=True, cwd=JOB)
        print(json.dumps({'pid': child.pid, 'job_root': str(JOB), 'production_cutover': False}))
        raise SystemExit(0)
    code = 1
    (JOB / 'controller.pid').write_text(str(os.getpid()) + '\n')
    try:
        main()
        code = 0
    finally:
        (JOB / 'exitcode').write_text(str(code) + '\n')
        (JOB / 'finished_at').write_text(datetime.datetime.now(datetime.timezone.utc).isoformat() + '\n')
