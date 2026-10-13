# Nightly dependency pin updates

**Status:** Approved for implementation by the 2026-10-13 handoff. The earlier
uncommitted implementation was audited and revised against this design.

**Issue:** [getscaf/sfu-fullstack-template#196](https://github.com/getscaf/sfu-fullstack-template/issues/196)

**Branch:** `abosio/196/ci-for-pinning`

## Problem and intended result

Bootstrap currently discovers Node's LTS major, compiles Python requirements
from the package index, and installs frontend dependencies without a committed
lockfile. The same template revision can therefore generate different
dependency sets on different days.

New projects should inherit explicit runtime versions and committed package
pins from the template revision they use. Four independent nightly PR streams
should refresh those pins. Each PR should be validated and merged through
normal branch protections. Failed updates should remain available for
investigation and trigger a Slack alert.

This supersedes the weekly cadence and separate bootstrap-artifact fetching
described in the existing pinning ADR proposal. The template itself will carry
the locks; bootstrap needs no separate artifact service.

## Scope

- Pin Python and Node to full stable versions used by Docker and CI.
- Commit complete Python requirement locks, including transitive dependencies
  and installation/build tools.
- Commit frontend `package-lock.json` and use `npm ci` for ordinary installs.
- Stop discovering runtime versions and regenerating locks during bootstrap.
- Preserve optional Celery, Sentry, frontend, and mail-provider choices.
- Add nightly updates, PR reuse, validation, protected auto-merge, and Slack
  failure alerts.
- Retain scheduled Test template failure alerts and remove success alerts.
- Document workflow setup and manual dependency updates.

Apt packages, other Kubernetes images, Nix package versions, and release tooling
are outside the proposed package pinning scope. Runtime tags include a Debian
distribution to avoid silently changing the base distribution. Image digests
and package hash enforcement are not part of the proposed version-pin policy.

## Approaches considered

1. **Repository-owned scripts and GitHub Actions — proposed.** These can render
   Copier variants, resolve their Python locks together, and implement the four
   PR streams and alert requirements. The scripts need regression tests.
2. **Dependabot.** Suitable for conventional manifests; additional generation
   would still be needed for conditional locks and bootstrap runtime consumers.
3. **Renovate.** Custom managers could discover runtime and manifest changes,
   but conditional lock generation and failure reporting still need integration.

## Pinning and update policy

| Stream | Version policy | Files owned by the stream |
| --- | --- | --- |
| Frontend runtime | Highest stable LTS Node version, including patch | Frontend Dockerfile, `.node-version`, Node reference in Bitbucket CI, Node major attribute in `flake.nix` |
| Backend runtime | Latest stable patch within the existing Python minor and Debian distribution | Backend Dockerfile, `.python-version`, Python reference in Bitbucket CI |
| Python packages | Highest stable compatible resolution of existing `.in` declarations | `backend/requirements/{base,local,production,tests,build}.txt` |
| Frontend packages | Highest compatible resolution of `package.json`, including transitive packages | `frontend/package-lock.json` |

Python minor upgrades remain deliberate maintainer changes. Node follows the
existing active-LTS policy. Prereleases are excluded. Existing source
constraints, including the PyCharm debugger pin and Apollo compatibility range,
remain authoritative. An unresolvable source declaration fails its stream
instead of overriding its constraint.

Manifests remain editable declarations; generated locks supply exact installed
versions. Both runtime streams touch Bitbucket CI, but each changes only its
own runtime reference. Required up-to-date-branch rules may defer the second
merge until the next refresh when both PRs overlap.

## Generated project behavior

`template/.python-version` and `template/.node-version` carry exact versions.
Dockerfiles carry matching image tags. Generated GitHub workflows read the
version files, and generated Make targets derive images from the Dockerfiles.

Copier renders committed requirement locks and the npm lockfile. Bootstrap may
install packages and create a development cluster, but it does not discover
newer versions or regenerate locks. The online Node-resolution task is removed.
Initial frontend installation, Docker builds, and frontend checks use `npm ci`.

`make compile` and `make compile-frontend` remain explicit maintainer commands
for changing a generated project's dependencies. Neither runs as an implicit
prerequisite or bootstrap task.

## Python lock generation

The updater evaluates 24 combinations of three boolean options (Celery, Sentry,
frontend) and three mail-service values to generate and validate one shared
compatible version set. This is a coverage technique, not 24 separate version
sets or a requirement for users to maintain 24 projects. The updater will:

1. Render every `.in` file for every configuration into a temporary directory.
2. Resolve their combined declarations into compatible exact constraints for
   the pinned Python version on Linux, the Docker target.
3. Resolve each requirement role and configuration against those constraints.
4. Factor identical dependency lines into common and conditional Jinja blocks.
5. Write the five `.txt` templates only after every resolution succeeds.

All roles share compatible versions. Optional dependencies and their
transitive requirements appear only where needed. Output is deterministic and
contains no timestamps or temporary paths. Copier renders these templates into
ordinary pinned requirement files.

Validation re-resolves source declarations against committed pins for all 24
configurations and compares the result with the locks. Missing transitive
packages, incompatible pins, and stale source/lock combinations fail the check.

## Frontend lock generation

The updater resolves `package.json` in a fresh temporary directory with
`npm install --package-lock-only --ignore-scripts`. Starting without the old
lock refreshes transitive packages; lifecycle scripts do not run during
resolution. The updater restores the Copier project-name expression in both
lockfile root locations and leaves `package.json` unchanged.

A generated project must successfully run `npm ci` with its rendered manifest
and lockfile, then pass existing frontend lint, typecheck, and tests.

## Nightly PR lifecycle

The workflow runs daily at 03:00 UTC and supports manual dispatch against the
default branch. Four matrix jobs use `fail-fast: false`. Whole-workflow
concurrency prevents overlapping runs from updating the same branches.

Each stream checks out the default branch, resolves its pins, and creates or
updates `automation/dependencies/<stream>`. A fixed branch identifies its one
open PR. Only declared stream files are committed. No diff means no new PR;
existing failing PRs are refreshed through the same branch.

PR creation precedes validation so a validation failure leaves a reviewable PR.
A dedicated update token causes ordinary PR checks to run unattended. Test
template renders the checked-out commit instead of fetching a separately named
remote branch.

The merge gate waits for `test-template`, `dependency-tests`, and other reported
checks on the expected PR head. Missing or pending checks keep it waiting.
Failed, skipped, cancelled, or timed-out checks fail the stream. A changed head
aborts the attempt so earlier results cannot authorize another commit.

After validation, the gate requests `gh pr merge --auto --squash` with
`--match-head-commit`. It never uses administrator bypass. GitHub enforces
required reviews, checks, merge queues, and other protections. Waiting for a
required review is an expected deferred merge. Check polling has a finite
timeout; failure to request auto-merge is a workflow failure.

## Failure reporting and configuration

A separate notification job runs after all matrix jobs, including failure or
cancellation. A failure during checkout, setup, resolution, PR creation/update,
validation, or the merge request sends a Slack alert with the repository and
workflow-run URL. Successful runs send no alert. Test template retains its
scheduled-failure alert and removes its success alert.

Required setup:

- `DEPENDENCY_UPDATE_TOKEN` in the existing `dev` environment: a dedicated
  fine-grained token scoped to this repository with Contents and Pull requests
  write access and access to read checks/statuses. Its identity must not bypass
  protection rules. Ordinary workflow token permissions remain read-only.
- `SLACK_WEBHOOK_URL` in `dev`, following the existing incoming-webhook setup.
- Repository auto-merge and squash merging enabled.
- Required checks for Test template and Dependency tests, together with
  existing required checks and review rules.
- An environment configuration compatible with unattended scheduled jobs.

## Validation and acceptance

| Acceptance criterion | Required evidence |
| --- | --- |
| Explicit Python and Node | Rendered Dockerfiles and CI consumers agree with version files |
| Fully pinned Python | Exact pins; all 24 configurations resolve without adding missing packages |
| Reproducible frontend installs | Rendered manifest and lock agree; `npm ci` succeeds |
| Four independent streams | Four matrix entries, explicit file ownership, `fail-fast: false` |
| Reusable PRs | Deterministic branches and create/update action behavior |
| Failed PR remains open | PR precedes validation; failure prevents merge |
| Protected automatic merge | Successful checks, unchanged head, protected auto-merge request |
| Nightly failure alerts | Failure/cancellation notification includes repository and run URL |
| Test template failure-only alerts | Success alert removed; scheduled-failure condition retained |
| Documentation | Maintainer guide, generated-project update docs, corrected ADR proposal |

Local verification covers unit tests, workflow lint, Copier rendering, all
Python lock configurations, frontend checks, and Docker builds where feasible.
PR reuse, protection enforcement, and Slack delivery require a configured
GitHub Actions run and cannot be demonstrated by local tests.

At spec-writing time, nine updater unit tests passed, Python locks resolved for
all 24 configurations, three representative projects rendered, and the default
frontend's locked packages installed. Frontend checks, Docker builds, workflow
lint, operational docs, and lifecycle integration validation remain outstanding.
