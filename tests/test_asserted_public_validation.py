"""Public publication reuses all candidate scientific gates without relaxing them."""
import copy
import io
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts/release/kg'))
import asserted_cutover
import publish_asserted_public_validation as public
from test_asserted_cutover import bundle as candidate_bundle


@pytest.fixture
def bundle(candidate_bundle):
    result = copy.deepcopy(candidate_bundle)
    for name, report in result['reports'].items():
        report['base_url'] = public.PUBLIC_ORIGIN
        if name == 'protocol':
            report['endpoint'] = public.PUBLIC_ORIGIN + '/sparql'
    result['reports']['query']['sparql_url'] = public.PUBLIC_ORIGIN + '/sparql'
    for row in result['reports']['downloads']['files']:
        row['url'] = row['url'].replace(asserted_cutover.BASE_URL, public.PUBLIC_ORIGIN)
    return result


def test_public_contract_passes_without_modifying_candidate(bundle):
    candidate_url = asserted_cutover.BASE_URL
    assert public.validate_public_bundle(**bundle)['counts'] == {'asserted': 45706977}
    assert asserted_cutover.BASE_URL == candidate_url == 'http://127.0.0.1:18901'
    with pytest.raises(ValueError, match='different candidate'):
        asserted_cutover.check_gates(**bundle)


@pytest.mark.parametrize('name', list(asserted_cutover.REPORTS))
@pytest.mark.parametrize('origin', ['http://127.0.0.1:18901', 'http://rubalkhali.science',
                                   'https://rubalkhali.science.evil.example'])
def test_every_suite_must_identify_exact_public_origin(bundle, name, origin):
    key = 'endpoint' if name == 'protocol' else 'base_url'
    bundle['reports'][name][key] = origin + ('/sparql' if name == 'protocol' else '')
    with pytest.raises(ValueError):
        public.validate_public_bundle(**bundle)
    assert asserted_cutover.BASE_URL == 'http://127.0.0.1:18901'


def test_private_direct_query_transport_rejected(bundle):
    bundle['reports']['query']['sparql_url'] = 'http://127.0.0.1:18901/sparql'
    with pytest.raises(ValueError, match='different direct endpoint'):
        public.validate_public_bundle(**bundle)


@pytest.mark.parametrize('name', ['query', 'protocol', 'isolation', 'browser'])
def test_missing_substantive_gate_still_rejected(bundle, name):
    bundle['reports'][name]['checks'].pop()
    with pytest.raises(ValueError):
        public.validate_public_bundle(**bundle)


def test_download_must_be_fully_validated_and_public(bundle):
    bundle['reports']['downloads']['files'][0]['url'] = 'http://127.0.0.1:18901/file'
    with pytest.raises(ValueError, match='download'):
        public.validate_public_bundle(**bundle)


def test_sanitized_proof_excludes_private_fields(bundle):
    reports = bundle['reports']
    for report in reports.values():
        report['private_path'] = '/private/operator/secrets'
        for row in report.get('checks', []):
            row['query'] = 'secret query /private/operator/secrets'
            row['request_parameters'] = {'password': 'secret-token'}
            row['response_file'] = '/private/operator/secrets'
    reports['downloads']['software'] = {'python': '/private/operator/python', 'raptor': '2.0.16',
                                       'validator_sha256': 'a' * 64, 'argv': ['secret-token']}
    raw = {name: json.dumps(value).encode() for name, value in reports.items()}
    proof = public.sanitized_proof(reports, raw, bundle['manifest_bytes'], {'asserted': 45706977, 'inferred': 0, 'materialized': 0})
    output = json.dumps(proof)
    assert 'secret-token' not in output
    assert '/private/' not in output
    assert 'response_file' not in output
    assert len(proof['query_result_gates']) == 26
    assert len(proof['protocol_gates']) == 14
    assert len(proof['browser_gates']) == 9
    assert len(proof['auxiliary_download_gates']) == 6
    assert proof['evidence_sha256'] == {name: asserted_cutover.sha(value) for name, value in raw.items()}
    assert proof['public_acceptance_passed'] is True


class Response(io.BytesIO):
    status = 200
    headers = {}

    def __init__(self, value, url):
        super().__init__(value)
        self.url = url

    def geturl(self):
        return self.url


@pytest.fixture
def staged(tmp_path, monkeypatch, bundle):
    root = tmp_path / 'release'
    gates = root / 'evidence/public'
    for name, relative in asserted_cutover.REPORTS.items():
        path = gates / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(bundle['reports'][name]))
    publication = root / 'publication/kg/3.0.0'
    publication.mkdir(parents=True)
    (publication / 'manifest.json').write_bytes(bundle['manifest_bytes'])
    (publication / 'validation.json').write_bytes(b'immutable candidate record')
    for name, value in bundle['auxiliary_bytes'].items():
        (publication / name).write_bytes(value)
    (root / 'evidence/asserted_load').mkdir()
    (root / 'evidence/asserted_load/report.json').write_bytes(bundle['private_loader_bytes'])
    (root / 'inputs/scientific').mkdir(parents=True)
    (root / 'inputs/scientific/manifest.json').write_bytes(bundle['auxiliary_bytes']['input-modules-manifest.json'])
    calls = []
    def opened(url, data=None, **kwargs):
        calls.append(url)
        if url.endswith('/manifest.json'):
            return Response(bundle['manifest_bytes'], url)
        from urllib.parse import parse_qs
        query = parse_qs(data.decode())['query'][0]
        count = 45706977 if '/asserted/3.0.0' in query else 0
        return Response(json.dumps({'results': {'bindings': [{'n': {'value': str(count)}}]}}).encode(), url)
    monkeypatch.setattr(public, 'urlopen', opened)
    return root, gates, publication, calls


def test_publish_requires_live_manifest_and_all_three_counts(staged):
    root, gates, publication, calls = staged
    result = public.publish(root, gates)
    assert result['public_acceptance_passed'] is True
    assert calls == [public.PUBLIC_ORIGIN + '/downloads/kg/3.0.0/manifest.json'] + [public.PUBLIC_ORIGIN + '/sparql'] * 3
    proof = json.loads((publication / public.OUTPUT_NAME).read_bytes())
    assert proof['live_graph_counts'] == {'asserted': 45706977, 'inferred': 0, 'materialized': 0}
    assert (publication / 'validation.json').read_bytes() == b'immutable candidate record'
    first = (publication / public.OUTPUT_NAME).read_bytes()
    with pytest.raises(FileExistsError):
        public.publish(root, gates)
    assert (publication / public.OUTPUT_NAME).read_bytes() == first


def test_failed_public_suite_writes_nothing(staged):
    root, gates, publication, calls = staged
    path = gates / asserted_cutover.REPORTS['query']
    report = json.loads(path.read_bytes())
    report['checks'][0]['status'] = 'failed'
    path.write_text(json.dumps(report))
    with pytest.raises(ValueError):
        public.publish(root, gates)
    assert calls == []
    assert not (publication / public.OUTPUT_NAME).exists()


@pytest.mark.parametrize('problem', ['different', 'trailing', 'redirect', 'partial'])
def test_bad_live_manifest_never_publishes(staged, monkeypatch, problem):
    root, gates, publication, _ = staged
    content = (publication / 'manifest.json').read_bytes()
    def opened(url, **kwargs):
        response = Response(content, url)
        if problem == 'different':
            response = Response(b'other release', url)
        elif problem == 'trailing':
            response = Response(content + b'x', url)
        elif problem == 'redirect':
            response.url = 'http://rubalkhali.science/downloads/kg/3.0.0/manifest.json'
        else:
            response.headers = {'Content-Range': 'bytes 0-99/200'}
        return response
    monkeypatch.setattr(public, 'urlopen', opened)
    with pytest.raises(ValueError):
        public.publish(root, gates)
    assert not (publication / public.OUTPUT_NAME).exists()


def test_nonpublic_fetch_rejected_without_request(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('Invalid origin must not trigger a request')
    monkeypatch.setattr(public, 'urlopen', forbidden)
    with pytest.raises(ValueError, match='public HTTPS'):
        public.public_response('https://rubalkhali.science.evil.example/manifest.json')
