"""Wait for checks on the expected PR commit, then request protected auto-merge."""

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


def merge_when_ready(repository, number, sha, timeout=5400):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
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
            return
        if pr["state"] != "OPEN":
            raise RuntimeError(f'PR is {pr["state"]}')
        if checks_passed(pr["statusCheckRollup"], REQUIRED_CHECKS):
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
            return
        print(f"Waiting for checks on PR #{number} ({sha})", flush=True)
        time.sleep(30)
    raise TimeoutError(f"Timed out waiting for PR #{number} checks")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repository")
    parser.add_argument("number")
    parser.add_argument("sha")
    args = parser.parse_args()
    merge_when_ready(args.repository, args.number, args.sha)
