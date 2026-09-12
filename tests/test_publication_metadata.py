import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from rdflib import Graph, Namespace, URIRef

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts/release/kg'))
from wkt_certificate_fixtures import certificate_fixture
from materialize import rules_for
SPEC = importlib.util.spec_from_file_location("publication", ROOT / "scripts/release/kg/assemble_publication_metadata.py")
PUBLICATION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PUBLICATION)


class PublicationMetadataTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.output = self.root / "prepared"
        self.artifacts = self.root / "publication/kg/3.0.0"
        self.artifacts.mkdir(parents=True)
        self.materialization = self.root / "materialization-batched"
        self.materialization.mkdir()
        self.exports_path = self.root / "evidence/graph_exports/report.json"
        self.exports_path.parent.mkdir(parents=True)
        self.attribution_path = self.root / "attribution.json"
        self.export_fixture_path = self.root / "export-fixture-report.json"
        self.repair_certificate_path = self.root / 'wkt-closure-preservation.json'
        self.repair_plan_path = self.root / 'wkt-repair-plan.json'
        self.repair_plan_path.write_text('{}')
        self.source_audit_path = self.root / 'geometry_rule_source_audit.json'
        self.source_audit_path.write_text('{}')
        self.export_fixture_path.write_text(json.dumps(dict(passed=True, triples=6, binary64_preserved=True,
                                                          blank_nodes_unicode_language_preserved=True, wkt_datatype_preserved=True)))
        archives = {}
        for kind in ("source", "modules"):
            path = self.artifacts / f"rubalkhali-kg-3.0.0-{kind}.tar.gz"
            path.write_bytes(kind.encode())
            archives[kind] = (path.stat().st_size, PUBLICATION.sha256(path))
        self.archives = archives
        self.patcher = patch.object(PUBLICATION, "ARCHIVES", archives)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        counts = {"asserted": 45706821, "inferred": 10, "materialized": 45706831}
        files = []
        for mode in PUBLICATION.MODES:
            name = f"rubalkhali-kg-3.0.0-{mode}.nq.gz"
            path = self.artifacts / name
            path.write_bytes(mode.encode())
            files.append(dict(name=name, url=PUBLICATION.DOWNLOAD + name, bytes=path.stat().st_size,
                              sha256=PUBLICATION.sha256(path), uncompressed_sha256="a" * 64,
                              triples=counts[mode], graph=PUBLICATION.GRAPHS[mode]))
        self.exports = dict(passed=True, version="3.0.0", counts=counts, asserted_missing_from_union=0, inferred_missing_from_union=0,
                            files=files, rdf_syntax_validation="pending; synthetic fixture")
        schema = Graph().parse(data='''
            @prefix : <urn:fixture:> .
            @prefix owl: <http://www.w3.org/2002/07/owl#> .
            :a owl:propertyChainAxiom (:p :q) .
            :b owl:propertyChainAxiom (:p :q :r) .
            :c owl:propertyChainAxiom ([owl:inverseOf :p] :q) .
            :d owl:propertyChainAxiom (:p [owl:inverseOf :q]) .
        ''', format='turtle')
        self.rules = rules_for(schema)
        self.program = '\n\n'.join('# ' + rule.name + '\n' + rule.update(
            PUBLICATION.GRAPHS['asserted'], PUBLICATION.GRAPHS['inferred']) for rule in self.rules) + '\n'
        for name in ("rules.rq", "execution_rules.rq"):
            (self.materialization / name).write_text(self.program)
        self.report = dict(status="fixed_point_reached", asserted_graph=PUBLICATION.GRAPHS["asserted"],
                           software={"python": "3.8.10", "rdflib": "4.2.2"}, batch_size=500000,
                           inferred_graph=PUBLICATION.GRAPHS["inferred"], asserted_triples=counts["asserted"],
                           inferred_triples=counts["inferred"], asserted_plus_inferred_triples=counts["materialized"],
                           passes=[dict(new_triples=0, rules=[dict(name=rule.name, new_triples=0) for rule in self.rules])],
                           program_version="synthetic", scope_limits={"scope": "synthetic only"},
                           generator_sha256=PUBLICATION.sha256(ROOT / "scripts/release/kg/materialize.py"),
                           rules_sha256=PUBLICATION.sha256(self.materialization / "rules.rq"),
                           execution_rules_sha256=PUBLICATION.sha256(self.materialization / "execution_rules.rq"))
        self.diagnostics = {name: [] for name in ("complement_types", "explicit_disjoint_types", "nothing_members", "pcr_extraction_role_clash")}
        attribution = dict(passed=True, archive_sha256=archives["modules"][1],
                           reference_attribution=[dict(file=name, explicit_licence_annotations=[]) for name in ("sio.owl", "envo.owl", "pato.owl", "uo.owl")])
        self.attribution_path.write_text(json.dumps(attribution))
        self.write_reports()

    def write_reports(self):
        (self.materialization / "materialization.json").write_text(json.dumps(self.report))
        (self.materialization / "contradiction_diagnostics.json").write_text(json.dumps(self.diagnostics))
        report_sha = PUBLICATION.sha256(self.materialization / 'materialization.json')
        plan_sha = PUBLICATION.sha256(self.repair_plan_path)
        certificate = certificate_fixture({'asserted': 45706821, 'inferred': 10}, report_sha, plan_sha)
        certificate['source_audit_sha256'] = PUBLICATION.sha256(self.source_audit_path)
        self.repair_certificate_path.write_text(json.dumps(certificate))
        self.exports.update(materialization_report_sha256=report_sha,
                            coordinate_repair_plan_sha256=plan_sha,
                            coordinate_repair_certificate_sha256=PUBLICATION.sha256(self.repair_certificate_path))
        self.exports_path.write_text(json.dumps(self.exports))

    def assemble(self):
        return PUBLICATION.assemble(self.root, self.output, self.attribution_path, "2026-09-10T00:00:00Z",
                                    export_fixture_path=self.export_fixture_path,
                                    repair_certificate_path=self.repair_certificate_path,
                                    repair_plan_path=self.repair_plan_path, source_audit_path=self.source_audit_path)

    def test_complete_fixture_emits_five_artifacts_without_publication(self):
        before = {p.name: p.read_bytes() for p in self.artifacts.iterdir()}
        result = self.assemble()
        self.assertEqual(5, len(result["files"]))
        self.assertEqual(PUBLICATION.GRAPHS, result["graphs"])
        self.assertEqual(PUBLICATION.DOWNLOAD + "validation.json", result["validation_url"])
        self.assertEqual(PUBLICATION.DOWNLOAD + 'wkt-closure-preservation.json',
                         result['coordinate_import']['certificate_url'])
        self.assertEqual(self.repair_certificate_path.read_bytes(),
                         (self.output / 'wkt-closure-preservation.json').read_bytes())
        self.assertEqual(5, len(result['coordinate_import']['verification_code']))
        for item in result['coordinate_import']['verification_code']:
            self.assertEqual(item['sha256'], PUBLICATION.sha256(self.output / item['name']))
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.artifacts.iterdir()})
        self.assertIsNone(result["project_data_licence"])
        self.assertFalse(result["query_time_inference"])
        self.assertEqual("pending; synthetic fixture", result["evidence"]["rdf_syntax_validation"])
        graph = Graph().parse(str(self.output / "service-description.ttl"), format="turtle")
        sd = Namespace("http://www.w3.org/ns/sparql-service-description#")
        self.assertEqual({URIRef(PUBLICATION.GRAPHS["asserted"])}, set(graph.objects(None, sd.defaultGraph)))
        self.assertEqual(3, len(list(graph.objects(None, sd.namedGraph))))
        readme = (self.output / "README.md").read_text()
        self.assertIn("--batch-size 500000", readme)
        self.assertIn("TransactionAfterImageLimit=250000000", readme)
        self.assertIn("sys_stat('txn_after_image_limit')", readme)
        self.assertEqual(250000000, result["reasoning"]["runtime"]["engine"]["transaction_after_image_limit_bytes"])
        self.assertIn("--materialization-dir RELEASE_ROOT/materialization-transaction-cap", readme)
        self.assertNotIn("All16", result["serialization_provenance"])
        self.assertIn("tolerance 1e-17", result["evidence"]["native_export_fixture"]["scope"])

    def test_failed_or_partial_closure_rejected(self):
        self.report["status"] = "failed"
        self.write_reports()
        with self.assertRaisesRegex(ValueError, "fixed point"):
            self.assemble()
        self.report["status"] = "fixed_point_reached"
        self.report["passes"][-1]["rules"][0]["new_triples"] = 1
        self.write_reports()
        with self.assertRaisesRegex(ValueError, "Every rule"):
            self.assemble()
        self.assertFalse(self.output.exists())

    def test_old_asserted_metadata_count_rejected(self):
        self.report["asserted_triples"] += 1
        self.write_reports()
        with self.assertRaisesRegex(ValueError, "Corrected frozen asserted"):
            self.assemble()

    def test_missing_inferred_union_gate_rejected(self):
        del self.exports["inferred_missing_from_union"]
        self.write_reports()
        with self.assertRaisesRegex(ValueError, "Export union"):
            self.assemble()

    def test_artifact_tampering_rejected(self):
        (self.artifacts / "rubalkhali-kg-3.0.0-source.tar.gz").write_bytes(b"tampered")
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            self.assemble()

    def test_missing_coordinate_repair_proof_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Separate coordinate repair'):
            PUBLICATION.assemble(self.root, self.output, self.attribution_path,
                                 '2026-09-10T00:00:00Z', export_fixture_path=self.export_fixture_path)

    def test_coordinate_certificate_bytes_bound_to_exports(self):
        with self.repair_certificate_path.open('a') as handle:
            handle.write('\n')
        with self.assertRaisesRegex(ValueError, 'different coordinate repair'):
            self.assemble()

    def test_failed_coordinate_certificate_rejected(self):
        certificate = json.loads(self.repair_certificate_path.read_text())
        certificate['status'] = 'failed'
        self.repair_certificate_path.write_text(json.dumps(certificate))
        with self.assertRaisesRegex(ValueError, 'Certificate not passed'):
            self.assemble()

    def test_changed_source_isolation_audit_rejected(self):
        self.source_audit_path.write_text('{"changed": true}')
        with self.assertRaisesRegex(ValueError, 'Source-isolation audit differs'):
            self.assemble()

    def test_rule_tampering_and_diagnostic_omission_rejected(self):
        (self.materialization / "rules.rq").write_text("different rule")
        with self.assertRaisesRegex(ValueError, "Rule-source hash"):
            self.assemble()
        self.diagnostics = {}
        self.write_reports()
        with self.assertRaisesRegex(ValueError, "Complete monitored"):
            self.assemble()

    def test_publication_output_and_overwrite_rejected(self):
        self.output = self.artifacts / "new-metadata"
        with self.assertRaisesRegex(ValueError, "outside the publication"):
            self.assemble()
        self.output = self.root / "existing"
        self.output.mkdir()
        with self.assertRaisesRegex(ValueError, "must be new"):
            self.assemble()

    def test_changing_class_partitions_require_each_pass_complete_inventory(self):
        import hashlib
        self.report["passes"] = []
        (self.materialization / "rules.rq").write_text(self.program)
        self.report["rules_sha256"] = PUBLICATION.sha256(self.materialization / "rules.rq")
        partition_dir = self.materialization / "execution_partitions"
        partition_dir.mkdir()
        for iteration, classes in enumerate((["urn:class:A"], ["urn:class:A", "urn:class:B"]), 1):
            names = ["subclass_type_named_" + hashlib.sha256(c.encode()).hexdigest()[:16] for c in classes]
            program = "\n".join("# " + name for name in names) + "\n"
            query = partition_dir / f"iteration_{iteration:04d}.rq"
            query.write_text(program)
            inventory = dict(named_classes=classes, anonymous_class_partition=False, query_sha256=PUBLICATION.sha256(query))
            (partition_dir / f"iteration_{iteration:04d}.json").write_text(json.dumps(inventory))
            scheduled = []
            for rule in self.rules:
                scheduled.extend(names if rule.name == 'subclass_type' else [rule.name])
            self.report["passes"].append(dict(iteration=iteration, new_triples=0,
                                              rules=[dict(name=name, new_triples=0) for name in scheduled],
                                              subclass_type_partitions=inventory))
        self.write_reports()
        result = self.assemble()
        self.assertEqual(4, len(result["reasoning"]["execution_partition_files"]))
        self.output = self.root / "bad-partitions"
        self.report["passes"][-1]["rules"].pop()
        self.write_reports()
        with self.assertRaisesRegex(ValueError, "complete logical rule schedule"):
            self.assemble()


if __name__ == "__main__":
    unittest.main()
