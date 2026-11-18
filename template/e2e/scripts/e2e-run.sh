#!/bin/bash
# E2E Test Orchestration Script
# Manages the full E2E verification workflow: setup, test, cleanup, diagnostics

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
SETUP_SCRIPT="$SCRIPT_DIR/e2e-setup.sh"
DIAGNOSTICS_SCRIPT="$SCRIPT_DIR/collect-diagnostics.sh"
REPORTS_DIR="$PROJECT_ROOT/e2e/reports"

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Logging functions
log_info() {
    echo -e "${GREEN}✓${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}⚠${NC} $1"
}

log_error() {
    echo -e "${RED}✗${NC} $1"
}

# Main orchestration function
main() {
    echo "=========================================="
    echo "E2E Verification Suite"
    echo "=========================================="
    echo ""
    
    # Create reports directory
    mkdir -p "$REPORTS_DIR"
    
    # Step 1: Validate prerequisites
    echo "Step 1: Validating prerequisites..."
    if ! bash "$SETUP_SCRIPT" validate; then
        log_error "Prerequisites validation failed"
        exit 1
    fi
    echo ""
    
    # Step 2: Start Tilt cluster
    echo "Step 2: Starting Tilt cluster..."
    if ! bash "$SETUP_SCRIPT" start; then
        log_error "Failed to start Tilt"
        exit 1
    fi
    echo ""
    
    # Step 3: Run tests
    echo "Step 3: Running E2E tests..."
    cd "$PROJECT_ROOT" || exit 1
    
    # Set environment variables for localhost targets (from Tilt port-forwards)
    export FRONTEND_URL="http://localhost:3000"
    export BACKEND_URL="http://localhost:8000"
    export DB_HOST="localhost"
    export DB_NAME="${DB_NAME:-myapp}"
    export DB_USER="${DB_USER:-myapp}"
    export DB_PASSWORD="${DB_PASSWORD}"
    
    local test_failed=0
    if pytest e2e/tests/ -v --tb=short 2>&1 | tee "$REPORTS_DIR/test_output.log"; then
        log_info "All tests passed"
    else
        log_error "Some tests failed"
        test_failed=1
    fi
    echo ""
    
    # Step 4: Collect diagnostics if tests failed
    if [ $test_failed -eq 1 ]; then
        echo "Step 4: Collecting diagnostics..."
        if [ -f "$DIAGNOSTICS_SCRIPT" ]; then
            bash "$DIAGNOSTICS_SCRIPT" "$REPORTS_DIR/diagnostics.log" 2>/dev/null || true
            log_info "Diagnostics collected to $REPORTS_DIR/diagnostics.log"
        fi
        echo ""
    fi
    
    # Step 5: Stop Tilt cluster
    echo "Step 5: Stopping Tilt cluster..."
    if ! bash "$SETUP_SCRIPT" stop; then
        log_warn "Failed to stop Tilt (this is non-fatal)"
    fi
    echo ""
    
    # Step 6: Summary
    echo "=========================================="
    if [ $test_failed -eq 0 ]; then
        log_info "E2E verification completed successfully"
        echo "=========================================="
        exit 0
    else
        log_error "E2E verification failed"
        log_error "Test output saved to: $REPORTS_DIR/test_output.log"
        if [ -f "$REPORTS_DIR/diagnostics.log" ]; then
            log_error "Diagnostics saved to: $REPORTS_DIR/diagnostics.log"
        fi
        echo "=========================================="
        exit 1
    fi
}

main "$@"
