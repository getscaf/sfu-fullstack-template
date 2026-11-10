"""Exercise source export from a checkout containing local development artifacts."""

import subprocess
import tempfile
import unittest
from pathlib import Path

from copier import run_copy

from tests.template_source import export_template_source


class TemplateSourceTests(unittest.TestCase):
    def test_render_uses_working_tree_changes_without_ignored_artifacts(self):
        with tempfile.TemporaryDirectory(prefix="scaf-source-tests-") as directory:
            work = Path(directory)
            root = work / "checkout"
            template = root / "template"
            template.mkdir(parents=True)
            (root / "copier.yml").write_text(
                "_subdirectory: template\n"
                "_templates_suffix: ''\n"
                "greeting:\n"
                "  type: str\n"
                "  default: world\n"
            )
            (template / ".gitignore").write_text(".direnv/\nnode_modules/\n")
            tracked = template / "message.txt"
            tracked.write_text("Original {{ greeting }}\n")
            subprocess.run(["git", "init", "--quiet", str(root)], check=True)
            subprocess.run(["git", "add", "."], cwd=root, check=True)

            tracked.write_text("Working tree {{ greeting }}\n")
            (template / "new file.txt").write_text("New {{ greeting }}\n")
            (root / "unrelated.txt").write_text("Outside the template source\n")
            artifacts = template / ".direnv"
            artifacts.mkdir()
            (artifacts / "flake-profile").symlink_to(work / "missing-profile")
            dependencies = template / "frontend/node_modules"
            dependencies.mkdir(parents=True)
            (dependencies / "installed.js").write_text("local dependency\n")

            source = work / "export"
            export_template_source(source, root=root)
            self.assertFalse((source / "template/.direnv").exists())
            self.assertFalse((source / "template/frontend/node_modules").exists())
            self.assertFalse((source / "unrelated.txt").exists())

            project = work / "project"
            run_copy(str(source), project, defaults=True, skip_tasks=True, quiet=True)
            self.assertEqual(
                (project / "message.txt").read_text(), "Working tree world\n"
            )
            self.assertEqual((project / "new file.txt").read_text(), "New world\n")


if __name__ == "__main__":
    unittest.main()
