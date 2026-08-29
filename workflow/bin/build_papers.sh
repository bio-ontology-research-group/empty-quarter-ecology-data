#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 13 ]]; then
  echo "usage: $0 PROJECT_ROOT ECOLOGY_PAPER OUTPUT_DIR RELEASE_EVIDENCE XRF_AUDIT SUBMISSION_FIGURES DATA_PAPER_FIGURES ENVIRONMENTAL_METADATA COMPETENCY_QUERY SOURCE_PROVENANCE EXECUTION_ENVIRONMENT EXECUTION_MODE TEX_CONTAINER" >&2
  exit 64
fi

project_root=$1
ecology_paper=$2
output_dir=$3
release_evidence=$4
xrf_audit=$5
submission_figures=$6
data_paper_figures=$7
environmental_metadata=$8
competency_query=$9
source_provenance=${10}
execution_environment=${11}
execution_mode=${12}
tex_container=${13}
task_root=$PWD/paper-sandbox

case "$output_dir" in
  /*) ;;
  *) output_dir="$PWD/$output_dir" ;;
esac

export SOURCE_DATE_EPOCH="${SOURCE_DATE_EPOCH:-1785888000}"
export FORCE_SOURCE_DATE="${FORCE_SOURCE_DATE:-1}"
export TZ="${TZ:-UTC}"
export LC_ALL="${LC_ALL:-C.UTF-8}"

mkdir -p \
  "$task_root/data-paper" \
  "$task_root/ecology-paper/figures" \
  "$task_root/ecology-paper/generated" \
  "$output_dir/data_paper" \
  "$output_dir/ecology_paper" \
  "$output_dir/logs"

for required in \
  "$source_provenance/source_state.json" \
  "$source_provenance/snapshot_file_manifest.tsv" \
  "$source_provenance/SHA256SUMS" \
  "$execution_environment/execution_environment_manifest.json" \
  "$execution_environment/environment.tsv" \
  "$execution_environment/tool_versions.tsv" \
  "$execution_environment/SHA256SUMS" \
  "$competency_query/competency_query_validation.json" \
  "$competency_query/field_xrf_site10_results.tsv" \
  "$competency_query/field_xrf_site10.rq" \
  "$competency_query/SHA256SUMS" \
  "$data_paper_figures/transect_altitude.png" \
  "$data_paper_figures/transect_altitude_profile.tsv" \
  "$data_paper_figures/transect_altitude_summary.json" \
  "$data_paper_figures/SHA256SUMS"
do
  if [[ ! -s "$required" ]]; then
    echo "paper build evidence/provenance input is missing or empty: $required" >&2
    exit 66
  fi
done

(
  cd "$source_provenance"
  sha256sum -c SHA256SUMS
)
(
  cd "$execution_environment"
  sha256sum -c SHA256SUMS
)
(
  cd "$competency_query"
  sha256sum -c SHA256SUMS
)
(
  cd "$data_paper_figures"
  sha256sum -c SHA256SUMS
)

# Prove that the evidence consumed by this task is byte-identical to the
# canonical evidence against which the manuscript package is tested.
cmp "$release_evidence/release_evidence.json" \
  "$project_root/data/release/release_evidence.json"
cmp "$release_evidence/sample_ledger.tsv" \
  "$project_root/data/release/sample_ledger.tsv"
cmp "$xrf_audit/xrf_audit_summary.json" \
  "$project_root/analysis/xrf_audit/xrf_audit_summary.json"
cmp "$environmental_metadata/environmental_measurements_curated.tsv" \
  "$project_root/data/processed/metadata/environmental_measurements_curated.tsv"
cmp "$environmental_metadata/environmental_measurements_audit.json" \
  "$project_root/data/processed/metadata/environmental_measurements_audit.json"
cmp "$environmental_metadata/env_table.tex" \
  "$project_root/data-paper/env_table.tex"
cmp "$competency_query/field_xrf_site10.rq" \
  "$project_root/data-paper/zenodo/sparql/field_xrf_site10.rq"

python3 - \
  "$competency_query/competency_query_validation.json" \
  "$competency_query/field_xrf_site10_results.tsv" <<'PY'
import csv
import json
import sys
from pathlib import Path

evidence = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if (
    evidence.get("status") != "passed"
    or evidence.get("expected_rows") != 46
    or evidence.get("observed_rows") != 46
):
    raise SystemExit(
        "field-XRF competency-query evidence is not a 46-row pass"
    )
with Path(sys.argv[2]).open(newline="", encoding="utf-8") as handle:
    observed_rows = sum(1 for _ in csv.reader(handle, delimiter="\t")) - 1
if observed_rows != 46:
    raise SystemExit(
        "field-XRF competency-query TSV has "
        f"{observed_rows} data rows; expected 46"
    )
PY

python3 "$project_root/scripts/manuscript/test_manuscript_consistency.py" \
  > "$output_dir/logs/data_paper_consistency.log" 2>&1

# Stage only the source files needed for deterministic TeX builds. The data
# paper's release package is several gigabytes and has already been validated
# above; copying it into a TeX task would add no build coverage.
cp \
  "$project_root/data-paper/sn-article.tex" \
  "$project_root/data-paper/01_introduction.tex" \
  "$project_root/data-paper/02_methods.tex" \
  "$project_root/data-paper/02_methods_taxonomy.tex" \
  "$project_root/data-paper/03_knowledge_representation.tex" \
  "$project_root/data-paper/04_data_records.tex" \
  "$project_root/data-paper/05_validation.tex" \
  "$project_root/data-paper/06_usage.tex" \
  "$project_root/data-paper/supplement.tex" \
  "$project_root/data-paper/kr_supplement.tex" \
  "$project_root/data-paper/xrf_table.tex" \
  "$project_root/data-paper/sn-bibliography.bib" \
  "$project_root/data-paper/sn-jnl.cls" \
  "$project_root/data-paper/sn-mathphys-num.bst" \
  "$task_root/data-paper/"
cp "$data_paper_figures/transect_altitude.png" \
  "$task_root/data-paper/"
cp "$environmental_metadata/env_table.tex" "$task_root/data-paper/"
cp \
  "$environmental_metadata/environmental_measurements_curated.tsv" \
  "$environmental_metadata/environmental_measurements_audit.json" \
  "$output_dir/logs/"

cp \
  "$ecology_paper/main.tex" \
  "$ecology_paper/supplement.tex" \
  "$ecology_paper/ph_shared_v1.tex" \
  "$ecology_paper/sample.bib" \
  "$ecology_paper/olplainarticle.cls" \
  "$task_root/ecology-paper/"
cp \
  "$ecology_paper/generated/ph_shared_v1_values.tex" \
  "$ecology_paper/generated/ph_shared_v1_values.manifest.json" \
  "$task_root/ecology-paper/generated/"
cp \
  "$submission_figures/fig1_landscape.pdf" \
  "$submission_figures/fig2_soil_position.pdf" \
  "$submission_figures/fig3_function_controls.pdf" \
  "$submission_figures/figS_campaign_rainfall.pdf" \
  "$task_root/ecology-paper/figures/"
if [[ -f "$submission_figures/figure_manifest.tsv" ]]; then
  cp "$submission_figures/figure_manifest.tsv" \
    "$output_dir/logs/figure_manifest.tsv"
fi

python3 - \
  "$source_provenance/snapshot_file_manifest.tsv" \
  "$task_root" \
  "$output_dir/logs/source_snapshot_build_verification.tsv" <<'PY'
import csv
import hashlib
import sys
from pathlib import Path

manifest_path = Path(sys.argv[1])
task_root = Path(sys.argv[2])
output_path = Path(sys.argv[3])

expected = {}
with manifest_path.open(newline="", encoding="utf-8") as handle:
    for row in csv.DictReader(handle, delimiter="\t"):
        if row["type"] == "file":
            expected[(row["snapshot"], row["path"])] = row["sha256"]

checks = []
for snapshot, directory in (
    ("data_paper", task_root / "data-paper"),
    ("ecology_paper", task_root / "ecology-paper"),
):
    for path in sorted(directory.rglob("*")):
        if (
            not path.is_file()
            or path.suffix.lower() in {".pdf", ".png"}
        ):
            continue
        relative = path.relative_to(directory).as_posix()
        observed = hashlib.sha256(path.read_bytes()).hexdigest()
        wanted = expected.get((snapshot, relative))
        status = "passed" if wanted == observed else "failed"
        checks.append(
            (snapshot, relative, wanted or "MISSING", observed, status)
        )

failures = [item for item in checks if item[-1] != "passed"]
with output_path.open("w", newline="", encoding="utf-8") as handle:
    writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
    writer.writerow(
        ("snapshot", "path", "expected_sha256", "observed_sha256", "status")
    )
    writer.writerows(checks)
if failures:
    first = failures[0]
    raise SystemExit(
        "staged paper source differs from the per-run source snapshot: "
        f"{first[0]}/{first[1]}"
    )
PY

(
  cd "$task_root"
  find data-paper ecology-paper -type f -print0 |
    sort -z |
    xargs -0 sha256sum > "$output_dir/SOURCE_SHA256SUMS"
)

build_tex() {
  local directory=$1
  local basename=$2
  (
    cd "$directory"
    pdflatex -interaction=nonstopmode -halt-on-error "$basename.tex"
    bibtex "$basename"
    pdflatex -interaction=nonstopmode -halt-on-error "$basename.tex"
    pdflatex -interaction=nonstopmode -halt-on-error "$basename.tex"
  )
}

build_tex "$task_root/data-paper" sn-article
build_tex "$task_root/data-paper" supplement
build_tex "$task_root/ecology-paper" main
build_tex "$task_root/ecology-paper" supplement

cp "$task_root/data-paper/sn-article.pdf" "$output_dir/data_paper/"
cp "$task_root/data-paper/supplement.pdf" "$output_dir/data_paper/"
cp "$task_root/ecology-paper/main.pdf" "$output_dir/ecology_paper/"
cp "$task_root/ecology-paper/supplement.pdf" "$output_dir/ecology_paper/"

if grep -En \
  'undefined references|Citation .* undefined|There were undefined|undefined citations' \
  "$task_root/data-paper/sn-article.log" \
  "$task_root/data-paper/supplement.log" \
  "$task_root/ecology-paper/main.log" \
  "$task_root/ecology-paper/supplement.log"
then
  printf '%s\n' "Undefined TeX reference or citation detected" >&2
  exit 1
fi

python3 "$project_root/workflow/bin/pdf_metadata.py" \
  "$output_dir/data_paper/sn-article.pdf" \
  "$output_dir/data_paper/supplement.pdf" \
  "$output_dir/ecology_paper/main.pdf" \
  "$output_dir/ecology_paper/supplement.pdf" \
  > "$output_dir/logs/pdf_metadata.tsv"

(
  cd "$output_dir"
  find data_paper ecology_paper -type f -name '*.pdf' -print0 |
    sort -z |
    xargs -0 sha256sum > SHA256SUMS
)

cp "$task_root/data-paper/sn-article.log" \
  "$output_dir/logs/data-paper-sn-article.log"
cp "$task_root/data-paper/sn-article.blg" \
  "$output_dir/logs/data-paper-sn-article.blg"
cp "$task_root/data-paper/supplement.log" \
  "$output_dir/logs/data-paper-supplement.log"
cp "$task_root/data-paper/supplement.blg" \
  "$output_dir/logs/data-paper-supplement.blg"
cp "$task_root/ecology-paper/main.log" \
  "$output_dir/logs/ecology-main.log"
cp "$task_root/ecology-paper/main.blg" \
  "$output_dir/logs/ecology-main.blg"
cp "$task_root/ecology-paper/supplement.log" \
  "$output_dir/logs/ecology-supplement.log"
cp "$task_root/ecology-paper/supplement.blg" \
  "$output_dir/logs/ecology-supplement.blg"

data_supplement_listing_overflows=$(
  grep -cE 'Overfull \\hbox .*in paragraph at lines' \
    "$output_dir/logs/data-paper-supplement.log" || true
)
printf '%s\n' "$data_supplement_listing_overflows" \
  > "$output_dir/logs/data_supplement_listing_overflow_count.txt"
if [[ "$data_supplement_listing_overflows" -ne 0 ]]; then
  printf '%s\n' \
    "data supplement contains $data_supplement_listing_overflows paragraph/listing overfull box(es)" \
    >&2
  exit 1
fi

if grep -En 'Warning--|error' "$output_dir"/logs/*.blg
then
  printf '%s\n' "BibTeX warning or error detected" >&2
  exit 1
fi

{
  pdflatex --version | sed -n '1,2p'
  bibtex --version | sed -n '1,2p'
} > "$output_dir/logs/tex_tool_versions.txt"

runtime_container_path=${APPTAINER_CONTAINER:-${SINGULARITY_CONTAINER:-}}
if [[ -n ${APPTAINER_NAME:-} ]]; then
  detected_container="apptainer:${APPTAINER_NAME}"
elif [[ -n ${SINGULARITY_NAME:-} ]]; then
  detected_container="singularity:${SINGULARITY_NAME}"
elif [[ -d /.singularity.d ]]; then
  detected_container="singularity:detected"
elif [[ -f /.dockerenv ]]; then
  detected_container="docker:detected"
elif [[ -f /run/.containerenv ]]; then
  detected_container="oci:detected"
else
  detected_container="none-detected"
fi

if [[ -z "$tex_container" || "$tex_container" == null ]]; then
  tex_container_status=not-declared
  tex_container_sha256=
elif [[ "$tex_container" == *@sha256:* ]]; then
  tex_container_status=immutable-digest-reference
  tex_container_sha256=${tex_container##*@sha256:}
elif [[ -f "$tex_container" ]]; then
  tex_container_status=local-image-checksummed
  tex_container_sha256=$(sha256sum "$tex_container" | cut -d' ' -f1)
elif [[ -n "$runtime_container_path" && -f "$runtime_container_path" ]]; then
  tex_container_status=runtime-local-image-checksummed
  tex_container_sha256=$(
    sha256sum "$runtime_container_path" |
      cut -d' ' -f1
  )
else
  tex_container_status=mutable-or-unresolved-reference
  tex_container_sha256=
fi

{
  printf 'schema_version\tpaper-build-environment-v1\n'
  printf 'role\texecuted-paper-build-environment\n'
  printf 'generated_at_utc\t%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf 'execution_mode\t%s\n' "$execution_mode"
  printf 'tex_container_declared\t%s\n' "${tex_container:-NOT_DECLARED}"
  printf 'tex_container_identity_status\t%s\n' "$tex_container_status"
  printf 'tex_container_sha256\t%s\n' \
    "${tex_container_sha256:-NOT_AVAILABLE}"
  printf 'container_runtime_detected\t%s\n' "$detected_container"
  printf 'container_runtime_path\t%s\n' \
    "${runtime_container_path:-NOT_AVAILABLE}"
  printf 'hostname\t%s\n' "$(hostname)"
  printf 'kernel\t%s\n' "$(uname -srmo | tr '\t\r\n' '   ')"
  printf 'pdflatex_executable\t%s\n' "$(command -v pdflatex || true)"
  printf 'pdflatex_version\t%s\n' "$(
    pdflatex --version 2>&1 |
      head -1 |
      tr '\t\r\n' '   '
  )"
  printf 'bibtex_executable\t%s\n' "$(command -v bibtex || true)"
  printf 'bibtex_version\t%s\n' "$(
    bibtex --version 2>&1 |
      head -1 |
      tr '\t\r\n' '   '
  )"
  printf 'SOURCE_DATE_EPOCH\t%s\n' "$SOURCE_DATE_EPOCH"
  printf 'TZ\t%s\n' "$TZ"
  printf 'LC_ALL\t%s\n' "$LC_ALL"
  printf 'source_state_sha256\t%s\n' "$(
    sha256sum "$source_provenance/source_state.json" |
      cut -d' ' -f1
  )"
  printf 'analysis_environment_manifest_sha256\t%s\n' "$(
    sha256sum \
      "$execution_environment/execution_environment_manifest.json" |
      cut -d' ' -f1
  )"
  printf 'competency_query_validation_sha256\t%s\n' "$(
    sha256sum \
      "$competency_query/competency_query_validation.json" |
      cut -d' ' -f1
  )"
} > "$output_dir/logs/paper_environment.tsv"

cp "$source_provenance/source_state.json" \
  "$output_dir/logs/source_state.json"
cp "$source_provenance/snapshot_file_manifest.tsv" \
  "$output_dir/logs/snapshot_file_manifest.tsv"
cp "$execution_environment/execution_environment_manifest.json" \
  "$output_dir/logs/execution_environment_manifest.json"
cp "$execution_environment/environment.tsv" \
  "$output_dir/logs/analysis_environment.tsv"
cp "$execution_environment/tool_versions.tsv" \
  "$output_dir/logs/analysis_tool_versions.tsv"
cp "$competency_query/competency_query_validation.json" \
  "$output_dir/logs/competency_query_validation.json"
cp "$competency_query/field_xrf_site10_results.tsv" \
  "$output_dir/logs/field_xrf_site10_results.tsv"
cp "$competency_query/field_xrf_site10.rq" \
  "$output_dir/logs/field_xrf_site10.rq"
cp "$competency_query/SHA256SUMS" \
  "$output_dir/logs/competency_query_SHA256SUMS"
cp "$data_paper_figures/transect_altitude_profile.tsv" \
  "$output_dir/logs/transect_altitude_profile.tsv"
cp "$data_paper_figures/transect_altitude_summary.json" \
  "$output_dir/logs/transect_altitude_summary.json"
cp "$data_paper_figures/transect_altitude.png" \
  "$output_dir/logs/transect_altitude.png"
cp "$data_paper_figures/SHA256SUMS" \
  "$output_dir/logs/transect_altitude_SHA256SUMS"

(
  cd "$output_dir/logs"
  sha256sum -c competency_query_SHA256SUMS
  sha256sum -c transect_altitude_SHA256SUMS
)

(
  cd "$output_dir"
  sha256sum \
    logs/source_snapshot_build_verification.tsv \
    logs/source_state.json \
    logs/snapshot_file_manifest.tsv \
    logs/execution_environment_manifest.json \
    logs/analysis_environment.tsv \
    logs/analysis_tool_versions.tsv \
    logs/competency_query_validation.json \
    logs/field_xrf_site10_results.tsv \
    logs/field_xrf_site10.rq \
    logs/competency_query_SHA256SUMS \
    logs/transect_altitude_profile.tsv \
    logs/transect_altitude_summary.json \
    logs/transect_altitude.png \
    logs/transect_altitude_SHA256SUMS \
    logs/paper_environment.tsv \
    > PROVENANCE_SHA256SUMS
  sha256sum -c PROVENANCE_SHA256SUMS
)
