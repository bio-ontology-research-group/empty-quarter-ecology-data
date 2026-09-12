# KG v3.0.0: asserted-only release

Deployed and publicly validated on 13 September 2026 (Saudi Arabia time).
The graph contains 45,706,977 asserted triples from 12 project modules and
four pinned reference ontologies. The serving database is separate from the
ongoing reasoning database. Stored assertions are the default SPARQL dataset;
explicit protocol datasets and `FROM`/`FROM NAMED` retain their documented
selection semantics. Anonymous updates and unavailable query modes are rejected.

## Downloads and evidence

All links require no authentication:

- [Release manifest](https://rubalkhali.science/downloads/kg/3.0.0/manifest.json)
- [Scientific source, 129,095,989 bytes](https://rubalkhali.science/downloads/kg/3.0.0/rubalkhali-kg-3.0.0-source.tar.gz)
- [Original RDF modules, 372,523,592 bytes](https://rubalkhali.science/downloads/kg/3.0.0/rubalkhali-kg-3.0.0-modules.tar.gz)
- [Asserted N-Quads, 330,556,313 bytes](https://rubalkhali.science/downloads/kg/3.0.0/rubalkhali-kg-3.0.0-asserted.nq.gz)
- [Module inventory](https://rubalkhali.science/downloads/kg/3.0.0/input-modules-manifest.json)
- [All-module source replay](https://rubalkhali.science/downloads/kg/3.0.0/source-rebuild-verification.json)
- [Public acceptance](https://rubalkhali.science/downloads/kg/3.0.0/post-deployment-validation.json)

The manifest SHA256 is
`9597bc71d9d2603f2a401ba9ccfc834376cc02795db103ace0c824889b618475`.
The public acceptance record SHA256 is
`d08b67fa9dbda4db2e2d8adb2c7506270139ef1ac03fa18a26b4c137a4383990`.
Copies of the public metadata are retained under `evidence/kg-v3.0.0/`.

## Reproduce

Download the source archive and check its byte count and SHA256 against the
manifest before extracting it into an empty directory. Follow its `README.md`:
the archive contains the scientific inputs, producer code, pinned environment,
source-file inventory and expected module hashes. Its full replay regenerates
all 16 source module hashes. Large upstream sequencing analyses are separate
from this source-to-KG replay.

The original module archive preserves the source RDF. For the pinned Virtuoso
image, apply the supplied `prepare_wkt_import.py` adapter before loading the
site module or reloading native N-Quads. It inserts whitespace after `POINT`
for 70 coordinates, preserving every coordinate digit and the original files.
The loader, adapter and native-export precision fixture have separately hashed
evidence. See [WKT_IMPORT.md](../scripts/release/kg/WKT_IMPORT.md).

The deployment used image
`openlink/virtuoso-opensource-7@sha256:0dbe1ab4fa0cb7bbafc1f6c0c2b0a5d6f22d918dbd17672f2ddb24580aa6756a`.
Operational scripts preserve the exact onto paths used for this deployment;
they are audit artifacts requiring an explicitly configured new target for reuse.

For the repository regression suite, first create its documented compatibility
layout with `bash scripts/release/bootstrap_package_layout.sh .`, then use the
Python 3.11 environment lock. The four small query fixtures under
`results/kg-release-3.0.0/query_expectations/` are deliberately tracked; generated
results and bulk exports remain outside Git.

## Acceptance and rollback

Both candidate and public origin passed:

| Gate | Result |
|---|---:|
| Exact source-derived query checks | 26 |
| Dataset, read-only and RDF/SELECT protocol checks | 14 |
| Asserted-only isolation and all 712 pH specimen links | 6 |
| Browser examples | 9 |
| Browser download-range checks | 3 |
| Full artifact downloads with size and checksum checks | 3 |
| Full import-proof downloads with checksum checks | 6 |

The N-Quads gate parsed the complete 45,706,977-triple stream and checked every
graph context and its uncompressed digest. Validation used Raptor 2.0.15 with
N-Quads input/output enabled. The earlier Turtle-only parser attempt failed
before parsing and its evidence was retained. The working runtime used Ubuntu
`raptor2-utils` 2.0.15-0ubuntu1.20.04.2, extracted without changing host packages:
package SHA256 `b6a3aeece39cb07d822c9fedb32d8c8a2b585d5cbba9b0c7f7ef3c4ab7478825`;
binary SHA256 `6e86e311c3540cdf787d4c5aacececb5365abebc82f240480a67993aa9a25e8a`.

`asserted_cutover.py` requires all five report suites and live graph counts,
checks the previous production configuration, and preserves a rollback copy.
The old application/database remain available. Its `rollback` operation
restores only that verified entry-point configuration. Public verification is
recorded separately by `publish_asserted_public_validation.py` after the switch;
the pre-cutover `validation.json` remains an immutable candidate-only record.

## Scientific correction and version policy

EQ-PH-SHARED-v1.0.1 reconciles 155 admitted Trip 4 assays to field replicate 2;
one of the 156 admitted Trip 4 assays already had that assignment. The correction
replaces 620 physical-specimen relations and preserves all 712 admitted assay
values, source workbook identifiers and admission decisions. All 712 current
process-to-specimen links were checked against the source module.

The data paper now reports this reconciliation, the 16-module inventory,
45,706,977 asserted triples, available query mode and observed acceptance checks.
The frozen release bytes will remain unchanged. Later corrections or validated
reasoning output require a new semantic version. Public sequencing access,
the broader dataset accession and its project-data licence remain separate;
this KG release grants no new data licence.

## Repository and manuscript checks

The isolated release checkout passed 362 KG, packaging, query, export,
coordinate and pH regression tests after the documented compatibility bootstrap.
The website checkout passed 107 backend/protocol/taxonomy tests and eight editor
tests, and its production build succeeded. Both data-paper documents compiled
successfully (32-page article and 22-page supplement), with no undefined
references or citations. The existing minor table-width and font warnings
remain. The frontend package audit reported 26 dependency advisories; dependency
upgrades and a comprehensive application-security audit are separate work.

Fifteen figure and source-snapshot tests passed, and the specimen-coverage table
regenerated byte-for-byte from the committed ledger. The data-paper figure
producer and workflow inputs are included. Rebuild the PDFs with `make paper`;
the build uses the repository's fixed `SOURCE_DATE_EPOCH=1785888000`.
This release was compiled with pdfTeX 1.40.26 (TeX Live 2025/dev/Debian).
