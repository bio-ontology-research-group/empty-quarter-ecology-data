#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 4 ]]; then
  echo "usage: $0 PROJECT_ROOT ECOLOGY_CORE_DIR CONTROL_DIR OUTPUT_DIR" >&2
  exit 64
fi

project_root=$(readlink -f "$1")
ecology_core=$(readlink -f "$2")
control_results=$(readlink -f "$3")
output_dir_abs=$PWD/$4
task_root=$PWD/rain-pulse-sandbox

mkdir -p \
  "$task_root/analysis/v2/review" \
  "$task_root/analysis/v3/ph_shared_v1" \
  "$task_root/data/processed" \
  "$task_root/data/metadata" \
  "$output_dir_abs"

cp \
  "$project_root/analysis/v3/rain_response_window.py" \
  "$project_root/analysis/v3/rain_pulse_response.py" \
  "$project_root/analysis/v3/run_rain_pulse_suite.py" \
  "$task_root/analysis/v3/"
ln -s "$ecology_core/cache" "$task_root/analysis/v2/review/cache"
ln -s "$control_results/control_audit" \
  "$task_root/analysis/v3/control_audit"
mkdir -p "$task_root/analysis/v3/ph_shared_v1"
ln -s "$ecology_core/ph_shared_v1" \
  "$task_root/analysis/v3/ph_shared_v1/ecology"
ln -s "$project_root/data/processed/climate" \
  "$task_root/data/processed/climate"
ln -s "$project_root/data/metadata/geodata" \
  "$task_root/data/metadata/geodata"

cd "$task_root"
python3 analysis/v3/run_rain_pulse_suite.py \
  --root "$task_root" \
  --permutations 19999 \
  --bootstraps 9999

for directory in \
  rain_pulse_response \
  rain_pulse_response_open_meteo \
  rain_pulse_sensitivities
do
  cp -a "analysis/v3/$directory" "$output_dir_abs/$directory"
done

python3 - "$output_dir_abs" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

out = Path(sys.argv[1])
files = []
for path in sorted(item for item in out.rglob("*") if item.is_file()):
    if path.name in {"SHA256SUMS", "run_manifest.json"}:
        continue
    files.append(
        {
            "path": str(path.relative_to(out)),
            "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    )
(out / "run_manifest.json").write_text(
    json.dumps(
        {
            "stage": "rain_pulse_suite",
            "status": "passed",
            "permutations_per_run": 19999,
            "site_block_bootstraps_per_run": 9999,
            "files": files,
        },
        indent=2,
        sort_keys=True,
    )
    + "\n",
    encoding="utf-8",
)
checksummed = files + [
    {
        "path": "run_manifest.json",
        "sha256": hashlib.sha256(
            (out / "run_manifest.json").read_bytes()
        ).hexdigest(),
    }
]
(out / "SHA256SUMS").write_text(
    "".join(f"{row['sha256']}  {row['path']}\n" for row in checksummed),
    encoding="utf-8",
)
PY

(
  cd "$output_dir_abs"
  sha256sum -c SHA256SUMS
)
