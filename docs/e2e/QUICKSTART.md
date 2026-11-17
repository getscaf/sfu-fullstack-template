# E2E Verification Quick Start

Run end-to-end verification for a scaffolded application on a local Tilt cluster in 5 minutes.

## Prerequisites

Before starting, make sure you have installed:

- Docker (version 20+)
- kubectl (version 1.20+)
- Tilt (version 0.30+)
- Python 3.8 or later

## Run E2E Verification

**Step 1: Install Python dependencies**

```bash
pip install -r e2e/requirements.txt
```

**Step 2: Start E2E verification**

```bash
bash e2e/scripts/e2e-run.sh
```

This script will:

1. Validate all prerequisites are installed
2. Start Tilt cluster
3. Wait for services to become healthy
4. Run all E2E tests
5. Collect diagnostics if tests fail
6. Stop Tilt cluster

**Step 3: Review results**

Test results display in the terminal.

Pass example:

```
✓ All tests passed
========================================
```

Fail example:

```
✗ Some tests failed
Test output saved to: e2e/reports/test_output.log
Diagnostics saved to: e2e/reports/diagnostics.log
```

## Troubleshooting

If tests fail, check:

1. **Are all prerequisites installed?**
   ```bash
   bash e2e/scripts/e2e-setup.sh validate
   ```

2. **Can Tilt start successfully?**
   ```bash
   bash e2e/scripts/e2e-setup.sh start
   ```

3. **What do the service logs show?**
   ```bash
   kubectl logs -f <pod-name>
   ```

4. **Are there any Kubernetes errors?**
   ```bash
   kubectl get events -A
   ```

For detailed troubleshooting, see [SETUP.md](SETUP.md).

## Next Steps

- Read [SETUP.md](SETUP.md) for complete setup and configuration documentation
- Review test reports in `e2e/reports/` directory
- Add custom tests following the patterns in `e2e/tests/`
