# Environment teardown and retry

Run teardown from the generated project directory with your normal AWS profile:

```bash
export AWS_PROFILE=your-project-profile
task teardown-sandbox
```

`task teardown-staging` uses the same workflow. Production teardown remains disabled.
The helper requires `python3` 3.9 or later, AWS CLI v2, and OpenTofu. GitHub CLI
access to the configured repository is needed only when the GitHub stack will
be removed. Nix supplies these tools in the development shell; otherwise they
must be available on your host's `PATH`.

The command inspects existing state and shows the AWS account, region, resource
addresses, and shared resources it will retain. One confirmation covers stopping
nodes and permanently deleting selected media, backups, images, and infrastructure.
`TERRAFORM_AUTO_APPROVE=1 task teardown-sandbox` explicitly approves that entire
scope. Task's `--yes` flag alone does not approve it.

Stop concurrent deployments, builds, and external processes writing to the
environment before teardown. The command stops surviving application nodes
without requiring access to Kubernetes, empties S3 object versions and delete
markers, removes ECR repositories with their images, and creates fresh destroy
plans for the remaining infrastructure. When bootstrap can also be removed, it
empties the state bucket at the end, so older bootstrap state with
`force_destroy = false` is supported.
S3 cleanup processes bounded pages and resolves the next page before deleting
the current page, keeping memory independent of the total bucket size and
preserving pagination cursors. Per-object errors stop cleanup, and a final
empty pass is required before completion.

## Updating an existing project for this fix

Use a separate render and merge only the teardown changes. Do not generate over
the existing project or rerun `tasks.py`: those setup hooks can initialize new
infrastructure or change unrelated files.

From the existing project, render a checked-out fixed template revision using
your saved answers. Replace `/path/to/fixed-template` with the checkout containing
the fix; its source revision must be reviewed before running the render.

```bash
teardown_render_dir=$(mktemp -d)
copier copy --defaults --skip-tasks \
  --data-file "$PWD/.copier-answers.yml" \
  --vcs-ref=HEAD \
  /path/to/fixed-template "$teardown_render_dir/rendered"
```

Use the fixed release tag/commit instead of `HEAD` when rendering from the remote
template repository. Saved project answers take precedence; newly introduced
questions use that revision's defaults. The render does not run bootstrap hooks.

Transfer these changes together:

- Copy `terraform/scripts/teardown.py` from the render into the existing project.
- Merge the root Taskfile's `teardown-environment`, `teardown-sandbox`,
  `teardown-staging`, and retired `delete-ecr-images`/`clean-s3-bucket-only` bodies.
  Preserve your project variables, authentication task, and unrelated tasks.
- Merge `terraform/Taskfile.yml`'s new `teardown` task and legacy destruction
  adapters. Remove the old generic `destroy-terraform` path and inline
  `clean-s3-bucket` implementation. Preserve deployment tasks.

Do not copy raw Jinja files from the template repository into a generated project.
Do not overwrite `.copier-answers.yml`, backend configuration, `.terraform`
directories, local bootstrap state, credentials, or customized Taskfiles wholesale.
The helper reads the existing configuration rather than requiring new root
Taskfile variables. After merging, rerun the same command:

```bash
task teardown-sandbox
```

No normal apply, redeploy, resource renaming, or manual state edit is required.

## Retrying and interpreting results

If a run stops, fix the reported cause and rerun the same teardown command. A
new run reads current state and generates new destroy plans. Already deleted
resources and missing root outputs do not require rebuilding the environment.
Nodes stopped by an unsuccessful attempt remain stopped; they are not
automatically restarted. Keep the original local `terraform/bootstrap/terraform.tfstate`.

If the remote backend is available but local bootstrap state is missing or does
not track the live backend resources, the command still destroys the selected
environment and, when safe, the GitHub stack. It preserves the bootstrap bucket,
table, and remote state, reports the reason, and returns exit code 0 for the
completed environment teardown. A malformed or mismatched local state remains
an error. Restore the original bootstrap state on the machine used for final
backend removal; do not create an empty state or import resources automatically.

Long plan/apply operations display resource progress and elapsed time, with a
heartbeat every 15 seconds when no new event arrives. Diagnostics are labeled
`warning:` or `error:` and show safe summaries, configuration locations, and
recognized API error codes; arbitrary provider detail, expression snippets,
raw state, and output values stay hidden.
For external GitHub lookups, check the indicated configuration location and
repository/authentication access when the diagnostic identifies that failure.
ELB ENI cleanup warnings include a reminder that remaining managed resources
will be checked before completion. A warning alone does not fail teardown;
completion still requires a successful apply and verification of managed state.

Known transient dependency/throttling errors use waits of 30, 60, and 120 seconds
before fresh destroy plans. New retries stop once 300 seconds have elapsed since
the first failure. An in-flight provider operation keeps its own timeout; the
retry budget does not abruptly kill it. Mixed permanent errors, such as an
authorization failure alongside a dependency error, are not retried.

Access denial, expired credentials, malformed state, and connection failures
remain errors. They are never interpreted as proof that a resource was deleted.
Per-object S3 failures also stop teardown before the backend is removed.

If another environment needs shared infrastructure, the command destroys only
the selected environment and reports that GitHub/bootstrap resources were
retained. If an IAM role outside the GitHub stack trusts its managed GitHub OIDC
provider, that stack and its backend are retained as well. Overlapping ECR
ownership in another state stops teardown before nodes are stopped; resolve
ownership separately rather than forcing repository deletion.
Every additional backend object is inspected, including suffixless workspace
keys. An unreadable or malformed object stops teardown before mutation because
ownership cannot be established from it.

Existing untagged Talos secrets use environment-only names. They are preserved
when ownership cannot be established, and are listed in the result; infrastructure
teardown continues. Secret lookup failures remain errors. Scoped k3s secrets and
Talos secrets tagged with this application's `application` and `environment`
values are eligible for deletion. No endpoint/content guessing or secret migration
is performed.

If the backend bucket was deleted before the lock table, the command uses the
original local bootstrap state to finish that stack. A repeated completed run
is a successful no-op only when that valid local state is empty, the account
matches, and both configured backend resources are confirmed absent. When the
backend bucket is already absent, missing local state is an explicit recovery
error. Bucket absence alone does not prove that every cloud resource was deleted;
recovery of arbitrary lost state is not part of this command.

Standalone state-bucket cleaning is retired. Use the environment teardown so
active remote state cannot be erased before its resources are destroyed.
