"""Run AWS and OpenTofu commands without exposing raw diagnostics or state."""

import json
import os
import re
import selectors
import subprocess
import sys
import time


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
