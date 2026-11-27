# Local Tilt E2E implementation plan

The [specification](../specs/2026-11-17-issue-214-add-full-end-to-end-verification-on-a-local-tilt-design.md)
and implementation ship together in PR #215.

1. Update the branch from `main` and verify scaffold generation and formatter
   compatibility across the Next.js/Wagtail matrix.
2. Preserve `e2e/scripts/e2e-run.sh` as the entry point. Let the Python runner
   own the temporary kind cluster, kubeconfig, exit status and run directory.
   Add the E2E test resource to the existing Tiltfile and do the readiness
   checks before starting pytest.
3. Cover anonymous Home and About requests in both renderers. When Wagtail
   is enabled, use its existing forms to sign in, edit and publish the starter
   example page. Verify the changed content from a separate, anonymous request.
4. Collect per-test and Kubernetes diagnostics and clean up the cluster on
   pass, failure and interruption. Keep each run's reports for troubleshooting.
5. Run the same command in all four template CI variants. Verify a successful
   run, controlled failure, repeat with fresh data and cluster cleanup.
   Document the verified setup and report locations in the generated project.
