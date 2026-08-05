# Reproducing the data descriptor

This repository identifies every manuscript input, generator, environment and
validation rule needed to reproduce the submitted data descriptor. Small and
medium inputs are committed directly. Files that exceed normal Git limits are
listed in `BULK_ARTIFACTS.tsv` with their uncompressed byte count and SHA-256.

The repository is a private pre-release candidate. It does not claim a DOI,
immutable public deposit, or public raw-read availability. The reported tables,
knowledge-graph modules and manuscript can nevertheless be reproduced from the
frozen derived inputs. Rebuilding those inputs from raw sequencing reads remains
blocked until the run records named in the manuscript become publicly usable.

## 1. Checkout and install the bulk inputs

Authenticate `gh` for the BORG private repository, then run:

```bash
git clone git@github.com:bio-ontology-research-group/empty-quarter-data-paper.git
cd empty-quarter-data-paper
bash scripts/release/download_bulk_artifacts.sh
bash scripts/release/bootstrap_package_layout.sh .
python3 scripts/release/verify_repository.py .
```

The downloader uses the pinned private pre-release `v0.6.0-rc32`, expands only
the two plain-text compressed assets, and verifies every installed byte stream.
It never accepts an existing file with the wrong size or digest.

## 2. Recreate the software environment

The Python environment is hash-locked for CPython 3.11 on Linux/x86-64:

```bash
uv venv --python 3.11 .venv
uv pip sync --python .venv/bin/python environment/requirements.lock.txt
```

`environment/environment.yml` additionally pins Java, Groovy, R, Raptor,
MAFFT and FastTree for the full knowledge-graph and cross-paper workflow. An
executed workflow records the actual tool versions and container identity; the
environment file alone is not treated as proof of execution.

## 3. Run fast regression tests

```bash
make bootstrap
make test
make paper
```

`make paper` builds both `paper/sn-article.tex` and `paper/supplement.tex`.
The manuscript roots are explicit; retired drafts and local TeX products are
not inputs. `make test` runs manuscript, package, and workflow-wiring checks
that do not generate a KG. The complete generator and semantic-validation suite
runs on `ws` or Ontolinator in the next step.

## 4. Rebuild the data and knowledge graph remotely

Every real knowledge-graph build must run on `ws` or Ontolinator, not on a local
workstation. Clone the exact repository revision on the selected host, install
the checksum-pinned bulk inputs, recreate the environment, and run the workflow
there. The evidence stage regenerates the environmental table, figure,
tractable RDF modules, release ledger, XRF audit and archived competency query:

```bash
# Run this complete block in a shell on ws or Ontolinator.
git clone git@github.com:bio-ontology-research-group/empty-quarter-data-paper.git
cd empty-quarter-data-paper
bash scripts/release/download_bulk_artifacts.sh
bash scripts/release/bootstrap_package_layout.sh .
.venv/bin/python -m pytest -q tests workflow/tests
workflow/bin/bootstrap_nextflow.sh run workflow/main.nf \
  -profile bare \
  --project_root "$PWD" \
  --ecology_paper /absolute/path/to/empty-quarter-ecology-reproducibility/empty-quarter-amplicon \
  --stage evidence \
  --outdir "$PWD/results/data-evidence-$(date -u +%Y%m%dT%H%M%SZ)"
```

Add `--run_kg true` on the same remote host to rebuild the corrected taxonomy mapping and the full
taxonomy ABox and to run the non-live validation suite. That path requires the
bulk feature table and NCBI Taxonomy snapshot and is designed for a machine
with at least 32 GB of Java heap plus scratch space for the multi-gigabyte ABox:

```bash
workflow/bin/bootstrap_nextflow.sh run workflow/main.nf \
  -profile bare \
  --project_root "$PWD" \
  --ecology_paper /absolute/path/to/empty-quarter-ecology-reproducibility/empty-quarter-amplicon \
  --stage evidence \
  --run_kg true \
  --taxonomy_source_taxonomy "$PWD/metadata/taxonomy/taxonomy-trips1-5.tsv" \
  --taxonomy_feature_table "$PWD/metadata/taxonomy/feature-table-trips1-5.tsv" \
  --taxonomy_canonical_mapping "$PWD/ontology/mapped_taxonomy.tsv" \
  --taxonomy_ncbi_owl "$PWD/data/ontologies/ncbitaxon.owl" \
  --taxonomy_sra_sheet "$PWD/metadata/sra-submissions/submission-sheet.tsv" \
  --outdir "$PWD/results/full-kg-$(date -u +%Y%m%dT%H%M%SZ)"
```

The workflow writes isolated outputs, checksums, source snapshots, execution
records, Nextflow trace/report/timeline files and validation reports. Do not use
`-resume` after changing any source, input or manuscript byte stream.

Copy the completed remote report directory back without changing it, then
verify its manifest before archiving it as release evidence. A local
`-stub-run` is permitted only to check workflow wiring; it is not KG validation.

## 5. Scope of reproducibility

The package supports:

- deterministic regeneration and byte comparison of every tractable RDF module;
- fresh taxonomy mapping and taxonomy-ABox generation from the canonical table;
- ShEx/OWL/project-invariant checks, a streaming full-ABox audit and archived
  competency-query replay;
- recreation of the manuscript figure and tables; and
- clean builds of the data descriptor and supplement.

It does not yet support an unauthenticated public download or reconstruction of
the canonical amplicon, shotgun and PMA inputs from raw reads. Those are release
and accession gates, not silently filled provenance steps.
