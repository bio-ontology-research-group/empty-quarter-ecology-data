#!/usr/bin/env bash
set -euo pipefail

workflow_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
project_root=$(cd "$workflow_dir/.." && pwd)
cache_dir=${NXF_BOOTSTRAP_DIR:-"$workflow_dir/.nextflow-bin"}
nextflow_version=${NXF_VER:-25.10.4}
launcher="$cache_dir/nextflow"

# The bare development profile deliberately does not use a container.  When
# the documented locked environment exists, make it the default interpreter
# for every Nextflow task without requiring an interactive activation step.
if [[ -x "$project_root/.venv/bin/python3" ]]; then
  export PATH="$project_root/.venv/bin:$PATH"
fi

if [[ ${NXF_BOOTSTRAP_USE_SYSTEM:-0} == 1 ]]; then
  launcher=$(command -v nextflow)
else
  mkdir -p "$cache_dir"
  if [[ ! -x "$launcher" ]]; then
    tmp_dir=$(mktemp -d)
    trap 'rm -rf "$tmp_dir"' EXIT
    (
      cd "$tmp_dir"
      curl -fsSL https://get.nextflow.io | bash
    )
    mv "$tmp_dir/nextflow" "$launcher"
    chmod 0755 "$launcher"
  fi
fi

export NXF_VER="$nextflow_version"

# Record the actual invocation before Nextflow starts. Release commands should
# always pass a unique --outdir; the project default is used only when omitted.
outdir="$project_root/results/reproducibility"
profile=NOT_EXPLICITLY_SET
arguments=("$@")
for ((index = 0; index < ${#arguments[@]}; index++)); do
  case "${arguments[$index]}" in
    --outdir)
      if ((index + 1 < ${#arguments[@]})); then
        outdir=${arguments[$((index + 1))]}
      fi
      ;;
    --outdir=*)
      outdir=${arguments[$index]#--outdir=}
      ;;
    -profile)
      if ((index + 1 < ${#arguments[@]})); then
        profile=${arguments[$((index + 1))]}
      fi
      ;;
    -profile=*)
      profile=${arguments[$index]#-profile=}
      ;;
  esac
done
case "$outdir" in
  /*) ;;
  *) outdir="$PWD/$outdir" ;;
esac
mkdir -p "$outdir/pipeline_info"
{
  printf '%q ' "$launcher" "$@"
  printf '\n'
} > "$outdir/pipeline_info/launch_command.txt"
{
  printf 'recorded_at_utc\t%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf 'working_directory\t%s\n' "$PWD"
  printf 'profile_argument\t%s\n' "$profile"
  printf 'nextflow_launcher\t%s\n' "$launcher"
  printf 'NXF_VER\t%s\n' "$NXF_VER"
  for variable in \
    PYTHONHASHSEED OMP_NUM_THREADS OPENBLAS_NUM_THREADS MKL_NUM_THREADS \
    NUMEXPR_NUM_THREADS JAVA_HOME NXF_BOOTSTRAP_USE_SYSTEM
  do
    printf '%s\t%s\n' "$variable" "${!variable:-NOT_SET}"
  done
} > "$outdir/pipeline_info/launch_environment.tsv"

exec "$launcher" "$@"
