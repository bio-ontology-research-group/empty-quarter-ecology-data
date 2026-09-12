#!/usr/bin/env python3
"""Replace the private candidate backend; retain and restore its predecessor."""
import json
from pathlib import Path
import subprocess

ROOT = Path('/data/empty-quarter-releases/kg-3.0.0-engine7-20260910')
NAME = 'eq_kg_3_0_0_protocol_backend'
PREVIOUS = NAME + '_before_numericsort'
NETWORK = 'eq_kg_3_0_0_net'
EXPECTED_ID = '9d04c11111b3fd570878eca6cac717b2ecbf53d99f95128f8f12266c121208bd'
IMAGE = 'sha256:35722911e444f36834a65992c5634d2c6d52487c054592f9e84e4942179b9394'


def run(*args):
    return subprocess.check_output(args, text=True).strip()


def main():
    report_path = ROOT / 'evidence/backend-numericsort-replacement.json'
    if report_path.exists():
        raise RuntimeError('replacement evidence exists; inspect before retrying')
    if run('docker', 'inspect', NAME, '--format', '{{.Id}}') != EXPECTED_ID:
        raise RuntimeError('candidate backend changed')
    if subprocess.run(['docker', 'inspect', PREVIOUS], stdout=subprocess.DEVNULL,
                      stderr=subprocess.DEVNULL).returncode == 0:
        raise RuntimeError('retained container name already exists')
    run('docker', 'image', 'inspect', IMAGE, '--format', '{{.Id}}')
    production = run('docker', 'inspect', 'viz_web_1', '--format', '{{.Id}}')
    run('docker', 'stop', NAME)
    run('docker', 'rename', NAME, PREVIOUS)
    run('docker', 'network', 'disconnect', NETWORK, PREVIOUS)
    try:
        container = run('docker', 'run', '-d', '--name', NAME,
                        '--network', NETWORK, '--network-alias', 'backend',
                        '--restart', 'unless-stopped', '--memory', '4g', '--cpus', '4',
                        '-e', 'SPARQL_ENDPOINT=http://eq_kg_3_0_0_engine7:8890/sparql', IMAGE)
        run('docker', 'exec', NAME, 'python', '-m', 'pip', 'check')
        run('docker', 'exec', 'eq_kg_3_0_0_web', 'nginx', '-t')
        run('docker', 'exec', 'eq_kg_3_0_0_web', 'nginx', '-s', 'reload')
        if run('docker', 'inspect', 'viz_web_1', '--format', '{{.Id}}') != production:
            raise RuntimeError('production container changed during replacement')
    except Exception:
        # Retain failed candidate for inspection; never remove its files.
        if subprocess.run(['docker', 'inspect', NAME], stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL).returncode == 0:
            run('docker', 'stop', NAME)
            run('docker', 'network', 'disconnect', NETWORK, NAME)
            run('docker', 'rename', NAME, NAME + '_failed_numericsort')
        run('docker', 'rename', PREVIOUS, NAME)
        run('docker', 'network', 'connect', '--alias', 'backend', NETWORK, NAME)
        run('docker', 'start', NAME)
        run('docker', 'exec', 'eq_kg_3_0_0_web', 'nginx', '-s', 'reload')
        raise
    report = {'version': '3.0.0', 'container_id': container, 'image': IMAGE,
              'previous_container_retained': PREVIOUS, 'previous_container_id': EXPECTED_ID,
              'production_container_id': production, 'production_entrypoint_changed': False,
              'scope': 'Candidate replacement only; protocol acceptance is separate.'}
    report_path.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
