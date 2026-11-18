"""Wait for checks on the expected PR commit, then request protected auto-merge.

`wait` polls with a read-only token. `merge` reads the PR once and requests
auto-merge only if the expected head is still ready, so a short-lived write
token is never held across the polling window.
"""

import argparse
import json
import subprocess
import time

REQUIRED_CHECKS = {"test-template", "dependency-tests"}


def checks_passed(checks, required):
    names = set()
    pending = False
    for check in checks:
        name = check.get("name", check.get("context"))
        names.add(name)
        if "conclusion" in check:
            if check["status"] != "COMPLETED":
                pending = True
                continue
            state = check["conclusion"]
        else:
            state = check["state"]
            if state in ("PENDING", "EXPECTED"):
                pending = True
                continue
        if state != "SUCCESS":
            raise RuntimeError(f"PR check {name!r} ended with {state!r}")
    return not pending and required <= names


def pr_status(repository, number, sha):
    """Return "merged", "ready", or "pending" for the expected PR head."""
    result = subprocess.run(
        [
            "gh",
            "pr",
            "view",
            number,
            "--repo",
            repository,
            "--json",
            "headRefOid,state,statusCheckRollup",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    pr = json.loads(result.stdout)
    if pr["headRefOid"] != sha:
        raise RuntimeError("PR head changed while waiting for checks")
    if pr["state"] == "MERGED":
        return "merged"
    if pr["state"] != "OPEN":
        raise RuntimeError(f'PR is {pr["state"]}')
    if checks_passed(pr["statusCheckRollup"], REQUIRED_CHECKS):
        return "ready"
    return "pending"


def wait_for_checks(repository, number, sha, timeout=5400):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pr_status(repository, number, sha) != "pending":
            return
        print(f"Waiting for checks on PR #{number} ({sha})", flush=True)
        time.sleep(30)
    raise TimeoutError(f"Timed out waiting for PR #{number} checks")


def request_merge(repository, number, sha):
    status = pr_status(repository, number, sha)
    if status == "merged":
        return
    if status != "ready":
        raise RuntimeError(f"PR #{number} checks are not ready; rerun the wait")
    subprocess.run(
        [
            "gh",
            "pr",
            "merge",
            number,
            "--repo",
            repository,
            "--auto",
            "--squash",
            "--match-head-commit",
            sha,
        ],
        check=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["wait", "merge"])
    parser.add_argument("repository")
    parser.add_argument("number")
    parser.add_argument("sha")
    args = parser.parse_args()
    operation = wait_for_checks if args.operation == "wait" else request_merge
    operation(args.repository, args.number, args.sha)
