import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which("jq"), "jq is required by the Node version hook")
class NodeVersionHookTests(unittest.TestCase):
    def test_hook_pins_selected_lts_in_github_and_bitbucket_projects(self):
        script = (
            Path(__file__).resolve().parents[1]
            / "template/scripts/update-node-version.sh"
        )
        common = ["flake.nix", "Makefile"]
        cases = {
            "headless-github": common
            + [
                "frontend/Dockerfile",
                ".github/workflows/main.yaml",
                ".github/workflows/semantic-release.yaml",
            ],
            "native-bitbucket": common + ["bitbucket-pipelines.yml"],
        }
        for mode, files in cases.items():
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                project = Path(directory)
                commands = project / "bin"
                commands.mkdir()
                curl = commands / "curl"
                # Exercise real jq/sed and the complete hook without network access.
                curl.write_text(
                    "#!/bin/sh\ncat <<'JSON'\n"
                    '[{"version":"v28.0.0","lts":false},'
                    '{"version":"v26.1.0","lts":"New LTS"},'
                    '{"version":"v24.0.0","lts":"Older LTS"}]\nJSON\n'
                )
                curl.chmod(0o755)
                original = "before __NODE_LTS_VERSION__ after\n"
                for name in files:
                    target = project / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(original)
                environment = {
                    **os.environ,
                    "PATH": f"{commands}{os.pathsep}{os.environ['PATH']}",
                }
                # Re-running must also work after the placeholders are gone.
                for _ in range(2):
                    result = subprocess.run(
                        ["bash", str(script)],
                        cwd=project,
                        env=environment,
                        capture_output=True,
                        text=True,
                        timeout=15,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    for name in files:
                        self.assertEqual(
                            (project / name).read_text(), "before 26 after\n"
                        )
                self.assertFalse(list(project.rglob("*.bak")))
