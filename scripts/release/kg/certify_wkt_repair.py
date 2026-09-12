#!/usr/bin/env python3
"""Read-only, rule-bound closure certificate for the exact 16-site WKT repair."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re

from rdflib import Graph, URIRef
from materialize import Endpoint, PREFIXES, iri

VERSION = 'rak-wkt-closure-preservation-1.1'
RULES_SHA256 = 'd606669b2651eab7bf4fff2bbcce46746c82a894d4ae7d863cb60a761b9b4451'
GENERATOR_SHA256 = 'b78c28aab98e94971435d2d0babb2ef532aa16a479c57be90c9552fb42b01d99'
ASSERTED = 'https://rubalkhali.science/graph/asserted/3.0.0'
INFERRED = 'https://rubalkhali.science/graph/inferred/3.0.0'
STAGING = 'urn:eq:release-test:geometry-precision-20260910:space'
PROCEDURE = 'DB.DBA.EQ_WKT_REPAIR_3_0_0_20260910'
PREDICATE = 'http://www.opengis.net/ont/geosparql#asWKT'
DATATYPE = 'http://www.opengis.net/ont/geosparql#wktLiteral'
RDF_TYPE = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type'
ANNOTATION_PROPERTY = 'http://www.w3.org/2002/07/owl#AnnotationProperty'
COORDINATE_TOLERANCE = 1e-10  # The pre-existing source/engine precision gate.

FIXED_RULES = (
    'equivalent_class_forward', 'equivalent_class_reverse',
    'equivalent_property_forward', 'equivalent_property_reverse',
    'subclass_transitive', 'subproperty_transitive', 'subclass_type',
    'has_value_forward', 'intersection_eliminate', 'intersection_introduce',
    'union_introduce', 'enumeration_members')
GUARDED_RULES = {
    'subproperty_fact': 'asWKT has no subPropertyOf antecedent',
    'domain': 'asWKT has no domain antecedent',
    'range_resource': 'asWKT has no range antecedent; literal fillers are excluded',
    'inverse_forward': 'asWKT has no inverse antecedent; literal subjects are excluded',
    'inverse_reverse': 'asWKT has no incoming inverse antecedent; literal subjects are excluded',
    'symmetric': 'asWKT has no SymmetricProperty type; literal subjects are excluded',
    'transitive': 'asWKT has no TransitiveProperty type',
    'has_value_classify': 'No restriction has asWKT as its onProperty object',
    'some_values_classify': 'No restriction uses asWKT; literal fillers are excluded',
    'some_thing_classify': 'No restriction uses asWKT; literal fillers are excluded',
    'all_values_existing': 'No restriction uses asWKT; literal fillers are excluded',
    'property_chain_length_2': 'asWKT occurs in no property-chain operand',
    'property_chain_length_3': 'asWKT occurs in no property-chain operand',
    'property_chain_length_2_inverse_1': 'asWKT occurs in no named or inverse chain operand',
    'property_chain_length_2_inverse_0': 'asWKT occurs in no named or inverse chain operand',
}
RULE_COVERAGE = {name: 'Changed predicate is absent from the fixed-predicate body'
                 for name in FIXED_RULES}
RULE_COVERAGE.update(GUARDED_RULES)
RULE_COVERAGE['has_value_forward'] = 'Body unchanged; no onProperty reference permits an asWKT head'
REQUIRED_CHECKS = {
    'completed_original_closure', 'exact_rule_program', 'complete_rule_classification',
    'source_audit', 'isolated_annotation_schema', 'no_inferred_asWKT',
    'no_old_geometry_objects_in_delta_before_repair', 'canonical_transaction',
    'exact_pre_repair_values', 'all_71_geometry_facts_verified',
    'all_70_source_points_at_original_precision_gate', 'polygon_unchanged',
    'asserted_count_unchanged', 'inferred_count_unchanged',
    'staged_70_source_points_unchanged',
}
PUBLIC_FIELDS = {
    'version', 'status', 'created_at', 'checker_sha256',
    'materialization_report_sha256', 'rules_sha256', 'generator_sha256',
    'source_audit_sha256', 'source_sites_sha256', 'repair_plan_sha256',
    'preflight_sha256', 'repair_execution_sha256', 'repair_sql_sha256',
    'repair_sql_log_sha256', 'asserted_graph', 'inferred_graph', 'counts',
    'repair_call_sha256', 'repair_call_log_sha256',
    'repairs_count', 'geometry_fact_count', 'coordinate_tolerance',
    'before_geometry_facts', 'after_geometry_facts', 'rule_coverage',
    'checks', 'proof', 'original_report_scope',
    'staging_graph', 'staging_geometry_facts',
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def write_new(path, record):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as handle:
        json.dump(record, handle, indent=2, sort_keys=True)
        handle.write('\n')


def point(value):
    match = re.fullmatch(r'POINT\s*\(\s*([^\s()]+)\s+([^\s()]+)\s*\)', value)
    if not match:
        return None
    result = tuple(float(x) for x in match.groups())
    require(all(math.isfinite(x) for x in result), 'Nonfinite point coordinate')
    return result


def source_geometries(path):
    graph = Graph().parse(str(path), format='xml')
    rows = {}
    for subject, value in graph.subject_objects(URIRef(PREDICATE)):
        require(str(subject) not in rows, 'Multiple WKT facts on one source subject')
        require(str(value.datatype) == DATATYPE, 'Unexpected source geometry datatype')
        rows[str(subject)] = {'value': str(value), 'datatype': DATATYPE}
    require(len(rows) == 71 and sum(point(r['value']) is not None for r in rows.values()) == 70,
            'Expected the frozen 70 points and one polygon')
    return rows


def validate_plan(plan, source=None):
    require(plan['asserted_graph'] == ASSERTED, 'Wrong repair graph')
    require(plan['expected_count_before'] == plan['expected_count_after'] == 45706821,
            'Unexpected asserted count contract')
    repairs = plan['repairs']
    require(plan['repair_count'] == len(repairs) == 16, 'Exactly 16 repairs required')
    require(len({r['subject'] for r in repairs}) == 16, 'Duplicate repair subject')
    for row in repairs:
        iri(row['subject'])
        require(row['predicate'] == PREDICATE, 'Repair changes a different predicate')
        require(set(row['before']) == set(row['after']) == {'value', 'datatype'},
                'Only typed geometry literals may change')
        require(row['before']['datatype'] == row['after']['datatype'] == DATATYPE,
                'Geometry datatype changes')
        require(point(row['before']['value']) is not None and point(row['after']['value']) is not None,
                'Only point literals may be repaired')
        require(row['after']['value'].startswith('POINT ('), 'Verified import spelling required')
        require(row['before'] != row['after'], 'Unchanged repair pair')
        if source is not None:
            require(row['subject'] in source, 'Repair subject absent from frozen sites source')
            require(row['source_lexical'] == source[row['subject']]['value'], 'Source lexical mismatch')
            require(row['after']['value'] == row['source_lexical'].replace('POINT(', 'POINT (', 1),
                    'Replacement must preserve exact original source digits')


def canonical_repair_sql(plan):
    """Return the only accepted transaction; this function never executes SQL."""
    validate_plan(plan)
    values = []
    for row in sorted(plan['repairs'], key=lambda item: item['subject']):
        old = json.dumps(row['before']['value'], ensure_ascii=False)
        values.append('    (' + iri(row['subject']) + ' ' + old + ')')
    binding = ('  VALUES (?s ?oldLex) {\n' + '\n'.join(values) + '\n  }\n'
               '  GRAPH ' + iri(ASSERTED) + ' { ?s ' + iri(PREDICATE) + ' ?old . }\n'
               '  GRAPH ' + iri(STAGING) + ' { ?s ' + iri(PREDICATE) + ' ?new . }\n'
               '  FILTER(STR(?old) = ?oldLex && DATATYPE(?old) = ' + iri(DATATYPE)
               + ' && DATATYPE(?new) = ' + iri(DATATYPE) + ')\n')
    update = ('SPARQL DEFINE sql:log-enable 1\n'
            'DELETE { GRAPH ' + iri(ASSERTED) + ' { ?s ' + iri(PREDICATE) + ' ?old . } }\n'
            'INSERT { GRAPH ' + iri(ASSERTED) + ' { ?s ' + iri(PREDICATE) + ' ?new . } }\n'
            'WHERE {\n' + binding + '}')
    before = 'SPARQL SELECT (COUNT(?s) AS ?n) WHERE {\n' + binding + '}'
    subjects = ' '.join(iri(row['subject']) for row in sorted(plan['repairs'], key=lambda item: item['subject']))
    after = ('SPARQL SELECT (COUNT(?s) AS ?n) WHERE { VALUES ?s { ' + subjects + ' } '
             'GRAPH ' + iri(ASSERTED) + ' { ?s ' + iri(PREDICATE) + ' ?new } '
             'GRAPH ' + iri(STAGING) + ' { ?s ' + iri(PREDICATE) + ' ?new } }')
    quoted = lambda value: "'" + value.replace("'", "''") + "'"
    return ("CREATE PROCEDURE " + PROCEDURE + " ()\n{\n  DECLARE state, message, metadata, rows ANY;\n"
            "  DECLARE EXIT HANDLER FOR SQLSTATE '*' { ROLLBACK WORK; RESIGNAL; };\n"
            "  log_enable (1, 1);\n  state := '00000';\n"
            "  exec (" + quoted(before) + ", state, message, vector (), 0, metadata, rows);\n"
            "  IF (state <> '00000') SIGNAL (state, message);\n"
            "  IF (length (rows) <> 1 OR rows[0][0] <> 16) SIGNAL ('WK001', 'Expected exactly 16 guarded old terms');\n"
            "  state := '00000';\n"
            "  exec (" + quoted(update) + ", state, message, vector (), 0, metadata, rows);\n"
            "  IF (state <> '00000') SIGNAL (state, message);\n"
            "  state := '00000';\n"
            "  exec (" + quoted(after) + ", state, message, vector (), 0, metadata, rows);\n"
            "  IF (state <> '00000') SIGNAL (state, message);\n"
            "  IF (length (rows) <> 1 OR rows[0][0] <> 16) SIGNAL ('WK002', 'Expected exactly 16 stored replacements');\n"
            "  COMMIT WORK;\n  result_names (state);\n  result ('WKT_REPAIR_COMMITTED_16');\n};\n")


def canonical_repair_call():
    """Execute only after a separately checked successful procedure definition."""
    return PROCEDURE + ' ();\n'


def validate_original_closure(directory):
    # Lazy import permits the metadata assembler to reuse validate_certificate.
    from assemble_publication_metadata import verify_schedules
    directory = Path(directory)
    report = read(directory / 'materialization.json')
    require(report['status'] == 'fixed_point_reached', 'Original closure is incomplete')
    require(report['generator_sha256'] == GENERATOR_SHA256, 'Unclassified generator version')
    require(report['rules_sha256'] == RULES_SHA256 == digest(directory / 'rules.rq'),
            'Logical rules differ from the independently classified program')
    require(report['execution_rules_sha256'] == digest(directory / 'execution_rules.rq'),
            'Execution rule hash mismatch')
    names = re.findall(r'(?m)^# ([A-Za-z0-9_]+)$', (directory / 'rules.rq').read_text())
    require(len(names) == 27 and set(names) == set(RULE_COVERAGE), 'Unclassified logical rule')
    require(report['passes'] and report['passes'][-1]['new_triples'] == 0,
            'No complete final zero pass')
    verify_schedules(report, directory)
    for row in report['passes'][-1]['rules']:
        require(row['new_triples'] == 0 and row['batch_additions'] == [0],
                'Final rule/partition lacks its zero-addition batch')
    diagnostics = read(directory / 'contradiction_diagnostics.json')
    require(set(diagnostics) == {'complement_types', 'explicit_disjoint_types',
                               'nothing_members', 'pcr_extraction_role_clash'}
            and all(not value for value in diagnostics.values()), 'Original diagnostics failed')
    require(report['asserted_graph'] == ASSERTED and report['inferred_graph'] == INFERRED,
            'Wrong original release graphs')
    return report


def geometry_rows(endpoint, graph=ASSERTED, expected_count=71):
    query = ('SELECT ?subject (STR(?g) AS ?value) (STR(DATATYPE(?g)) AS ?datatype) '
             'WHERE { GRAPH ' + iri(graph) + ' { ?subject ' + iri(PREDICATE) + ' ?g } }')
    bindings = endpoint.query(query)['results']['bindings']
    rows = {}
    for item in bindings:
        subject = item['subject']['value']
        require(subject not in rows, 'Multiple live geometry values for one subject')
        rows[subject] = {key: item[key]['value'] for key in ('value', 'datatype')}
    require(len(rows) == expected_count, 'Unexpected live geometry inventory')
    return rows


def staged_geometry_gate(endpoint, source):
    rows = geometry_rows(endpoint, STAGING, 70)
    points = {subject: value for subject, value in source.items() if point(value['value']) is not None}
    require(set(rows) == set(points), 'Staged source point subjects differ')
    for subject, reference in points.items():
        actual = point(rows[subject]['value'])
        require(rows[subject]['datatype'] == DATATYPE and actual is not None
                and max(abs(a-b) for a, b in zip(actual, point(reference['value']))) <= COORDINATE_TOLERANCE,
                'Staged source point precision gate failed')
    return rows


def validate_schema_rows(outgoing, incoming):
    require(not incoming, 'asWKT participates in an incoming schema/reference statement')
    require(outgoing == {(RDF_TYPE, ANNOTATION_PROPERTY)},
            'asWKT is not isolated to its annotation-property declaration')


def schema_gate(endpoint):
    dataset = 'FROM ' + iri(ASSERTED) + ' FROM ' + iri(INFERRED)
    outgoing = endpoint.query('SELECT DISTINCT ?p ?o ' + dataset +
                              ' WHERE { ' + iri(PREDICATE) + ' ?p ?o }')['results']['bindings']
    incoming = endpoint.query('ASK ' + dataset + ' { ?s ?p ' + iri(PREDICATE) + ' }')['boolean']
    validate_schema_rows({(row['p']['value'], row['o']['value']) for row in outgoing}, incoming)
    require(not endpoint.query('ASK { GRAPH ' + iri(INFERRED) +
                               ' { ?s ' + iri(PREDICATE) + ' ?o } }')['boolean'],
            'Inferred asWKT facts require a different repair proof')


def preflight(endpoint, materialization_dir, source_audit, plan_path, source_sites):
    """Capture exact live preconditions before the administrator's repair."""
    report = validate_original_closure(materialization_dir)
    plan, source = read(plan_path), source_geometries(source_sites)
    validate_plan(plan, source)
    require(digest(source_sites) == plan['source_sha256'], 'Sites source hash mismatch')
    audit = read(source_audit)
    require(audit['status'] == 'passed' and audit['module_count'] == 16
            and audit['geometry_vocabulary_modules'] == ['rubalkhali_sites.owl']
            and audit['asWKT_object_occurrences'] == 0 and audit['asWKT_fact_count'] == 71,
            'Complete source-isolation audit required')
    records = {row['file']: row for row in audit['records']}
    require(len(audit['records']) == len(records) == 16
            and records['rubalkhali_sites.owl']['sha256'] == digest(source_sites),
            'Source audit does not bind the actual sites source')
    schema_gate(endpoint)
    rows = geometry_rows(endpoint)
    staged = staged_geometry_gate(endpoint, source)
    for repair in plan['repairs']:
        require(rows[repair['subject']] == repair['before'], 'Exact live old literal mismatch')
    values = ' '.join(iri(row['subject']) for row in plan['repairs'])
    old_query = ('ASK { VALUES ?site { ' + values + ' } GRAPH ' + iri(ASSERTED) +
                 ' { ?site ' + iri(PREDICATE) + ' ?old } GRAPH ' + iri(INFERRED) +
                 ' { ?s ?p ?old } }')
    # Bind actual stored old terms through their sites, never reparse old WKT.
    require(not endpoint.query(old_query)['boolean'], 'Old geometry object occurs in inferred delta')
    counts = {mode: endpoint.count(graph) for mode, graph in
              (('asserted', ASSERTED), ('inferred', INFERRED))}
    require(counts == {mode: report[mode + '_triples'] for mode in counts},
            'Graphs changed since original closure')
    return {'version': VERSION, 'status': 'passed', 'phase': 'preflight',
            'created_at': datetime.now(timezone.utc).isoformat(),
            'checker_sha256': digest(__file__),
            'materialization_report_sha256': digest(Path(materialization_dir) / 'materialization.json'),
            'source_audit_sha256': digest(source_audit), 'repair_plan_sha256': digest(plan_path),
            'source_sites_sha256': digest(source_sites), 'counts': counts,
            'before_geometry_facts': rows, 'old_object_query_sha256': hashlib.sha256(old_query.encode()).hexdigest(),
            'staging_graph': STAGING, 'staging_geometry_facts': staged,
            'old_geometry_objects_absent_from_inferred': True, 'annotation_schema_isolated': True}


def validate_geometry_transition(before, after, plan, source):
    require(set(before) == set(after) == set(source), 'Geometry subject inventory changed')
    replacements = {row['subject']: row for row in plan['repairs']}
    polygon_count = 0
    for subject, reference in source.items():
        require(after[subject]['datatype'] == before[subject]['datatype'] == DATATYPE,
                'Live geometry datatype mismatch')
        if subject in replacements:
            require(before[subject] == replacements[subject]['before'], 'Recorded old pair mismatch')
        else:
            require(before[subject] == after[subject], 'Unlisted geometry changed')
        original_point = point(reference['value'])
        if original_point is None:
            polygon_count += 1
            require(before[subject] == after[subject], 'Polygon was modified')
        else:
            actual = point(after[subject]['value'])
            require(actual is not None and max(abs(a-b) for a, b in zip(actual, original_point))
                    <= COORDINATE_TOLERANCE, 'Source coordinate precision gate failed')
    require(polygon_count == 1, 'Expected exactly one preserved polygon')


def checked_file(execution_path, record, key):
    path = (Path(execution_path).parent / record[key + '_file']).resolve()
    require(digest(path) == record[key + '_sha256'], 'Execution evidence hash mismatch: ' + key)
    return path


def certify(endpoint, materialization_dir, source_audit, plan_path, source_sites, execution_path):
    report = validate_original_closure(materialization_dir)
    plan, execution = read(plan_path), read(execution_path)
    source = source_geometries(source_sites)
    validate_plan(plan, source)
    require(execution['status'] == 'passed' and execution['exclusive_write_window'] is True,
            'Successful exclusive repair execution required')
    require(execution['procedure_absent_before_definition'] is True
            and execution['definition_checked_before_call'] is True,
            'Separate checked definition/call and absence precondition required')
    require(execution['asserted_graph'] == ASSERTED and execution['inferred_graph'] == INFERRED,
            'Execution graph mismatch')
    before_file = checked_file(execution_path, execution, 'preflight')
    before = read(before_file)
    require(before['version'] == VERSION and before['status'] == 'passed'
            and before['phase'] == 'preflight' and before['checker_sha256'] == digest(__file__),
            'Expected checker-produced successful preflight')
    for key, path in (('materialization_report', Path(materialization_dir) / 'materialization.json'),
                      ('repair_plan', plan_path), ('source_audit', source_audit),
                      ('source_sites', source_sites)):
        require(before[key + '_sha256'] == digest(path), 'Preflight input changed: ' + key)
    require(execution['repair_plan_sha256'] == digest(plan_path)
            and execution['materialization_report_sha256'] == before['materialization_report_sha256'],
            'Execution provenance differs from preflight')
    sql_file = checked_file(execution_path, execution, 'sql')
    require(sql_file.read_text() == canonical_repair_sql(plan), 'Transaction exceeds exact repair scope')
    sql_log = checked_file(execution_path, execution, 'sql_log')
    require(sql_log.stat().st_size > 0 and not re.search(r'\*\*\* Error|Virtuoso .* Error',
                                                      sql_log.read_text(), re.I), 'Repair definition failed')
    call_file = checked_file(execution_path, execution, 'call')
    require(call_file.read_text() == canonical_repair_call(), 'Unexpected repair invocation')
    call_log = checked_file(execution_path, execution, 'call_log')
    require('WKT_REPAIR_COMMITTED_16' in call_log.read_text()
            and not re.search(r'\*\*\* Error|Virtuoso .* Error', call_log.read_text(), re.I),
            'Repair invocation failed')
    schema_gate(endpoint)
    after = geometry_rows(endpoint)
    staged = staged_geometry_gate(endpoint, source)
    require(before['staging_graph'] == STAGING and before['staging_geometry_facts'] == staged,
            'Validated staged geometry terms changed during repair')
    validate_geometry_transition(before['before_geometry_facts'], after, plan, source)
    counts = {mode: endpoint.count(graph) for mode, graph in
              (('asserted', ASSERTED), ('inferred', INFERRED))}
    require(counts == before['counts'] == {mode: report[mode + '_triples'] for mode in counts},
            'Release graph counts changed')
    require(before['annotation_schema_isolated'] is True
            and before['old_geometry_objects_absent_from_inferred'] is True,
            'Missing pre-repair dependency check')
    certificate = {
        'version': VERSION, 'status': 'passed', 'created_at': datetime.now(timezone.utc).isoformat(),
        'checker_sha256': digest(__file__), 'materialization_report_sha256': before['materialization_report_sha256'],
        'rules_sha256': RULES_SHA256, 'generator_sha256': GENERATOR_SHA256,
        'source_audit_sha256': digest(source_audit), 'source_sites_sha256': digest(source_sites),
        'repair_plan_sha256': digest(plan_path), 'preflight_sha256': digest(before_file),
        'repair_execution_sha256': digest(execution_path), 'repair_sql_sha256': digest(sql_file),
        'repair_sql_log_sha256': digest(sql_log), 'asserted_graph': ASSERTED, 'inferred_graph': INFERRED,
        'repair_call_sha256': digest(call_file), 'repair_call_log_sha256': digest(call_log),
        'counts': counts, 'repairs_count': 16, 'geometry_fact_count': 71,
        'coordinate_tolerance': COORDINATE_TOLERANCE,
        'before_geometry_facts': before['before_geometry_facts'], 'after_geometry_facts': after,
        'staging_graph': STAGING, 'staging_geometry_facts': staged,
        'rule_coverage': RULE_COVERAGE, 'checks': {key: True for key in sorted(REQUIRED_CHECKS)},
        'proof': 'The exact changed facts have predicate geo:asWKT and literal objects. The complete hash-bound positive rule program has no body grounding that can use those facts under the verified isolated annotation schema. Every original inferred consequence therefore remains supported independently of the old WKT facts, and the replacements create no new rule consequence. The same exclusive inferred delta is the least fixed point for the repaired asserted input. Canonical guarded SQL changes only the 16 planned annotations; all 71 geometry subjects, the polygon, graph counts and inference ownership are checked.',
        'original_report_scope': 'The unchanged materialization report certifies the pre-repair input. This separate certificate extends its finite-rule closure result through the exact isolated-annotation repair; it does not claim complete OWL reasoning or rewrite the historical input identity.',
    }
    validate_certificate(certificate, before['materialization_report_sha256'], digest(plan_path), counts)
    return certificate


def validate_certificate(certificate, materialization_report_sha256, repair_plan_sha256, counts):
    """Reusable immutable pre-export gate; caller separately binds certificate file SHA."""
    require(set(certificate) == PUBLIC_FIELDS, 'Unknown/private or missing certificate fields')
    require(certificate['version'] == VERSION and certificate['status'] == 'passed', 'Certificate not passed')
    require(certificate['checker_sha256'] == digest(__file__), 'Certificate checker version mismatch')
    require(certificate['materialization_report_sha256'] == materialization_report_sha256
            and certificate['repair_plan_sha256'] == repair_plan_sha256, 'Certificate input hash mismatch')
    require(certificate['rules_sha256'] == RULES_SHA256 and certificate['generator_sha256'] == GENERATOR_SHA256,
            'Certificate rule program mismatch')
    require(certificate['rule_coverage'] == RULE_COVERAGE, 'Incomplete rule proof')
    require(set(certificate['checks']) == REQUIRED_CHECKS
            and all(value is True for value in certificate['checks'].values()), 'Certificate checks incomplete')
    require(certificate['asserted_graph'] == ASSERTED and certificate['inferred_graph'] == INFERRED
            and certificate['counts'] == counts, 'Certificate release graph mismatch')
    require(certificate['repairs_count'] == 16 and certificate['geometry_fact_count'] == 71
            and certificate['coordinate_tolerance'] == COORDINATE_TOLERANCE, 'Certificate repair scope mismatch')
    require(len(certificate['before_geometry_facts']) == len(certificate['after_geometry_facts']) == 71,
            'Missing geometry evidence')
    before, after = certificate['before_geometry_facts'], certificate['after_geometry_facts']
    require(set(before) == set(after), 'Certificate geometry subjects changed')
    changed = 0
    polygons = 0
    for subject, old in before.items():
        new = after[subject]
        require(set(old) == set(new) == {'value', 'datatype'}
                and old['datatype'] == new['datatype'] == DATATYPE,
                'Certificate geometry datatype or fields changed')
        if point(old['value']) is None:
            polygons += 1
            require(new == old and old['value'].startswith('POLYGON'),
                    'Certificate polygon changed')
        else:
            require(point(new['value']) is not None, 'Certificate point type changed')
        changed += old != new
    require(changed == 16 and polygons == 1, 'Certificate must change exactly 16 points')
    staged = certificate['staging_geometry_facts']
    require(certificate['staging_graph'] == STAGING and len(staged) == 70
            and set(staged) == {s for s, row in after.items() if point(row['value']) is not None},
            'Certificate staged geometry scope changed')
    for subject, row in staged.items():
        require(row == after[subject], 'Certificate after terms differ from validated staging terms')
    return certificate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--endpoint', required=True)
    parser.add_argument('--materialization-dir', type=Path, required=True)
    parser.add_argument('--source-audit', type=Path, required=True)
    parser.add_argument('--repair-plan', type=Path, required=True)
    parser.add_argument('--source-sites', type=Path, required=True)
    parser.add_argument('--repair-execution', type=Path)
    parser.add_argument('--preflight', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    require(args.preflight != bool(args.repair_execution), 'Select preflight or completed repair execution')
    endpoint = Endpoint(args.endpoint, [], 7200)
    parameters = (endpoint, args.materialization_dir, args.source_audit, args.repair_plan, args.source_sites)
    result = preflight(*parameters) if args.preflight else certify(*parameters, args.repair_execution)
    write_new(args.output, result)
    print(json.dumps({'status': result['status'], 'version': VERSION}), flush=True)


if __name__ == '__main__':
    main()
