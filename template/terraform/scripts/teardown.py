#!/usr/bin/env python3
"""Destroy a generated environment, including retries of an interrupted destroy.

Uses only the standard library and AWS/OpenTofu CLIs. Never prints state or raw
command output: both can contain credentials, even when the command failed.
"""

import argparse
import json
import os
import re
import selectors
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import unquote


class TeardownError(Exception):
    pass


RETRYABLE_CODES = frozenset(
    (
        "DependencyViolation",
        "ResourceInUse",
        "ResourceInUseException",
        "Throttling",
        "ThrottlingException",
        "RequestLimitExceeded",
        "TooManyRequestsException",
        "PriorRequestNotComplete",
    )
)
SAFE_SUMMARIES = frozenset(
    (
        "External Program Execution Failed",
        "Resource postcondition failed",
        "Resource precondition failed",
        "Error acquiring the state lock",
        "Unsupported argument",
        "Missing required argument",
        "Unsupported attribute",
        "Reference to undeclared resource",
        "Reference to undeclared input variable",
        "Invalid value for input variable",
        "Invalid provider configuration",
        "Failed to load plugin schemas",
        "Failed to query available provider packages",
        "Error in function call",
        "Provider produced inconsistent final plan",
    )
)


def error_codes(text):
    matches = re.findall(
        r"An error occurred \(([A-Za-z0-9_.-]+)\)|api error ([A-Za-z0-9_.-]+):", text
    )
    return {value for pair in matches for value in pair if value}


def diagnostic_summary(diagnostic):
    """Never render arbitrary provider detail, expression snippets, or outputs."""
    severity = diagnostic.get("severity")
    level = severity if severity in ("warning", "error") else "diagnostic"
    summary = diagnostic.get("summary", "")
    safe = summary if summary in SAFE_SUMMARIES else "OpenTofu diagnostic"
    elb_warning = severity == "warning" and summary.startswith(
        "cleaning up ELB Classic Load Balancer ("
    )
    if elb_warning:
        safe = "ELB ENI cleanup"
    detail = str(diagnostic.get("detail", ""))
    codes = error_codes(summary + "\n" + detail)
    if codes:
        safe += " ({})".format(", ".join(sorted(codes)))
    if elb_warning:
        safe += "; remaining managed resources will be checked before completion"
    if summary == "External Program Execution Failed":
        safe += (
            "; check external-program authentication and configured repository access"
        )
    location = diagnostic.get("range") or {}
    filename = location.get("filename")
    line = (location.get("start") or {}).get("line")
    if isinstance(filename, str) and isinstance(line, int):
        safe += " at {}:{}".format(filename, line)
    return "{}: {}".format(level, safe)


class CommandError(TeardownError):
    def __init__(self, operation, result, diagnostics=None):
        errors = diagnostics if diagnostics is not None else [result.stderr]
        groups = [error_codes(text) for text in errors]
        codes = set().union(*groups) if groups else set()
        self.code = ", ".join(sorted(codes)) if codes else "CommandFailed"
        self.transient = bool(groups) and all(
            group and group <= RETRYABLE_CODES for group in groups
        )
        summaries = [
            s
            for s in SAFE_SUMMARIES
            if re.search(r"(?m)^Error: " + re.escape(s) + r"\s*$", result.stderr)
        ]
        message = "{} failed ({})".format(operation, self.code)
        if summaries:
            message += ": " + "; ".join(sorted(summaries))
        super().__init__(message)


def run_tofu_ui(args, label, timeout):
    """Read OpenTofu's JSON UI, exposing only progress and safe diagnostics.

    Both pipes are merged so neither can deadlock. Raw lines stay in memory and
    never become log output; JSON output values and provisioner logs are ignored.
    """
    print("Starting {}".format(label), flush=True)
    started = time.monotonic()
    heartbeat = started + 15
    errors, opaque = [], []

    def consume(raw):
        line = raw.decode("utf-8", errors="replace")
        try:
            event = json.loads(line)
        except ValueError:
            if line.strip():
                opaque.append(line)
            return
        if not isinstance(event, dict):
            return
        kind = event.get("type")
        if kind == "version" and str(event.get("ui", "")).split(".")[0] != "1":
            raise TeardownError("Unsupported OpenTofu UI version")
        if kind in (
            "apply_start",
            "apply_progress",
            "apply_complete",
            "apply_errored",
            "refresh_start",
            "refresh_complete",
        ):
            hook = event.get("hook") or {}
            address = (hook.get("resource") or {}).get("addr")
            elapsed = hook.get("elapsed_seconds")
            if isinstance(address, str):
                suffix = (
                    " ({}s)".format(elapsed)
                    if isinstance(elapsed, (int, float))
                    else ""
                )
                print("{}: {} {}{}".format(label, address, kind, suffix), flush=True)
        elif kind == "change_summary":
            changes = event.get("changes") or {}
            if all(
                isinstance(changes.get(k), int) for k in ("add", "change", "remove")
            ):
                print(
                    "{}: {} add, {} change, {} destroy".format(
                        label, changes["add"], changes["change"], changes["remove"]
                    ),
                    flush=True,
                )
        elif kind == "diagnostic":
            diagnostic = event.get("diagnostic") or {}
            if diagnostic.get("severity") == "error":
                errors.append(
                    str(diagnostic.get("summary", ""))
                    + "\n"
                    + str(diagnostic.get("detail", ""))
                )
            print(
                "{}: {}".format(label, diagnostic_summary(diagnostic)),
                file=sys.stderr,
                flush=True,
            )

    process = None
    selector = selectors.DefaultSelector()
    try:
        process = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env={**os.environ, "AWS_PAGER": "", "TF_INPUT": "0"},
        )
        selector.register(process.stdout, selectors.EVENT_READ)
        pending = b""
        while selector.get_map():
            now = time.monotonic()
            if now - started >= timeout:
                raise TeardownError(
                    "{} timed out; rerun teardown to inspect remaining state".format(
                        label
                    )
                )
            if now >= heartbeat:
                print(
                    "{} still running ({}s elapsed)".format(label, int(now - started)),
                    flush=True,
                )
                heartbeat = now + 15
            for key, _ in selector.select(timeout=min(1, timeout - (now - started))):
                chunk = os.read(key.fd, 65536)
                if not chunk:
                    selector.unregister(key.fileobj)
                    if pending:
                        consume(pending)
                    break
                pending += chunk
                while b"\n" in pending:
                    line, pending = pending.split(b"\n", 1)
                    consume(line)
        code = process.wait(timeout=max(1, timeout - (time.monotonic() - started)))
        if code:
            result = subprocess.CompletedProcess(args, code, "", "\n".join(opaque))
            raise CommandError(label, result, diagnostics=errors + opaque)
    except (OSError, subprocess.TimeoutExpired):
        raise TeardownError(
            "{} could not complete; check command availability/connectivity".format(
                label
            )
        ) from None
    finally:
        selector.close()
        if process is not None:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            process.stdout.close()
    return ""


def run(args, cwd=None, timeout=300):
    try:
        result = subprocess.run(
            [str(arg) for arg in args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            env={**os.environ, "AWS_PAGER": "", "TF_INPUT": "0"},
        )
    except (OSError, subprocess.TimeoutExpired):
        raise TeardownError(
            "{} could not complete; check availability/connectivity".format(args[0])
        ) from None
    if result.returncode:
        operation = " ".join(str(a) for a in args[:3])
        if args[0] == "aws":
            services = (
                "s3api",
                "s3",
                "ec2",
                "ecr",
                "iam",
                "sts",
                "secretsmanager",
                "dynamodb",
            )
            position = next((i for i, arg in enumerate(args) if arg in services), None)
            if position is not None:
                operation = "aws " + " ".join(args[position : position + 2])
        raise CommandError(operation, result)
    return result.stdout


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


def literal(text, block, field, required=True):
    """Read a literal from the generated HCL shape; never evaluate HCL code."""
    match = re.search(block + r"\s*\{", text)
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
        entry = re.search(
            r"(?m)^\s*"
            + re.escape(field)
            + r'\s*=\s*("(?:[^"\\]|\\.)*")\s*(?://.*|#.*)?$',
            "".join(body),
        )
        if entry:
            value = decode(entry[1], field)
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
        self.application = literal(config, r'output\s+"application"', "value")
        github = (self.terraform / "github/oidc.tf").read_text()
        role = literal(
            github, r'resource\s+"aws_iam_role"\s+"github_oidc_role"', "name"
        )
        self.slug = role.removesuffix("-github-oidc-role")
        cluster = (self.root / "bootstrap-cluster/Taskfile.yml").read_text()
        modes = re.findall(r"(?m)^  (k3s|talos):\s*$", cluster)
        if len(modes) != 1:
            raise TeardownError("Cannot determine configured cluster OS")
        self.os = modes[0]
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
        self.region = self.backend_config["region"]
        self.bucket = self.backend_config["bucket"]
        self.table = self.backend_config.get("dynamodb_table")
        if not self.table:
            raise TeardownError("Cannot resolve the configured bootstrap lock table")
        if os.environ.get("TF_WORKSPACE", "default") != "default":
            raise TeardownError(
                "Select the default workspace; additional workspaces are retained, not guessed"
            )
        self.states = {}
        self.approved = {}
        self.keep = []
        self.keep_bootstrap = []
        self.secrets = []
        self.retained_secrets = []

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
                region or self.region,
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

    def tofu(self, stack, *args):
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
        return run(
            ["tofu", "-chdir={}".format(self.terraform / stack), *args],
            timeout=7200 if args[0] == "apply" else 300,
        )

    def pages(self, service, operation, *args, region=None):
        token_args = []
        while True:
            page = self.aws(service, operation, *args, *token_args, region=region)
            yield page
            if page.get("IsTruncated"):
                if operation == "list-object-versions":
                    token_args = ["--key-marker", page["NextKeyMarker"]]
                    if page.get("NextVersionIdMarker"):
                        token_args += [
                            "--version-id-marker",
                            page["NextVersionIdMarker"],
                        ]
                elif page.get("NextContinuationToken"):
                    token_args = ["--continuation-token", page["NextContinuationToken"]]
                else:
                    token_args = ["--marker", page.get("Marker") or page["NextMarker"]]
            else:
                break

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

    def local_bootstrap(self, required=True):
        workspace = self.data_dir("bootstrap") / "environment"
        if workspace.exists() and workspace.read_text().strip() != "default":
            raise TeardownError(
                "Bootstrap recovery requires the original default workspace"
            )
        path = self.terraform / "bootstrap/terraform.tfstate"
        metadata = self.data_dir("bootstrap") / "terraform.tfstate"
        if metadata.exists():
            backend = decode(metadata.read_text(), "bootstrap backend").get(
                "backend", {}
            )
            if backend.get("type") != "local":
                raise TeardownError(
                    "Bootstrap recovery requires its original local backend"
                )
            configured = backend.get("config", {}).get("path")
            if configured:
                path = Path(configured)
                if not path.is_absolute():
                    path = self.terraform / "bootstrap" / path
        if not path.is_file():
            if not required:
                self.keep_bootstrap.append("original local bootstrap state is missing")
                return {"version": 4, "resources": []}
            raise TeardownError(
                "Original local bootstrap state is missing; restore it before teardown"
            )
        state = decode_state(path.read_text(), "local bootstrap state")
        self.validate_bootstrap(state)
        return state

    def validate_bootstrap(self, state):
        for item in resources(state, "bootstrap"):
            attrs = item["values"]
            if item["type"] in ("aws_s3_bucket", "aws_s3_bucket_versioning"):
                if (attrs.get("bucket") or attrs["id"]) != self.bucket:
                    raise TeardownError(
                        "Local bootstrap bucket does not match the configured backend"
                    )
            if (
                item["type"] == "aws_dynamodb_table"
                and (attrs.get("name") or attrs["id"]) != self.table
            ):
                raise TeardownError(
                    "Local bootstrap table does not match the configured backend"
                )

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

    def repository_identity(self, item):
        return (
            self.account,
            self.resource_region(item),
            item["values"].get("name") or item["values"]["id"],
        )

    def check_ecr_ownership(self, selected):
        selected_repos = {
            self.repository_identity(r)
            for r in selected
            if r["type"] == "aws_ecr_repository"
        }
        for stack, state in self.states.items():
            if stack in (self.environment, "github", "bootstrap"):
                continue
            other = {
                self.repository_identity(r)
                for r in resources(state, stack)
                if r["type"] == "aws_ecr_repository"
            }
            if selected_repos & other:
                raise TeardownError(
                    "ECR ownership overlaps with {}; resolve ownership before teardown".format(
                        stack
                    )
                )

    def inspect(self):
        if self.aws("sts", "get-caller-identity").get("Account") != self.account:
            raise TeardownError(
                "AWS caller account does not match project configuration"
            )
        self.backend_present = self.bucket_exists(self.bucket, self.region)
        self.states["bootstrap"] = self.local_bootstrap(
            required=not self.backend_present
        )
        bootstrap_items = resources(self.states["bootstrap"], "bootstrap")
        if self.backend_present and not any(
            item["type"] == "aws_s3_bucket" for item in bootstrap_items
        ):
            if not self.keep_bootstrap:
                self.keep_bootstrap.append(
                    "local bootstrap state does not track aws_s3_bucket"
                )
        # Retained bootstrap needs no additional IAM/DynamoDB inspection. Only
        # require those permissions when this run will actually finalize it.
        if not self.keep_bootstrap:
            self.table_present = self.table_exists()
            if self.table_present and not any(
                item["type"] == "aws_dynamodb_table" for item in bootstrap_items
            ):
                if not self.backend_present:
                    raise TeardownError(
                        "A live backend resource is missing from local bootstrap state; restore the original state"
                    )
                self.keep_bootstrap.append(
                    "local bootstrap state does not track aws_dynamodb_table"
                )
        if not self.backend_present:
            return self.prepare_bootstrap_recovery()
        for stack, backend in self.backends.items():
            self.states[stack] = self.read_remote(backend)
        known = {b["key"] for b in self.backends.values() if b["bucket"] == self.bucket}
        for page in self.pages(
            "s3api",
            "list-objects-v2",
            "--bucket",
            self.bucket,
            "--expected-bucket-owner",
            self.account,
        ):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                if key in known:
                    continue
                # Backend/workspace keys have no required filename suffix.
                extra = dict(self.backend_config, key=key)
                self.states["extra:" + key] = self.read_remote(extra)
                self.keep.append("unclassified backend entry {}".format(key))
        selected = resources(self.states[self.environment], self.environment)
        self.check_ecr_ownership(selected)
        for stack, state in self.states.items():
            items = resources(state, stack)
            self.validate_account(items)
            if stack in (self.environment, "github", "bootstrap"):
                continue
            if items:
                self.keep.append("active state {}".format(stack))
        if not self.keep:
            # Avoid initializing a GitHub stack already known to be shared.
            self.inspect_oidc()
        self.inspect_secrets()
        stacks = [self.environment]
        if not self.keep:
            stacks += ["github"]
            if not self.keep_bootstrap:
                stacks += ["bootstrap"]
        for stack in stacks:
            if self.keep and stack in ("github", "bootstrap"):
                continue
            self.approve_stack(stack)
        return True

    def inspect_oidc(self):
        items = resources(
            self.states.get("github", {"version": 4, "resources": []}), "github"
        )
        providers = {
            r["values"].get("arn") or r["values"]["id"]
            for r in items
            if r["type"] == "aws_iam_openid_connect_provider"
        }
        if not providers:
            return
        own_roles = {
            r["values"].get("arn") for r in items if r["type"] == "aws_iam_role"
        }
        for page in self.pages("iam", "list-roles"):
            for role in page.get("Roles", []):
                if role.get("Arn") in own_roles:
                    continue
                policy = role.get("AssumeRolePolicyDocument", {})
                if isinstance(policy, str):
                    policy = decode(unquote(policy), "IAM trust policy")

                def references(value):
                    if isinstance(value, str):
                        return value in providers
                    if isinstance(value, dict):
                        return any(references(v) for v in value.values())
                    if isinstance(value, list):
                        return any(references(v) for v in value)
                    return False

                if references(policy):
                    reason = "OIDC provider used by role {}".format(role["Arn"])
                    if reason not in self.keep:
                        self.keep.append(reason)

    def inspect_secrets(self):
        names = [self.slug + "_" + self.environment + "_kubeconfig"]
        if self.os == "talos":
            names = [
                self.environment + suffix
                for suffix in (
                    "_kubeconfig",
                    "_talosconfig_yaml",
                    "_talos_controlplane_yaml",
                )
            ]
        for name in names:
            try:
                value = self.aws(
                    "secretsmanager", "describe-secret", "--secret-id", name
                )
            except CommandError as error:
                if error.code == "ResourceNotFoundException":
                    continue
                raise
            tags = {t["Key"]: t["Value"] for t in value.get("Tags", [])}
            if self.os == "talos" and not (
                tags.get("application") == self.application
                and tags.get("environment") == self.environment
            ):
                self.retained_secrets.append(name)
            else:
                self.secrets.append(value["ARN"])

    def pull(self, stack):
        state = decode_state(
            self.tofu(stack, "state", "pull"), "{} state".format(stack)
        )
        return state

    def approve_stack(self, stack):
        items = resources(self.states[stack], stack)
        self.validate_account(items)
        if not items:
            return
        if (
            stack == "github"
            and '"gh"' in (self.terraform / "github/oidc.tf").read_text()
            and not shutil.which("gh")
        ):
            raise TeardownError("gh is required for the remaining GitHub destroy plan")
        self.tofu(stack, "init", "-input=false", "-no-color")
        fresh = self.pull(stack)
        self.validate_account(resources(fresh, stack))
        if stack == "bootstrap":
            self.validate_bootstrap(fresh)
        if stack == self.environment:
            self.check_ecr_ownership(resources(fresh, stack))
        self.states[stack] = fresh
        if stack == "github":
            # Keep the second guard: it checks freshly pulled ownership, not
            # the earlier remote snapshot used to schedule the stack.
            self.inspect_oidc()
            if self.keep:
                return
        approved = {}
        for item in resources(fresh, stack):
            approved.setdefault(item["address"], set()).add(item["values"]["id"])
        self.approved[stack] = approved
        self.check_plan(stack)

    def check_plan(self, stack, apply=False):
        with tempfile.TemporaryDirectory(prefix="scaf-destroy-") as directory:
            plan = str(Path(directory) / "destroy.tfplan")
            self.tofu(
                stack, "plan", "-destroy", "-input=false", "-no-color", "-out=" + plan
            )
            value = decode(self.tofu(stack, "show", "-json", plan), "destroy plan")
            for change in value.get("resource_changes", []):
                if change.get("mode") == "data":
                    if change["change"]["actions"] not in (
                        ["read"],
                        ["no-op"],
                        ["delete"],
                    ):
                        raise TeardownError(
                            "Unexpected data-source action in {}".format(stack)
                        )
                    continue
                action = change["change"]
                identities = self.approved[stack].get(change["address"], set())
                if (
                    action["actions"] not in (["delete"], ["no-op"])
                    or (action.get("before") or {}).get("id") not in identities
                ):
                    raise TeardownError(
                        "Destroy plan expands approved scope or mutates a resource: {}".format(
                            change["address"]
                        )
                    )
            if apply:
                self.tofu(stack, "apply", "-input=false", "-no-color", plan)

    def prepare_bootstrap_recovery(self):
        items = resources(self.states["bootstrap"], "bootstrap")
        self.validate_account(items)
        if not items:
            self.inspect_secrets()
            print(
                "Teardown already complete for the known backend scope; bucket and table are absent."
            )
            for name in self.retained_secrets:
                print("Legacy secret preserved (ownership unverified): {}".format(name))
            return False
        print(
            "Backend bucket is absent; recovering only resources in local bootstrap state."
        )
        self.approve_stack("bootstrap")
        return True

    def table_exists(self):
        try:
            self.aws("dynamodb", "describe-table", "--table-name", self.table)
        except CommandError as error:
            if error.code == "ResourceNotFoundException":
                return False
            raise
        return True

    def verify_backend_absent(self):
        if self.bucket_exists(self.bucket, self.region) or self.table_exists():
            raise TeardownError(
                "Backend resources still exist; teardown is not complete"
            )

    def confirm(self):
        print(
            "Teardown {} in account {}, region {}".format(
                self.environment, self.account, self.region
            )
        )
        for stack, addresses in self.approved.items():
            for address in sorted(addresses):
                print("  delete {}: {}".format(stack, address))
            for item in resources(self.states[stack], stack):
                if item["type"] in (
                    "aws_s3_bucket",
                    "aws_ecr_repository",
                    "aws_instance",
                    "aws_dynamodb_table",
                    "aws_iam_openid_connect_provider",
                ):
                    print("    {}: {}".format(item["type"], item["values"]["id"]))
        for secret in self.secrets:
            print("  delete secret: {}".format(secret))
        for reason in self.keep:
            print("  retain GitHub/bootstrap: {}".format(reason))
        for reason in self.keep_bootstrap:
            print("  retain bootstrap: {}".format(reason))
        for secret in self.retained_secrets:
            print("  retain unverified legacy secret: {}".format(secret))
        print(
            "This permanently deletes selected media, backups, container images, and infrastructure."
        )
        if os.environ.get("TERRAFORM_AUTO_APPROVE") == "1":
            print("Approved by TERRAFORM_AUTO_APPROVE=1")
            return
        try:
            answer = input("Type 'yes' to continue: ")
        except EOFError:
            answer = ""
        if answer != "yes":
            raise TeardownError(
                "Teardown cancelled; no destructive operations performed"
            )

    def resource_region(self, item):
        if item["type"] == "aws_s3_bucket" and item["values"].get("region"):
            return item["values"]["region"]
        arn = item["values"].get("arn") or ""
        return (arn.split(":")[3] if arn.startswith("arn:") else "") or self.region

    def stop_nodes(self):
        for item in resources(self.states[self.environment], self.environment):
            if item["type"] != "aws_instance":
                continue
            identity = item["values"]["id"]
            region = self.resource_region(item)
            deadline = time.monotonic() + 300
            requested = False
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
                        break
                    raise
                instances = [
                    i
                    for reservation in response.get("Reservations", [])
                    for i in reservation.get("Instances", [])
                ]
                if not instances or instances[0]["State"]["Name"] in (
                    "stopped",
                    "terminated",
                ):
                    break
                if not requested and instances[0]["State"]["Name"] not in (
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

    def delete_objects(self, bucket, objects, region):
        for offset in range(0, len(objects), 1000):
            payload = json.dumps(
                {"Objects": objects[offset : offset + 1000], "Quiet": True}
            )
            # Long S3 keys can exceed OS argument-size limits even in one batch.
            with tempfile.TemporaryDirectory(prefix="scaf-s3-delete-") as directory:
                request = Path(directory) / "delete.json"
                request.write_text(payload)
                result = self.aws(
                    "s3api",
                    "delete-objects",
                    "--bucket",
                    bucket,
                    "--expected-bucket-owner",
                    self.account,
                    "--delete",
                    "file://" + str(request),
                    region=region,
                )
            if result.get("Errors"):
                codes = sorted({e.get("Code", "Unknown") for e in result["Errors"]})
                raise TeardownError(
                    "S3 deletion failed in {} ({})".format(bucket, ", ".join(codes))
                )

    def empty_bucket(self, bucket, region):
        if not self.bucket_exists(bucket, region):
            return
        for _ in range(3):
            found_objects = False
            for operation, collections, attributes in (
                (
                    "list-object-versions",
                    ("Versions", "DeleteMarkers"),
                    ("Key", "VersionId"),
                ),
                ("list-objects-v2", ("Contents",), ("Key",)),
            ):
                pages = iter(
                    self.pages(
                        "s3api",
                        operation,
                        "--bucket",
                        bucket,
                        "--expected-bucket-owner",
                        self.account,
                        "--max-keys",
                        "1000",
                        region=region,
                    )
                )
                page = next(pages, None)
                while page is not None:
                    # Resolve the next cursor while this page still exists.
                    # Only the current and next pages are retained in memory.
                    following = next(pages, None)
                    objects = [
                        {attribute: entry[attribute] for attribute in attributes}
                        for collection in collections
                        for entry in page.get(collection, [])
                    ]
                    self.delete_objects(bucket, objects, region)
                    found_objects = found_objects or bool(objects)
                    page = following
            if not found_objects:
                print("Bucket empty: {}".format(bucket))
                return
        raise TeardownError(
            "Bucket {} keeps refilling; stop external writers and retry".format(bucket)
        )

    def cleanup(self):
        for item in resources(self.states[self.environment], self.environment):
            attrs = item["values"]
            region = self.resource_region(item)
            if item["type"] == "aws_s3_bucket":
                self.empty_bucket(attrs.get("bucket") or attrs["id"], region)
            elif item["type"] == "aws_ecr_repository":
                name = attrs.get("name") or attrs["id"]
                try:
                    self.aws(
                        "ecr",
                        "delete-repository",
                        "--registry-id",
                        self.account,
                        "--repository-name",
                        name,
                        "--force",
                        region=region,
                    )
                except CommandError as error:
                    if error.code != "RepositoryNotFoundException":
                        raise
                try:
                    self.aws(
                        "ecr",
                        "describe-repositories",
                        "--registry-id",
                        self.account,
                        "--repository-names",
                        name,
                        region=region,
                    )
                except CommandError as error:
                    if error.code == "RepositoryNotFoundException":
                        continue
                    raise
                raise TeardownError(
                    "ECR repository still exists after deletion: {}".format(name)
                )
        for secret in self.secrets:
            try:
                self.aws(
                    "secretsmanager",
                    "delete-secret",
                    "--secret-id",
                    secret,
                    "--force-delete-without-recovery",
                )
            except CommandError as error:
                if error.code != "ResourceNotFoundException":
                    raise

    def destroy(self, stack):
        if stack not in self.approved:
            return
        print("Destroying remaining resources: {}".format(stack))
        delays = (30, 60, 120)
        deadline = None
        for attempt in range(len(delays) + 1):
            try:
                self.check_plan(stack, apply=True)
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
        if resources(self.pull(stack), stack):
            raise TeardownError(
                "Managed resources remain in {}; backend preserved".format(stack)
            )

    def execute(self):
        if not self.inspect():
            return
        self.confirm()
        if self.backend_present:
            self.stop_nodes()
            self.cleanup()
            self.destroy(self.environment)
            if not self.keep:
                self.destroy("github")
            if not self.keep and not self.keep_bootstrap:
                # Recheck remote state before permanently erasing its versions.
                for backend in self.backends.values():
                    if resources(self.read_remote(backend), backend["key"]):
                        raise TeardownError(
                            "Dependent state is not empty; backend preserved"
                        )
                self.empty_bucket(self.bucket, self.region)
                self.destroy("bootstrap")
                self.verify_backend_absent()
        else:
            self.destroy("bootstrap")
            self.verify_backend_absent()
        if self.keep:
            print(
                "Environment teardown completed; shared GitHub/bootstrap infrastructure retained."
            )
        elif self.keep_bootstrap:
            print(
                "Environment/GitHub teardown completed; bootstrap retained: {}.".format(
                    "; ".join(self.keep_bootstrap)
                )
            )
        else:
            print("Infrastructure teardown completed for {}.".format(self.environment))
        for secret in self.retained_secrets:
            print("Legacy secret preserved (ownership unverified): {}".format(secret))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    try:
        for executable in ("aws", "tofu"):
            if not shutil.which(executable):
                raise TeardownError("{} is required".format(executable))
        Teardown(root, args.environment).execute()
    except (TeardownError, OSError) as error:
        # OSError filenames are safe; command output/state are never included.
        print(
            "Teardown stopped: {}. Fix the problem and rerun the same command.".format(
                error
            ),
            file=sys.stderr,
        )
        return 1
    except KeyboardInterrupt:
        print(
            "Teardown interrupted; rerun the same command to inspect remaining state.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
