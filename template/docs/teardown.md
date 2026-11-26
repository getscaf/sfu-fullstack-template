# Environment teardown

For a project provisioned with this template, run the task for the environment
with your project's normal AWS profile.

```bash
export AWS_PROFILE=your-project-profile
task teardown-sandbox
```

`task teardown-staging` follows the protected policy. Production teardown is
disabled. The tasks require Python 3.9+, AWS CLI v2 and OpenTofu.

## Protected environments

A sandbox or staging environment is protected by default. The task checks the
destroy plan before stopping nodes. A bucket with objects, old versions or
delete markers, or a repository with images, blocks teardown. Review and
preserve any contents you need, then arrange their cleanup separately before
rerunning the task. OpenTofu also enforces these deletion constraints when
applying the plan. Type the environment name to approve the displayed scope.
`TERRAFORM_AUTO_APPROVE=1` only applies to deployment.

The environment plan can schedule deletion of its Terraform-managed cluster
secrets with a 30-day recovery window. Cluster bootstrap writes credential
values directly to Secrets Manager. Terraform stores the secret identifiers and
deletion settings. A subsequent deployment gets new secret names while the old
secrets remain recoverable.

The cluster config fetch tasks resolve the secret ARNs from the environment's
OpenTofu outputs. On a fresh checkout, run `tofu init` in the environment's
Terraform directory with a profile that can read its remote state before
fetching the config.

## Disposable demo and E2E sandboxes

Answer yes to the disposable-sandbox question when generating a project
dedicated to a demo or E2E run. In noninteractive Copier runs the answer is
`copier__disposable_sandbox=true`. The first successful apply persists the
sandbox's S3 and ECR deletion settings and disables the cluster secrets'
recovery window. Teardown can then permanently delete the sandbox's media,
backups, container images and credentials through OpenTofu. Staging and
production keep their protected policies.

Use `TEARDOWN_AUTO_APPROVE=1 task teardown-sandbox` for unattended disposable
teardown. The task still checks the plan and storage ownership.

## Retrying

Stop concurrent deployments and external writers before running teardown.
After an interruption, resolve the reported error and rerun the same task.
It inspects the remaining state and makes a fresh destroy plan. Nodes already
stopped are reported and left stopped. The task retries recognized transient AWS
dependency errors, including delays during load-balancer cleanup. An ELB ENI
warning is informational when OpenTofu succeeds and the remaining state is
verified empty.

The project's shared GitHub stack, state bucket, state history and lock table
are retained for both policies. The state bucket and table also have
`prevent_destroy` in Bootstrap Terraform. Retiring the shared project
infrastructure is a separate operation. A saved empty environment state is
reported as already complete. A missing or unreadable state is reported as an
error.

Select the policy before provisioning. Changing the Copier answer or the
generated policy file does not update flags already stored in Terraform state.
This workflow does not include an upgrade procedure for partially destroyed
projects generated before the policy was introduced.
