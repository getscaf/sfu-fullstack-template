"""Opt-in real HTTP checks. See the implementation plan for the running-service setup."""

import json
import os
import re
import shlex
import subprocess
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode, urljoin
from urllib.request import HTTPRedirectHandler, build_opener, urlopen

import yaml


@unittest.skipUnless(
    os.environ.get("SCAF_RUN_WAGTAIL_SMOKE") == "1",
    "opt-in running-service smoke suite",
)
class WagtailSmokeTests(unittest.TestCase):
    def test_cms_handles_parallel_asset_and_login_requests(self):
        backend = os.environ["SCAF_SMOKE_BACKEND_URL"].rstrip("/")
        # Browser asset/AJAX concurrency exposes cProfile conflicts hidden by serial checks.
        paths = ["/cms/login/", "/cms/sprite/?h=scaf-concurrency-check"] * 8

        def get(path):
            with urlopen(backend + path, timeout=30) as response:
                response.read()
                return response.status

        with ThreadPoolExecutor(max_workers=4) as pool:
            self.assertEqual(list(pool.map(get, paths)), [200] * len(paths))

    def test_publication_preview_media_and_nested_paths(self):
        project = Path(os.environ["SCAF_SMOKE_PROJECT_DIR"])
        backend = os.environ["SCAF_SMOKE_BACKEND_URL"].rstrip("/")
        answers = yaml.safe_load((project / ".copier-answers.yml").read_text())
        self.assertTrue(answers["copier__use_wagtail"])
        nextjs = answers["copier__create_nextjs_frontend"]
        public = (
            os.environ["SCAF_SMOKE_FRONTEND_URL"].rstrip("/") if nextjs else backend
        )
        if os.environ.get("SCAF_SMOKE_MANAGE_COMMAND"):
            command = shlex.split(os.environ["SCAF_SMOKE_MANAGE_COMMAND"])
        else:
            command = [
                "kubectl",
                "--context",
                "kind-" + answers["copier__project_slug"].replace("_", "-"),
                "exec",
                "deployment/backend",
                "-c",
                "backend",
                "--",
                "python",
                "manage.py",
            ]
        module = answers["copier__project_slug"] + ".cms.tests.smoke_fixtures"

        def fixture(action, data=None):
            code = f"import json; from {module} import run, cleanup; "
            if action == "cleanup":
                code += f"cleanup({data!r}); print(json.dumps({{}}))"
            else:
                code += f"print(json.dumps(run({action!r}, {data!r})))"
            result = subprocess.run(
                command + ["shell", "--no-imports", "-c", code],
                cwd=project / "backend",
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
            return json.loads(result.stdout.strip().splitlines()[-1])

        def get(url, expected=200):
            try:
                with urlopen(url, timeout=30) as response:
                    status, body = response.status, response.read()
            except HTTPError as error:
                status, body = error.code, error.read()
            self.assertEqual(
                status, expected, f"Unexpected HTTP status for {url.split('?')[0]}"
            )
            return body

        data = fixture("setup")
        try:
            get(public + data["path"], 404)
            if nextjs:
                preview_url = (
                    public
                    + "/cms-preview?"
                    + urlencode(
                        {"content_type": "cms.contentpage", "token": data["token"]}
                    )
                )
                self.assertIn(b"First smoke body", get(preview_url))
            fixture("publish", data["id"])
            published = get(public + data["path"])
            self.assertIn(b"First smoke body", published)
            self.assertIn(b"First smoke body", get(public + data["space_path"]))
            if nextjs:
                canonical = re.search(
                    rb'<link rel="canonical" href="([^"]+)"', published
                )
                self.assertIsNotNone(canonical)
                self.assertEqual(
                    canonical.group(1).decode(), public + data["path"].rstrip("/")
                )
            hero = re.search(rb'<img[^>]+src="([^"]+)"', published)
            self.assertIsNotNone(hero)
            self.assertTrue(get(urljoin(public + "/", hero.group(1).decode())))
            self.assertIn(b"Other same leaf", get(public + data["other_path"]))
            if nextjs:
                page = json.loads(get(backend + f"/api/cms/v2/pages/{data['id']}/"))
                self.assertTrue(get(page["hero_image"]["url"]))
            fixture("edit", data["id"])
            self.assertIn(b"Updated smoke body", get(public + data["path"]))
            if nextjs:
                renamed = fixture("rename", data["id"])

                class NoRedirect(HTTPRedirectHandler):
                    def redirect_request(self, request, fp, code, msg, headers, newurl):
                        return None

                with self.assertRaises(HTTPError) as redirect:
                    build_opener(NoRedirect).open(
                        public + renamed["old_path"], timeout=30
                    )
                self.assertEqual(redirect.exception.code, 301)
                self.assertEqual(
                    urljoin(public, redirect.exception.headers["Location"]),
                    public + renamed["path"],
                )
                self.assertIn(b"Updated smoke body", get(public + renamed["old_path"]))
                data["path"] = renamed["path"]
            fixture("restrict", data["branch"])
            if nextjs:
                get(public + data["path"], 404)
            fixture("unpublish", data["id"])
            get(public + data["path"], 404)
        finally:
            fixture("cleanup", data)


if __name__ == "__main__":
    unittest.main()
