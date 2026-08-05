#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 3 ]]; then
  echo "usage: $0 PROJECT_ROOT ECOLOGY_CORE_DIR OUTPUT_DIR" >&2
  exit 64
fi

project_root=$(readlink -f "$1")
ecology_core=$(readlink -f "$2")
output_dir_abs=$PWD/$3
task_root=$PWD/control-analysis-sandbox

mkdir -p \
  "$task_root/analysis/v2/review" \
  "$task_root/analysis/v3" \
  "$task_root/data/processed" \
  "$task_root/data/release" \
  "$output_dir_abs"

# The analysis scripts infer the project root from their own location.  Keep
# code and generated outputs inside the task sandbox, while presenting the
# immutable repository inputs through read-only symlinks.
cp -a "$project_root/scripts" "$task_root/scripts"
cp "$project_root"/scripts/analysis/*.py "$task_root/analysis/v3/"
ln -s "$ecology_core/cache" "$task_root/analysis/v2/review/cache"
ln -s "$project_root/data/metadata" "$task_root/data/metadata"
ln -s "$project_root/data/processed/taxonomy" \
  "$task_root/data/processed/taxonomy"
ln -s "$project_root/data/processed/climate" \
  "$task_root/data/processed/climate"
ln -s "$project_root/data/processed/geochemistry" \
  "$task_root/data/processed/geochemistry"
ln -s "$project_root/data/release/sample_ledger.tsv" \
  "$task_root/data/release/sample_ledger.tsv"

declare -A canonical_outputs=(
  [results]=claim_rescue
  [xrf_community_rescue]=xrf_community_rescue
  [spatial_turnover_rescue]=spatial_turnover_rescue
  [compartment_composition]=compartment_composition
  [depth_extraction]=depth_extraction
  [xrf_community_clr]=xrf_community_clr
  [geographic_prediction]=geographic_prediction
  [spatial_resolution_sensitivity]=spatial_resolution_sensitivity
  [distance_decay_turnover]=distance_decay_turnover
  [evenness_decomposition]=evenness_decomposition
)
for destination in "${!canonical_outputs[@]}"; do
  source_name=${canonical_outputs[$destination]}
  source_path=$ecology_core/$source_name
  if [[ ! -d "$source_path" ]]; then
    echo "ecology core omitted required control-comparison input: $source_name" >&2
    exit 66
  fi
  ln -s "$source_path" "$task_root/analysis/v3/$destination"
done

cd "$task_root"
python3 scripts/controls/run_assay_aware_control_audit.py \
  --profile-metadata analysis/v2/review/cache/alpha.tsv \
  --output-dir analysis/v3/control_audit
bash scripts/controls/run_control_ecology_sensitivity.sh \
  "$task_root" "$task_root/analysis/v3/control_sensitivity"

cp -a analysis/v3/control_audit "$output_dir_abs/control_audit"
cp -a analysis/v3/control_sensitivity "$output_dir_abs/control_sensitivity"

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
            "stage": "control_analysis",
            "status": "passed",
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
        "bytes": (out / "run_manifest.json").stat().st_size,
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
