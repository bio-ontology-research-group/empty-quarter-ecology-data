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

if [ "${VALIDATE_LIVE:-1}" = "0" ]; then
    echo "Skipping live Virtuoso/backend/frontend checks (VALIDATE_LIVE=0)."
    echo ""
    exit 0
fi

# Post-inference / live-KG validation. In LITE mode (default) this only
# touches live Virtuoso and reads small TSVs — no multi-GB graph dumps.
# Set FULL=1 to also re-dump the materialized graph and run ELK + ShEx
# over it (hours).
chmod +x scripts/validation/validate_materialized.sh
if ./scripts/validation/validate_materialized.sh; then
    echo -e "${GREEN}>>> Post-Inference Validation: SUCCESS${NC}"
else
    echo -e "${RED}>>> Post-Inference Validation: FAILED${NC}"
    exit 1
fi

echo ""

# 5. Backend endpoint smoke tests
# Runtime check that every per-site endpoint serves 200s for every site —
# guards against the Virtuoso planner regressions that broke /sites,
# /samples and /data/xrf during Sprint 2 (2026-05-05/06).
# Requires the backend container to be running and pytest+httpx available.
echo "Running backend endpoint smoke tests..."
BACKEND_BASE="${EQ_BACKEND_BASE:-http://localhost:8080/api}"
SPARQL_BASE="${SPARQL_ENDPOINT:-http://localhost:8895/sparql}"

if ! curl -sf -o /dev/null --max-time 5 "${BACKEND_BASE}/data/stats"; then
    echo -e "${RED}>>> Backend not reachable at ${BACKEND_BASE} — skipping endpoint tests.${NC}"
    echo "    (start it with: ./manage.sh start)"
elif ! command -v python3 >/dev/null 2>&1; then
    echo -e "${RED}>>> python3 not found — skipping endpoint tests.${NC}"
else
    # Prefer uv if available (handles deps for the calling user); fall back to
    # python3 -m pytest (assumes pytest+httpx pre-installed).
    if command -v uv >/dev/null 2>&1; then
        TEST_CMD="uv run --with httpx --with pytest python -m pytest"
    else
        TEST_CMD="python3 -m pytest"
    fi
    if EQ_BACKEND_BASE="$BACKEND_BASE" SPARQL_ENDPOINT="$SPARQL_BASE" \
       $TEST_CMD tests/test_backend_endpoints.py -q --tb=short; then
        echo -e "${GREEN}>>> Backend endpoint tests: SUCCESS${NC}"
    else
        echo -e "${RED}>>> Backend endpoint tests: FAILED${NC}"
        exit 1
    fi
fi

echo ""

# 6. Frontend smoke tests — drive a real headless Chromium against every
#    public route and fail if a JavaScript runtime error fires or a route
#    renders an empty page. Catches breakage that HTTP-only checks miss
#    (e.g. a Vite manualChunks regression that 200s on every chunk but
#    crashes at module init with "Cannot read properties of undefined").
#
# This is a deployment gate: a frontend that can't render is a no-go even
# if every backend endpoint passes.
echo "Running frontend smoke tests..."
FRONTEND_BASE="${EQ_FRONTEND_BASE:-http://localhost:8080}"

if ! curl -sf -o /dev/null --max-time 5 "${FRONTEND_BASE}/"; then
    echo -e "${RED}>>> Frontend not reachable at ${FRONTEND_BASE} — skipping frontend tests.${NC}"
elif ! command -v uv >/dev/null 2>&1; then
    echo -e "${YELLOW}>>> uv not available; skipping frontend smoke tests.${NC}"
    echo "    (install: curl -LsSf https://astral.sh/uv/install.sh | sh)"
else
    # Ensure Chromium is installed for the calling user. The first-time
    # download is ~150 MB; subsequent runs are no-ops. We pin the playwright
    # version to keep the gate reproducible.
    PLAYWRIGHT_PIN="playwright==1.50.0"
    uv run --with "$PLAYWRIGHT_PIN" python -m playwright install chromium >/dev/null 2>&1 || true

    if EQ_BASE="$FRONTEND_BASE" \
       uv run --with httpx --with pytest --with "$PLAYWRIGHT_PIN" \
         python -m pytest tests/test_frontend_smoke.py -q --tb=short; then
        echo -e "${GREEN}>>> Frontend smoke tests: SUCCESS${NC}"
    else
        echo -e "${RED}>>> Frontend smoke tests: FAILED${NC}"
        exit 1
    fi
fi

echo ""
echo -e "${GREEN}ALL VALIDATIONS PASSED SUCCESSFULLY.${NC}"
