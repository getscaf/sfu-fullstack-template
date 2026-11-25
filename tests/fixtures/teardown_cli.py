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
    return (
        scenario["bootstrap"]
        if stack == "bootstrap"
        else scenario["remote"].get(
            scenario["keys"][stack], {"version": 4, "resources": []}
        )
    )


def write_state(stack, state):
    if stack == "bootstrap":
        scenario["bootstrap"] = state
        (PATH.parent / "project/terraform/bootstrap/terraform.tfstate").write_text(
            json.dumps(state)
        )
    else:
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
            chunk = entries[start : start + 1000]
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
            chunk = entries[start : start + 1000]
            result = {
                "Contents": [{"Key": key} for key in chunk],
                "IsTruncated": start + len(chunk) < len(entries),
            }
            if result["IsTruncated"]:
                result["NextContinuationToken"] = chunk[-1]
            emit(result)
        if operation == "delete-objects":
            payload = option("--delete")
            if payload.startswith("file://"):
                payload = Path(payload.removeprefix("file://")).read_text()
                call = scenario["calls"][-1]
                call[call.index("--delete") + 1] = payload
            objects = json.loads(payload)["Objects"]
            assert len(objects) <= 1000
            if scenario.get("object_error"):
                emit({"Errors": [{"Key": "private", "Code": "AccessDenied"}]})
            for item in objects:
                key = item["Key"]
                bucket["versions"] = [
                    v
                    for v in bucket["versions"]
                    if not (
                        v["Key"] == key
                        and (
                            "VersionId" not in item
                            or v["VersionId"] == item["VersionId"]
                        )
                    )
                ]
                bucket["objects"] = [v for v in bucket["objects"] if v != key]
                if name == scenario["state_bucket"]:
                    scenario["remote"].pop(key, None)
            emit({})
    if service == "ecr":
        name = option("--repository-name") or option("--repository-names")
        if name not in scenario["repositories"]:
            fail("RepositoryNotFoundException")
        if operation == "delete-repository":
            if "--force" not in args:
                fail("RepositoryNotEmptyException")
            scenario["repositories"].remove(name)
            emit({})
        if operation == "describe-repositories":
            emit({"repositories": [{"repositoryName": name}]})
        if operation == "list-images":
            # Legacy cleanup can miss images; reproduce the original failure
            # at native destroy rather than supplying the fixed cleanup path.
            emit([])
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
            scenario["nodes"][identity] = "stopped"
            emit({})
    if service == "secretsmanager":
        name = option("--secret-id")
        name = next(
            (
                k
                for k, v in scenario["secrets"].items()
                if k == name or v["ARN"] == name
            ),
            name,
        )
        if (
            name not in scenario["secrets"]
            and operation == "delete-secret"
            and "--force-delete-without-recovery" in args
        ):
            emit({})
        if name not in scenario["secrets"]:
            fail("ResourceNotFoundException")
        if operation == "describe-secret":
            emit(scenario["secrets"][name])
        if operation == "delete-secret":
            del scenario["secrets"][name]
            emit({})
    if service == "iam" and operation == "list-roles":
        start = int(option("--marker", "0"))
        chunk = scenario["roles"][start : start + 2]
        more = start + len(chunk) < len(scenario["roles"])
        result = {"Roles": chunk, "IsTruncated": more}
        if more:
            result["Marker"] = str(start + len(chunk))
        emit(result)
    if service == "dynamodb":
        if not scenario["table_exists"]:
            fail("ResourceNotFoundException")
        emit({"Table": {"TableName": option("--table-name")}})
elif tool == "tofu":
    stack_path = (
        Path(args.pop(0).split("=", 1)[1])
        if args[0].startswith("-chdir=")
        else Path.cwd()
    )
    stack = stack_path.name
    action = args[0]
    state = state_for(stack)
    if action == "init":
        (stack_path / ".terraform").mkdir(exist_ok=True)
        emit({})
    if action == "output":
        outputs = dict(state.get("outputs", {}))
        for item in state.get("resources", []):
            if item["type"] == "aws_ecr_repository":
                outputs["backend_ecr_repo"] = {
                    "value": "123456789012.dkr.ecr.us-east-1.amazonaws.com/"
                    + item["instances"][0]["attributes"]["id"]
                }
        emit(outputs)
    if action == "state" and args[1] == "pull":
        emit(state)
    if action == "plan":
        if stack == "github" and scenario.get("github_error"):
            fail("GitHubLookupFailed")
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
            address = ".".join(
                filter(
                    None, [resource.get("module"), resource["type"], resource["name"]]
                )
            )
            changes.append(
                {
                    "address": address,
                    "mode": "managed",
                    "change": {
                        "actions": ["delete"],
                        "before": resource["instances"][0]["attributes"],
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
            identity = resource["instances"][0]["attributes"]["id"]
            if resource["type"] == "aws_s3_bucket":
                bucket = scenario["buckets"].get(identity)
                if bucket and (
                    bucket["versions"]
                    or bucket["objects"]
                    or (identity == scenario["state_bucket"] and scenario["remote"])
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
                fail("RepositoryNotEmptyException")
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
elif tool == "gh":
    if scenario.get("github_error"):
        fail("GitHubLookupFailed")
    emit({"owner": "example", "name": "project", "owner_id": "1", "repository_id": "2"})
fail("UnexpectedFakeCommand")
