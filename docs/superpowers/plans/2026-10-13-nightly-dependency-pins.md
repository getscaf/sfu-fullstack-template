# Nightly dependency pins implementation plan

**Goal:** Implement issue #196 so new projects inherit committed pins and four
independent nightly PR streams keep them current.

**Design:** [Nightly dependency pin updates](../specs/2026-10-13-nightly-dependency-pins-design.md)

**Architecture:** Python scripts resolve runtime/package pins; Copier renders
committed locks. GitHub Actions creates reusable PRs, validates their current
commits, requests protected auto-merge, and reports failures to Slack.

**Stack:** Python, Jinja2, packaging, uv, npm, Copier, GitHub CLI, GitHub Actions.

**Execution:** The 2026-10-13 handoff approves implementation on the existing
`abosio/196/ci-for-pinning` branch. The user's subsequent request authorizes
logically grouped local commits. Preserve user-owned files. Do not push,
create a PR, or change repository settings.

**Current state:** The initial draft was audited against the issue and approved
design, revised, and independently verified. Checked items now describe
verified behavior and completed local checks. Hosted lifecycle checks remain
pending in the separate remote checklist below.

## Task 1: Requirements and design review

**Files:** This plan and the linked spec; read issue #196, bootstrap files,
existing workflows, and `docs/adr/proposals/2026-04-16-version-pinning-strategy.md`.

- [x] Read the issue, repository context, and current-branch state.
- [x] Record policies, alternatives, component boundaries, and acceptance tests.
- [x] Receive implementation approval through the user's 2026-10-13 handoff.

## Task 2: Runtime selectors and consumers

**Files:** `.github/scripts/dependency_pins.py`, `tests/test_dependency_pins.py`,
`template/.{node,python}-version`, both template Dockerfiles,
`template/bitbucket-pipelines.yml`, `template/flake.nix`, generated GitHub
workflows, `copier.yml`, `template/scripts/update-node-version.sh`.

- [x] Add failing tests for numeric LTS selection, prerelease exclusion, missing
  releases, Python minor/distribution preservation, and Node consumer agreement.
- [x] Implement selectors using official Node and Docker Python release metadata.
- [x] Store exact runtime versions and update Docker/CI consumers.
- [x] Remove online Node resolution from bootstrap.
- [x] Add backend consumer coverage: both Docker stages and Bitbucket agree;
  updating Python leaves Node references unchanged.
- [x] Verify unchanged release metadata produces no file diff on a second update.
- [x] Run `python -m unittest discover -s tests -p 'test_dependency_pins.py' -v`.
  Expect consistent consumers and explicit errors for absent stable releases.

## Task 3: Complete conditional Python locks

**Files:** `.github/scripts/python_locks.py`, `tests/test_python_locks.py`,
`template/backend/requirements/build.in`, five generated requirement `.txt`
files, and `template/backend/Dockerfile`.

- [x] Add a failing test comparing factored lock rendering with expected package
  sets across all 24 configurations; reject an empty configuration set.
- [x] Implement shared constraints, per-role resolution, and conditional factoring.
- [x] Write locks only after all configurations resolve successfully.
- [x] Pin installation/build tools and generate initial locks.
- [x] Resolve committed locks for every configuration without missing packages.
- [x] Test atomic failure: seed existing locks, force a later resolver failure,
  and assert every seeded lock remains unchanged.
- [x] Test rejection of unpinned/conflicting lines and missing transitive packages.
- [x] Verify repeated generation produces identical output; investigate any
  output-file preferences or ordering drift.
- [x] Run:

  ```sh
  python -m unittest discover -s tests -p 'test_python_locks.py' -v
  python .github/scripts/python_locks.py --check
  ```

  Expect all rendered locks to be complete, exact, and compatible with the source
  declarations and the pinned Linux Python target.

## Task 4: npm lock and reproducible bootstrap

**Files:** `.github/scripts/dependency_pins.py`, frontend lock/Dockerfile,
`template/Makefile`, `template/tasks.py`, and `copier.yml`.

- [x] Resolve a fresh npm lock without lifecycle scripts or manifest changes.
- [x] Restore Copier's project name in both lockfile root locations.
- [x] Use `npm ci` for ordinary frontend installs.
- [x] Remove Python compilation from bootstrap and implicit Make prerequisites.
- [x] Keep explicit project-maintainer update targets using pinned images.
- [x] Render default/all-features/minimal projects and install default locked npm
  dependencies in a temporary project.
- [x] Test that npm resolution failure preserves the lock and manifest; verify
  Copier substitutions produce valid JSON and matching root package metadata.
- [x] Run `npm ci`, `npm run lint-src`, `npm run typecheck`, and `npm run test`
  in the rendered frontend. Expect all existing checks to pass. Investigate
  compatibility failures before choosing constraints or compatibility fixes.

## Task 5: PR check gate

**Files:** `.github/scripts/merge_dependency_pr.py`,
`tests/test_merge_dependency_pr.py`.

- [x] Add failing tests for absent, queued, failed, cancelled, timed-out, skipped,
  neutral, and successful checks.
- [x] Require template/dependency checks and successful other reported statuses.
- [x] Poll with a deadline; abort when the PR closes or its head changes.
- [x] Request protected auto-merge with the validated head SHA.
- [x] Test orchestration with changed-head, closed, merged, timeout, and successful
  PR responses. Assert only a validated current head invokes merge.
- [x] Test merge-request API failure propagation; verify no bypass flag appears.
- [x] Run `python -m unittest discover -s tests -p 'test_merge_dependency_pr.py' -v`.
  Expect unsuccessful validation to prevent the merge request.

## Task 6: Nightly workflow and alerts

**Files:** `.github/workflows/update-dependencies.yaml`,
`.github/workflows/dependency-tests.yaml`, `.github/requirements.txt`, and
`.github/workflows/test-template.yaml`.

- [x] Validate default-branch nightly/manual triggers and serialized workflow runs.
- [x] Validate four independent matrix entries, file lists, and stable PR branches.
- [x] Create/update PRs before validation using a dedicated update token.
- [x] Keep ordinary token permissions read-only and add a failure notification job.
- [x] Render local HEAD in Test template, pin its runtimes, and remove success alerts.
- [x] Add PR checks for script tests and all optional Python locks.
- [x] Run:

  ```sh
  actionlint .github/workflows/update-dependencies.yaml \
    .github/workflows/dependency-tests.yaml \
    .github/workflows/test-template.yaml
  ```

  Expect no schema, expression, or action-input errors.
- [x] Review token use, file ownership, notification conditions, and timeouts.
- [x] Verify the PR action exposes the current head SHA for unchanged existing
  dependency PRs, so they are still checked and eligible for merge.

## Task 7: Operational documentation

**Files:** `docs/dependency-updates.md`, `.github/README.md`,
`template/docs/development.md`, and the existing version-pinning ADR proposal.

- [x] Document policies, optional locks, stable branches, and manual updater commands.
- [x] Document token/webhook secrets, token access, environment requirements,
  auto-merge/squash settings, and required checks.
- [x] Explain failed PR investigation, alerts, and merges deferred by reviews
  or updated-base requirements.
- [x] Document generated-project dependency updates and correct the ADR's cadence
  and artifact delivery description.

## Task 8: Integration verification and final review

- [x] Run all updater tests and all 24 Python lock checks after the final change.
- [x] Lint all changed workflows.
- [x] Render temporary default/all-features/minimal projects from a source snapshot
  excluding ignored local files. Git-backed `--vcs-ref=HEAD` omits uncommitted
  draft changes and is appropriate only once they are committed.
- [x] Check rendered runtime/lock agreement and run frontend checks.
- [x] Build backend production and development/test images with optional features
  and the frontend image; check installed backend package compatibility.
- [x] Run existing backend tests with a temporary database where feasible.
- [x] Review every issue acceptance criterion against the finished implementation.
- [x] Run `git diff --check`; inspect the complete diff and new files.
- [x] Report verification evidence and limitations; leave changes on the current branch.

## Verified refinements from the draft audit

- Validate each Python requirement role's complete dependency closure and
  extras against one shared version set across all feature combinations;
  combining the roles could hide a missing production dependency.
- Canonicalize package names and reject conflicting pins across configurations.
  Prepare every factored template before replacing any existing lock.
- Include pip in the installation/build lock and disable isolated source
  builds during normal application installs. The CI test venv installs its
  own pinned build tools before building source packages.
- Preserve the existing Python image distribution during runtime updates.
- Install make/build tools in the slim Python Bitbucket steps. Upgrade the
  generated runtime setup actions so rendered workflow lint passes.
- Support merge-queue events for both required checks and surface Slack
  delivery failures. Explicitly list the five Python stream-owned files.
- Run backend tests in Test template against a PostgreSQL service on host
  port 15432, leaving 5432 available to Tilt. Adapt the existing GraphQL test
  to Strawberry's `assert_no_errors` API after reproducing the incompatibility.
- Exercise bootstrap feature cleanup with external commands mocked; no local
  cluster or Git commit is created by these regression tests.

## Local verification evidence — 2026-10-13

- `python -m unittest discover -s tests -v`: **37 passed**, including runtime,
  npm failure preservation, complete conditional locks, merge-gate
  orchestration, and representative Copier/bootstrap regression coverage.
- `python .github/scripts/python_locks.py --check`: **all 24 combinations
  passed**, checking all five roles and extras. Real repeated lock generation
  produced byte-identical files. These combinations cover one shared version
  set; they are not separately maintained product version sets.
- Official release metadata confirms Node **24.21.0** and Python
  **3.13.16-slim-bookworm** satisfy the approved runtime policies.
- Default, all-features, and minimal projects rendered from a source snapshot
  that excluded Git-ignored local files and included the uncommitted draft.
  Runtime consumers and npm root metadata agree; bootstrap preserves locks
  and removes disabled feature files.
- A fresh frontend resolution ran with the pinned Node image and updated
  `graphql-ws` from 6.3.0 to 6.4.0 without changing the manifest.
- Both documented generated-project manual targets, `make compile` and
  `make compile-frontend`, completed successfully in the temporary project.
- `npm ci` succeeded using the pinned Node image. Frontend lint, typecheck, and
  its existing **1 test** passed in both the rendered project and built image.
- Docker builds passed for the frontend, default backend production/test,
  all-features backend development/test, and minimal backend test images.
  Backend `pip check` passed for production, all-features, and minimal images.
- Django tests passed against an isolated temporary PostgreSQL instance:
  **15 default**, **16 all-features**, and **11 minimal**. The generated
  `CI=true make backend-test` target also passed **15 tests** in a clean pinned
  slim Python image after installing its system prerequisites.
- Actionlint passed for all three repository workflows and the changed
  rendered GitHub workflows. Generated pre-commit hooks, script Black/isort
  checks, and `git diff --check` passed. Independent spec and code-quality
  reviews found no remaining actionable gaps.
- Local Docker execution used Linux ARM64. Upstream metadata/deprecation
  warnings were observed without failing the checks. Full Test template/Tilt
  execution and the hosted lifecycle checklist below remain unexecuted locally.
- An additional `npm audit` diagnostic reports **12 high findings** stemming
  from the development-tool dependency chain through `braces` 3.0.3. Its
  [reviewed advisory](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm) lists
  no patched release. Fresh compatible resolution retains it; the updater
  keeps the existing feature declarations and does not claim audit cleanliness.
- The user requested logically grouped local commits after verification.
  No push, implementation PR, or repository-setting changes were performed.

## Remote verification after workflow configuration

These checks require configured GitHub Actions and are not part of local proof:

1. Confirm one PR per changed stream, none for unchanged streams, and reused PR
   numbers on the following run.
2. Confirm a controlled failing PR stays open while other streams finish and
   Slack receives a repository/run URL.
3. Confirm successful PRs merge only after required checks and reviews.
4. Confirm scheduled Test template success is silent and failure still alerts.
5. Confirm merge-queue commits receive both required checks and that changing
   a PR head during polling cannot authorize the replacement commit.
6. Run the complete Test template workflow, including its PostgreSQL-backed
   backend tests and Tilt CI, on the GitHub runner.
