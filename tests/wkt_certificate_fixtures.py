"""Synthetic certificate for release gate unit tests; never real release evidence."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts/release/kg'))
import certify_wkt_repair as cert


def certificate_fixture(counts, materialization_report_sha256, repair_plan_sha256):
    before, after = {}, {}
    for index in range(1, 71):
        subject = 'urn:fixture:site:' + str(index)
        after[subject] = {'value': f'POINT({50 + index/10} {20 + index/100})', 'datatype': cert.DATATYPE}
        before[subject] = dict(after[subject])
        if index <= 16:
            before[subject]['value'] = f'POINT({50 + index/10 + 0.000001} {20 + index/100})'
    polygon = {'value': 'POLYGON((0 0, 1 0, 1 1, 0 0))', 'datatype': cert.DATATYPE}
    before['urn:fixture:polygon'] = dict(polygon)
    after['urn:fixture:polygon'] = dict(polygon)
    record = {key: 'a' * 64 for key in cert.PUBLIC_FIELDS}
    record.update(version=cert.VERSION, status='passed', checker_sha256=cert.digest(cert.__file__),
                  materialization_report_sha256=materialization_report_sha256,
                  repair_plan_sha256=repair_plan_sha256,
                  rules_sha256=cert.RULES_SHA256, generator_sha256=cert.GENERATOR_SHA256,
                  asserted_graph=cert.ASSERTED, inferred_graph=cert.INFERRED,
                  counts=counts, repairs_count=16, geometry_fact_count=71, coordinate_tolerance=1e-10,
                  before_geometry_facts=before, after_geometry_facts=after,
                  staging_graph=cert.STAGING,
                  staging_geometry_facts={s: r for s, r in after.items() if cert.point(r['value']) is not None},
                  rule_coverage=cert.RULE_COVERAGE,
                  checks={key: True for key in cert.REQUIRED_CHECKS},
                  created_at='2026-09-10T00:00:00Z',
                  proof='SYNTHETIC TEST FIXTURE', original_report_scope='SYNTHETIC TEST FIXTURE')
    cert.validate_certificate(record, materialization_report_sha256, repair_plan_sha256, counts)
    return record
