"""Destroy a generated environment, including retries of an interrupted destroy.

Uses only the standard library and AWS/OpenTofu CLIs. Never prints state or raw
command output: both can contain credentials, even when the command failed.
"""

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

from .teardown_commands import CommandError, TeardownError, run, run_tofu_ui


def decode(text, label):
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        raise TeardownError(
            "Invalid JSON from {} (contents withheld)".format(label)
        ) from None


def decode_state(text, label):
    state = decode(text, label)
    if (
        not isinstance(state, dict)
        or not isinstance(state.get("serial"), int)
        or not isinstance(state.get("lineage"), str)
        or not state["lineage"]
    ):
        raise TeardownError("Missing state identity for {}".format(label))
    resources(state, label)
    return state


def hcl_source(text):
    """Mask comments/heredocs and identify quoted spans before literal lookup."""
    code, quoted = list(text), []
    special = re.compile(r'/\*|//|#|"|<<-?([A-Za-z_][A-Za-z_0-9-]*)[ \t]*\r?\n')
    position = 0
    while True:
        match = special.search(text, position)
        if not match:
            break
        start = match.start()
        if match[0] == '"':
            string = re.match(r'"(?:[^"\\\r\n]|\\[^\r\n])*"', text[start:])
            if not string:
                raise TeardownError("Cannot resolve configuration: unterminated string")
            token = string[0]
            # A quote inside a template expression needs a full HCL parser.
            # Reject it instead of treating its contents as configuration.
            for expression in re.finditer(r"[$%]\{", token):
                depth = 1
                for char in token[expression.end() : -1]:
                    if char == "{":
                        depth += 1
                    elif char == "}":
                        depth -= 1
                        if depth == 0:
                            break
                if depth:
                    raise TeardownError(
                        "Cannot resolve configuration: unsupported quoted template expression"
                    )
            position = start + len(token)
            quoted.append((start, position))
            continue
        if match[0] == "/*":
            end = text.find("*/", match.end())
            if end < 0:
                raise TeardownError(
                    "Cannot resolve configuration: unterminated comment"
                )
            position = end + 2
        elif match[1]:
            indent = r"[ \t]*" if match[0].startswith("<<-") else ""
            terminator = re.search(
                r"(?m)^" + indent + re.escape(match[1]) + r"[ \t]*\r?$",
                text[match.end() :],
            )
            if not terminator:
                raise TeardownError(
                    "Cannot resolve configuration: unterminated heredoc"
                )
            position = match.end() + terminator.end()
        else:
            end = text.find("\n", match.end())
            position = len(text) if end < 0 else end
        code[start:position] = [
            char if char in "\r\n" else " " for char in text[start:position]
        ]
    return "".join(code), quoted


def literal(text, block, field, required=True):
    """Read a literal from the generated HCL shape; never evaluate HCL code."""
    text, quoted_spans = hcl_source(text)
    matches = [
        match
        for match in re.finditer(block + r"\s*\{", text)
        if not any(start <= match.start() < end for start, end in quoted_spans)
    ]
    if len(matches) > 1:
        raise TeardownError("Cannot resolve configuration: ambiguous literal block")
    match = matches[0] if matches else None
    value = None
    if match:
        # Stop at the block boundary, allowing nested policy JSON/maps after
        # the generated literal fields. Only collect top-level attributes.
        depth, quoted, escaped = 1, False, False
        body = []
        for char in text[match.end() :]:
            if quoted:
                if depth == 1:
                    body.append(char)
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    quoted = False
            elif char == '"':
                quoted = True
                if depth == 1:
                    body.append(char)
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    break
            elif depth == 1:
                body.append(char)
        if depth:
            raise TeardownError(
                "Cannot resolve configuration: unterminated literal block"
            )
        entries = re.findall(
            r"(?m)^\s*"
            + re.escape(field)
            + r'\s*=\s*("(?:[^"\\]|\\.)*")\s*(?://.*|#.*)?$',
            "".join(body),
        )
        if len(entries) > 1:
            raise TeardownError(
                "Cannot resolve configuration: ambiguous literal attribute"
            )
        if entries:
            value = decode(entries[0], field)
            if "${" in value or "%{" in value:
                value = None
    if value is None and required:
        raise TeardownError(
            "Cannot resolve literal {} from configuration; no resources deleted".format(
                field
            )
        )
    return value


def resources(state, label):
    if (
        not isinstance(state, dict)
        or state.get("version") != 4
        or not isinstance(state.get("resources"), list)
    ):
        raise TeardownError("Unsupported/corrupt state for {}".format(label))
    found = []
    for item in state["resources"]:
        if not isinstance(item, dict):
            raise TeardownError("Invalid resource in {}".format(label))
        if item.get("mode") == "data":
            continue
        if item.get("mode") != "managed":
            raise TeardownError("Unsupported resource mode in {}".format(label))
        if not all(
            isinstance(item.get(key), str) for key in ("type", "name")
        ) or not isinstance(item.get("instances"), list):
            raise TeardownError("Invalid managed resource in {}".format(label))
        for instance in item.get("instances", []):
            if not isinstance(instance, dict):
                raise TeardownError("Invalid resource instance in {}".format(label))
            address = ".".join(
                filter(None, [item.get("module"), item["type"], item["name"]])
            )
            if "index_key" in instance:
                address += "[{}]".format(json.dumps(instance["index_key"]))
            attrs = instance.get("attributes")
            if not isinstance(attrs, dict) or not attrs.get("id"):
                raise TeardownError(
                    "Missing managed resource identity: {} in {}".format(address, label)
                )
            found.append({"address": address, "type": item["type"], "values": attrs})
    return found


class Teardown:
    def __init__(self, root, environment):
        self.root = Path(root).resolve()
        self.terraform = self.root / "terraform"
        self.environment = {"production": "prod"}.get(environment, environment)
        if self.environment not in ("sandbox", "staging", "prod"):
            raise TeardownError("Environment must be sandbox, staging, or production")
        if self.environment == "prod":
            raise TeardownError("Production teardown remains disabled")
        config = (self.terraform / "modules/global_variables/main.tf").read_text()
        self.account = literal(config, r'output\s+"account_id"', "value")
        self.application_region = literal(config, r'output\s+"aws_region"', "value")
        policy_path = self.terraform / self.environment / "teardown-policy.json"
        self.disposable = False
        if self.environment == "sandbox" and policy_path.is_file():
            policy = decode(policy_path.read_text(), "sandbox teardown policy")
            if (
                not isinstance(policy, dict)
                or type(policy.get("disposable")) is not bool
            ):
                raise TeardownError(
                    "Sandbox teardown policy must declare a boolean disposable"
                )
            self.disposable = policy["disposable"]
        self.backends = {}
        for stack in ("sandbox", "staging", "prod", "github"):
            file = (
                self.terraform
                / stack
                / ("oidc.tf" if stack == "github" else "backend.tf")
            )
            if file.exists():
                self.backends[stack] = self.backend(stack, file.read_text())
        self.backend_config = self.backends[self.environment]
        targets = [(b["bucket"], b["key"], b["region"]) for b in self.backends.values()]
        if len(targets) != len(set(targets)):
            raise TeardownError(
                "Multiple stacks point to the same state object; resolve backend configuration first"
            )
        self.backend_region = self.backend_config["region"]
        self.bucket = self.backend_config["bucket"]
        if os.environ.get("TF_WORKSPACE", "default") != "default":
            raise TeardownError(
                "Select the default workspace; additional workspaces are retained, not guessed"
            )
        self.phase = "preflight"
        self.environment_resources = []
        self.storage_owners = {}
        self.approved = {}

    def data_dir(self, stack):
        configured = Path(os.environ.get("TF_DATA_DIR", ".terraform"))
        return (
            configured
            if configured.is_absolute()
            else self.terraform / stack / configured
        )

    def backend(self, stack, text):
        fields = ("bucket", "key", "region", "dynamodb_table")
        result = {
            key: literal(text, r'backend\s+"s3"', key, required=False) for key in fields
        }
        meta = self.data_dir(stack) / "terraform.tfstate"
        if meta.exists():
            value = decode(meta.read_text(), "initialized backend").get("backend", {})
            if value.get("type") != "s3":
                raise TeardownError(
                    "Unsupported initialized backend for {}".format(stack)
                )
            result.update(
                {
                    key: value["config"][key]
                    for key in fields
                    if value.get("config", {}).get(key) is not None
                }
            )
        workspace = self.data_dir(stack) / "environment"
        if workspace.exists() and workspace.read_text().strip() != "default":
            raise TeardownError("Non-default workspace configured for {}".format(stack))
        if not all(
            isinstance(result.get(key), str) and result[key]
            for key in ("bucket", "key", "region")
        ):
            raise TeardownError("Incomplete backend for {}".format(stack))
        return result

    def aws(self, service, operation, *args, region=None):
        output = run(
            [
                "aws",
                "--region",
                region or self.application_region,
                "--output",
                "json",
                "--no-cli-pager",
                "--no-paginate",
                service,
                operation,
                *args,
            ]
        )
        return decode(output or "{}", "AWS {} {}".format(service, operation))

    def tofu(self, *args):
        stack = self.environment
        if args[0] in ("init", "plan", "apply"):
            return run_tofu_ui(
                [
                    "tofu",
                    "-chdir={}".format(self.terraform / stack),
                    args[0],
                    *(["-json"] if args[0] != "init" else []),
                    *args[1:],
                ],
                "{} {}".format(stack, args[0]),
                7200 if args[0] == "apply" else 300,
            )
        return run(["tofu", "-chdir={}".format(self.terraform / stack), *args])

    def bucket_exists(self, bucket, region):
        try:
            result = self.aws(
                "s3api",
                "get-bucket-location",
                "--bucket",
                bucket,
                "--expected-bucket-owner",
                self.account,
                region=region,
            )
        except CommandError as error:
            if error.code == "NoSuchBucket":
                return False
            raise
        location = result.get("LocationConstraint") or "us-east-1"
        if {"EU": "eu-west-1"}.get(location, location) != region:
            raise TeardownError(
                "Bucket {} is in a different region than configured".format(bucket)
            )
        return True

    def read_remote(self, backend):
        try:
            text = run(
                [
                    "aws",
                    "--region",
                    backend["region"],
                    "--no-cli-pager",
                    "s3",
                    "cp",
                    "s3://{}/{}".format(backend["bucket"], backend["key"]),
                    "-",
                    "--only-show-errors",
                ]
            )
        except CommandError as error:
            if error.code in ("NoSuchKey", "404"):
                return {"version": 4, "resources": []}
            raise
        state = decode_state(text, backend["key"])
        return state

    def validate_account(self, items):
        for item in items:
            arn = item["values"].get("arn") or ""
            if arn.startswith("arn:"):
                account = arn.split(":")[4]
                if account and account != self.account:
                    raise TeardownError(
                        "State contains a resource from another AWS account: {}".format(
                            item["address"]
                        )
                    )

    def bucket_identity(self, item):
        return item["values"].get("bucket") or item["values"]["id"]

    def storage_identity(self, item):
        if item["type"] == "aws_s3_bucket":
            return ("S3", self.bucket_identity(item))
        if item["type"] == "aws_ecr_repository":
            return (
                "ECR",
                self.account,
                self.resource_region(item),
                item["values"].get("name") or item["values"]["id"],
            )
        return None

    def check_storage_ownership(self, selected):
        backend_buckets = {backend["bucket"] for backend in self.backends.values()}
        for item in selected:
            identity = self.storage_identity(item)
            if identity is None:
                continue
            if identity[0] == "S3" and identity[1] in backend_buckets:
                raise TeardownError(
                    "S3 ownership overlaps with a configured state backend; resolve ownership before teardown"
                )
            owner = self.storage_owners.get(identity)
            if owner:
                raise TeardownError(
                    "{} ownership overlaps with {}; resolve ownership before teardown".format(
                        identity[0], owner
                    )
                )

    def index_storage_owners(self, backend, label):
        items = resources(self.read_remote(backend), label)
        self.validate_account(items)
        for item in items:
            identity = self.storage_identity(item)
            if identity is not None:
                self.storage_owners.setdefault(identity, label)

    def inspect(self):
        if self.aws("sts", "get-caller-identity").get("Account") != self.account:
            raise TeardownError(
                "AWS caller account does not match project configuration"
            )
        if not self.bucket_exists(self.bucket, self.backend_region):
            raise TeardownError(
                "State backend bucket is missing; cannot verify environment teardown"
            )
        selected = self.read_remote(self.backend_config)
        if "serial" not in selected:
            raise TeardownError(
                "Environment has no recorded state; cannot verify teardown"
            )
        items = resources(selected, self.environment)
        self.validate_account(items)
        if not items:
            print(
                "Environment teardown already complete; shared GitHub and bootstrap retained."
            )
            return False
        self.inspect_other_states()
        self.check_storage_ownership(items)
        stack = self.environment
        self.tofu("init", "-input=false", "-no-color")
        fresh = self.pull()
        outputs = fresh.get("outputs")
        policy = (
            outputs.get("teardown_disposable") if isinstance(outputs, dict) else None
        )
        applied = policy.get("value") if isinstance(policy, dict) else None
        self.applied_disposable = applied is True
        # An explicitly protected deployment overrides a disposable checkout.
        self.disposable = self.disposable and applied is not False
        items = resources(fresh, stack)
        self.environment_resources = items
        self.validate_account(items)
        self.check_storage_ownership(items)
        for item in items:
            self.approved.setdefault(item["address"], set()).add(item["values"]["id"])
        self.check_plan()
        return True

    def inspect_other_states(self):
        buckets = {}
        for stack, backend in self.backends.items():
            if stack != self.environment:
                self.index_storage_owners(backend, stack)
            buckets.setdefault((backend["bucket"], backend["region"]), backend)
        for (bucket, region), backend in buckets.items():
            known = {b["key"] for b in self.backends.values() if b["bucket"] == bucket}
            cursor = []
            while True:
                page = self.aws(
                    "s3api",
                    "list-objects-v2",
                    "--bucket",
                    bucket,
                    "--expected-bucket-owner",
                    self.account,
                    *cursor,
                    region=region,
                )
                for obj in page.get("Contents", []):
                    key = obj["Key"]
                    if key not in known:
                        self.index_storage_owners(
                            dict(backend, key=key), "extra:" + bucket + "/" + key
                        )
                if not page.get("IsTruncated"):
                    break
                token = page.get("NextContinuationToken")
                if not token or cursor == ["--continuation-token", token]:
                    raise TeardownError(
                        "Cannot finish listing backend bucket {}".format(bucket)
                    )
                cursor = ["--continuation-token", token]

    def pull(self):
        return decode_state(
            self.tofu("state", "pull"), "{} state".format(self.environment)
        )

    def check_plan(self, apply=False):
        with tempfile.TemporaryDirectory(prefix="scaf-destroy-") as directory:
            plan = str(Path(directory) / "destroy.tfplan")
            self.tofu("plan", "-destroy", "-input=false", "-no-color", "-out=" + plan)
            value = decode(self.tofu("show", "-json", plan), "destroy plan")
            planned = []
            for change in value.get("resource_changes", []):
                if change.get("mode") == "data":
                    if change["change"]["actions"] not in (
                        ["read"],
                        ["no-op"],
                        ["delete"],
                    ):
                        raise TeardownError(
                            "Unexpected data-source action in {}".format(
                                self.environment
                            )
                        )
                    continue
                action = change["change"]
                identities = self.approved.get(change["address"], set())
                if (
                    action["actions"] not in (["delete"], ["no-op"])
                    or (action.get("before") or {}).get("id") not in identities
                ):
                    raise TeardownError(
                        "Destroy plan expands approved scope or mutates a resource: {}".format(
                            change["address"]
                        )
                    )
                if action["actions"] == ["delete"]:
                    planned.append(
                        {
                            "address": change["address"],
                            "type": change["type"],
                            "values": action["before"],
                        }
                    )
            self.validate_account(planned)
            self.check_storage_ownership(planned)
            self.check_deletion_policy(planned)
            if apply:
                self.tofu("apply", "-input=false", "-no-color", plan)

    def check_deletion_policy(self, planned):
        blocked = []
        lock_tables = {
            (b.get("dynamodb_table"), b["region"]) for b in self.backends.values()
        }
        for item in planned:
            kind, values = item["type"], item["values"]
            address = item["address"]
            if (
                kind == "aws_dynamodb_table"
                and (values["id"], self.resource_region(item)) in lock_tables
            ):
                raise TeardownError(
                    "Destroy plan includes a configured backend lock table"
                )
            if kind == "aws_secretsmanager_secret":
                if not self.disposable and values.get("recovery_window_in_days") == 0:
                    raise TeardownError(
                        "{} would be deleted without a recovery window".format(address)
                    )
                continue
            if kind not in ("aws_s3_bucket", "aws_ecr_repository"):
                continue
            flag = "force_destroy" if kind == "aws_s3_bucket" else "force_delete"
            if values.get(flag) is True:
                if not self.disposable:
                    raise TeardownError(
                        "{} enables {}; protected teardown cannot proceed".format(
                            address, flag
                        )
                    )
                continue
            region = self.resource_region(item)
            if kind == "aws_s3_bucket":
                name = self.bucket_identity(item)
                if self.bucket_contains_data(name, region):
                    blocked.append("S3 bucket {}".format(name))
            else:
                name = values.get("name") or values["id"]
                if self.repository_contains_images(name, region):
                    blocked.append("ECR repository {}".format(name))
        if blocked:
            raise TeardownError(
                "Non-empty protected storage: {}. Review and clear its contents separately before retrying".format(
                    ", ".join(blocked)
                )
            )

    def bucket_contains_data(self, name, region):
        try:
            versions = self.aws(
                "s3api",
                "list-object-versions",
                "--bucket",
                name,
                "--max-keys",
                "1",
                "--expected-bucket-owner",
                self.account,
                region=region,
            )
            if versions.get("Versions") or versions.get("DeleteMarkers"):
                return True
            current = self.aws(
                "s3api",
                "list-objects-v2",
                "--bucket",
                name,
                "--max-keys",
                "1",
                "--expected-bucket-owner",
                self.account,
                region=region,
            )
            return bool(current.get("Contents"))
        except CommandError as error:
            if error.code == "NoSuchBucket":
                return False
            raise

    def repository_contains_images(self, name, region):
        try:
            result = self.aws(
                "ecr",
                "list-images",
                "--registry-id",
                self.account,
                "--repository-name",
                name,
                "--max-results",
                "1",
                region=region,
            )
            return bool(result.get("imageIds"))
        except CommandError as error:
            if error.code == "RepositoryNotFoundException":
                return False
            raise

    def confirm(self):
        print(
            "Teardown {} in account {}, region {}".format(
                self.environment, self.account, self.application_region
            )
        )
        if self.backend_region != self.application_region:
            print("State backend region: {}".format(self.backend_region))
        for address in sorted(self.approved):
            print("  delete {}: {}".format(self.environment, address))
        for item in self.environment_resources:
            if item["type"] in ("aws_s3_bucket", "aws_ecr_repository", "aws_instance"):
                print("    {}: {}".format(item["address"], item["values"]["id"]))
        print("Shared GitHub resources, state bucket and lock table will be retained.")
        if self.disposable:
            print(
                "Disposable sandbox: Terraform can permanently delete media, backups, images and cluster secrets."
            )
            if (
                self.applied_disposable
                and os.environ.get("TEARDOWN_AUTO_APPROVE") == "1"
            ):
                print("Approved by TEARDOWN_AUTO_APPROVE=1 for the disposable sandbox")
                return
        try:
            answer = input("Type '{}' to continue: ".format(self.environment))
        except EOFError:
            answer = ""
        if answer != self.environment:
            raise TeardownError(
                "Teardown cancelled; no destructive operations performed"
            )

    def resource_region(self, item):
        if item["type"] == "aws_s3_bucket" and item["values"].get("region"):
            return item["values"]["region"]
        arn = item["values"].get("arn") or ""
        return (
            arn.split(":")[3] if arn.startswith("arn:") else ""
        ) or self.application_region

    def stop_nodes(self):
        for item in self.environment_resources:
            if item["type"] != "aws_instance":
                continue
            identity = item["values"]["id"]
            region = self.resource_region(item)
            deadline = time.monotonic() + 300
            requested = False
            observed = None
            print("Checking node {} in {}".format(identity, region), flush=True)
            while True:
                try:
                    response = self.aws(
                        "ec2",
                        "describe-instances",
                        "--instance-ids",
                        identity,
                        region=region,
                    )
                except CommandError as error:
                    if error.code == "InvalidInstanceID.NotFound":
                        print(
                            "Node {} in {}: absent".format(identity, region), flush=True
                        )
                        break
                    raise
                instances = [
                    i
                    for reservation in response.get("Reservations", [])
                    for i in reservation.get("Instances", [])
                ]
                state = instances[0]["State"]["Name"] if instances else "absent"
                if state != observed:
                    print(
                        "Node {} in {}: {}".format(identity, region, state), flush=True
                    )
                    observed = state
                if state in ("absent", "stopped", "terminated"):
                    break
                if not requested and state not in (
                    "stopping",
                    "shutting-down",
                ):
                    self.aws(
                        "ec2",
                        "stop-instances",
                        "--instance-ids",
                        identity,
                        region=region,
                    )
                    requested = True
                    continue
                if time.monotonic() >= deadline:
                    raise TeardownError(
                        "Timed out waiting for node {} to stop; teardown can be retried".format(
                            identity
                        )
                    )
                time.sleep(2)

    def destroy(self):
        stack = self.environment
        self.phase = "destroy {}".format(stack)
        print("Destroying remaining resources: {}".format(stack))
        delays = (30, 60, 120)
        deadline = None
        for attempt in range(len(delays) + 1):
            try:
                self.check_plan(apply=True)
                break
            except CommandError as error:
                now = time.monotonic()
                if deadline is None:
                    deadline = now + 300
                if (
                    not error.transient
                    or attempt == len(delays)
                    or now + delays[attempt] >= deadline
                ):
                    raise
                print(
                    "Waiting for AWS dependency cleanup before replanning {} (retry in {}s)".format(
                        stack, delays[attempt]
                    ),
                    flush=True,
                )
                time.sleep(delays[attempt])
                if time.monotonic() >= deadline:
                    raise
        if resources(self.pull(), stack):
            raise TeardownError(
                "Managed resources remain in {}; backend preserved".format(stack)
            )

    def execute(self):
        if not self.inspect():
            return
        self.phase = "confirmation"
        self.confirm()
        self.phase = "node shutdown"
        self.stop_nodes()
        self.destroy()
        print(
            "Environment teardown completed for {}; shared GitHub and bootstrap retained.".format(
                self.environment
            )
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    teardown = None
    try:
        for executable in ("aws", "tofu"):
            if not shutil.which(executable):
                raise TeardownError("{} is required".format(executable))
        teardown = Teardown(root, args.environment)
        teardown.execute()
    except (TeardownError, OSError) as error:
        # OSError filenames are safe; command output/state are never included.
        print(
            "Teardown stopped during {}: {}. Fix the problem and rerun the same command.".format(
                teardown.phase if teardown else "preflight", error
            ),
            file=sys.stderr,
        )
        return 1
    except KeyboardInterrupt:
        print(
            "Teardown interrupted during {}; rerun the same command to inspect remaining state.".format(
                teardown.phase if teardown else "preflight"
            ),
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
