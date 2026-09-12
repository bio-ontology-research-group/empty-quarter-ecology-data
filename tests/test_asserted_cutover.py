"""Offline fail-closed contracts; no Docker, production file or network access."""
import copy
import io
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts/release/kg'))
import asserted_cutover as cutover


def encoded(value):
    return json.dumps(value).encode()


@pytest.fixture
def bundle():
    rows = [dict(file=f'module-{i}.ttl', sha256=f'{i:064x}', load_graph=cutover.GRAPH) for i in range(16)]
    rows[0].update(file='rubalkhali_sites.owl')
    rows[1].update(file='rubalkhali_ph_eq_ph_shared_v1_0_1.ttl', sha256=cutover.PH_SHA256)
    modules = encoded(dict(version='3.0.0', module_count=16, records=rows))
    loader = encoded(dict(version='3.0.0', passed=True, module_count=16, graph=cutover.GRAPH,
                          triples=cutover.COUNT, input_manifest_sha256=cutover.sha(modules)))
    auxiliary = {
        'input-modules-manifest.json': modules,
        'asserted-loader-report.json': loader,
        'site-import-adaptations.json': encoded([dict(typed_point_whitespace_changes=70,
            coordinate_digits_changed=False, original_source_preserved=True, source_sha256=rows[0]['sha256'])]),
        'native-export-fixture.json': encoded(dict(passed=True, triples=6, binary64_preserved=True,
            blank_nodes_unicode_language_preserved=True, wkt_datatype_preserved=True)),
        'prepare_wkt_import.py': b'# source-preserving adapter fixture\n',
        'source-rebuild-verification.json': encoded(dict(passed=True, mode='--all', checks=[
            dict(file=row['file'], sha256=row['sha256'], expected_sha256=row['sha256'], passed=True)
            for row in rows])),
    }
    files = [dict(name=name, url='/downloads/kg/3.0.0/' + name, bytes=10, sha256='a' * 64)
             for name in sorted(cutover.FILE_NAMES)]
    next(row for row in files if row['name'].endswith('.nq.gz')).update(
        graph=cutover.GRAPH, triples=cutover.COUNT, uncompressed_sha256='b' * 64)
    manifest = dict(version='3.0.0', release_mode='asserted-only', graphs={'asserted': cutover.GRAPH},
        counts={'asserted': cutover.COUNT}, available_modes=['asserted'], default_graph=cutover.GRAPH,
        query_time_inference=False, files=files,
        coordinate_import=dict(method='fresh-source-preserving-import', files=[
            dict(name=name, url='/downloads/kg/3.0.0/' + name, bytes=len(raw), sha256=cutover.sha(raw))
            for name, raw in auxiliary.items()]),
        evidence=dict(input_manifest_sha256=cutover.sha(modules), private_loader_report_sha256=cutover.sha(loader),
            source_rebuild_report_sha256=cutover.sha(auxiliary['source-rebuild-verification.json']),
            native_export_fixture_sha256=cutover.sha(auxiliary['native-export-fixture.json'])))
    variants = ('direct_server_default', 'direct_asserted', 'api_asserted',
                'direct_explicit_from', 'api_explicit_from_asserted')
    query_rows = [dict(case=case, variant=variant, status='passed', rows=count, expected_rows=count,
                       expected_sha256='c' * 64, numeric_order_checked=True)
                  for case, count in cutover.CASE_ROWS.items()
                  for variant in (('api_rank_genus_limit20',) if case == 'taxonomy_api_ERR16061083_top20' else variants)]
    protocol = [dict(name=name, passed=True, http_status=200, complete_response=True)
                for name in cutover.PROTOCOL_CHECKS]
    next(row for row in protocol if row['name'] == 'anonymous_update_denied')['http_status'] = 400
    protocol.extend(dict(name=name, passed=True, http_status=200, complete_response=True, triples=6,
        content_type=mime, graph_isomorphic=True, literal_datatypes_preserved=True)
        for name, mime in cutover.GRAPH_FORMAT_CHECKS.items())
    protocol.extend(dict(name=name, passed=True, http_status=200, complete_response=True, rows=6,
        content_type=mime, result_multiset_preserved=True, literal_datatypes_preserved=True)
        for name, mime in cutover.SELECT_LITERAL_CHECKS.items())
    reports = {
        'query': dict(version='3.0.0', release_mode='asserted-only', status='passed', checks=query_rows),
        'protocol': dict(version='3.0.0', passed=True, endpoint=cutover.BASE_URL + '/sparql', checks=protocol,
            graph_fixture=dict(sha256=cutover.GRAPH_FIXTURE_SHA256, triples=6, graph='urn:eq:release-test:export')),
        'isolation': dict(version='3.0.0', release_mode='asserted-only', passed=True, asserted_triples=cutover.COUNT,
            ph_source_sha256=cutover.PH_SHA256, checks=[dict(name=name, passed=True) for name in cutover.ISOLATION_CHECKS]),
        'downloads': dict(version='3.0.0', passed=True, manifest_sha256=cutover.sha(encoded(manifest)),
            files=[dict(row, url=cutover.BASE_URL + row['url'], passed=True,
                        rdf_syntax_checked=row['name'].endswith('.nq.gz')) for row in files],
            auxiliary_files=[dict(row, passed=True, full_read=True, http_status=200)
                             for row in manifest['coordinate_import']['files']]),
        'browser': dict(status='passed', release_mode='asserted-only',
            checks=[dict(name=name, status='passed', rows=count if count is not None else 1,
                         numeric_order_checked=True) for name, count in cutover.BROWSER_ROWS.items()],
            downloads=[dict(row, bounded_range_status=206) for row in files]),
    }
    for report in reports.values():
        report['base_url'] = cutover.BASE_URL
    return dict(reports=reports, manifest_bytes=encoded(manifest), auxiliary_bytes=auxiliary,
                private_loader_bytes=loader)


def test_complete_asserted_evidence_passes(bundle):
    assert cutover.check_gates(**bundle)['counts'] == {'asserted': 45706977}


@pytest.mark.parametrize('report', ['query', 'protocol', 'isolation', 'browser'])
def test_missing_or_duplicate_gate_rejected(bundle, report):
    rows = bundle['reports'][report]['checks']
    rows[-1] = copy.deepcopy(rows[0])
    with pytest.raises(ValueError):
        cutover.check_gates(**bundle)


@pytest.mark.parametrize('report', list(cutover.REPORTS))
def test_wrong_candidate_rejected(bundle, report):
    field = 'endpoint' if report == 'protocol' else 'base_url'
    bundle['reports'][report][field] = 'http://127.0.0.1:18897'
    with pytest.raises(ValueError, match='different candidate'):
        cutover.check_gates(**bundle)


@pytest.mark.parametrize('change', ['query_count', 'taxonomy_order', 'failed_protocol', 'rdf_terms',
    'isolation_failed', 'browser_count', 'browser_mode', 'download_count', 'download_hash',
    'download_rdf', 'auxiliary_missing', 'auxiliary_partial', 'auxiliary_changed', 'private_loader_changed'])
def test_invalid_report_content_rejected(bundle, change):
    reports = bundle['reports']
    if change == 'query_count':
        reports['query']['checks'][0]['rows'] = 0
    elif change == 'taxonomy_order':
        next(r for r in reports['query']['checks'] if r['case'] == 'taxonomy_ERR16061083_genus')['numeric_order_checked'] = False
    elif change == 'failed_protocol':
        reports['protocol']['checks'][0]['passed'] = False
    elif change == 'rdf_terms':
        next(r for r in reports['protocol']['checks'] if r['name'] in cutover.GRAPH_FORMAT_CHECKS)['literal_datatypes_preserved'] = False
    elif change == 'isolation_failed':
        reports['isolation']['checks'][0]['passed'] = False
    elif change == 'browser_count':
        reports['browser']['checks'][0]['rows'] = 0
    elif change == 'browser_mode':
        reports['browser']['release_mode'] = 'materialized'
    elif change == 'download_count':
        reports['downloads']['files'].pop()
    elif change == 'download_hash':
        reports['downloads']['manifest_sha256'] = '0' * 64
    elif change == 'download_rdf':
        next(r for r in reports['downloads']['files'] if r['name'].endswith('.nq.gz'))['rdf_syntax_checked'] = False
    elif change == 'auxiliary_missing':
        reports['downloads']['auxiliary_files'].pop()
    elif change == 'auxiliary_partial':
        reports['downloads']['auxiliary_files'][0]['full_read'] = False
    elif change == 'auxiliary_changed':
        bundle['auxiliary_bytes']['prepare_wkt_import.py'] += b'changed'
    else:
        bundle['private_loader_bytes'] += b' '
    with pytest.raises(ValueError):
        cutover.check_gates(**bundle)


def rebind(bundle, name, value):
    """Alter a proof with all hashes refreshed: semantic gates must still fail."""
    raw = encoded(value)
    bundle['auxiliary_bytes'][name] = raw
    manifest = json.loads(bundle['manifest_bytes'])
    for container in (manifest['coordinate_import']['files'], bundle['reports']['downloads']['auxiliary_files']):
        next(row for row in container if row['name'] == name).update(bytes=len(raw), sha256=cutover.sha(raw))
    bundle['manifest_bytes'] = encoded(manifest)
    bundle['reports']['downloads']['manifest_sha256'] = cutover.sha(bundle['manifest_bytes'])


@pytest.mark.parametrize('field,value', [('typed_point_whitespace_changes', 69),
    ('coordinate_digits_changed', True), ('original_source_preserved', False), ('source_sha256', 'f' * 64)])
def test_source_preserving_adaptation_required_even_with_matching_hashes(bundle, field, value):
    name = 'site-import-adaptations.json'
    content = json.loads(bundle['auxiliary_bytes'][name])
    content[0][field] = value
    rebind(bundle, name, content)
    with pytest.raises(ValueError, match='seventy-point'):
        cutover.check_gates(**bundle)


@pytest.mark.parametrize('change', ['count', 'mode', 'inference', 'materialized_graph'])
def test_asserted_manifest_contract_is_exact(bundle, change):
    manifest = json.loads(bundle['manifest_bytes'])
    if change == 'count':
        manifest['counts']['asserted'] -= 1
    elif change == 'mode':
        manifest['release_mode'] = 'materialized'
    elif change == 'inference':
        manifest['query_time_inference'] = True
    else:
        manifest['graphs']['materialized'] = 'urn:unreleased'
    bundle['manifest_bytes'] = encoded(manifest)
    with pytest.raises(ValueError, match='asserted-only manifest'):
        cutover.check_gates(**bundle)


class Response(io.BytesIO):
    status = 200
    headers = {}


@pytest.mark.parametrize('counts,passes', [([cutover.COUNT, 0, 0], True),
    ([cutover.COUNT, 1, 0], False), ([cutover.COUNT, 0, 1], False), ([cutover.COUNT - 1, 0, 0], False)])
def test_live_counts_include_absent_unreleased_graphs(monkeypatch, counts, passes):
    responses = iter(counts)
    monkeypatch.setattr(cutover, 'urlopen', lambda *a, **k: Response(encoded(
        {'results': {'bindings': [{'n': {'value': str(next(responses))}}]}})))
    if passes:
        assert cutover.verify_live_counts() == {'asserted': cutover.COUNT, 'inferred': 0, 'materialized': 0}
    else:
        with pytest.raises(ValueError, match='graph contents changed'):
            cutover.verify_live_counts()


@pytest.fixture
def activation(tmp_path, monkeypatch):
    root = tmp_path / 'release'
    (root / 'evidence').mkdir(parents=True)
    (root / 'publication/kg/3.0.0').mkdir(parents=True)
    config = tmp_path / 'nginx.conf'
    config.write_bytes(b'original')
    monkeypatch.setattr(cutover, 'ROOT', root)
    monkeypatch.setattr(cutover, 'CONFIG', config)
    monkeypatch.setattr(cutover, 'BASELINE_SHA256', cutover.sha(b'original'))
    monkeypatch.setattr(cutover, 'proposed_config', lambda: b'asserted candidate')
    monkeypatch.setattr(cutover, 'load_bundle', lambda _: ({}, b'manifest', {
        'manifest_sha256': cutover.sha(b'manifest'),
        'gates': {name: {'path': '/private/operator/path/' + name, 'sha256': 'd' * 64}
                  for name in cutover.REPORTS}}))
    monkeypatch.setattr(cutover, 'verify_live_counts', lambda: {'asserted': cutover.COUNT, 'inferred': 0, 'materialized': 0})
    monkeypatch.setattr(cutover, 'urlopen', lambda *a, **k: Response(b'manifest'))
    monkeypatch.setattr(cutover, 'write_config', config.write_bytes)
    calls = []
    def run(*args):
        calls.append(args)
        if args[:3] == ('docker', 'inspect', 'viz_web_1'):
            return cutover.OLD_WEB_ID
        if args[:3] == ('docker', 'inspect', cutover.CANDIDATE):
            return json.dumps([dict(Id='candidate-id', Image='image-id', State={'Running': True},
                NetworkSettings={'Networks': {'viz_default': {'Aliases': [cutover.ALIAS]}}})])
        return ''
    monkeypatch.setattr(cutover, 'run', run)
    return root, config, calls


def test_activation_never_claims_public_acceptance(activation):
    root, config, _ = activation
    record = cutover.activate(root / 'evidence/candidate')
    assert config.read_bytes() == b'asserted candidate'
    assert record['public_acceptance_passed'] is False
    assert record['status'] == 'activated; public acceptance gates pending'
    public_path = root / 'publication/kg/3.0.0/validation.json'
    public_bytes = public_path.read_bytes()
    public = json.loads(public_bytes)
    assert public['public_acceptance_passed'] is False
    assert public['candidate_acceptance_passed'] is True
    assert public['manifest_sha256'] == cutover.sha(b'manifest')
    assert public['check_counts']['queries'] == 26
    assert b'/private/' not in public_bytes
    assert b'18901' not in public_bytes
    assert cutover.rollback()['status'] == 'restored'
    assert config.read_bytes() == b'original'
    assert public_path.read_bytes() == public_bytes


def test_existing_public_validation_never_overwritten(activation):
    root, config, _ = activation
    public_path = root / 'publication/kg/3.0.0/validation.json'
    public_path.write_bytes(b'prior immutable record')
    with pytest.raises(FileExistsError):
        cutover.activate(root / 'evidence/candidate')
    assert config.read_bytes() == b'original'
    assert public_path.read_bytes() == b'prior immutable record'


def test_failed_reload_restores_configuration(activation, monkeypatch):
    root, config, _ = activation
    calls = []
    def reload():
        calls.append(config.read_bytes())
        if len(calls) == 1:
            raise RuntimeError('nginx reload failed')
    monkeypatch.setattr(cutover, 'reload_nginx', reload)
    with pytest.raises(RuntimeError, match='reload failed'):
        cutover.activate(root / 'evidence/candidate')
    assert calls == [b'asserted candidate', b'original']
    assert config.read_bytes() == b'original'
    record = json.loads((root / 'evidence/asserted_cutover/activation.json').read_bytes())
    assert record['status'] == 'automatically rolled back after activation error'
    assert record['public_acceptance_passed'] is False


def test_failed_gate_never_writes_production(activation, monkeypatch):
    root, config, calls = activation
    def failed(_):
        raise ValueError('missing gate')
    monkeypatch.setattr(cutover, 'load_bundle', failed)
    with pytest.raises(ValueError, match='missing gate'):
        cutover.activate(root / 'evidence/candidate')
    assert config.read_bytes() == b'original'
    assert calls == []
    assert not (root / 'evidence/asserted_cutover').exists()


def test_reused_config_writer_preserves_inode(tmp_path, monkeypatch):
    import cutover as legacy
    config = tmp_path / 'nginx.conf'
    config.write_bytes(b'old')
    inode = config.stat().st_ino
    monkeypatch.setattr(legacy, 'CONFIG', config)
    cutover.write_config(b'new configuration')
    assert config.stat().st_ino == inode
    assert config.read_bytes() == b'new configuration'
