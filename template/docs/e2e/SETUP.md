# E2E setup and troubleshooting

Follow the [Quickstart](QUICKSTART.md) from the root of a generated project.
Keep the Python virtual environment active when running the command. The first
run may take longer because kind and Tilt need to pull and build images.

## What the command verifies

Tilt deploys the local Kubernetes manifests to a newly created kind cluster.
The E2E resource waits for the application's workloads, then checks Django's
`/readiness` endpoint. This checks the database connection after the backend's
migration init container has completed. When Next.js is enabled, its HTTP
endpoint must also respond before pytest starts.

Home and About are requested anonymously. The suite uses Next.js when enabled
and the Django-rendered routes otherwise. Wagtail-enabled projects also create
a temporary CMS administrator, sign in through the real Wagtail login form,
edit and publish the intro of the generated example page, and fetch the public
page with a separate anonymous client to verify the update.

The same command runs in template CI across the Next.js/Wagtail combinations.

## Reports

Every run prints its own directory under `e2e/reports/`. It contains:

| File | Contents |
| --- | --- |
| `kind.log` | Cluster creation output |
| `tilt.log` | Tilt build output, readiness errors and pytest summary |
| `test-report.json` | Per-test results when pytest ran |
| `diagnostics.log` | Kubernetes resource status, events and pod logs when a run fails after the cluster is created |
| `cleanup.log` | Cluster deletion output |

If cluster startup fails, check `docker info` and read `kind.log`. If services
time out, check `tilt.log` for image or readiness failures and `diagnostics.log`
for details on workloads, including the backend migration container. If the
CMS test fails, check the named login, edit, publish or public page assertion
in the pytest output.

## Cleanup and repeat runs

The command uses an isolated kubeconfig, chooses loopback ports for the test
services and deletes the cluster it created on success, failure or
interruption. Each invocation starts with a new database. If cleanup is
interrupted or fails, the runner prints the exact kind command for deleting
its cluster.
