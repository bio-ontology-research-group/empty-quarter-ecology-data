#!/usr/bin/env python3
"""Prepare KG 3.0.0 publication metadata locally; never publish or mutate graphs."""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import shutil

from rdflib import Graph, Literal, Namespace, RDF, URIRef
from finalize_graphs import repair_evidence

VERSION = "3.0.0"
RELEASE = "https://rubalkhali.science/kb/v3.0.0/"
DOWNLOAD = "/downloads/kg/3.0.0/"
MODES = ("asserted", "inferred", "materialized")
GRAPHS = {mode: "https://rubalkhali.science/graph/" + mode + "/3.0.0" for mode in MODES}
ARCHIVES = {
    "source": (128991713, "320ecfe3e26dce4b378ef233e78f9256829b08e9343eda300fd73533a8afeb26"),
    "modules": (372519738, "7dcbeb447831e9af25973f9a4fac8376ef7d1564abc85e0118edd87baa39f974"),
}
SEMANTICS = {
    "asserted": "Deduplicated union of 16 manifested scientific and pinned reference RDF modules.",
    "inferred": "Exclusive delta: consequences of the recorded finite positive rule program absent from the asserted graph.",
    "materialized": "Deduplicated asserted-plus-inferred union; stored triples are served without query-time inference.",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read(path):
    return json.loads(path.read_text())


def verify_schedules(materialization, directory):
    """Check each executed schedule against logical rules and its own inventory."""
    logical = re.findall(r"(?m)^# ([A-Za-z0-9_]+)$", (directory / "rules.rq").read_text())
    require(logical and len(logical) == len(set(logical)), "Unique logical rule inventory required")
    partition_files = []
    for row in materialization["passes"]:
        expected = list(logical)
        inventory = row.get("subclass_type_partitions")
        if inventory is not None:
            require("subclass_type" in logical, "Partitions have no corresponding logical rule")
            classes = inventory["named_classes"]
            require(classes == sorted(set(classes)), "Named partition inventory must be sorted and unique")
            names = ["subclass_type_named_" + hashlib.sha256(c.encode()).hexdigest()[:16] for c in classes]
            if inventory["anonymous_class_partition"]:
                names.append("subclass_type_anonymous")
            index = expected.index("subclass_type")
            expected[index:index + 1] = names
            stem = f"execution_partitions/iteration_{row['iteration']:04d}"
            metadata_path, query_path = directory / (stem + ".json"), directory / (stem + ".rq")
            require(read(metadata_path) == inventory, "Partition inventory differs from completed report")
            require(sha256(query_path) == inventory["query_sha256"], "Partition query hash mismatch")
            require(re.findall(r"(?m)^# ([A-Za-z0-9_]+)$", query_path.read_text()) == names,
                    "Partition queries do not match recorded active-class inventory")
            partition_files.extend((metadata_path, query_path))
        require([rule["name"] for rule in row["rules"]] == expected,
                "Executed pass does not cover the complete logical rule schedule")
    return partition_files


def assemble(root, output, attribution_path, released_at, default_graph="asserted", materialization_dir=None, export_fixture_path=None,
             repair_certificate_path=None, repair_plan_path=None, source_audit_path=None):
    root, output = root.resolve(), output.resolve()
    publication = root / "publication"
    require(not output.exists(), "Output directory must be new")
    require(output != publication and publication not in output.parents,
            "Metadata must be prepared outside the publication tree")
    require(datetime.fromisoformat(released_at.replace("Z", "+00:00")).tzinfo is not None,
            "Explicit timezone required for release timestamp")
    exports_path = root / "evidence/graph_exports/report.json"
    materialization_dir = (materialization_dir or root / "materialization-batched").resolve()
    require(materialization_dir.parent == root, "Materialization evidence must belong to this release workspace")
    materialization_path = materialization_dir / "materialization.json"
    exports, materialization = read(exports_path), read(materialization_path)
    runtime_path = Path(__file__).with_name("inference_runtime.json")
    runtime = read(runtime_path)
    browser_runtime_path = Path(__file__).with_name("browser_runtime.json")
    require(all(materialization.get("software", {}).get(key) == runtime["controller"][key] for key in ("python", "rdflib")),
            "Completed controller runtime differs from recorded inference runtime")
    require(materialization.get("batch_size") == runtime["engine"]["batch_size"], "Materialization batch differs from runtime record")
    require(exports.get("passed") is True and exports.get("version") == VERSION, "Successful versioned export report required")
    require(materialization.get("status") == "fixed_point_reached", "Completed fixed point required")
    passes = materialization.get("passes", [])
    require(passes and passes[-1]["new_triples"] == 0, "Final complete zero-addition pass required")
    require(passes[-1].get("rules") and all(r["new_triples"] == 0 for r in passes[-1]["rules"]),
            "Every rule must add zero triples in the final pass")
    diagnostics = read(materialization_dir / "contradiction_diagnostics.json")
    require(set(diagnostics) == {"complement_types", "explicit_disjoint_types", "nothing_members", "pcr_extraction_role_clash"},
            "Complete monitored contradiction diagnostics required")
    require(all(not rows for rows in diagnostics.values()),
            "Monitored contradiction diagnostics must be empty")
    require(sha256(Path(__file__).with_name("materialize.py")) == materialization["generator_sha256"],
            "Current materializer source does not match the completed report")
    counts = {mode: materialization[mode + "_triples"] for mode in ("asserted", "inferred")}
    require(counts["asserted"] == 45706821 and counts["inferred"] >= 0, "Corrected frozen asserted count required")
    counts["materialized"] = sum(counts.values())
    require(materialization["asserted_plus_inferred_triples"] == counts["materialized"], "Materialized count mismatch")
    require(exports["counts"] == counts and exports["asserted_missing_from_union"] == 0 and
            exports.get("inferred_missing_from_union") == 0, "Export union checks failed")
    for mode in ("asserted", "inferred"):
        require(materialization[mode + "_graph"] == GRAPHS[mode], "Wrong versioned graph")
    for filename, key in (("rules.rq", "rules_sha256"), ("execution_rules.rq", "execution_rules_sha256")):
        require(sha256(materialization_dir / filename) == materialization[key], "Rule-source hash mismatch: " + filename)
    partition_files = verify_schedules(materialization, materialization_dir)
    require(repair_certificate_path is not None and repair_plan_path is not None and source_audit_path is not None,
            "Separate coordinate repair certificate and plan required")
    repair_hashes = repair_evidence(materialization_path, repair_certificate_path, repair_plan_path)
    certificate = read(repair_certificate_path)
    require(sha256(source_audit_path) == certificate['source_audit_sha256'],
            'Source-isolation audit differs from coordinate certificate')
    require(all(exports.get(key) == value for key, value in repair_hashes.items()),
            "Export evidence belongs to a different coordinate repair or original closure")
    verification_code = []
    for name in ('certify_wkt_repair.py', 'audit_geometry_rule_reachability.py',
                 'assemble_publication_metadata.py', 'finalize_graphs.py', 'kg_admin.py'):
        path = Path(__file__).with_name(name)
        verification_code.append({'name': name, 'url': DOWNLOAD + name, 'sha256': sha256(path)})
    require(verification_code[0]['sha256'] == certificate['checker_sha256'],
            'Published checker source differs from the successful certificate')
    directory = publication / "kg/3.0.0"
    files = []
    for kind, (size, digest) in ARCHIVES.items():
        name = "rubalkhali-kg-3.0.0-" + kind + ".tar.gz"
        files.append(dict(name=name, url=DOWNLOAD + name, bytes=size, sha256=digest,
                          media_type="application/gzip", kind=kind,
                          description="Frozen scientific source tables, exact producer code and pinned environments; includes rebuild instructions." if kind == "source" else "Sixteen RDF modules, pinned reference ontologies, manifest, checksums and offline catalogue."))
    require(len(exports.get("files", [])) == 3, "Exactly three graph exports required")
    by_name = {row["name"]: row for row in exports["files"]}
    require(len(by_name) == 3, "Duplicate graph export")
    for mode in MODES:
        name = "rubalkhali-kg-3.0.0-" + mode + ".nq.gz"
        row = dict(by_name[name])
        require(row["url"] == DOWNLOAD + name and row["graph"] == GRAPHS[mode], "Noncanonical graph download")
        require(row["triples"] == counts[mode], "Export triple count mismatch")
        require(len(row["uncompressed_sha256"]) == 64, "Missing uncompressed export hash")
        row.update(kind=mode, media_type="application/gzip", description=SEMANTICS[mode])
        files.append(row)
    for row in files:
        path = directory / row["name"]
        require(path.is_file() and not path.is_symlink(), "Artifact must be a regular file: " + row["name"])
        require(path.stat().st_size == row["bytes"] and sha256(path) == row["sha256"], "Artifact checksum mismatch: " + row["name"])
    audit = read(attribution_path)
    require(audit.get("passed") is True and audit.get("archive_sha256") == ARCHIVES["modules"][1], "Reference attribution must come from the verified module archive")
    attribution = audit["reference_attribution"]
    require({row["file"] for row in attribution} == {"sio.owl", "envo.owl", "pato.owl", "uo.owl"}, "Four pinned reference records required")
    require(export_fixture_path is not None, "Native export fixture evidence required")
    fixture = read(export_fixture_path)
    require(fixture.get("passed") is True and fixture.get("triples") == 6 and
            all(fixture.get(key) is True for key in ("binary64_preserved", "blank_nodes_unicode_language_preserved", "wkt_datatype_preserved")),
            "Native export fixture did not pass its declared six-triple scope")
    manifest = dict(version=VERSION, version_iri=RELEASE, released_at=released_at,
                    metadata_status="Metadata assembled from completed reports; actual HTTP/query-gate evidence is provided separately at validation.json.",
                    validation_url=DOWNLOAD + "validation.json",
                    files=files, counts=counts, graphs=GRAPHS, graph_semantics=SEMANTICS, query_time_inference=False,
                    query_contract="SPARQL and API defaults use asserted data. Explicit protocol dataset or FROM selection is honored. API mode=materialized selects the union unless an explicit dataset overrides it.",
                    project_data_licence=None, licence_statement="No new licence is granted. Project-data licence has not been assigned; preserve existing third-party terms and annotations.",
                    third_party_reference_annotations=attribution,
                    reasoning=dict(program_version=materialization["program_version"], status=materialization["status"],
                                   software=materialization["software"], runtime=runtime, runtime_sha256=sha256(runtime_path),
                                   rules_sha256=materialization["rules_sha256"], execution_rules_sha256=materialization["execution_rules_sha256"],
                                   generator_sha256=materialization["generator_sha256"], passes=len(passes),
                                   execution_partition_files=[{"path": str(path.relative_to(materialization_dir)), "sha256": sha256(path)} for path in partition_files],
                                   scope_limits=materialization["scope_limits"], completeness="Least fixed point of the recorded finite rule program only; not full OWL-Horst, OWL 2 RL, EL or DL reasoning or complete consistency."),
                    reproducibility_scope="KG regeneration from frozen scientific tables. This does not reconstruct raw-read processing, establish unknown historical physical runs, or grant access to unavailable public sequencing records.",
                    coordinate_import=dict(certificate_url=DOWNLOAD + "wkt-closure-preservation.json",
                                           certificate_sha256=repair_hashes['coordinate_repair_certificate_sha256'],
                                           repair_plan_url=DOWNLOAD + "wkt-repair-plan.json",
                                           repair_plan_sha256=repair_hashes['coordinate_repair_plan_sha256'],
                                           source_audit_url=DOWNLOAD + 'geometry_rule_source_audit.json',
                                           source_audit_sha256=sha256(source_audit_path),
                                           verification_code=verification_code,
                                           adapter="scripts/release/kg/prepare_wkt_import.py in the verified source archive",
                                           scope="Original module bytes and coordinate digits are retained. Import uses a separately hashed POINT-whitespace adapter to preserve numerical geometry. The original materialization report describes pre-repair input; the separate certificate proves closure preservation through the exact 16-annotation repair."),
                    serialization_provenance="All 16 original module hashes were reproduced from the frozen source package. Native engine N-Quads use engine-assigned blank-node identifiers/order and canonical literal spellings, including doubles and WKT. Export hashes verify the released bytes, not identical N-Quads bytes across fresh database imports. Graph semantics and the recorded finite closure, rather than native serialization order, are the reconstruction target.",
                    evidence={"graph_exports_report_sha256": sha256(exports_path), "materialization_report_sha256": sha256(materialization_path),
                              "browser_acceptance_runtime": read(browser_runtime_path), "browser_runtime_sha256": sha256(browser_runtime_path),
                              "reference_annotation_audit_sha256": sha256(attribution_path),
                              "native_export_fixture": {"sha256": sha256(export_fixture_path), "result": fixture,
                                                        "scope": "Six triples; binary64 value equality and precision tolerance 1e-17, WKT POINT whitespace normalized for comparison, Unicode, language tags and blank-node structure. Not a full-graph literal-value proof."},
                              "rdf_syntax_validation": exports.get("rdf_syntax_validation", "not reported"),
                              "http_download_validation": "not performed by this assembler"})
    if default_graph:
        require(default_graph in MODES, "Unknown default graph")
        manifest["default_graph"] = GRAPHS[default_graph]
    output.mkdir(parents=True)
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (output / "SHA256SUMS").write_text("".join(row["sha256"] + "  " + row["name"] + "\n" for row in files))
    for name in ("rules.rq", "execution_rules.rq"):
        shutil.copyfile(materialization_dir / name, output / name)
    for path in partition_files:
        target = output / path.relative_to(materialization_dir)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    (output / "THIRD_PARTY_ATTRIBUTIONS.json").write_text(json.dumps(attribution, indent=2) + "\n")
    shutil.copyfile(runtime_path, output / "inference_runtime.json")
    shutil.copyfile(browser_runtime_path, output / "browser_runtime.json")
    shutil.copyfile(repair_certificate_path, output / "wkt-closure-preservation.json")
    shutil.copyfile(repair_plan_path, output / "wkt-repair-plan.json")
    shutil.copyfile(source_audit_path, output / 'geometry_rule_source_audit.json')
    for row in verification_code:
        shutil.copyfile(Path(__file__).with_name(row['name']), output / row['name'])
    service_description(manifest, output / "service-description.ttl")
    (output / "README.md").write_text(release_readme(manifest))
    return manifest


def service_description(manifest, path):
    sd, dct, void = Namespace("http://www.w3.org/ns/sparql-service-description#"), Namespace("http://purl.org/dc/terms/"), Namespace("http://rdfs.org/ns/void#")
    graph = Graph()
    for prefix, namespace in (("sd", sd), ("dcterms", dct), ("void", void)):
        graph.bind(prefix, namespace)
    service, dataset = URIRef(RELEASE + "service"), URIRef(RELEASE)
    graph.add((service, RDF.type, sd.Service))
    graph.add((service, sd.endpoint, URIRef("https://rubalkhali.science/sparql")))
    graph.add((service, sd.supportedLanguage, sd.SPARQL11Query))
    graph.add((service, sd.defaultDataset, dataset))
    graph.add((service, dct.description, Literal("Stored versioned graphs; no query-time inference. Metadata prepared for this release; this file alone does not verify deployment.")))
    graph.add((dataset, RDF.type, sd.Dataset))
    for mode in MODES:
        named, data = URIRef(RELEASE + "named-graph/" + mode), URIRef(GRAPHS[mode])
        graph.add((dataset, sd.namedGraph, named))
        graph.add((named, sd.name, data))
        graph.add((named, sd.graph, data))
        graph.add((data, RDF.type, sd.Graph))
        graph.add((data, void.triples, Literal(manifest["counts"][mode])))
        graph.add((data, dct.description, Literal(SEMANTICS[mode])))
    if "default_graph" in manifest:
        graph.add((dataset, sd.defaultGraph, URIRef(manifest["default_graph"])))
    graph.serialize(str(path), format="turtle")


def release_readme(manifest):
    inventory = "\n".join("- [" + row["name"] + "](" + row["url"] + "): " + row["description"] for row in manifest["files"])
    return f"""# Rub' al-Khali knowledge graph 3.0.0

Version IRI: `{RELEASE}`. Release timestamp: `{manifest['released_at']}`.
The version and download paths are fixed; rebuilding does not increment them.
Do not replace an already published release with different bytes.

## Downloads

{inventory}

`manifest.json` records byte counts, SHA-256 values and graph cardinalities.
After downloading the five files and `SHA256SUMS` into one directory, run
`sha256sum -c SHA256SUMS`. N-Quads exports preserve their versioned graph names.
The inferred graph is an exclusive delta, not a standalone complete dataset.
The materialized graph is the deduplicated asserted-plus-delta union.
All 16 original module bytes were reproduced from the frozen source package.
Native engine N-Quads have engine-assigned blank-node identifiers and ordering;
the engine also uses canonical literal spellings, including doubles and WKT.
Before importing original site XML or downloaded native N-Quads, use the
source bundle's `scripts/release/kg/prepare_wkt_import.py` as documented in
`scripts/release/kg/WKT_IMPORT.md`. This creates a separate hashed loader
copy that avoids the engine's short-token POINT binary32 storage path.
Original source and download bytes remain unchanged. The all-70-site import
and native-export reload fixture passes the unchanged 1e-10 degree gate
only with this adapter; unadapted loading loses precision for 16 sites.
Download hashes identify the released bytes, not a promise of identical
N-Quads byte order across fresh database imports. Graph semantics and the
recorded finite-rule closure are the reconstruction target.
SPARQL and API defaults use asserted data. Explicit protocol dataset or FROM
selection is honored. API `mode=materialized` selects the union unless an
explicit dataset overrides it. Stored graphs need no query-time inference.
Choose an explicit named graph
when the asserted-versus-materialized distinction matters.

## Rebuild the scientific graph

Extract `rubalkhali-kg-3.0.0-source.tar.gz`; then follow its `README.md` to
create the pinned Linux environment and set `CONDA_PREFIX`, `JAVA_HOME` and
`PATH`. Verify its `SOURCE_SHA256SUMS` before generation. From the extracted
directory, run:

```sh
bash scripts/release/rebuild_public_sources.sh "$PWD" /absolute/path/to/new/kg-output
```

The output directory must not exist. This regenerates the project modules
from frozen scientific tables, copies the four exact reference ontologies,
and checks all 16 output hashes. It does not redo raw FASTQ processing or
resolve undocumented historical run identities. The source archive excludes
private correspondence and does not supply new sequencing access rights.

For materialization, load the manifested modules as one deduplicated asserted
union in an isolated engine, and follow `scripts/release/kg/README.md` in the
source archive. The finite rule program and bounded execution program are
available as `rules.rq` and `execution_rules.rq`; their hashes are recorded in
the manifest. A completed final zero-addition pass establishes closure only
for that program. No complete OWL-Horst, OWL 2 RL, EL or DL reasoning,
existential-witness generation, equality reasoning or full consistency proof
is claimed. Query-time inference remains disabled.

The archived materialization report precedes a bounded repair of 16 site
annotations. `wkt-closure-preservation.json` independently verifies that these
annotations cannot contribute to any body grounding of the exact 27-rule
program, and that copying the verified source-coordinate terms leaves the
exclusive inferred delta unchanged. It binds the original report and the
exact repair plan by hash; this manifest binds that certificate to the final
export hashes. The original report has not been relabelled as a run on changed
inputs. A fresh rebuild applies the import adapter before materialization and
does not need to replay this historical repair.

The certificate, repair plan, source-isolation audit and five verifier source
files are auxiliary downloads listed under `coordinate_import` in the manifest.
Their exact hashes are checked alongside the five main artifacts. To inspect
or rerun the certificate checker, place the verifier source files in the
extracted source archive's `scripts/release/kg/` directory; its unchanged
`materialize.py` supplies the remaining local dependency. The source-audit
helper accepts explicit source and output paths. Administrative repair
execution remains a separate operation; downloading or running the read-only
checker does not execute the repair SQL.

The actual inference controller used Python {manifest['reasoning']['software']['python']}
and RDFLib {manifest['reasoning']['software']['rdflib']}, with pyparsing 2.4.6,
isodate 0.6.0, six 1.14.0 and setuptools 45.2.0. This differs from the pinned
scientific-generation Python 3.11.14/RDFLib 7.1.4 environment. The engine is
`{manifest['reasoning']['runtime']['engine']['image']}`,
upstream 7.2.17/internal 7.20.3243, with `hash_join_enable=1` and 500,000-triple
batches. The final engine configuration sets
`[Parameters] TransactionAfterImageLimit=250000000`; confirm that
`sys_stat('txn_after_image_limit')` returns 250000000 before starting.
The earlier 50,000,000-byte limit caused SR325 during a subproperty update;
that failed report is preserved and is not closure evidence. This bounded
limit change did not change the rule program or batch size.
`inference_runtime.json` records the image identity and resource
settings. The source archive's `scripts/release/kg/inference-requirements.lock`
pins observed controller package versions; follow its README to create a
separate Python 3.8.10 environment. Package-version pins do not claim an exact
reconstruction of the host distribution's package builds.

The source archive's example supplies the release's explicit batch size;
the driver's default remains 200,000. To reproduce the actual 500,000-triple
execution setting, retain the explicit option. After loading a fresh asserted graph and leaving
the inferred graph empty, run from the extracted source directory:

```sh
/absolute/path/to/inference-environment/bin/python scripts/release/kg/materialize.py \\
  --endpoint http://127.0.0.1:18896/sparql \\
  --sql-command-file /absolute/path/to/staging_sql_command.json \\
  --asserted-graph https://rubalkhali.science/graph/asserted/3.0.0 \\
  --inferred-graph https://rubalkhali.science/graph/inferred/3.0.0 \\
  --batch-size 500000 \\
  --output-dir /absolute/path/to/new/materialization-transaction-cap \\
  --staging-only
```

Supply your own isolated SQL runner configuration; no credentials are
included. When assembling publication metadata from the completed recovery
run, explicitly pass
`--materialization-dir RELEASE_ROOT/materialization-transaction-cap`; do not
select the earlier interrupted `materialization-batched` or failed
`materialization-guarded` evidence. The command above starts from fresh
asserted input; resuming the preserved checkpoint instead requires the
documented `--resume-report` and `--resume-generator` safeguards.

## Attribution and validation scope

Project-data licence is unset; this metadata grants no new licence.
`THIRD_PARTY_ATTRIBUTIONS.json` preserves exact licence, rights, creator and
version annotations from the downloaded reference ontologies. SIO declares
CC BY 4.0, ENVO CC0 1.0 and PATO CC BY 3.0. The pinned UO file contains no
explicit ontology-root licence annotation; that is not permission or a claim
about its external documentation.

This metadata was assembled from completed local generation/materialization
and export evidence. The assembler verifies all five local artifact hashes;
it does not publish them, test HTTP delivery, parse every exported N-Quad,
or establish that a production endpoint serves these bytes. Those are
separate release gates; their actual status is not inferred from this README.
Their release acceptance evidence is available separately at `validation.json`,
which links this manifest's exact hash without introducing a circular hash.
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--reference-attribution", type=Path, required=True)
    parser.add_argument("--released-at", required=True)
    parser.add_argument("--export-fixture-report", type=Path, required=True)
    parser.add_argument("--materialization-dir", type=Path)
    parser.add_argument("--repair-certificate", type=Path, required=True)
    parser.add_argument("--repair-plan", type=Path, required=True)
    parser.add_argument("--source-audit", type=Path, required=True)
    parser.add_argument("--default-graph", choices=("asserted",), default="asserted")
    args = parser.parse_args()
    manifest = assemble(args.root, args.output_dir, args.reference_attribution, args.released_at, args.default_graph,
                        args.materialization_dir, args.export_fixture_report, args.repair_certificate, args.repair_plan,
                        args.source_audit)
    print(json.dumps({"prepared": True, "published": False, "version": VERSION, "files": len(manifest["files"]), "counts": manifest["counts"]}))


if __name__ == "__main__":
    main()
