# Empty Quarter reproducibility workflow

This Nextflow DSL2 workflow rebuilds the evidence shared by the Scientific Data
and ecology manuscripts. It treats the repository and paper sources as
read-only inputs, runs each stage in an isolated task directory, and publishes
only declared outputs with checksums and execution reports.

The source-provenance stage uses explicit manuscript allowlists. For the data
descriptor, `sn-article.tex` and `supplement.tex` are the only roots; for the
ecology paper, `main.tex` and `supplement.tex` are the only roots. Historical
alternative manuscripts, TeX build products, and orphan figures cannot enter
the captured release source or the paper-build sandbox.

## Stages

- `evidence`: exact source snapshots plus an executed-environment record;
  deterministic regeneration and byte regression of the data descriptor's
  60-site transect-altitude profile and figure;
  fresh generation of the site, environmental-measurement, sample, XRF, DNA,
  SRA and QC RDF modules from declared source inputs, with byte-for-byte
  regression against the staged release candidate; exact-cell environmental-metadata
  curation with range, campaign-date and RDF regression checks; the
  sample/release ledger; the field-versus-laboratory XRF audit; and a
  fail-closed chemical-identifier audit against pinned ChEBI and PubChem
  records. It also executes the archived field-XRF Site 10 competency query
  against the canonical base, sites, and XRF OWL modules and requires exactly
  46 result rows from two field-XRF processes.
- `core`: evidence plus the canonical grouped ecology analyses, including
  site-level spatial, campaign/rainfall, paired-PMA, and laboratory-XRF
  community tests; a rebuilt prevalence-filtered ASV alignment and tree;
  collection-order and leakage-free geographic-prediction audits; ASV
  resolution and neighbour-graph sensitivity; paired compartment distance
  decay and turnover decomposition; the post-hoc evenness decomposition;
  site-level climate associations; and the short-term rise-and-decay rainfall
  suite. The rainfall stage repeats the complete peak search with $19,999$
  campaign-stratified lag rotations and $9,999$ whole-site bootstrap draws,
  then reruns it across rainfall products, cohorts, contaminant filtering, pH
  adjustment and alternative route trends.
- `advanced`: core plus bounded phylogenetic-signal and encoded-function
  diagnostics, the conditional-network and resolution-matched functional
  analyses, followed by deterministic manuscript
  figures built directly from the canonical result tables. The functional
  analysis requires the genome-level coverM directory and eggNOG annotation
  file explicitly.
- `full`: advanced analyses; the freshly generated tractable RDF modules; a
  fresh, conservative Trips 1--5 taxonomy mapping and clean ontology module;
  a newly generated taxonomy ABox that consumes the freshly generated SRA
  module; the non-live ELK/ShEx/XRF/IRI validation suite; and clean builds of both
  manuscripts. Invalid or ambiguous external taxon mappings are replaced by
  lineage-and-rank-scoped project identifiers and retained in a decision
  ledger. The generated multi-gigabyte ABox is covered by its own streaming
  relationship audit plus an independent full-file Turtle parser; ShEx
  coverage is reported separately and is not implied by that gate.

`--run_kg true` runs the same three fail-closed taxonomy/KG tasks from any
lighter stage. Neither the 1.6-GB NCBI Taxonomy scan nor the high-memory ABox
generation task is created for ordinary `evidence`, `core`, or `advanced`
runs unless that flag is set.

The authoritative inclusion/retirement status of every analysis is in
`analysis_manifest.tsv`. Retired analyses remain in the repository for
provenance but are not part of the manuscript-generating path.
In particular, the legacy all-trip script that called a same-matrix elemental
score “salinity” is retired; the advanced stage consumes the canonical
laboratory-XRF result produced in `core` and does not execute that script.

## Run locally

The installed launcher on some workstations is too old for Java 21. The
bootstrap wrapper downloads the current launcher into a gitignored directory
and pins the workflow to Nextflow 25.10.4, which is also available on IBEX.
Create the hashed Python environment once before a real core, advanced or full
run:

```bash
uv venv --python 3.11 .venv
uv pip sync --python .venv/bin/python workflow/requirements.lock.txt
```

The bootstrap wrapper automatically prepends this environment to `PATH`; no
interactive activation is required. The `evidence` stage can run with a
compatible system Python, but later stages intentionally fail if their pinned
scientific dependencies are unavailable.

Use `-resume` only after a transient failure when source code, canonical
inputs, and manuscript files have not changed. The project paths are passed as
read-only values rather than staged file inputs, so a clean release run must
omit `-resume`; this prevents Nextflow from reusing a task whose external
source changed without changing its path.

The analysis environment for a KG/full run must also provide Raptor `rapper`
`2.0.16`. Run `workflow/bin/bootstrap_raptor.sh` to build the exact version
from its checksum-pinned upstream source archive; the Nextflow bootstrap adds
that cached executable to `PATH`. This parser is intentionally independent of
the Python streaming scanner. `environment.yml` pins Java 21 and Groovy 4 for
the generator; a container build must pre-populate the Groovy `@Grab`
dependencies pinned in the project scripts so an IBEX task does not depend on
an interactive download.

```bash
workflow/bin/bootstrap_nextflow.sh run workflow/main.nf \
  -profile bare,test \
  --project_root "$PWD" \
  --ecology_paper "$PWD/empty-quarter-amplicon" \
  --stage evidence
```

`bare` is explicitly containerless: every task uses the current host
environment. `conda-linux-64.lock` is the exact package-build lock used for the
reviewed Linux run; `pip-overlay.lock.txt` adds only the two hash-locked
pip-only packages without replacing Conda dependencies. `environment.yml`
remains the editable cross-platform recipe. The execution stage records the
actual package inventory and the hashes of all three declarations. For a fully
containerized release, build from the explicit lock and supply the resulting
analysis and TeX container images:

```bash
workflow/bin/bootstrap_nextflow.sh run workflow/main.nf \
  -profile local \
  --analysis_container ghcr.io/ORG/empty-quarter-analysis@sha256:DIGEST \
  --tex_container ghcr.io/ORG/empty-quarter-tex@sha256:DIGEST \
  --stage full
```

The Python layer is fully resolved in `requirements.lock.txt`, including
artifact hashes for Linux/x86-64 and Python 3.11. Recreate it with:

```bash
uv venv --python 3.11 .venv
uv pip sync --python .venv/bin/python workflow/requirements.lock.txt
```

Regenerate the lock only after intentionally editing `requirements.in`:

```bash
uv pip compile workflow/requirements.in \
  --python-version 3.11 \
  --python-platform x86_64-unknown-linux-gnu \
  --generate-hashes \
  --output-file workflow/requirements.lock.txt
```

`environment.yml` additionally pins the R and command-line components used by
the advanced diagnostics. Release containers must be referenced by immutable
digest.

On a workstation with Docker but no Singularity, use `ws_host`. All analysis,
including `CAPTURE_EXECUTION_ENVIRONMENT`, then runs in the actual host
environment; its executable versions, Python/R packages, and lock-file hashes
are recorded without claiming that analysis was containerized. Only
`BUILD_PAPERS` runs in Docker, and the profile rejects a paper build unless
the TeX image is an immutable `@sha256:` reference:

```bash
workflow/bin/bootstrap_nextflow.sh run workflow/main.nf \
  -profile ws_host \
  --project_root "$PWD" \
  --ecology_paper "$PWD/empty-quarter-amplicon" \
  --outdir "$PWD/results/reproducibility-release-UNIQUE_ID" \
  --tex_container ghcr.io/ORG/empty-quarter-tex@sha256:DIGEST \
  --pma_asv_table /absolute/path/to/PMA_ASV_table.tsv \
  --coverm_dir /absolute/path/to/coverm_profiles.tar.gz \
  --eggnog_annotations /absolute/path/to/eq.emapper.annotations.gz \
  --measured_function_inputs /absolute/path/to/measured_function_inputs.tar.gz \
  --stage full
```

Do not pass `--analysis_container` with `ws_host`; the profile deliberately
executes analysis on the host. On a workstation that does provide Singularity,
the existing `ws` profile remains available for containerizing both analysis
and the paper build:

```bash
workflow/bin/bootstrap_nextflow.sh run workflow/main.nf \
  -profile ws \
  --project_root "$PWD" \
  --ecology_paper "$PWD/empty-quarter-amplicon" \
  --outdir "$PWD/results/reproducibility-release-UNIQUE_ID" \
  --analysis_container /absolute/path/analysis-IMAGE_SHA256.sif \
  --tex_container /absolute/path/tex-IMAGE_SHA256.sif \
  --pma_asv_table /absolute/path/to/PMA_ASV_table.tsv \
  --coverm_dir /absolute/path/to/coverm_profiles.tar.gz \
  --eggnog_annotations /absolute/path/to/eq.emapper.annotations.gz \
  --measured_function_inputs /absolute/path/to/measured_function_inputs.tar.gz \
  --stage full
```

A local SIF is hashed by the environment-capture task. An OCI reference must
contain `@sha256:` to constitute an immutable identity. Never reuse the
release output directory for a separate invocation.

## Run on IBEX

Do not run analysis on the login node. Submit the Nextflow driver itself as a
small Slurm job, then let the workflow submit all tasks through the `ibex`
profile:

```bash
module load nextflow/25.10.4 singularity/3.9.7 groovy/4.0.7
sbatch --account=c2014 --partition=debug workflow/ibex/launch_debug.sbatch
```

After the debug workflow passes, submit `workflow/ibex/launch_full.sbatch`.
Set `EQ_PROJECT_ROOT`, `EQ_ECOLOGY_PAPER`, `EQ_ANALYSIS_CONTAINER`, and
`EQ_TEX_CONTAINER` to immutable paths/digests before submission. The IBEX
launcher uses the checksummed release-candidate PMA, CoverM, eggNOG, and
measured-function artifacts. Override `EQ_PMA_ASV_TABLE`, `EQ_COVERM_DIR`,
`EQ_EGGNOG_ANNOTATIONS`, or `EQ_MEASURED_FUNCTION_INPUTS` only when a later
version is intentionally selected.

For an advanced run outside the launcher, provide all four inputs:

```bash
workflow/bin/bootstrap_nextflow.sh run workflow/main.nf \
  -profile ibex \
  --stage advanced \
  --pma_asv_table /absolute/path/to/PMA_ASV_table.tsv \
  --coverm_dir /absolute/path/to/coverm_profiles.tar.gz \
  --eggnog_annotations /absolute/path/to/eq.emapper.annotations.gz \
  --measured_function_inputs /absolute/path/to/measured_function_inputs.tar.gz
```

## Knowledge-graph generation and validation contract

The evidence branch first runs `GENERATE_CORE_KG_MODULES` in an isolated
workspace. `rubalkhali.owl` is treated as the curated, versioned TBox/RBox
input; the site, environmental-measurement, sample, XRF, DNA, SRA and QC
modules are regenerated in dependency order from source tables. Each fresh
module must be byte-identical to the staged release candidate. The release
ledger and executable field-XRF query consume this generated bundle rather
than the checkout's prebuilt modules. The same task independently recounts
the class, object-property and datatype-property declarations in the curated
base ontology and fails if they differ from the manuscript values; the
machine-readable result is `ontology_declaration_audit.json`.

The KG/full branch then has three additional data-dependent tasks:

1. `BUILD_TAXONOMY_MAPPING` reads the complete Trips 1--5 taxonomy and feature
   table, the historical canonical mapping, and the pinned NCBI Taxonomy OWL.
   It publishes corrected JSON/TSV mappings, a checksum-bearing passing
   manifest, the clean `ecosystem_module` in OWL and Turtle, a source-schema
   audit, and the complete correction decision ledger.
2. `GENERATE_TAXONOMY_ABOX` accepts only that corrected passing manifest and
   uses explicit taxonomy, feature-table, SRA-sheet, freshly generated SRA,
   and clean-module inputs. It
   publishes the newly generated Turtle ABox, a deterministic input/output
   manifest, and SHA-256 checksums. The streaming generator requests 48 GB RAM
   and sets a 32-GB JVM heap; it does not retain the full ABox in OWLAPI.
3. `KG_VALIDATE` verifies the core-module, mapping and taxonomy-ABox checksum
   sets, rejects both the repository's pre-existing taxonomy ABox and its
   prebuilt tractable modules as validation inputs, and validates the exact
   newly generated bundle.
   It publishes the full-file syntax/structural report, validation logs, copied
   input manifests, and checksums for the validation bundle.

The default inputs can be overridden with
`--taxonomy_source_taxonomy`, `--taxonomy_feature_table`,
`--taxonomy_canonical_mapping`, `--taxonomy_ncbi_owl`,
and `--taxonomy_sra_sheet`. A release run must use the complete Trips 1--5
inputs; the generator's small fixture mode is intentionally not exposed by
this workflow.

## Reproducibility contract

- All random analyses must use recorded seeds.
- Each invocation creates three deterministic authoritative source archives
  (analysis/workflow, data-paper, and ecology-paper) plus a per-file SHA-256
  manifest. Git commit, status, and patch files are regenerated as contextual
  metadata for that invocation. If `.git` is absent, the exported tree is
  identified directly by current file hashes; metadata from an earlier run is
  never copied. The data-paper archive explicitly includes
  `zenodo/sparql/` without traversing the multi-gigabyte Zenodo staging tree.
- `CAPTURE_EXECUTION_ENVIRONMENT` runs inside the analysis task environment
  and records actual executable paths, versions, Python packages, R session
  information, profile mode, and the declared/detected container identity.
  The host-side source-capture process is labelled separately and must not be
  cited as the analysis environment.
- `BUILD_PAPERS` records the actually executed TeX environment separately,
  verifies every staged manuscript source against the same invocation's
  source snapshot, embeds the source and analysis-environment manifest hashes
  in its provenance logs, and archives the competency-query JSON, 46-row TSV,
  exact query, and their checksum manifest.
- The bootstrap wrapper records the shell-escaped launch command, selected
  profile, launcher and controlled threading variables under
  `pipeline_info/`. These files describe one invocation only.
- If analysis and paper/environmental-metadata stages are necessarily run as
  separate invocations, publish both launch records, source manifests, and
  environment bundles and describe them as separate runs. Do not merge their
  outputs into evidence for a single end-to-end execution.
- Source and result files receive SHA-256 checksums.
- Field environmental sheets remain immutable inputs. A versioned
  exact-cell ledger moves or quarantines values, the generated curated TSV
  and supplementary table must match their checked-in copies byte for byte,
  and retained temperature, pressure and humidity values must pass declared
  physical ranges. The same ledger drives the environmental RDF generator.
- XRF chemical identifiers are resolved from one canonical YAML file against
  the pinned ChEBI OWL and dated PubChem snapshot. Unsupported mappings remain
  explicit nulls, and the two legacy ChEBI-only YAML files are regression
  tested as exact projections of the canonical mapping.
- The field-XRF Site 10 competency query runs at every `evidence` stage
  against staged canonical base, sites, and XRF OWL inputs. It fails unless
  RDFLib returns exactly 46 rows from two field-XRF processes targeting only
  Site 10; the exact query, engine version, input hashes, results, and
  checksums are retained.
- Corrected taxonomy mappings retain every rejected or contextualized external
  mapping in an audit ledger; no lexical match is silently asserted as an
  external taxon identity.
- Nextflow writes trace, report, timeline, and DAG artifacts.
- No manuscript number is authoritative unless it is generated by this workflow.
- Manuscript result figures are rendered from workflow outputs, fail closed if
  a claim verdict changes, omit PDF creation timestamps, and carry an
  input/output checksum manifest.
- Pending pH/EC measurements and public accessions enter through versioned input
  manifests; they are never entered manually into TeX.
