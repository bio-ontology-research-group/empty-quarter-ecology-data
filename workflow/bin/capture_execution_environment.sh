#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 5 ]]; then
  echo "usage: $0 PROJECT_ROOT OUTPUT_DIR EXECUTION_MODE ANALYSIS_CONTAINER SOURCE_STATE" >&2
  exit 64
fi

project_root=$1
output_dir=$2
execution_mode=$3
analysis_container=$4
source_state=$5

mkdir -p "$output_dir"

if [[ ! -s "$source_state" ]]; then
  echo "source-state manifest is missing or empty: $source_state" >&2
  exit 66
fi

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

if [[ -z "$analysis_container" || "$analysis_container" == null ]]; then
  container_identity_status=not-declared
  container_sha256=
elif [[ "$analysis_container" == *@sha256:* ]]; then
  container_identity_status=immutable-digest-reference
  container_sha256=${analysis_container##*@sha256:}
elif [[ -f "$analysis_container" ]]; then
  container_identity_status=local-image-checksummed
  container_sha256=$(sha256sum "$analysis_container" | cut -d' ' -f1)
elif [[ -n "$runtime_container_path" && -f "$runtime_container_path" ]]; then
  container_identity_status=runtime-local-image-checksummed
  container_sha256=$(
    sha256sum "$runtime_container_path" |
      cut -d' ' -f1
  )
else
  container_identity_status=mutable-or-unresolved-reference
  container_sha256=
fi

one_line() {
  tr '\t\r\n' '   ' | sed -E 's/ +$//'
}

tool_record() {
  local name=$1
  local executable=
  local version=
  executable=$(command -v "$name" 2>/dev/null || true)
  if [[ -z "$executable" ]]; then
    printf '%s\tNOT_FOUND\tNOT_FOUND\n' "$name"
    return
  fi
  case "$name" in
    python3)
      version=$("$executable" --version 2>&1 | head -1 | one_line)
      ;;
    R|Rscript)
      version=$("$executable" --version 2>&1 | head -1 | one_line)
      ;;
    java)
      version=$("$executable" -version 2>&1 | head -1 | one_line)
      ;;
    groovy)
      version=$("$executable" --version 2>&1 | head -1 | one_line)
      ;;
    rapper)
      version=$("$executable" -v 2>&1 | head -1 | one_line)
      ;;
    mafft)
      version=$("$executable" --version 2>&1 | head -1 | one_line)
      ;;
    FastTree)
      version=$(
        { "$executable" 2>&1 </dev/null || true; } |
          head -1 |
          one_line
      )
      ;;
    pdflatex|bibtex|gcc|g++|make)
      version=$("$executable" --version 2>&1 | head -1 | one_line)
      ;;
    *)
      version=$("$executable" --version 2>&1 | head -1 | one_line)
      ;;
  esac
  printf '%s\t%s\t%s\n' "$name" "$executable" "$version"
}

{
  printf 'tool\texecutable\tversion\n'
  for tool in \
    python3 R Rscript java groovy rapper mafft FastTree gcc g++ make \
    pdflatex bibtex
  do
    tool_record "$tool"
  done
} > "$output_dir/tool_versions.tsv"

python_package_inventory_method=python-not-found
if command -v python3 >/dev/null 2>&1; then
  if python3 -m pip freeze --all \
    > "$output_dir/python_packages.unsorted.txt" 2>/dev/null
  then
    python_package_inventory_method=pip-freeze-all
  elif python3 - \
    > "$output_dir/python_packages.unsorted.txt" <<'PY'
from importlib.metadata import distributions

packages = []
for distribution in distributions():
    name = distribution.metadata.get("Name")
    if not name:
        raise RuntimeError(
            f"installed distribution lacks a Name field: {distribution!r}"
        )
    packages.append((name.casefold(), name, distribution.version))

for _, name, version in sorted(packages):
    print(f"{name}=={version}")
PY
  then
    python_package_inventory_method=importlib-metadata
  else
    echo "could not enumerate installed Python distributions" >&2
    exit 70
  fi
  LC_ALL=C sort "$output_dir/python_packages.unsorted.txt" \
    > "$output_dir/python_packages.txt"
  rm "$output_dir/python_packages.unsorted.txt"
else
  printf 'NOT_AVAILABLE: python3 not found\n' \
    > "$output_dir/python_packages.txt"
fi

python3 - > "$output_dir/figure_runtime.tsv" <<'PY'
import sys

import matplotlib
from matplotlib import ft2font

print("component\tversion")
print(f"python\t{sys.version.split()[0]}")
print(f"matplotlib\t{matplotlib.__version__}")
print(f"freetype\t{ft2font.__freetype_version__}")
PY

{
  printf 'schema_version\texecution-environment-v1\n'
  printf 'role\texecuted-analysis-task-environment\n'
  printf 'generated_at_utc\t%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf 'execution_mode\t%s\n' "$execution_mode"
  printf 'analysis_container_declared\t%s\n' \
    "${analysis_container:-NOT_DECLARED}"
  printf 'container_identity_status\t%s\n' "$container_identity_status"
  printf 'container_sha256\t%s\n' "${container_sha256:-NOT_AVAILABLE}"
  printf 'container_runtime_detected\t%s\n' "$detected_container"
  printf 'container_runtime_path\t%s\n' \
    "${runtime_container_path:-NOT_AVAILABLE}"
  printf 'hostname\t%s\n' "$(hostname)"
  printf 'kernel\t%s\n' "$(uname -srmo | one_line)"
  printf 'os_release\t%s\n' "$(
    if [[ -r /etc/os-release ]]; then
      sed -n \
        -e 's/^PRETTY_NAME=//p' \
        -e 's/^VERSION_ID=//p' \
        /etc/os-release |
        tr -d '"' |
        paste -sd ';' - |
        one_line
    else
      printf 'NOT_AVAILABLE'
    fi
  )"
  printf 'python_lock_sha256\t%s\n' "$(
    sha256sum "$project_root/workflow/requirements.lock.txt" |
      cut -d' ' -f1
  )"
  printf 'environment_yml_sha256\t%s\n' "$(
    sha256sum "$project_root/workflow/environment.yml" |
      cut -d' ' -f1
  )"
  printf 'conda_explicit_lock_sha256\t%s\n' "$(
    sha256sum "$project_root/workflow/conda-linux-64.lock" |
      cut -d' ' -f1
  )"
  printf 'pip_overlay_lock_sha256\t%s\n' "$(
    sha256sum "$project_root/workflow/pip-overlay.lock.txt" |
      cut -d' ' -f1
  )"
  printf 'python_package_inventory_method\t%s\n' \
    "$python_package_inventory_method"
  printf 'source_state_sha256\t%s\n' "$(
    sha256sum "$source_state" |
      cut -d' ' -f1
  )"
  for variable in \
    NXF_VER PYTHONHASHSEED OMP_NUM_THREADS OPENBLAS_NUM_THREADS \
    MKL_NUM_THREADS NUMEXPR_NUM_THREADS CONDA_PREFIX VIRTUAL_ENV \
    JAVA_HOME R_HOME
  do
    printf '%s\t%s\n' "$variable" "${!variable:-NOT_SET}"
  done
} > "$output_dir/environment.tsv"

if command -v Rscript >/dev/null 2>&1; then
  if ! Rscript --vanilla -e 'sessionInfo(); writeLines("--- installed packages ---"); ip <- installed.packages()[,c("Package","Version")]; write.table(ip[order(ip[,1]),], row.names=FALSE, sep="\t", quote=FALSE)' \
    > "$output_dir/r_session_info.txt" 2>&1
  then
    printf '\nCAPTURE_STATUS: Rscript returned non-zero\n' \
      >> "$output_dir/r_session_info.txt"
  fi
else
  printf 'NOT_AVAILABLE: Rscript not found\n' \
    > "$output_dir/r_session_info.txt"
fi

python3 - \
  "$output_dir" \
  "$execution_mode" \
  "$analysis_container" \
  "$container_identity_status" \
  "$detected_container" \
  "$source_state" \
  "$python_package_inventory_method" <<'PY'
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

output_dir = Path(sys.argv[1])


def evidence(path: Path) -> dict[str, object]:
    content = path.read_bytes()
    return {
        "file": path.name,
        "bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }


payload = {
    "schema_version": "execution-environment-v1",
    "status": "captured",
    "captured_at_utc": datetime.now(timezone.utc)
    .replace(microsecond=0)
    .isoformat()
    .replace("+00:00", "Z"),
    "execution_mode": sys.argv[2],
    "analysis_container_declared": sys.argv[3] or None,
    "container_identity_status": sys.argv[4],
    "container_runtime_detected": sys.argv[5],
    "source_state": evidence(Path(sys.argv[6])),
    "python_package_inventory_method": sys.argv[7],
    "artifacts": {
        name: evidence(output_dir / name)
        for name in (
            "environment.tsv",
            "figure_runtime.tsv",
            "tool_versions.tsv",
            "python_packages.txt",
            "r_session_info.txt",
        )
    },
    "interpretation": (
        "These versions were queried inside the environment that executed "
        "this Nextflow process. The explicit Conda lock, pip overlay, and "
        "environment.yml are declared build inputs; the queried inventory "
        "is the evidence for the versions that actually executed."
    ),
}
(output_dir / "execution_environment_manifest.json").write_text(
    json.dumps(payload, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
PY

(
  cd "$output_dir"
  find . -maxdepth 1 -type f ! -name SHA256SUMS -printf '%P\0' |
    sort -z |
    xargs -0 sha256sum > SHA256SUMS
  sha256sum -c SHA256SUMS
)
