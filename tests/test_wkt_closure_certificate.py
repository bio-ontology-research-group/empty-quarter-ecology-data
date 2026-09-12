import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest
from rdflib import Graph, Literal, RDF, RDFS, URIRef

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts/release/kg'
sys.path.insert(0, str(SCRIPTS))
import certify_wkt_repair as cert
from materialize import materialize_local, rules_for


def fixture_plan():
    source = {}
    repairs = []
    for index in range(1, 71):
        subject = 'https://rubalkhali.science/kb/RAK_' + str(1000000 + index)
        value = f'POINT({50 + index/10} {20 + index/100})'
        source[subject] = {'value': value, 'datatype': cert.DATATYPE}
        if index <= 16:
            repairs.append({'subject': subject, 'predicate': cert.PREDICATE,
                            'before': {'value': f'POINT({50 + index/10 + 0.000001} {20 + index/100})',
                                       'datatype': cert.DATATYPE},
                            'after': {'value': value.replace('POINT(', 'POINT ('), 'datatype': cert.DATATYPE},
                            'source_lexical': value})
    source['urn:polygon'] = {'value': 'POLYGON((0 0, 1 0, 1 1, 0 0))', 'datatype': cert.DATATYPE}
    plan = {'asserted_graph': cert.ASSERTED, 'expected_count_before': 45706821,
            'expected_count_after': 45706821, 'repair_count': 16, 'repairs': repairs}
    before = copy.deepcopy(source)
    after = copy.deepcopy(source)
    for repair in repairs:
        before[repair['subject']] = repair['before']
        after[repair['subject']] = repair['after']
    return plan, source, before, after


def full_program():
    schema = Graph().parse(data='''
        @prefix : <urn:example:> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        :a owl:propertyChainAxiom (:p :q) .
        :b owl:propertyChainAxiom (:p :q :r) .
        :c owl:propertyChainAxiom ([owl:inverseOf :p] :q) .
        :d owl:propertyChainAxiom (:p [owl:inverseOf :q]) .
    ''', format='turtle')
    rules = rules_for(schema)
    return rules, '\n\n'.join('# ' + r.name + '\n' + r.update(cert.ASSERTED, cert.INFERRED)
                              for r in rules) + '\n'


def fake_completed_directory(tmp_path):
    rules, program = full_program()
    (tmp_path / 'rules.rq').write_text(program)
    (tmp_path / 'execution_rules.rq').write_text(program)
    report = {'status': 'fixed_point_reached', 'generator_sha256': cert.GENERATOR_SHA256,
              'rules_sha256': hashlib.sha256(program.encode()).hexdigest(),
              'execution_rules_sha256': hashlib.sha256(program.encode()).hexdigest(),
              'asserted_graph': cert.ASSERTED, 'inferred_graph': cert.INFERRED,
              'passes': [{'iteration': 1, 'new_triples': 0,
                          'rules': [{'name': r.name, 'new_triples': 0, 'batch_additions': [0]} for r in rules]}]}
    (tmp_path / 'materialization.json').write_text(json.dumps(report))
    (tmp_path / 'contradiction_diagnostics.json').write_text(json.dumps({
        'complement_types': [], 'explicit_disjoint_types': [],
        'nothing_members': [], 'pcr_extraction_role_clash': []}))
    return report


def test_exact_program_hash_and_27_rule_coverage(tmp_path):
    fake_completed_directory(tmp_path)
    assert cert.validate_original_closure(tmp_path)['rules_sha256'] == cert.RULES_SHA256
    assert len(cert.RULE_COVERAGE) == 27


def test_unknown_or_changed_rule_is_rejected(tmp_path):
    fake_completed_directory(tmp_path)
    with (tmp_path / 'rules.rq').open('a') as handle:
        handle.write('\n# unknown_rule\n')
    with pytest.raises(ValueError, match='Logical rules'):
        cert.validate_original_closure(tmp_path)


def test_incomplete_zero_schedule_is_rejected(tmp_path):
    report = fake_completed_directory(tmp_path)
    report['passes'][0]['rules'].pop()
    (tmp_path / 'materialization.json').write_text(json.dumps(report))
    with pytest.raises(ValueError, match='complete logical rule schedule'):
        cert.validate_original_closure(tmp_path)


def test_schema_involvement_fails_closed():
    declaration = {(cert.RDF_TYPE, cert.ANNOTATION_PROPERTY)}
    cert.validate_schema_rows(declaration, False)
    for rows, incoming in ((declaration, True),
                           (declaration | {(str(RDFS.subPropertyOf), 'urn:super')}, False),
                           (declaration | {(cert.RDF_TYPE, 'http://www.w3.org/2002/07/owl#TransitiveProperty')}, False)):
        with pytest.raises(ValueError):
            cert.validate_schema_rows(rows, incoming)


def test_canonical_sql_guards_old_str_without_reparsing_geometry():
    plan, source, before, after = fixture_plan()
    cert.validate_plan(plan, source)
    sql = cert.canonical_repair_sql(plan)
    assert sql.count('DELETE {') == sql.count('INSERT {') == 1
    assert 'STR(?old) = ?oldLex' in sql
    assert '^^<' + cert.DATATYPE + '>' not in sql
    assert 'GRAPH <' + cert.STAGING + '>' in sql
    assert "DECLARE EXIT HANDLER FOR SQLSTATE '*' { ROLLBACK WORK; RESIGNAL; }" in sql
    assert 'DEFINE sql:log-enable 1' in sql
    assert sql.index('COMMIT WORK;') < sql.index("result ('WKT_REPAIR_COMMITTED_16')")
    assert sql.startswith('CREATE PROCEDURE ' + cert.PROCEDURE)
    assert cert.canonical_repair_call() == cert.PROCEDURE + ' ();\n'
    assert cert.INFERRED not in sql
    assert plan['repairs'][0]['before']['value'] in sql
    assert cert.canonical_repair_sql({**plan, 'repairs': list(reversed(plan['repairs']))}) == sql


def test_wrong_predicate_or_unlisted_repair_rejected():
    plan, source, before, after = fixture_plan()
    plan['repairs'][0]['predicate'] = 'urn:different'
    with pytest.raises(ValueError, match='different predicate'):
        cert.canonical_repair_sql(plan)
    plan, source, before, after = fixture_plan()
    plan['repairs'].append(copy.deepcopy(plan['repairs'][0]))
    with pytest.raises(ValueError, match='16 repairs'):
        cert.validate_plan(plan)


def test_equal_float_with_changed_source_digits_is_rejected():
    plan, source, before, after = fixture_plan()
    row = plan['repairs'][0]
    row['after']['value'] = row['after']['value'].replace('50.1 ', '50.1000000000000001 ')
    assert cert.point(row['after']['value']) == cert.point(row['source_lexical'])
    with pytest.raises(ValueError, match='exact original source digits'):
        cert.validate_plan(plan, source)


def test_all71_transition_and_original_precision_gate():
    plan, source, before, after = fixture_plan()
    cert.validate_geometry_transition(before, after, plan, source)
    wrong = copy.deepcopy(after)
    wrong[plan['repairs'][0]['subject']] = plan['repairs'][0]['before']
    with pytest.raises(ValueError, match='precision gate'):
        cert.validate_geometry_transition(before, wrong, plan, source)


def test_unlisted_point_or_polygon_change_rejected():
    plan, source, before, after = fixture_plan()
    for subject in ('urn:polygon', 'https://rubalkhali.science/kb/RAK_1000070'):
        wrong = copy.deepcopy(after)
        wrong[subject]['value'] += ' '
        with pytest.raises(ValueError, match='Unlisted geometry changed'):
            cert.validate_geometry_transition(before, wrong, plan, source)


def test_literal_annotation_repair_preserves_reference_least_fixed_point():
    graph = Graph()
    graph.add((URIRef(cert.PREDICATE), RDF.type, URIRef(cert.ANNOTATION_PROPERTY)))
    graph.add((URIRef('urn:A'), RDFS.subClassOf, URIRef('urn:B')))
    graph.add((URIRef('urn:site'), RDF.type, URIRef('urn:A')))
    old = Literal('POINT(1.000001 2)', datatype=URIRef(cert.DATATYPE))
    new = Literal('POINT (1 2)', datatype=URIRef(cert.DATATYPE))
    graph.add((URIRef('urn:site'), URIRef(cert.PREDICATE), old))
    first, _ = materialize_local(graph, batch_size=3)
    graph.remove((URIRef('urn:site'), URIRef(cert.PREDICATE), old))
    graph.add((URIRef('urn:site'), URIRef(cert.PREDICATE), new))
    second, _ = materialize_local(graph, batch_size=3)
    assert set(first) == set(second) == {(URIRef('urn:site'), RDF.type, URIRef('urn:B'))}


def public_certificate():
    plan, source, before, after = fixture_plan()
    record = {key: 'a' * 64 for key in cert.PUBLIC_FIELDS}
    record.update(version=cert.VERSION, status='passed', checker_sha256=cert.digest(cert.__file__),
                  rules_sha256=cert.RULES_SHA256, generator_sha256=cert.GENERATOR_SHA256,
                  asserted_graph=cert.ASSERTED, inferred_graph=cert.INFERRED,
                  counts={'asserted': 45706821, 'inferred': 123}, repairs_count=16,
                  geometry_fact_count=71, coordinate_tolerance=1e-10,
                  before_geometry_facts=before, after_geometry_facts=after,
                  staging_graph=cert.STAGING,
                  staging_geometry_facts={s: r for s, r in after.items() if cert.point(r['value']) is not None},
                  rule_coverage=cert.RULE_COVERAGE,
                  checks={key: True for key in cert.REQUIRED_CHECKS})
    return record


def test_public_certificate_validator_rejects_changed_scope_and_private_fields():
    original = public_certificate()
    cert.validate_certificate(original, 'a' * 64, 'a' * 64, original['counts'])
    mutations = [
        {'operator_path': '/private/operator/evidence'},
        {'version': 'different'}, {'status': 'failed'},
        {'rules_sha256': 'b' * 64}, {'checker_sha256': 'b' * 64},
        {'repair_plan_sha256': 'b' * 64}, {'coordinate_tolerance': 1e-4},
        {'repairs_count': 17}, {'rule_coverage': {}},
        {'checks': {key: False for key in cert.REQUIRED_CHECKS}},
        {'after_geometry_facts': {}},
    ]
    for mutation in mutations:
        record = copy.deepcopy(original)
        record.update(mutation)
        with pytest.raises(ValueError):
            cert.validate_certificate(record, 'a' * 64, 'a' * 64, original['counts'])


def test_read_only_preflight_to_certificate_hash_bound_workflow(tmp_path):
    class SnapshotEndpoint:
        def __init__(self, geometry):
            self.geometry = geometry

        def count(self, graph):
            return 45706821 if graph == cert.ASSERTED else 123

        def query(self, query):
            if query.startswith('SELECT DISTINCT ?p ?o'):
                return {'results': {'bindings': [{'p': {'value': cert.RDF_TYPE},
                                                 'o': {'value': cert.ANNOTATION_PROPERTY}}]}}
            if query.startswith('SELECT ?subject'):
                geometry = ({s: r for s, r in after.items() if cert.point(r['value']) is not None}
                            if cert.STAGING in query else self.geometry)
                return {'results': {'bindings': [dict(subject={'value': s},
                                                     **{k: {'value': v} for k, v in r.items()})
                                                 for s, r in geometry.items()]}}
            assert query.startswith('ASK '), 'Read-only query expected'
            return {'boolean': False}

    def save(name, data):
        path = tmp_path / name
        path.write_text(json.dumps(data))
        return path

    report = fake_completed_directory(tmp_path)
    report.update(asserted_triples=45706821, inferred_triples=123)
    save('materialization.json', report)
    plan, source, before, after = fixture_plan()
    graph = Graph()
    for subject, row in source.items():
        graph.add((URIRef(subject), URIRef(cert.PREDICATE),
                   Literal(row['value'], datatype=URIRef(cert.DATATYPE))))
    source_file = tmp_path / 'sites.owl'
    graph.serialize(destination=str(source_file), format='xml')
    plan['source_sha256'] = cert.digest(source_file)
    plan_file = save('plan.json', plan)
    audit_file = save('audit.json', {'status': 'passed', 'module_count': 16,
                                   'geometry_vocabulary_modules': ['rubalkhali_sites.owl'],
                                   'asWKT_object_occurrences': 0, 'asWKT_fact_count': 71,
                                   'records': [{'file': 'rubalkhali_sites.owl', 'sha256': cert.digest(source_file)}]
                                   + [{'file': 'other' + str(i), 'sha256': 'a' * 64} for i in range(15)]})
    preflight = cert.preflight(SnapshotEndpoint(before), tmp_path, audit_file, plan_file, source_file)
    before_file = save('preflight.json', preflight)
    sql_file, log_file = tmp_path / 'repair.sql', tmp_path / 'repair.log'
    sql_file.write_text(cert.canonical_repair_sql(plan))
    log_file.write_text('Procedure definition succeeded.\n')
    call_file, call_log = tmp_path / 'call.sql', tmp_path / 'call.log'
    call_file.write_text(cert.canonical_repair_call())
    call_log.write_text('WKT_REPAIR_COMMITTED_16\n')
    execution = {'status': 'passed', 'exclusive_write_window': True,
                 'procedure_absent_before_definition': True, 'definition_checked_before_call': True,
                 'asserted_graph': cert.ASSERTED, 'inferred_graph': cert.INFERRED,
                 'repair_plan_sha256': cert.digest(plan_file),
                 'materialization_report_sha256': cert.digest(tmp_path / 'materialization.json')}
    for key, path in (('preflight', before_file), ('sql', sql_file), ('sql_log', log_file),
                      ('call', call_file), ('call_log', call_log)):
        execution[key + '_file'] = path.name
        execution[key + '_sha256'] = cert.digest(path)
    execution_file = save('execution.json', execution)
    certificate = cert.certify(SnapshotEndpoint(after), tmp_path, audit_file,
                               plan_file, source_file, execution_file)
    assert certificate['status'] == 'passed'
    assert certificate['counts'] == {'asserted': 45706821, 'inferred': 123}
    assert set(certificate) == cert.PUBLIC_FIELDS
    execution['definition_checked_before_call'] = False
    save('execution.json', execution)
    with pytest.raises(ValueError, match='Separate checked'):
        cert.certify(SnapshotEndpoint(after), tmp_path, audit_file,
                     plan_file, source_file, execution_file)
    execution['definition_checked_before_call'] = True
    call_log.write_text('No successful commit marker.\n')
    execution['call_log_sha256'] = cert.digest(call_log)
    save('execution.json', execution)
    with pytest.raises(ValueError, match='invocation failed'):
        cert.certify(SnapshotEndpoint(after), tmp_path, audit_file,
                     plan_file, source_file, execution_file)
    call_log.write_text('WKT_REPAIR_COMMITTED_16\n')
    execution['call_log_sha256'] = cert.digest(call_log)
    sql_file.write_text(sql_file.read_text() + 'SPARQL CLEAR GRAPH <urn:other>;\n')
    execution['sql_sha256'] = cert.digest(sql_file)
    save('execution.json', execution)
    with pytest.raises(ValueError, match='exact repair scope'):
        cert.certify(SnapshotEndpoint(after), tmp_path, audit_file,
                     plan_file, source_file, execution_file)
def test_public_certificate_rejects_geometry_inventory_tampering():
    original = public_certificate()
    for mutation in ('different_subject', 'datatype', 'polygon', 'seventeenth_point'):
        record = copy.deepcopy(original)
        after = record['after_geometry_facts']
        if mutation == 'different_subject':
            after['urn:other'] = after.pop('urn:polygon')
        elif mutation == 'datatype':
            after['urn:polygon']['datatype'] = 'urn:other'
        elif mutation == 'polygon':
            after['urn:polygon']['value'] += ' '
        else:
            after['https://rubalkhali.science/kb/RAK_1000070']['value'] += ' '
        with pytest.raises(ValueError):
            cert.validate_certificate(record, 'a' * 64, 'a' * 64, original['counts'])
