# RDF generation & ontology engineering

Everything needed to (re)build the Rub' al-Khali knowledge graph from source
metadata and to validate it. See [`../REPRODUCE.md`](../REPRODUCE.md) for the
end-to-end workflow.

## Layout

| Path | Contents |
|------|----------|
| `ontology-src/` | Hand-authored TBox: `rubalkhali-root.ttl`, `sites.ttl`, `samples.ttl`, `analysis.ttl`, and the compiled base ontology `rubalkhali.owl` (302 classes, 22 properties). |
| `generators/` | Groovy ABox generators (OWL API 5). Run in the order listed in `REPRODUCE.md`; `update_rubalkhali_ontology.groovy` builds the TBox first. |
| `taxonomy-alignment/` | NCBI/GTDB/iNaturalist alignment pipeline: `LexicalAlign` → `VerifySeeds` → `MergeTaxonomies` → `GraftInat` (plus conflict resolution / candidate prep). |
| `validation/` | ShEx + OWL-consistency + integrity + competency-question validators, orchestrated by `validate_all.sh`. |
| `shex/` | Eight ShEx schemas (sites, samples, measurements, dna, xrf, sra, qc, taxonomy). |
| `sparql/` | `SPARQL.md` (competency questions), `ODP.md` (ontology design patterns), `SCHEMA.md` (KG schema). |
| `config/codes/` | `xrf_chemical_mapping.yml`, `xrf_chebi_mapping.yml`, `biome_codes.yml`. |
| `manage.sh` | Build orchestrator: `start` / `stop` / `update` / `validate` / `reset`. |
| `deploy_onto.sh` | Ontology deployment to the triple store. |
| `void.ttl` | VoID descriptor for the dataset. |

## Critical invariants

These are load-bearing; breaking them silently corrupts the KG. The full list is
in [`../CLAUDE.md`](../CLAUDE.md).

- **XRF analyte IRIs:** `update_rubalkhali_ontology.groovy` and
  `generate_xrf_abox.groovy` both iterate `config/codes/xrf_chemical_mapping.yml`
  (counters at 100/500) and **must skip `LE`** (Light Elements; predefined
  `RAK_0000032/0000033`). Skipping it wrong shifts every analyte label (Si↔Fe).
- **Measurement reification:** every measurement uses the canonical SIO
  four-individual split; both `SIO_000215` (value→quality) and `SIO_000216`
  (quality→value) directions are asserted because ELK has no inverse reasoning.
- **Centralized TBox:** every RAK class/property used by an ABox generator is
  declared once in `update_rubalkhali_ontology.groovy`; ABox scripts only attach
  instances. Reserved IRI ranges are documented in `CLAUDE.md`.
