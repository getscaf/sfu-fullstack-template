## 2026-04-16 - Version Pinning Strategy

### Decision

Reintroduce version pinning for the Full Stack template. CI will generate and store tested lock files weekly, and SCAF will fetch these pinned artifacts during bootstrap instead of resolving dependencies live.

### Context & Rationale

The Full Stack template previously generated dependencies on the fly during bootstrap, risking broken builds from untested upstream package changes outside the team's direct control. This "bleeding edge" approach — always pulling the latest available packages — introduced unpredictable breakage for users bootstrapping new projects.

The team evaluated two approaches:

- **Unpinned (status quo):** Dependencies resolved at bootstrap time. Always fresh, but fragile — any upstream package change can silently break the bootstrap experience.
- **Pinned with CI-driven updates ("cutting edge"):** Lock files generated from a known-working CI run and stored as artifacts. SCAF fetches these during bootstrap. Weekly CI runs regenerate and commit updated lock files, keeping the template current without exposing users to unverified upstream changes.

The team agreed that pinning with automated updates is the industry-standard approach and resolves the majority of existing bootstrap reliability issues. Because automated tests gate all lock file updates, manual PR review of weekly dependency updates is unnecessary — a failed CI run will block the update from landing.

The main branch remains protected by mandatory PR CI gating, ensuring it stays releasable. However, dependency breakage from packages outside the repo is best mitigated by pinned lock files from successful CI runs rather than relying on main's recency.

### Impact & Next Steps

- Bootstrap reliability improves significantly: users get a dependency set known to work, not the latest unverified packages.
- Bootstrap time may also improve, as preresolved lock files reduce install-time resolution overhead.
- Weekly automated CI workflow to regenerate and commit updated lock files; no manual PR review required given test coverage.
- Dependabot PRs (currently paused) will resume with CI gating to keep CI tooling dependencies current.
- SCAF to be updated to fetch pinned lock file artifacts during bootstrap instead of resolving dependencies live.
- SCAF UI to be enhanced to allow users to select a specific release or opt into main explicitly, improving transparency and control.
- Offline bootstrap remains unsupported by design; SCAF requires online access to fetch templates and artifacts.
