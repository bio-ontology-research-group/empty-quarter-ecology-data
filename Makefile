SHELL := /usr/bin/env bash
PYTHON ?= python3
VENV ?= .venv
MAMBA ?= micromamba
CONDA_ENV ?= .conda-env
SOURCE_DATE_EPOCH ?= 1785888000

.PHONY: bootstrap env env-linux-exact manifest verify test paper evidence-stub clean

bootstrap:
	bash scripts/release/bootstrap_package_layout.sh .

env:
	uv venv --python 3.11 $(VENV)
	uv pip sync --python $(VENV)/bin/python environment/requirements.lock.txt

env-linux-exact:
	$(MAMBA) create --yes --prefix "$(CURDIR)/$(CONDA_ENV)" \
		--file environment/conda-linux-64.lock
	"$(CURDIR)/$(CONDA_ENV)/bin/python" -m pip install \
		--no-deps --require-hashes -r environment/pip-overlay.lock.txt

manifest: bootstrap
	$(PYTHON) scripts/release/build_repository_manifest.py . --write

verify: bootstrap
	$(PYTHON) scripts/release/verify_repository.py .

test: bootstrap
	$(PYTHON) scripts/manuscript/test_manuscript_consistency.py
	$(PYTHON) -m pytest -q \
		workflow/tests/test_capture_source_snapshot.py \
		workflow/tests/test_control_analysis_inputs.py \
		workflow/tests/test_core_kg_wiring.py \
		workflow/tests/test_data_paper_figure_wiring.py \
		workflow/tests/test_ecology_workflow_wiring.py \
		workflow/tests/test_environment_lock_alignment.py \
		workflow/tests/test_release_dictionary.py

paper:
	cd paper && SOURCE_DATE_EPOCH=$(SOURCE_DATE_EPOCH) FORCE_SOURCE_DATE=1 \
		latexmk -pdf -interaction=nonstopmode -halt-on-error sn-article.tex
	cd paper && SOURCE_DATE_EPOCH=$(SOURCE_DATE_EPOCH) FORCE_SOURCE_DATE=1 \
		latexmk -pdf -interaction=nonstopmode -halt-on-error supplement.tex

evidence-stub: bootstrap
	@echo "Stub only: run every real KG build on ws or Ontolinator."
	workflow/bin/bootstrap_nextflow.sh run workflow/main.nf \
		-profile bare,test -stub-run \
		--project_root "$(CURDIR)" \
		--ecology_paper "$(CURDIR)/../ecology/empty-quarter-amplicon" \
		--stage evidence \
		--outdir "$(CURDIR)/results/evidence-stub"

clean:
	cd paper && latexmk -C sn-article.tex && latexmk -C supplement.tex
