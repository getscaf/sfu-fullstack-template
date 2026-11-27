"""Check Docker failures stop bootstrap before modifying the generated project."""

import runpy
import subprocess
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

TASKS = Path(__file__).resolve().parents[1] / "template/tasks.py"


class DockerAvailabilityTests(unittest.TestCase):
    def setUp(self):
        self.tasks = runpy.run_path(str(TASKS))

    def test_unavailable_docker_stops_before_setup(self):
        failures = [
            (FileNotFoundError("docker"), "Install Docker"),
            (
                subprocess.CalledProcessError(1, ["docker", "info"]),
                "Docker daemon is not reachable",
            ),
            (
                subprocess.TimeoutExpired(["docker", "info"], 10),
                "Docker daemon is not reachable",
            ),
            (PermissionError("docker"), "Docker daemon is not reachable"),
        ]
        main = self.tasks["main"]
        for failure, message in failures:
            with self.subTest(failure=type(failure).__name__):
                setup = Mock()
                with patch.dict(
                    main.__globals__, {"set_flags_in_secrets": setup}
                ), patch("subprocess.run", side_effect=failure):
                    with self.assertRaises(SystemExit) as error:
                        main()
                self.assertIsInstance(error.exception.code, str)
                self.assertIn(message, error.exception.code)
                self.assertIn("docker info", error.exception.code)
                setup.assert_not_called()

    def test_reachable_docker_allows_setup(self):
        main = self.tasks["main"]
        setup = Mock(side_effect=RuntimeError("setup reached"))
        with patch.dict(main.__globals__, {"set_flags_in_secrets": setup}), patch(
            "subprocess.run", return_value=subprocess.CompletedProcess([], 0)
        ):
            with self.assertRaisesRegex(RuntimeError, "setup reached"):
                main()
        setup.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
