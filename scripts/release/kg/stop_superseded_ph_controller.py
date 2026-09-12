#!/usr/bin/env python3
"""Stop only the verified superseded controller at a SQL-child-free boundary."""
import hashlib
import json
import os
from pathlib import Path
import signal
import time
from datetime import datetime, timezone

ROOT = Path('/data/empty-quarter-releases/kg-3.0.0-engine7-20260910')
PID = 874295
OUTPUT = ROOT / 'evidence/operator_interruption_ph_reconciliation.json'
REPORT = ROOT / 'materialization-transaction-cap/materialization.json'
LOG = ROOT / 'evidence/materialization_driver_transaction_cap.log'


def state():
    path = Path('/proc') / str(PID) / 'stat'
    if not path.exists():
        return None
    fields = path.read_text().rsplit(')', 1)[1].split()
    return {'state': fields[0], 'start_ticks': int(fields[19]), 'exit_status': int(fields[49])}


def main():
    if OUTPUT.exists():
        raise FileExistsError(OUTPUT.name)
    command = (Path('/proc') / str(PID) / 'cmdline').read_bytes().split(b'\0')
    if (str(ROOT / 'entailment-code/materialize.py').encode() not in command
            or str(REPORT.parent).encode() not in command):
        raise ValueError('Target is not the exact superseded release controller')
    report = json.loads(REPORT.read_text())
    if report['status'] != 'running':
        raise ValueError('Historical controller is not running')
    original = state()
    deadline = time.monotonic() + 600
    while True:
        current = state()
        if current is None or current['state'] == 'Z':
            raise ValueError('Controller exited before requested boundary interruption')
        if current['start_ticks'] != original['start_ticks']:
            raise ValueError('Controller PID identity changed')
        children = (Path('/proc') / str(PID) / 'task' / str(PID) / 'children').read_text().split()
        if not children:
            os.kill(PID, signal.SIGINT)
            break
        if time.monotonic() > deadline:
            raise TimeoutError('No SQL-child-free boundary reached; no signal sent')
        time.sleep(0.05)
    deadline = time.monotonic() + 60
    while state() is not None and state()['state'] != 'Z':
        if time.monotonic() > deadline:
            raise TimeoutError('SIGINT sent; controller exit requires operator inspection')
        time.sleep(0.05)
    record = {
        'status': 'operator_interrupted',
        'reason': 'New laboratory confirmation requires corrected Trip 4 pH specimen mappings and a fresh full rebuild',
        'controller_pid': PID, 'controller_start_ticks': original['start_ticks'],
        'signal': 'SIGINT', 'sql_children_at_signal': [],
        'recorded_at': datetime.now(timezone.utc).isoformat(),
        'controller_exit': state(),
        'preserved_materialization_report_sha256': hashlib.sha256(REPORT.read_bytes()).hexdigest(),
        'preserved_driver_log_sha256': hashlib.sha256(LOG.read_bytes()).hexdigest(),
        'fixed_point_claimed': False, 'graphs_cleared': False, 'production_mutated': False,
    }
    with OUTPUT.open('x') as handle:
        json.dump(record, handle, indent=2, sort_keys=True)
        handle.write('\n')
    print(json.dumps(record), flush=True)


if __name__ == '__main__':
    main()
