"""Inference-specific mode checks must reject silently asserted materialized requests."""
import importlib.util
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts/release/kg'))
import mode_gates as gates


@pytest.fixture
def witness():
    return gates.source_witness(ROOT)


def payload(roles):
    return {'head': {'vars': ['role']}, 'results': {'bindings': [
        {'role': {'type': 'uri', 'value': role}} for role in roles]}}


def test_source_witness_is_independent_and_differential(witness):
    assert len(witness['roles']) == 6
    assert witness['asserted_class'] != witness['inferred_class']
    assert len(witness['sources']) == 3
    assert all(len(source['sha256']) == 64 for source in witness['sources'])
    assert gates.compare_witness(payload([]), witness, 'asserted') == []
    assert len(gates.compare_witness(payload(witness['roles']), witness, 'materialized')) == 6


@pytest.mark.parametrize('mutation', ['empty', 'extra', 'wrong_role', 'duplicate'])
def test_materialized_requires_exact_six_source_roles(witness, mutation):
    roles = witness['roles'][:]
    if mutation == 'empty':
        roles = []
    elif mutation == 'extra':
        roles.append('urn:unexpected-role')
    elif mutation == 'wrong_role':
        roles[0] = 'urn:unexpected-role'
    else:
        roles[0] = roles[1]
    with pytest.raises(gates.GateError):
        gates.compare_witness(payload(roles), witness, 'materialized')


def test_asserted_must_exclude_derived_types(witness):
    with pytest.raises(gates.GateError):
        gates.compare_witness(payload(witness['roles']), witness, 'asserted')


@pytest.mark.parametrize('broken', [None, 'api', 'direct'])
def test_driver_rejects_materialized_mode_ignored_despite_correct_metadata(tmp_path, monkeypatch, witness, broken):
    monkeypatch.setattr(gates, 'source_witness', lambda *args: witness)
    def request(url, timeout, payload=None, form=None):
        if url.endswith('/kg-release.json'):
            return {'version': gates.VERSION, 'graphs': gates.GRAPHS}
        transport = 'api' if payload is not None else 'direct'
        data = payload if payload is not None else dict(form)
        query = data['query']
        requested = data.get('mode', 'asserted')
        actual = requested if transport == 'api' else next((mode for mode, iri in gates.GRAPHS.items() if data.get('default-graph-uri') == iri), 'asserted')
        for mode, iri in gates.GRAPHS.items():
            if f'FROM <{iri}>' in query:
                actual = mode
        if transport == broken:
            actual = 'asserted'
        result = globals()['payload'](witness['roles'] if actual == 'materialized' else [])
        return {'kg_version': gates.VERSION, 'mode': requested, 'data': result} if transport == 'api' else result
    monkeypatch.setattr(gates, 'request_json', request)
    code = gates.main(['--base-url', 'https://candidate.invalid', '--output-dir', str(tmp_path)])
    result = json.loads((tmp_path / 'mode_gates.json').read_text())
    assert code == (1 if broken else 0)
    assert result['status'] == ('failed' if broken else 'passed')
    if not broken:
        assert len(result['checks']) == 9
    else:
        failed = result['checks'][-1]
        assert failed['transport'] == broken and failed['expected_rows'] == 6 and failed['rows'] == 0
