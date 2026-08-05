#!/bin/bash
# scripts/validate_original.sh - Validate the original (non-materialized) RDF modules

# ANSI Color Codes
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

LOG_FILE="validation_original_$(date +%Y%m%d_%H%M%S).log"
touch "$LOG_FILE"

log() {
    echo -e "$1"
    echo -e "$1" | sed 's/\x1b\[[0-9;]*m//g' >> "$LOG_FILE"
}

log "${BLUE}=================================================${NC}"
log "${BLUE}   ORIGINAL RDF DATA VALIDATION (PRE-INFERENCE)  ${NC}"
log "${BLUE}=================================================${NC}"
log "Start Time: $(date)"
log ""

OVERALL_STATUS=0

# 1. XRF Integrity
log "${YELLOW}Step 1: XRF Data Integrity...${NC}"
if groovy scripts/validation/verify_xrf_integrity.groovy >> "$LOG_FILE" 2>&1; then
    log "${GREEN}✅ PASSED: XRF Integrity${NC}"
else
    log "${RED}❌ FAILED: XRF Integrity${NC}"
    OVERALL_STATUS=1
fi

# 1b. Field and laboratory XRF provenance must remain semantically distinct.
log "${YELLOW}Step 1b: XRF Field/Laboratory Semantics...${NC}"
if groovy scripts/validation/validate_xrf_sample_types.groovy >> "$LOG_FILE" 2>&1; then
    log "${GREEN}✅ PASSED: XRF Field/Laboratory Semantics${NC}"
else
    log "${RED}❌ FAILED: XRF Field/Laboratory Semantics${NC}"
    OVERALL_STATUS=1
fi

# 2. Logical Consistency (ELK)
log "${YELLOW}Step 2: Logical Consistency (Original)...${NC}"
if groovy scripts/validation/validate_consistency.groovy >> "$LOG_FILE" 2>&1; then
    if grep -q "INCONSISTENT" "$LOG_FILE"; then
        log "${RED}❌ FAILED: Original data is INCONSISTENT${NC}"
        OVERALL_STATUS=1
    else
        log "${GREEN}✅ PASSED: Logical Consistency${NC}"
    fi
else
    log "${RED}❌ FAILED: Consistency check execution error${NC}"
    OVERALL_STATUS=1
fi

# 3. ShEx Validation
log "${YELLOW}Step 3: ShEx Validation (Original)...${NC}"
if groovy scripts/validation/validate_rdf.groovy >> "$LOG_FILE" 2>&1; then
    log "${GREEN}✅ PASSED: ShEx Validation${NC}"
else
    log "${RED}❌ FAILED: ShEx Validation${NC}"
    OVERALL_STATUS=1
fi

# 4. Label Uniqueness — every RAK_ entity must have exactly one rdfs:label
log "${YELLOW}Step 4: Label Uniqueness...${NC}"
if groovy scripts/validation/validate_labels.groovy >> "$LOG_FILE" 2>&1; then
    log "${GREEN}✅ PASSED: Label Uniqueness${NC}"
else
    log "${RED}❌ FAILED: Label Uniqueness — see ${LOG_FILE}${NC}"
    OVERALL_STATUS=1
fi

# 5. IRI Registry — no IRI declared/used inconsistently across generators
log "${YELLOW}Step 5: IRI Registry...${NC}"
if python3 scripts/validation/check_iri_registry.py >> "$LOG_FILE" 2>&1; then
    log "${GREEN}✅ PASSED: IRI Registry${NC}"
else
    log "${RED}❌ FAILED: IRI Registry — see ${LOG_FILE}${NC}"
    OVERALL_STATUS=1
fi

# 6. Control identity, provenance, process-stage and analysis invariants
log "${YELLOW}Step 6: Laboratory Control Validation...${NC}"
CONTROL_PY=".venv/bin/python"
if [ ! -x "$CONTROL_PY" ]; then
    CONTROL_PY="python3"
fi
if "$CONTROL_PY" scripts/validation/validate_controls.py >> "$LOG_FILE" 2>&1; then
    log "${GREEN}✅ PASSED: Laboratory Controls${NC}"
else
    log "${RED}❌ FAILED: Laboratory Controls — see ${LOG_FILE}${NC}"
    OVERALL_STATUS=1
fi

log ""
if [ $OVERALL_STATUS -eq 0 ]; then
    log "${GREEN}ALL ORIGINAL DATA VALIDATIONS PASSED. 🚀${NC}"
    exit 0
else
    log "${RED}SOME ORIGINAL DATA VALIDATIONS FAILED. ⚠️${NC}"
    exit 1
fi
