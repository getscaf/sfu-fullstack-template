"""Plan the rendered IAM trust policy without contacting AWS or GitHub."""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from jinja2 import Environment, StrictUndefined

ROOT = Path(__file__).resolve().parents[1]
ISSUER = "arn:aws:iam::123456789012:oidc-provider/token.actions.githubusercontent.com"


@unittest.skipUnless(
    shutil.which("tofu") and shutil.which("jq"), "tofu and jq required"
)
class GitHubOIDCTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="scaf-oidc-tests-")
        cls.project = Path(cls.directory.name)
        template = ROOT / "template/terraform/github"
        rendered = (
            Environment(undefined=StrictUndefined)
            .from_string((template / "oidc.tf").read_text())
            .render(
                copier__aws_region="us-east-1",
                copier__project_dash="oidc-demo",
                copier__project_slug="oidc_demo",
                copier__source_control_organization_slug="exampleorg",
                copier__repo_name="example-project",
            )
        )
        # Tests use local ephemeral state, never the generated remote backend.
        rendered = re.sub(r'  backend "s3" \{.*?\n  \}\n', "", rendered, flags=re.S)
        (cls.project / "oidc.tf").write_text(rendered)
        shutil.copy2(template / "check_oidc_provider.sh", cls.project)
        cls.bin = cls.project / "bin"
        cls.bin.mkdir()
        cls.metadata = cls.project / "repository.json"
        cls.write_command(
            "aws",
            """import sys
if sys.argv[1:3] == ['sts', 'get-caller-identity']:
    print('123456789012')
elif sys.argv[1:3] != ['iam', 'get-open-id-connect-provider']:
    sys.exit('Unexpected AWS command in offline test')
""",
        )
        cls.write_command(
            "gh",
            """import json, os, subprocess, sys
from pathlib import Path
if os.environ.get('OIDC_TEST_GH_ERROR'):
    sys.exit('GitHub repository lookup failed')
args = sys.argv[1:]
if args[:5] != ['api', '--hostname', 'github.com', 'repos/exampleorg/example-project', '--jq']:
    sys.exit('Unexpected GitHub lookup arguments: ' + repr(args))
# Exercise the actual filter passed to gh, including the external provider's
# requirement that all result values are strings.
result = subprocess.run(['jq', args[5]], input=Path(os.environ['OIDC_TEST_REPOSITORY']).read_text(), text=True, capture_output=True)
sys.stdout.write(result.stdout)
sys.stderr.write(result.stderr)
sys.exit(result.returncode)
""",
        )
        cls.env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(("AWS_", "GH_", "GITHUB_"))
        }
        cls.env.update(
            PATH=f"{cls.bin}{os.pathsep}{os.environ['PATH']}",
            OIDC_TEST_REPOSITORY=str(cls.metadata),
            TF_IN_AUTOMATION="true",
            TF_INPUT="0",
        )
        cls.run_tofu("init", "-backend=false", "-input=false", "-no-color")

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    @classmethod
    def write_command(cls, name, body):
        path = cls.bin / name
        path.write_text(f"#!{sys.executable}\n{body}")
        path.chmod(0o755)

    @classmethod
    def run_tofu(cls, *args, env=None, check=True):
        result = subprocess.run(
            ["tofu", *args],
            cwd=cls.project,
            env=env or cls.env,
            capture_output=True,
            text=True,
            timeout=180,
        )
        if check and result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        return result

    def prepare(
        self,
        owner_id=12345,
        repository_id=67890,
        owner="ExampleOrg",
        name="Example-Project",
    ):
        self.metadata.write_text(
            json.dumps(
                {
                    "owner": {"login": owner, "id": owner_id},
                    "name": name,
                    "id": repository_id,
                }
            )
        )
        expected = json.dumps(
            [
                "repo:ExampleOrg/Example-Project:*",
                f"repo:ExampleOrg@{owner_id}/Example-Project@{repository_id}:*",
            ]
        )
        (self.project / "oidc.tftest.hcl").write_text(f"""mock_provider "aws" {{
  mock_data "aws_iam_openid_connect_provider" {{
    defaults = {{ arn = "{ISSUER}" }}
  }}
}}

run "repository_trust" {{
  command = plan
  assert {{
    condition = jsondecode(aws_iam_role.github_oidc_role.assume_role_policy).Statement[0].Condition.StringLike["token.actions.githubusercontent.com:sub"] == {expected}
    error_message = "Trust must accept only this repository's legacy and exact-ID subjects."
  }}
  assert {{
    condition = jsondecode(aws_iam_role.github_oidc_role.assume_role_policy).Statement[0].Condition.StringEquals["token.actions.githubusercontent.com:aud"] == "sts.amazonaws.com"
    error_message = "The audience restriction must be preserved."
  }}
  assert {{
    condition = jsondecode(aws_iam_role.github_oidc_role.assume_role_policy).Statement[0].Principal.Federated == "{ISSUER}"
    error_message = "Trust must use the existing GitHub OIDC provider."
  }}
}}
""")

    def test_legacy_and_immutable_subjects_are_scoped_to_canonical_repository(self):
        self.prepare()
        result = self.run_tofu("test", "-no-color")
        self.assertIn("1 passed", result.stdout)

    def test_repository_ids_are_discovered_rather_than_hardcoded(self):
        self.prepare(owner_id=98765, repository_id=43210)
        self.run_tofu("test", "-no-color")

    def test_failed_repository_lookup_prevents_a_successful_plan(self):
        self.prepare()
        result = self.run_tofu(
            "test",
            "-no-color",
            env={**self.env, "OIDC_TEST_GH_ERROR": "1"},
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("GitHub repository lookup failed", result.stdout + result.stderr)

    def test_invalid_repository_id_is_rejected(self):
        self.prepare(repository_id=None)
        result = self.run_tofu("test", "-no-color", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            "GitHub repository metadata must include numeric owner and repository IDs",
            result.stdout + result.stderr,
        )

    def test_redirect_to_another_namespace_does_not_expand_trust(self):
        for metadata in ({"owner": "AnotherOrg"}, {"name": "another-project"}):
            with self.subTest(metadata=metadata):
                self.prepare(**metadata)
                result = self.run_tofu("test", "-no-color", check=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(
                    "GitHub repository lookup must match the configured owner/repository",
                    result.stdout + result.stderr,
                )


if __name__ == "__main__":
    unittest.main()
