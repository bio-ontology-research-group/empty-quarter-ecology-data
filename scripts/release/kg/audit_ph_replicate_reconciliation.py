#!/usr/bin/env python3
"""Audit frozen Trip 4 pH specimen links against the laboratory confirmation."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import re

from rdflib import Graph, Namespace, URIRef
from rdflib.namespace import DC

SIO = Namespace('http://semanticscience.org/resource/')
EVIDENCE_ID = 'EQ-PH-TRIP4-REPLICATE-CONFIRMATION-20260910'
FIELDS = ['source_sheet', 'source_row', 'sample_id', 'trip', 'site', 'compartment',
          'recorded_replicate', 'recorded_specimen_iri', 'confirmed_sample_id',
          'confirmed_replicate', 'confirmed_specimen_iri', 'disposition', 'evidence_id', 'application_status']


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_tsv(path):
    with path.open() as handle:
        return list(csv.DictReader(handle, delimiter='\t'))


def write_tsv(path, rows):
    with path.open('x') as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, delimiter='\t', lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    root, output = args.project_root, args.output_dir
    if output.exists():
        raise FileExistsError('Audit output must be new')
    inputs = {
        'sample_abox': root / 'data/processed/semantics/ontology/rubalkhali_samples.owl',
        'ph_abox': root / 'data/processed/semantics/ontology/rubalkhali_ph_eq_ph_shared_v1_0_0.ttl',
        'sample_ledger': root / 'data/release/sample_ledger.tsv',
        'observation_audit': root / 'metadata/ph/ph_observation_audit.tsv',
        'accepted_measurements': root / 'metadata/ph/ph_accepted_measurements.tsv',
    }
    samples = Graph().parse(inputs['sample_abox'], format='xml')
    ph = Graph().parse(inputs['ph_abox'], format='turtle')
    identifiers = {}
    for subject, label in samples.subject_objects(DC.identifier):
        if str(label) in identifiers:
            raise ValueError('Nonunique sample identifier')
        identifiers[str(label)] = subject
    ledger = {row['sample_id']: row for row in read_tsv(inputs['sample_ledger']) if row['trip'] == 'Trip4'}
    accepted = read_tsv(inputs['accepted_measurements'])
    rows = [row for row in read_tsv(inputs['observation_audit']) if row['trip'] == '4']
    if len(accepted) != 712 or len(rows) != 177:
        raise ValueError('Frozen source inventory changed')
    mapping, admitted, changed = [], [], []
    relation_counts = {str(predicate): 0 for predicate in
                       (SIO.SIO_000230, SIO.SIO_000291, SIO.SIO_000011, SIO.SIO_000008)}
    for row in rows:
        target_id = re.sub(r'r[123]$', 'r2', row['sample_id'])
        if target_id not in identifiers or target_id not in ledger:
            raise ValueError('Confirmed specimen absent: ' + target_id)
        if ledger[target_id]['site'] != row['site'] or ledger[target_id]['compartment'] != row['compartment']:
            raise ValueError('Confirmed specimen changes campaign/site/compartment')
        entry = {key: row[key] for key in ('source_sheet', 'source_row', 'sample_id', 'trip', 'site', 'compartment', 'disposition')}
        entry.update(recorded_replicate=row['replicate'], recorded_specimen_iri=row['specimen_iri'],
                     confirmed_sample_id=target_id, confirmed_replicate='2',
                     confirmed_specimen_iri=str(identifiers[target_id]), evidence_id=EVIDENCE_ID,
                     application_status=('assay_specimen_confirmed' if row['ph_value'] else
                                         'not_assayed_no_physical_assignment'))
        mapping.append(entry)
        if row['disposition'] != 'ADMITTED_MEASUREMENT':
            continue
        admitted.append(entry)
        if entry['recorded_specimen_iri'] == entry['confirmed_specimen_iri']:
            continue
        old = URIRef(row['specimen_iri'])
        for predicate in (SIO.SIO_000230, SIO.SIO_000291, SIO.SIO_000011):
            if len(list(ph.triples((None, predicate, old)))) != 1:
                raise ValueError('Unexpected frozen specimen relation inventory')
            relation_counts[str(predicate)] += 1
        if len(list(ph.triples((old, SIO.SIO_000008, None)))) != 1:
            raise ValueError('Unexpected frozen quality relation inventory')
        relation_counts[str(SIO.SIO_000008)] += 1
        changed.append(entry)
    if len(admitted) != 156 or len(changed) != 155:
        raise ValueError('Expected 156 accepted and 155 changed Trip 4 links')
    output.mkdir(parents=True)
    write_tsv(output / 'all_trip4_source_rows.tsv', mapping)
    write_tsv(output / 'accepted_trip4_specimen_mapping.tsv', admitted)
    confirmation = {
        'evidence_id': EVIDENCE_ID, 'confirmed_at': '2026-09-10T13:16:33Z',
        'source_role': 'Laboratory author reporting the laboratory operator confirmation',
        'fact': 'Field replicate 2 was used for every Trip 4 pH assay because replicate 1 had been depleted.',
        'supersedes': 'Earlier same-day replicate-1 assignment for the 14 July assays',
        'scope': 'Trip 4 physical specimen identity; original workbook cells and assay values remain preserved',
    }
    report = {
        'status': 'audited_correction_required', 'predecessor_version': 'EQ-PH-SHARED-v1.0.0',
        'successor_version': 'EQ-PH-SHARED-v1.0.1', 'confirmation': confirmation,
        'counts': {'all_accepted_measurements': 712, 'trip4_source_rows': 177,
                   'trip4_accepted_measurements': 156, 'accepted_specimen_identity_changes': 155,
                   'accepted_unchanged_rep2': 1, 'wrong_asserted_specimen_relations': 620,
                   'measured_source_row_identity_changes': 174,
                   'unassayed_rows_without_physical_assignment': 2},
        'unassayed_mapping_scope': 'The two unassayed rows retain their original specimen links; mapping targets are prospective replicate-2 identifiers, not assertions that an assay occurred.',
        'wrong_asserted_relation_counts': relation_counts,
        'deterministic_targets_complete': True, 'missing_targets': [],
        'unchanged_accepted_sample_id': 'S28Dr2',
        'semantic_assessment': 'The predecessor asserts physical specimen relations, not group-level associations. These SIO relations participate in inference. A fresh full materialization is required; the annotation-only WKT certificate does not cover this correction.',
        'inputs': {key: {'path': str(path.relative_to(root)), 'sha256': digest(path)} for key, path in inputs.items()},
        'outputs': {name: digest(output / name) for name in
                    ('all_trip4_source_rows.tsv', 'accepted_trip4_specimen_mapping.tsv')},
    }
    (output / 'confirmation.json').write_text(json.dumps(confirmation, indent=2, sort_keys=True) + '\n')
    (output / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    print(json.dumps(report['counts'], sort_keys=True))


if __name__ == '__main__':
    main()
