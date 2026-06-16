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

# 1. Synchronize Files
echo "Step 1: Synchronizing files to ${REMOTE_SERVER}..."
# Exclude genomics data, functional results, and local envs to save space/time
rsync -avz --progress \
    --exclude '.git' \
    --exclude 'node_modules' \
    --exclude '.venv' \
    --exclude 'data/processed/genomics' \
    --exclude 'data/processed/functional' \
    --exclude 'virtuoso_db/core.*' \
    ./ ${REMOTE_SERVER}:${REMOTE_DIR}/

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
    echo '  - Generating QC...' && \
    JAVA_OPTS='${JAVA_OPTS_16G}' groovy scripts/rdf/generate_qc_abox.groovy"

# Note: Taxonomy generation is extremely memory intensive. 
# It is skipped here to avoid OOM; sync the local TTL instead if changes occur.
# To run it: ssh onto 'cd /data/empty-quarter && JAVA_OPTS="-Xmx128g" groovy scripts/rdf/generate_taxonomy_abox.groovy'

# 3. Validation
echo "Step 3: Running remote validation suite..."
ssh ${REMOTE_SERVER} "cd ${REMOTE_DIR} && ./scripts/validation/validate_all.sh"

# 4. Restart Services
echo "Step 4: Rebuilding and Restarting Docker services..."
ssh ${REMOTE_SERVER} "cd ${REMOTE_DIR}/viz && \
    docker-compose build --no-cache web backend && \
    docker-compose up -d --force-recreate"

# 5. Reload Virtuoso
echo "Step 5: Reloading Virtuoso and Materializing Inference..."
echo "Waiting 60s for Virtuoso to initialize..."
sleep 60
ssh ${REMOTE_SERVER} "docker exec viz_virtuoso_1 isql-v 1111 dba dba /opt/virtuoso/load_data.sql"

echo "================================================="
echo "   DEPLOYMENT COMPLETE                           "
echo "   Web: https://rubalkhali.science/              "
echo "   Consensus: https://consensus.rubalkhali.science/"
echo "================================================="
