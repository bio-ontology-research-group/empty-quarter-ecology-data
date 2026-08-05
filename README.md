# Rub' al-Khali multimodal dataset and knowledge graph

This private BORG repository is the reproducible companion to the Scientific
Data manuscript *A multimodal field dataset and semantic knowledge graph for
the Rub' al-Khali desert microbiome*. It contains the active manuscript,
source metadata, ontology and ShEx sources, generated tractable modules,
analysis code, validation evidence, a hash-locked Python environment and the
Nextflow workflow.

Start with [REPRODUCE.md](REPRODUCE.md). Files too large for ordinary Git are
identified in [BULK_ARTIFACTS.tsv](BULK_ARTIFACTS.tsv) and are retrieved from a
private, checksum-pinned pre-release. `make verify`, `make test` and
`make paper` provide the short verification path.

Run every real knowledge-graph build on `ws` or Ontolinator. Local machines may
run regression tests, manuscript builds, and the explicitly stubbed workflow,
but are not a supported execution target for KG generation. The remote workflow
records the source state, environment, commands, checksums, and validation
results needed to audit the build.

## Pre-release status

This directory is a **staging snapshot**, not a published or immutable release.
It accompanies the working manuscript:

> **A multimodal field dataset and semantic knowledge graph for the Rub' al-Khali desert microbiome**

The generated modules, source tables, checksums, and evidence files here have
been reconciled to the current manuscript analysis. A Zenodo DOI,
release date, final per-file licences, and public-access claims must not be
added until the remaining release gates below have passed.

`PRE_RELEASE_MANIFEST.tsv` is the package-level source of truth for whether a
staged artifact is a canonical candidate, audit evidence, legacy material
excluded from the canonical release, or a derived file still requiring a
frozen provenance record. The machine-generated source ledger and evidence
manifest are under `evidence/release/`.

Repository generators retain their source-tree path conventions. After
extracting the candidate, create the documented relative compatibility layer
without duplicating payload files:

```bash
bash scripts/release/bootstrap_package_layout.sh .
python3 scripts/metadata/generate_env_table.py \
  --project-root . --output-dir ./environmental-replay
make test
```

The environmental replay must reproduce the staged 274-row curated table
byte for byte. The bootstrap command refuses to replace an existing path.

## Current accounting

These are generated development counts, not frozen publication statistics.

| Layer | Current count | Counting unit |
|---|---:|---|
| Source ledger | 2,550 | 2,302 master-sheet rows plus 248 plant rows |
| Master-sheet controls | 34 | Control-labelled source rows |
| Metadata-complete source rows | 2,540 | Rows passing the current metadata rule |
| Knowledge-graph-eligible specimens | 2,516 | All non-control rows; sites 61–64 resolve through confirmed aliases |
| DNA extracts | 1,647 | Generated DNA-extract individuals |
| Amplicon libraries | 1,242 | Generated library individuals |
| FASTQ datasets | 1,242 | Generated digital-dataset individuals |
| Canonical Trips 1–5 feature table | 1,271 | Profiles; 1,242 normalized field identifiers |
| Ecology analysis table | 1,237 | Retained profiles; 1,209 normalized field identifiers |
| Primary ecology frame (sites 1--60) | 1,227 | Retained profiles used for repeated-campaign inference |
| Field XRF | 71 | Complete in-situ sessions at 58 Trip 5 sites |
| Laboratory XRF, Trips 1–4 | 547 | Processed selected-sample records |
| Laboratory XRF, Trip 5 | 178 | Processed selected-sample records |
| Laboratory XRF, canonical total | 725 | The 547-plus-178 union |
| XRF measurement values | 19,763 | Generated values, each with a value-to-quality link |
| Annual climate measurements | 582 | 194 site--campaign records by three variables; 54 source values quarantined |
| Monthly climate measurements | 12,936 | 3,234 site--month records by four variables |
| Archived-soil pH | 712 | Admitted specimen measurements in 29 reconstructed sessions; 456 additional source rows remain unavailable or quarantined |
| Genome-abundance profiles | 150 | CoverM tables used by the encoded-function null |
| Annotated genome subset | 990 | Genomes shared by CoverM and eggNOG inputs |
| Paired PMA aliquots | 9 | Treated-versus-untreated Trip 5 pairs |

The generated sample, DNA, SRA, and XRF modules reconcile to those eligible
inputs. `rubalkhali_xrf.owl` contains 796 XRF process individuals (725
laboratory and 71 field) and 19,763 measurement-value individuals,
each with a value-to-quality link.

The canonical feature table has 29 normalized identifiers represented by two
export columns each. None of the 29 paired ASV count vectors is identical, and
both profiles remain after ecological filtering for 28 identifiers. Their
upstream laboratory or export relationship is not documented, so they remain
distinct profiles rather than being silently deduplicated or averaged. The
pairwise audit is `evidence/release/profile_duplicate_audit.tsv`.

The 34 source rows not ingested as field specimens are represented through a
separate SIO-patterned control model. All 36 genuine Trip-1-only records from numeric
sites 61–64 are ingested through
`metadata/samples/site_aliases.tsv`. Stable identities for all 10 named
catalogue locations are recorded separately in
`metadata/samples/site_iri_registry.tsv`; the site generator fails if the
observed named-site labels differ from that bijection. The alias ledger
preserves their numeric
source identifiers and exact coordinates while linking them to the existing
named catalogue sites and the four coordinate-matched Trip 1 visits; it
does not mint duplicate physical locations. They remain outside the
repeated-campaign inference frame because those locations could not be
revisited. The 26 SRA rows outside the field-specimen lineage are
control-labelled records and are represented as control sequence occurrences
where the evidence supports that link. The
34-profile difference between the canonical feature table and the ecology
analysis table is itemized in `evidence/release/profile_duplicate_audit.tsv`
and `evidence/release/sample_ledger.tsv`: 24 are controls, and the remaining
ten profiles (nine biological identifiers plus one additional `T1Dr1` run)
each contain fewer than the declared 1,000-read
ecological threshold.

The current author-confirmed design is frozen in
`evidence/controls/control_ground_truth.tsv`. Trips 1 and 2 used purified-DNA
ZymoBIOMICS HMW DNA Standard D6322; Trip 3 used whole-cell ZymoBIOMICS
Microbial Community Standard D6300; Trip 4 had no positive control; and the
Trip 5 D6300 positive and negative pair was sequenced by shotgun metagenomics,
not by the 16S assay. Extraction blanks and PCR blanks are distinct roles.
EB1-EB18 and Negative1/2/4-7 are extraction blanks, but only EB1-EB17 have
frozen extraction-batch mappings. An extraction blank is linked to its batch,
never directly to a trip, because a batch may contain specimens from several
trips. Three paired 16S libraries and one Trip 4 workbook record already bear
evidence-supported PCR-blank roles. Complete mapping of reused or generic
labels to PCR batches awaits laboratory confirmation.

The generated control graph is `ontology/rubalkhali_controls.ttl`; normalized
tables are under `metadata/controls/`; its shape is `shex/controls.shex`; and
the assay-aware audit and before/after ecology comparison are under
`evidence/control-audit/` and `evidence/control-sensitivity/`. Historical
preliminary identity files remain in `evidence/controls/`, but their product
candidates are not current ground truth.

The bounded before/after comparison can be replayed from the extracted
package alone after creating the pinned environment in
`environment/environment.yml` (or installing
`environment/requirements.lock.txt`):

```bash
PYTHON=/path/to/that/environment/bin/python \
  bash evidence/control-sensitivity/commands.sh ./control-sensitivity-replay
```

The command consumes the checksummed canonical cache and comparison outputs
under `evidence/ecology-canonical/`, the laboratory-XRF axis under
`evidence/xrf-community/`, and the staged metadata. It never trains the
contaminant screen on a positive control and refuses to overwrite an existing
output directory. The original repository-run commands are retained
separately as `evidence/control-sensitivity/commands_repository.sh`.

## Environmental metadata curation

The five files under `metadata/samplesheets/` are preserved as immutable
field-source records. The canonical 274-row table is
`metadata/environmental/environmental_measurements_curated.tsv`; it is
generated by `scripts/metadata/generate_env_table.py` from those sheets and
the exact-cell ledger
`metadata/samples/environmental_measurement_corrections.tsv`.

The ledger and fail-closed generator make three source issues explicit:

- the eight Trip 2 values 34.5--41.9 are shifted from the source humidity
  column into temperature; no Trip 2 pressure or humidity is inferred;
- 15 records appended to the legacy Trip 3 worksheet retain their original
  March 2023 dates and are treated as Trip 1 auxiliary/revisit records, so
  Trip 3 contains 60 primary and five named February 2024 records; and
- the Trip 5 site 40 source humidity of 194% is preserved in the ledger but
  quarantined as missing because no primary source establishes a decimal
  correction.

The Trip 3 site 21 value 31.321% is not a correction: the original workbook
stores the fraction 0.31321. The workbook and machine-readable audit are
under `evidence/environmental/`. The same correction ledger drives the
staged environmental RDF module. It links 260 of the 274 rows to unambiguous
catalogue visits (260 temperatures, 187 pressures and 251 humidity values);
the fourteen auxiliary or revisit labels other than exact catalogue label
`19.5` are retained in the table but are not linked by coordinate
coincidence. The module contains no out-of-range field humidity assertion.

## Archived-soil pH

The pH data used by both manuscripts are frozen as
`EQ-PH-SHARED-v1.0.0`. The source workbook, version manifest, registry and
immutable predecessor are under `metadata/samples/ph/`; normalized admitted,
session, entity-registry and complete row-audit tables are under
`metadata/ph/`. The audit accounts for all 1,168 source rows: 712 admitted
measurements, 356 rows without a measurement, 45 depleted
specimens, 36 rows with ambiguous measurement dates, and 19 numeric rows with
incomplete recorded calibration or quality-control evidence. No missing or
quarantined value is imputed. The Trip 4 source notes identify `S28Sr1` as
missed during preparation and `S57Dr1` as depleted.

The source workbook has no session identifier. The 29 session individuals are
reconstructed from unique combinations of trip, accepted measurement date,
electrode slope and pH-10 read-back; they must not be interpreted as directly
recorded laboratory batch identifiers.

The canonical graph-equivalent RDF/XML and Turtle modules are
`ontology/rubalkhali_ph_eq_ph_shared_v1_0_0.owl` and
`ontology/rubalkhali_ph_eq_ph_shared_v1_0_0.ttl`. Each admitted observation is
represented by an SIO measuring process connected to its specimen input and
target and to its pH value output. The value has unit `UO:0000196` and
quantifies the acidity quality attached to the specimen; the process also
links to its reconstructed measurement session. The root knowledge graph
imports this versioned module.
The source reconciliation, predecessor comparison, ecology sensitivity, ShEx
result and checksums are under `evidence/ph/`. All 653 observations in the
predecessor are unchanged, and this shared version adds 59 admitted
observations. The measurement campaign is complete as available, but pH
coverage remains incomplete and non-random across trips and specimens.

After running `scripts/release/bootstrap_package_layout.sh` on `ws` or
Ontolinator, the complete pH normalization, ecology analysis, predecessor
comparison, shape validation and canonical-module byte comparison can be
replayed there with:

```bash
PH_PYTHON=/path/to/that/environment/bin/python \
  bash scripts/analysis/run_ph_shared_v1.sh
```

The driver writes its regenerated manuscript macros under the pH analysis
directory when the companion manuscript source tree is not present.

## Companion ecology-analysis inputs

The statistical inputs needed for the ecology paper's genome-resolved
encoded-function, PICRUSt2 comparison, metabolic-marker summary, and paired
PMA analyses are staged separately from the amplicon and ontology layers:

- `metadata/metagenome/coverm_profiles.tar.gz` contains the 150 CoverM
  genome-relative-abundance tables;
- `metadata/metagenome/eq.emapper.annotations.gz` is the eggNOG annotation
  table from which the 990-genome KO matrix is constructed;
- `metadata/metagenome/measured_function_inputs.tar.gz` contains the six
  exact source tables named in the measured-function input manifest; and
- `metadata/relic-dna/PMA_ASV_table.tsv` is the count matrix for the nine
  treated-versus-untreated aliquot pairs (18 analytical columns, with
  controls retained separately).

The three analysis programs are under `scripts/analysis/`, and archive
checksums are under `evidence/companion-analysis/`. These staged inputs
support the named downstream PMA, measured-function and encoded-function
endpoints within the boundaries stated in the manuscript. They do not replace
public deposition of the underlying shotgun and PMA sequence reads, nor do
they make upstream assembly, binning, dereplication, annotation or
CoverM generation reproducible without the raw reads and genome catalogue.
Those upstream accessions remain a release gate.

## XRF data products are distinct

Field and laboratory XRF are separate acquisition workflows:

- `metadata/geochemistry/xrf_field_table.tsv` contains the 71 site-level
  in-situ sessions. These records do not identify a physical soil sample or
  compartment.
- `metadata/geochemistry/xrf_lab_table_trips1-4.tsv` contains 547 laboratory
  records. Repeated reported cells were reduced with the documented
  maximum-positive rule.
- `metadata/geochemistry/xrf_lab_table_filtered.tsv` contains all 178 Trip 5
  laboratory records. Repeated reported cells preserve the last-reported
  value.

The two laboratory source-specific aggregation rules are disclosed and
reproduced by the audit; they are processing rules, not calibration. No
field/laboratory calibration or interchangeability claim is made.

`metadata/geochemistry/xrf_lab_combined.tsv` is a misleadingly named,
retired 158-record Trip 5 subset. It is retained for provenance only and is
marked `legacy-excluded` in the package manifest. The corresponding
547-plus-158 analytical union of 705 records is also retired. Neither is an
input to the current XRF knowledge-graph generation or analysis.

The complete reconciliation, aggregation checks, field/laboratory comparison,
and method-metadata gaps are under `evidence/xrf_audit/`.

## Bounded competency-query validation

The exact field-XRF query is `sparql/field_xrf_site10.rq`. The executed
validator, `scripts/validation/validate_competency_query.py`, loaded the
checksummed base, site, and XRF modules and enforced a fixed expected
cardinality. It returned 46 analyte-value rows for Site 10: 24 from field
process Test 5847 and 22 from Test 5848. The result table, JSON validation
record, and checksums are under `evidence/competency-query/`.

This evidence validates only that bounded retrieval. It does not establish a
pass rate for the historical competency-query suite.

## Taxonomy tables

The canonical Trips 1–5 set is:

- `metadata/taxonomy/feature-table-trips1-5.tsv`
- `metadata/taxonomy/taxonomy-trips1-5.tsv`
- `metadata/taxonomy/ASV_seqs-trips1-5.fasta`

The older `feature-table.tsv` (1,013 profiles; 984 normalized field
identifiers) and its companion `taxonomy.tsv` are retained so that earlier
processing can be audited, but they are explicitly excluded from the
canonical release. The two `feature_table_filtered_*` tables and
`unique_taxa.txt` are supporting derived artifacts whose final inclusion
depends on a frozen derivation and provenance record. See
`metadata/taxonomy/README.md` for exact checksums and status.

The taxonomy ABox in `ontology/rubalkhali_taxonomy_abox.ttl` has been
synchronized to the clean-workflow output. It contains 44,528,482 triples in
5,953,690 contiguous subject blocks, including 1,236 processing individuals,
17,304 abundance datasets, and 2,962,918 quality/value pairs. Its byte size,
SHA-256 and complete streaming-validation record are included in the staging
manifest and reproducibility bundle.

## Package layout

- `metadata/DATA_DICTIONARY.tsv`: machine-readable field definitions, data
  types, units, and missing-value conventions for the canonical tabular
  records
- `ontology/`: generated OWL/RDF modules synchronized to the current
  pre-release generation
- `ontology-src/`: hand-authored ontology source modules
- `metadata/`: specimen, expedition, control, geodata, geochemistry,
  sequencing, climate, QC, and taxonomy data
- `scripts/rdf/`: RDF-generation scripts used by the staged modules
- `scripts/analysis/`: bounded companion-paper analyses used for the staged
  functional and PMA results
- `workflow/` and `environment/`: Nextflow orchestration, task wrappers,
  regression tests, the pinned Conda recipe and the hash-locked Python
  environment
- `scripts/release/`: source-ledger and release-reconciliation generator
- `scripts/validation/` and `shex/`: structural and semantic validation
- `sparql/`: competency-query and schema documentation
- `evidence/release/`: generated ledger, count reconciliation, and source
  manifest
- `evidence/environmental/`: source-workbook evidence and the generated
  environmental correction/range/campaign-date audit
- `evidence/ph/`: pH source reconciliation, version comparison, ecology
  sensitivity, shape-validation result and checksums
- `evidence/xrf_audit/`: XRF source inventory, aggregation reproduction, and
  discrepancy audit
- `evidence/xrf_chemical_mapping_audit/`: fail-closed ChEBI/PubChem
  identifier ledger, source hashes, and audited null dispositions
- `evidence/companion-analysis/`: checksums for the staged derived inputs
- `evidence/ecology-canonical/`: exact baseline cache and canonical result
  files used by the package-only control-sensitivity replay
- `evidence/xrf-community/`: the exact laboratory-XRF axis and loadings used
  by that replay
- `evidence/primer-identity/`: primer audit counts, code pointer and exact
  source-path ledger
- `evidence/competency-query/`: bounded field-XRF query result, validation
  record, and checksums

The intended generation order is base ontology, sites, samples,
measurements, XRF, DNA, SRA, QC, taxonomy, controls, pH, and ecosystem mapping.
The staged Nextflow workflow records this order and its pinned software
environment. A fresh execution record against the final frozen deposit must
still be attached at release time.

## Development identifiers

The development metadata currently refer to umbrella project
`PRJEB104209` and amplicon project `PRJEB106069`. These identifiers are not
yet evidence that every sample, run, and file required by the manuscript is
publicly retrievable. The endpoint and portal at `rubalkhali.science` are
also development resources, not substitutes for an immutable archive.

## Remaining release gates

Before this directory can be deposited and cited:

1. record explicit upstream QC dispositions for the nine biological-profile
   identifiers and the additional `T1Dr1` run absent from the ecology table;
2. verify every public accession and anonymous file download, including the
   underlying shotgun and PMA reads and the genome catalogue;
3. freeze a version, repository commit, per-file licences, checksums, and the
   Zenodo DOI; and
4. re-run the manuscript consistency tests against that exact frozen package.

Trip-1-only sites 61–64 have coordinate-confirmed canonical site and visit
links. Control-labelled records have explicit materials, roles, processes,
evidence and uncertainty dispositions without assigning extraction blanks to
trips. The package should be described as validated only against the
checksummed reports for the final staged version.

No CC BY, MIT, DOI, or public-availability statement in this staging tree is
final until the deposited record supplies the corresponding evidence.
