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
                "sts",
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
        self.states = {}
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

    def repository_identity(self, item):
        return (
            self.account,
            self.resource_region(item),
            item["values"].get("name") or item["values"]["id"],
        )

    def bucket_identity(self, item):
        return item["values"].get("bucket") or item["values"]["id"]

    def check_storage_ownership(self, selected):
        selected_repos = {
            self.repository_identity(r)
            for r in selected
            if r["type"] == "aws_ecr_repository"
        }
        selected_buckets = {
            self.bucket_identity(r) for r in selected if r["type"] == "aws_s3_bucket"
        }
        backend_buckets = {backend["bucket"] for backend in self.backends.values()}
        if selected_buckets & backend_buckets:
            raise TeardownError(
                "S3 ownership overlaps with a configured state backend; resolve ownership before teardown"
            )
        for stack, state in self.states.items():
            if stack == self.environment:
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
            other_buckets = {
                self.bucket_identity(r)
                for r in resources(state, stack)
                if r["type"] == "aws_s3_bucket"
            }
            if selected_buckets & other_buckets:
                raise TeardownError(
                    "S3 ownership overlaps with {}; resolve ownership before teardown".format(
                        stack
                    )
                )

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
        self.states[self.environment] = selected
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
        self.tofu(stack, "init", "-input=false", "-no-color")
        fresh = self.pull(stack)
        self.states[stack] = fresh
        items = resources(fresh, stack)
        self.validate_account(items)
        self.check_storage_ownership(items)
        approved = {}
        for item in items:
            approved.setdefault(item["address"], set()).add(item["values"]["id"])
        self.approved[stack] = approved
        self.check_plan(stack)
        return True

    def inspect_other_states(self):
        buckets = {}
        for stack, backend in self.backends.items():
            if stack != self.environment:
                self.states[stack] = self.read_remote(backend)
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
                        self.states["extra:" + bucket + "/" + key] = self.read_remote(
                            dict(backend, key=key)
                        )
                if not page.get("IsTruncated"):
                    break
                token = page.get("NextContinuationToken")
                if not token or cursor == ["--continuation-token", token]:
                    raise TeardownError(
                        "Cannot finish listing backend bucket {}".format(bucket)
                    )
                cursor = ["--continuation-token", token]
        for stack, state in self.states.items():
            self.validate_account(resources(state, stack))

    def pull(self, stack):
        state = decode_state(
            self.tofu(stack, "state", "pull"), "{} state".format(stack)
        )
        return state

    def check_plan(self, stack, apply=False):
        with tempfile.TemporaryDirectory(prefix="scaf-destroy-") as directory:
            plan = str(Path(directory) / "destroy.tfplan")
            self.tofu(
                stack, "plan", "-destroy", "-input=false", "-no-color", "-out=" + plan
            )
            value = decode(self.tofu(stack, "show", "-json", plan), "destroy plan")
            planned = []
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
                self.tofu(stack, "apply", "-input=false", "-no-color", plan)

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
        for address in sorted(self.approved[self.environment]):
            print("  delete {}: {}".format(self.environment, address))
        for item in resources(self.states[self.environment], self.environment):
            if item["type"] in ("aws_s3_bucket", "aws_ecr_repository", "aws_instance"):
                print("    {}: {}".format(item["address"], item["values"]["id"]))
        print("Shared GitHub resources, state bucket and lock table will be retained.")
        if self.disposable:
            print(
                "Disposable sandbox: Terraform can permanently delete media, backups, images and cluster secrets."
            )
            if os.environ.get("TEARDOWN_AUTO_APPROVE") == "1":
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
        for item in resources(self.states[self.environment], self.environment):
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

    def destroy(self, stack):
        if stack not in self.approved:
            return
        self.phase = "destroy {}".format(stack)
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
        self.phase = "confirmation"
        self.confirm()
        self.phase = "node shutdown"
        self.stop_nodes()
        self.destroy(self.environment)
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
