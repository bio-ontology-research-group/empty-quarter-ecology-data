#!/bin/bash
# deploy_onto.sh - Automated deployment script for Ontolinator (onto)
# Usage: ./deploy_onto.sh

set -e

REMOTE_SERVER="onto"
REMOTE_DIR="/data/empty-quarter"
JAVA_OPTS_64G="-Xmx64g"
JAVA_OPTS_16G="-Xmx16g"

echo "================================================="
echo "   DEPLOYING EMPTY QUARTER TO ONTOLINATOR        "
echo "================================================="

# 0. Rebuild media manifests locally so the synced public/ tree is current.
# These scripts read from data/media/*.parquet (built by the gallery
# pipeline — Tasks 1-7) and regenerate the JSONs the frontend imports.
# Skipped if the inventory parquet doesn't exist (clean repo, first deploy).
echo "Step 0: Rebuilding media manifests..."
if [ "${SKIP_MEDIA_REBUILD:-0}" = "1" ]; then
    echo "  - SKIP_MEDIA_REBUILD=1 — using existing media manifests/assets"
elif [ -f data/media/curation_v1.parquet ]; then
    uv run python scripts/utils/process_photos.py
    uv run python scripts/utils/build_featured.py
    uv run python scripts/utils/copy_audio_voices.py
    # videos.json + public/gallery/<trip>/<site>/videos/ get refreshed
    # by process_videos.py if the encoded clips already exist locally.
    uv run python scripts/utils/process_videos.py --commit || true
    # Step 0b: re-apply BLIP image/video captions. process_videos.py and
    # the curation scripts above can overwrite videos.json (and would
    # strip its `caption` fields); photo_metadata.json is untouched here
    # but the merge is idempotent, so re-running keeps everything in sync.
    # Source-of-truth captions live in scripts/curation/captions_v1.json.
    if [ -f scripts/curation/captions_v1.json ]; then
        uv run python scripts/curation/merge_captions.py \
            --captions scripts/curation/captions_v1.json
    fi
else
    echo "  - No data/media/curation_v1.parquet — skipping media rebuild"
fi

# 1. Synchronize Files
echo "Step 1: Synchronizing files to ${REMOTE_SERVER}..."
# Exclude genomics data, functional results, and local envs to save space/time.
# Also exclude `pictures/` (raw + curated source media — the website only
# needs the derived public/gallery/ thumbnails) and `data/media/` (parquet
# inventories — local pipeline state, not needed on remote).
rsync -avz --progress \
    --exclude '.git' \
    --exclude 'node_modules' \
    --exclude '.venv' \
    --exclude '.pytest_cache' \
    --exclude '.ruff_cache' \
    --exclude '.mypy_cache' \
    --exclude 'data/processed/genomics' \
    --exclude 'data/processed/functional' \
    --exclude 'virtuoso_db' \
    --exclude 'data-paper' \
    --exclude 'ecology-paper' \
    --exclude 'analysis/v2' \
    --exclude 'related-manuscripts' \
    --exclude 'slides/literature' \
    --exclude '__pycache__' \
    --exclude '.claude' \
    --exclude 'pictures' \
    --exclude 'data/media' \
    --exclude 'website/frontend/dist' \
    --exclude 'tasks' \
    --exclude 'scripts/validation/.shex_classpath' \
    ./ ${REMOTE_SERVER}:${REMOTE_DIR}/

# The placeholder "Interview 001" clip was removed from the Voices UI, but
# rsync intentionally does not use --delete for the full tree. Remove stale
# public copies explicitly so the file is not left addressable after deploy.
ssh ${REMOTE_SERVER} "rm -f \
    '${REMOTE_DIR}/website/frontend/public/audio/Interview 001.m4a' \
    '${REMOTE_DIR}/website/frontend/public/audio/Interview 001.srt'"

# 2. Rebuild Data on Remote
echo "Step 2: Rebuilding RDF data on ${REMOTE_SERVER}..."
ssh ${REMOTE_SERVER} "cd ${REMOTE_DIR} && \
    echo '  - Updating Ontology...' && \
    groovy scripts/rdf/update_rubalkhali_ontology.groovy && \
    echo '  - Generating Sites...' && \
    groovy scripts/rdf/generate_site_ontology.groovy && \
    echo '  - Generating Samples...' && \
    groovy scripts/rdf/generate_samples_abox.groovy && \
    echo '  - Generating Measurements...' && \
    groovy scripts/rdf/generate_measurements_abox.groovy && \
    echo '  - Generating XRF (with normalization)...' && \
    groovy scripts/rdf/generate_xrf_abox.groovy && \
    echo '  - Generating DNA & SRA...' && \
    groovy scripts/rdf/generate_dna_abox.groovy && \
    groovy scripts/rdf/generate_sra_abox.groovy && \
    echo '  - Generating laboratory controls...' && \
    python3 scripts/rdf/generate_controls_abox.py && \
    echo '  - Generating QC...' && \
    JAVA_OPTS='${JAVA_OPTS_16G}' groovy scripts/rdf/generate_qc_abox.groovy"

# Note: Taxonomy generation is extremely memory intensive.
# It is skipped here to avoid OOM; sync the local TTL instead if changes occur.
# To run it: ssh onto 'cd /data/empty-quarter && JAVA_OPTS="-Xmx128g" groovy scripts/rdf/generate_taxonomy_abox.groovy'

# 2b. Pre-compute alpha + beta diversity from the trips 1-5 abundance table.
# Output is dropped at website/frontend/public/diversity.json so the next
# `docker compose build frontend` bakes it into the served static assets
# (consumed by the Compare → Diversity tab via /diversity.json fetch).
echo "Step 2b: Computing alpha/beta diversity..."
ssh ${REMOTE_SERVER} "cd ${REMOTE_DIR} && \
    python3 scripts/diversity/compute_diversity.py && \
    cp data/processed/taxonomy/diversity.json website/frontend/public/diversity.json"

# 3. Pre-restart validation
echo "Step 3: Running pre-restart validation suite..."
ssh ${REMOTE_SERVER} "cd ${REMOTE_DIR} && VALIDATE_LIVE=0 ./scripts/validation/validate_all.sh"

# 4. Restart Services
echo "Step 4: Rebuilding and Restarting Docker services..."
ssh ${REMOTE_SERVER} "cd ${REMOTE_DIR}/viz && \
    docker-compose build --no-cache web backend && \
    docker-compose up -d --force-recreate"

# 5. Reload Virtuoso
echo "Step 5: Reloading Virtuoso and Materializing Inference..."
echo "Waiting 60s for Virtuoso to initialize..."
sleep 60
ssh ${REMOTE_SERVER} "VC=\$(docker ps --filter 'ancestor=tenforce/virtuoso:latest' --format '{{.Names}}' | head -1) && \
    test -n \"\$VC\" && \
    docker exec \"\$VC\" isql-v 1111 dba dba /opt/virtuoso/load_data.sql"

# 5b. Live KG validation after Virtuoso has been recreated and loaded.
echo "Step 5b: Running live KG validation..."
ssh ${REMOTE_SERVER} "cd ${REMOTE_DIR} && ./scripts/validation/validate_materialized.sh"

# 6. Post-deploy smoke tests against the live URL.
# Catches the silent-empty failure mode (200 OK + data:[]) and any per-site
# 500. Exits non-zero on failure so the deploy script aborts loudly.
# History: Without this, a 2026-05-10 deploy left both /data/xrf and
# /data/taxonomy returning 0 rows for ~2 hours before the user noticed
# from the UI ("No taxonomy data available").
echo "Step 6: Running post-deploy smoke tests against https://rubalkhali.science/ ..."
./scripts/deploy_smoke.sh https://rubalkhali.science

echo "================================================="
echo "   DEPLOYMENT COMPLETE                           "
echo "   Web: https://rubalkhali.science/              "
echo "   Consensus: https://consensus.rubalkhali.science/"
echo "================================================="
