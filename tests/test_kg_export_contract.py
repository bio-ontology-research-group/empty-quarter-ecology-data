import importlib.util
import hashlib
import json
from pathlib import Path

import pytest


@pytest.mark.parametrize('flaw', [None, 'wrong_graph', 'old_asserted_count', 'wrong_union', 'nonzero_rule', 'empty_rules'])
def test_export_requires_exact_completed_release_evidence(monkeypatch, flaw):
    directory = Path(__file__).resolve().parents[1] / 'scripts/release/kg'
    monkeypatch.syspath_prepend(str(directory))
    spec = importlib.util.spec_from_file_location('kg_finalize', directory / 'finalize_graphs.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    report = {'status': 'fixed_point_reached', 'passes': [{'new_triples': 0, 'rules': [{'new_triples': 0}]}],
              'asserted_graph': module.BASE + 'asserted/3.0.0',
              'inferred_graph': module.BASE + 'inferred/3.0.0',
              'asserted_triples': 45706821, 'inferred_triples': 100,
              'asserted_plus_inferred_triples': 45706921}
    if flaw == 'wrong_graph':
        report['asserted_graph'] = 'urn:wrong-release'
    elif flaw == 'old_asserted_count':
        report['asserted_triples'] = 45706822
    elif flaw == 'wrong_union':
        report['asserted_plus_inferred_triples'] = 1
    elif flaw == 'nonzero_rule':
        report['passes'][-1]['rules'][0]['new_triples'] = 1
    elif flaw == 'empty_rules':
        report['passes'][-1]['rules'] = []
    if flaw:
        with pytest.raises(RuntimeError):
            module.validate_materialization(report)
    else:
        module.validate_materialization(report)


def test_union_uses_logged_autocommit_without_modifying_source_graphs(monkeypatch):
    directory = Path(__file__).resolve().parents[1] / 'scripts/release/kg'
    monkeypatch.syspath_prepend(str(directory))
    spec = importlib.util.spec_from_file_location('kg_finalize', directory / 'finalize_graphs.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    graphs = dict(asserted='urn:a', inferred='urn:i', materialized='urn:m')
    assert module.union_sql(graphs) == (
        'SPARQL DEFINE sql:log-enable 3 COPY GRAPH <urn:a> TO GRAPH <urn:m>;\n'
        'SPARQL DEFINE sql:log-enable 3 ADD GRAPH <urn:i> TO GRAPH <urn:m>;\nCHECKPOINT;\n')


@pytest.mark.parametrize('flaw', [None, 'report_hash', 'plan_hash', 'failed_certificate', 'different_rules'])
def test_export_requires_bound_coordinate_repair_certificate(monkeypatch, tmp_path, flaw):
    directory = Path(__file__).resolve().parents[1] / 'scripts/release/kg'
    monkeypatch.syspath_prepend(str(directory))
    from wkt_certificate_fixtures import certificate_fixture
    import certify_wkt_repair as cert
    import finalize_graphs as module
    counts = {'asserted': 45706821, 'inferred': 100}
    report = {'asserted_triples': counts['asserted'], 'inferred_triples': counts['inferred'],
              'rules_sha256': cert.RULES_SHA256, 'generator_sha256': cert.GENERATOR_SHA256}
    if flaw == 'different_rules':
        report['rules_sha256'] = 'b' * 64
    materialization_path = tmp_path / 'materialization.json'
    materialization_path.write_text(json.dumps(report))
    plan_path = tmp_path / 'plan.json'
    plan_path.write_text('{}')
    report_sha = hashlib.sha256(materialization_path.read_bytes()).hexdigest()
    plan_sha = hashlib.sha256(plan_path.read_bytes()).hexdigest()
    certificate = certificate_fixture(counts, report_sha, plan_sha)
    if flaw == 'report_hash':
        certificate['materialization_report_sha256'] = 'b' * 64
    elif flaw == 'plan_hash':
        certificate['repair_plan_sha256'] = 'b' * 64
    elif flaw == 'failed_certificate':
        certificate['status'] = 'failed'
    certificate_path = tmp_path / 'certificate.json'
    certificate_path.write_text(json.dumps(certificate))
    if flaw:
        with pytest.raises(ValueError):
            module.repair_evidence(materialization_path, certificate_path, plan_path)
    else:
        hashes = module.repair_evidence(materialization_path, certificate_path, plan_path)
        assert hashes == {
            'materialization_report_sha256': report_sha,
            'coordinate_repair_plan_sha256': plan_sha,
            'coordinate_repair_certificate_sha256': hashlib.sha256(certificate_path.read_bytes()).hexdigest(),
        }
