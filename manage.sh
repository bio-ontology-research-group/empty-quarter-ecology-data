#!/bin/bash
# manage.sh - Unified management script for the Empty Quarter Project
#
# This script consolidates functionality for infrastructure management,
# data regeneration, and deployment.
#
# Usage: ./manage.sh [command] [options]

set -e

# Configuration
PROJECT_ROOT=$(pwd)
WEBSITE_DIR="${PROJECT_ROOT}/website"
VIRTUOSO_DB_DIR="${PROJECT_ROOT}/virtuoso_db"
VIRTUOSO_CONTAINER="eq_virtuoso"
DATA_LOAD_SCRIPT="/docker-virtuoso-entrypoint-initdb.d/load_data.sql"

# ANSI Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Helper Functions
log() {
    echo -e "${BLUE}[EQ-MANAGE]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
    exit 1
}

success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

show_help() {
    echo "Usage: ./manage.sh [command]"
    echo ""
    echo "Commands:"
    echo "  start       Start the full infrastructure (Backend, Frontend, Virtuoso)"
    echo "  stop        Stop the infrastructure"
    echo "  restart     Restart the infrastructure"
    echo "  logs        Follow logs from all containers"
    echo "  update      Incremental data update (Groovy scripts -> Reload DB -> Validate)"
    echo "  reset       Full hard reset (Wipe DB -> Regen all data -> Clean Build -> Reload)"
    echo "  validate    Run the full validation suite"
    echo "  help        Show this help message"
    echo ""
}

# -----------------------------------------------------------------------------
# Core Logic Blocks
# -----------------------------------------------------------------------------

start_infra() {
    log "Starting infrastructure..."
    cd "$WEBSITE_DIR"
    docker-compose up -d --build
    cd "$PROJECT_ROOT"
    success "Services started. Frontend available at http://localhost:8080"
}

stop_infra() {
    log "Stopping infrastructure..."
    cd "$WEBSITE_DIR"
    docker-compose down
    cd "$PROJECT_ROOT"
    success "Infrastructure stopped."
}

generate_rdf() {
    log "Regenerating RDF/OWL Data (Groovy Pipelines)..."
    
    # Core Ontology
    groovy scripts/rdf/update_rubalkhali_ontology.groovy
    groovy scripts/rdf/generate_site_ontology.groovy
    
    # ABox Data
    groovy scripts/rdf/generate_samples_abox.groovy
    groovy scripts/rdf/generate_measurements_abox.groovy
    groovy scripts/rdf/generate_xrf_abox.groovy
    groovy scripts/rdf/generate_dna_abox.groovy
    groovy scripts/rdf/generate_sra_abox.groovy
    groovy scripts/rdf/generate_qc_abox.groovy
    
    success "RDF data generation complete."
}

reload_virtuoso() {
    log "Reloading data into Virtuoso..."
    
    # Check if container is running
    if ! docker ps | grep -q "$VIRTUOSO_CONTAINER"; then
        error "Virtuoso container ($VIRTUOSO_CONTAINER) is not running. Start infra first."
    fi

    docker exec "$VIRTUOSO_CONTAINER" isql-v 1111 dba dba "$DATA_LOAD_SCRIPT"
    success "Data reloaded successfully."
}

run_validation() {
    log "Running validation suite..."
    chmod +x scripts/validation/validate_all.sh
    ./scripts/validation/validate_all.sh
}

wipe_db() {
    warn "Wiping Virtuoso database files..."
    rm -f "${VIRTUOSO_DB_DIR}/virtuoso.db" \
          "${VIRTUOSO_DB_DIR}/virtuoso.trx" \
          "${VIRTUOSO_DB_DIR}/virtuoso.log" \
          "${VIRTUOSO_DB_DIR}/virtuoso.pxa" \
          "${VIRTUOSO_DB_DIR}/virtuoso-temp.db"
    success "Database files removed."
}

# -----------------------------------------------------------------------------
# Command Handlers
# -----------------------------------------------------------------------------

case "$1" in
    start)
        start_infra
        ;;
    
    stop)
        stop_infra
        ;;

    restart)
        stop_infra
        start_infra
        ;;

    logs)
        cd "$WEBSITE_DIR"
        docker-compose logs -f
        ;;

    update)
        # Incremental update: Gen Data -> Validation -> Reload
        log "Starting INCREMENTAL update..."
        generate_rdf
        run_validation
        reload_virtuoso
        success "Update complete."
        ;;

    reset)
        # Full reset: Stop -> Wipe -> Gen -> Start -> Reload
        log "Starting FULL HARD RESET..."
        
        stop_infra
        wipe_db
        generate_rdf
        start_infra
        
        log "Waiting 15s for Virtuoso to initialize..."
        sleep 15
        
        reload_virtuoso
        success "Full reset complete."
        ;;

    validate)
        run_validation
        ;;

    help|--help|-h)
        show_help
        ;;

    *)
        error "Unknown command: $1. Use './manage.sh help' for usage."
        ;;
esac
