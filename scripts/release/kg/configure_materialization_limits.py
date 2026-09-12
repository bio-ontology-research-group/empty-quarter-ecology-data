#!/usr/bin/env python3
"""Apply the approved limits only to the isolated 3.0.0 candidate database."""
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

from materialize import Endpoint, dump_json

ROOT = Path('/data/empty-quarter-releases/kg-3.0.0-engine7-20260910')
CONFIG = ROOT / 'database/virtuoso.ini'
BACKUP = ROOT / 'evidence/virtuoso.ini.before-positive-materialization-limit'
REPORT = ROOT / 'evidence/materialization_limits_positive.json'
CONTAINER = 'eq_kg_3_0_0_engine7'


def main():
    if BACKUP.exists() or REPORT.exists():
        raise FileExistsError('Refusing to overwrite configuration evidence')
    original = subprocess.run(['docker', 'exec', '-u', '0', CONTAINER,
                               'cat', '/database/virtuoso.ini'], check=True,
                              capture_output=True, text=True).stdout
    match = re.search(r'(?ms)^\[SPARQL\].*?(?=^\[|\Z)', original)
    if not match:
        raise ValueError('Missing unique SPARQL section')
    section = match.group()
    settings = {'MaxConstructTriples': 100000000, 'MaxMemInUse': 17179869184}
    previous = {}
    for key, value in settings.items():
        pattern = rf'(?m)^({key}\s*=\s*)(\d+)([^\n]*)$'
        rows = list(re.finditer(pattern, section))
        if len(rows) > 1:
            raise ValueError('Setting duplicated: ' + key)
        previous[key] = int(rows[0][2]) if rows else None
        if rows:
            section = re.sub(pattern, lambda row: row[1] + str(value) + row[3], section)
        else:
            section = section.rstrip() + f'\n{key} = {value}\n\n'
    revised = original[:match.start()] + section + original[match.end():]
    command = json.loads((ROOT / 'entailment-code/staging_sql_command.json').read_text())
    Endpoint('http://127.0.0.1:18896/sparql', command, 7200).sql('CHECKPOINT;')
    with BACKUP.open('x') as handle:
        BACKUP.chmod(0o600)
        handle.write(original)
    subprocess.run(['docker', 'exec', '-i', '-u', '0', CONTAINER,
                    'tee', '/database/virtuoso.ini'], input=revised, text=True,
                   stdout=subprocess.DEVNULL, check=True)
    record = {'container': CONTAINER, 'previous': previous, 'current': settings,
              'before_sha256': hashlib.sha256(original.encode()).hexdigest(),
              'after_sha256': hashlib.sha256(revised.encode()).hexdigest(),
              'production_mutated': False}
    dump_json(REPORT, record)
    subprocess.run(['docker', 'restart', CONTAINER], check=True)
    print(json.dumps(record), flush=True)


if __name__ == '__main__':
    main()
