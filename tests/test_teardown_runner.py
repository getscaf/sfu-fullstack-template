"""Teardown command, retry and state parsing tests."""

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from template.terraform.scripts import teardown as HELPER
from template.terraform.scripts import teardown_commands as COMMANDS

ELB_WARNING = {
    "severity": "warning",
    "summary": "cleaning up ELB Classic Load Balancer (SENSITIVE_TEST_PAYLOAD) ENIs",
    "detail": "api error AuthFailure: SENSITIVE_TEST_PAYLOAD",
}


class TeardownRunnerTests(unittest.TestCase):
    def test_ambiguous_or_unsupported_hcl_is_rejected(self):
        live = 'output "aws_region" {\n  value = "eu-west-1"\n}\n'
        for text in (
            live + live,
            'output "aws_region" {\n value = "a"\n value = "b"\n}\n',
            "/* unclosed comment\n" + live,
            'output "description" { value = <<EOF\n' + live,
            'output "description" { value = "unclosed\n' + live,
            'output "description" { value = "${jsonencode({a = "x"})}" }\n' + live,
        ):
            with self.subTest(text=text):
                with self.assertRaises(HELPER.TeardownError):
                    HELPER.literal(text, r'output\s+"aws_region"', "value")

    def test_literal_discovery_ignores_comments_and_quoted_content(self):
        old = 'output "aws_region" {\n  value = "old"\n}\n'
        live = 'output "aws_region" {\n  value = "eu-west-1"\n}\n'
        for decoy in (
            "/*\n" + old + "*/\n",
            "\n".join("# " + line for line in old.splitlines()) + "\n",
            "\n".join("// " + line for line in old.splitlines()) + "\n",
            'output "description" {\n  value = <<-DOC\n' + old + "DOC\n}\n",
            'output "description" {\n  value = ' + json.dumps(old) + "\n}\n",
        ):
            with self.subTest(decoy=decoy):
                self.assertEqual(
                    HELPER.literal(decoy + live, r'output\s+"aws_region"', "value"),
                    "eu-west-1",
                )
        body = 'output "aws_region" {\n/*\n  value = "old"\n*/\n  value = "eu-west-1" # current\n}\n'
        self.assertEqual(
            HELPER.literal(body, r'output\s+"aws_region"', "value"), "eu-west-1"
        )
        url = 'backend "s3" {\n bucket = "https://example.test/#fragment"\n}\n'
        self.assertEqual(
            HELPER.literal(url, r'backend\s+"s3"', "bucket"),
            "https://example.test/#fragment",
        )

    def failure(self, *codes):
        text = "\n".join("api error {}: failed".format(code) for code in codes)
        return COMMANDS.CommandError(
            "sandbox apply", subprocess.CompletedProcess([], 1, "", text)
        )

    def destroyer(self, failures):
        helper = HELPER.Teardown.__new__(HELPER.Teardown)
        helper.environment = "sandbox"
        helper.check_plan = Mock(side_effect=failures)
        helper.pull = Mock(return_value={"version": 4, "resources": []})
        return helper

    def test_diagnostic_severity_preserves_exit_status_and_retry_classification(self):
        dependency = {
            "severity": "error",
            "summary": "Error deleting resource",
            "detail": "api error DependencyViolation: SENSITIVE_TEST_PAYLOAD",
        }
        for diagnostics, status, code, transient in (
            ([ELB_WARNING], 0, None, None),
            ([dict(ELB_WARNING, severity="error")], 1, "AuthFailure", False),
            ([ELB_WARNING, dependency], 1, "DependencyViolation", True),
        ):
            with self.subTest(diagnostics=diagnostics):
                script = "import sys\n" + "\n".join(
                    "print({!r}, flush=True)".format(
                        json.dumps({"type": "diagnostic", "diagnostic": diagnostic})
                    )
                    for diagnostic in diagnostics
                )
                script += "\nsys.exit({})\n".format(status)
                output, errors = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(output), contextlib.redirect_stderr(
                    errors
                ):
                    if status:
                        with self.assertRaises(COMMANDS.CommandError) as raised:
                            COMMANDS.run_tofu_ui(
                                [sys.executable, "-c", script], "sandbox apply", 10
                            )
                        self.assertEqual(raised.exception.code, code)
                        self.assertEqual(raised.exception.transient, transient)
                    else:
                        COMMANDS.run_tofu_ui(
                            [sys.executable, "-c", script], "sandbox apply", 10
                        )
                self.assertNotIn(
                    "SENSITIVE_TEST_PAYLOAD", output.getvalue() + errors.getvalue()
                )
                for diagnostic in diagnostics:
                    self.assertIn(
                        "sandbox apply: {}:".format(diagnostic["severity"]),
                        errors.getvalue(),
                    )
                if diagnostics[0]["severity"] == "error":
                    self.assertNotIn("warning:", errors.getvalue())
                    self.assertNotIn("will be checked", errors.getvalue())

    def test_retry_uses_increasing_delays_and_fresh_plans(self):
        error = self.failure("DependencyViolation")
        helper = self.destroyer([error, error, error, None])
        ticks = [0]

        def sleep(seconds):
            ticks[0] += seconds

        with patch.object(
            HELPER.time, "monotonic", side_effect=lambda: ticks[0]
        ), patch.object(
            HELPER.time, "sleep", side_effect=sleep
        ) as sleeping, contextlib.redirect_stdout(
            io.StringIO()
        ):
            helper.destroy()
        self.assertEqual(
            [call.args[0] for call in sleeping.call_args_list], [30, 60, 120]
        )
        self.assertEqual(helper.check_plan.call_count, 4)

    def test_retry_deadline_counts_time_inside_later_attempts(self):
        error = self.failure("DependencyViolation")
        ticks = [0]

        def fail_slowly(*args, **kwargs):
            ticks[0] += 301
            raise error

        helper = self.destroyer([])
        helper.check_plan.side_effect = fail_slowly
        with patch.object(
            HELPER.time, "monotonic", side_effect=lambda: ticks[0]
        ), patch.object(HELPER.time, "sleep") as sleeping, contextlib.redirect_stdout(
            io.StringIO()
        ):
            with self.assertRaises(COMMANDS.CommandError):
                helper.destroy()
        self.assertEqual(helper.check_plan.call_count, 2)
        sleeping.assert_called_once_with(30)

        # A suspended machine can resume after the retry window has expired.
        ticks[0] = 0
        helper = self.destroyer([error, None])
        with patch.object(
            HELPER.time, "monotonic", side_effect=lambda: ticks[0]
        ), patch.object(
            HELPER.time, "sleep", side_effect=lambda _: ticks.__setitem__(0, 301)
        ), contextlib.redirect_stdout(
            io.StringIO()
        ):
            with self.assertRaises(COMMANDS.CommandError):
                helper.destroy()
        self.assertEqual(helper.check_plan.call_count, 1)

    def test_mixed_permanent_errors_are_not_retried(self):
        helper = self.destroyer([self.failure("DependencyViolation", "AuthFailure")])
        with patch.object(HELPER.time, "sleep") as sleeping, contextlib.redirect_stdout(
            io.StringIO()
        ):
            with self.assertRaises(COMMANDS.CommandError):
                helper.destroy()
        sleeping.assert_not_called()
        self.assertEqual(helper.check_plan.call_count, 1)
        misleading = COMMANDS.CommandError(
            "plan",
            subprocess.CompletedProcess(
                [], 1, "", "Error: Invalid variable named ResourceInUse"
            ),
        )
        self.assertFalse(misleading.transient)
        structured = COMMANDS.CommandError(
            "apply",
            subprocess.CompletedProcess([], 1, "", ""),
            diagnostics=[
                "api error DependencyViolation: pending",
                "Invalid configuration",
            ],
        )
        self.assertFalse(structured.transient)

    def test_progress_is_displayed_while_child_is_still_running(self):
        with tempfile.TemporaryDirectory() as directory:
            acknowledgement = Path(directory) / "displayed"
            progress = {
                "type": "apply_progress",
                "hook": {
                    "resource": {"addr": "terraform_data.probe"},
                    "elapsed_seconds": 1,
                },
            }
            hidden = {
                "type": "outputs",
                "outputs": {
                    "secret": {"sensitive": True, "value": "SENSITIVE_TEST_PAYLOAD"}
                },
            }
            script = "import time,sys\nfrom pathlib import Path\nprint({!r}, flush=True)\nprint({!r}, flush=True)\ndeadline=time.monotonic()+3\nwhile not Path({!r}).exists() and time.monotonic()<deadline: time.sleep(.01)\nsys.exit(0 if Path({!r}).exists() else 7)".format(
                json.dumps(progress),
                json.dumps(hidden),
                str(acknowledgement),
                str(acknowledgement),
            )

            class Display(io.StringIO):
                def write(self, text):
                    if "apply_progress" in text:
                        acknowledgement.write_text("displayed")
                    return super().write(text)

            output = Display()
            with contextlib.redirect_stdout(output):
                COMMANDS.run_tofu_ui(
                    [sys.executable, "-c", script], "sandbox apply", 10
                )
            self.assertTrue(acknowledgement.exists())
            self.assertNotIn("SENSITIVE_TEST_PAYLOAD", output.getvalue())

    @unittest.skipUnless(
        shutil.which("tofu"), "OpenTofu required for native JSON UI probe"
    )
    def test_native_tofu_json_ui_hides_sensitive_outputs(self):
        with tempfile.TemporaryDirectory(prefix="scaf-native-ui-") as directory:
            path = Path(directory)
            (path / "main.tf").write_text(
                'resource "terraform_data" "probe" { input = "safe" }\noutput "private" {\n value = "SENSITIVE_TEST_PAYLOAD"\n sensitive = true\n}\n'
            )
            env = {
                k: v
                for k, v in os.environ.items()
                if not k.startswith(("AWS_", "GH_", "GITHUB_", "TF_"))
            }
            command = [shutil.which("tofu"), "-chdir=" + directory]
            initialized = subprocess.run(
                [*command, "init", "-input=false"],
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(initialized.returncode, 0, initialized.stderr)
            output = io.StringIO()
            with patch.dict(os.environ, env, clear=True), contextlib.redirect_stdout(
                output
            ):
                COMMANDS.run_tofu_ui(
                    [*command, "plan", "-json", "-out=" + str(path / "plan")],
                    "probe plan",
                    30,
                )
                COMMANDS.run_tofu_ui(
                    [*command, "apply", "-json", str(path / "plan")], "probe apply", 30
                )
                COMMANDS.run_tofu_ui(
                    [
                        *command,
                        "plan",
                        "-destroy",
                        "-json",
                        "-out=" + str(path / "destroy"),
                    ],
                    "probe destroy plan",
                    30,
                )
                COMMANDS.run_tofu_ui(
                    [*command, "apply", "-json", str(path / "destroy")],
                    "probe destroy",
                    30,
                )
            empty = HELPER.decode_state(
                (path / "terraform.tfstate").read_text(), "native empty state"
            )
            self.assertEqual(HELPER.resources(empty, "native empty state"), [])
            self.assertIn("terraform_data.probe", output.getvalue())
            self.assertNotIn("SENSITIVE_TEST_PAYLOAD", output.getvalue())


if __name__ == "__main__":
    unittest.main()
