#!/usr/bin/env python3
"""Persist only the approved RDF hash-join flag in the isolated candidate."""
import hashlib
from pathlib import Path
import re
import subprocess
from materialize import dump_json

ROOT = Path('/data/empty-quarter-releases/kg-3.0.0-engine7-20260910')
CONTAINER = 'eq_kg_3_0_0_engine7'
backup = ROOT / 'evidence/virtuoso.ini.before-hash-join-rollback'
report = ROOT / 'evidence/hash_join_configuration_rollback.json'
if backup.exists() or report.exists():
    raise FileExistsError('Refusing to overwrite configuration evidence')
original = subprocess.run(['docker', 'exec', '-u', '0', CONTAINER, 'cat', '/database/virtuoso.ini'],
                          check=True, text=True, capture_output=True).stdout
sections = list(re.finditer(r'(?ms)^\[Flags\].*?(?=^\[|\Z)', original))
if len(sections) > 1:
    raise ValueError('Duplicate Flags sections')
if sections:
    match = sections[0]
    section = match.group()
    pattern = r'(?m)^hash_join_enable\s*=\s*\d+[^\n]*$'
    matches = list(re.finditer(pattern, section))
    if len(matches) > 1:
        raise ValueError('Duplicate hash join settings')
    section = re.sub(pattern, 'hash_join_enable = 1', section) if matches else section.rstrip() + '\nhash_join_enable = 1\n\n'
    revised = original[:match.start()] + section + original[match.end():]
else:
    revised = original.rstrip() + '\n\n[Flags]\nhash_join_enable = 1\n'
with backup.open('x') as handle:
    backup.chmod(0o600)
    handle.write(original)
subprocess.run(['docker', 'exec', '-i', '-u', '0', CONTAINER, 'tee', '/database/virtuoso.ini'],
               input=revised, text=True, stdout=subprocess.DEVNULL, check=True)
record = {'setting': 'Flags.hash_join_enable', 'value': 1, 'container': CONTAINER,
          'before_sha256': hashlib.sha256(original.encode()).hexdigest(),
          'after_sha256': hashlib.sha256(revised.encode()).hexdigest(),
          'restart_performed': False, 'production_mutated': False}
dump_json(report, record)
print(record)
