import io
import os
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

from template.e2e import run as e2e


class E2ERunnerTests(unittest.TestCase):
    def run_with_tilt_result(self, tilt_result, cleanup_result=0):
        with tempfile.TemporaryDirectory() as tmp:
            reports = Path(tmp)

            def run_command(command, _log, env):
                if command[:3] == ["kind", "create", "cluster"]:
                    Path(env["KUBECONFIG"]).touch()
                    return 0
                result = tilt_result if command[0] == "tilt" else cleanup_result
                if isinstance(result, (Exception, KeyboardInterrupt)):
                    raise result
                return result

            with (
                patch.object(e2e, "REPORTS", reports),
                patch.object(e2e, "verify", return_value=0),
                patch.object(e2e, "forward_ports", return_value=["31001", "31002"]),
                patch.object(e2e, "run_logged", side_effect=run_command) as run,
                patch.object(e2e, "collect_diagnostics") as diagnostics,
                patch.dict(os.environ, {"KUBECONFIG": "/existing/development-config"}),
            ):
                result = e2e.run_suite()

            create, tilt, cleanup = (call.args for call in run.call_args_list)
            cluster = create[0][4]
            self.assertTrue(cluster.startswith("scaf-e2e-"))
            self.assertEqual(tilt[0][-1], f"kind-{cluster}")
            self.assertEqual(
                cleanup[0], ["kind", "delete", "cluster", "--name", cluster]
            )
            self.assertEqual(create[2]["KUBECONFIG"], cleanup[2]["KUBECONFIG"])
            self.assertFalse(Path(create[2]["KUBECONFIG"]).exists())
            self.assertNotEqual(create[2]["KUBECONFIG"], "/existing/development-config")
            return result, diagnostics.call_count

    def test_failure_is_reported_and_cluster_is_deleted(self):
        self.assertEqual(self.run_with_tilt_result(1), (1, 1))

    def test_interrupt_collects_diagnostics_and_deletes_cluster(self):
        self.assertEqual(self.run_with_tilt_result(KeyboardInterrupt()), (130, 1))

    def test_cleanup_failure_fails_an_otherwise_successful_run(self):
        self.assertEqual(self.run_with_tilt_result(0, cleanup_result=2), (2, 0))

    def test_second_interrupt_prints_the_cluster_recovery_command(self):
        with redirect_stderr(io.StringIO()) as stderr:
            self.assertEqual(
                self.run_with_tilt_result(
                    KeyboardInterrupt(), cleanup_result=KeyboardInterrupt()
                ),
                (130, 1),
            )
        self.assertRegex(
            stderr.getvalue(), r"kind delete cluster --name scaf-e2e-[a-f0-9]+"
        )

    def test_cleanup_launch_error_prints_the_cluster_recovery_command(self):
        with redirect_stderr(io.StringIO()) as stderr:
            self.assertEqual(
                self.run_with_tilt_result(
                    0, cleanup_result=OSError("kind unavailable")
                ),
                (1, 0),
            )
        self.assertIn("kind unavailable", stderr.getvalue())
        self.assertRegex(
            stderr.getvalue(), r"kind delete cluster --name scaf-e2e-[a-f0-9]+"
        )
