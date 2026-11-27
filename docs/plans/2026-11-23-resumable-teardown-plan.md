# Resumable environment teardown

Issue [#227](https://github.com/getscaf/sfu-fullstack-template/issues/227).
Scope revised following [PR #231 review](https://github.com/getscaf/sfu-fullstack-template/pull/231#pullrequestreview-6061613120).

A newly generated project can use the same teardown task after an interrupted
destroy. Sandbox and staging protect data by default. A sandbox provisioned
for a demo or E2E run can opt into permanent deletion at generation time.
Existing partially destroyed projects do not require an automated migration.

- Copier writes the sandbox policy. The first successful apply stores the
  applicable force settings in the generated S3 buckets and ECR repositories.
  The shared Terraform module defaults to protected behavior for staging and
  production. Production teardown remains disabled.
- OpenTofu creates and manages cluster secret containers. Cluster tasks
  publish values to their ARN and retrieve them by that ARN. Protected secrets
  retain a 30-day recovery window. Unique names allow redeploy while deletion
  is pending. Disposable secrets have no recovery window.
- The helper discovers remaining state, checks account and storage ownership,
  and verifies each refreshed destroy plan against its approved scope. A
  populated resource without force settings blocks before node shutdown.
  Protected plans reject force settings even if the corresponding storage is
  currently empty. No external S3, ECR or Secrets Manager deletion is needed.
- Require the typed environment name for interactive approval. A separate
  teardown auto-approval setting is available for explicitly disposable
  sandboxes. Deployment auto-approval cannot approve teardown.
- Retain the shared GitHub stack and Bootstrap, including state history and
  the lock table. Bootstrap has lifecycle guards. Environment teardown cannot
  authorize destruction of configured backend buckets or lock tables.
- Report observed node states and the active phase. Replan on retryable
  dependency errors and report completion only after checking remaining state.

The automated suite exercises the rendered Task flow on an interrupted
disposable teardown, a protected teardown with populated storage, shared
resources, separate approval, versioned S3 blockers, and error diagnostics.
Native OpenTofu plans with a mocked AWS provider validate rendered policy
settings. The earlier v1.18.2 AWS sandbox smoke exercised the superseded
external cleanup approach. A fresh disposable AWS deployment with the revised
policy is the outstanding live acceptance check.
