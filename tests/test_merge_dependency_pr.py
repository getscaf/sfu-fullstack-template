import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / ".github/scripts"))
import merge_dependency_pr as merge


def check(name, status="COMPLETED", conclusion="SUCCESS"):
    return {"name": name, "status": status, "conclusion": conclusion}


class MergeGateTests(unittest.TestCase):
    def pr(self, *, sha="expected", state="OPEN", checks=None):
        return subprocess.CompletedProcess(
            [],
            0,
            json.dumps(
                {
                    "headRefOid": sha,
                    "state": state,
                    "statusCheckRollup": (
                        [check(name) for name in merge.REQUIRED_CHECKS]
                        if checks is None
                        else checks
                    ),
                }
            ),
        )

    def test_success_requests_auto_merge_for_only_the_validated_head(self):
        with patch.object(
            merge.subprocess,
            "run",
            side_effect=[
                self.pr(checks=[]),
                self.pr(),
                subprocess.CompletedProcess([], 0),
            ],
        ) as run, patch.object(merge.time, "sleep"):
            merge.merge_when_ready("owner/repo", "7", "expected")
        command = run.call_args.args[0]
        self.assertEqual(
            command,
            [
                "gh",
                "pr",
                "merge",
                "7",
                "--repo",
                "owner/repo",
                "--auto",
                "--squash",
                "--match-head-commit",
                "expected",
            ],
        )

    def test_changed_head_or_closed_pr_prevents_merge(self):
        for response in (self.pr(sha="other"), self.pr(state="CLOSED")):
            with self.subTest(response=response.stdout), patch.object(
                merge.subprocess, "run", return_value=response
            ) as run:
                with self.assertRaises(RuntimeError):
                    merge.merge_when_ready("owner/repo", "7", "expected")
                self.assertEqual(run.call_count, 1)

    def test_changed_head_while_checks_are_pending_prevents_merge(self):
        with patch.object(
            merge.subprocess,
            "run",
            side_effect=[self.pr(checks=[]), self.pr(sha="other")],
        ) as run, patch.object(merge.time, "sleep"):
            with self.assertRaisesRegex(RuntimeError, "head changed"):
                merge.merge_when_ready("owner/repo", "7", "expected")
        self.assertEqual(run.call_count, 2)

    def test_already_merged_expected_head_needs_no_request(self):
        with patch.object(
            merge.subprocess, "run", return_value=self.pr(state="MERGED")
        ) as run:
            merge.merge_when_ready("owner/repo", "7", "expected")
        self.assertEqual(run.call_count, 1)

    def test_timeout_leaves_pending_pr_unmerged(self):
        with patch.object(merge.time, "monotonic", side_effect=[0, 0, 2]), patch.object(
            merge.time, "sleep"
        ), patch.object(
            merge.subprocess, "run", return_value=self.pr(checks=[])
        ) as run:
            with self.assertRaises(TimeoutError):
                merge.merge_when_ready("owner/repo", "7", "expected", timeout=1)
        self.assertEqual(run.call_count, 1)

    def test_failed_validation_leaves_pr_unmerged(self):
        with patch.object(
            merge.subprocess,
            "run",
            return_value=self.pr(checks=[check("test-template", conclusion="FAILURE")]),
        ) as run:
            with self.assertRaises(RuntimeError):
                merge.merge_when_ready("owner/repo", "7", "expected")
        self.assertEqual(run.call_count, 1)

    def test_view_or_merge_api_failure_propagates(self):
        for results in (
            [subprocess.CalledProcessError(1, "gh")],
            [self.pr(), subprocess.CalledProcessError(1, "gh")],
        ):
            with self.subTest(results=results), patch.object(
                merge.subprocess, "run", side_effect=results
            ):
                with self.assertRaises(subprocess.CalledProcessError):
                    merge.merge_when_ready("owner/repo", "7", "expected")

    def test_missing_or_queued_template_check_never_allows_merge(self):
        self.assertFalse(merge.checks_passed([], {"test-template", "dependency-tests"}))
        self.assertFalse(merge.checks_passed([check("Lint PR")], {"test-template"}))
        self.assertFalse(
            merge.checks_passed(
                [check("test-template", "QUEUED", None)], {"test-template"}
            )
        )

    def test_success_requires_all_expected_checks(self):
        self.assertTrue(
            merge.checks_passed(
                [
                    check("test-template"),
                    check("dependency-tests"),
                    {"context": "external", "state": "SUCCESS"},
                ],
                {"test-template", "dependency-tests"},
            )
        )
        self.assertFalse(
            merge.checks_passed(
                [
                    check("test-template"),
                    {"context": "external", "state": "PENDING"},
                ],
                {"test-template"},
            )
        )

    def test_failure_cancellation_or_skipped_validation_fails_closed(self):
        for conclusion in [
            "FAILURE",
            "CANCELLED",
            "TIMED_OUT",
            "SKIPPED",
            "NEUTRAL",
            "ACTION_REQUIRED",
        ]:
            with self.subTest(conclusion=conclusion):
                with self.assertRaises(RuntimeError):
                    merge.checks_passed(
                        [check("test-template", conclusion=conclusion)],
                        {"test-template"},
                    )
        with self.assertRaises(RuntimeError):
            merge.checks_passed(
                [{"context": "external", "state": "ERROR"}], {"test-template"}
            )


if __name__ == "__main__":
    unittest.main()
