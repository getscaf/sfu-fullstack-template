# End-to-end verification on a local Tilt cluster

A freshly generated Scaf application should start and work on its local
Kubernetes stack. A developer runs one command from the generated project to
verify the scaffold, get a useful failure report, and return to a clean state.
The same command runs in the template CI matrix.

## Execution

`bash e2e/scripts/e2e-run.sh` creates a disposable kind cluster with its own
kubeconfig and starts `tilt ci` using the project's Tiltfile. E2E mode runs
the standard local Kubernetes manifests, uses loopback port forwards, and
disables development syncback and Docker image pruning.

Tilt starts pytest while the services and their port forwards are available.
The test resource waits on the scaffold's enabled workloads. It probes
Django's `/readiness` endpoint, which checks its configured database, and the
Next.js endpoint when enabled. The backend runs its existing migration init
container before accepting traffic.

## Test scenarios

| Scaffold option | Expected result |
| --- | --- |
| Next.js enabled | Anonymous Home and About requests return the corresponding Next.js pages. |
| Next.js disabled | Anonymous Home and About requests return the scaffold's Django pages. |
| Wagtail enabled | A temporary CMS administrator signs in through Wagtail, edits and publishes the starter example page, and its public page shows the updated content. |
| Wagtail disabled | Only the standard page smoke tests run. |

The Wagtail test exercises the real editor forms, session, database persistence
and public rendering. The public request uses a fresh anonymous client and
goes to Next.js or Django according to the scaffold options. The temporary
administrator and edited content are confined to the disposable database.

## Results and cleanup

The command prints the outcome and returns a nonzero status if setup,
readiness, pytest or cleanup fails. Each run writes its logs and pytest JSON
report when pytest ran. On failure it also collects relevant Kubernetes
resource status, pod logs and events before deleting the cluster. Interruption
also triggers cleanup. All four Next.js/Wagtail CI variants upload their
reports.

A successful validation starts from a fresh scaffold, passes the applicable
tests, and removes the run's cluster. A controlled failure produces a nonzero
exit and diagnostics, and a repeated run starts from a new database.

This work covers local Tilt verification. Browser automation and production
build verification are tracked in [#206](https://github.com/getscaf/sfu-fullstack-template/issues/206).
AWS and production deployment verification are outside this scope.
