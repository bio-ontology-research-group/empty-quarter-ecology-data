#!/bin/bash
# scripts/validate_materialized.sh — Post-inference / live-KG validation
#
# Two modes:
#   LITE (default; deployment gate, ~minutes):
#     - Step 3: SPARQL competency queries against live Virtuoso
#     - Step 4: Taxonomy abundance reconstruction
#     Skips Step 1 (ELK on multi-GB materialized graph) and Step 2 (ShEx
#     against materialized) because both restate guarantees already proved
#     by the pre-inference original-data validation, and ELK on the full
#     materialized closure runs for hours.
#
#   FULL (FULL=1):
#     - Refresh data/processed/ontology/rubalkhali_materialized.ttl from
#       Virtuoso so we validate what's actually loaded.
#     - All four steps.
#
# The deployment gate uses LITE.

set -e

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Generous heap for the large-graph case in FULL mode; ignored otherwise.
export JAVA_OPTS="${JAVA_OPTS:--Xmx80g}"

LOG_FILE="validation_materialized_$(date +%Y%m%d_%H%M%S).log"
touch "$LOG_FILE"

log() {
    echo -e "$1"
    echo -e "$1" | sed 's/\x1b\[[0-9;]*m//g' >> "$LOG_FILE"
}

IS_FULL="${FULL:-0}"
MATERIALIZED_FILE="data/processed/ontology/rubalkhali_materialized.ttl"

log "${BLUE}=================================================${NC}"
log "${BLUE}   POST-INFERENCE / LIVE-KG VALIDATION           ${NC}"
log "${BLUE}=================================================${NC}"
log "Mode:       $([ "$IS_FULL" = "1" ] && echo 'FULL (deep)' || echo 'LITE (deployment gate)')"
log "Start Time: $(date)"
log ""

OVERALL_STATUS=0

if [ "$IS_FULL" = "1" ]; then
    log "${YELLOW}[FULL] Refreshing materialized graph from Virtuoso...${NC}"
    if [ -x scripts/utils/dump_virtuoso.sh ]; then
        if ./scripts/utils/dump_virtuoso.sh >> "$LOG_FILE" 2>&1; then
            log "${GREEN}  ✅ Refresh complete.${NC}"
        else
            log "${RED}  ❌ Refresh failed — aborting FULL mode.${NC}"
            exit 1
        fi
    else
        log "${RED}  ⚠️  dump_virtuoso.sh not executable; using existing materialized file.${NC}"
    fi
    log ""

    if [ ! -s "$MATERIALIZED_FILE" ]; then
        log "${RED}❌ ERROR: Materialized file not found or empty.${NC}"
        exit 1
    fi

    log "${YELLOW}Step 1: Logical Consistency (Materialized, FULL)...${NC}"
    if groovy scripts/validation/validate_consistency.groovy "$MATERIALIZED_FILE" >> "$LOG_FILE" 2>&1; then
        log "${GREEN}✅ PASSED: Logical Consistency${NC}"
    else
        log "${RED}❌ FAILED: Materialized data is INCONSISTENT${NC}"
        OVERALL_STATUS=1
    fi

    log "${YELLOW}Step 2: ShEx Validation (Materialized, FULL)...${NC}"
    if groovy scripts/validation/validate_rdf.groovy "$MATERIALIZED_FILE" >> "$LOG_FILE" 2>&1; then
        log "${GREEN}✅ PASSED: ShEx Validation${NC}"
    else
        log "${RED}❌ FAILED: ShEx Validation${NC}"
        OVERALL_STATUS=1
    fi
else
    log "${BLUE}(LITE mode — skipping Step 1 ELK / Step 2 ShEx on the multi-GB${NC}"
    log "${BLUE} materialized graph; these are covered by the original-data pass.)${NC}"
    log ""
fi

# ---- Steps that always run, in both LITE and FULL ----

log "${YELLOW}Step 3: End-to-End SPARQL Validation (Virtuoso)...${NC}"
VIRTUOSO_CONTAINER="$(docker ps \
    --filter 'ancestor=tenforce/virtuoso:latest' \
    --format '{{.Names}}' | head -1)"
if [ -z "$VIRTUOSO_CONTAINER" ]; then
    log "${RED}❌ FAILED: Virtuoso container is not running.${NC}"
    OVERALL_STATUS=1
else
    if groovy scripts/validation/test_virtuoso_sparql.groovy >> "$LOG_FILE" 2>&1; then
        if grep -q "FAIL:" "$LOG_FILE"; then
            log "${RED}❌ FAILED: SPARQL Validation (failures detected)${NC}"
            OVERALL_STATUS=1
        else
            log "${GREEN}✅ PASSED: SPARQL Validation${NC}"
        fi
    else
        log "${RED}❌ FAILED: SPARQL Validation (execution error)${NC}"
        OVERALL_STATUS=1
    fi
fi

log "${YELLOW}Step 4: Taxonomy Reconstruction (Abundance Check)...${NC}"
TAX_LOG="${LOG_FILE}.tax_step"
if groovy scripts/validation/validate_taxonomy_abundance.groovy > "$TAX_LOG" 2>&1; then
    cat "$TAX_LOG" >> "$LOG_FILE"
    if grep -q "❌" "$TAX_LOG"; then
        log "${RED}❌ FAILED: Taxonomy Reconstruction (mismatch detected)${NC}"
        OVERALL_STATUS=1
    else
        log "${GREEN}✅ PASSED: Taxonomy Reconstruction${NC}"
    fi
    rm -f "$TAX_LOG"
else
    cat "$TAX_LOG" >> "$LOG_FILE"
    log "${RED}❌ FAILED: Taxonomy Reconstruction (execution error)${NC}"
    rm -f "$TAX_LOG"
    OVERALL_STATUS=1
fi

log ""
if [ $OVERALL_STATUS -eq 0 ]; then
    log "${GREEN}ALL POST-INFERENCE VALIDATIONS PASSED. 🚀${NC}"
    exit 0
else
    log "${RED}SOME POST-INFERENCE VALIDATIONS FAILED. ⚠️${NC}"
    exit 1
fi
