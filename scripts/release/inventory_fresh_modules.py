#!/usr/bin/env python3
"""Freeze the exact deduplicated-module load inventory for KG 3.0.0.

This is a file inventory, not an assertion that the union is already deduplicated
or materialized. Exactly one serialization per scientific module is selected.
"""
import argparse
import hashlib
import json
import shutil
from pathlib import Path


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--workspace", type=Path, required=True)
    p.add_argument("--stage-inputs", action="store_true")
    a = p.parse_args()
    w = a.workspace
    core = w / "fresh_workflow/02_core_kg/core_kg_modules"
    records = []
    files = [(core / n, "curated_ontology_metadata_derivation" if n == "rubalkhali.owl" else "fresh_source_generation") for n in (
        "rubalkhali.owl", "rubalkhali_sites.owl", "rubalkhali_samples.owl", "rubalkhali_measurements.owl", "rubalkhali_dna.owl", "rubalkhali_sra.owl", "rubalkhali_xrf.owl", "rubalkhali_qc.owl", "rubalkhali_controls.ttl", "rubalkhali_ph_eq_ph_shared_v1_0_1.ttl")]
    files += [(w / "fresh_workflow/09_taxonomy_abox/taxonomy_abox/rubalkhali_taxonomy_abox.ttl", "fresh_source_generation"),
              (w / "fresh_workflow/08_taxonomy_mapping/taxonomy_mapping/canonical/ecosystem_module.ttl", "fresh_source_generation"),
              (w / "reference_inputs/sio.owl", "pinned_reference_1.59")]
    files += [(w / "reference_inputs" / name, "pinned_direct_root_import") for name in ("envo.owl", "pato.owl", "uo.owl")]
    release_inputs = w / "release_inputs"
    if a.stage_inputs:
        release_inputs.mkdir(exist_ok=True)
    for path, derivation in files:
        h = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1048576), b""):
                h.update(chunk)
        records.append({"path": str(path.relative_to(w)), "file": path.name, "bytes": path.stat().st_size, "sha256": h.hexdigest(), "derivation": derivation,
                        "type": "turtle" if path.suffix == ".ttl" else "rdfxml", "load_graph": "https://rubalkhali.science/graph/asserted/3.0.0"})
        if a.stage_inputs:
            target = release_inputs / path.name
            if target.exists():
                raise FileExistsError(f"Refusing to overwrite staged input: {target}")
            shutil.copy2(path, target)
    result = {"version": "3.0.0", "version_iri": "https://rubalkhali.science/kb/v3.0.0/", "module_count": len(records),
              "load_contract": "Deduplicate these 16 RDF modules into one asserted union; do not load both serializations or the retired rubalkhali_kb.owl alias. Import declarations are not instructions to fetch unlisted web ontologies.",
              "reference_coverage": "Root imports SIO1.59, ENVO2025-10-20, PATO2025-05-14 and UO2023-05-25 loaded in full from exact date-matched cached files; these four root ontology headers declare no further owl:imports. RO not separately imported. ChEBI and full NCBITaxon served as mapping sources but are not independently loaded; referenced taxon terms are provided by the generated ecosystem module, not a claim of full external-term closure.",
              "excluded": ["rubalkhali_kb.owl (retired stale TBox alias)", "retired taxonomy_rak/ncbitaxon_module", "sibling OWL/TTL serializations of the same module", "service-description metadata (managed separately)"],
              "records": records}
    (w / "fresh_modules_manifest.json").write_text(json.dumps(result, indent=2) + "\n")
    if a.stage_inputs:
        (release_inputs / "manifest.json").write_text(json.dumps(result, indent=2) + "\n")
        (release_inputs / "SHA256SUMS").write_text("".join(r["sha256"] + "  " + r["file"] + "\n" for r in records))
    print(f"Inventoried {len(records)} modules", flush=True)


if __name__ == "__main__":
    main()
