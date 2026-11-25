# Environment teardown implementation plan

Status: Implemented; core AWS recovery smoke passed, with additional scenarios and a bootstrap-credential cleanup follow-up recorded below. Updated: 2026-11-24.

Issue: [#227 — Fix S3/ECR cleanup and make environment teardown resumable](https://github.com/getscaf/sfu-fullstack-template/issues/227).

Fix the generated teardown command so it cleans populated AWS resources and can finish after a previous attempt deleted only part of an environment. An existing generated project must be able to receive the update and rerun `task teardown-sandbox` without a prerequisite normal apply, redeployment, manual AWS deletion, or state edits, provided required infrastructure state remains accessible and ownership of resources selected for deletion is unambiguous. Preserve and explicitly report legacy secrets whose ownership cannot be established; they do not block infrastructure destruction.

Implement the two behaviors together: cleaning non-empty S3/ECR resources and resuming the existing teardown workflow. Keep the change within the fullstack template and its tests/documentation; the `scaf` CLI does not need to change.

## Scope

| Required for this fix | Outside this fix |
| --- | --- |
| Application S3 cleanup, including versions and delete markers | Changing bucket versioning, storage architecture, or application behavior |
| ECR deletion that works with existing state | Renaming ECR repositories or moving them between states |
| Repeated execution after a partial destroy | Repairing arbitrary lost/corrupt state or importing resources automatically |
| Ownership checks before deletion; preserve shared infrastructure | Redesigning infrastructure ownership across environments |
| Correct secret-task dispatch and protection of ambiguous legacy secrets | Renaming or migrating existing Talos secrets; unrelated bootstrap-task cleanup |
| One explicit teardown confirmation and clear failure/completion results | Enabling production teardown or redesigning deployment tasks |
| Automated retry tests and one disposable AWS acceptance scenario | A general infrastructure orchestration framework or a broad deployment test platform |

Preserve the current public command names. Keep production teardown disabled. Normalize `production` to the `prod` Terraform directory inside the teardown helper, without changing backend keys or deployment behavior.

Keep a review finding in this issue when it is necessary to select the correct resources, avoid deleting another environment's data, or retry the supported teardown command. A broader repair to resource naming or provisioning belongs in a follow-up. Protect existing resources here even when their structural correction is deferred.

## Existing behavior and constraints

- `template/terraform/modules/base/s3.tf` enables versioning on `static_storage`. Existing cleanup only targets the Terraform state bucket. Application media and static assets share `static-storage`; `backups` can also prevent destruction once populated.
- `template/Taskfile.yml` has an ECR deletion prompt already. Its image deletion depends on root outputs, discards per-image failure results, and does not verify emptiness. The new workflow replaces that teardown path rather than adding a second cleanup system beside it.
- A partially completed destroy may remove outputs before the next attempt. Resource discovery must use state resource records, not outputs or reconstructed resource names.
- ECR defaults use sandbox names in every environment. This establishes a collision risk, not proof that a particular repository is shared. Compare actual account/region/resource identifiers before deleting anything.
- Backend keys differ: sandbox/prod use the project slug, while staging uses the project dash. Read configured backend identities; do not derive keys from a naming convention or change them in this fix.
- The GitHub role and state bucket/DynamoDB backend are shared. Environment configuration reads the GitHub role as a data source, and GitHub configuration invokes `gh api`. Destroy planning can therefore depend on resources and credentials outside the selected environment.
- The GitHub OIDC provider can also be shared across projects in the same AWS account: IAM requires a unique provider URL per account, and deleting a provider breaks role assumption for roles that still trust it. The project that first created it may manage the provider in its GitHub state while later projects only read it. Protect this account-level dependency before deleting a GitHub stack. See [AWS provider constraints](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_providers_create_oidc.html) and [provider deletion behavior](https://docs.aws.amazon.com/IAM/latest/APIReference/API_DeleteOpenIDConnectProvider.html).
- Bootstrap uses local state. Its files are ignored by Git and are not guaranteed to exist on another machine. The current template has `force_destroy = true`, but that setting was added in [#124](https://github.com/getscaf/sfu-fullstack-template/pull/124) ([commit 593f569](https://github.com/getscaf/sfu-fullstack-template/commit/593f569252d543d86b0241e511fe94fb100738e0)) on 2025-07-24. Older projects that have not applied that setting can still have it disabled in state. Bootstrap cleanup must work with either value, without a prerequisite apply.
- Talos uses unscoped legacy secret names such as `sandbox_kubeconfig`. Dispatching to its existing deletion task without ownership checks could delete another project's secret.

## Implementation structure

Add a small Python helper under `template/terraform/scripts/teardown.py`. Use the Python standard library and existing `aws`/`tofu` CLIs. Support Python 3.9 and later. Nix supplies Python in the generated development shell; other users need a compatible host interpreter. The Taskfile must check that `python3` exists and is at least 3.9 before invoking the helper, with a clear error if not. Test the helper on an actual 3.9 interpreter, not only with a syntax check. Do not introduce a package dependency, a generic workflow engine, or a new user-facing recovery command.

Keep Taskfiles as thin entry points for authentication and the existing environment selection. Keep the patch to existing Taskfiles concentrated in the teardown task bodies and their direct cleanup adapters. Put resource discovery, error classification, confirmation, sequencing, and bounded retry logic in the helper so the real flow can be exercised by tests. Do not require newly introduced Taskfile variables that older projects lack; resolve necessary identities from their existing backend/configuration files and initialized backend metadata.

Read JSON state snapshots into memory. Use the selected stack's initialized backend and the actual configured state locations for cross-environment checks. Support the generated configuration's literal backend settings and honor initialized backend overrides where present; reject settings that cannot be resolved reliably. Read other environments' state objects directly from S3 through the AWS CLI and parse their JSON in memory. Do not run `tofu init` or validate unrelated environment modules merely to inspect their state.

Resolve the application region from the generated `global_variables` module's `aws_region` output. Secret discovery/deletion and resource-region fallbacks use that region; backend bucket and lock-table operations use the configured backend region. Backend overrides must not redirect application secret cleanup to a same-named secret in another region.

Literal lookup ignores HCL comments, quoted decoys and heredoc bodies. Ambiguous blocks/attributes, unterminated syntax and quoted template expressions requiring a full HCL parser fail before discovery or deletion; the helper does not evaluate HCL expressions.

Do not dump state, credentials, private keys, or raw subprocess payloads into console logs or repository files. Log resource addresses, identifiers, phase names, and useful error codes. Temporary request payloads, if required, must use a private temporary directory and be removed after use.

For long-running OpenTofu operations, display a filtered JSON UI stream containing resource progress, elapsed time, and safe diagnostic summaries/locations. Ignore output values, provisioner logs, arbitrary diagnostic detail, and expression snippets; `state pull` and `show -json` remain private. Emit a 15-second heartbeat during quiet periods so slow CloudFront deletion is visibly running.

## Workflow

### 1. Inspect and validate before AWS mutations

Resolve the selected environment, AWS account/region, relevant backend locations, and current managed resources. Check backend availability before initializing a remote-backed stack: if the bucket is confirmed absent, enter the local-bootstrap recovery/no-op checks in step 7 instead of failing at remote initialization. Otherwise initialize the selected OpenTofu stack as needed. Distinguish an absent state object from denied access, invalid credentials, malformed state, or a connection failure.

An available remote backend is sufficient to inspect and destroy the selected environment. If local bootstrap state is absent or valid but does not track live backend resources, retain bootstrap and continue with the environment and, if safe, GitHub. Do not turn this into a blanket retention of GitHub or a prerequisite for environment cleanup. Corrupt/mismatched local state remains an error; an absent remote backend still requires the original local state for recovery.

Recovery also inspects independently accessible configured backends using the same regional lock table, including additional workspace keys in those buckets. Active or unclassified dependent state retains bootstrap; unreadable dependent state stops recovery. A missing selected bucket alone does not authorize deleting a lock table used from another bucket. Normal teardown and recovery share the same backend inspection routine.

Inspect other configured environment states and any additional state/workspace entries in the shared backend before deciding that shared resources can be removed. An unreadable or unclassified state cannot establish that shared infrastructure is unused. A confirmed absent state object is different from an inaccessible one.

Compare selected ECR repository identifiers and generated application bucket identifiers with other environment states. If the same repository or application bucket is managed elsewhere, stop before node shutdown or deletion with a specific ownership-conflict error. If another state cannot be read and storage ownership therefore cannot be established, also stop before deletion. Skipping only the helper deletion is insufficient because the subsequent Terraform destroy could still delete the resource. Resolving overlapping ownership is a separate migration.

If only shared GitHub/bootstrap infrastructure is in use elsewhere, allow the selected environment teardown to proceed and retain those shared stacks. Retention with continued environment cleanup also applies when state is readable and deletion ownership is established, but shared-stack usage cannot be classified conclusively. An unreadable state that prevents ownership checks follows the stop rule above, not this retention case. Report what was retained and why; do not report a complete full-stack teardown.

If a GitHub stack scheduled for deletion manages the GitHub OIDC provider, inspect all pages of the account's IAM role trust policies for references to that exact provider ARN. Exclude only role identities managed by the GitHub stack being deleted. A reference from any other role means the whole GitHub stack and its state backend must be retained; a warning alone does not permit deletion. Lookup/permission errors remain preflight failures, not proof that the provider is unused. Limit this to the provider-deletion guard; do not add a general IAM dependency scanner, split the GitHub state, or use forget/state-removal operations. Skip this check when the provider is only a data source or the GitHub stack is already retained.

Validate dependencies for the phases that actually remain. When GitHub destruction is needed, verify the configured repository lookup and required metadata, not just `gh auth status`. Do not require GitHub access when that phase is already complete or will be retained.

Create and inspect preliminary destroy plans for the remaining stacks scheduled for deletion before mutating AWS. This catches current data-source/configuration failures early. These plans are for preflight review; they will not be applied after external cleanup changes AWS state.

### 2. Confirm the complete operation once

Display the account, region, environment, all infrastructure selected for destruction, and shared stacks that will be deleted or retained. Define the approved infrastructure scope as every managed resource address and identity present in the state of each stack approved for destruction, including CloudFront, network, and bootstrap resources, not just the S3/ECR cleanup targets. Scope addresses by stack/backend identity so identical addresses in different stacks cannot be confused. Include exact identifiers for secrets selected outside Terraform state. Explicitly state that sandbox media, backup contents, and container images will be permanently removed, and identify unverified legacy secrets that will be retained.

Require one confirmation before stopping nodes, deleting secrets, emptying buckets, or deleting repositories. `TERRAFORM_AUTO_APPROVE=1` explicitly accepts the entire displayed teardown scope; document that meaning. Task's `--yes` flag alone must not silently bypass the helper's confirmation.

After confirmation, fresh plans for the same approved scope do not need another interactive prompt. A fresh plan may delete only a subset of the approved managed addresses with matching resource identities; resources already removed by external cleanup may disappear from it. Allow managed-resource `delete` and `no-op` actions and data-source reads; reject managed-resource create, update, replacement, forget, or any deletion outside the approved set. Output changes are not managed-resource mutations. If interrupted, recompute the scope and confirm again on the next invocation. Do not automatically restart stopped nodes after a failure; report their status and the failed phase.

### 3. Stop remaining application writers

Use EC2 instance identifiers from the selected environment state to stop surviving application/backup nodes. Wait for the stopped state with a finite timeout. Treat already stopped, terminated, or confirmed absent instances appropriately. Do not depend on a working Kubernetes API.

This prevents template-managed application and backup processes from repopulating S3 during cleanup. Concurrent deploys and external writers must be stopped during teardown; do not build a distributed deployment-locking system in this fix. If storage continues to refill, fail clearly rather than looping indefinitely.

### 4. Clean application storage and ECR

External S3 emptying is limited to `module.cluster.aws_s3_bucket.static_storage` and `module.cluster.aws_s3_bucket.backups`, using their actual state identifiers. Custom buckets retain their Terraform deletion policy; inclusion in an approved destroy plan does not authorize bypassing `force_destroy = false` by emptying them externally.

For the selected state's application buckets (`static_storage` and `backups`), remove current objects, all object versions, and delete markers. Handle unversioned as well as versioned/suspended buckets. Paginate listing results, respect the 1,000-entry delete limit, inspect per-object errors, and verify emptiness. A missing bucket is complete; access denial is an error. Do not change application buckets to unconditional `force_destroy`.

For repositories whose ownership was validated, call ECR forced repository deletion and verify the result. Treat `RepositoryNotFoundException` as complete. Let AWS remove image/manifest contents rather than maintaining a second image-by-image deletion algorithm. Do not add unconditional `repository_force_delete` settings as a parallel fix: existing state must already work with this path.

Retry only classified transient failures with finite limits. Classify actual API error codes in every blocking diagnostic, not arbitrary keyword occurrences anywhere in stderr. If any blocking error is permanent or unclassified, do not retry. Real authorization errors and unsupported resource protection must stop the phase with a useful message.

### 5. Handle secrets without broadening ownership

Use the selected cluster OS rather than the current hardcoded k3s task. Preserve existing scoped k3s secret identifiers. A confirmed absent secret is already complete; other API errors remain visible.

For legacy Talos names, delete only when ownership is established, for example by trustworthy matching resource tags or an existing project-specific association. A generic environment-only name is insufficient. Existing untagged Talos secrets must not prevent infrastructure destruction: preserve any secret whose ownership is ambiguous, show it as retained during preflight, and include its identifier and reason in the final result. Do not add mandatory endpoint/content matching or a secret-naming migration in this fix.

Distinguish uncertain ownership after a successful lookup from failed discovery. Secret discovery or deletion errors such as access denial, expired credentials, and connectivity failures must remain explicit nonzero failures; never reinterpret them as an absent or unowned secret. A successful run with retained secrets must say that infrastructure teardown completed with the listed legacy secrets preserved, rather than claiming that every project-related object was deleted.

### 6. Destroy and verify the environment

After external cleanup, create a fresh destroy plan and apply it within the approved scope. Never apply the preliminary plan or a previous run's saved plan. OpenTofu must refresh the ECR repository, its lifecycle/policy resources, and other resources already deleted from AWS.

Do not remove state bindings merely to make the command pass. If destroy fails, preserve the backend and stop subsequent deletion phases. A retry reads current state and acts only on the resources that remain.

Treat the ELB ENI message separately from a failed load balancer deletion. Verify ownership/status before remediation. Do not add force-detach operations or infer missing IAM permissions from the warning alone. Allow bounded waiting/replanning for confirmed transient network dependency failures. Do not blanket-retry every failed destroy or hide unresolved dependencies.

Label JSON diagnostics explicitly as warnings or errors. Map the known dynamic ELB ENI warning summary to fixed safe text explaining that remaining managed resources will be checked before completion. Do not print its raw summary/detail or describe it as proven harmless. Preserve the provider's severity, process exit status, and error-only retry classification; an actual error must never be relabeled as a warning.

Use 30/60/120-second backoff before new destroy plans, with no further retries started after a 300-second window measured from the first failure. Include later attempt durations when deciding whether another retry may start. Preserve the in-flight provider operation's own timeout rather than killing it mid-delete when the retry window expires. Test schedules and mixed-error behavior with a fake clock so CI does not sleep for minutes.

### 7. Finalize shared resources last

Once environment destruction is verified, remove the GitHub stack only if no other environment needs it and its managed OIDC provider has no role references outside that stack. If the GitHub stack is retained for another project, retain its backend as well. Otherwise verify that all state stacks using the backend have no remaining managed resources before deleting bootstrap infrastructure.

Removing bootstrap additionally requires valid matching local bootstrap state that tracks its live resources. When the backend exists but this local state is missing/incomplete, preserve bootstrap and its remote state without blocking environment/GitHub cleanup. Return exit code 0 with an explicit qualified completion message; do not claim full project deletion. Do not require additional bootstrap-only inspection permissions for a stack already retained for missing local state.

Replace the old inline state-bucket cleanup with the same paginated, error-checked S3 routine used for application buckets. Empty the state bucket only after all dependent stacks have been verified empty and no other environment needs the backend. Then generate a fresh bootstrap destroy plan and apply it. This must work when bootstrap state has `force_destroy = false`; neither changing that setting nor a normal apply is required. Retire the unsafe standalone state-bucket cleaning entry point from the documented workflow; keep no shortcut that erases active remote states without these checks.

If the backend bucket is already deleted but DynamoDB or other bootstrap resources remain, use the existing local bootstrap state to discover and finish only those remaining resources. Validate the configured AWS account, region, and backend identities before acting. Do not require an additional teardown checkpoint file or change deployment entry points to invalidate one.

Define a completed-teardown no-op as follows: a valid local bootstrap state file exists and contains no managed resources, the caller's AWS account matches configuration, and the configured backend bucket and DynamoDB table are both confirmed absent in the expected region. Do not create an empty local state file merely to satisfy this check. Report retained legacy secrets separately when present.

If the backend is gone and local bootstrap state is missing, unreadable, or inconsistent, return a clear nonzero recovery error. Bucket absence does not prove that environment resources were deleted; local bootstrap state only tracks bootstrap resources. Resuming the normal teardown sequence does not provide automatic recovery of arbitrary lost environment state or a guarantee that unrelated/orphaned cloud resources have been discovered. Do not guess ownership, recreate the backend, or auto-import resources. Cross-machine recovery after loss of all state is outside the one-command guarantee.

## Repeatability contract

| Observed condition | Required behavior |
| --- | --- |
| Resource exists and is approved for this environment | Perform its remaining cleanup/deletion |
| Resource is confirmed absent | Continue without treating absence as failure |
| Node stopped, bucket empty, or phase verifiably complete | Skip the unnecessary operation |
| Outputs missing but managed-resource state is available | Discover resources from state and continue |
| Other environment uses GitHub/bootstrap | Retain shared infrastructure and explain the result |
| Remote backend available but local bootstrap state missing or valid/incomplete | Complete environment/GitHub cleanup when safe, retain bootstrap, and report qualified success with exit code 0 |
| Role outside the approved GitHub stack trusts its managed OIDC provider | Retain the GitHub stack and backend; complete only the selected environment teardown |
| ECR ownership overlaps | Stop before destructive work |
| Legacy secret lookup succeeds but ownership is ambiguous | Preserve and report the secret; continue infrastructure teardown |
| Credentials, permissions, connectivity, or state inspection fail | Return nonzero; do not reinterpret as absence |
| Confirmed transient dependency cleanup | Retry with a finite deadline and fresh plans where needed |
| Bootstrap partially deleted with valid local bootstrap state | Validate account/backend identities and finish remaining bootstrap resources |
| Backend gone and local bootstrap state missing, unreadable, or inconsistent | Return a clear recovery error; do not return a successful no-op |
| Valid local bootstrap state has no managed resources, account matches, and configured backend bucket/table are absent | Return a successful no-op for the known teardown scope; report retained legacy secrets separately |

## Work units and affected files

1. **Discovery and preflight:** implement Python runtime checks, helper state/backend inspection, account validation, ownership checks, and confirmation of the full managed-resource scope. Add focused unit tests for error classification and resource selection.
2. **Cleanup and sequencing:** implement node stopping, S3 cleanup, ECR deletion, and guarded secret handling. Wire the root and Terraform Taskfiles to the helper; remove duplicate inline teardown cleanup.
3. **Destroy and finalization:** implement fresh plans, bounded dependency handling, shared-stack retention, bootstrap recovery, and accurate final messages. Keep state available until all dependent phases finish.
4. **Regression coverage and documentation:** exercise rendered commands, integrate tests into the existing CI job, and document updating an existing project and rerunning the same command.

Deliver these work units in one PR with focused commits so cleanup and retry support ship together. They are implementation/review groupings, not separate releases.

Expected files are `template/Taskfile.yml`, `template/terraform/Taskfile.yml`, the new helper, narrowly required bootstrap Taskfile adapters, generated teardown documentation, `tests/test_teardown.py` with fixtures/helpers, and `.github/workflows/dependency-tests.yaml` for the pinned Task executable and Python 3.9 compatibility check. Avoid changes to application code, deployment sequencing, ECR names, backend keys, storage architecture, or the `scaf` CLI.

## Updating an existing generated project

Document a targeted file update as the recovery path; do not require a full `scaf`/Copier update or rerun bootstrap hooks. Render the fixed template revision into a separate temporary directory using the project's saved Copier answers with generation tasks disabled. Preserve those saved answers and use the fixed revision's defaults for newly introduced unanswered questions (`--defaults`); do not prompt for or change existing project identities. The release instructions must provide the exact tested render command and fixed revision, rather than asking users to copy unrendered Jinja template files.

Transfer only the new helper and the relevant rendered teardown changes in the root/terraform Taskfiles and any required cluster-OS adapters. For customized Taskfiles, apply those changes as a reviewed merge that preserves project variables, authentication, and unrelated tasks; do not overwrite whole Taskfiles blindly. List the precise files/hunks in the update instructions. Preserve existing state, `.terraform` directories, credentials, backend configuration, and Copier answers. Keep the helper path consistent with the merged task calls.

After the file update, run `task teardown-sandbox` from the existing project. No normal apply, regeneration in place, infrastructure initialization hooks, or resource recreation is part of the update. The old-project retry test must exercise this same transfer/merge procedure, including a customized Taskfile case.

## Follow-up candidates

These are separate work items, not prerequisites to expanding this issue into a migration project. The protective checks described above remain required here.

| Follow-up | Why it matters | Boundary in this issue |
| --- | --- | --- |
| Define ECR ownership across environments and correct the sandbox-only defaults | Different environments currently request the same repository names. A proper correction requires an ownership decision and compatibility/state-migration design. | Detect overlapping ownership before any destructive step and stop with an actionable error; do not rename or transfer repositories. |
| Give Talos secrets project-scoped names with a migration for legacy installations | Environment-only secret names can collide across projects in the same AWS account. Provisioning, fetching, and deletion must eventually use one consistent scheme. | Preserve and report ambiguous legacy secrets while continuing infrastructure teardown; do not rename secrets or add a provisioning migration. |
| Define account-level ownership and lifecycle for the shared GitHub OIDC provider | The first project can manage a provider subsequently used by other projects, making project teardown an account-wide authentication risk. | Check external role references and retain the whole GitHub stack/backend when in use; no state migration or IAM ownership redesign here. |
| Clean project-scoped ArgoCD bootstrap credentials after teardown | The AWS smoke audit found two SSM deploy-key parameters and the corresponding GitHub deploy key remaining after successful infrastructure deletion. These are created by bootstrap tasks outside Terraform. | Record this existing cleanup gap separately; a follow-up should establish ownership and include the exact parameter/key identities in the approved scope before deletion. |

Do not create standalone work for every incidental inconsistency. Unrelated `reset-config` aliases and production deployment-path repairs do not block this teardown fix; handle them separately when their workflows are addressed.

## Verification

Use the repository's existing `unittest` and generated-project helpers; do not add pytest or a new test runner. Fake `aws`, `tofu`, and `gh` commands must share a persistent JSON scenario store across invocations and record sanitized operations. Strip real credentials from the test environment and ensure no unexpected command can fall through to a real service.

Run the actual rendered `task teardown-sandbox` entry point against those fakes, including the authentication wrapper, helper, and phase ordering. The main regression starts with pre-fix state, including a pre-#124 bootstrap snapshot with `force_destroy = false` and ECR forced deletion not enabled, lets a run fail after partial deletion, installs the updated rendered files through the documented targeted update without running generation hooks or normal apply, and reruns the same command. Assert final resource state and preservation of resources outside scope, not just printed messages.

| Scenario | Required assertion |
| --- | --- |
| Old populated installation, partial failure, then updated files and retry | Same public command completes without normal apply, recreation, state edits, or manual deletion |
| Pre-#124 bootstrap state with `force_destroy = false` | After dependent stacks are verified empty, the helper empties the versioned state bucket and bootstrap destruction succeeds without first persisting a new setting |
| Customized Taskfile receives the documented targeted update | Existing customizations survive and the merged entry point invokes the new helper correctly |
| Python missing, below 3.9, and actual Python 3.9 | Clear preflight error before destructive work for unsupported/missing interpreters; helper behavior works on 3.9 |
| Missing outputs and some already deleted resources | Remaining resources are still found; prior deletions are tolerated |
| Available remote backend without local bootstrap state | Environment and eligible GitHub resources are removed; bucket/table/state remain; exit code 0 clearly reports retained bootstrap |
| More than 1,000 S3 versions/markers, multiple listing pages, unversioned backups | Complete deletion within API limits and explicit detection of per-object errors |
| Populated ECR, manifest content, or already missing repository | Correct forced deletion/absence handling and a fresh subsequent destroy plan |
| Authentication, access denial, state read, or repository lookup failure | No false absence/success; preflight failures cause no destructive calls |
| Confirmation declined or input unavailable | No node stop, secret deletion, data purge, or destroy apply |
| Explicit auto-approve versus Task's `--yes` alone | Only documented explicit approval bypasses the helper prompt |
| Fresh plan after cleanup includes approved CloudFront/VPC resources, data reads, and no-op actions | Approved deletions and harmless reads/no-ops pass; new identities, out-of-scope deletions, and managed create/update/replacement/forget actions fail |
| Long operations and failing external lookups | Resource progress arrives before the child exits, heartbeat/diagnostic context remains visible, and secret outputs/details never reach logs |
| Transient errors, mixed permanent errors, and slow retry attempts | Backoff is 30/60/120 seconds; only known transient failures retry; no new retry starts after the deadline |
| Another environment's state is active, unreadable, or has overlapping ECR ownership | Shared resources remain; conflicts stop deletion before mutation |
| Readable state has inconclusive shared-stack usage but selected deletion ownership is established | Environment teardown can proceed with shared stacks retained; an unreadable state cannot use this path |
| Managed GitHub OIDC provider is referenced by an external role, including on a later IAM listing page | GitHub stack/backend are retained; no provider deletion or forget occurs; failed role inspection stops preflight |
| Destroy fails after external cleanup | Backend survives; next invocation can continue |
| Bootstrap stops after bucket deletion but before DynamoDB deletion | Valid local bootstrap state allows completion after account/backend checks; missing, corrupt, or inconsistent state produces a clear error |
| Already completed teardown | Valid local bootstrap state has no managed resources, account matches, and configured bucket/table absence is verified; no-op needs no deleted services or irrelevant GitHub access |
| k3s and Talos secret handling | Correct adapter and missing-secret handling; ambiguous legacy Talos secrets are retained/reported without blocking infrastructure teardown; secret discovery errors remain failures |

Generate all eight combinations of Wagtail on/off, frontend present/absent, and k3s/Talos for task/helper wiring. Run the full behavioral suite on a representative sandbox project, with targeted Talos/optional-frontend cases. Exercise staging dispatch and production's disabled entry point without enabling production teardown.

Extend the existing `.github/workflows/dependency-tests.yaml` job, which already runs `python -m unittest discover -s tests -v`, to install a Task executable pinned to a validated version. Do not create a duplicate test job or silently skip the behavioral tests when Task is absent. Use that job's existing uv setup to supply an actual Python 3.9 interpreter for helper subprocess compatibility tests; the generation/test driver retains the project's configured Python version. Run the new teardown tests, template generation tests, and then the existing repository suite once. Expand testing only for demonstrated failures or compatibility concerns.

Before release, use a disposable AWS sandbox with representative static/media versions, backup objects, and ECR manifest contents. Reproduce a partial destroy, update the files, and rerun `task teardown-sandbox`. Verify that the actual provider reconciles externally deleted ECR repository/policy resources, observe real ELB/ENI cleanup, verify final resource inventory, and run the completed command again. This is the acceptance check for behavior that fake CLIs cannot establish.

## Delivery criteria

- The original S3/ECR blockers and retry behavior are delivered together.
- Existing projects receive the required Taskfiles/helper and can retry without provisioning anything first.
- Documentation distinguishes infrastructure teardown with retained shared infrastructure or unverified legacy secrets from full project teardown and from unverifiable completion.
- Old bootstrap state with `force_destroy = false` and legacy untagged Talos secrets do not require a preliminary normal apply or prevent the supported infrastructure teardown.
- Automated regression checks pass; the AWS acceptance result is recorded before claiming the runtime issue resolved.
- No resource renaming/state migration, unconditional application-data force deletion, production enablement, or unrelated infrastructure modernization is included.

## Implementation and validation results

The root teardown tasks now call `template/terraform/scripts/teardown.py` through a single Terraform Taskfile adapter. The helper discovers resources from state, confirms the full deletion scope, stops surviving nodes, cleans application S3/ECR contents, and applies fresh checked destroy plans. Shared-state/ECR/OIDC guards, retained legacy Talos secrets, old bootstrap settings, local-bootstrap recovery, and verified no-op handling are implemented. No application resource names or deployment flow were changed.

The targeted update procedure is documented in `template/docs/teardown.md`. Its regression test starts with both frozen legacy Taskfiles from commit `c4a8752`, runs the documented Copier command with saved older answers and generation hooks disabled, then merges both sets of rendered task bodies into customized root and Terraform Taskfiles and completes a previously failed destroy. CI uses the existing dependency-test job with Task 3.44.0, a pinned upstream archive SHA256 verified before extraction, and a real Python 3.9 helper compatibility run.

Local validation:

- Before the PR review loop, the teardown suite ran all 37 tests successfully, including all eight feature/OS render combinations and real Python 3.9 execution. It covered the original scenarios plus missing local bootstrap state, live structured progress, native OpenTofu JSON UI redaction, bounded retry schedules, mixed permanent errors, non-backend S3 regions, and a real two-Taskfile legacy update. Later review-loop regressions and validation are recorded in the PR's review evidence. The retry runner tests also verify that a machine resuming after the deadline does not begin another attempt.
- Warning/error regression checks cover successful teardown with an ELB ENI warning, preservation of the backend after a real apply failure alongside that warning, and error-only retry classification. The same ELB text at error severity remains an error, and neither dynamic raw summaries nor private details reach logs.
- Before this diagnostics follow-up, repository discovery ran 92 tests: 90 passed and the two existing opt-in running-service Wagtail smoke tests were skipped. Existing storage-routing and GitHub OIDC provider tests passed; lock validation covered all 48 Python feature configurations. The diagnostics follow-up reran the complete teardown suite above.
- Python formatting/import checks and Git whitespace checks passed. Helper compatibility was exercised on Python 3.9.24; the main local test driver used Python 3.13.8.

A disposable Wagtail/Next.js/k3s sandbox generated from release `v1.18.2` was provisioned for manual AWS validation in `us-east-1`. A real Wagtail image upload produced one original and two renditions in the versioned application bucket; both ECR repositories contained images. The unmodified legacy teardown reproduced `BucketNotEmpty`, `RepositoryNotEmptyException` for both repositories, and the Classic ELB ENI `AuthFailure` warning. Its remaining sandbox state contained exactly the application bucket and two ECR repositories. Both ENIs named in the warning were confirmed absent afterward.

The current working-tree template was exported to an isolated render with generation hooks skipped. Only the helper and the relevant bodies in both Taskfiles were transferred to the existing sandbox project. Existing answers, Nix pins, Terraform configuration, and local bootstrap state were preserved. A real preflight through the updated public task successfully planned deletion of the three remaining sandbox resources, one GitHub role, and three bootstrap resources without create/update actions. This first preflight was explicitly declined at confirmation. The subsequent manually approved rerun completed cleanup and deletion without a normal apply, resource recreation, or state editing; provider reconciliation after helper-driven ECR deletion therefore passed on real AWS.

The final read-only audit confirmed absence of all three buckets, both ECR repositories, Classic ELB, the instance and its root EBS volume, VPC/ENIs/security groups/subnets/routes/ACLs/internet gateway, EC2 keypair, project IAM roles/users/policies/instance profile, CloudFront distribution/OAC/OAI, ACM certificate, project DNS records, scoped Secrets Manager entries, and the DynamoDB lock table. The existing shared GitHub OIDC provider remained present. Stale tagging-catalog entries were cross-checked against service APIs and confirmed absent. Local bootstrap state contains no managed resources. A further invocation of the same public teardown command returned exit code 0 with the completed no-op message, without initialization or destruction.

Full project-artifact cleanup is not claimed: the audit found `/teardownproject/sandbox/argocd/github_deploy_key`, its `.pub` SSM parameter, and the GitHub repository's read-only deploy key remaining. Their values were not read. They are outside the current Terraform/helper cleanup scope and are recorded as the bootstrap-credential follow-up above. The GitHub repository itself was also retained.

AWS coverage limits: this sandbox used bootstrap `force_destroy = true`, had no S3 delete markers, and had an empty backup bucket. The older bootstrap setting, delete-marker cleanup, non-empty backup cleanup, and retry backoff have automated coverage; this AWS run does not validate those additional scenarios. No E2E platform was introduced.
