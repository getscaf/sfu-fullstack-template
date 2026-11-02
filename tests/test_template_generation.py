import ast
import itertools
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

from tests.generation import generate_project


class TemplateGenerationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="scaf-generation-tests-")
        cls.projects = {
            (nextjs, wagtail): generate_project(
                Path(cls.directory.name) / f"{nextjs}-{wagtail}",
                nextjs=nextjs,
                wagtail=wagtail,
            )
            for nextjs, wagtail in itertools.product([False, True], repeat=2)
        }

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def test_four_option_combinations(self):
        for (nextjs, wagtail), project in self.projects.items():
            with self.subTest(nextjs=nextjs, wagtail=wagtail):
                backend = project / "backend"
                self.assertEqual((project / "frontend").exists(), nextjs)
                self.assertEqual((backend / "cms_demo/cms").exists(), wagtail)
                self.assertEqual((project / "docs/wagtail.md").exists(), wagtail)
                requirements = (backend / "requirements/base.in").read_text()
                self.assertEqual("wagtail" in requirements.splitlines(), wagtail)
                self.assertEqual(
                    "wagtail-headless-preview" in requirements, nextjs and wagtail
                )
                self.assertEqual("strawberry-graphql-django" in requirements, nextjs)
                self.assertEqual((backend / "config/schema.py").exists(), nextjs)
                for path in backend.rglob("*.py"):
                    ast.parse(path.read_text(), filename=str(path))
                settings = (backend / "config/settings/base.py").read_text()
                self.assertEqual('"wagtail"' in settings, wagtail)
                if wagtail:
                    self.assertEqual((backend / "cms_demo/cms/api.py").exists(), nextjs)
                    self.assertEqual(
                        (backend / "cms_demo/cms/serializers.py").exists(), nextjs
                    )
                    migration = (
                        backend / "cms_demo/cms/migrations/0001_initial.py"
                    ).read_text()
                    self.assertNotIn("headless_preview", migration)
                    self.assertIn('bases=("wagtailcore.page",)', migration)
                if nextjs:
                    self.assertEqual(
                        (project / "frontend/lib/cms-origins.ts").exists(), wagtail
                    )
                    self.assertEqual(
                        (project / "frontend/pages/content/[[...slug]].tsx").exists(),
                        wagtail,
                    )
                    self.assertEqual(
                        (project / "frontend/pages/cms-preview.tsx").exists(), wagtail
                    )
                    # Node pinning is a setup hook, deliberately skipped in this suite.
                    self.assertIn(
                        "__NODE_LTS_VERSION__",
                        (project / "frontend/Dockerfile").read_text(),
                    )

    def test_cloud_access_boundaries(self):
        for (nextjs, wagtail), project in self.projects.items():
            with self.subTest(nextjs=nextjs, wagtail=wagtail):
                tf = project / "terraform/modules/base"
                s3 = (tf / "s3.tf").read_text()
                policy = json.loads(
                    re.search(r"policy = <<EOF\n(.*?)\nEOF", s3, re.S).group(1)
                )
                resources = policy["Statement"]["Resource"]
                if wagtail:
                    self.assertEqual(
                        {resource.split("}", 1)[1] for resource in resources},
                        {
                            "/static/*",
                            "/media/original_images/*",
                            "/media/images/*",
                            "/media/avatar_images/*",
                        },
                    )
                else:
                    self.assertEqual(resources, "${aws_s3_bucket.static_storage.arn}/*")
                self.assertIn("block_public_acls       = true", s3)
                routes = (tf / "route53.tf").read_text()
                self.assertIn('type    = "A"', routes)
                self.assertIn('type    = "AAAA"', routes)
                self.assertEqual('"nextjs"' in routes, nextjs)
                behavior = (tf / "cloudfront.tf").read_text()
                if nextjs:
                    self.assertIn('path_pattern           = "/static/*"', behavior)
                    self.assertEqual(
                        'path_pattern           = "/media/*"' in behavior, not wagtail
                    )

    @unittest.skipUnless(
        shutil.which("kubectl"), "kubectl kustomize is required for manifest checks"
    )
    def test_environment_configuration_chain(self):
        for (nextjs, wagtail), project in self.projects.items():
            environments = []
            for environment in ["sandbox", "prod"]:
                with self.subTest(
                    nextjs=nextjs, wagtail=wagtail, environment=environment
                ):
                    overlay = project / "k8s" / environment
                    # Real sealed values are not needed to build or inspect manifests.
                    (overlay / "secrets.yaml").write_text(
                        "apiVersion: bitnami.com/v1alpha1\nkind: SealedSecret\n"
                        "metadata:\n  name: secrets-config\nspec: {}\n"
                    )
                    result = subprocess.run(
                        ["kubectl", "kustomize", str(overlay)],
                        capture_output=True,
                        text=True,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    manifests = list(yaml.safe_load_all(result.stdout))
                    config = next(
                        doc["data"]
                        for doc in manifests
                        if doc["kind"] == "ConfigMap"
                        and doc["metadata"]["name"].startswith("app-config")
                    )
                    self.assertEqual(
                        config["DJANGO_AWS_STORAGE_BUCKET_NAME"],
                        f"cms-demo-{environment}-static-storage",
                    )
                    self.assertEqual(
                        config["AWS_S3_CUSTOM_DOMAIN"], f"{environment}.example.test"
                    )
                    backend = f"https://api.{environment}.example.test"
                    public = f"https://{environment}.example.test"
                    frontend = f"nextjs.{environment}.example.test"
                    roots = (
                        project / "terraform" / environment / "cluster.tf"
                    ).read_text()
                    self.assertIn(
                        f'api_domain_name        = "api.{environment}.example.test"',
                        roots,
                    )
                    cert = next(
                        doc
                        for doc in manifests
                        if doc["kind"] == "Certificate"
                        and doc["metadata"]["name"] == "cluster-cert"
                    )
                    sans = cert["spec"]["dnsNames"]
                    self.assertIn(f"api.{environment}.example.test", sans)
                    ingresses = {
                        doc["metadata"]["name"]: doc
                        for doc in manifests
                        if doc["kind"] == "IngressRoute"
                    }
                    self.assertEqual(
                        ingresses["backend-ingress"]["spec"]["routes"][0]["match"],
                        f"Host(`api.{environment}.example.test`)",
                    )
                    deployment = next(
                        doc
                        for doc in manifests
                        if doc["kind"] == "Deployment"
                        and doc["metadata"]["name"] == "backend"
                    )
                    pod = deployment["spec"]["template"]["spec"]
                    migration = next(
                        container
                        for container in pod["initContainers"]
                        if container["name"] == "backend-migration"
                    )
                    self.assertEqual(
                        migration["command"],
                        [
                            "sh",
                            "-c",
                            "python manage.py migrate && python manage.py initialize_cms",
                        ]
                        if wagtail
                        else ["python", "manage.py", "migrate"],
                    )
                    collection = next(
                        container
                        for container in pod["initContainers"]
                        if container["name"] == "backend-collectstatic"
                    )
                    self.assertEqual(collection["image"], pod["containers"][0]["image"])
                    self.assertEqual(
                        collection["command"],
                        ["python", "manage.py", "collectstatic", "--noinput"],
                    )
                    self.assertEqual(
                        collection["envFrom"], pod["containers"][0]["envFrom"]
                    )
                    if nextjs:
                        self.assertIn(frontend, roots)
                        self.assertIn(frontend, sans)
                        self.assertEqual(
                            ingresses["frontend-ingress"]["spec"]["routes"][0]["match"],
                            f"Host(`{frontend}`)",
                        )
                        self.assertEqual(
                            set(config["CORS_ALLOWED_ORIGINS"].split(",")),
                            {public, f"https://{frontend}"},
                        )
                    else:
                        self.assertNotIn("frontend-ingress", ingresses)
                        self.assertFalse(
                            any(name.startswith("nextjs.") for name in sans)
                        )
                        self.assertNotIn("CORS_ALLOWED_ORIGINS", config)
                    self.assertIn(backend, config["DJANGO_CSRF_TRUSTED_ORIGINS"])
                    if wagtail:
                        self.assertEqual(config["CMS_BACKEND_BASE_URL"], backend)
                        self.assertEqual(
                            config["CMS_PUBLIC_BASE_URL"], public if nextjs else backend
                        )
                    else:
                        self.assertNotIn("CMS_PUBLIC_BASE_URL", config)
                    environments.append(frontend)
            self.assertEqual(len(set(environments)), 2)

    def test_other_optional_features_remain_independent(self):
        project = generate_project(
            Path(self.directory.name) / "alternate",
            nextjs=False,
            wagtail=True,
            copier__use_celery=True,
            copier__use_sentry=True,
            copier__operating_system="talos",
            copier__repo_url="git@bitbucket.org:example/cms-demo.git",
        )
        self.assertTrue((project / "bitbucket-pipelines.yml").exists())
        self.assertFalse((project / ".github").exists())
        self.assertTrue((project / "k8s/base/celery.yaml").exists())
        self.assertTrue((project / "backend/cms_demo/cms/models.py").exists())


if __name__ == "__main__":
    unittest.main()
