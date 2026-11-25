"""Run rendered teardown commands against persistent fake AWS/OpenTofu state."""

import contextlib
import importlib.util
import io
import itertools
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import yaml
from jinja2 import Environment, StrictUndefined

from tests.generation import generate_project
from tests.template_source import export_template_source

ROOT = Path(__file__).resolve().parents[1]
ACCOUNT = "123456789012"
PROVIDER = "arn:aws:iam::{}:oidc-provider/token.actions.githubusercontent.com".format(
    ACCOUNT
)
ROLE = "arn:aws:iam::{}:role/cms_demo-github-oidc-role".format(ACCOUNT)
ELB_WARNING = {
    "severity": "warning",
    "summary": "cleaning up ELB Classic Load Balancer (SENSITIVE_TEST_PAYLOAD) ENIs",
    "detail": "api error AuthFailure: SENSITIVE_TEST_PAYLOAD",
}
TASK = shutil.which("task")
SPEC = importlib.util.spec_from_file_location(
    "teardown_helper", ROOT / "template/terraform/scripts/teardown.py"
)
HELPER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HELPER)


def resource(kind, resource_name, identity, **values):
    return {
        "module": (
            "module.cluster"
            if kind
            not in (
                "aws_iam_role",
                "aws_iam_openid_connect_provider",
                "aws_dynamodb_table",
            )
            else None
        ),
        "mode": "managed",
        "type": kind,
        "name": resource_name,
        "instances": [{"attributes": {"id": identity, **values}}],
    }


def state(*items):
    return {
        "version": 4,
        "serial": 1,
        "lineage": "test-state",
        "resources": list(items),
        "outputs": {
            "private_deploy_key": {
                "value": "SENSITIVE_TEST_PAYLOAD",
                "sensitive": True,
                "type": "string",
            }
        },
    }


class TeardownTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which("task"):
            raise RuntimeError(
                "Task is required for teardown behavioral tests; install the CI-pinned version"
            )
        cls.directory = tempfile.TemporaryDirectory(prefix="scaf-teardown-tests-")
        cls.work = Path(cls.directory.name)
        cls.generated = generate_project(
            cls.work / "rendered",
            copier__aws_account_id=ACCOUNT,
            copier__aws_region="us-east-1",
        )

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def setUp(self):
        self.case = Path(tempfile.mkdtemp(dir=self.work))
        self.project = self.case / "project"
        shutil.copytree(self.generated, self.project)
        self.bin = self.case / "bin"
        self.bin.mkdir()
        body = (ROOT / "tests/fixtures/teardown_cli.py").read_text()
        for name in ("aws", "tofu", "gh"):
            script = self.bin / name
            script.write_text("#!{}\n{}".format(sys.executable, body))
            script.chmod(0o755)
        self.data = self.case / "scenario.json"
        self.bucket = "cms-demo-terraform-state"
        self.static = "cms-demo-sandbox-static-storage"
        self.backups = "cms-demo-sandbox-backups"
        self.repo = "cms-demo-sandbox-backend"
        self.env = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith(("AWS_", "GH_", "GITHUB_", "TF_", "TERRAFORM_"))
        }
        self.env.update(
            PATH=str(self.bin) + os.pathsep + os.environ["PATH"],
            TEARDOWN_SCENARIO=str(self.data),
            AWS_PROFILE="offline-test",
            TERRAFORM_AUTO_APPROVE="1",
        )
        self.fixture = {
            "calls": [],
            "keys": {
                "sandbox": "cms_demo.sandbox.json",
                "staging": "cms-demo.staging.json",
                "prod": "cms_demo.prod.json",
                "github": "cms-demo.github.json",
            },
            "state_bucket": self.bucket,
            "buckets": {
                name: {"versions": [], "objects": []}
                for name in (self.bucket, self.static, self.backups)
            },
            "repositories": [self.repo],
            "nodes": {"i-one": "running"},
            "secrets": {},
            "table_exists": True,
            "roles": [
                {
                    "Arn": ROLE,
                    "AssumeRolePolicyDocument": {"Principal": {"Federated": PROVIDER}},
                }
            ],
            "remote": {
                "cms_demo.sandbox.json": state(
                    resource("aws_instance", "node", "i-one"),
                    resource(
                        "aws_s3_bucket",
                        "static_storage",
                        self.static,
                        bucket=self.static,
                        force_destroy=False,
                    ),
                    resource(
                        "aws_s3_bucket",
                        "backups",
                        self.backups,
                        bucket=self.backups,
                        force_destroy=False,
                    ),
                    resource(
                        "aws_ecr_repository",
                        "repository",
                        self.repo,
                        name=self.repo,
                        arn="arn:aws:ecr:us-east-1:{}:repository/{}".format(
                            ACCOUNT, self.repo
                        ),
                    ),
                    resource("aws_ecr_lifecycle_policy", "policy", self.repo),
                    resource("aws_vpc", "vpc", "vpc-one"),
                    resource("aws_cloudfront_distribution", "distribution", "CFONE"),
                ),
                "cms-demo.github.json": state(
                    resource(
                        "aws_iam_openid_connect_provider",
                        "github",
                        PROVIDER,
                        arn=PROVIDER,
                    ),
                    resource(
                        "aws_iam_role",
                        "github_oidc_role",
                        "cms_demo-github-oidc-role",
                        arn=ROLE,
                    ),
                ),
            },
            "bootstrap": state(
                resource(
                    "aws_s3_bucket",
                    "terraform_state",
                    self.bucket,
                    bucket=self.bucket,
                    force_destroy=False,
                ),
                resource(
                    "aws_dynamodb_table",
                    "terraform_state",
                    self.bucket,
                    name=self.bucket,
                ),
            ),
        }
        self.fixture["buckets"][self.static]["versions"] = [
            {"Key": "static/admin.css", "VersionId": "old"},
            {"Key": "media/image.jpg", "VersionId": "marker", "DeleteMarker": True},
        ]
        self.fixture["buckets"][self.backups]["objects"] = ["backup.dump"]
        self.fixture["buckets"][self.bucket]["versions"] = [
            {"Key": k, "VersionId": "old-state"} for k in self.fixture["remote"]
        ]
        self.persist()

    def persist(self):
        self.data.write_text(json.dumps(self.fixture))
        (self.project / "terraform/bootstrap/terraform.tfstate").write_text(
            json.dumps(self.fixture["bootstrap"])
        )

    def current(self):
        return json.loads(self.data.read_text())

    def invoke(
        self, *, approve=True, input_text="", command="teardown-sandbox", python39=False
    ):
        env = dict(self.env)
        if not approve:
            env.pop("TERRAFORM_AUTO_APPROVE")
        if python39:
            interpreter = os.environ.get("TEARDOWN_PYTHON39")
            if not interpreter:
                self.skipTest(
                    "Set TEARDOWN_PYTHON39 for the real Python 3.9 compatibility run"
                )
            (self.bin / "python3").symlink_to(interpreter)
        result = subprocess.run(
            [TASK, command],
            cwd=self.project,
            env=env,
            input=input_text,
            capture_output=True,
            text=True,
            timeout=90,
        )
        self.assertNotIn("SENSITIVE_TEST_PAYLOAD", result.stdout + result.stderr)
        return result

    def assert_success(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def destructive(self, fixture=None):
        calls = (fixture or self.current())["calls"]
        operations = {
            "stop-instances",
            "delete-objects",
            "delete-repository",
            "delete-secret",
            "apply",
        }
        return [c for c in calls if any(x in operations for x in c)]

    def test_old_state_retry_and_completed_noop(self):
        self.fixture["fail_apply"] = {"sandbox": 1}
        self.persist()
        first = self.invoke()
        self.assertNotEqual(first.returncode, 0)
        partial = self.current()
        self.assertIn(self.bucket, partial["buckets"])
        self.assertTrue(partial["remote"]["cms-demo.github.json"]["resources"])
        self.assertNotIn("i-one", partial["nodes"])
        # Same files/command; missing outputs and deleted ECR do not block retry.
        self.assert_success(self.invoke())
        done = self.current()
        self.assertFalse(done["buckets"])
        self.assertFalse(done["repositories"])
        self.assertFalse(done["table_exists"])
        before = len(self.destructive())
        again = self.invoke()
        self.assert_success(again)
        self.assertIn("already complete", again.stdout)
        self.assertEqual(len(self.destructive()), before)

    def test_many_versions_and_delete_markers_are_paginated_and_batched(self):
        self.fixture["buckets"][self.static]["versions"] = [
            {
                "Key": "asset{:04}".format(i),
                "VersionId": str(i),
                "DeleteMarker": i % 2 == 0,
            }
            for i in range(2005)
        ]
        self.persist()
        self.assert_success(self.invoke())
        calls = self.current()["calls"]
        self.assertTrue(any("--key-marker" in c for c in calls))
        requests = [
            json.loads(c[c.index("--delete") + 1])["Objects"]
            for c in calls
            if "delete-objects" in c
        ]
        self.assertTrue(any(len(batch) == 1000 for batch in requests))
        self.assertTrue(all(len(batch) <= 1000 for batch in requests))

    def test_per_object_error_preserves_backend(self):
        self.fixture["object_error"] = True
        self.persist()
        result = self.invoke()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("AccessDenied", result.stderr)
        self.assertIn(self.bucket, self.current()["buckets"])
        self.assertFalse(any("apply" in c for c in self.current()["calls"]))

    def test_s3_cleanup_deletes_pages_before_listing_entire_bucket(self):
        self.fixture["buckets"][self.static]["versions"] = [
            {
                "Key": "media/image.jpg",
                "VersionId": "version-{:04}".format(i),
                "DeleteMarker": i % 3 == 0,
            }
            for i in range(3005)
        ]
        self.fixture["buckets"][self.backups]["objects"] = [
            "backup-{:04}.dump".format(i) for i in range(2005)
        ]
        self.persist()
        self.assert_success(self.invoke())
        calls = self.current()["calls"]
        for bucket, operation in (
            (self.static, "list-object-versions"),
            (self.backups, "list-objects-v2"),
        ):
            with self.subTest(bucket=bucket):
                listings = [
                    index
                    for index, call in enumerate(calls)
                    if operation in call and bucket in call
                ]
                deletions = [
                    index
                    for index, call in enumerate(calls)
                    if "delete-objects" in call and bucket in call
                ]
                self.assertGreaterEqual(len(listings), 3)
                self.assertLess(deletions[0], listings[2])
        self.assertTrue(any("--version-id-marker" in call for call in calls))
        self.assertFalse(self.current()["buckets"])

    def test_preflight_errors_do_not_delete_anything(self):
        for error in ("AccessDenied", "ExpiredToken", "ConnectionError"):
            with self.subTest(error=error):
                self.fixture["calls"] = []
                self.fixture["errors"] = {"s3/cp": error}
                self.persist()
                self.assertNotEqual(self.invoke().returncode, 0)
                self.assertFalse(self.destructive())

    def test_decline_and_task_yes_do_not_approve(self):
        result = self.invoke(approve=False, input_text="no\n")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.destructive())
        result = subprocess.run(
            ["task", "--yes", "teardown-sandbox"],
            cwd=self.project,
            env={k: v for k, v in self.env.items() if k != "TERRAFORM_AUTO_APPROVE"},
            input="",
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.destructive())

    def test_overlapping_ecr_stops_before_node_shutdown(self):
        repo = self.fixture["remote"]["cms_demo.sandbox.json"]["resources"][3]
        self.fixture["remote"]["cms-demo.staging.json"] = state(repo)
        self.persist()
        result = self.invoke()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ownership overlaps", result.stderr)
        self.assertFalse(self.destructive())

    def test_suffixless_workspace_state_checks_ownership_before_cleanup(self):
        pristine = json.loads(json.dumps(self.fixture))
        for overlaps in (True, False):
            with self.subTest(overlaps=overlaps):
                self.fixture = json.loads(json.dumps(pristine))
                other = (
                    self.fixture["remote"]["cms_demo.sandbox.json"]["resources"][3]
                    if overlaps
                    else resource("aws_instance", "other", "i-other")
                )
                self.fixture["remote"]["env:/other/state"] = state(other)
                self.persist()
                result = self.invoke()
                if overlaps:
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("ownership overlaps", result.stderr)
                    self.assertFalse(self.destructive())
                    self.assertIn(self.repo, self.current()["repositories"])
                else:
                    self.assert_success(result)
                    self.assertIn(
                        "shared GitHub/bootstrap infrastructure retained", result.stdout
                    )
                    self.assertIn(self.bucket, self.current()["buckets"])
                    self.assertTrue(
                        self.current()["remote"]["env:/other/state"]["resources"]
                    )

    def test_other_environment_preserves_shared_stacks(self):
        self.fixture["remote"]["cms-demo.staging.json"] = state(
            resource("aws_instance", "other", "i-other")
        )
        self.persist()
        result = self.invoke()
        self.assert_success(result)
        self.assertIn("shared GitHub/bootstrap infrastructure retained", result.stdout)
        self.assertIn(self.bucket, self.current()["buckets"])
        self.assertTrue(self.current()["remote"]["cms-demo.github.json"]["resources"])
        self.assertFalse(
            any(
                c[0] == "tofu" and any("staging" in a for a in c)
                for c in self.current()["calls"]
            )
        )

    def test_oidc_reference_on_later_iam_page_preserves_backend(self):
        self.fixture["roles"] += [
            {
                "Arn": "arn:aws:iam::{}:role/unrelated".format(ACCOUNT),
                "AssumeRolePolicyDocument": {},
            },
            {
                "Arn": "arn:aws:iam::{}:role/other-project".format(ACCOUNT),
                "AssumeRolePolicyDocument": {"Principal": {"Federated": [PROVIDER]}},
            },
        ]
        self.fixture["roles"].append(self.fixture["roles"][-1])
        self.persist()
        result = self.invoke()
        self.assert_success(result)
        self.assertEqual(result.stdout.count("OIDC provider used by role"), 1)
        self.assertIn(self.bucket, self.current()["buckets"])
        self.assertTrue(any("--marker" in c for c in self.current()["calls"]))

    def test_github_lookup_failure_happens_before_cleanup(self):
        self.fixture["github_error"] = True
        self.persist()
        result = self.invoke()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("External Program Execution Failed", result.stderr)
        self.assertIn("repository access", result.stderr)
        self.assertIn("oidc.tf:25", result.stderr)
        self.assertFalse(self.destructive())

    def test_bootstrap_interruption_resumes_without_remote_init(self):
        self.fixture["fail_apply"] = {"bootstrap": 1}
        self.persist()
        self.assertNotEqual(self.invoke().returncode, 0)
        self.assertNotIn(self.bucket, self.current()["buckets"])
        self.assertTrue(self.current()["table_exists"])
        self.fixture = self.current()
        self.fixture["calls"] = []
        self.persist()
        self.assert_success(self.invoke())
        self.assertFalse(self.current()["table_exists"])
        self.assertFalse(
            any(
                c[0] == "tofu" and "init" in c and "bootstrap" not in c[1]
                for c in self.current()["calls"]
            )
        )

    def test_wrong_account_is_not_success(self):
        self.fixture["caller"] = "999999999999"
        self.persist()
        self.assertNotEqual(self.invoke().returncode, 0)
        self.assertFalse(self.destructive())

    def test_missing_local_state_preserves_only_bootstrap(self):
        self.fixture["errors"] = {"dynamodb/describe-table": "AccessDenied"}
        self.persist()
        (self.project / "terraform/bootstrap/terraform.tfstate").unlink()
        result = self.invoke()
        self.assert_success(result)
        self.assertIn("bootstrap retained", result.stdout)
        self.assertIn("local bootstrap state is missing", result.stdout)
        current = self.current()
        self.assertFalse(current["remote"]["cms_demo.sandbox.json"]["resources"])
        self.assertFalse(current["remote"]["cms-demo.github.json"]["resources"])
        self.assertIn(self.bucket, current["buckets"])
        self.assertTrue(current["table_exists"])
        self.assertTrue(current["remote"])
        self.assertFalse(any("describe-table" in c for c in current["calls"]))
        self.assertFalse(
            any(c[0] == "tofu" and "bootstrap" in c[1] for c in current["calls"])
        )

    def test_missing_local_state_and_backend_is_recovery_error(self):
        self.fixture["buckets"].pop(self.bucket)
        self.persist()
        (self.project / "terraform/bootstrap/terraform.tfstate").unlink()
        self.assertNotEqual(self.invoke().returncode, 0)
        self.assertFalse(self.destructive())

    def test_talos_legacy_secrets_are_retained_without_blocking(self):
        path = self.project / "bootstrap-cluster/Taskfile.yml"
        path.write_text(
            path.read_text()
            .replace("k3s:", "talos:")
            .replace("./k3s.yaml", "./talos.yaml")
        )
        # Task eagerly parses included files; generate a real Talos adapter.
        talos = generate_project(
            self.case / "talos",
            copier__operating_system="talos",
            copier__aws_account_id=ACCOUNT,
        )
        shutil.copyfile(
            talos / "bootstrap-cluster/talos.yaml",
            self.project / "bootstrap-cluster/talos.yaml",
        )
        for suffix in ("_kubeconfig", "_talosconfig_yaml", "_talos_controlplane_yaml"):
            name = "sandbox" + suffix
            self.fixture["secrets"][name] = {
                "ARN": "arn:aws:secretsmanager:us-east-1:{}:secret:{}".format(
                    ACCOUNT, name
                )
            }
        self.persist()
        result = self.invoke()
        self.assert_success(result)
        self.assertEqual(len(self.current()["secrets"]), 3)
        self.assertIn("Legacy secret preserved", result.stdout)

    def test_documented_update_preserves_customizations_and_finishes_legacy_failure(
        self,
    ):
        taskfile = self.project / "Taskfile.yml"
        legacy = ROOT / "tests/fixtures/teardown_legacy"
        renderer = Environment(undefined=StrictUndefined)
        previous = yaml.safe_load(
            renderer.from_string((legacy / "Taskfile.yml.jinja").read_text()).render(
                copier__project_dash="cms-demo",
                copier__aws_region="us-east-1",
                copier__aws_account_id=ACCOUNT,
                copier__operating_system="k3s",
            )
        )
        terraform_taskfile = self.project / "terraform/Taskfile.yml"
        previous_tf = yaml.safe_load(
            renderer.from_string(
                (legacy / "terraform-Taskfile.yml.jinja").read_text()
            ).render()
        )
        previous_tf["tasks"]["custom-terraform-task"] = {
            "cmds": ["echo custom-terraform"]
        }
        previous_tf["vars"] = {"CUSTOM_TERRAFORM_SETTING": "preserved"}
        terraform_taskfile.write_text(yaml.safe_dump(previous_tf, sort_keys=False))
        previous["tasks"]["custom-project-task"] = {"cmds": ["echo custom-preserved"]}
        previous["vars"]["CUSTOM_SETTING"] = "preserved"
        taskfile.write_text(yaml.safe_dump(previous, sort_keys=False))
        helper = self.project / "terraform/scripts/teardown.py"
        helper.unlink()
        failed = subprocess.run(
            [TASK, "--yes", "teardown-sandbox"],
            cwd=self.project,
            env=self.env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn("BucketNotEmpty", failed.stderr)
        self.assertNotIn("i-one", self.current()["nodes"])
        # Transfer only the documented rendered helper/task bodies; no setup,
        # normal apply, or replacement of the user's custom tasks/variables.
        source = self.case / "fixed-template"
        rendered = self.case / "update-render"
        export_template_source(source)
        answers = self.project / ".copier-answers.yml"
        old_answers = yaml.safe_load(answers.read_text())
        old_answers.pop("copier__use_wagtail", None)
        answers.write_text(yaml.safe_dump(old_answers))
        before = answers.read_bytes()
        rendered_result = subprocess.run(
            [
                sys.executable,
                "-m",
                "copier",
                "copy",
                "--defaults",
                "--skip-tasks",
                "--data-file",
                str(answers),
                "--vcs-ref=HEAD",
                str(source),
                str(rendered),
            ],
            env=self.env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(rendered_result.returncode, 0, rendered_result.stderr)
        self.assertEqual(answers.read_bytes(), before)
        fixed = yaml.safe_load((rendered / "Taskfile.yml").read_text())
        shutil.copyfile(rendered / "terraform/scripts/teardown.py", helper)
        for name in (
            "teardown-environment",
            "teardown-sandbox",
            "teardown-staging",
            "delete-ecr-images",
            "clean-s3-bucket-only",
        ):
            previous["tasks"][name] = fixed["tasks"][name]
        taskfile.write_text(yaml.safe_dump(previous, sort_keys=False))
        fixed_tf = yaml.safe_load((rendered / "terraform/Taskfile.yml").read_text())
        for name in (
            "teardown",
            "destroy-environment-dir",
            "destroy-github-dir",
            "destroy-bootstrap-dir",
            "clean-s3-bucket",
        ):
            previous_tf["tasks"][name] = fixed_tf["tasks"][name]
        previous_tf["tasks"].pop("destroy-terraform")
        terraform_taskfile.write_text(yaml.safe_dump(previous_tf, sort_keys=False))
        self.assert_success(self.invoke())
        self.assertIn("custom-project-task", taskfile.read_text())
        self.assertIn("CUSTOM_SETTING", taskfile.read_text())
        self.assertIn("custom-terraform-task", terraform_taskfile.read_text())
        self.assertIn("CUSTOM_TERRAFORM_SETTING", terraform_taskfile.read_text())
        self.assertFalse(self.current()["buckets"])

    def test_shared_discovery_errors_are_preflight_failures(self):
        for operation in ("iam/list-roles", "secretsmanager/describe-secret"):
            with self.subTest(operation=operation):
                self.fixture["calls"] = []
                self.fixture["errors"] = {operation: "AccessDenied"}
                self.persist()
                self.assertNotEqual(self.invoke().returncode, 0)
                self.assertFalse(self.destructive())

    def test_fresh_plan_cannot_expand_scope_after_cleanup(self):
        self.fixture.update(expand_scope=True, expand_after_preflight=True)
        self.persist()
        result = self.invoke()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("approved scope", result.stderr)
        self.assertFalse(
            any(c[0] == "tofu" and "apply" in c for c in self.current()["calls"])
        )
        self.assertIn(self.bucket, self.current()["buckets"])

    def test_mutation_actions_are_rejected_before_cleanup(self):
        for action in (["create"], ["update"], ["delete", "create"], ["forget"]):
            with self.subTest(action=action):
                self.fixture["calls"] = []
                self.fixture["action_override"] = action
                self.persist()
                self.assertNotEqual(self.invoke().returncode, 0)
                self.assertFalse(self.destructive())

    def test_backend_override_is_used_instead_of_guessed_key(self):
        key = "custom/sandbox-state.tfstate"
        self.fixture["remote"][key] = self.fixture["remote"].pop(
            "cms_demo.sandbox.json"
        )
        self.fixture["keys"]["sandbox"] = key
        directory = self.project / "terraform/sandbox/.terraform"
        directory.mkdir()
        (directory / "terraform.tfstate").write_text(
            json.dumps(
                {
                    "backend": {
                        "type": "s3",
                        "config": {
                            "bucket": self.bucket,
                            "key": key,
                            "region": "us-east-1",
                            "dynamodb_table": self.bucket,
                        },
                    }
                }
            )
        )
        self.persist()
        self.assert_success(self.invoke())

    def test_custom_bucket_keeps_terraform_deletion_policy(self):
        original = json.dumps(self.fixture)
        for module, name in (
            ("module.cluster", "audit_archive"),
            ("module.audit", "static_storage"),
        ):
            with self.subTest(module=module, name=name):
                self.fixture = json.loads(original)
                bucket = "custom-audit-archive"
                item = resource(
                    "aws_s3_bucket", name, bucket, bucket=bucket, force_destroy=False
                )
                item["module"] = module
                self.fixture["remote"]["cms_demo.sandbox.json"]["resources"].append(
                    item
                )
                self.fixture["buckets"][bucket] = {
                    "versions": [],
                    "objects": ["audit.log"],
                }
                self.persist()
                result = self.invoke()
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertIn("BucketNotEmpty", result.stderr)
                current = self.current()
                self.assertEqual(current["buckets"][bucket]["objects"], ["audit.log"])
                self.assertFalse(
                    any(
                        "delete-objects" in call and bucket in call
                        for call in current["calls"]
                    )
                )
                self.assertIn(self.bucket, current["buckets"])

    def test_shared_application_bucket_stops_before_node_shutdown(self):
        self.fixture["remote"]["cms-demo.staging.json"] = state(
            resource("aws_s3_bucket", "imported_media", self.static, bucket=self.static)
        )
        self.persist()
        result = self.invoke()
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("S3 ownership overlaps", result.stderr)
        self.assertFalse(self.destructive())
        self.assertEqual(
            self.current()["buckets"][self.static]["versions"],
            self.fixture["buckets"][self.static]["versions"],
        )

    def test_staging_uses_its_configured_dash_key(self):
        self.fixture["remote"]["cms-demo.staging.json"] = self.fixture["remote"].pop(
            "cms_demo.sandbox.json"
        )
        self.persist()
        self.assert_success(self.invoke(command="teardown-staging"))

    def test_production_remains_disabled(self):
        result = self.invoke(command="teardown-production")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.destructive())

    def test_python_version_check_precedes_helper(self):
        script = self.bin / "python3"
        script.write_text("#!/bin/sh\nexit 1\n")
        script.chmod(0o755)
        result = self.invoke()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Python 3.9", result.stderr)
        self.assertFalse(self.destructive())

    def test_empty_local_state_does_not_hide_existing_table(self):
        self.fixture["buckets"].pop(self.bucket)
        self.fixture["bootstrap"] = state()
        self.persist()
        self.assertNotEqual(self.invoke().returncode, 0)
        self.assertFalse(self.destructive())

    def test_empty_local_state_cannot_authorize_live_backend_cleanup(self):
        self.fixture["bootstrap"] = state()
        self.persist()
        result = self.invoke()
        self.assert_success(result)
        self.assertIn("bootstrap retained", result.stdout)
        self.assertIn(self.bucket, self.current()["buckets"])
        self.assertTrue(self.current()["table_exists"])
        self.assertFalse(self.current()["remote"]["cms_demo.sandbox.json"]["resources"])

    def test_s3_region_comes_from_bucket_state(self):
        self.fixture["buckets"][self.static]["region"] = "us-west-2"
        item = self.fixture["remote"]["cms_demo.sandbox.json"]["resources"][1]
        item["instances"][0]["attributes"].update(
            region="us-west-2", arn="arn:aws:s3:::" + self.static
        )
        self.persist()
        self.assert_success(self.invoke())
        calls = [
            c
            for c in self.current()["calls"]
            if "list-object-versions" in c and self.static in c
        ]
        self.assertTrue(calls)
        self.assertTrue(all(c[c.index("--region") + 1] == "us-west-2" for c in calls))

    def test_progress_and_useful_diagnostics_do_not_reveal_values(self):
        result = self.invoke()
        self.assert_success(result)
        self.assertIn("apply_progress (10s)", result.stdout)
        error = HELPER.diagnostic_summary(
            {
                "summary": "External Program Execution Failed",
                "detail": "SENSITIVE_TEST_PAYLOAD",
                "range": {"filename": "oidc.tf", "start": {"line": 25}},
            }
        )
        self.assertIn("External Program Execution Failed", error)
        self.assertIn("repository access", error)
        self.assertIn("oidc.tf:25", error)
        self.assertNotIn("SENSITIVE_TEST_PAYLOAD", error)

    def test_invalid_local_state_cannot_become_successful_noop(self):
        self.fixture["buckets"].pop(self.bucket)
        self.fixture["table_exists"] = False
        self.persist()
        path = self.project / "terraform/bootstrap/terraform.tfstate"
        path.write_text('{"version":4}')
        self.assertNotEqual(self.invoke().returncode, 0)
        self.assertFalse(self.destructive())

    def test_missing_resource_inventory_stops_before_any_deletion(self):
        pristine = json.loads(json.dumps(self.fixture))
        incomplete = state()
        incomplete.pop("resources")
        for location in ("sandbox", "staging", "bootstrap"):
            with self.subTest(location=location):
                self.fixture = json.loads(json.dumps(pristine))
                if location == "bootstrap":
                    self.fixture["bootstrap"] = incomplete
                else:
                    key = (
                        "cms_demo.sandbox.json"
                        if location == "sandbox"
                        else "cms-demo.staging.json"
                    )
                    self.fixture["remote"][key] = incomplete
                self.persist()
                result = self.invoke()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Unsupported/corrupt state", result.stderr)
                self.assertFalse(self.destructive())
                self.assertIn(self.bucket, self.current()["buckets"])

    def test_elb_warning_allows_verified_teardown_completion(self):
        self.fixture["diagnostics"] = {"apply": [ELB_WARNING]}
        self.persist()
        result = self.invoke()
        self.assert_success(result)
        self.assertIn(
            "sandbox apply: warning: ELB ENI cleanup (AuthFailure)", result.stderr
        )
        self.assertIn("remaining managed resources will be checked", result.stderr)
        self.assertIn("Infrastructure teardown completed", result.stdout)
        self.assertFalse(self.current()["buckets"])
        self.assertFalse(self.current()["table_exists"])
        self.assertFalse(self.current()["repositories"])

    def test_elb_warning_does_not_hide_apply_failure(self):
        self.fixture["diagnostics"] = {"apply": [ELB_WARNING]}
        self.fixture["fail_apply"] = {"sandbox": 1}
        self.persist()
        result = self.invoke()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            "sandbox apply: warning: ELB ENI cleanup (AuthFailure)", result.stderr
        )
        self.assertIn(
            "sandbox apply: error: OpenTofu diagnostic (InjectedInterruption)",
            result.stderr,
        )
        self.assertNotIn("Infrastructure teardown completed", result.stdout)
        self.assertIn(self.bucket, self.current()["buckets"])
        self.assertTrue(self.current()["remote"]["cms_demo.sandbox.json"]["resources"])

    def test_actual_python39_helper(self):
        self.fixture["diagnostics"] = {"apply": [ELB_WARNING]}
        self.persist()
        self.assert_success(self.invoke(python39=True))

    def test_all_feature_and_os_combinations_render(self):
        for nextjs, wagtail, cluster in itertools.product(
            (False, True), (False, True), ("k3s", "talos")
        ):
            with self.subTest(nextjs=nextjs, wagtail=wagtail, cluster=cluster):
                project = generate_project(
                    self.case
                    / "variants"
                    / "{}-{}-{}".format(nextjs, wagtail, cluster),
                    nextjs=nextjs,
                    wagtail=wagtail,
                    copier__operating_system=cluster,
                )
                result = subprocess.run(
                    ["task", "--list"],
                    cwd=project,
                    env=self.env,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("teardown-sandbox", result.stdout)
                self.assertTrue((project / "terraform/scripts/teardown.py").is_file())


class TeardownRunnerTests(unittest.TestCase):
    def failure(self, *codes):
        text = "\n".join("api error {}: failed".format(code) for code in codes)
        return HELPER.CommandError(
            "sandbox apply", subprocess.CompletedProcess([], 1, "", text)
        )

    def destroyer(self, failures):
        helper = HELPER.Teardown.__new__(HELPER.Teardown)
        helper.approved = {"sandbox": {}}
        helper.check_plan = Mock(side_effect=failures)
        helper.pull = Mock(return_value=state())
        return helper

    def test_diagnostic_severity_preserves_exit_status_and_retry_classification(self):
        dependency = {
            "severity": "error",
            "summary": "Error deleting resource",
            "detail": "api error DependencyViolation: SENSITIVE_TEST_PAYLOAD",
        }
        for diagnostics, status, code, transient in (
            ([ELB_WARNING], 0, None, None),
            ([dict(ELB_WARNING, severity="error")], 1, "AuthFailure", False),
            ([ELB_WARNING, dependency], 1, "DependencyViolation", True),
        ):
            with self.subTest(diagnostics=diagnostics):
                script = "import sys\n" + "\n".join(
                    "print({!r}, flush=True)".format(
                        json.dumps({"type": "diagnostic", "diagnostic": diagnostic})
                    )
                    for diagnostic in diagnostics
                )
                script += "\nsys.exit({})\n".format(status)
                output, errors = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(output), contextlib.redirect_stderr(
                    errors
                ):
                    if status:
                        with self.assertRaises(HELPER.CommandError) as raised:
                            HELPER.run_tofu_ui(
                                [sys.executable, "-c", script], "sandbox apply", 10
                            )
                        self.assertEqual(raised.exception.code, code)
                        self.assertEqual(raised.exception.transient, transient)
                    else:
                        HELPER.run_tofu_ui(
                            [sys.executable, "-c", script], "sandbox apply", 10
                        )
                self.assertNotIn(
                    "SENSITIVE_TEST_PAYLOAD", output.getvalue() + errors.getvalue()
                )
                for diagnostic in diagnostics:
                    self.assertIn(
                        "sandbox apply: {}:".format(diagnostic["severity"]),
                        errors.getvalue(),
                    )
                if diagnostics[0]["severity"] == "error":
                    self.assertNotIn("warning:", errors.getvalue())
                    self.assertNotIn("will be checked", errors.getvalue())

    def test_retry_uses_increasing_delays_and_fresh_plans(self):
        error = self.failure("DependencyViolation")
        helper = self.destroyer([error, error, error, None])
        ticks = [0]

        def sleep(seconds):
            ticks[0] += seconds

        with patch.object(
            HELPER.time, "monotonic", side_effect=lambda: ticks[0]
        ), patch.object(
            HELPER.time, "sleep", side_effect=sleep
        ) as sleeping, contextlib.redirect_stdout(
            io.StringIO()
        ):
            helper.destroy("sandbox")
        self.assertEqual(
            [call.args[0] for call in sleeping.call_args_list], [30, 60, 120]
        )
        self.assertEqual(helper.check_plan.call_count, 4)

    def test_retry_deadline_counts_time_inside_later_attempts(self):
        error = self.failure("DependencyViolation")
        ticks = [0]

        def fail_slowly(*args, **kwargs):
            ticks[0] += 301
            raise error

        helper = self.destroyer([])
        helper.check_plan.side_effect = fail_slowly
        with patch.object(
            HELPER.time, "monotonic", side_effect=lambda: ticks[0]
        ), patch.object(HELPER.time, "sleep") as sleeping, contextlib.redirect_stdout(
            io.StringIO()
        ):
            with self.assertRaises(HELPER.CommandError):
                helper.destroy("sandbox")
        self.assertEqual(helper.check_plan.call_count, 2)
        sleeping.assert_called_once_with(30)

        # A suspended machine can resume after the retry window has expired.
        ticks[0] = 0
        helper = self.destroyer([error, None])
        with patch.object(
            HELPER.time, "monotonic", side_effect=lambda: ticks[0]
        ), patch.object(
            HELPER.time, "sleep", side_effect=lambda _: ticks.__setitem__(0, 301)
        ), contextlib.redirect_stdout(
            io.StringIO()
        ):
            with self.assertRaises(HELPER.CommandError):
                helper.destroy("sandbox")
        self.assertEqual(helper.check_plan.call_count, 1)

    def test_mixed_permanent_errors_are_not_retried(self):
        helper = self.destroyer([self.failure("DependencyViolation", "AuthFailure")])
        with patch.object(HELPER.time, "sleep") as sleeping, contextlib.redirect_stdout(
            io.StringIO()
        ):
            with self.assertRaises(HELPER.CommandError):
                helper.destroy("sandbox")
        sleeping.assert_not_called()
        self.assertEqual(helper.check_plan.call_count, 1)
        misleading = HELPER.CommandError(
            "plan",
            subprocess.CompletedProcess(
                [], 1, "", "Error: Invalid variable named ResourceInUse"
            ),
        )
        self.assertFalse(misleading.transient)
        structured = HELPER.CommandError(
            "apply",
            subprocess.CompletedProcess([], 1, "", ""),
            diagnostics=[
                "api error DependencyViolation: pending",
                "Invalid configuration",
            ],
        )
        self.assertFalse(structured.transient)

    def test_progress_is_displayed_while_child_is_still_running(self):
        with tempfile.TemporaryDirectory() as directory:
            acknowledgement = Path(directory) / "displayed"
            progress = {
                "type": "apply_progress",
                "hook": {
                    "resource": {"addr": "terraform_data.probe"},
                    "elapsed_seconds": 1,
                },
            }
            hidden = {
                "type": "outputs",
                "outputs": {
                    "secret": {"sensitive": True, "value": "SENSITIVE_TEST_PAYLOAD"}
                },
            }
            script = "import time,sys\nfrom pathlib import Path\nprint({!r}, flush=True)\nprint({!r}, flush=True)\ndeadline=time.monotonic()+3\nwhile not Path({!r}).exists() and time.monotonic()<deadline: time.sleep(.01)\nsys.exit(0 if Path({!r}).exists() else 7)".format(
                json.dumps(progress),
                json.dumps(hidden),
                str(acknowledgement),
                str(acknowledgement),
            )

            class Display(io.StringIO):
                def write(self, text):
                    if "apply_progress" in text:
                        acknowledgement.write_text("displayed")
                    return super().write(text)

            output = Display()
            with contextlib.redirect_stdout(output):
                HELPER.run_tofu_ui([sys.executable, "-c", script], "sandbox apply", 10)
            self.assertTrue(acknowledgement.exists())
            self.assertNotIn("SENSITIVE_TEST_PAYLOAD", output.getvalue())

    @unittest.skipUnless(
        shutil.which("tofu"), "OpenTofu required for native JSON UI probe"
    )
    def test_native_tofu_json_ui_hides_sensitive_outputs(self):
        with tempfile.TemporaryDirectory(prefix="scaf-native-ui-") as directory:
            path = Path(directory)
            (path / "main.tf").write_text(
                'resource "terraform_data" "probe" { input = "safe" }\noutput "private" {\n value = "SENSITIVE_TEST_PAYLOAD"\n sensitive = true\n}\n'
            )
            env = {
                k: v
                for k, v in os.environ.items()
                if not k.startswith(("AWS_", "GH_", "GITHUB_", "TF_"))
            }
            command = [shutil.which("tofu"), "-chdir=" + directory]
            initialized = subprocess.run(
                [*command, "init", "-input=false"],
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(initialized.returncode, 0, initialized.stderr)
            output = io.StringIO()
            with patch.dict(os.environ, env, clear=True), contextlib.redirect_stdout(
                output
            ):
                HELPER.run_tofu_ui(
                    [*command, "plan", "-json", "-out=" + str(path / "plan")],
                    "probe plan",
                    30,
                )
                HELPER.run_tofu_ui(
                    [*command, "apply", "-json", str(path / "plan")], "probe apply", 30
                )
                HELPER.run_tofu_ui(
                    [
                        *command,
                        "plan",
                        "-destroy",
                        "-json",
                        "-out=" + str(path / "destroy"),
                    ],
                    "probe destroy plan",
                    30,
                )
                HELPER.run_tofu_ui(
                    [*command, "apply", "-json", str(path / "destroy")],
                    "probe destroy",
                    30,
                )
            empty = HELPER.decode_state(
                (path / "terraform.tfstate").read_text(), "native empty state"
            )
            self.assertEqual(HELPER.resources(empty, "native empty state"), [])
            self.assertIn("terraform_data.probe", output.getvalue())
            self.assertNotIn("SENSITIVE_TEST_PAYLOAD", output.getvalue())


if __name__ == "__main__":
    unittest.main()
