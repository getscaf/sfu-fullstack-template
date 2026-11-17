# End-to-End Verification for Local Tilt Cluster Specification

## Intent and Why

This specification defines a comprehensive end-to-end (E2E) verification process that validates a newly scaffolded application deployed on a local Kubernetes cluster managed by Tilt. The goal is to ensure that all application components (frontend, backend, database, and services) work together correctly from a clean state.

This verification validates the complete application workflow rather than testing individual components in isolation. It serves two purposes:

1. **Quality assurance**: Confirm that a fresh scaffolded project deploys and functions correctly.
2. **Documentation**: Establish a repeatable, documented process that contributors can use to verify their own scaffolded projects locally.

## Goals and Non-Goals

### Goals
- Establish a clear, documented process for running E2E verification locally on a Tilt cluster.
- Verify that all required services deploy successfully and reach a healthy state.
- Validate end-to-end workflows that exercise the full application stack (frontend → backend → database).
- Produce clear pass/fail results with actionable diagnostic information when tests fail.
- Enable reproducible testing from a completely clean local environment.
- Document environment cleanup procedures to prevent state contamination between test runs.

### Non-Goals
- Provision AWS infrastructure or test against cloud environments.
- Run automated E2E verification in an AWS sandbox.
- Automate AWS sandbox provisioning and teardown.
- Verify production deployment scenarios.
- Test individual components in isolation (unit or integration testing).
- Optimize test execution time or parallelization strategies.

## Constraints

- The verification process must run entirely on a local Kubernetes cluster managed by Tilt.
- The process must work with a fresh scaffolded project (no pre-existing application state).
- All required dependencies (Docker, Kubernetes, Tilt) must be installed and configured on the local machine.
- The environment must be cleanable to a known state before and after verification runs.
- Documentation must be clear enough for contributors without deep Kubernetes experience.

## Approaches Considered

### Approach 1: Shell Script with Manual Verification Steps
Create a shell script that starts Tilt, waits for services, and prints instructions for manual verification steps.

**Trade-offs:**
- Simple to understand for non-technical contributors
- Requires manual verification, error-prone and not repeatable
- Cannot be integrated into automated workflows

### Approach 2: Integration Tests Against Running Tilt Cluster (Recommended)
Write automated tests (using pytest, Node.js test runners, or similar) that run against a live Tilt cluster. Tests verify service availability, frontend rendering, API connectivity, and data flow.

**Trade-offs:**
- Fully automated and repeatable
- Can be integrated into CI/CD pipelines
- Requires test infrastructure but is more maintainable long-term
- Clear pass/fail results with detailed diagnostics

### Approach 3: Heavyweight E2E with Cypress/Playwright
Use browser automation tools to test the complete user journey, including UI interactions.

**Trade-offs:**
- Most realistic user scenario testing
- Heavier dependencies and more complex to set up
- Slower test execution
- Out of scope for initial implementation; can be added later

## Selected Approach

**Approach 2: Integration Tests Against Running Tilt Cluster**

This approach is recommended because it:
- Provides fully automated, repeatable verification without manual steps.
- Produces clear, actionable test results suitable for CI/CD integration.
- Can be maintained and extended by contributors with standard testing skills.
- Establishes a foundation for browser-based E2E tests in the future.

## Implementation Strategy

### 1. Local Environment Setup

**Prerequisites:**
- Docker (version X.X+)
- Kubernetes (kubectl, minimum version X.X)
- Tilt (version X.X+)
- Project-specific tools (Python 3.8+, Node.js 16+, etc.)

**Initialization Process:**

1. User prepares the local environment by running a setup script: `./scripts/e2e-setup.sh`
2. The script validates that all required tools are installed.
3. The script starts the Tilt cluster with the scaffolded project configuration.
4. Tilt monitors the status of all defined services.

**Expected Outcomes:**
- All Kubernetes services reach "Running" status.
- All readiness probes pass (if configured).
- Tilt dashboard shows all resources as healthy.

### 2. Service Health Verification

Before tests begin, the verification process confirms that all required services are healthy:

**Services to Verify:**
- **Frontend:** React/Vue web application (accessible via HTTP)
- **Backend API:** REST API service (responds to health checks)
- **Database:** PostgreSQL or other database (accepts connections, schema initialized)
- **Cache (if used):** Redis or similar (operational)

**Health Check Strategy:**
- Implement health endpoint checks (e.g., GET `/health` for the backend)
- Verify database connectivity and schema presence (e.g., SELECT COUNT(*) from key tables)
- Confirm frontend is served and renders without errors (e.g., HTTP 200 response with valid HTML)
- Use kubectl to verify pod status and resource availability

**Wait and Timeout Logic:**
- Tests wait up to 2 minutes for services to become healthy (configurable).
- If any service fails to reach healthy state, the verification stops with a clear error message.
- Logs from unhealthy pods are captured and displayed to aid debugging.

### 3. End-to-End Test Scenarios

The verification process includes tests that exercise representative workflows across the full application stack:

#### Test 1: Frontend Availability and Rendering
- **Objective:** Verify that the frontend is accessible and renders.
- **Steps:**
  1. Make an HTTP request to the frontend URL.
  2. Verify the response status is 200 OK.
  3. Verify the response contains expected HTML markup (e.g., title, root div).
- **Expected Result:** PASS

#### Test 2: Backend API Connectivity
- **Objective:** Verify that the backend API responds to requests.
- **Steps:**
  1. Call a simple backend API endpoint (e.g., GET `/api/health` or `/api/status`).
  2. Verify the response status is 200 OK.
  3. Verify the response contains expected JSON structure.
- **Expected Result:** PASS

#### Test 3: Backend-to-Database Connectivity
- **Objective:** Verify that the backend can read from and write to the database.
- **Steps:**
  1. Call a backend endpoint that writes test data (e.g., POST `/api/test-write`).
  2. Call a backend endpoint that reads that data (e.g., GET `/api/test-read`).
  3. Verify the written data matches the read data.
- **Expected Result:** PASS

#### Test 4: Frontend-to-Backend Communication
- **Objective:** Verify that the frontend can communicate with the backend.
- **Steps:**
  1. Call a backend endpoint that sets up initial data.
  2. Make a frontend request that fetches that data via the backend (simulated or real).
  3. Verify the data is accessible and correctly formatted.
- **Expected Result:** PASS

#### Test 5: Complete User Workflow (Representative)
- **Objective:** Verify a complete, representative application workflow.
- **Example Workflow (for a task app):**
  1. Create a new task via the backend API (or through a simulated frontend request).
  2. Retrieve the task list via the backend API.
  3. Verify the new task appears in the list.
  4. Update the task (e.g., mark as complete).
  5. Verify the update persists.
- **Expected Result:** PASS

### 4. Test Result Reporting

**Result Format:**
- Each test produces a clear PASS or FAIL result.
- Failed tests include:
  - The test name and objective.
  - The specific assertion that failed.
  - Relevant error messages or HTTP response details.
  - Suggested remediation steps.

**Output Destination:**
- Results are logged to stdout for display in the terminal.
- Results are also saved to a test report file (JSON or similar) for integration with CI/CD systems.

**Example Report Structure:**
```
Test Run: 2026-11-17 14:00:00 UTC
Duration: 45 seconds
Results:
  ✓ Frontend Availability and Rendering (1.2s)
  ✓ Backend API Connectivity (0.8s)
  ✓ Backend-to-Database Connectivity (2.1s)
  ✓ Frontend-to-Backend Communication (1.5s)
  ✓ Complete User Workflow (3.2s)

Summary: 5 passed, 0 failed
```

### 5. Failure Detection and Diagnostics

When a test fails, the verification process captures diagnostic information:

**Diagnostic Collection:**
- Kubernetes pod logs (all pods in the deployment)
- Pod resource status and events
- Error messages from the failing service
- Last 100 lines of each service's logs
- Network connectivity checks (ping, curl) to identify network issues

**Diagnostic Reporting:**
- Diagnostic information is included in the test report.
- A summary file is created with key debugging information.
- Clear instructions guide the user to investigate further (e.g., `kubectl logs <pod-name>`).

### 6. Reproducibility

**Making Tests Reproducible:**

- **Fresh State:** The setup process tears down any existing Tilt deployment before starting a new one.
- **Deterministic Test Data:** Tests use fixtures or seed data that is consistent across runs.
- **No External Dependencies:** Tests do not rely on pre-existing local state or external services.
- **Documented Prerequisites:** Clear documentation lists all required tools and versions.
- **Idempotent Operations:** Test operations (write, read, update) are designed to work correctly even if run multiple times.

**Setup and Cleanup Procedures:**

**Before Tests:**
1. Check if Tilt is already running; stop it if necessary.
2. Run `tilt down` to remove all Kubernetes resources.
3. Run `tilt up` to start the application fresh.
4. Wait for all services to reach healthy state (health checks pass).

**After Tests:**
1. Optionally collect logs and artifacts for debugging.
2. Run `tilt down` to remove all Kubernetes resources.
3. Run `docker system prune` to clean up unused Docker images and volumes (optional).
4. Confirm that the local environment is clean and ready for the next test run.

### 7. Documentation

The specification includes documentation for:

**User-Facing Documentation:**
- Quick-start guide: "How to run E2E verification locally" (5 minutes to first test run).
- Prerequisites checklist.
- Troubleshooting guide for common failures.
- Expected test duration and machine requirements.

**Developer Documentation:**
- Architecture overview of the test framework.
- How to add new test scenarios.
- Test data setup and fixtures.
- How to debug failing tests.

**CI/CD Integration Guide:**
- How to integrate the E2E tests into continuous integration pipelines.
- Expected environment variables and configuration.
- How to parse and report test results.

## Success Criteria

A successful E2E verification implementation meets these criteria:

1. ✅ A fresh scaffolded project can be started successfully in a local Tilt cluster without manual configuration.
2. ✅ All required services (frontend, backend, database) reach a healthy state before verification begins.
3. ✅ E2E tests validate the application's key workflows across the frontend, backend, and database.
4. ✅ Test execution produces clear PASS/FAIL results with useful diagnostic information when tests fail.
5. ✅ The verification process is fully reproducible and can be run multiple times from a clean state.
6. ✅ The local environment can be cleaned up completely after testing (all Tilt resources removed, state cleared).
7. ✅ Documentation is clear and sufficient for contributors to run E2E verification without additional guidance.

## Limitations

This specification establishes a foundation for local E2E verification. Known limitations and future improvements:

- **No browser automation:** Tests do not interact with the UI via a browser. Cypress/Playwright-based E2E tests can be added in a follow-up issue.
- **No load testing:** Tests verify basic functionality, not performance or scalability.
- **No multi-environment testing:** Tests currently run only on a local Kubernetes cluster. Cloud environment testing (AWS, GCP) is out of scope.
- **No A/B or feature-flag testing:** Tests assume a single, standard application configuration.

## Companion Artifacts

No mockups or visual companions are required for this specification.
