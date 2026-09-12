#!/usr/bin/env python3
"""Audited controller-only stop after its outstanding SQL child has finished."""
import hashlib
import json
import os
from pathlib import Path
import signal
import time
from datetime import datetime, timezone

from materialize import dump_json

ROOT = Path('/data/empty-quarter-releases/kg-3.0.0-engine7-20260910')
PID = 673296
REPORT = ROOT / 'materialization-partitioned/materialization.json'
LOG = ROOT / 'evidence/materialization_driver_partitioned.log'
OUTPUT = ROOT / 'evidence/operator_checkpoint_httpguard.json'


def proc_state(pid):
    path = Path(f'/proc/{pid}/stat')
    if not path.exists():
        return None
    # Fields following the parenthesized process name start with field3(state).
    fields = path.read_text().rsplit(')', 1)[1].split()
    return {'state': fields[0], 'start_ticks': int(fields[19]), 'exit_status': int(fields[49])}


def main():
    if OUTPUT.exists():
        raise FileExistsError('Refusing to overwrite interruption evidence')
    command = Path(f'/proc/{PID}/cmdline').read_bytes().split(b'\0')
    if str(ROOT / 'entailment-code/materialize.py').encode() not in command:
        raise ValueError('PID is not the exact release controller')
    prior = json.loads(REPORT.read_text())
    if prior['status'] != 'running':
        raise ValueError('Controller report is not running')
    started = proc_state(PID)
    os.kill(PID, signal.SIGSTOP)
    deadline = time.monotonic() + 7200
    while proc_state(PID)['state'] not in ('T', 't'):
        time.sleep(0.05)
    children = [int(x) for x in Path(f'/proc/{PID}/task/{PID}/children').read_text().split()]
    while True:
        states = {str(pid): proc_state(pid) for pid in children}
        if all(state is None or state['state'] == 'Z' for state in states.values()):
            break
        if time.monotonic() > deadline:
            os.kill(PID, signal.SIGCONT)
            raise TimeoutError('SQL child did not finish; controller resumed unchanged')
        time.sleep(1)
    if any(state and state['exit_status'] != 0 for state in states.values()):
        os.kill(PID, signal.SIGCONT)
        raise ValueError('SQL child exited abnormally; controller resumed to record its own failure')
    os.kill(PID, signal.SIGKILL)
    while proc_state(PID) and proc_state(PID)['state'] != 'Z':
        time.sleep(0.05)
    record = dict(prior, status='operator_interrupted')
    record['operator_interruption'] = {
        'reason': 'Mandatory partial-HTTP-response guard; no database process terminated',
        'controller_pid': PID, 'controller_start_ticks': started['start_ticks'],
        'controller_terminated': True, 'all_update_children_completed': True,
        'sql_children': states, 'controller_pause_signal': 'SIGSTOP',
        'controller_termination_signal': 'SIGKILL after SQLchildren completed',
        'preserved_running_report_sha256': hashlib.sha256(REPORT.read_bytes()).hexdigest(),
        'preserved_batch_log_sha256': hashlib.sha256(LOG.read_bytes()).hexdigest(),
        'recorded_at': datetime.now(timezone.utc).isoformat(),
        'production_mutated': False}
    dump_json(OUTPUT, record)
    print(json.dumps(record['operator_interruption']), flush=True)


if __name__ == '__main__':
    main()
