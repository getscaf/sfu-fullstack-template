# Nightly dependency pins implementation plan

**Goal:** Implement issue #196 so new projects inherit committed pins and four
independent nightly PR streams keep them current.

**Design:** [Nightly dependency pin updates](../specs/2026-10-13-nightly-dependency-pins-design.md)

**Architecture:** Python scripts resolve runtime/package pins; Copier renders
committed locks. GitHub Actions creates reusable PRs, validates their current
commits, requests protected auto-merge, and reports failures to Slack.

**Stack:** Python, Jinja2, packaging, uv, npm, Copier, GitHub CLI, GitHub Actions.

**Execution:** Use the existing `abosio/196/ci-for-pinning` branch. Continue after
design review. Commit and push this spec and plan as requested; keep the draft
implementation uncommitted pending review. Preserve user-owned files. No
implementation PR or repository-setting changes are needed for this task.

**Current state:** Initial implementation exists because work started before
the design was documented. Checked items describe draft work already done;
they do not imply the feature is ready to merge.

## Task 1: Requirements and design review

**Files:** This plan and the linked spec; read issue #196, bootstrap files,
existing workflows, and `docs/adr/proposals/2026-04-16-version-pinning-strategy.md`.

- [x] Read the issue, repository context, and current-branch state.
- [x] Record policies, alternatives, component boundaries, and acceptance tests.
- [ ] Review the spec and plan with the user before further implementation.

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
- [ ] Add backend consumer coverage: both Docker stages and Bitbucket agree;
  updating Python leaves Node references unchanged.
- [ ] Verify unchanged release metadata produces no file diff on a second update.
- [ ] Run `python -m unittest discover -s tests -p 'test_dependency_pins.py' -v`.
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
- [ ] Test atomic failure: seed existing locks, force a later resolver failure,
  and assert every seeded lock remains unchanged.
- [ ] Test rejection of unpinned/conflicting lines and missing transitive packages.
- [ ] Verify repeated generation produces identical output; investigate any
  output-file preferences or ordering drift.
- [ ] Run:

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
- [ ] Test that npm resolution failure preserves the lock and manifest; verify
  Copier substitutions produce valid JSON and matching root package metadata.
- [ ] Run `npm ci`, `npm run lint-src`, `npm run typecheck`, and `npm run test`
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
- [ ] Test orchestration with changed-head, closed, merged, timeout, and successful
  PR responses. Assert only a validated current head invokes merge.
- [ ] Test merge-request API failure propagation; verify no bypass flag appears.
- [ ] Run `python -m unittest discover -s tests -p 'test_merge_dependency_pr.py' -v`.
  Expect unsuccessful validation to prevent the merge request.

## Task 6: Nightly workflow and alerts

**Files:** `.github/workflows/update-dependencies.yaml`,
`.github/workflows/dependency-tests.yaml`, `.github/requirements.txt`, and
`.github/workflows/test-template.yaml`.

- [x] Draft default-branch nightly/manual triggers and serialized workflow runs.
- [x] Draft four independent matrix entries, file lists, and stable PR branches.
- [x] Create/update PRs before validation using a dedicated update token.
- [x] Keep ordinary token permissions read-only and add a failure notification job.
- [x] Render local HEAD in Test template, pin its runtimes, and remove success alerts.
- [x] Add PR checks for script tests and all optional Python locks.
- [ ] Run:

  ```sh
  actionlint .github/workflows/update-dependencies.yaml \
    .github/workflows/dependency-tests.yaml \
    .github/workflows/test-template.yaml
  ```

  Expect no schema, expression, or action-input errors.
- [ ] Review token use, file ownership, notification conditions, and timeouts.
- [ ] Verify the PR action exposes the current head SHA for unchanged existing
  dependency PRs, so they are still checked and eligible for merge.

## Task 7: Operational documentation

**Files:** `docs/dependency-updates.md`, `.github/README.md`,
`template/docs/development.md`, and the existing version-pinning ADR proposal.

- [ ] Document policies, optional locks, stable branches, and manual updater commands.
- [ ] Document token/webhook secrets, token access, environment requirements,
  auto-merge/squash settings, and required checks.
- [ ] Explain failed PR investigation, alerts, and merges deferred by reviews
  or updated-base requirements.
- [ ] Document generated-project dependency updates and correct the ADR's cadence
  and artifact delivery description.

## Task 8: Integration verification and final review

- [ ] Run all updater tests and all 24 Python lock checks after the final change.
- [ ] Lint all changed workflows.
- [ ] Render temporary default/all-features/minimal projects from a source snapshot
  excluding ignored local files. Git-backed `--vcs-ref=HEAD` omits uncommitted
  draft changes and is appropriate only once they are committed.
- [ ] Check rendered runtime/lock agreement and run frontend checks.
- [ ] Build backend production and development/test images with optional features
  and the frontend image; check installed backend package compatibility.
- [ ] Run existing backend tests with a temporary database where feasible.
- [ ] Review every issue acceptance criterion against the finished implementation.
- [ ] Run `git diff --check`; inspect the complete diff and new files.
- [ ] Report verification evidence and limitations; leave changes on the current branch.

## Remote verification after workflow configuration

These checks require configured GitHub Actions and are not part of local proof:

1. Confirm one PR per changed stream, none for unchanged streams, and reused PR
   numbers on the following run.
2. Confirm a controlled failing PR stays open while other streams finish and
   Slack receives a repository/run URL.
3. Confirm successful PRs merge only after required checks and reviews.
4. Confirm scheduled Test template success is silent and failure still alerts.
