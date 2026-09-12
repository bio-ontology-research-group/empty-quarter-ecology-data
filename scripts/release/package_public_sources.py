#!/usr/bin/env python3
"""Build an explicit, scientific-input-only source package; never crawl a repo."""
import argparse
import hashlib
import json
import shutil
from pathlib import Path


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--workspace", type=Path, required=True)
    a = p.parse_args()
    w = a.workspace
    source = w / "source"
    out = w / "public_source"
    out.mkdir(exist_ok=False)
    pairs = []
    def add(relative, origin=None):
        pairs.append((Path(origin) if origin else source / relative, relative))
    for name in ("site_ontology", "measurements_abox", "samples_abox", "xrf_abox", "dna_abox", "sra_abox", "qc_abox", "taxonomy_abox"):
        add(f"scripts/rdf/generate_{name}.groovy")
    for name in ("generate_controls_abox.py", "generate_ph_dataset.py"):
        add("scripts/rdf/" + name)
    for name in ("build_canonical_taxonomy.py", "ncbi_index.py"):
        add("scripts/taxonomy/" + name)
    for name in ("biome_codes.yml", "xrf_chemical_mapping.yml"):
        add("config/codes/" + name)
    add("config/ph/ph_measurements.shex")
    add("data/metadata/QC_reads/multiqc_general_stats.txt")
    for number, year in ((1, 2023), (2, 2023), (3, 2024), (4, 2024), (5, 2025)):
        add(f"data/metadata/samplesheets/trip{number}-{year}.tsv")
        add(f"data/metadata/geodata/trip{number}_geodata.tsv")
    add("data/metadata/samplesheets/additional_fastqs_v2.tsv")
    for name in ("Sample_Mastersheet.xlsx", "EB_Sample_Map_FourthTrip2.xlsx", "Sequenced_Samples_by_EB_FifthTrip.xlsx", "plants.tsv", "environmental_measurement_corrections.tsv", "sample_corrections.tsv", "site_aliases.tsv", "site_iri_registry.tsv"):
        add("data/metadata/samples/" + name)
    add("data/metadata/samples/ph/versions/EQ-PH-SHARED-v1.0.0/ph_measurements.xlsx")
    add("data/metadata/samples/ph/versions/EQ-PH-SHARED-v1.0.0/manifest.json")
    for name in ("ph_measurements.xlsx", "manifest.json", "trip4_specimen_reconciliation.tsv", "confirmation.json"):
        add("data/metadata/samples/ph/versions/EQ-PH-SHARED-v1.0.1/" + name)
    add("data/metadata/samples/ph/version_registry.tsv")
    for name in ("control_ground_truth.tsv", "source_snapshots/ibex_20250714_16s_samplesheet.tsv", "source_snapshots/ibex_trip5_16s_samplesheet.tsv", "source_snapshots/ibex_20250714_qiime2/controls-metadata.tsv"):
        add("data/metadata/samples/controls/" + name)
    add("data/metadata/sra-submissions/submission-sheet.tsv")
    add("data/processed/climate/monthly_weather_averages.tsv")
    add("data/processed/climate/climate_acquisition_frozen.json")
    for name in ("xrf_field_table.tsv", "xrf_lab_table_filtered.tsv", "xrf_lab_table_trips1-4.tsv"):
        add("data/processed/geochemistry/" + name)
    add("data/release/sample_ledger.tsv")
    for name in ("taxonomy-trips1-5.tsv", "feature-table-trips1-5.tsv"):
        add("data/metadata/taxonomy/" + name)
    add("data/ontologies/ncbitaxon.owl")
    add("inputs/mapped_taxonomy.tsv", source / "ontology/mapped_taxonomy.tsv")
    add("inputs/curated_rubalkhali_pre_release.owl", w / "source_baseline/rubalkhali.owl")
    for name in ("sio.owl", "envo.owl", "pato.owl", "uo.owl"):
        add("data/ontologies/" + name, w / "reference_inputs" / name)
    for name in ("environment.yml", "conda-linux-64.lock", "pip-overlay.lock.txt", "requirements.lock.txt"):
        add("environment/" + name)
    add("workflow/bin/run_taxonomy_abox_generation.sh")
    add("workflow/bin/bootstrap_raptor.sh")
    add("scripts/validation/validate_taxonomy_abox_streaming.py")
    for name in ("stamp_kg_release.py", "rebuild_public_sources.sh", "write_offline_catalog.py"):
        add("scripts/release/" + name, w / "public_source_tools" / name)
    for name in ("materialize.py", "README.md", "verify_release_witnesses.py", "query_gates.py"):
        add("scripts/release/kg/" + name, w / "public_source_tools/kg" / name)
    add("expected/fresh_modules_manifest.json", w / "fresh_modules_manifest.json")
    add("expected/root_metadata_correction.json", w / "root_metadata_correction.json")
    add("expected/reference_inputs_manifest.json", w / "reference_inputs_manifest.json")
    add("expected/catalog-v001.xml", w / "release_inputs/catalog-v001.xml")
    for name in ("field_xrf_site10.tsv", "taxonomy_first100.tsv", "environment_pseudomonas_gt35.tsv", "sites70.tsv", "six_pcr_ntcs.json"):
        add("expected/query_expectations/" + name, w / "query_expectations" / name)
    records = []
    for origin, relative in pairs:
        target = out / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(origin, target)
        h = hashlib.sha256()
        with target.open("rb") as f:
            for block in iter(lambda: f.read(1048576), b""):
                h.update(block)
        records.append(dict(path=relative, bytes=target.stat().st_size, sha256=h.hexdigest(), source_path=str(origin)))
    result = dict(version="3.0.0", files=len(records), bytes=sum(r["bytes"] for r in records),
                  policy="Explicit scientific-source whitelist only. No private correspondence, credentials, private evidence, .git, unrelated trees, generated RDF modules or fixture files. Existing curated scientific provenance citations remain in scientific source tables. No new licence is granted.", records=records)
    (out / "SOURCE_MANIFEST.json").write_text(json.dumps(result, indent=2) + "\n")
    (out / "SOURCE_SHA256SUMS").write_text("".join(r["sha256"] + "  " + r["path"] + "\n" for r in records))
    print(json.dumps({k: v for k, v in result.items() if k != "records"}), flush=True)


if __name__ == "__main__":
    main()
