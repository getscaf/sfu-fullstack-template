## 2026-04-16 - Version Pinning Strategy

**Status:** Proposal. The nightly implementation refines the cadence and
delivery mechanism described here; release-selection tooling remains a
separate proposal.

### Decision

Reintroduce version pinning for the Full Stack template. Commit runtime
versions and tested package locks in the template itself. Copier delivers
these files with the selected template revision, and bootstrap installs them
without resolving newer dependencies or fetching a separate lock artifact.
Four independent nightly PR streams refresh the pins at 03:00 UTC and request
auto-merge after validation through normal repository protection rules.

### Context & Rationale

The Full Stack template previously generated dependencies on the fly during bootstrap, risking broken builds from untested upstream package changes outside the team's direct control. This "bleeding edge" approach — always pulling the latest available packages — introduced unpredictable breakage for users bootstrapping new projects.

The team evaluated two approaches:

- **Unpinned (status quo):** Dependencies resolved at bootstrap time. Always fresh, but fragile — any upstream package change can silently break the bootstrap experience.
- **Pinned with CI-driven updates ("cutting edge"):** Runtime versions and
  complete package locks are committed alongside the template. Nightly CI
  creates or updates dependency PRs, and validation gates their merge. Copier
  includes the committed pins when generating a project.

Pinning with automated updates reduces bootstrap failures caused by untested
upstream changes. A failed check prevents an update from merging and leaves
its PR available for investigation. Protected auto-merge respects required
reviews, checks, and merge queues; it does not bypass them.

The main branch remains protected by mandatory PR CI gating, ensuring it stays releasable. However, dependency breakage from packages outside the repo is best mitigated by pinned lock files from successful CI runs rather than relying on main's recency.

### Impact & Next Steps

- Bootstrap reliability improves significantly: users get a dependency set known to work, not the latest unverified packages.
- Bootstrap time may also improve, as preresolved lock files reduce install-time resolution overhead.
- Nightly automated PR streams update frontend runtime, backend runtime,
  Python packages, and frontend packages independently. Stable branches reuse
  open PRs; failed streams alert Slack while the other streams continue.
- Python and Node use full stable runtime versions matching Docker and CI.
  Python patch updates retain the current minor and Debian distribution. Node
  follows stable LTS; Nix follows only its major and is outside the exact
  runtime guarantee.
- Python locks share one compatible version set with conditional optional
  dependencies. Committed npm locks support `npm ci`. Source declarations
  remain authoritative, including debugger pins and Apollo ranges.
- Copier delivers committed locks and runtime files directly. Bootstrap no
  longer compiles Python requirements or discovers the latest Node version.
- Dependabot and CI/release-tool updates remain separate from the four
  application/runtime streams.
- A SCAF UI that lets users select a release or opt into main remains a
  separate proposal; this pinning implementation does not deliver that UI.
- Offline bootstrap remains unsupported by design; SCAF requires online
  access to fetch templates, packages, and container images.

Operational setup, update commands, scope limits, and hosted acceptance checks
are documented in [`docs/dependency-updates.md`](../../dependency-updates.md).
