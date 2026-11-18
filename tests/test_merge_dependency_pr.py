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

    MERGE_COMMAND = [
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
    ]

    def test_wait_polls_until_checks_pass_without_merging(self):
        with patch.object(
            merge.subprocess,
            "run",
            side_effect=[self.pr(checks=[]), self.pr()],
        ) as run, patch.object(merge.time, "sleep"):
            merge.wait_for_checks("owner/repo", "7", "expected")
        self.assertEqual(run.call_count, 2)
        for call in run.call_args_list:
            self.assertNotIn("merge", call.args[0])

    def test_wait_returns_for_already_merged_expected_head(self):
        with patch.object(
            merge.subprocess, "run", return_value=self.pr(state="MERGED")
        ) as run:
            merge.wait_for_checks("owner/repo", "7", "expected")
        self.assertEqual(run.call_count, 1)

    def test_changed_head_or_closed_pr_stops_wait_and_merge(self):
        for operation in (merge.wait_for_checks, merge.request_merge):
            for response in (self.pr(sha="other"), self.pr(state="CLOSED")):
                with self.subTest(
                    operation=operation.__name__, response=response.stdout
                ), patch.object(
                    merge.subprocess, "run", return_value=response
                ) as run:
                    with self.assertRaises(RuntimeError):
                        operation("owner/repo", "7", "expected")
                    self.assertEqual(run.call_count, 1)

    def test_changed_head_while_checks_are_pending_stops_wait(self):
        with patch.object(
            merge.subprocess,
            "run",
            side_effect=[self.pr(checks=[]), self.pr(sha="other")],
        ) as run, patch.object(merge.time, "sleep"):
            with self.assertRaisesRegex(RuntimeError, "head changed"):
                merge.wait_for_checks("owner/repo", "7", "expected")
        self.assertEqual(run.call_count, 2)

    def test_wait_timeout_leaves_pending_pr_unmerged(self):
        with patch.object(merge.time, "monotonic", side_effect=[0, 0, 2]), patch.object(
            merge.time, "sleep"
        ), patch.object(
            merge.subprocess, "run", return_value=self.pr(checks=[])
        ) as run:
            with self.assertRaises(TimeoutError):
                merge.wait_for_checks("owner/repo", "7", "expected", timeout=1)
        self.assertEqual(run.call_count, 1)

    def test_failed_validation_stops_wait_and_merge(self):
        failed = [check("test-template", conclusion="FAILURE")]
        for operation in (merge.wait_for_checks, merge.request_merge):
            with self.subTest(operation=operation.__name__), patch.object(
                merge.subprocess, "run", return_value=self.pr(checks=failed)
            ) as run:
                with self.assertRaises(RuntimeError):
                    operation("owner/repo", "7", "expected")
            self.assertEqual(run.call_count, 1)

    def test_merge_requests_auto_merge_for_only_the_validated_head(self):
        with patch.object(
            merge.subprocess,
            "run",
            side_effect=[self.pr(), subprocess.CompletedProcess([], 0)],
        ) as run:
            merge.request_merge("owner/repo", "7", "expected")
        self.assertEqual(run.call_count, 2)
        self.assertEqual(run.call_args.args[0], self.MERGE_COMMAND)

    def test_merge_checks_once_and_never_polls_pending_checks(self):
        with patch.object(
            merge.subprocess, "run", return_value=self.pr(checks=[])
        ) as run, patch.object(merge.time, "sleep") as sleep:
            with self.assertRaisesRegex(RuntimeError, "not ready"):
                merge.request_merge("owner/repo", "7", "expected")
        self.assertEqual(run.call_count, 1)
        sleep.assert_not_called()

    def test_merge_is_a_no_op_for_already_merged_expected_head(self):
        with patch.object(
            merge.subprocess, "run", return_value=self.pr(state="MERGED")
        ) as run:
            merge.request_merge("owner/repo", "7", "expected")
        self.assertEqual(run.call_count, 1)

    def test_view_or_merge_api_failure_propagates(self):
        for operation, results in (
            (merge.wait_for_checks, [subprocess.CalledProcessError(1, "gh")]),
            (merge.request_merge, [subprocess.CalledProcessError(1, "gh")]),
            (
                merge.request_merge,
                [self.pr(), subprocess.CalledProcessError(1, "gh")],
            ),
        ):
            with self.subTest(
                operation=operation.__name__, results=results
            ), patch.object(merge.subprocess, "run", side_effect=results):
                with self.assertRaises(subprocess.CalledProcessError):
                    operation("owner/repo", "7", "expected")

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
