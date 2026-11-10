"""Keep the Wagtail CI matrix compatible with dependency PR merge checks."""

import json
import os
import subprocess
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


class TemplateWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.jobs = yaml.safe_load(
            (ROOT / ".github/workflows/test-template.yaml").read_text()
        )["jobs"]

    def test_required_check_covers_every_template_job(self):
        gate = self.jobs["test-template"]
        self.assertNotIn("strategy", gate)
        self.assertEqual(gate["if"], "always()")
        self.assertEqual(set(gate["needs"]), set(self.jobs) - {"test-template"})
        # Notifications belong in conditional steps; a skipped job would block
        # the updater, which requires all reported checks to succeed.
        for job in self.jobs.values():
            self.assertNotIn("schedule", job.get("if", ""))

    def test_required_check_rejects_failed_cancelled_and_skipped_dependencies(self):
        gate = self.jobs["test-template"]
        script = gate["steps"][0]["run"]
        for outcome in ("success", "failure", "cancelled", "skipped"):
            with self.subTest(outcome=outcome):
                results = {name: {"result": "success"} for name in gate["needs"]}
                results["test-template-variants"]["result"] = outcome
                result = subprocess.run(
                    ["bash", "-e", "-c", script],
                    env={**os.environ, "TEMPLATE_RESULTS": json.dumps(results)},
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode == 0, outcome == "success")


if __name__ == "__main__":
    unittest.main()
