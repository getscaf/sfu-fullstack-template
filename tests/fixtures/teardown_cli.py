"""Persistent fake CLIs for teardown tests. Never delegates to a real service."""

import json
import os
import sys
from pathlib import Path

PATH = Path(os.environ["TEARDOWN_SCENARIO"])
scenario = json.loads(PATH.read_text())
tool = Path(sys.argv[0]).name
args = sys.argv[1:]
scenario["calls"].append([tool, *args])


def save():
    PATH.write_text(json.dumps(scenario))


def emit_diagnostics():
    for diagnostic in scenario.get("diagnostics", {}).get(args[0], []):
        print(json.dumps({"type": "diagnostic", "diagnostic": diagnostic}), flush=True)


def emit(value):
    save()
    if tool == "tofu" and "-json" in args and args[0] in ("plan", "apply"):
        print(json.dumps({"type": "version", "ui": "1.0"}), flush=True)
        emit_diagnostics()
        kind = "apply_progress" if args[0] == "apply" else "refresh_start"
        print(
            json.dumps(
                {
                    "type": kind,
                    "hook": {
                        "resource": {
                            "addr": "module.cluster.aws_cloudfront_distribution.distribution"
                        },
                        "action": "delete",
                        "elapsed_seconds": 10,
                    },
                }
            ),
            flush=True,
        )
        print(
            json.dumps(
                {
                    "type": "outputs",
                    "outputs": {
                        "secret": {"sensitive": True, "value": "SENSITIVE_TEST_PAYLOAD"}
                    },
                }
            ),
            flush=True,
        )
        raise SystemExit(0)
    print(json.dumps(value))
    raise SystemExit(0)


def fail(code):
    save()
    if tool == "tofu" and "-json" in args:
        emit_diagnostics()
        summary = (
            "External Program Execution Failed"
            if code == "GitHubLookupFailed"
            else "Error deleting resource"
        )
        print(
            json.dumps(
                {
                    "type": "diagnostic",
                    "diagnostic": {
                        "severity": "error",
                        "summary": summary,
                        "detail": "api error {}: SENSITIVE_TEST_PAYLOAD".format(code),
                        "range": {"filename": "oidc.tf", "start": {"line": 25}},
                    },
                }
            ),
            flush=True,
        )
    print("An error occurred ({}) SENSITIVE_TEST_PAYLOAD".format(code), file=sys.stderr)
    raise SystemExit(1)


def option(flag, default=None):
    return args[args.index(flag) + 1] if flag in args else default


def state_for(stack):
    return scenario["remote"].get(
        scenario["keys"][stack], {"version": 4, "resources": []}
    )


def write_state(stack, state):
    scenario["remote"][scenario["keys"][stack]] = state


if tool == "aws":
    while args and args[0].startswith("--"):
        arg = args.pop(0)
        if arg in ("--region", "--profile", "--output"):
            args.pop(0)
    service, operation = args[:2]
    if service == "configure":
        save()
        raise SystemExit(0)
    error = scenario.get("errors", {}).get(service + "/" + operation)
    if error:
        fail(error)
    if service == "sts":
        emit({"Account": scenario.get("caller", "123456789012")})
    if service == "s3":
        uri = args[2]
        bucket, key = uri.removeprefix("s3://").split("/", 1)
        if bucket not in scenario["buckets"]:
            fail("NoSuchBucket")
        if key not in scenario["remote"]:
            fail("404")
        emit(scenario["remote"][key])
    if service == "s3api":
        name = option("--bucket")
        if name not in scenario["buckets"]:
            fail("NoSuchBucket")
        bucket = scenario["buckets"][name]
        if operation == "head-bucket":
            emit({})
        if operation == "get-bucket-location":
            emit({"LocationConstraint": bucket.get("region")})
        if operation == "list-object-versions":
            entries = sorted(bucket["versions"], key=lambda value: value["Key"])
            start = 0
            marker = option("--key-marker")
            if marker is not None:
                version = option("--version-id-marker")
                try:
                    start = next(
                        index + 1
                        for index, value in enumerate(entries)
                        if value["Key"] == marker and value["VersionId"] == version
                    )
                except StopIteration:
                    fail("InvalidPaginationMarker")
            chunk = entries[start : start + int(option("--max-keys", "1000"))]
            result = {
                "Versions": [v for v in chunk if not v.get("DeleteMarker")],
                "DeleteMarkers": [v for v in chunk if v.get("DeleteMarker")],
                "IsTruncated": start + len(chunk) < len(entries),
            }
            if result["IsTruncated"]:
                result["NextKeyMarker"] = chunk[-1]["Key"]
                result["NextVersionIdMarker"] = chunk[-1]["VersionId"]
            emit(result)
        if operation == "list-objects-v2":
            entries = list(bucket["objects"])
            if name == scenario["state_bucket"]:
                entries += list(scenario["remote"])
            entries = sorted(set(entries))
            start = 0
            marker = option("--continuation-token")
            if marker is not None:
                try:
                    start = entries.index(marker) + 1
                except ValueError:
                    fail("InvalidPaginationMarker")
            chunk = entries[start : start + int(option("--max-keys", "1000"))]
            result = {
                "Contents": [{"Key": key} for key in chunk],
                "IsTruncated": start + len(chunk) < len(entries),
            }
            if result["IsTruncated"]:
                result["NextContinuationToken"] = chunk[-1]
            emit(result)
    if service == "ecr" and operation == "list-images":
        name = option("--repository-name")
        if name not in scenario["repositories"]:
            fail("RepositoryNotFoundException")
        emit(
            {
                "imageIds": (
                    [{"imageTag": "populated"}] if name in scenario["images"] else []
                )
            }
        )
    if service == "ec2":
        identity = option("--instance-ids")
        if identity not in scenario["nodes"]:
            fail("InvalidInstanceID.NotFound")
        if operation == "describe-instances":
            emit(
                {
                    "Reservations": [
                        {
                            "Instances": [
                                {
                                    "InstanceId": identity,
                                    "State": {"Name": scenario["nodes"][identity]},
                                }
                            ]
                        }
                    ]
                }
            )
        if operation == "stop-instances":
            if scenario.get("stop_errors", {}).get(identity):
                fail(scenario["stop_errors"][identity])
            scenario["nodes"][identity] = "stopped"
            emit({})
    if service == "secretsmanager":
        secret = scenario["secrets"].get(option("--secret-id"))
        if secret is None:
            fail("ResourceNotFoundException")
        if operation == "put-secret-value":
            secret["value"] = option("--secret-string")
            emit({})
        if operation == "get-secret-value":
            save()
            print(secret["value"])
            raise SystemExit(0)
elif tool == "tofu":
    stack_path = (
        Path(args.pop(0).split("=", 1)[1])
        if args[0].startswith("-chdir=")
        else Path.cwd()
    )
    stack = stack_path.name
    action = args[0]
    state = state_for(stack)
    if action == "output" and args[1:] == ["-json", "cluster_secret_arns"]:
        emit(state["outputs"]["cluster_secret_arns"]["value"])
    if action == "init":
        (stack_path / ".terraform").mkdir(exist_ok=True)
        emit({})
    if action == "state" and args[1] == "pull":
        emit(state)
    if action == "plan":
        remaining = []
        for resource in state.get("resources", []):
            identity = resource["instances"][0]["attributes"]["id"]
            if (
                resource["type"] in ("aws_ecr_repository", "aws_ecr_lifecycle_policy")
                and identity not in scenario["repositories"]
            ):
                continue
            if (
                resource["type"] in ("aws_s3_bucket", "aws_s3_bucket_versioning")
                and identity not in scenario["buckets"]
            ):
                continue
            remaining.append(resource)
        changes = []
        for resource in remaining:
            before = resource["instances"][0]["attributes"]
            address = ".".join(
                filter(
                    None, [resource.get("module"), resource["type"], resource["name"]]
                )
            )
            changes.append(
                {
                    "address": address,
                    "type": resource["type"],
                    "mode": "managed",
                    "change": {
                        "actions": ["delete"],
                        "before": before,
                    },
                }
            )
        changes += [
            {
                "address": "data.external.lookup",
                "mode": "data",
                "change": {"actions": ["read"]},
            }
        ]
        count = scenario.setdefault("plans", {})
        count[stack] = count.get(stack, 0) + 1
        if scenario.get("action_override") and changes:
            changes[0]["change"]["actions"] = scenario["action_override"]
        if scenario.get("expand_scope") and (
            not scenario.get("expand_after_preflight") or count[stack] > 1
        ):
            changes.append(
                {
                    "address": "aws_instance.unapproved",
                    "mode": "managed",
                    "change": {"actions": ["delete"], "before": {"id": "i-other"}},
                }
            )
        path = next(a.split("=", 1)[1] for a in args if a.startswith("-out="))
        Path(path).write_text(
            json.dumps({"resource_changes": changes, "remaining": remaining})
        )
        emit({})
    if action == "show":
        emit(json.loads(Path(args[-1]).read_text()))
    if action == "apply":
        plan = json.loads(Path(args[-1]).read_text())
        pending = list(plan["remaining"])
        interrupted = scenario.get("fail_apply", {}).get(stack, 0) > 0
        if interrupted:
            scenario["fail_apply"][stack] -= 1
        deleted = []
        for resource in pending:
            attrs = resource["instances"][0]["attributes"]
            identity = attrs["id"]
            if resource["type"] == "aws_s3_bucket":
                bucket = scenario["buckets"].get(identity)
                if (
                    not attrs.get("force_destroy")
                    and bucket
                    and (
                        bucket["versions"]
                        or bucket["objects"]
                        or (identity == scenario["state_bucket"] and scenario["remote"])
                    )
                ):
                    write_state(
                        stack,
                        {
                            **state,
                            "resources": [r for r in pending if r not in deleted],
                            "outputs": {},
                        },
                    )
                    fail("BucketNotEmpty")
                scenario["buckets"].pop(identity, None)
            if (
                resource["type"] == "aws_ecr_repository"
                and identity in scenario["repositories"]
            ):
                if identity in scenario["images"] and not attrs.get("force_delete"):
                    fail("RepositoryNotEmptyException")
                scenario["repositories"].remove(identity)
                if identity in scenario["images"]:
                    scenario["images"].remove(identity)
            if resource["type"] == "aws_secretsmanager_secret":
                days = attrs["recovery_window_in_days"]
                if days:
                    scenario["secrets"][identity]["scheduled_recovery_days"] = days
                else:
                    del scenario["secrets"][identity]
            if resource["type"] == "aws_instance":
                scenario["nodes"].pop(identity, None)
            if resource["type"] == "aws_dynamodb_table":
                scenario["table_exists"] = False
            deleted.append(resource)
            if interrupted:
                break
        state = {
            **state,
            "resources": [r for r in pending if r not in deleted],
            "outputs": {},
        }
        write_state(stack, state)
        if interrupted:
            fail("InjectedInterruption")
        emit({})
fail("UnexpectedFakeCommand")
