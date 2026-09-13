# Repository and manuscript CI

The `validate` workflow verifies repository integrity before running the
manuscript consistency tests, workflow wiring tests and both TeX builds.
It does not rebuild the KG or test the live service. Live acceptance evidence
for KG v3.0.0 is in `evidence/kg-v3.0.0/post-deployment-validation.json`.

The September 13 CI repair refreshes stale repository/deposit checksums and
bibliography citation inventory, and updates manuscript assertions against
the current prose and dated evidence. It does not change manuscript prose,
the deployed graph, the versioned downloads or the `kg-v3.0.0` tag.

## Preparing a source-only correction

From the repository root, use Python 3.11. Install the CI test dependencies
listed in `.github/workflows/validate.yml`; the scientific workflow's pinned
environment remains under `environment/`.

```sh
bash scripts/release/bootstrap_package_layout.sh .
python scripts/manuscript/audit_bibliography_custody.py \
  --paper-root paper --output evidence/bibliography/source_custody.json
python scripts/manuscript/update_pre_release_manifest.py \
  --stage . --refresh-declared
```

`--refresh-declared` updates existing rows only. It preserves their categories
and licence dispositions. An absent bulk artifact retains its recorded hash
only if `BULK_ARTIFACTS.tsv` has exactly the same size and hash; this is not a
claim that the artifact was downloaded or revalidated. Use the full staging
mode, without this option, when preparing a new deposit inventory.

Stage the intended source changes and any new files explicitly. Then regenerate
`FILE_MANIFEST.tsv` **last**: it covers every Git-indexed file except itself,
including `PRE_RELEASE_MANIFEST.tsv`.

```sh
python scripts/release/build_repository_manifest.py . --write
git add FILE_MANIFEST.tsv
python scripts/release/verify_repository.py .
python scripts/manuscript/test_manuscript_consistency.py
python -m pytest -q \
  workflow/tests/test_capture_source_snapshot.py \
  workflow/tests/test_core_kg_wiring.py \
  workflow/tests/test_data_paper_figure_wiring.py \
  workflow/tests/test_ecology_workflow_wiring.py \
  workflow/tests/test_environment_lock_alignment.py \
  workflow/tests/test_release_dictionary.py
make paper
```

Install `latexmk`, `texlive-latex-extra` and `texlive-science` for the last step.
Check the same commands in a clean checkout so ignored files cannot conceal
missing inputs. After pushing, inspect the GitHub run for that exact commit;
local success alone does not establish that CI passed. Existing release tags
and their historical CI runs remain unchanged.
