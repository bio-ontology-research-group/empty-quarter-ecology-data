#!/bin/bash
# scripts/validate_all.sh - Full Validation Suite (Original & Materialized)

# ANSI Color Codes
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

echo "================================================="
echo "   RUNNING FULL VALIDATION SUITE                 "
echo "================================================="

# 3. ShEx Validation
chmod +x scripts/validation/validate_original.sh
if ./scripts/validation/validate_original.sh; then
    echo -e "${GREEN}>>> Original Data Validation: SUCCESS${NC}"
else
    echo -e "${RED}>>> Original Data Validation: FAILED${NC}"
    exit 1
fi

echo ""

# 4. Taxonomy Completeness
echo "Checking Taxonomy Completeness..."
if [ ! -f "data/taxonomy/unique_taxa.txt" ]; then
    echo "Generating unique_taxa.txt..."
    cut -f2 data/processed/taxon-tables/taxonomy.tsv | sort | uniq > data/taxonomy/unique_taxa.txt
fi

if groovy scripts/validation/VerifyTaxonomyCompleteness.groovy; then
    echo -e "${GREEN}>>> Taxonomy Completeness: SUCCESS${NC}"
else
    echo -e "${RED}>>> Taxonomy Completeness: FAILED${NC}"
    exit 1
fi

echo ""

# 2. Ensure Materialized file exists (if not, dump it)
if [ ! -s "data/processed/ontology/rubalkhali_materialized.ttl" ]; then
    echo "Materialized file not found. Generating..."
    ./scripts/utils/dump_virtuoso.sh
fi

# 3. Validate Materialized
chmod +x scripts/validation/validate_materialized.sh
if ./scripts/validation/validate_materialized.sh; then
    echo -e "${GREEN}>>> Materialized Data Validation: SUCCESS${NC}"
else
    echo -e "${RED}>>> Materialized Data Validation: FAILED${NC}"
    exit 1
fi

echo ""
echo -e "${GREEN}ALL VALIDATIONS PASSED SUCCESSFULLY.${NC}"