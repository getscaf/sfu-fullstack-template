"""Exercise rendered bootstrap without creating clusters or Git commits."""

import contextlib
import io
import json
import runpy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from copier import run_copy

from tests.template_source import export_template_source


class TemplateBootstrapTests(unittest.TestCase):
    def test_bootstrap_preserves_locks_and_optional_features(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            source = work / "source"
            export_template_source(source)
            variants = [
                {
                    "copier__use_celery": False,
                    "copier__use_sentry": False,
                    "copier__create_nextjs_frontend": True,
                },
                {
                    "copier__use_celery": True,
                    "copier__use_sentry": True,
                    "copier__create_nextjs_frontend": True,
                },
                {
                    "copier__use_celery": False,
                    "copier__use_sentry": False,
                    "copier__create_nextjs_frontend": False,
                },
            ]
            variants = [
                {**options, "copier__use_wagtail": wagtail}
                for options in variants
                for wagtail in (False, True)
            ]
            for i, options in enumerate(variants):
                with self.subTest(options=options):
                    project = work / str(i)
                    run_copy(
                        str(source),
                        project,
                        defaults=True,
                        skip_tasks=True,
                        quiet=True,
                        data={"copier__project_name_raw": "Pin Audit", **options},
                    )
                    requirements = project / "backend/requirements"
                    before = {
                        path.name: path.read_bytes()
                        for path in requirements.glob("*.txt")
                    }
                    frontend_lock = (
                        project / "frontend/package-lock.json"
                    ).read_bytes()
                    manifest = json.loads(
                        (project / "frontend/package.json").read_text()
                    )
                    lock = json.loads(frontend_lock)
                    self.assertEqual(lock["name"], manifest["name"])
                    self.assertEqual(lock["packages"][""]["name"], manifest["name"])
                    self.assertEqual(
                        lock["packages"][""]["dependencies"], manifest["dependencies"]
                    )
                    self.assertEqual(
                        lock["packages"][""]["devDependencies"],
                        manifest["devDependencies"],
                    )
                    with contextlib.chdir(project), contextlib.redirect_stdout(
                        io.StringIO()
                    ), patch("subprocess.run") as commands:
                        runpy.run_path(str(project / "tasks.py"), run_name="__main__")
                    self.assertEqual(
                        before,
                        {
                            path.name: path.read_bytes()
                            for path in requirements.glob("*.txt")
                        },
                    )
                    invoked = [call.args[0] for call in commands.call_args_list]
                    self.assertNotIn(["make", "compile"], invoked)
                    self.assertEqual(
                        ["make", "init-frontend-dependencies"] in invoked,
                        options["copier__create_nextjs_frontend"],
                    )
                    self.assertEqual(
                        (project / "frontend").exists(),
                        options["copier__create_nextjs_frontend"],
                    )
                    self.assertEqual(
                        (project / "backend/pin_audit/celery_app.py").exists(),
                        options["copier__use_celery"],
                    )
                    self.assertEqual(
                        (project / "docs/sentry.md").exists(),
                        options["copier__use_sentry"],
                    )
                    self.assertEqual(
                        (project / "backend/config/schema.py").exists(),
                        options["copier__create_nextjs_frontend"],
                    )
                    self.assertEqual(
                        (project / "backend/pin_audit/cms").exists(),
                        options["copier__use_wagtail"],
                    )
                    if options["copier__create_nextjs_frontend"]:
                        self.assertEqual(
                            (project / "frontend/package-lock.json").read_bytes(),
                            frontend_lock,
                        )


if __name__ == "__main__":
    unittest.main()
