#!/usr/bin/env python3
"""Replace only the private candidate web image, retaining its old container."""
from pathlib import Path
import subprocess

ROOT = Path('/data/empty-quarter-releases/kg-3.0.0-engine7-20260910')
IMAGE = 'sha256:b50e8c778d3daca3dfb7cbbfe4283aabea9e5459320eaa604e59046fec718423'
PREVIOUS = 'eq_kg_3_0_0_web_before_numericsort'
EXPECTED_ID = '8e27a44471a05f1a80f7c50998e4d4b23a5f2dae5a8ffbc5602f72f35cf04ef7'


def run(*args):
    subprocess.run(args, check=True)


actual = subprocess.check_output(['docker', 'inspect', 'eq_kg_3_0_0_web', '--format', '{{.Id}}'], text=True).strip()
if actual != EXPECTED_ID:
    raise RuntimeError('candidate web changed; inspect before replacement')
if subprocess.run(['docker', 'inspect', PREVIOUS], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
    raise RuntimeError('previous candidate name already exists; do not overwrite')
run('docker', 'image', 'inspect', IMAGE, '--format', '{{.Id}}')
run('docker', 'stop', 'eq_kg_3_0_0_web')
run('docker', 'rename', 'eq_kg_3_0_0_web', PREVIOUS)
run('docker', 'network', 'disconnect', 'viz_default', PREVIOUS)
run('docker', 'network', 'disconnect', 'eq_kg_3_0_0_net', PREVIOUS)
args = ['docker', 'run', '-d', '--name', 'eq_kg_3_0_0_web',
        '--network', 'eq_kg_3_0_0_net', '--restart', 'unless-stopped',
        '--memory', '2g', '--cpus', '2', '-p', '127.0.0.1:18897:80',
        '-v', f'{ROOT}/app/nginx.candidate.conf:/etc/nginx/conf.d/default.conf:ro',
        '-v', f'{ROOT}/publication:/release-public:ro']
for directory in ('gallery', 'audio', 'tracks', 'twin-data', 'downloads'):
    args += ['-v', f'/data/empty-quarter/website/frontend/public/{directory}:/usr/share/nginx/html/{directory}:ro']
run(*args, IMAGE)
run('docker', 'network', 'connect', '--alias', 'eqkg300web', 'viz_default', 'eq_kg_3_0_0_web')
run('docker', 'exec', 'eq_kg_3_0_0_web', 'nginx', '-t')
