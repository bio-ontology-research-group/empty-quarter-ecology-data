import copy
import importlib.util
import io
import json
from pathlib import Path
import sys

import pytest
from wkt_certificate_fixtures import certificate_fixture, cert
from verify_downloads import auxiliary_entries, VERIFICATION_CODE

SPEC = importlib.util.spec_from_file_location('kg_cutover', Path(__file__).resolve().parents[1] / 'scripts/release/kg/cutover.py')
CUTOVER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CUTOVER)


@pytest.fixture
def evidence():
    cases = ('field_xrf_site10', 'taxonomy_ERR16061083_genus', 'environment_pseudomonas_gt35', 'sites70', 'six_pcr_ntcs')
    variants = ('direct_server_default', 'direct_asserted', 'api_asserted', 'direct_explicit_from',
                'api_explicit_from_asserted', 'api_explicit_from_materialized')
    checks = [{'case': c, 'variant': v, 'status': 'passed', 'rows': CUTOVER.CASE_ROWS[c], 'expected_rows': CUTOVER.CASE_ROWS[c]} for c in cases for v in variants]
    checks.append({'case': 'taxonomy_api_ERR16061083_top20', 'variant': 'api_rank_genus_limit20',
                   'status': 'passed', 'rows': 20, 'expected_rows': 20})
    for row in checks:
        if row['case'] in ('taxonomy_ERR16061083_genus', 'taxonomy_api_ERR16061083_top20'):
            row['numeric_order_checked'] = True
    files = [{'name': 'rubalkhali-kg-3.0.0-' + n, 'bytes': 10, 'sha256': 'a' * 64}
             for n in ('source.tar.gz', 'modules.tar.gz', 'asserted.nq.gz', 'inferred.nq.gz', 'materialized.nq.gz')]
    counts = dict(asserted=45706821, inferred=100, materialized=45706921)
    for row, name in zip(files[2:], ('asserted', 'inferred', 'materialized')):
        row.update(graph=CUTOVER.GRAPHS[name], triples=counts[name])
    materialization = {'status': 'fixed_point_reached', 'passes': [{'new_triples': 0}],
        'asserted_graph': CUTOVER.GRAPHS['asserted'], 'inferred_graph': CUTOVER.GRAPHS['inferred'],
        'asserted_triples': counts['asserted'], 'inferred_triples': counts['inferred'],
        'asserted_plus_inferred_triples': counts['materialized'],
        'rules_sha256': cert.RULES_SHA256, 'generator_sha256': cert.GENERATOR_SHA256}
    materialization_sha256 = CUTOVER.sha(json.dumps(materialization).encode())
    plan_sha256 = 'b' * 64
    repair = certificate_fixture({key: counts[key] for key in ('asserted', 'inferred')},
                                 materialization_sha256, plan_sha256)
    repair_sha256 = CUTOVER.sha(json.dumps(repair).encode())
    manifest = json.dumps({'version': '3.0.0', 'files': files, 'graphs': CUTOVER.GRAPHS, 'counts': counts,
        'coordinate_import': {'certificate_url': '/downloads/kg/3.0.0/wkt-closure-preservation.json',
                              'certificate_sha256': repair_sha256, 'repair_plan_sha256': plan_sha256,
                              'repair_plan_url': '/downloads/kg/3.0.0/wkt-repair-plan.json',
                              'source_audit_url': '/downloads/kg/3.0.0/geometry_rule_source_audit.json',
                              'source_audit_sha256': repair['source_audit_sha256'],
                              'verification_code': [dict(name=name, url='/downloads/kg/3.0.0/' + name,
                                  sha256=repair['checker_sha256'] if name == 'certify_wkt_repair.py' else 'a' * 64)
                                  for name in sorted(VERIFICATION_CODE)]},
        'evidence': {'materialization_report_sha256': materialization_sha256}}).encode()
    roles = ['urn:role:' + str(i) for i in range(6)]
    browser_checks = [{'name': n, 'status': 'passed', 'rows': 1} for n in (
        'asserted', 'clicked_light_elements', 'All sampling sites and their GPS coordinates',
        'Biomes associated with each site', 'DNA extraction records and concentrations',
        'Provenance: soil sample → DNA → library → sequencing run',
        'Genus-level composition and abundance for ERR16061083',
        'Pseudomonas abundance at hot sites (cross-domain join)',
        'Sequencing QC metrics for a specific sample')]
    browser_checks.append(dict(name='unscoped_materialized_inference_witness', status='passed',
                               mode='materialized', rows=6, expected_rows=6, expected_role_iris=roles))
    browser_counts = {'asserted': 46, 'clicked_light_elements': 71,
                      'All sampling sites and their GPS coordinates': 70,
                      'Genus-level composition and abundance for ERR16061083': 48,
                      'Pseudomonas abundance at hot sites (cross-domain join)': 360}
    for row in browser_checks:
        row['rows'] = browser_counts.get(row['name'], row['rows'])
        if row['name'] == 'Genus-level composition and abundance for ERR16061083':
            row['numeric_order_checked'] = True
    mode_checks = [{'name': name, 'status': 'passed', 'rows': rows, 'expected_rows': rows}
                   for name, rows in [('direct_server_default', 0), ('direct_asserted', 0),
                       ('direct_materialized', 6), ('direct_from_asserted', 0), ('direct_from_materialized', 6),
                       ('api_asserted', 0), ('api_materialized', 6),
                       ('api_materialized_from_asserted', 0), ('api_asserted_from_materialized', 6)]]
    protocol_checks = [dict(name=name, passed=True, http_status=200, complete_response=True)
                       for name in sorted(CUTOVER.PROTOCOL_CHECKS)]
    next(row for row in protocol_checks if row['name'] == 'anonymous_update_denied')['http_status'] = 400
    protocol_checks.extend(dict(name=name, passed=True, http_status=200, complete_response=True,
                                triples=6, content_type=mime, graph_isomorphic=True,
                                literal_datatypes_preserved=True)
                           for name, mime in CUTOVER.GRAPH_FORMAT_CHECKS.items())
    protocol_checks.extend(dict(name=name, passed=True, http_status=200, complete_response=True,
                                rows=6, content_type=mime, result_multiset_preserved=True,
                                literal_datatypes_preserved=True)
                           for name, mime in CUTOVER.SELECT_LITERAL_CHECKS.items())
    return dict(protocol={'version': '3.0.0', 'passed': True, 'checks': protocol_checks,
                          'graph_fixture': {'sha256': CUTOVER.GRAPH_FIXTURE_SHA256,
                                            'triples': 6, 'graph': 'urn:eq:release-test:export'}},
                query={'version': '3.0.0', 'status': 'passed', 'checks': checks},
                mode={'version': '3.0.0', 'status': 'passed', 'checks': mode_checks, 'source_witness': {'roles': roles}},
                download={'passed': True, 'manifest_sha256': CUTOVER.sha(manifest),
                          'files': [dict(f, passed=True, rdf_syntax_checked=f['name'].endswith('.nq.gz')) for f in files],
                          'auxiliary_files': [dict(row, bytes=10, passed=True, http_status=200, full_read=True)
                                              for row in auxiliary_entries(json.loads(manifest))]},
                browser={'status': 'passed', 'materialized_aggregate': 'checked populated',
                         'downloads': [dict(f, bounded_range_status=206) for f in files], 'checks': browser_checks},
                witness={'status': 'passed', 'asserted_inferred_overlap': 0},
                materialization=materialization, repair=repair,
                materialization_sha256=materialization_sha256, repair_sha256=repair_sha256,
                manifest=manifest)


def test_complete_evidence_passes(evidence):
    CUTOVER.check_gates(**evidence)


@pytest.mark.parametrize('missing', ['repair', 'repair_sha256', 'materialization_sha256'])
def test_repair_and_actual_byte_hashes_are_mandatory(evidence, missing):
    del evidence[missing]
    with pytest.raises(TypeError):
        CUTOVER.check_gates(**evidence)


def update_manifest(evidence, manifest):
    evidence['manifest'] = json.dumps(manifest).encode()
    evidence['download']['manifest_sha256'] = CUTOVER.sha(evidence['manifest'])


@pytest.mark.parametrize('flaw', ['missing_coordinate_import', 'wrong_url', 'wrong_certificate_hash',
    'missing_plan_hash', 'invalid_plan_hash', 'different_plan_hash', 'wrong_materialization_hash',
    'missing_materialization_hash', 'actual_repair_hash_changed', 'actual_materialization_hash_changed'])
def test_coordinate_repair_manifest_binding_is_required(evidence, flaw):
    manifest = json.loads(evidence['manifest'])
    if flaw == 'missing_coordinate_import':
        del manifest['coordinate_import']
    elif flaw == 'wrong_url':
        manifest['coordinate_import']['certificate_url'] = '/downloads/kg/2.0.6/wkt-closure-preservation.json'
    elif flaw == 'wrong_certificate_hash':
        manifest['coordinate_import']['certificate_sha256'] = '0' * 64
    elif flaw == 'missing_plan_hash':
        del manifest['coordinate_import']['repair_plan_sha256']
    elif flaw == 'invalid_plan_hash':
        manifest['coordinate_import']['repair_plan_sha256'] = 'not a digest'
    elif flaw == 'different_plan_hash':
        manifest['coordinate_import']['repair_plan_sha256'] = '0' * 64
    elif flaw == 'wrong_materialization_hash':
        manifest['evidence']['materialization_report_sha256'] = '0' * 64
    elif flaw == 'missing_materialization_hash':
        del manifest['evidence']['materialization_report_sha256']
    elif flaw == 'actual_repair_hash_changed':
        evidence['repair_sha256'] = '0' * 64
    else:
        evidence['materialization_sha256'] = '0' * 64
    update_manifest(evidence, manifest)
    with pytest.raises(ValueError):
        CUTOVER.check_gates(**evidence)


@pytest.mark.parametrize('flaw', ['failed', 'private_field', 'missing_check', 'false_check',
    'changed_counts', 'wrong_graph', 'wrong_scope', 'wrong_rules', 'wrong_generator',
    'different_materialization_rules', 'different_materialization_generator'])
def test_coordinate_certificate_scope_and_rule_program_are_checked(evidence, flaw):
    repair = evidence['repair']
    if flaw == 'failed':
        repair['status'] = 'failed'
    elif flaw == 'private_field':
        repair['operator_path'] = '/private/operator/record'
    elif flaw == 'missing_check':
        repair['checks'].pop(next(iter(repair['checks'])))
    elif flaw == 'false_check':
        repair['checks'][next(iter(repair['checks']))] = False
    elif flaw == 'changed_counts':
        repair['counts']['inferred'] += 1
    elif flaw == 'wrong_graph':
        repair['asserted_graph'] = 'urn:wrong'
    elif flaw == 'wrong_scope':
        repair['repairs_count'] = 15
    elif flaw == 'wrong_rules':
        repair['rules_sha256'] = '0' * 64
    elif flaw == 'wrong_generator':
        repair['generator_sha256'] = '0' * 64
    elif flaw == 'different_materialization_rules':
        evidence['materialization']['rules_sha256'] = '0' * 64
    else:
        evidence['materialization']['generator_sha256'] = '0' * 64
    evidence['repair_sha256'] = CUTOVER.sha(json.dumps(repair).encode())
    manifest = json.loads(evidence['manifest'])
    manifest['coordinate_import']['certificate_sha256'] = evidence['repair_sha256']
    update_manifest(evidence, manifest)
    with pytest.raises(ValueError):
        CUTOVER.check_gates(**evidence)


@pytest.mark.parametrize('flaw', ['missing', 'duplicate', 'wrong_name', 'failed', 'wrong_hash',
    'wrong_url', 'partial_status', 'partial_read', 'zero_bytes', 'noninteger_bytes'])
def test_auxiliary_proof_downloads_are_mandatory(evidence, flaw):
    rows = evidence['download']['auxiliary_files']
    if flaw == 'missing':
        rows.pop()
    elif flaw == 'duplicate':
        rows[0] = rows[1]
    elif flaw == 'wrong_name':
        rows[0]['name'] = 'other.json'
    elif flaw == 'failed':
        rows[0]['passed'] = False
    elif flaw == 'wrong_hash':
        rows[0]['sha256'] = '0' * 64
    elif flaw == 'wrong_url':
        rows[0]['url'] = '/other/file.json'
    elif flaw == 'partial_status':
        rows[0]['http_status'] = 206
    elif flaw == 'partial_read':
        rows[0]['full_read'] = False
    elif flaw == 'zero_bytes':
        rows[0]['bytes'] = 0
    else:
        rows[0]['bytes'] = True
    with pytest.raises(ValueError, match='proof download'):
        CUTOVER.check_gates(**evidence)


@pytest.mark.parametrize('target', ['audit', 'checker'])
def test_published_auxiliary_proof_matches_certified_inputs(evidence, target):
    manifest = json.loads(evidence['manifest'])
    if target == 'audit':
        name = 'geometry_rule_source_audit.json'
        manifest['coordinate_import']['source_audit_sha256'] = '0' * 64
    else:
        name = 'certify_wkt_repair.py'
        row = next(item for item in manifest['coordinate_import']['verification_code'] if item['name'] == name)
        row['sha256'] = '0' * 64
    # Even a download hash matching a substituted manifest cannot pass.
    next(row for row in evidence['download']['auxiliary_files'] if row['name'] == name)['sha256'] = '0' * 64
    update_manifest(evidence, manifest)
    with pytest.raises(ValueError, match='differs from the repair certificate'):
        CUTOVER.check_gates(**evidence)


def write_eight_reports(tmp_path, evidence):
    """Serialize distinct bytes, then bind the certificate and manifest to them."""
    names = ('query', 'mode', 'download', 'browser', 'witness', 'materialization', 'protocol', 'repair')
    paths = {name: tmp_path / (name + '.json') for name in names}
    evidence['query'].update(numeric_atol='1e-12', numeric_rtol='1e-12', coordinate_atol='1e-10')
    evidence['mode']['source_witness']['sources'] = [{'sha256': 'a' * 64}]
    evidence['download']['software'] = dict(python='3.11.14', raptor='2.0.15', validator_sha256='c' * 64)
    for row in evidence['download']['files']:
        row.setdefault('triples', None)
        row.setdefault('graph', None)
    evidence['materialization'].update(program_version='fixture', software={}, batch_size=500000,
        execution_rules_sha256='c' * 64, scope_limits={})
    evidence['materialization']['passes'][0].update(iteration=1, rules=[])
    paths['materialization'].write_text(json.dumps(evidence['materialization'], indent=3) + '\n')
    materialization_sha = CUTOVER.sha(paths['materialization'].read_bytes())
    evidence['repair']['materialization_report_sha256'] = materialization_sha
    paths['repair'].write_text(json.dumps(evidence['repair'], indent=4) + '\n')
    manifest = json.loads(evidence['manifest'])
    manifest['evidence']['materialization_report_sha256'] = materialization_sha
    manifest['coordinate_import']['certificate_sha256'] = CUTOVER.sha(paths['repair'].read_bytes())
    manifest_path = tmp_path / 'manifest.json'
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
    evidence['download']['manifest_sha256'] = CUTOVER.sha(manifest_path.read_bytes())
    for row in evidence['download']['auxiliary_files']:
        if row['name'] == 'wkt-closure-preservation.json':
            row['sha256'] = manifest['coordinate_import']['certificate_sha256']
            row['bytes'] = paths['repair'].stat().st_size
    for name in names:
        if name not in ('materialization', 'repair'):
            paths[name].write_text(json.dumps(evidence[name], indent=2) + '\n')
    return paths, manifest_path


def validation_writer():
    path = Path(CUTOVER.__file__).with_name('write_validation_evidence.py')
    spec = importlib.util.spec_from_file_location('kg_validation_writer', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_writer_hashes_read_bytes_once_and_publishes_whitelisted_certificate(evidence, tmp_path, monkeypatch):
    writer = validation_writer()
    paths, manifest = write_eight_reports(tmp_path, evidence)
    output = tmp_path / 'acceptance.json'
    argv = ['writer', '--manifest', str(manifest), '--output', str(output)]
    for name, path in paths.items():
        argv += ['--' + name, str(path)]
    monkeypatch.setattr(sys, 'argv', argv)
    reader = Path.read_bytes
    observed = {}
    def counted(path):
        observed[path] = observed.get(path, 0) + 1
        return reader(path)
    monkeypatch.setattr(Path, 'read_bytes', counted)
    writer.main()
    public = json.loads(output.read_text())
    assert set(public['evidence_sha256']) == set(paths)
    assert len(public['download_gates']) == 5
    assert public['auxiliary_download_gates'] == evidence['download']['auxiliary_files']
    assert len(public['auxiliary_download_gates']) == 8
    for name, path in paths.items():
        assert observed[path] == 1
        assert public['evidence_sha256'][name] == CUTOVER.sha(reader(path))
    assert observed[manifest] == 1
    assert public['coordinate_import_certificate_sha256'] == public['evidence_sha256']['repair']
    assert set(public['coordinate_import_certificate']) == cert.PUBLIC_FIELDS
    assert public['coordinate_import_certificate'] == evidence['repair']
    assert str(tmp_path) not in output.read_text()


@pytest.mark.parametrize('flaw', ['missing_repair', 'changed_repair_bytes', 'changed_materialization_bytes', 'private_certificate_field'])
def test_writer_refuses_incomplete_or_unbound_repair(evidence, tmp_path, monkeypatch, flaw):
    writer = validation_writer()
    paths, manifest = write_eight_reports(tmp_path, evidence)
    output = tmp_path / 'acceptance.json'
    if flaw == 'changed_repair_bytes':
        paths['repair'].write_bytes(paths['repair'].read_bytes() + b'\n')
    elif flaw == 'changed_materialization_bytes':
        paths['materialization'].write_bytes(paths['materialization'].read_bytes() + b'\n')
    elif flaw == 'private_certificate_field':
        repair = json.loads(paths['repair'].read_bytes())
        repair['private_path'] = '/private/record'
        paths['repair'].write_text(json.dumps(repair))
    argv = ['writer', '--manifest', str(manifest), '--output', str(output)]
    for name, path in paths.items():
        if flaw == 'missing_repair' and name == 'repair':
            continue
        argv += ['--' + name, str(path)]
    monkeypatch.setattr(sys, 'argv', argv)
    with pytest.raises((ValueError, SystemExit)):
        writer.main()
    assert not output.exists()


def test_cutover_cli_binds_actual_eight_report_hashes_before_activation(evidence, tmp_path, monkeypatch):
    paths, manifest = write_eight_reports(tmp_path, evidence)
    target = tmp_path / 'publication/kg/3.0.0/manifest.json'
    target.parent.mkdir(parents=True)
    target.write_bytes(manifest.read_bytes())
    monkeypatch.setattr(CUTOVER, 'ROOT', tmp_path)
    observed = {}
    actual_check = CUTOVER.check_gates
    def stop_after_check(**kwargs):
        actual_check(**kwargs)
        observed.update(kwargs)
        raise RuntimeError('TEST STOP after validated gates; no activation')
    monkeypatch.setattr(CUTOVER, 'check_gates', stop_after_check)
    def inspect_only(*args):
        assert args == ('docker', 'inspect', 'viz_web_1', '--format', '{{.Id}}')
        return CUTOVER.OLD_WEB_ID
    monkeypatch.setattr(CUTOVER, 'run', inspect_only)
    argv = ['cutover', 'activate']
    for name, path in paths.items():
        argv += ['--' + name, str(path)]
    monkeypatch.setattr(sys, 'argv', argv)
    with pytest.raises(RuntimeError, match='TEST STOP'):
        CUTOVER.main()
    assert observed['repair_sha256'] == CUTOVER.sha(paths['repair'].read_bytes())
    assert observed['materialization_sha256'] == CUTOVER.sha(paths['materialization'].read_bytes())
    assert observed['repair'] == evidence['repair']
    assert not (tmp_path / 'evidence/cutover').exists()


def test_rollback_does_not_require_repair_or_revalidate_activation(monkeypatch, tmp_path):
    baseline = b'original rollback fixture\n'
    directory = tmp_path / 'evidence/cutover'
    directory.mkdir(parents=True)
    (directory / 'nginx.before.conf').write_bytes(baseline)
    config = tmp_path / 'nginx.conf'
    config.write_bytes(Path(CUTOVER.__file__).with_name('nginx.cutover.conf').read_bytes())
    monkeypatch.setattr(CUTOVER, 'ROOT', tmp_path)
    monkeypatch.setattr(CUTOVER, 'CONFIG', config)
    monkeypatch.setattr(CUTOVER, 'BASELINE_SHA256', CUTOVER.sha(baseline))
    def no_gate(**kwargs):
        raise AssertionError('Rollback must remain independent of activation certificate')
    monkeypatch.setattr(CUTOVER, 'check_gates', no_gate)
    calls = []
    def execute(*args):
        calls.append(args)
        return CUTOVER.OLD_WEB_ID if args[1] == 'inspect' else ''
    monkeypatch.setattr(CUTOVER, 'run', execute)
    monkeypatch.setattr(sys, 'argv', ['cutover', 'rollback'])
    CUTOVER.main()
    assert config.read_bytes() == baseline
    assert json.loads((directory / 'rollback.json').read_text())['status'] == 'restored'
    assert len(calls) == 3


@pytest.mark.parametrize('target', ['profile', 'api', 'browser'])
@pytest.mark.parametrize('value', [None, False])
def test_numeric_sort_proof_required(evidence, target, value):
    if target == 'browser':
        row = next(c for c in evidence['browser']['checks']
                   if c['name'] == 'Genus-level composition and abundance for ERR16061083')
    else:
        name = 'taxonomy_ERR16061083_genus' if target == 'profile' else 'taxonomy_api_ERR16061083_top20'
        row = next(c for c in evidence['query']['checks'] if c['case'] == name)
    if value is None:
        del row['numeric_order_checked']
    else:
        row['numeric_order_checked'] = value
    with pytest.raises(ValueError, match='numeric ordering'):
        CUTOVER.check_gates(**evidence)


@pytest.mark.parametrize('flaw', ['failed', 'old_version', 'missing', 'duplicate',
                                 'partial', 'wrong_fixture', 'wrong_mime',
                                 'changed_graph', 'changed_datatype', 'wrong_count', 'update_allowed',
                                 'select_wrong_datatype', 'select_wrong_rows', 'select_wrong_multiset'])
def test_protocol_flaws_block_activation(evidence, flaw):
    protocol = evidence['protocol']
    row = next(c for c in protocol['checks'] if c['name'] == 'construct_turtle_roundtrip')
    if flaw == 'failed':
        protocol['passed'] = False
    elif flaw == 'old_version':
        protocol['version'] = '2.0.6'
    elif flaw == 'missing':
        protocol['checks'].pop()
    elif flaw == 'duplicate':
        protocol['checks'][0] = protocol['checks'][1]
    elif flaw == 'partial':
        row['complete_response'] = False
    elif flaw == 'wrong_fixture':
        protocol['graph_fixture']['sha256'] = '0' * 64
    elif flaw == 'wrong_mime':
        row['content_type'] = 'application/octet-stream'
    elif flaw == 'changed_graph':
        row['graph_isomorphic'] = False
    elif flaw == 'changed_datatype':
        row['literal_datatypes_preserved'] = False
    elif flaw == 'wrong_count':
        row['triples'] = 5
    elif flaw.startswith('select_'):
        selected = next(c for c in protocol['checks'] if c['name'] == 'select_json_literal_roundtrip')
        if flaw == 'select_wrong_datatype':
            selected['literal_datatypes_preserved'] = False
        elif flaw == 'select_wrong_rows':
            selected['rows'] = 5
        else:
            selected['result_multiset_preserved'] = False
    else:
        next(c for c in protocol['checks'] if c['name'] == 'anonymous_update_denied')['http_status'] = 200
    with pytest.raises(ValueError):
        CUTOVER.check_gates(**evidence)


@pytest.mark.parametrize('flaw', [None, 'count_changed', 'partial', 'empty_result'])
def test_live_graph_counts_are_rechecked_before_activation(monkeypatch, flaw):
    counts = dict(asserted=45706821, inferred=100, materialized=45706921)
    requests = []

    def reply(url, data, timeout):
        mode = ('asserted', 'inferred', 'materialized')[len(requests)]
        from urllib.parse import parse_qs
        query = parse_qs(data.decode())['query'][0]
        assert 'FROM NAMED <' + CUTOVER.GRAPHS[mode] + '>' in query
        requests.append(mode)
        rows = [{'n': {'value': str(counts[mode] + (1 if flaw == 'count_changed' else 0))}}]
        value = io.BytesIO(json.dumps({'results': {'bindings': [] if flaw == 'empty_result' else rows}}).encode())
        value.status = 200
        value.headers = {'X-SQL-State': 'S1TAT'} if flaw == 'partial' else {}
        return value

    monkeypatch.setattr(CUTOVER, 'urlopen', reply)
    if flaw:
        with pytest.raises(RuntimeError):
            CUTOVER.verify_live_counts(counts)
    else:
        assert CUTOVER.verify_live_counts(counts) == counts
        assert requests == ['asserted', 'inferred', 'materialized']


def test_entrypoint_write_preserves_bind_mount_inode(monkeypatch, tmp_path):
    config = tmp_path / 'nginx.conf'
    config.write_bytes(b'original configuration')
    inode = config.stat().st_ino
    monkeypatch.setattr(CUTOVER, 'CONFIG', config)
    CUTOVER.write_config(b'replacement configuration')
    assert config.read_bytes() == b'replacement configuration'
    assert config.stat().st_ino == inode


@pytest.mark.parametrize('flaw', ['partial_queries', 'duplicate_query', 'wrong_rows', 'stale_manifest',
                                   'missing_download', 'unparsed_rdf', 'partial_browser', 'failed_witness',
                                   'nonzero_pass', 'ignored_materialized_mode', 'fake_expected_count',
                                   'wrong_materialization_graph', 'wrong_materialization_count',
                                   'empty_browser_witness', 'wrong_browser_witness', 'missing_browser_example',
                                   'wrong_download_graph', 'duplicate_browser_download'])
def test_incomplete_evidence_blocks_activation(evidence, flaw):
    item = copy.deepcopy(evidence)
    if flaw == 'partial_queries':
        item['query']['checks'].pop()
    elif flaw == 'duplicate_query':
        item['query']['checks'][0] = item['query']['checks'][1]
    elif flaw == 'wrong_rows':
        item['query']['checks'][0]['rows'] = 0
    elif flaw == 'stale_manifest':
        item['download']['manifest_sha256'] = 'b' * 64
    elif flaw == 'missing_download':
        item['download']['files'].pop()
    elif flaw == 'unparsed_rdf':
        item['download']['files'][-1]['rdf_syntax_checked'] = False
    elif flaw == 'partial_browser':
        item['browser']['checks'].pop()
    elif flaw == 'failed_witness':
        item['witness']['status'] = 'failed'
    elif flaw == 'ignored_materialized_mode':
        item['mode']['checks'][6]['rows'] = 0
    elif flaw == 'fake_expected_count':
        item['query']['checks'][0].update(rows=10, expected_rows=10)
    elif flaw == 'wrong_materialization_graph':
        item['materialization']['asserted_graph'] = 'urn:wrong-graph'
    elif flaw == 'wrong_materialization_count':
        item['materialization']['inferred_triples'] = 50
    elif flaw == 'empty_browser_witness':
        item['browser']['checks'][-1].update(rows=0, expected_rows=0)
    elif flaw == 'wrong_browser_witness':
        item['browser']['checks'][-1]['expected_role_iris'][0] = 'urn:wrong-role'
        # Preserve the independently sourced expected inventory.
        item['mode']['source_witness']['roles'] = evidence['mode']['source_witness']['roles'][:]
    elif flaw == 'missing_browser_example':
        item['browser']['checks'].pop(2)
    elif flaw == 'wrong_download_graph':
        item['download']['files'][-1]['graph'] = 'urn:wrong-graph'
    elif flaw == 'duplicate_browser_download':
        item['browser']['downloads'][0] = item['browser']['downloads'][1]
    else:
        item['materialization']['passes'][-1]['new_triples'] = 1
    with pytest.raises(ValueError):
        CUTOVER.check_gates(**item)
