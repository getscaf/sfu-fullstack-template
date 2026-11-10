"""Plan public asset routing and permissions without contacting AWS."""

import itertools
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from jinja2 import Environment, StrictUndefined

ROOT = Path(__file__).resolve().parents[1]
BUCKET = "assets-sandbox-static-storage"
WAGTAIL_PREFIXES = [
    "static/",
    "media/original_images/",
    "media/images/",
    "media/avatar_images/",
]

MOCK_TEST = """mock_provider "aws" {
  mock_resource "aws_s3_bucket" {
    defaults = {
      id = "assets-sandbox-static-storage"
      arn = "arn:aws:s3:::assets-sandbox-static-storage"
      bucket_regional_domain_name = "assets-sandbox-static-storage.s3.us-east-1.amazonaws.com"
    }
  }
  mock_resource "aws_cloudfront_distribution" {
    defaults = {
      arn = "arn:aws:cloudfront::123456789012:distribution/ASSETS"
    }
  }
  mock_resource "aws_acm_certificate" {
    defaults = {
      arn = "arn:aws:acm:us-east-1:123456789012:certificate/00000000-0000-0000-0000-000000000000"
    }
  }
  mock_data "aws_iam_policy_document" {
    defaults = { json = "{}" }
  }
}

run "public_asset_access" {
  command = plan
  assert {
    condition = jsonencode(jsondecode(aws_s3_bucket_policy.static_storage.policy).Statement.Resource) == jsonencode(var.expected_s3_resources)
    error_message = "S3 must preserve the intended public prefixes and legacy non-Wagtail access."
  }
  assert {
    condition = jsonencode([for behavior in aws_cloudfront_distribution.cloudfront.ordered_cache_behavior : behavior.path_pattern]) == jsonencode(var.expected_paths)
    error_message = "CloudFront must route exactly the expected asset paths, preserving their order."
  }
  assert {
    condition = alltrue([for behavior in aws_cloudfront_distribution.cloudfront.ordered_cache_behavior : behavior.target_origin_id == aws_s3_bucket.static_storage.id if behavior.path_pattern != "/api/*"])
    error_message = "Public asset behaviors must use the S3 origin."
  }
  assert {
    condition = aws_cloudfront_distribution.cloudfront.default_cache_behavior[0].target_origin_id == var.expected_default_origin
    error_message = "The default origin must remain Next.js or S3 according to the selected features."
  }
  assert {
    condition = jsondecode(aws_s3_bucket_policy.static_storage.policy).Statement.Condition.StringEquals["AWS:SourceArn"] == aws_cloudfront_distribution.cloudfront.arn
    error_message = "S3 reads must remain restricted to this CloudFront distribution."
  }
}
"""


@unittest.skipUnless(shutil.which("tofu"), "tofu is required for cloud asset plans")
class CloudAssetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="scaf-cloud-assets-")
        cls.project = Path(cls.directory.name)
        cls.template = ROOT / "template/terraform/modules/base"
        version = re.search(
            r'aws\s*=\s*\{.*?version\s*=\s*"([^"]+)"',
            (cls.template / "versions.tf").read_text(),
            re.S,
        ).group(1)
        defaults = {
            "app_name": "assets",
            "environment": "sandbox",
            "tags": {},
            "domain_name": "assets.example.test",
            "nextjs_domain_name": "nextjs.assets.example.test",
            "cluster_name": "assets-cluster",
        }
        fixture = {
            "terraform": {
                "required_providers": {
                    "aws": {"source": "hashicorp/aws", "version": version}
                }
            },
            "provider": {"aws": {"region": "us-east-1"}},
            "variable": {
                **{name: {"default": value} for name, value in defaults.items()},
                "expected_paths": {},
                "expected_s3_resources": {},
                "expected_default_origin": {},
            },
            "resource": {
                "aws_acm_certificate": {
                    "cert": {
                        "domain_name": defaults["domain_name"],
                        "validation_method": "DNS",
                    }
                }
            },
        }
        (cls.project / "fixture.tf.json").write_text(json.dumps(fixture))
        (cls.project / "assets.tftest.hcl").write_text(MOCK_TEST)
        cls.env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("AWS_")
        }
        cls.env.update(TF_IN_AUTOMATION="true", TF_INPUT="0")
        cls.run_tofu("init", "-backend=false", "-input=false", "-no-color")

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    @classmethod
    def run_tofu(cls, *args):
        result = subprocess.run(
            ["tofu", *args],
            cwd=cls.project,
            env=cls.env,
            capture_output=True,
            text=True,
            timeout=180,
        )
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        return result

    def render(self, *, nextjs, wagtail):
        environment = Environment(undefined=StrictUndefined)
        for name in ("locals.tf", "s3.tf", "cloudfront.tf"):
            rendered = environment.from_string(
                (self.template / name).read_text()
            ).render(
                copier__create_nextjs_frontend=nextjs,
                copier__use_wagtail=wagtail,
            )
            (self.project / name).write_text(rendered)

    def assert_asset_plan(self, *, nextjs, wagtail, prefixes):
        expected = {
            "expected_paths": (
                [f"/{prefix}*" for prefix in prefixes] + ["/api/*"] if nextjs else []
            ),
            "expected_s3_resources": (
                [f"arn:aws:s3:::{BUCKET}/{prefix}*" for prefix in prefixes]
                if wagtail
                else f"arn:aws:s3:::{BUCKET}/*"
            ),
            "expected_default_origin": "assets-cluster" if nextjs else BUCKET,
        }
        (self.project / "expected.tfvars.json").write_text(json.dumps(expected))
        self.run_tofu("test", "-no-color", "-var-file=expected.tfvars.json")

    def test_public_access_for_all_feature_combinations(self):
        for nextjs, wagtail in itertools.product((False, True), repeat=2):
            with self.subTest(nextjs=nextjs, wagtail=wagtail):
                self.render(nextjs=nextjs, wagtail=wagtail)
                self.assert_asset_plan(
                    nextjs=nextjs,
                    wagtail=wagtail,
                    prefixes=WAGTAIL_PREFIXES if wagtail else ["static/", "media/"],
                )

    def test_adding_one_prefix_updates_routing_and_permissions(self):
        self.render(nextjs=True, wagtail=True)
        locals_path = self.project / "locals.tf"
        locals_path.write_text(
            locals_path.read_text().replace(
                '"static/",', '"static/",\n    "media/banners/",', 1
            )
        )
        self.assert_asset_plan(
            nextjs=True,
            wagtail=True,
            prefixes=[WAGTAIL_PREFIXES[0], "media/banners/", *WAGTAIL_PREFIXES[1:]],
        )


if __name__ == "__main__":
    unittest.main()
