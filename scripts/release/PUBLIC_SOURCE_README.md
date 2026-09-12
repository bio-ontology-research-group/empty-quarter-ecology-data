# Rub al-Khali KG 3.0.0: scientific source package

This package regenerates the release's scientific RDF modules from the frozen
input tables. It contains no generated taxonomy ABox, private correspondence,
credentials, review correspondence, Git history or unrelated fixture datasets. Every
included source file is listed and hashed in `SOURCE_MANIFEST.json` and
`SOURCE_SHA256SUMS`.

Declared acceptance tests, five frozen expected-result tables and two small
exact release modules used as inference witnesses are included separately.
They do not replace fresh scientific generation or the full module archive.

The starting inputs are the released feature-count/classifier tables, curated
sample and laboratory tables/workbooks, QC summaries, environmental summaries,
source-control records and pinned ontology references. This is a complete KG
source rebuild, not a reconstruction of historical raw-read processing.

## Rebuild

Use Linux x86-64, at least 48 GB available RAM and 30 GB free output space.
The validated runtime is Python 3.11.14, Java 21.0.10 and Groovy 4.0.28. Exact
Conda package builds/URLs/hashes and the hashed pip overlay are included.
Initial environment installation and Groovy's version-pinned Maven dependency
resolution require network access. Scientific input tables are all local.

From the extracted package directory:

```sh
sha256sum -c SOURCE_SHA256SUMS
micromamba create -y -p "$PWD/.runtime" --file environment/conda-linux-64.lock
micromamba run -p "$PWD/.runtime" python -m pip install --no-deps --require-hashes -r environment/pip-overlay.lock.txt
export CONDA_PREFIX="$PWD/.runtime"
export JAVA_HOME="$CONDA_PREFIX/lib/jvm"
export PATH="$CONDA_PREFIX/bin:$PATH"
bash scripts/release/rebuild_public_sources.sh "$PWD" /absolute/path/to/new-output
```

The output directory must not already exist. The driver preserves all input
files, applies the explicit release metadata stamp, runs the same scientific
generators as the validated workflow and checks all 16 selected output/reference
hashes against `expected/fresh_modules_manifest.json`. It fails on any mismatch.
`rebuild_verification.json` records each comparison. `--core-only` skips only
the taxonomy mapping/ABox pair for a shorter diagnostic run; it is not the
complete reproduction gate.

Outputs are under `new-output/data/processed/ontology/`. One serialization per
module is selected; do not add the retired `rubalkhali_kb.owl` alias or duplicate
OWL/TTL versions to the asserted union. Copy `expected/catalog-v001.xml` beside
the selected modules for offline import resolution. The catalogue maps both
stable ontology IRIs and selected document IRIs to local files.

To repeat the exhaustive taxonomy structural and Turtle syntax gate, install
Raptor 2.0.16 using the checksum-pinned `workflow/bin/bootstrap_raptor.sh` (requires
the usual C build tools and libxml2 headers), add `workflow/.raptor-bin/bin` to
PATH, then run:

```sh
python scripts/validation/validate_taxonomy_abox_streaming.py \
  --input /absolute/path/to/new-output/data/processed/ontology/rubalkhali_taxonomy_abox.ttl \
  --output /absolute/path/to/new-output/taxonomy_validation.json
```

## Scope and provenance

The full taxonomy is regenerated from 1,271 source profile columns. The frozen
SRA-linkage and control inclusion policies determine which profiles produce
the 1,236 represented taxonomy processes; those assignments are not invented
physical-run identities. The complete source tables remain available here.

SIO 1.59, ENVO 2025-10-20, PATO 2025-05-14 and UO 2023-05-25 are included as
the loaded reference modules. Full NCBITaxon is a mapping source; the generated
ecosystem module supplies the selected taxon vocabulary. Full ChEBI and RO are
not independently loaded by this release. No implicit remote import expansion
is part of the release contract.

The initial full Nextflow DAG passed source/graph validation. Staging then
identified old version annotations in a second serialization of the root
subject. The corrected stamp changes only those root metadata annotations;
it preserves scientific entity axioms and produces the final published hash.
The original DAG and the subsequent metadata correction are documented
separately in `validation/`. The standalone driver reproduces the corrected
metadata directly; it does not repeat the earlier stamping defect.

Before importing the generated site module into the pinned Virtuoso engine,
use `scripts/release/kg/prepare_wkt_import.py` to produce a separate loader
copy. Follow `scripts/release/kg/WKT_IMPORT.md`: exactly 70 point literals
receive a whitespace-only adapter that prevents the engine's short-token
binary32 storage path; the polygon, source digits and original module hash
are unchanged. The same adapter is required when importing native N-Quads
downloads, whose serializer removes that whitespace. Never replace the
published original bytes with a loader copy. This additional import step
does not change the 16-module source-generation hash replay contract.

The materialization rule implementation is provided under `scripts/release/kg/`.
Its README defines a finite rule contract; it is not unrestricted OWL DL
reasoning. Source-derived query expectations are in `expected/query_expectations/`.
The operational ELK LITE check is a limited projection and is not a claim of
full OWL consistency or OWL 2 EL conformance. This source package alone does
not assert successful public deployment or public FASTQ availability.

The actual inference controller used a separate Python 3.8.10 environment:
RDFLib 4.2.2, pyparsing 2.4.6, isodate 0.6.0, six 1.14.0 and setuptools 45.2.0.
The scientific-generation environment above uses Python 3.11.14/RDFLib 7.1.4.
`scripts/release/kg/inference_runtime.json` records the exact observed versions,
engine image digest, 500,000-triple batches and `hash_join_enable=1`.
The final engine configuration uses
`[Parameters] TransactionAfterImageLimit=250000000`, verified by
`sys_stat('txn_after_image_limit')` returning 250000000. The former
50,000,000-byte limit caused a recorded SR325 failure during a subproperty
update; it was not convergence. The unchanged guarded materializer resumed
with 500,000-triple batches in `materialization-transaction-cap`, preserving
the earlier failed report. A successful final zero-addition pass and the
remaining release gates are still required; this package does not establish
their outcome. Follow the adjacent materializer README for fresh starts and
the explicit checkpoint/resume safeguards.
To create a separate controller environment when Python 3.8.10 is available:

```sh
python3.8 -m venv /absolute/path/to/new-inference-environment
/absolute/path/to/new-inference-environment/bin/python -m pip install --no-deps \
  -r scripts/release/kg/inference-requirements.lock
```

Check that this interpreter reports 3.8.10 before running the controller.
These pins identify observed package versions, not byte-identical host
distribution builds. They do not replace the exact pinned Virtuoso image
or the materializer's fixture and full closure checks.

## Repeat the source-derived query gates

The package includes the gate driver, all five frozen expectation tables,
the exact three printed SELECT listings in `paper/05_validation.tex`, and
the archived executable XRF query/results under `evidence/competency-query/`.
No manuscript prose, private review tree or endpoint-derived replacement
expectations are needed. From the extracted source directory and pinned
environment, run:

```sh
python scripts/release/kg/query_gates.py \
  --base-url https://rubalkhali.science \
  --root "$PWD" \
  --expectations "$PWD/expected/query_expectations" \
  --paper "$PWD/paper" \
  --output-dir /absolute/path/to/new-query-gate-report
```

For a candidate deployment, replace `--base-url` with its origin; use
`--sparql-url` only if the direct endpoint is hosted separately. The checker
compares exact source-derived tuples (46 field-XRF rows, all 48 genus-profile
rows for the emitted run label `FASTQ dataset for ERR16061083`,
360 same-visit temperature/taxon rows, 70 sites and six PCR controls),
preserving multiplicity and documented numeric tolerances. It tests direct
SPARQL, API modes, explicit graph selection and the taxonomy API. Do not
replace expected tables with observed endpoint results or treat timeout and
truncation as success.

The printed genus query selects this complete named profile, not an arbitrary
LIMIT 100 preview. `scripts/release/kg/taxonomy_all_runs.rq` retains the full
all-run formulation without LIMIT for a locally loaded snapshot or a
long-running analysis. No interactive performance claim is made for that
all-run query: earlier global preview variants exceeded the candidate's
300-second timeout. Historical `taxonomy_first100.tsv` is retained as prior
evidence, not used for the current complete-profile gate. Its raw lineage
strings did not match the RDF display encoding; the independent corrected
projection is `taxonomy_first100_display_corrected.tsv`.
`validation/taxonomy-preview-timeouts/` preserves both measured failure
reports and the exact tested queries. The profile restriction changes the
scientific question to the complete named profile; it is not evidence that
the former global query was optimized successfully.

The 48 expected tuples were freshly derived from the full frozen count table,
taxonomy mapping, sample-to-run allocation and graph labels, not sliced from
the former 100-row preview. After the complete source rebuild above, regenerate
the taxonomy and environmental expectations using the pinned scientific
environment (replace the rebuild-output path):

```sh
python scripts/release/derive_query_expectations.py \
  --source "$PWD" \
  --mapping /absolute/path/to/rebuild-output/taxonomy_mapping/mapped_taxonomy_corrected.json \
  --ecosystem /absolute/path/to/rebuild-output/data/processed/ontology/ecosystem_module.ttl \
  --modules /absolute/path/to/rebuild-output/data/processed/ontology \
  --reference-dir "$PWD/data/ontologies" \
  --run-accession ERR16061083 \
  --output /absolute/path/to/new-source-expectations
```

This reads the complete frozen feature-count table and tractable regenerated
modules, not the large generated taxonomy ABox or an endpoint response.
`expected/query_expectations/source_expectations_manifest.json` records the
source hashes and the complete-table selection rule. Keep the existing
site/control/XRF expectation files alongside these regenerated tables.
The categorical lineage field follows the frozen RDF producer's exact
`Domain: ...; Phylum: ...; ...; Genus: ...` format. The accompanying
`taxonomy_lineage_source_projection.tsv` preserves raw classifier identity
and emitted literal side by side. Numeric counts, aggregation keys and
relative-abundance denominators are unchanged by this display projection.

The inference-specific mode gate requires zero ancestor-role results from
asserted data and the exact six source-derived roles from materialized data:

```sh
python scripts/release/kg/mode_gates.py \
  --base-url https://rubalkhali.science \
  --root "$PWD" \
  --output-dir /absolute/path/to/new-mode-gate-report
python -m pytest -q tests/test_kg_query_gates.py tests/test_kg_mode_gates.py
```

The duplicated default-path expectation files and `ontology/rubalkhali.owl`
plus `ontology/rubalkhali_controls.ttl` support these unchanged test interfaces.
Their bytes are independently hashed in the source manifest.
`tests/browser_kg_candidate.py` is the real-browser gate, without request mocks.
The browser worker used Python 3.10.16 through uv, Playwright 1.62.0 and
Chromium 151.0.7922.173. The inference-specific browser case also needs
RDFLib 7.6.0. Exact observed Python dependencies are pinned in
`scripts/release/kg/browser-requirements.lock`; `browser_runtime.json`
distinguishes this from the generation and inference-controller environments.
With uv and the recorded system Chromium available, run from this directory:

```sh
uv run --no-project --python 3.10.16 \
  --with-requirements scripts/release/kg/browser-requirements.lock \
  python tests/browser_kg_candidate.py \
  --base-url https://rubalkhali.science --release-root "$PWD" \
  --output-dir /absolute/path/to/new-browser-report \
  --check-materialized --check-all-examples --check-downloads
```

Use these completed-release checks only after the candidate has materialized
graphs and download metadata. They fail rather than accept pending release
state. The browser default is `/usr/bin/chromium`; `--chromium` selects the
explicit binary when installed elsewhere.

The synthetic materialization fixtures and their test sources are included:
`verify_staging_fixture.py`, `verify_batch_resume_fixture.py`,
`entailment_fixture.ttl` and `tests/test_release_entailment.py`. Their live
variants only target new `urn:eq:release-test:` graphs. Supply your own
SQL-stdin runner configuration for the isolated database; no administrator
connection configuration or credentials are bundled. The local rule tests
run in the pinned scientific environment with
`python -m pytest -q tests/test_release_entailment.py`.

No new licence or redistribution permission is granted by this packaging
step. Existing third-party notices remain in their files. Project licensing
must be established with the authors; do not infer a licence from availability.
