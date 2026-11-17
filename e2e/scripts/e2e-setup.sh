#!/bin/bash
# E2E Setup and Validation Script
# Validates prerequisites and manages Tilt cluster lifecycle

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
CONFIG_DIR="$PROJECT_ROOT/e2e/config"

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

# Check if command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Check command version
check_version() {
    local cmd=$1
    local min_version=$2
    
    if ! command_exists "$cmd"; then
        return 1
    fi
    
    local version=$($cmd --version 2>&1 | head -1)
    return 0
}

# Validate prerequisites
validate_prerequisites() {
    echo "Validating E2E prerequisites..."
    echo ""
    
    local missing_tools=0
    
    # Check Docker
    if command_exists docker; then
        local docker_version=$(docker --version | awk '{print $3}' | sed 's/,//')
        log_info "Docker: $docker_version"
    else
        log_error "Docker not found. Please install Docker."
        ((missing_tools++))
    fi
    
    # Check kubectl
    if command_exists kubectl; then
        local kubectl_version=$(kubectl version --client -o json 2>/dev/null | grep -o '"gitVersion":"[^"]*"' | cut -d'"' -f4 || echo "unknown")
        log_info "kubectl: $kubectl_version"
    else
        log_error "kubectl not found. Please install kubectl."
        ((missing_tools++))
    fi
    
    # Check Tilt
    if command_exists tilt; then
        local tilt_version=$(tilt version 2>/dev/null | head -1 || echo "unknown")
        log_info "Tilt: $tilt_version"
    else
        log_error "Tilt not found. Please install Tilt."
        ((missing_tools++))
    fi
    
    # Check Python
    if command_exists python3; then
        local python_version=$(python3 --version 2>&1 | awk '{print $2}')
        log_info "Python 3: $python_version"
    else
        log_error "Python 3 not found. Please install Python 3.8+."
        ((missing_tools++))
    fi
    
    echo ""
    if [ $missing_tools -gt 0 ]; then
        log_error "Missing $missing_tools required tool(s). Please install them and try again."
        return 1
    fi
    
    log_info "All prerequisites validated."
    return 0
}

# Start Tilt
start_tilt() {
    echo ""
    echo "Starting Tilt cluster..."
    
    if check_tilt_running; then
        log_warn "Tilt is already running"
        return 0
    fi
    
    cd "$PROJECT_ROOT" || exit 1
    
    # Start Tilt
    if tilt up 2>&1; then
        echo "Waiting for Tilt to be ready..."
        local max_wait=30
        local elapsed=0
        
        while [ $elapsed -lt $max_wait ]; do
            if tilt status >/dev/null 2>&1; then
                log_info "Tilt cluster is running"
                return 0
            fi
            sleep 1
            ((elapsed++))
        done
        
        log_warn "Tilt did not report ready within $max_wait seconds"
        return 0
    else
        log_error "Failed to start Tilt"
        return 1
    fi
}

# Stop Tilt
stop_tilt() {
    echo ""
    echo "Stopping Tilt cluster..."
    
    if ! check_tilt_running; then
        log_warn "Tilt is not running"
        return 0
    fi
    
    cd "$PROJECT_ROOT" || exit 1
    
    if tilt down 2>&1; then
        log_info "Tilt cluster stopped"
        return 0
    else
        log_error "Failed to stop Tilt"
        return 1
    fi
}

# Check if Tilt is running
check_tilt_running() {
    tilt status >/dev/null 2>&1
    return $?
}

# Main function
main() {
    local action="${1:-validate}"
    
    case "$action" in
        validate)
            validate_prerequisites
            ;;
        start)
            validate_prerequisites && start_tilt
            ;;
        stop)
            stop_tilt
            ;;
        restart)
            stop_tilt && start_tilt
            ;;
        status)
            if check_tilt_running; then
                log_info "Tilt is running"
                tilt status
            else
                log_warn "Tilt is not running"
            fi
            ;;
        *)
            echo "Usage: $0 {validate|start|stop|restart|status}"
            exit 1
            ;;
    esac
}

main "$@"
