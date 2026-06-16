#!/bin/bash
# scripts/validate_materialized.sh - Validate the fully materialized RDF data

# ANSI Color Codes
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Increase JVM memory for large RDF validation
export JAVA_OPTS="-Xmx80g"

LOG_FILE="validation_materialized_$(date +%Y%m%d_%H%M%S).log"
touch "$LOG_FILE"

log() {
    echo -e "$1"
    echo -e "$1" | sed 's/\x1b\[[0-9;]*m//g' >> "$LOG_FILE"
}

MATERIALIZED_FILE="data/processed/ontology/rubalkhali_materialized.ttl"

log "${BLUE}=================================================${NC}"
log "${BLUE}   MATERIALIZED RDF DATA VALIDATION (POST-INF)   ${NC}"
log "${BLUE}=================================================${NC}"
log "Start Time: $(date)"
log "Target:     $MATERIALIZED_FILE"
log ""

if [ ! -s "$MATERIALIZED_FILE" ]; then
    log "${RED}❌ ERROR: Materialized file not found or empty.${NC}"
    log "  Please run scripts/utils/dump_virtuoso.sh first."
    exit 1
fi

OVERALL_STATUS=0

# 1. Logical Consistency (ELK)
log "${YELLOW}Step 1: Logical Consistency (Materialized)...${NC}"
if groovy scripts/validation/validate_consistency.groovy "$MATERIALIZED_FILE" >> "$LOG_FILE" 2>&1; then
    log "${GREEN}✅ PASSED: Logical Consistency${NC}"
else
    log "${RED}❌ FAILED: Materialized data is INCONSISTENT${NC}"
    OVERALL_STATUS=1
fi

# 2. ShEx Validation
log "${YELLOW}Step 2: ShEx Validation (Materialized)...${NC}"
if groovy scripts/validation/validate_rdf.groovy "$MATERIALIZED_FILE" >> "$LOG_FILE" 2>&1; then
    log "${GREEN}✅ PASSED: ShEx Validation${NC}"
else
    log "${RED}❌ FAILED: ShEx Validation${NC}"
    OVERALL_STATUS=1
fi

# 3. End-to-End SPARQL Validation (Virtuoso)
log "${YELLOW}Step 3: End-to-End SPARQL Validation (Virtuoso)...${NC}"
if ! docker ps | grep -q "eq_virtuoso"; then
    log "${RED}❌ FAILED: Virtuoso container is not running.${NC}"
    OVERALL_STATUS=1
else
    if groovy scripts/validation/test_virtuoso_sparql.groovy >> "$LOG_FILE" 2>&1; then
         if grep -q "FAIL:" "$LOG_FILE"; then
             log "${RED}❌ FAILED: SPARQL Validation (Failures detected)${NC}"
             OVERALL_STATUS=1
         else
             log "${GREEN}✅ PASSED: SPARQL Validation${NC}"
         fi
    else
        log "${RED}❌ FAILED: SPARQL Validation (Execution Error)${NC}"
        OVERALL_STATUS=1
    fi
fi

# 4. Taxonomy Reconstruction
log "${YELLOW}Step 4: Taxonomy Reconstruction (Abundance Check)...${NC}"
if groovy scripts/validation/validate_taxonomy_abundance.groovy >> "$LOG_FILE" 2>&1; then
    if grep -q "❌" "$LOG_FILE"; then
         log "${RED}❌ FAILED: Taxonomy Reconstruction (Mismatch detected)${NC}"
         OVERALL_STATUS=1
    else
         log "${GREEN}✅ PASSED: Taxonomy Reconstruction${NC}"
    fi
else
    log "${RED}❌ FAILED: Taxonomy Reconstruction (Execution Error)${NC}"
    OVERALL_STATUS=1
fi

log ""
if [ $OVERALL_STATUS -eq 0 ]; then
    log "${GREEN}ALL MATERIALIZED DATA VALIDATIONS PASSED. 🚀${NC}"
    exit 0
else
    log "${RED}SOME MATERIALIZED DATA VALIDATIONS FAILED. ⚠️${NC}"
    exit 1
fi
