#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 3 ]]; then
  echo "usage: $0 PROJECT_ROOT ECOLOGY_PAPER OUTPUT_DIR" >&2
  exit 64
fi

project_root=$1
ecology_paper=$2
output_dir=$3

mkdir -p "$output_dir"

python3 "$project_root/workflow/bin/capture_source_snapshot.py" \
  --project-root "$project_root" \
  --ecology-paper "$ecology_paper" \
  --output-dir "$output_dir"

# This describes only the host process that captured the immutable source
# archives. It is deliberately not labelled as the executed analysis
# environment; that is captured by CAPTURE_EXECUTION_ENVIRONMENT from inside
# the analysis task environment/container.
{
  printf 'role\tsource-snapshot-capture-host\n'
  printf 'generated_at_utc\t%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf 'hostname\t%s\n' "$(hostname)"
  printf 'kernel\t%s\n' "$(uname -srmo)"
  printf 'python_executable\t%s\n' "$(command -v python3 || true)"
  printf 'python\t%s\n' "$(python3 --version 2>&1 || true)"
} > "$output_dir/source_capture_host.tsv"

(
  cd "$output_dir"
  find . -maxdepth 1 -type f ! -name SHA256SUMS -printf '%P\0' |
    sort -z |
    xargs -0 sha256sum > SHA256SUMS
  sha256sum -c SHA256SUMS
)
