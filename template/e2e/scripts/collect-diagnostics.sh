#!/bin/bash
# Diagnostic Collection Script
# Gathers logs, pod status, and other debugging information when tests fail

set -e

OUTPUT_FILE="${1:-diagnostics.log}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging
log_section() {
    echo -e "${BLUE}=== $1 ===${NC}" | tee -a "$OUTPUT_FILE"
}

log_info() {
    echo -e "${GREEN}✓${NC} $1" | tee -a "$OUTPUT_FILE"
}

log_error() {
    echo -e "${RED}✗${NC} $1" | tee -a "$OUTPUT_FILE"
}

# Main diagnostics collection
main() {
    echo "Starting diagnostic collection..." >&2
    
    # Create or clear output file
    > "$OUTPUT_FILE"
    
    log_section "Diagnostic Report"
    echo "Generated at: $(date -u +'%Y-%m-%dT%H:%M:%SZ')" | tee -a "$OUTPUT_FILE"
    echo "Hostname: $(hostname)" | tee -a "$OUTPUT_FILE"
    echo "" | tee -a "$OUTPUT_FILE"
    
    # Kubernetes pod status
    log_section "Kubernetes Pod Status"
    if command -v kubectl >/dev/null 2>&1; then
        echo "Pods:" >> "$OUTPUT_FILE"
        kubectl get pods -A 2>&1 | tee -a "$OUTPUT_FILE" || log_error "Failed to get pods"
        echo "" >> "$OUTPUT_FILE"
    else
        log_error "kubectl not found"
    fi
    
    # Pod descriptions
    log_section "Pod Descriptions"
    if command -v kubectl >/dev/null 2>&1; then
        kubectl describe pods -A 2>&1 | tee -a "$OUTPUT_FILE" || log_error "Failed to describe pods"
        echo "" >> "$OUTPUT_FILE"
    else
        log_error "kubectl not found"
    fi
    
    # Pod logs
    log_section "Pod Logs"
    if command -v kubectl >/dev/null 2>&1; then
        # Get all pods with namespace and collect their logs
        kubectl get pods -A -o json 2>/dev/null | \
        jq -r '.items[] | "\(.metadata.namespace) \(.metadata.name)"' | while read -r ns pod; do
            if [ -n "$ns" ] && [ -n "$pod" ]; then
                echo "--- Logs for pod: $ns/$pod ---" >> "$OUTPUT_FILE"
                kubectl logs -n "$ns" "$pod" --timestamps=true --tail=100 2>&1 | tee -a "$OUTPUT_FILE" || echo "No logs available for $ns/$pod" >> "$OUTPUT_FILE"
                echo "" >> "$OUTPUT_FILE"
            fi
        done
    else
        log_error "kubectl not found"
    fi
    
    # Service status
    log_section "Service Status"
    if command -v kubectl >/dev/null 2>&1; then
        echo "Services:" >> "$OUTPUT_FILE"
        kubectl get svc -A 2>&1 | tee -a "$OUTPUT_FILE" || log_error "Failed to get services"
        echo "" >> "$OUTPUT_FILE"
    else
        log_error "kubectl not found"
    fi
    
    # Tilt status
    log_section "Tilt Status"
    if command -v tilt >/dev/null 2>&1; then
        echo "Tilt status:" >> "$OUTPUT_FILE"
        tilt status 2>&1 | tee -a "$OUTPUT_FILE" || log_error "Failed to get Tilt status"
        echo "" >> "$OUTPUT_FILE"
    else
        log_error "tilt not found"
    fi
    
    # Docker info
    log_section "Docker Information"
    if command -v docker >/dev/null 2>&1; then
        echo "Docker version:" >> "$OUTPUT_FILE"
        docker --version 2>&1 | tee -a "$OUTPUT_FILE" || log_error "Failed to get Docker version"
        echo "" >> "$OUTPUT_FILE"
        
        echo "Running containers:" >> "$OUTPUT_FILE"
        docker ps 2>&1 | tee -a "$OUTPUT_FILE" || log_error "Failed to list containers"
        echo "" >> "$OUTPUT_FILE"
    else
        log_error "docker not found"
    fi
    
    # Kubernetes events
    log_section "Kubernetes Events"
    if command -v kubectl >/dev/null 2>&1; then
        echo "Recent events:" >> "$OUTPUT_FILE"
        kubectl get events -A 2>&1 | tee -a "$OUTPUT_FILE" || log_error "Failed to get events"
        echo "" >> "$OUTPUT_FILE"
    else
        log_error "kubectl not found"
    fi
    
    log_info "Diagnostics collected to: $OUTPUT_FILE"
}

main "$@"
