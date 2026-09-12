#!/usr/bin/env bash
# Detached fresh RDF regeneration; never resumes old outputs or deploys them.
set -euo pipefail
job_root=${1:?explicit new job root required}
[[ "$job_root" == /mnt/data1/eq-release-build-20260912.* ]] || exit 64
predecessor=/mnt/data1/eq-release-build-20260910.oRKlE8
trap 'rc=$?; printf "%s\n" "$rc" > "$job_root/source_rebuild.exitcode"; date -u +%FT%TZ > "$job_root/finished_at"' EXIT
export CONDA_PREFIX="$predecessor/runtime" JAVA_HOME="$predecessor/runtime/lib/jvm"
export PATH="$predecessor/runtime/bin:/usr/bin:/bin"
export JAVA_OPTS="-Xms2g -Xmx32g"
export OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4 MKL_NUM_THREADS=4
date -u +%FT%TZ > "$job_root/started_at"
printf '%s\n' preparing_frozen_source > "$job_root/stage"
cp -a --reflink=auto "$predecessor/public_source" "$job_root/source"
cp -a "$job_root/overlay/." "$job_root/source/"
python3 "$job_root/prepare_successor_manifest.py" "$job_root/source"
printf '%s\n' rebuilding_all_rdf_modules > "$job_root/stage"
bash "$job_root/source/scripts/release/rebuild_public_sources.sh" "$job_root/source" "$job_root/rebuilt"
printf '%s\n' source_rebuild_verified_awaiting_fresh_database_load > "$job_root/stage"
printf '%s\n' 'All source modules regenerated and checked. Fresh database load, inference, exports, and deployment gates are still required.'
