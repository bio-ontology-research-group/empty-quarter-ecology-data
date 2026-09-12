#!/usr/bin/env python3
"""Start the isolated release application; does not change the live entry point."""
import json
from pathlib import Path
import subprocess

ROOT = Path('/data/empty-quarter-releases/kg-3.0.0-engine7-20260910')
NETWORK = 'eq_kg_3_0_0_net'


def run(*args):
    return subprocess.check_output(args, text=True).strip()


def main():
    if not (ROOT / 'evidence/asserted_load/load.sql').is_file():
        raise RuntimeError('candidate input loading has not started')
    if subprocess.run(['docker', 'network', 'inspect', NETWORK],
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
        raise RuntimeError('candidate application network already exists; inspect before continuing')
    public = ROOT / 'publication'
    (public / 'kg/3.0.0').mkdir(parents=True, exist_ok=True)
    network_id = run('docker', 'network', 'create', NETWORK)
    run('docker', 'network', 'connect', '--alias', 'virtuoso', NETWORK, 'eq_kg_3_0_0_engine7')
    backend = run('docker', 'run', '-d', '--name', 'eq_kg_3_0_0_protocol_backend',
                  '--network', NETWORK, '--network-alias', 'backend',
                  '--restart', 'unless-stopped', '--memory', '4g', '--cpus', '4',
                  '-e', 'SPARQL_ENDPOINT=http://eq_kg_3_0_0_engine7:8890/sparql',
                  'empty-quarter-backend:kg-3.0.0-protocol')
    args = ['docker', 'run', '-d', '--name', 'eq_kg_3_0_0_web',
            '--network', NETWORK, '--network-alias', 'web',
            '--restart', 'unless-stopped', '--memory', '2g', '--cpus', '2',
            '-p', '127.0.0.1:18897:80',
            '-v', f'{ROOT}/app/nginx.candidate.conf:/etc/nginx/conf.d/default.conf:ro',
            '-v', f'{public}:/release-public:ro']
    for directory in ('gallery', 'audio', 'tracks', 'twin-data', 'downloads'):
        source = Path('/data/empty-quarter/website/frontend/public') / directory
        if not source.is_dir():
            raise RuntimeError(f'missing existing public directory: {source}')
        args += ['-v', f'{source}:/usr/share/nginx/html/{directory}:ro']
    web = run(*args, 'empty-quarter-web:kg-3.0.0-finalqueries')
    run('docker', 'network', 'connect', '--alias', 'eqkg300web', 'viz_default', 'eq_kg_3_0_0_web')
    run('docker', 'exec', 'eq_kg_3_0_0_web', 'nginx', '-t')
    report = {'version': '3.0.0', 'network': network_id, 'backend': backend,
              'web': web, 'candidate_url': 'http://127.0.0.1:18897',
              'production_entrypoint_changed': False}
    (ROOT / 'evidence/application_stage.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
