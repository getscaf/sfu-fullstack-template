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
        missing_tools=$((missing_tools + 1))
    fi
    
    # Check kubectl
    if command_exists kubectl; then
        local kubectl_version=$(kubectl version --client -o json 2>/dev/null | grep -o '"gitVersion":"[^"]*"' | cut -d'"' -f4 || echo "unknown")
        log_info "kubectl: $kubectl_version"
    else
        log_error "kubectl not found. Please install kubectl."
        missing_tools=$((missing_tools + 1))
    fi
    
    # Check Tilt
    if command_exists tilt; then
        local tilt_version=$(tilt version 2>/dev/null | head -1 || echo "unknown")
        log_info "Tilt: $tilt_version"
    else
        log_error "Tilt not found. Please install Tilt."
        missing_tools=$((missing_tools + 1))
    fi
    
    # Check Python
    if command_exists python3; then
        local python_version=$(python3 --version 2>&1 | awk '{print $2}')
        log_info "Python 3: $python_version"
    else
        log_error "Python 3 not found. Please install Python 3.8+."
        missing_tools=$((missing_tools + 1))
    fi
    
    echo ""
    if [ $missing_tools -gt 0 ]; then
        log_error "Missing $missing_tools required tool(s). Please install them and try again."
        return 1
    fi
    
    log_info "All prerequisites validated."
    return 0
}

# Check if Tilt is running
is_tilt_running() {
    # Check if tilt process exists
    pgrep -f "tilt serve" >/dev/null 2>&1
    return $?
}

# Start Tilt in background
start_tilt() {
    echo ""
    echo "Starting Tilt cluster..."
    
    if is_tilt_running; then
        log_warn "Tilt is already running"
        return 0
    fi
    
    cd "$PROJECT_ROOT" || return 1
    
    # Start Tilt in background (foreground mode for logs)
    # tilt up runs in foreground; we start it in background and wait for readiness
    if tilt up &
    then
        local tilt_pid=$!
        echo "Tilt process ID: $tilt_pid"
        
        # Wait for tilt to be responsive (check port 10350)
        local max_wait=60
        local elapsed=0
        
        while [ $elapsed -lt $max_wait ]; do
            if curl -s http://localhost:10350 >/dev/null 2>&1; then
                log_info "Tilt cluster is responding"
                return 0
            fi
            sleep 2
            elapsed=$((elapsed + 2))
        done
        
        log_warn "Tilt did not respond within $max_wait seconds, proceeding anyway"
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
    
    if ! is_tilt_running; then
        log_info "Tilt is not running"
        return 0
    fi
    
    cd "$PROJECT_ROOT" || return 1
    
    # Use tilt down to properly shut down
    if tilt down 2>&1; then
        log_info "Tilt cluster stopped"
        
        # Wait for process to actually die
        sleep 2
        return 0
    else
        log_error "Failed to stop Tilt with 'tilt down', killing process"
        pkill -f "tilt serve" || true
        return 0
    fi
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
            if is_tilt_running; then
                log_info "Tilt is running"
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
