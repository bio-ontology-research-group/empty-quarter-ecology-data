#!/usr/bin/env python3
"""Durable named acceptance steps for the asserted-only candidate."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path('/data/empty-quarter-releases/kg-3.0.0-asserted-20260912')
SOURCE = Path('/data/empty-quarter-rebuild-20260912.soesx5/source')
CODE = Path(__file__).resolve().parent
PYTHON = '/tmp/eq-validation-20260805.HFq85v/conda-env2/bin/python3'

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('step', choices=['query', 'protocol', 'isolation', 'downloads', 'package', 'bundle'])
    p.add_argument('--public', action='store_true')
    p.add_argument('--detach', action='store_true')
    a = p.parse_args()
    phase = 'public' if a.public else 'candidate'
    out = ROOT / 'evidence' / phase
    out.mkdir(parents=True, exist_ok=True)
    if a.detach:
        with (out / (a.step + '.log')).open('x') as log:
            command = [sys.executable, '-u', __file__, a.step] + (['--public'] if a.public else [])
            child = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log,
                                     stderr=subprocess.STDOUT, start_new_session=True)
        print('Detached', a.step, 'PID', child.pid, flush=True)
        return
    if a.step == 'bundle':
        if a.public:
            raise ValueError('Bundling is a candidate preparation step')
        deadline = time.monotonic() + 14400
        while not (ROOT / 'evidence/asserted_export.json').exists():
            exitcode = CODE / 'asserted_stage.exitcode'
            if exitcode.exists() and exitcode.read_text().strip() != '0':
                raise RuntimeError('Asserted export failed; do not package partial output')
            if time.monotonic() >= deadline:
                raise TimeoutError('Asserted export wait exceeded four hours')
            time.sleep(5)
        for step in ('package', 'downloads'):
            subprocess.run([sys.executable, '-u', __file__, step], check=True)
        (out / 'bundle.exitcode').write_text('0\n')
        return
    base = 'https://rubalkhali.science' if a.public else 'http://127.0.0.1:18901'
    commands = {
        'query': [PYTHON, CODE / 'query_gates.py', '--base-url', base, '--root', SOURCE,
            '--expectations', SOURCE / 'expected/query_expectations', '--output-dir', out / 'query', '--asserted-only'],
        'protocol': [PYTHON, CODE / 'check_engine_contract.py', '--endpoint', base + '/sparql', '--output', out / 'protocol.json'],
        'isolation': [PYTHON, CODE / 'asserted_release_gates.py', '--base-url', base,
            '--ph-source', ROOT / 'inputs/scientific/rubalkhali_ph_eq_ph_shared_v1_0_1.ttl', '--output', out / 'isolation.json'],
        'downloads': [PYTHON, CODE / 'verify_downloads.py', '--base-url', base, '--output-dir', out / 'downloads'],
        'package': [PYTHON, CODE / 'package_asserted_release.py', '--root', ROOT, '--source', SOURCE,
            '--output-dir', ROOT / 'publication/kg/3.0.0', '--export-report', ROOT / 'evidence/asserted_export.json',
            '--import-code', CODE],
    }
    # The earlier workflow build supports Turtle only. Use the distribution
    # Raptor binary, extracted without changing host packages, for N-Quads.
    os.environ['PATH'] = '/data/empty-quarter-rebuild-20260912.soesx5/raptor-runtime/usr/bin:' + os.environ['PATH']
    rc = 1
    try:
        subprocess.run(list(map(str, commands[a.step])), check=True)
        if a.step == 'package':
            import shutil
            shutil.copy2(ROOT / 'publication/kg/3.0.0/service-description.ttl', ROOT / 'publication/service-description.ttl')
        rc = 0
    finally:
        (out / (a.step + '.exitcode')).write_text(str(rc) + '\n')

if __name__ == '__main__':
    main()
