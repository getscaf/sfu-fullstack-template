"""Run the generated project's local Tilt verification in a disposable kind cluster."""

import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import ExitStack
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "e2e" / "reports"


def run_logged(command, log_path, env):
    with log_path.open("w", encoding="utf-8", buffering=1) as log:
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            start_new_session=True,
        )
        try:
            with process.stdout:
                for line in process.stdout:
                    log.write(line)
                    print(line, end="", flush=True)
            return process.wait()
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()


def forward_ports():
    with ExitStack() as sockets:
        ports = []
        for _ in range(2):
            listener = sockets.enter_context(socket.socket())
            listener.bind(("127.0.0.1", 0))
            ports.append(str(listener.getsockname()[1]))
        return ports


def collect_diagnostics(report_dir, env):
    kubectl = ["kubectl", "--context", env["SCAF_E2E_CONTEXT"], "--request-timeout=10s"]
    with (report_dir / "diagnostics.log").open("w", encoding="utf-8") as log:
        for args in (
            ["get", "pods,services,persistentvolumeclaims", "-o", "wide"],
            ["get", "events", "--sort-by=.lastTimestamp"],
            ["logs", "deployment/backend", "--all-containers", "--tail=100"],
            ["logs", "statefulset/postgres", "--all-containers", "--tail=100"],
            ["logs", "deployment/frontend", "--all-containers", "--tail=100"],
        ):
            if (
                args[0:2] == ["logs", "deployment/frontend"]
                and not (ROOT / "frontend" / "package.json").is_file()
            ):
                continue
            log.write(f"\n$ kubectl {' '.join(args)}\n")
            log.flush()
            try:
                subprocess.run(
                    kubectl + args,
                    env=env,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    timeout=15,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired) as error:
                log.write(f"{error}\n")


def verify(requirements):
    missing = [name for name in requirements if shutil.which(name) is None]
    if missing:
        print(f"Missing required programs: {', '.join(missing)}", file=sys.stderr)
        return 1
    for module in ("bs4", "httpx", "pytest", "pytest_jsonreport"):
        try:
            __import__(module)
        except ImportError as error:
            print(
                f"{error}. Install dependencies with python3 -m pip install "
                "-r e2e/requirements.txt.",
                file=sys.stderr,
            )
            return 1
    return 0


def delete_cluster(cluster, report_dir, env):
    try:
        status = run_logged(
            ["kind", "delete", "cluster", "--name", cluster],
            report_dir / "cleanup.log",
            env,
        )
    except KeyboardInterrupt:
        status = 130
    except OSError as error:
        print(f"E2E cleanup failed: {error}", file=sys.stderr)
        status = 1
    if status:
        print(
            f"Could not delete {cluster}. Retry with "
            f"kind delete cluster --name {cluster}",
            file=sys.stderr,
        )
    return status


def run_suite():
    if verify(("docker", "kind", "kubectl", "tilt")):
        return 1

    REPORTS.mkdir(parents=True, exist_ok=True)
    report_dir = Path(tempfile.mkdtemp(prefix="run-", dir=REPORTS))
    cluster = f"scaf-e2e-{uuid4().hex[:12]}"
    backend_port, frontend_port = forward_ports()
    print(f"E2E reports: {report_dir}", flush=True)

    with tempfile.TemporaryDirectory(prefix="scaf-e2e-") as temp_dir:
        kubeconfig = str(Path(temp_dir) / "kubeconfig")
        env = {
            **os.environ,
            "KUBECONFIG": kubeconfig,
            "SCAF_E2E_CONTEXT": f"kind-{cluster}",
            "SCAF_E2E_BACKEND_PORT": backend_port,
            "SCAF_E2E_FRONTEND_PORT": frontend_port,
            "SCAF_E2E_PYTHON": sys.executable,
            "SCAF_E2E_REPORT_DIR": str(report_dir),
        }
        status = 1
        try:
            status = run_logged(
                ["kind", "create", "cluster", "--name", cluster, "--wait", "120s"],
                report_dir / "kind.log",
                env,
            )
            if status == 0:
                status = run_logged(
                    [
                        "tilt",
                        "ci",
                        "--host=127.0.0.1",
                        "--port=0",
                        "--context",
                        env["SCAF_E2E_CONTEXT"],
                    ],
                    report_dir / "tilt.log",
                    env,
                )
        except KeyboardInterrupt:
            status = 130
        except OSError as error:
            print(f"E2E execution failed: {error}", file=sys.stderr)
            status = 1
        finally:
            try:
                if status and Path(kubeconfig).exists():
                    collect_diagnostics(report_dir, env)
            finally:
                cleanup = delete_cluster(cluster, report_dir, env)
                status = status or cleanup

    outcome = "failed" if status else "passed"
    print(f"E2E verification {outcome}. Reports: {report_dir}", flush=True)
    return status


def run_tests(args):
    import httpx

    report_dir = Path(os.environ["SCAF_E2E_REPORT_DIR"])
    urls = [f"http://127.0.0.1:{os.environ['SCAF_E2E_BACKEND_PORT']}/readiness"]
    if os.environ["SCAF_E2E_NEXTJS"] == "1":
        urls.append(f"http://127.0.0.1:{os.environ['SCAF_E2E_FRONTEND_PORT']}/")
    deadline = time.monotonic() + 120
    statuses = {}
    with httpx.Client(timeout=5, trust_env=False) as client:
        while time.monotonic() < deadline:
            for url in urls:
                try:
                    statuses[url] = client.get(url).status_code
                except httpx.RequestError as error:
                    statuses[url] = str(error)
            if all(status == 200 for status in statuses.values()):
                break
            time.sleep(1)
        else:
            print(f"Services did not become healthy: {statuses}", file=sys.stderr)
            return 1

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--json-report",
            f"--json-report-file={report_dir / 'test-report.json'}",
            *args,
            str(ROOT / "e2e" / "tests"),
        ],
        cwd=ROOT,
        check=False,
    )
    return result.returncode


def interrupt(signum, frame):
    raise KeyboardInterrupt


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, interrupt)
    if sys.argv[1:2] == ["test"]:
        sys.exit(run_tests(sys.argv[2:]))
    sys.exit(run_suite())
