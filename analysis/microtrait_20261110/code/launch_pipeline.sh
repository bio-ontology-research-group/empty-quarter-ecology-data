#!/bin/bash
set -euo pipefail
ROOT="/scratch/project/k10018/eq-microtrait-20261110"
cd "$ROOT"
mkdir -p logs results provenance tmp

PY="python3"
if [ -x "/project/k10018/sw/envs/mapping/bin/python" ]; then
  PY="/project/k10018/sw/envs/mapping/bin/python"
fi

# Guard: query user queue once, fail closed if query fails, normalize array IDs, intersect with recorded IDs, refuse if any match
if [ -f provenance/root_jobs.json ]; then
  if ! QUEUE_OUTPUT=$(squeue -u "$USER" -h -o "%i"); then
    echo "ERROR: Failed to query Slurm queue (squeue -u \"\$USER\" -h -o \"%i\"); failing closed." >&2
    exit 1
  fi
  "$PY" - "$QUEUE_OUTPUT" "provenance/root_jobs.json" << 'EOF'
import json, sys

queue_output = sys.argv[1]
root_jobs_file = sys.argv[2]

active_ids = set()
for line in queue_output.splitlines():
    token = line.strip()
    if token:
        # Normalize array IDs by splitting at underscore (e.g. 15924726_0 -> 15924726)
        active_ids.add(token.split("_")[0])

try:
    with open(root_jobs_file, "r") as f:
        data = json.load(f)
except Exception as e:
    print(f"ERROR: Failed reading {root_jobs_file}: {e}", file=sys.stderr)
    sys.exit(1)

recorded_ids = set()
for k, v in data.items():
    if k.endswith("_job_id") and str(v).strip().isdigit():
        recorded_ids.add(str(v).strip())
    elif k == "superseded_jobs" and isinstance(v, list):
        for j in v:
            if str(j).strip().isdigit():
                recorded_ids.add(str(j).strip())

matches = active_ids.intersection(recorded_ids)
if matches:
    print(
        f"ERROR: Refusing launch: active job(s) from {root_jobs_file} currently in queue: "
        f"{', '.join(sorted(matches))}",
        file=sys.stderr,
    )
    sys.exit(1)
EOF
fi

record_root_job() {
  local key="$1"
  local val="$2"
  "$PY" - "$key" "$val" "$ROOT" << 'EOF'
import json, os, sys
from datetime import datetime, timezone
from pathlib import Path

key = sys.argv[1]
val = sys.argv[2]
root_dir = sys.argv[3]

prov_file = Path("provenance/root_jobs.json")
prov_file.parent.mkdir(parents=True, exist_ok=True)
data = {}
if prov_file.exists():
    try:
        with open(prov_file, "r") as f:
            data = json.load(f)
    except Exception:
        data = {}

data[key] = str(val).strip()
data["updated_at"] = datetime.now(timezone.utc).isoformat()
data.setdefault("submitter", os.environ.get("USER", "root"))
data.setdefault("remote_root", root_dir)
data.setdefault("local_root", "/home/leechuck/Documents/papers/empty-quarter/microtrait-20261110")
data.setdefault("stage2_array_spec", "0-33")

with open(prov_file, "w") as f:
    json.dump(data, f, indent=2)
    f.write("\n")
EOF
  echo "Recorded ${key}=${val} in provenance/root_jobs.json"
}

# 1. Stage 0a FASTA extraction
J_STAGE0A=$(sbatch --parsable code/sbatch_stage0a_extract.sh | cut -d';' -f1)
record_root_job "stage0a_extract_job_id" "$J_STAGE0A"

# 2. Stage 0b V14 DB prep
J_STAGE0B=$(sbatch --parsable code/sbatch_stage0b_db.sh | cut -d';' -f1)
record_root_job "stage0b_db_job_id" "$J_STAGE0B"

# 3. Stage 1 Smoke test after BOTH Stage 0a and Stage 0b
J_STAGE1=$(sbatch --parsable --dependency=afterok:${J_STAGE0A}:${J_STAGE0B} code/sbatch_stage1_smoke.sh | cut -d';' -f1)
record_root_job "stage1_smoke_job_id" "$J_STAGE1"

# 4. Stage 2 Array 0-33 after Stage 1 Smoke
J_STAGE2=$(sbatch --parsable --dependency=afterok:${J_STAGE1} --array=0-33 code/sbatch_stage2_array.sh | cut -d';' -f1)
record_root_job "stage2_production_array_job_id" "$J_STAGE2"

# 5. Stage 3 Aggregate after Stage 2 Array
J_STAGE3=$(sbatch --parsable --dependency=afterok:${J_STAGE2} code/sbatch_stage3_aggregate.sh | cut -d';' -f1)
record_root_job "stage3_aggregate_job_id" "$J_STAGE3"

TS=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
cat > provenance/slurm_jobs.json <<EOF
{
  "submitted_at": "${TS}",
  "account": "k10018",
  "partition": "workq",
  "stage0a_extract_job_id": "${J_STAGE0A}",
  "stage0b_db_job_id": "${J_STAGE0B}",
  "stage1_smoke_job_id": "${J_STAGE1}",
  "stage2_production_array_job_id": "${J_STAGE2}",
  "stage2_array_spec": "0-33 (34 nodes, 32 workers/node x 4 HMMER threads, ~160 MAGs/node)",
  "stage3_aggregate_job_id": "${J_STAGE3}",
  "dependency_chain": "stage0a (${J_STAGE0A}) + stage0b (${J_STAGE0B}) -> afterok:${J_STAGE0A}:${J_STAGE0B} smoke (${J_STAGE1}) -> afterok:${J_STAGE1} array[0-33] (${J_STAGE2}) -> afterok:${J_STAGE2} aggregate (${J_STAGE3})"
}
EOF

cat provenance/root_jobs.json
