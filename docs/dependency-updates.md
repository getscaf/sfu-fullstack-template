# Dependency pins and nightly updates

New projects receive the runtime versions and package locks committed in the
template revision selected by Copier. Bootstrap installs those locks without
discovering newer runtimes or compiling requirements. Frontend installs use
`npm ci`; changing a dependency set is an explicit maintainer action.

## Pinning policy

| Stream | Update policy | Owned files, relative to `template/` |
| --- | --- | --- |
| `frontend-runtime` | Highest stable Node LTS full version; retain the Debian distribution | `.node-version`, `frontend/Dockerfile`, `bitbucket-pipelines.yml`, Node major in `flake.nix` |
| `backend-runtime` | Latest stable Python patch within the current minor and Debian distribution | `.python-version`, `backend/Dockerfile`, `bitbucket-pipelines.yml` |
| `python` | One compatible stable resolution of the existing `.in` declarations | `backend/requirements/{base,local,production,tests,build}.txt` |
| `frontend-packages` | Fresh compatible resolution of the current `package.json`, including transitive packages | `frontend/package-lock.json` |

The workflow's [`matrix.paths`](../.github/workflows/update-dependencies.yaml)
defines the files each stream may commit. Both runtime streams edit Bitbucket
CI, but each changes only its own runtime reference.

The version files contain full versions matching Docker and CI. Generated
GitHub workflows read those files, and generated Make targets use the images
declared in the Dockerfiles. Python minor upgrades require a coordinated manual
change. The frontend updater adjusts only the Node major attribute in Nix;
Nix packages are outside the exact runtime guarantee.

Source declarations remain authoritative. The updater preserves constraints
such as the PyCharm debugger pin in Python and the Apollo compatibility range
in `package.json`. If the declarations cannot resolve, that stream fails.
Prereleases are excluded from Python and runtime resolution.

The Python updater combines the rendered source declarations into one shared
compatible version set, then generates a complete lock for each requirement
role. Common pins and conditional optional packages are factored into the five
Copier `.txt` templates. Celery, Sentry, frontend, and mail-provider choices
therefore retain their optional dependencies and transitive requirements. The
24 configurations are a generation and validation technique for this shared
set, rather than 24 separately maintained product version sets.

`build.txt` pins installation and source-distribution build tools, including
pip, setuptools, wheel, and uv. Application installs use `--no-deps` and
`--no-build-isolation` after installing these tools, so source builds use the
committed build-tool environment. Apt packages, other Kubernetes images, Nix
package versions, image digests, package hash enforcement, and release tooling
are outside this pinning policy.

The frontend updater starts in a fresh directory without the old lock and runs
`npm install --package-lock-only --ignore-scripts`. This refreshes transitive
packages without executing package lifecycle scripts or changing
`package.json`. It restores the Copier project-name expression in the lock.

## GitHub setup

Configure the existing `dev` environment with:

- `DEPENDENCY_UPDATE_TOKEN`: a fine-grained token for a dedicated automation
  identity, scoped to this repository. Grant Contents and Pull requests write
  access and Checks and Commit statuses read access. The identity must not have
  a protection-rule bypass. Using this token allows created PRs to trigger the
  normal PR workflows; the default workflow token remains read-only.
- `SLACK_WEBHOOK_URL`: the incoming-webhook URL used for failure notifications.

Enable repository auto-merge and squash merging. Require the `test-template`
and `dependency-tests` checks alongside the repository's existing required
checks and review rules. Both workflows handle `merge_group` events for merge
queue validation. Configure the `dev` environment so scheduled jobs can run
unattended; approval requirements that stop these jobs also stop the updater
and its notification job.

## Nightly PR lifecycle

[`Nightly dependency updates`](../.github/workflows/update-dependencies.yaml)
runs daily at 03:00 UTC and accepts manual dispatch on the default branch.
Four matrix jobs run independently with `fail-fast: false`. Workflow
concurrency prevents overlapping runs from updating the same branches.

Each job starts from the default branch, resolves its stream, and creates or
updates `automation/dependencies/<group>`. The stable branch reuses the same
open PR on later runs, including a failing PR. A no-change run creates no new
PR. An unchanged existing open PR can still enter the validation gate using
the create/update action's PR number and head outputs.

PR creation happens before validation. The gate polls checks for up to 90
minutes and verifies that the PR still has the expected head commit on every
poll. It waits for both named checks and all other reported checks to succeed.
Missing or pending checks keep it waiting. Failed, skipped, cancelled,
timed-out, or other non-success conclusions fail the stream and leave the PR
open. A changed head aborts the attempt; results from an earlier commit cannot
authorize the new head.

After the checks pass, the gate requests
`gh pr merge --auto --squash --match-head-commit <sha>`. It does not request
administrator bypass. GitHub enforces required reviews, up-to-date branches,
merge queues, and other protections. A successful request may defer the merge
until a review or updated base is available. Since both runtime PRs touch
Bitbucket CI, an up-to-date-branch rule may defer one after the other merges;
the next nightly refresh updates it. Failure to request auto-merge fails the
job.

A separate notification job runs after the matrix and alerts Slack if an
update job fails or is cancelled, including failures during checkout, setup,
resolution, PR creation, check polling, or the merge request. Alerts identify
the repository and link to the workflow run. Slack delivery errors fail the
notification step (`errors: true`). Successful runs send no alert. The separate
02:00 UTC Test template schedule retains its failure alert and sends no success
alert.

## Local maintenance and validation

Run these commands from the template repository root. Select the Python
version in `template/.python-version`, then prepare an environment with the
same resolver-tool version used by the workflows:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r .github/requirements.txt uv==0.12.3
nvm install "$(cat template/.node-version)"
nvm use "$(cat template/.node-version)"
```

The examples use nvm for Node; another version manager can select the same
full version. Resolution needs network access to package indexes or runtime
release metadata. Backend runtime discovery reads Docker's official-image
metadata; validation and builds also need access to their package indexes and
container registries.

Refresh only the intended stream:

```bash
python .github/scripts/dependency_pins.py frontend-runtime
python .github/scripts/dependency_pins.py backend-runtime
python .github/scripts/dependency_pins.py python
python .github/scripts/dependency_pins.py frontend-packages
```

For a deliberate dependency change, edit `template/backend/requirements/*.in`
or `template/frontend/package.json` first, then run the corresponding updater.
Commit the declarations together with their regenerated locks. Do not edit the
generated Python pins by hand. For a deliberate runtime upgrade, coordinate
the version file, Dockerfile, Bitbucket reference, and the Node major in Nix as
applicable, then regenerate locks when the runtime change requires it.

Run the updater regression tests and validate every Python configuration:

```bash
python -m unittest discover -s tests -v
python .github/scripts/python_locks.py --check
```

The checker re-resolves declarations for the pinned Python on Linux against
the committed shared pins. It checks complete transitive dependencies,
consistent versions, extras, and source/lock agreement across all 24
configurations without writing new locks.

Render a representative project with Copier and run its existing formatting,
frontend lint/typecheck/tests, backend tests, and image builds. Include feature
combinations affected by the change. The Test template workflow renders its
checked-out commit with `--vcs-ref=HEAD` and runs formatting, frontend checks,
backend tests against PostgreSQL, and Tilt CI. Instructions for manual updates
within a generated project are in its
[`docs/development.md`](../template/docs/development.md).

## Hosted acceptance checklist

Local tests can check scripts, templates, lock resolution, and builds. A
configured GitHub Actions run is needed to verify the following behavior:

- Run on the default branch and confirm four independent streams commit only
  their declared files. Verify one failed stream does not stop the others.
- Run again with an existing PR and confirm that its branch and PR are reused.
  Verify a no-change stream creates no new PR and an unchanged existing open PR
  still reaches the check gate.
- Cause a PR check to fail and confirm the PR stays open, no merge request is
  made, and Slack receives an alert with the repository and run link. Exercise
  setup or resolution failure as well as a failed check.
- Change a PR head during polling and confirm the earlier commit's checks
  cannot authorize the replacement commit.
- Confirm missing or pending checks wait and non-success conclusions fail,
  including additional checks outside the two named required checks.
- Confirm a passing PR requests squash auto-merge without bypass. Exercise
  required reviews, an updated base, and the merge queue, verifying both
  required workflows report checks for `merge_group`.
- Confirm successful updates and successful scheduled Test template runs send
  no Slack message, while a failed scheduled Test template run still alerts.

Record the workflow-run and PR links when completing this checklist. Local
verification alone cannot demonstrate PR reuse, token permissions, protection
enforcement, merge queue behavior, or Slack delivery.
