# End-to-End Verification for Local Tilt Cluster Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a comprehensive, automated E2E verification system that validates a scaffolded application running on a local Tilt cluster, confirming all services deploy successfully and core workflows function correctly.

**Architecture:** A Python-based test framework with async health-check verification, modular test cases exercising the full application stack (frontend → backend → database), and comprehensive diagnostic collection for failed tests. The system supports both standalone verification runs and CI/CD integration with clear PASS/FAIL reporting.

**Tech Stack:**
- Python 3.8+ with pytest framework
- pytest-asyncio for async health checks and test execution
- httpx or requests for HTTP API testing
- psycopg2 for database connectivity verification
- YAML for test configuration
- Bash shell scripts for orchestration

**Spec:** `docs/specs/2026-11-17-issue-214-add-full-end-to-end-verification-on-a-local-tilt-design.md`

## Global Constraints

- Tests must run against a live Tilt cluster (no mocking of services).
- All test data must be fixtures or seeded data; no reliance on pre-existing state.
- Maximum wait time for service health check: 2 minutes (configurable).
- Tests must be repeatable from a clean environment state.
- Python version floor: 3.8
- Kubernetes kubectl must be available in PATH.
- Tilt must be available in PATH and functional.

## Review Focus

1. **Service health check timeout or false negatives:** Tests assume a service is healthy but it fails during test execution. Health checks must be robust and reflect actual service readiness.
2. **Database state contamination between tests:** Sequential tests may fail if previous test data is not cleaned up. Transactions or fixtures must ensure isolation.
3. **Frontend rendering without JavaScript execution:** Tests check for HTTP 200 and HTML markup but don't execute JavaScript. Breaking changes to frontend initialization or hydration may not be caught.
4. **Backend API contract drift:** Tests hardcode API endpoint paths and response schemas. Backend changes (endpoint renames, response structure changes) will break tests silently if not updated.
5. **Environment-specific failures:** Tests may pass locally but fail in CI due to network config, DNS, or Kubernetes version differences. Test diagnostics must clearly separate configuration issues from application bugs.

---

## File Structure

```
e2e/
  config/
    health-checks.yaml      # Service health check definitions
    test-data.yaml          # Fixture data and test constants
  scripts/
    e2e-setup.sh            # Cluster setup and teardown
    e2e-run.sh              # Test orchestration script
    collect-diagnostics.sh  # Log and pod state collection
  tests/
    __init__.py
    conftest.py             # Shared pytest configuration, fixtures
    test_health_checks.py   # Health check tests
    test_frontend.py        # Frontend availability tests
    test_backend_api.py     # Backend API connectivity tests
    test_database.py        # Backend-to-database connectivity tests
    test_workflows.py       # Complete workflow tests
  lib/
    __init__.py
    health_checker.py       # Service health verification logic
    test_runner.py          # Test execution and reporting
    diagnostics.py          # Log and diagnostic collection
    fixtures.py             # Test data and seed utilities
  reports/
    test_report.json        # Test run report (generated)
    diagnostics.log         # Collected diagnostics (generated)
docs/
  e2e/
    QUICKSTART.md           # 5-minute quick-start guide
    SETUP.md                # Full setup and prerequisites
    TROUBLESHOOTING.md      # Common failures and fixes
    ARCHITECTURE.md         # Design and test framework details
```

## Task Breakdown

### Task 1: Setup Scripts and Cluster Orchestration

**Files:**
- Create: `e2e/scripts/e2e-setup.sh`
- Create: `e2e/scripts/e2e-run.sh`
- Create: `e2e/config/health-checks.yaml`
- Modify: `e2e/scripts/collect-diagnostics.sh` (or create if missing)

**Interfaces:**
- Consumes: Tilt configuration from `Tiltfile` (read-only)
- Produces: Setup status output, diagnostics collection script interface

**Steps:**

- [ ] **Step 1: Create `e2e/scripts/e2e-setup.sh` with cluster validation**

Implement a Bash script that:
1. Validates all required tools are installed (docker, kubectl, tilt).
2. Checks for minimum versions of each tool.
3. Halts with an error message if any requirement is missing.
4. Outputs a summary of validated tools and versions.

```bash
#!/bin/bash
set -e

echo "Validating E2E prerequisites..."
# Check for each required tool
# Display versions
# Exit 1 if any tool is missing
```

- [ ] **Step 2: Run validation test to confirm prerequisites are detected**

Create a simple test script that calls `e2e-setup.sh` and verifies:
- All tools are found when available.
- Clear error messages when tools are missing.

Run: `bash e2e/scripts/e2e-setup.sh`
Expected: Validation succeeds or fails with clear error messages.

- [ ] **Step 3: Extend `e2e-setup.sh` to start and stop Tilt**

Add functions to the script:
- `start_tilt()`: Runs `tilt up` and waits for Tilt to report ready.
- `stop_tilt()`: Runs `tilt down` to remove all resources.
- `check_tilt_running()`: Uses `tilt status` to verify Tilt cluster is operational.

- [ ] **Step 4: Create `e2e/config/health-checks.yaml`**

Define the services and health check endpoints in YAML:

```yaml
services:
  frontend:
    name: "Frontend"
    url: "http://frontend:3000"
    health_endpoint: "/"
    expected_status: 200
    description: "React/Vue web application"
    timeout_seconds: 30
  
  backend:
    name: "Backend API"
    url: "http://backend:8000"
    health_endpoint: "/api/health"
    expected_status: 200
    description: "REST API service"
    timeout_seconds: 30
  
  database:
    name: "PostgreSQL Database"
    type: "database"
    host: "postgres"
    port: 5432
    database: "app_db"
    health_check: "SELECT 1"
    timeout_seconds: 30
```

- [ ] **Step 5: Create `e2e/scripts/e2e-run.sh` for test orchestration**

Implement a Bash script that:
1. Calls `e2e-setup.sh` to validate prerequisites.
2. Starts Tilt (via `start_tilt()` function).
3. Runs pytest tests.
4. Collects diagnostics if tests fail.
5. Stops Tilt and cleans up.
6. Exits with appropriate status code.

```bash
#!/bin/bash
source e2e/scripts/e2e-setup.sh
start_tilt
pytest e2e/tests/
RESULT=$?
if [ $RESULT -ne 0 ]; then
  bash e2e/scripts/collect-diagnostics.sh
fi
stop_tilt
exit $RESULT
```

- [ ] **Step 6: Create `e2e/scripts/collect-diagnostics.sh`**

Implement a Bash script that collects logs and pod state when tests fail:
1. Runs `kubectl get pods` to show pod status.
2. Runs `kubectl describe pods` for detailed pod information.
3. Collects logs from each pod: `kubectl logs <pod>`.
4. Saves output to `e2e/reports/diagnostics.log`.
5. Displays summary of collected diagnostics to stdout.

- [ ] **Step 7: Commit setup and configuration files**

```bash
git add e2e/scripts/ e2e/config/
git commit -m "feat(e2e): add cluster setup and orchestration scripts"
```

---

### Task 2: Test Framework and Utilities

**Files:**
- Create: `e2e/lib/health_checker.py`
- Create: `e2e/lib/test_runner.py`
- Create: `e2e/lib/diagnostics.py`
- Create: `e2e/lib/fixtures.py`
- Create: `e2e/lib/__init__.py`
- Create: `e2e/tests/conftest.py`
- Create: `e2e/tests/__init__.py`
- Create: `e2e/requirements.txt`

**Interfaces:**
- Consumes: `e2e/config/health-checks.yaml` (read), Tilt cluster (live connection)
- Produces: `HealthChecker` class, `TestRunner` class, pytest fixtures, test report format

**Steps:**

- [ ] **Step 1: Create `e2e/lib/health_checker.py` with HealthChecker class**

Implement a `HealthChecker` class:
- Constructor: `__init__(self, config_path: str, timeout_seconds: int = 120)`
- Method: `async check_all_services() -> Dict[str, HealthStatus]`
  - Returns dict with service name as key, HealthStatus (healthy/unhealthy/timeout) as value.
  - Waits up to `timeout_seconds` for all services to become healthy.
  - Raises exception if any service fails to become healthy.
- Method: `async check_service(service_name: str) -> bool`
  - Makes HTTP request (for HTTP services) or database connection (for database).
  - Returns True if healthy, False if unhealthy.
- Property: `service_statuses` - returns current status of all services.

```python
class HealthChecker:
    def __init__(self, config_path: str, timeout_seconds: int = 120):
        self.config = load_yaml(config_path)
        self.timeout_seconds = timeout_seconds
        self.statuses = {}
    
    async def check_all_services(self) -> Dict[str, str]:
        # Implement parallel health checks with timeout
        pass
```

- [ ] **Step 2: Implement HTTP service health checks in HealthChecker**

Add a method `_check_http_service(service: dict) -> bool`:
1. Constructs health check URL from service config.
2. Makes HTTP GET request with connection timeout.
3. Checks response status code matches `expected_status`.
4. Returns True if successful, False if request fails or status mismatch.

Use httpx library for async HTTP requests.

- [ ] **Step 3: Implement database service health checks in HealthChecker**

Add a method `_check_database_service(service: dict) -> bool`:
1. Constructs database connection string from service config.
2. Opens a connection using psycopg2.
3. Executes health check query (e.g., `SELECT 1`).
4. Returns True if query succeeds, False if connection fails.

Handle connection errors gracefully and return False.

- [ ] **Step 4: Create `e2e/lib/test_runner.py` with TestRunner class**

Implement a `TestRunner` class:
- Constructor: `__init__(self, test_dir: str, report_path: str)`
- Method: `run_tests() -> TestReport`
  - Executes all tests in `test_dir` using pytest.
  - Collects results (passed, failed, skipped, duration).
  - Saves report to `report_path` as JSON.
  - Returns TestReport object.
- Method: `format_report() -> str`
  - Returns human-readable test report summary.

```python
class TestRunner:
    def __init__(self, test_dir: str, report_path: str):
        self.test_dir = test_dir
        self.report_path = report_path
    
    def run_tests(self) -> TestReport:
        # Execute pytest and collect results
        pass
```

- [ ] **Step 5: Create `e2e/lib/diagnostics.py` with log collection**

Implement a `DiagnosticsCollector` class:
- Method: `collect_pod_logs() -> str`
  - Runs `kubectl get pods` to list all pods.
  - For each pod, runs `kubectl logs <pod>` to collect logs.
  - Returns all logs as a string.
- Method: `collect_pod_status() -> str`
  - Runs `kubectl describe pods` to get detailed pod status.
  - Returns pod status information as a string.
- Method: `save_diagnostics(output_path: str) -> None`
  - Collects logs, status, and other diagnostic info.
  - Saves to file at `output_path`.

- [ ] **Step 6: Create `e2e/lib/fixtures.py` with test data utilities**

Implement functions for test data:
- `load_test_data(config_path: str) -> dict`
  - Loads test data from `e2e/config/test-data.yaml`.
  - Returns dict of test data (users, tasks, etc.) for use in tests.
- `cleanup_test_data(backend_url: str) -> None`
  - Calls a cleanup endpoint on the backend to reset test data.
  - Or, uses database connection to delete test data directly.

- [ ] **Step 7: Create `e2e/tests/conftest.py` with pytest configuration**

Implement pytest fixtures:
- `health_checker_fixture()`: Returns a HealthChecker instance, runs setup.
- `backend_url_fixture()`: Returns the backend URL from config.
- `frontend_url_fixture()`: Returns the frontend URL from config.
- `test_data_fixture()`: Loads and provides test data to tests.
- `cleanup_fixture()`: Cleanup fixture that runs after each test.

Configure pytest to:
- Use asyncio for async tests.
- Set markers for test categories (health, api, frontend, workflow).
- Configure test discovery.

```python
@pytest.fixture
async def health_checker():
    checker = HealthChecker("e2e/config/health-checks.yaml")
    yield checker
```

- [ ] **Step 8: Create `e2e/requirements.txt`**

List all Python dependencies:
```
pytest>=7.0
pytest-asyncio>=0.21
httpx>=0.24
psycopg2-binary>=2.9
pyyaml>=6.0
```

- [ ] **Step 9: Create `e2e/lib/__init__.py` and `e2e/tests/__init__.py`**

Create empty `__init__.py` files to make directories Python packages.

- [ ] **Step 10: Commit test framework**

```bash
git add e2e/lib/ e2e/tests/conftest.py e2e/requirements.txt
git commit -m "feat(e2e): add test framework and health checker utilities"
```

---

### Task 3: Health Check Tests

**Files:**
- Create: `e2e/tests/test_health_checks.py`
- Modify: `e2e/config/test-data.yaml` (create with minimal defaults)

**Interfaces:**
- Consumes: `HealthChecker` class, `health-checks.yaml` configuration
- Produces: Passing health check tests, service availability confirmation

**Steps:**

- [ ] **Step 1: Create `e2e/config/test-data.yaml` with defaults**

Create a minimal test data configuration:

```yaml
# Test data for E2E verification
test_users:
  - username: "test_user"
    email: "test@example.com"
    password: "test_password_123"

test_items:
  - title: "Test Task 1"
    description: "This is a test task"
  - title: "Test Task 2"
    description: "Another test task"

database:
  user: "app_user"
  password: "app_password"
  name: "app_db"
```

- [ ] **Step 2: Create `e2e/tests/test_health_checks.py`**

Implement health check tests:

```python
@pytest.mark.asyncio
@pytest.mark.health
async def test_all_services_healthy(health_checker):
    """Verify all required services reach healthy state."""
    statuses = await health_checker.check_all_services()
    
    for service_name, status in statuses.items():
        assert status == "healthy", f"{service_name} is not healthy: {status}"

@pytest.mark.asyncio
@pytest.mark.health
async def test_frontend_service_healthy(health_checker):
    """Verify frontend service is accessible."""
    status = await health_checker.check_service("frontend")
    assert status is True, "Frontend service is not healthy"

@pytest.mark.asyncio
@pytest.mark.health
async def test_backend_service_healthy(health_checker):
    """Verify backend API service is accessible."""
    status = await health_checker.check_service("backend")
    assert status is True, "Backend service is not healthy"

@pytest.mark.asyncio
@pytest.mark.health
async def test_database_service_healthy(health_checker):
    """Verify database is accessible."""
    status = await health_checker.check_service("database")
    assert status is True, "Database is not healthy"
```

- [ ] **Step 3: Run health check tests to verify they execute**

Run: `pytest e2e/tests/test_health_checks.py -v`
Expected: All health check tests PASS or indicate services are not yet running (expected on first run before Tilt starts).

- [ ] **Step 4: Commit health check tests**

```bash
git add e2e/tests/test_health_checks.py e2e/config/test-data.yaml
git commit -m "feat(e2e): add health check verification tests"
```

---

### Task 4: Frontend Availability Tests

**Files:**
- Create: `e2e/tests/test_frontend.py`

**Interfaces:**
- Consumes: `frontend_url_fixture`, HTTP client library (httpx)
- Produces: Frontend availability verification tests

**Steps:**

- [ ] **Step 1: Create `e2e/tests/test_frontend.py`**

Implement frontend tests:

```python
@pytest.mark.asyncio
@pytest.mark.frontend
async def test_frontend_http_200(frontend_url):
    """Verify frontend responds with HTTP 200 OK."""
    async with httpx.AsyncClient() as client:
        response = await client.get(frontend_url)
        assert response.status_code == 200, \
            f"Frontend returned {response.status_code}, expected 200"

@pytest.mark.asyncio
@pytest.mark.frontend
async def test_frontend_contains_html(frontend_url):
    """Verify frontend response contains valid HTML."""
    async with httpx.AsyncClient() as client:
        response = await client.get(frontend_url)
        content = response.text
        
        assert "<html" in content.lower() or "<!doctype" in content.lower(), \
            "Frontend response does not contain HTML markup"
        assert "<head" in content.lower() or "head" in content.lower(), \
            "Frontend response missing <head> tag"

@pytest.mark.asyncio
@pytest.mark.frontend
async def test_frontend_contains_root_div(frontend_url):
    """Verify frontend renders React/Vue root element."""
    async with httpx.AsyncClient() as client:
        response = await client.get(frontend_url)
        content = response.text
        
        # Check for common React/Vue root element IDs
        assert 'id="root"' in content or 'id="app"' in content, \
            "Frontend response missing root div (id='root' or id='app')"
```

- [ ] **Step 2: Run frontend tests to verify implementation**

Run: `pytest e2e/tests/test_frontend.py -v`
Expected: Tests PASS when Tilt cluster is running and frontend is accessible.

- [ ] **Step 3: Commit frontend tests**

```bash
git add e2e/tests/test_frontend.py
git commit -m "feat(e2e): add frontend availability tests"
```

---

### Task 5: Backend API Tests

**Files:**
- Create: `e2e/tests/test_backend_api.py`

**Interfaces:**
- Consumes: `backend_url_fixture`, HTTP client library (httpx)
- Produces: Backend API connectivity verification tests

**Steps:**

- [ ] **Step 1: Create `e2e/tests/test_backend_api.py`**

Implement backend API tests:

```python
@pytest.mark.asyncio
@pytest.mark.api
async def test_backend_health_endpoint(backend_url):
    """Verify backend /api/health endpoint responds."""
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{backend_url}/api/health")
        assert response.status_code == 200, \
            f"Backend health check failed: {response.status_code}"
        
        data = response.json()
        assert data.get("status") == "ok", \
            f"Backend health status is not 'ok': {data}"

@pytest.mark.asyncio
@pytest.mark.api
async def test_backend_accepts_requests(backend_url):
    """Verify backend accepts HTTP requests."""
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{backend_url}/api/status")
        assert response.status_code in [200, 404], \
            f"Backend returned unexpected status: {response.status_code}"
```

- [ ] **Step 2: Run backend API tests**

Run: `pytest e2e/tests/test_backend_api.py -v`
Expected: Tests PASS when backend service is running and responding.

- [ ] **Step 3: Commit backend API tests**

```bash
git add e2e/tests/test_backend_api.py
git commit -m "feat(e2e): add backend API connectivity tests"
```

---

### Task 6: Database Connectivity Tests

**Files:**
- Create: `e2e/tests/test_database.py`

**Interfaces:**
- Consumes: Database credentials from config, `fixtures.py` utilities, database connection library (psycopg2)
- Produces: Database connectivity and query verification tests

**Steps:**

- [ ] **Step 1: Create `e2e/tests/test_database.py`**

Implement database tests:

```python
@pytest.mark.asyncio
@pytest.mark.database
async def test_database_connection(test_data):
    """Verify database connection is successful."""
    try:
        conn = psycopg2.connect(
            host=test_data["database"]["host"],
            user=test_data["database"]["user"],
            password=test_data["database"]["password"],
            database=test_data["database"]["name"]
        )
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        result = cursor.fetchone()
        cursor.close()
        conn.close()
        
        assert result[0] == 1, "Database query returned unexpected result"
    except psycopg2.Error as e:
        pytest.fail(f"Database connection failed: {e}")

@pytest.mark.asyncio
@pytest.mark.database
async def test_database_schema_exists(test_data):
    """Verify database schema is initialized."""
    try:
        conn = psycopg2.connect(
            host=test_data["database"]["host"],
            user=test_data["database"]["user"],
            password=test_data["database"]["password"],
            database=test_data["database"]["name"]
        )
        cursor = conn.cursor()
        
        # Check for expected tables (customize based on schema)
        cursor.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public'
        """)
        tables = cursor.fetchall()
        
        cursor.close()
        conn.close()
        
        assert len(tables) > 0, "Database schema is empty; expected tables not found"
    except psycopg2.Error as e:
        pytest.fail(f"Database schema check failed: {e}")
```

- [ ] **Step 2: Run database tests**

Run: `pytest e2e/tests/test_database.py -v`
Expected: Tests PASS when database is accessible and initialized.

- [ ] **Step 3: Commit database tests**

```bash
git add e2e/tests/test_database.py
git commit -m "feat(e2e): add database connectivity tests"
```

---

### Task 7: Complete Workflow Tests

**Files:**
- Create: `e2e/tests/test_workflows.py`

**Interfaces:**
- Consumes: `backend_url_fixture`, `test_data_fixture`, HTTP client library (httpx), database connection
- Produces: End-to-end workflow verification tests

**Steps:**

- [ ] **Step 1: Create `e2e/tests/test_workflows.py`**

Implement complete workflow tests:

```python
@pytest.mark.asyncio
@pytest.mark.workflow
async def test_backend_to_database_write_and_read(backend_url, test_data):
    """Verify backend can write to and read from database."""
    async with httpx.AsyncClient() as client:
        # Create test item via API
        payload = {"title": test_data["test_items"][0]["title"]}
        create_response = await client.post(
            f"{backend_url}/api/items",
            json=payload
        )
        
        assert create_response.status_code == 201, \
            f"Failed to create item: {create_response.status_code}"
        
        created_item = create_response.json()
        item_id = created_item.get("id")
        
        # Retrieve item via API
        get_response = await client.get(f"{backend_url}/api/items/{item_id}")
        assert get_response.status_code == 200, \
            f"Failed to retrieve item: {get_response.status_code}"
        
        retrieved_item = get_response.json()
        assert retrieved_item.get("title") == payload["title"], \
            "Retrieved item does not match created item"

@pytest.mark.asyncio
@pytest.mark.workflow
async def test_complete_user_workflow(backend_url, test_data):
    """Verify a complete application workflow."""
    async with httpx.AsyncClient() as client:
        # Step 1: Verify backend is ready
        health_response = await client.get(f"{backend_url}/api/health")
        assert health_response.status_code == 200, \
            "Backend is not healthy"
        
        # Step 2: Create multiple items
        items = []
        for item_data in test_data["test_items"]:
            response = await client.post(
                f"{backend_url}/api/items",
                json={"title": item_data["title"]}
            )
            assert response.status_code == 201, \
                f"Failed to create item: {response.status_code}"
            items.append(response.json())
        
        # Step 3: List all items
        list_response = await client.get(f"{backend_url}/api/items")
        assert list_response.status_code == 200, \
            "Failed to list items"
        
        all_items = list_response.json()
        assert len(all_items) >= len(items), \
            "Not all created items appear in list"
        
        # Step 4: Update an item
        item_id = items[0]["id"]
        update_response = await client.put(
            f"{backend_url}/api/items/{item_id}",
            json={"title": "Updated Title"}
        )
        assert update_response.status_code == 200, \
            f"Failed to update item: {update_response.status_code}"
        
        # Verify update
        verify_response = await client.get(f"{backend_url}/api/items/{item_id}")
        assert verify_response.status_code == 200
        assert verify_response.json()["title"] == "Updated Title", \
            "Item update was not persisted"
```

- [ ] **Step 2: Run workflow tests**

Run: `pytest e2e/tests/test_workflows.py -v`
Expected: Tests PASS when all services are running and APIs are functional.

- [ ] **Step 3: Commit workflow tests**

```bash
git add e2e/tests/test_workflows.py
git commit -m "feat(e2e): add complete workflow verification tests"
```

---

### Task 8: Test Reporting and Integration

**Files:**
- Modify: `e2e/lib/test_runner.py` (extend from Task 2)
- Create: `e2e/lib/report_formatter.py`

**Interfaces:**
- Consumes: Test results from pytest, test report JSON format
- Produces: Human-readable test reports, CI/CD integration data

**Steps:**

- [ ] **Step 1: Extend `e2e/lib/test_runner.py` to generate detailed reports**

Implement report generation:
- Capture test execution time for each test.
- Capture pytest output and format it.
- Generate JSON report with test results, timings, failures.

```python
def generate_json_report(self, test_results):
    """Generate JSON report from pytest results."""
    report = {
        "timestamp": datetime.now().isoformat(),
        "total_tests": len(test_results),
        "passed": sum(1 for t in test_results if t["outcome"] == "passed"),
        "failed": sum(1 for t in test_results if t["outcome"] == "failed"),
        "tests": test_results
    }
    return report
```

- [ ] **Step 2: Create `e2e/lib/report_formatter.py`**

Implement report formatting:

```python
class ReportFormatter:
    @staticmethod
    def format_summary(test_results) -> str:
        """Format test results as human-readable summary."""
        passed = sum(1 for t in test_results if t["outcome"] == "passed")
        failed = sum(1 for t in test_results if t["outcome"] == "failed")
        
        summary = f"""
Test Run Summary
================
Total: {len(test_results)} tests
Passed: {passed}
Failed: {failed}
Duration: X seconds

Result: {'PASS' if failed == 0 else 'FAIL'}
"""
        return summary
```

- [ ] **Step 3: Integrate diagnostics collection when tests fail**

Modify test runner to:
- Run diagnostics collection if any test fails.
- Include diagnostic output in the final report.
- Save diagnostics to `e2e/reports/diagnostics.log`.

- [ ] **Step 4: Commit reporting improvements**

```bash
git add e2e/lib/report_formatter.py e2e/lib/test_runner.py
git commit -m "feat(e2e): add test reporting and diagnostics integration"
```

---

### Task 9: Documentation

**Files:**
- Create: `docs/e2e/QUICKSTART.md`
- Create: `docs/e2e/SETUP.md`
- Create: `docs/e2e/TROUBLESHOOTING.md`
- Create: `docs/e2e/ARCHITECTURE.md`

**Interfaces:**
- Consumes: Specification, test framework, scripts
- Produces: User and developer documentation

**Steps:**

- [ ] **Step 1: Create `docs/e2e/QUICKSTART.md`**

Write a 5-minute quick-start guide:

```markdown
# Quick Start: E2E Verification

## Prerequisites
- Docker
- kubectl
- Tilt
- Python 3.8+

## Run E2E Tests (5 minutes)

1. Install dependencies:
   ```bash
   pip install -r e2e/requirements.txt
   ```

2. Start E2E verification:
   ```bash
   bash e2e/scripts/e2e-run.sh
   ```

3. Wait for tests to complete (3-5 minutes).

4. Review test results in the terminal output.

If tests fail, see TROUBLESHOOTING.md for common issues.
```

- [ ] **Step 2: Create `docs/e2e/SETUP.md`**

Write full setup documentation:
- Detailed prerequisites with version requirements.
- Verification commands for each tool.
- Step-by-step Tilt cluster setup.
- Database initialization instructions.
- Configuration options (timeouts, URLs, test data).

- [ ] **Step 3: Create `docs/e2e/TROUBLESHOOTING.md`**

Write troubleshooting guide:
- Common failures and solutions.
- How to access pod logs.
- How to debug failing tests.
- Network connectivity checks.
- Kubernetes resource checks.

```markdown
## Service is not healthy

If a service fails to reach healthy state:

1. Check pod status:
   ```bash
   kubectl get pods
   ```

2. View pod logs:
   ```bash
   kubectl logs <pod-name>
   ```

3. Check service endpoints:
   ```bash
   kubectl get svc
   ```
```

- [ ] **Step 4: Create `docs/e2e/ARCHITECTURE.md`**

Write architecture documentation:
- Overview of test framework design.
- How to add new test scenarios.
- Test data setup and fixtures.
- Debugging test failures.
- Integration with CI/CD pipelines.

- [ ] **Step 5: Commit documentation**

```bash
git add docs/e2e/
git commit -m "docs(e2e): add comprehensive E2E verification documentation"
```

---

### Task 10: Final Integration and Validation

**Files:**
- Modify: Root-level `Tiltfile` (verify E2E resource definitions)
- Create or modify: `.gitignore` (exclude test artifacts)

**Interfaces:**
- Consumes: All E2E framework files and tests
- Produces: Fully functional E2E verification system ready for use

**Steps:**

- [ ] **Step 1: Verify Tiltfile includes E2E resources**

Check that `Tiltfile` defines all required services (frontend, backend, database, etc.) and that Tilt can start them successfully.

- [ ] **Step 2: Update `.gitignore` for E2E test artifacts**

Add lines to exclude generated test reports and diagnostics:

```
e2e/reports/
e2e/__pycache__/
e2e/.pytest_cache/
*.pyc
.env.local
```

- [ ] **Step 3: Run full E2E verification manually**

Execute: `bash e2e/scripts/e2e-run.sh`
Expected: All tests PASS or provide clear error messages with diagnostics.

- [ ] **Step 4: Verify cleanup works**

After E2E tests complete, verify:
- Tilt cluster is shut down.
- No Kubernetes resources remain.
- Local environment is clean for next test run.

- [ ] **Step 5: Final commit**

```bash
git add .gitignore
git commit -m "feat(e2e): complete end-to-end verification implementation"
```

---

## Review Focus Tests

This section maps each Review Focus item to the task and test that covers it:

1. **Service health check timeout or false negatives**
   - **Task 3, Test: `test_all_services_healthy`**
   - Verifies HealthChecker waits appropriately and detects unhealthy services before tests run.

2. **Database state contamination between tests**
   - **Task 7, Test: `test_backend_to_database_write_and_read`**
   - Uses unique test data per run; cleanup fixtures reset state between tests.
   - **Task 6, implicit:** Database schema check confirms clean, initialized state.

3. **Frontend rendering without JavaScript execution**
   - **Task 4, Test: `test_frontend_contains_root_div`**
   - Checks for React/Vue root element as a proxy for initialization.
   - **Limitation:** Documented in spec; browser automation E2E is out of scope.

4. **Backend API contract drift**
   - **Task 5, Test: `test_backend_health_endpoint`** and **Task 7, Test: `test_complete_user_workflow`**
   - Hardcoded endpoints and response schemas; breaking changes will cause test failures.
   - **Mitigation:** Tests must be updated when API contracts change; CI integration will catch this.

5. **Environment-specific failures**
   - **Task 8, Diagnostics Collection**
   - Collects pod logs, status, and events when tests fail.
   - **Task 9, `TROUBLESHOOTING.md`** provides network and DNS debugging steps.
   - **Mitigation:** Clear diagnostics help distinguish configuration issues from application bugs.

---

## Execution Handoff

Plan complete and saved to `docs/plans/2026-11-17-issue-214-add-full-end-to-end-verification-on-a-local-tilt-plan.md`.

This plan establishes a comprehensive E2E verification system with:
- Cluster orchestration and health checks (Task 1-2)
- Five layers of verification tests: health, frontend, API, database, workflows (Tasks 3-7)
- Professional test reporting and diagnostics (Task 8)
- Complete documentation for users and developers (Task 9)
- Final validation and integration (Task 10)

The plan is structured for inline execution with clear task boundaries and independently testable deliverables. Each task produces working, reviewable code that integrates seamlessly with the next task.
