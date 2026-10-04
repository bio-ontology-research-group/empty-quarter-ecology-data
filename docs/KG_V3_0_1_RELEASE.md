# KG v3.0.1 and the companion ecology paper

KG v3.0.1 is archived at https://doi.org/10.5281/zenodo.23134168.
Its asserted union contains 45,707,660 triples from sixteen modules. Project-authored
RDF, terms, definitions and dataset metadata are CC BY 4.0; imported vocabularies
retain their licences. See LICENSE-DATA.md and THIRD_PARTY_ATTRIBUTIONS.json.
Software licensing is specified separately in LICENSE-SOFTWARE.

The public release manifest and sixteen-module inventory are preserved verbatim
in evidence/kg-v3.0.1/. That directory includes the checksum-verified published
rebuild kit, original ontology, parsed-export and module-validation evidence,
Zenodo metadata and a fresh read-only publication check. The archived inventory's
top-level version_iri retains a v3.0.0 string; the released ontology, manifest
and graph contexts identify v3.0.1. Preserve the inventory bytes for verification;
use the ontology's owl:versionIRI as the ontology version identifier.

## Reproduce the released graph

Fetch the manifest at
https://bio2vec.net/data/empty-quarter/kg/3.0.1/manifest.json and verify downloaded
artifact sizes and SHA-256 digests. Extract the published kit and module archive
into an empty directory. Follow the kit README: use the pinned engine, coordinate-
preserving WKT loader adapter and isolated empty database, then load the sixteen
modules, export the asserted graph and validate its contexts/counts. Run every
real graph build on ws or Ontolinator. The kit contains module load/export code
and evidence; it does not itself regenerate upstream scientific observations.

Fifteen scientific/reference module hashes are identical to v3.0.0. Their original
producer replay remains under evidence/kg-v3.0.0/. The v3.0.1 root ontology adds
342 reviewed definitions and scoped licensing/release metadata, preserving term
axioms. The kit contains its builder, reviewed definitions and source hash. The
current paper keeps the earlier scientific/query validations dated to their actual
release and reports v3.0.1-specific checks separately.

## Reconcile the analytical inputs

metadata/climate/current_analysis_inputs.json selects the corrected daily
Open-Meteo and five-product exposure files. Both October packages are copied
byte-for-byte from the corrected ecology analysis and include their acquisition
and replay evidence. Their README commands describe the original ecology-side
replay; the versioned copies here provide the same data bytes to downstream users.
The frozen acquisition tables remain available as provenance and are not selected
by this manifest. KG monthly-climate observations retain their release hashes.

Ecology uses 1,237 retained profiles, with 1,227 in its primary 60-site frame.
The physical well-to-well p=0.87 analysis remains awaiting Rund's code/plate map;
it is separate from the reproduced library-order test in this data descriptor.
Public raw-read access and missing upstream processing parameters remain explicit
limits on raw-read-to-table reproduction. They do not prevent verification of
this released asserted graph from its sixteen distributed modules.
