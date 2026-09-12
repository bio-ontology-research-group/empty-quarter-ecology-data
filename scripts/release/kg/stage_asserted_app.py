#!/usr/bin/env python3
"""Build isolated asserted-only portal images; preserve the live stack."""
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path('/data/empty-quarter-releases/kg-3.0.0-asserted-20260912')
JOB = Path('/data/empty-quarter-rebuild-20260912.soesx5')
NETWORK = 'eq_kg_3_0_0_asserted_net'
BACKEND = 'eq_kg_3_0_0_asserted_backend'
WEB = 'eq_kg_3_0_0_asserted_web'

def run(*args):
    return subprocess.check_output(args, text=True).strip()

def main():
    app = ROOT / 'app'
    if app.exists():
        raise FileExistsError('Do not overwrite an existing application build')
    shutil.copytree('/data/empty-quarter-releases/kg-3.0.0-engine7-20260910/app', app)
    shutil.copytree(JOB / 'app-overlay', app, dirs_exist_ok=True)
    config = (app / 'nginx.candidate.conf').read_text().replace('eq_kg_3_0_0_protocol_backend', BACKEND)
    (app / 'nginx.candidate.conf').write_text(config)
    for kind in ('backend', 'frontend'):
        tag = 'empty-quarter-' + kind + ':kg-3.0.0-asserted-20260912'
        command = ['docker', 'build', '--pull=false', '-f', str(app / ('Dockerfile.' + kind)), '-t', tag]
        command.append(str(app / 'backend') if kind == 'backend' else str(app))
        with (ROOT / 'evidence' / (kind + '_build.log')).open('x') as log:
            subprocess.run(command, check=True, stdout=log, stderr=subprocess.STDOUT)
    run('docker', 'network', 'create', NETWORK)
    run('docker', 'network', 'connect', NETWORK, 'eq_kg_3_0_0_asserted')
    backend = run('docker', 'run', '-d', '--name', BACKEND, '--network', NETWORK,
        '--restart', 'unless-stopped', '--memory', '4g', '--cpus', '4',
        '-e', 'SPARQL_ENDPOINT=http://eq_kg_3_0_0_asserted:8890/sparql',
        '-e', 'KG_RELEASE_MODE=asserted-only', 'empty-quarter-backend:kg-3.0.0-asserted-20260912')
    public = ROOT / 'publication'
    public.mkdir(exist_ok=True)
    args = ['docker', 'run', '-d', '--name', WEB, '--network', NETWORK,
        '--restart', 'unless-stopped', '--memory', '2g', '--cpus', '2', '-p', '127.0.0.1:18901:80',
        '-v', str(app / 'nginx.candidate.conf') + ':/etc/nginx/conf.d/default.conf:ro',
        '-v', str(public) + ':/release-public:ro']
    for directory in ('gallery', 'audio', 'tracks', 'twin-data', 'downloads'):
        source = Path('/data/empty-quarter/website/frontend/public') / directory
        if not source.is_dir():
            raise FileNotFoundError(source)
        args.extend(['-v', str(source) + ':/usr/share/nginx/html/' + directory + ':ro'])
    web = run(*args, 'empty-quarter-frontend:kg-3.0.0-asserted-20260912')
    run('docker', 'network', 'connect', '--alias', 'eqkg300assertedweb', 'viz_default', WEB)
    run('docker', 'exec', WEB, 'nginx', '-t')
    report = dict(version='3.0.0', release_mode='asserted-only', backend=backend, web=web,
        candidate_url='http://127.0.0.1:18901', production_entrypoint_changed=False)
    (ROOT / 'evidence/application_stage.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report), flush=True)

if __name__ == '__main__':
    if sys.argv[1:] == ['--detach']:
        with (ROOT / 'evidence/application_build_driver.log').open('x') as log:
            proc = subprocess.Popen([sys.executable, '-u', __file__], stdin=subprocess.DEVNULL,
                stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        print(json.dumps({'pid': proc.pid}))
    else:
        status = 1
        try:
            main()
            status = 0
        finally:
            (ROOT / 'evidence/application_build.exitcode').write_text(str(status) + '\n')
