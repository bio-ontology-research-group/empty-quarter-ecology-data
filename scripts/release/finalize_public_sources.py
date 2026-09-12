#!/usr/bin/env python3
"""Add explicitly selected public validation records and freeze source hashes."""
import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--workspace", type=Path, required=True)
    a = p.parse_args()
    w = a.workspace
    out = w / "public_source"
    proof = w / "public_source_full_replay_v2/rebuild_verification.json"
    verification = json.loads(proof.read_text())
    assert verification["passed"] and verification["mode"] == "--all"
    assert len(verification["checks"]) == 16
    items = {
        "README.md": w / "public_source_tools/PUBLIC_SOURCE_README.md",
        "validation/BUILD_REPORT.md": w / "public_source_tools/BUILD_REPORT.md",
        "validation/complete_public_source_replay.json": proof,
        "validation/root_metadata_delta.json": w / "root_metadata_delta.json",
        "validation/root_metadata_correction.json": w / "root_metadata_correction.json",
        "validation/strict_skip_reasons.log": w / "strict_skip_reasons.log",
        "validation/taxonomy_abox_streaming_validation.json": w / "fresh_workflow/10_kg_validation/kg_validation/taxonomy_abox_streaming_validation.json",
        "validation/fresh_nextflow_run_manifest.json": w / "fresh_workflow/10_kg_validation/kg_validation/run_manifest.json",
        "validation/fresh_nextflow_trace.tsv": w / "fresh_workflow/pipeline_info/trace.tsv",
        "validation/root_stamp_regression.log": w / "root_stamp_final_regression.log",
        "evidence/competency-query/field_xrf_site10.rq": w / "source/evidence/competency-query/field_xrf_site10.rq",
        "evidence/competency-query/field_xrf_site10_results.tsv": w / "query_expectations/field_xrf_site10.tsv",
        "scripts/release/derive_query_expectations.py": w / "public_source_tools/derive_query_expectations.py",
        "expected/query_expectations/taxonomy_ERR16061083_genus.tsv": w / "query_expectations_r8/taxonomy_ERR16061083_genus.tsv",
        "expected/query_expectations/environment_pseudomonas_gt35.tsv": w / "query_expectations_r8/environment_pseudomonas_gt35.tsv",
        "expected/query_expectations/source_expectations_manifest.json": w / "query_expectations_r8/source_expectations_manifest.json",
        "expected/query_expectations/taxonomy_lineage_source_projection.tsv": w / "query_expectations_r8/taxonomy_lineage_source_projection.tsv",
        "expected/query_expectations/taxonomy_first100_display_corrected.tsv": w / "query_expectations_r8/taxonomy_first100.tsv",
        "results/kg-release-3.0.0/query_expectations/taxonomy_ERR16061083_genus.tsv": w / "query_expectations_r8/taxonomy_ERR16061083_genus.tsv",
        "results/kg-release-3.0.0/query_expectations/environment_pseudomonas_gt35.tsv": w / "query_expectations_r8/environment_pseudomonas_gt35.tsv",
    }
    for name in ("materialize.py", "README.md", "verify_release_witnesses.py", "query_gates.py", "mode_gates.py", "inference_runtime.json", "inference-requirements.lock", "browser_runtime.json", "browser-requirements.lock", "verify_staging_fixture.py", "verify_batch_resume_fixture.py", "entailment_fixture.ttl", "taxonomy_all_runs.rq", "prepare_wkt_import.py", "WKT_IMPORT.md"):
        items["scripts/release/kg/" + name] = w / "public_source_tools/kg" / name
    for name in ("browser_kg_candidate.py", "test_kg_query_gates.py", "test_kg_mode_gates.py", "test_release_entailment.py", "test_query_expectation_selection.py", "test_manuscript_query_fixtures.py", "test_wkt_import_precision.py"):
        items["tests/" + name] = w / "public_source_tools/tests" / name
    for name in ("REPORT.md", "original.owl", "space.owl", "manifest.json", "exported.nq", "reload-adapted-loader.nq", "reload-adapter.json", "load.sql", "load.log", "export.sql", "export.log", "reload-load.sql", "reload-load.log", "queried/report.json", "reload-queried/report.json", "repair-plan.json"):
        items["validation/wkt-import/" + name] = w / "public_source_tools/wkt-import" / name
    for variant in ("unchanged", "two-branch"):
        for name in ("benchmark.json", "query.rq"):
            relative = "validation/taxonomy-preview-timeouts/" + variant + "/" + name
            items[relative] = w / "public_source_tools/taxonomy-preview-timeouts" / variant / name
    # These three exact released modules are small source-backed acceptance
    # witnesses, not substitutes for the complete fresh generation above.
    for name in ("rubalkhali.owl", "rubalkhali_controls.ttl", "rubalkhali_sites.owl"):
        items["ontology/" + name] = w / "release_inputs" / name
    for name in ("field_xrf_site10.tsv", "taxonomy_first100.tsv", "sites70.tsv", "six_pcr_ntcs.json"):
        items["results/kg-release-3.0.0/query_expectations/" + name] = out / "expected/query_expectations" / name
    manifest = json.loads((out / "SOURCE_MANIFEST.json").read_text())
    sources = {r["path"]: r["source_path"] for r in manifest["records"]}
    for relative, origin in items.items():
        target = out / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(origin, target)
        sources[relative] = str(origin)
    # The downstream query checker consumes exactly these printed SELECTs;
    # package query source alone, not the complete manuscript/review tree.
    paper_source = (w / "source/paper/05_validation.tex").read_text()
    listings = re.findall(r"\\begin\{lstlisting\}\[[\s\S]*?\\end\{lstlisting\}", paper_source)
    assert len(listings) == 3
    (out / "paper").mkdir(exist_ok=True)
    (out / "paper/05_validation.tex").write_text("% Printed scientific SELECT queries; extracted without prose.\n" + "\n\n".join(listings) + "\n")
    sources["paper/05_validation.tex"] = "exact printed SELECT listings from source/paper/05_validation.tex"
    records = []
    for relative, origin in sorted(sources.items()):
        path = out / relative
        h = hashlib.sha256()
        with path.open("rb") as f:
            for block in iter(lambda: f.read(1048576), b""):
                h.update(block)
        records.append(dict(path=relative, bytes=path.stat().st_size, sha256=h.hexdigest(), source_path=origin))
    manifest.update(files=len(records), bytes=sum(r["bytes"] for r in records), records=records,
                    policy="Explicit scientific source and acceptance-gate whitelist only, including declared test sources, three exact small RDF witness modules and bounded WKT import fixture evidence. No private correspondence, credentials, administrative backups, .git, unrelated source trees or unlisted fixtures. Existing scientific provenance citations remain. No new licence is granted.",
                    complete_driver_replay="passed: all16 module hashes reproduced; no generated taxonomy payload supplied as source")
    (out / "SOURCE_MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (out / "SOURCE_SHA256SUMS").write_text("".join(r["sha256"] + "  " + r["path"] + "\n" for r in records))
    print(json.dumps({k: v for k, v in manifest.items() if k != "records"}), flush=True)


if __name__ == "__main__":
    main()
