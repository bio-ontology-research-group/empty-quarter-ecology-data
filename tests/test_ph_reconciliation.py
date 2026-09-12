"""Regression proof for the explicit Trip 4 physical-specimen correction."""
import copy
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest
from rdflib import Graph, URIRef
from rdflib.namespace import RDF, RDFS, OWL, DCTERMS

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts/rdf/generate_ph_dataset.py'
spec = importlib.util.spec_from_file_location('ph_reconciliation_generator', SCRIPT)
ph = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ph)
VERSION = ROOT / 'metadata/samples/ph/versions/EQ-PH-SHARED-v1.0.1'


def read_rows(path):
    with path.open() as handle:
        return list(csv.DictReader(handle, delimiter='\t'))


def generate(version, output, mapping=True):
    path = ROOT / 'metadata/samples/ph/versions' / version
    command = [sys.executable, str(SCRIPT), '--project-root', str(ROOT),
               '--workbook', str(path / 'ph_measurements.xlsx'), '--output-dir', str(output),
               '--as-of', '2026-08-03', '--dataset-version', version,
               '--dataset-status', 'FROZEN', '--dataset-purpose', 'shared-manuscripts',
               '--measurement-campaign-closed']
    if mapping:
        command += ['--specimen-reconciliation', str(path / 'trip4_specimen_reconciliation.tsv')]
    return subprocess.run(command, check=True, capture_output=True, text=True)


@pytest.fixture(scope='module')
def outputs(tmp_path_factory):
    directory = tmp_path_factory.mktemp('ph-correction')
    for name, version, mapping in (('old', 'EQ-PH-SHARED-v1.0.0', False),
                                   ('new', 'EQ-PH-SHARED-v1.0.1', True),
                                   ('repeat', 'EQ-PH-SHARED-v1.0.1', True)):
        generate(version, directory / name, mapping)
    return directory


def test_predecessor_workbook_and_generated_graph_are_preserved(outputs):
    old = ROOT / 'metadata/samples/ph/versions/EQ-PH-SHARED-v1.0.0/ph_measurements.xlsx'
    assert old.read_bytes() == (VERSION / 'ph_measurements.xlsx').read_bytes()
    assert hashlib.sha256(old.read_bytes()).hexdigest() == '701db2a771b257da09bb276c8ca29df4408ba5986bd515821ccea275a8c692c1'
    assert (outputs / 'old/kg/rubalkhali_ph_measurements.ttl').read_bytes() == (
        ROOT / 'data/processed/semantics/ontology/rubalkhali_ph_eq_ph_shared_v1_0_0.ttl').read_bytes()


def test_all_observations_and_admissions_preserved_with_exact_identity_counts(outputs):
    old = read_rows(outputs / 'old/normalized/ph_observation_audit.tsv')
    new = read_rows(outputs / 'new/normalized/ph_observation_audit.tsv')
    assert len(old) == len(new) == 1168
    changed = accepted_changed = 0
    for before, after in zip(old, new):
        assert {key: value for key, value in before.items() if key != 'specimen_iri'} == {
            key: after[key] for key in before if key != 'specimen_iri'}
        difference = before['specimen_iri'] != after['specimen_iri']
        changed += difference
        accepted_changed += difference and before['disposition'] == ph.ADMITTED
        if after['trip'] == '4' and after['ph_value']:
            assert after['confirmed_replicate'] == '2'
            assert after['confirmed_specimen_id'].endswith('r2')
        if after['trip'] == '4' and not after['ph_value']:
            assert after['confirmed_specimen_id'] == ''
            assert after['specimen_reconciliation_status'] == 'not_assayed_no_physical_assignment'
            assert before['specimen_iri'] == after['specimen_iri']
    assert (changed, accepted_changed) == (174, 155)
    assert sum(row['disposition'] == ph.ADMITTED for row in new) == 712


def test_exact620_physical_relations_and_stable_measurement_entities(outputs):
    old = Graph().parse(outputs / 'old/kg/rubalkhali_ph_measurements.ttl', format='turtle')
    new = Graph().parse(outputs / 'new/kg/rubalkhali_ph_measurements.ttl', format='turtle')
    for category in (ph.SIO.SIO_001054, ph.SIO.SIO_001089, ph.PATO.PATO_0001842):
        assert set(old.subjects(RDF.type, category)) == set(new.subjects(RDF.type, category))
        assert len(set(new.subjects(RDF.type, category))) == 712
    assert set(old.triples((None, ph.SIO.SIO_000300, None))) == set(new.triples((None, ph.SIO.SIO_000300, None)))
    predicates = {ph.SIO.SIO_000230, ph.SIO.SIO_000291, ph.SIO.SIO_000011, ph.SIO.SIO_000008}
    removed = {t for t in set(old) - set(new) if t[1] in predicates}
    added = {t for t in set(new) - set(old) if t[1] in predicates}
    assert len(removed) == len(added) == 620
    for predicate in predicates:
        assert sum(t[1] == predicate for t in removed) == sum(t[1] == predicate for t in added) == 155
    mapping = read_rows(VERSION / 'trip4_specimen_reconciliation.tsv')
    replacements = {URIRef(r['recorded_specimen_iri']): URIRef(r['confirmed_specimen_iri'])
                    for r in mapping if r['disposition'] == ph.ADMITTED}
    assert {(replacements.get(s, s), p, replacements.get(o, o)) for s, p, o in removed} == added
    ignored = {RDFS.label, DCTERMS.identifier, DCTERMS.title, DCTERMS.description}
    ontologies = set(old.subjects(RDF.type, OWL.Ontology)) | set(new.subjects(RDF.type, OWL.Ontology))
    remaining = (set(old) ^ set(new)) - removed - added
    assert all(p in ignored or s in ontologies for s, p, o in remaining)


def test_successor_turtle_and_normalized_outputs_repeat_byte_exactly(outputs):
    for relative in ('kg/rubalkhali_ph_measurements.ttl', 'kg/rubalkhali_ph_measurements.owl',
                     'normalized/ph_observation_audit.tsv', 'normalized/ph_accepted_measurements.tsv',
                     'normalized/ph_entity_registry.tsv', 'normalized/ph_measurement_sessions.tsv'):
        assert (outputs / 'new' / relative).read_bytes() == (outputs / 'repeat' / relative).read_bytes()


def test_successor_cannot_be_generated_without_explicit_mapping(tmp_path):
    with pytest.raises(subprocess.CalledProcessError):
        generate('EQ-PH-SHARED-v1.0.1', tmp_path / 'missing', mapping=False)


def test_mapping_hash_and_predecessor_version_are_enforced(tmp_path):
    manifest = json.loads((VERSION / 'manifest.json').read_text())
    mapping = tmp_path / 'mapping.tsv'
    mapping.write_bytes((VERSION / 'trip4_specimen_reconciliation.tsv').read_bytes() + b'\n')
    with pytest.raises(ValueError, match='mapping hash mismatch'):
        ph.apply_specimen_reconciliation([], mapping, manifest, {}, {}, manifest['source']['sha256'])
    manifest['dataset_version'] = 'EQ-PH-SHARED-v1.0.0'
    with pytest.raises(ValueError, match='restricted'):
        ph.apply_specimen_reconciliation([], mapping, manifest, {}, {}, manifest['source']['sha256'])
