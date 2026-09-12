#!/usr/bin/env python3
"""Apply the approved bounded transaction-image limit to the release candidate."""
import hashlib
import json
from pathlib import Path
import re
import subprocess

from materialize import Endpoint, dump_json

ROOT = Path('/data/empty-quarter-releases/kg-3.0.0-engine7-20260910')
CONTAINER = 'eq_kg_3_0_0_engine7'
LIMIT = 250000000
BACKUP = ROOT / 'evidence/virtuoso.ini.before-transaction-image-limit'
REPORT = ROOT / 'evidence/transaction_image_configuration.json'
RUNTIME = ROOT / 'evidence/transaction_image_runtime.log'


def runtime_value(endpoint):
    output = endpoint.sql("SELECT sys_stat('txn_after_image_limit') AS txn_limit;")
    values = re.findall(r'^\s*(\d+)\s*$', output, re.M)
    if len(values) != 1:
        raise ValueError('Cannot verify exactly one transaction-image runtime value')
    return int(values[0]), output


def main():
    if any(path.exists() for path in (BACKUP, REPORT, RUNTIME)):
        raise FileExistsError('Refusing to overwrite transaction-limit evidence')
    command = json.loads((ROOT / 'entailment-code/staging_sql_command.json').read_text())
    endpoint = Endpoint('http://127.0.0.1:18896/sparql', command, 7200)
    previous_runtime, before_log = runtime_value(endpoint)
    if previous_runtime != 50000000:
        raise ValueError('Unexpected prior runtime transaction-image limit')
    counts = {kind: endpoint.count('https://rubalkhali.science/graph/' + kind + '/3.0.0')
              for kind in ('asserted', 'inferred')}
    if counts != {'asserted': 45706821, 'inferred': 87678125}:
        raise ValueError('Frozen graph counts do not match the preserved failed-run boundary')
    original = subprocess.run(['docker', 'exec', '-u', '0', CONTAINER,
                               'cat', '/database/virtuoso.ini'], check=True,
                              capture_output=True, text=True).stdout
    sections = list(re.finditer(r'(?ms)^\[Parameters\].*?(?=^\[|\Z)', original))
    if len(sections) != 1:
        raise ValueError('Expected one Parameters configuration section')
    match = sections[0]
    section = match.group()
    pattern = r'(?m)^(TransactionAfterImageLimit\s*=\s*)(\d+)([^\n]*)$'
    rows = list(re.finditer(pattern, section))
    if len(rows) > 1:
        raise ValueError('Duplicate TransactionAfterImageLimit settings')
    previous_config = int(rows[0][2]) if rows else None
    if rows:
        section = re.sub(pattern, lambda row: row[1] + str(LIMIT) + row[3], section)
    else:
        section = section.rstrip() + '\nTransactionAfterImageLimit = 250000000\n\n'
    revised = original[:match.start()] + section + original[match.end():]
    with BACKUP.open('x') as handle:
        BACKUP.chmod(0o600)
        handle.write(original)
    subprocess.run(['docker', 'exec', '-i', '-u', '0', CONTAINER,
                    'tee', '/database/virtuoso.ini'], input=revised, text=True,
                   stdout=subprocess.DEVNULL, check=True)
    update_log = endpoint.sql("SELECT __dbf_set('txn_after_image_limit', 250000000);")
    current_runtime, after_log = runtime_value(endpoint)
    if current_runtime != LIMIT:
        raise ValueError('Runtime transaction-image limit did not change as requested')
    actual = subprocess.run(['docker', 'exec', '-u', '0', CONTAINER,
                             'cat', '/database/virtuoso.ini'], check=True,
                            capture_output=True, text=True).stdout
    if actual != revised:
        raise ValueError('Configuration readback mismatch')
    with RUNTIME.open('x') as handle:
        handle.write(before_log + update_log + after_log)
    record = {
        'container': CONTAINER, 'setting': 'Parameters.TransactionAfterImageLimit',
        'runtime_setting': 'txn_after_image_limit', 'previous_config': previous_config,
        'previous_runtime': previous_runtime, 'current_runtime': current_runtime,
        'frozen_counts_before_change': counts,
        'before_sha256': hashlib.sha256(original.encode()).hexdigest(),
        'after_sha256': hashlib.sha256(revised.encode()).hexdigest(),
        'runtime_evidence_sha256': hashlib.sha256(RUNTIME.read_bytes()).hexdigest(),
        'failure_report_sha256': hashlib.sha256((ROOT / 'materialization-guarded/materialization.json').read_bytes()).hexdigest(),
        'generator_sha256': hashlib.sha256((ROOT / 'entailment-code/materialize.py').read_bytes()).hexdigest(),
        'batch_size': 500000, 'transaction_logging_changed': False,
        'restart_performed': False, 'production_mutated': False,
        'sources': [
            'https://docs.openlinksw.com/virtuoso/virtuosotipsandtrickssparulupdatestrl/',
            'https://docs.openlinksw.com/virtuoso/ch-server/',
            'https://raw.githubusercontent.com/openlink/virtuoso-opensource/v7.2.17/libsrc/Wi/log.c',
            'https://raw.githubusercontent.com/openlink/virtuoso-opensource/v7.2.17/libsrc/Wi/srvstat.c'],
    }
    dump_json(REPORT, record)
    print(json.dumps(record), flush=True)


if __name__ == '__main__':
    main()
