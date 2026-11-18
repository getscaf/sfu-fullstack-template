# E2E Verification Setup and Configuration

Complete setup and configuration guide for end-to-end verification on a local Tilt cluster.

## Prerequisites

### Required Tools

Install these tools before running E2E verification.

#### Docker

Download and install Docker Desktop from https://www.docker.com/products/docker-desktop

Verify installation:
```bash
docker --version
```

#### kubectl

Install kubectl from https://kubernetes.io/docs/tasks/tools/

Verify installation:
```bash
kubectl version --client
```

#### Tilt

Install Tilt from https://docs.tilt.dev/install.html

Verify installation:
```bash
tilt version
```

#### Python 3.8+

Python 3.8 or later is required.

Verify installation:
```bash
python3 --version
```

### Minimum Versions

- Docker: 20.0+
- kubectl: 1.20+
- Tilt: 0.30+
- Python: 3.8+

## Installation

### Step 1: Validate Prerequisites

Confirm all required tools are installed and functional:

```bash
bash e2e/scripts/e2e-setup.sh validate
```

Expected output:

```
✓ Docker: 29.0.0
✓ kubectl: v1.28.0
✓ Tilt: v0.33.13
✓ Python 3: 3.12.2
✓ All prerequisites validated.
```

If any tool is missing, install it and try again.

### Step 2: Install Python Dependencies

Install test framework dependencies:

```bash
pip install -r e2e/requirements.txt
```

Installed packages:

- pytest: test execution framework
- pytest-asyncio: async test support
- httpx: HTTP client for API testing
- psycopg2-binary: PostgreSQL client
- pyyaml: YAML configuration parsing

### Step 3: Verify Project Configuration

The project must include a `Tiltfile` that defines:

- Frontend service (accessible on http://localhost:3000)
- Backend API service (accessible on http://localhost:8000)
- PostgreSQL database (accessible on postgres:5432)

Verify the Tiltfile exists:

```bash
ls -la Tiltfile
```

## Configuration

### Service Configuration

Service health checks are defined in `e2e/config/health-checks.yaml`.

Each service includes:

- **type**: "http" or "database"
- **url**: Service URL for HTTP services
- **health_endpoint**: Endpoint to check for service health
- **expected_status**: Expected HTTP status code
- **timeout_seconds**: Maximum wait time for health check
- **retries**: Number of retry attempts

Example:

```yaml
services:
  frontend:
    name: "Frontend"
    type: "http"
    url: "http://localhost:3000"
    health_endpoint: "/"
    expected_status: 200
    timeout_seconds: 30
    retries: 5
```

### Test Data Configuration

Test fixtures are defined in `e2e/config/test-data.yaml`.

This includes:

- Test user credentials
- Test data items
- Database configuration

Customize test data for your application:

```yaml
test_users:
  - username: "test_user"
    email: "test@example.com"
    password: "test_password_123"

test_items:
  - title: "Item 1"
    description: "Description 1"
```

### Environment Variables

Override default configuration using environment variables:

```bash
# Frontend URL
export FRONTEND_URL="http://localhost:3000"

# Backend URL
export BACKEND_URL="http://localhost:8000"

# Database password
export DB_PASSWORD="postgres"
```

## Running Verification

### Basic Execution

Run the complete E2E verification workflow:

```bash
bash e2e/scripts/e2e-run.sh
```

### Manual Execution

Run components individually for debugging:

**Validate prerequisites:**
```bash
bash e2e/scripts/e2e-setup.sh validate
```

**Start Tilt:**
```bash
bash e2e/scripts/e2e-setup.sh start
```

**Run tests:**
```bash
pytest e2e/tests/ -v
```

**Stop Tilt:**
```bash
bash e2e/scripts/e2e-setup.sh stop
```

**Collect diagnostics:**
```bash
bash e2e/scripts/collect-diagnostics.sh e2e/reports/diagnostics.log
```

### Running Specific Tests

Run only health check tests:

```bash
pytest e2e/tests/test_health_checks.py -v
```

Run only frontend tests:

```bash
pytest e2e/tests/test_frontend.py -v
```

Run tests matching a pattern:

```bash
pytest e2e/tests/ -k "health" -v
```

## Test Reports

After running tests, results are saved in `e2e/reports/`:

- **test_output.log**: Complete pytest output
- **diagnostics.log**: Kubernetes and service diagnostics (if tests fail)
- **test_report.json**: Machine-readable test results (future)

View test output:

```bash
cat e2e/reports/test_output.log
```

View diagnostics:

```bash
cat e2e/reports/diagnostics.log
```

## Troubleshooting

### Services Not Becoming Healthy

Check Kubernetes pod status:

```bash
kubectl get pods -A
```

View pod logs:

```bash
kubectl logs <pod-name>
```

Check pod events:

```bash
kubectl describe pod <pod-name>
```

### Cannot Connect to Services

Verify services are exposed:

```bash
kubectl get svc -A
```

Port-forward to test connectivity:

```bash
kubectl port-forward svc/frontend 3000:3000
# In another terminal:
curl http://localhost:3000
```

### Tilt Not Starting

Check Tilt status:

```bash
tilt status
```

View Tilt logs:

```bash
tilt logs
```

Restart Tilt:

```bash
bash e2e/scripts/e2e-setup.sh restart
```

### Database Connection Issues

Verify PostgreSQL is running:

```bash
kubectl get pods -A | grep postgres
```

Test database connection:

```bash
kubectl exec -it <postgres-pod> -- psql -U postgres -c "SELECT 1"
```

Check database configuration in `e2e/config/test-data.yaml`.

## Cleanup

After running verification, clean up resources:

Stop Tilt:

```bash
bash e2e/scripts/e2e-setup.sh stop
```

Remove test reports:

```bash
rm -rf e2e/reports/
```

Clean up Docker resources:

```bash
docker system prune
```

## Next Steps

- Run E2E verification: `bash e2e/scripts/e2e-run.sh`
- Review quick start guide: [QUICKSTART.md](QUICKSTART.md)
- Check test results: `cat e2e/reports/test_output.log`
- Add custom tests: See `e2e/tests/` for examples
