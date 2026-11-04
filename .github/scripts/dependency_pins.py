"""Update one dependency stream without modifying another stream's files."""

import argparse
import json
import re
import subprocess
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GROUPS = ("frontend-runtime", "backend-runtime", "python", "frontend-packages")


def fetch(url):
    with urllib.request.urlopen(url, timeout=60) as response:
        return response.read().decode()


def node_version(releases):
    versions = [
        release["version"].removeprefix("v")
        for release in releases
        if release["lts"] and re.fullmatch(r"v\d+\.\d+\.\d+", release["version"])
    ]
    if not versions:
        raise ValueError("No stable Node.js LTS release found")
    return max(versions, key=lambda version: tuple(map(int, version.split("."))))


def python_version(metadata, current_tag):
    current = re.fullmatch(r"(\d+\.\d+)(?:\.\d+)?(-slim-\w+)", current_tag)
    if not current:
        raise ValueError(f"Unsupported Python image tag: {current_tag}")
    minor, suffix = current.groups()
    tags = [
        tag.strip()
        for line in metadata.splitlines()
        if line.startswith("Tags: ")
        for tag in line[6:].split(",")
        if re.fullmatch(re.escape(minor) + r"\.\d+" + re.escape(suffix), tag.strip())
    ]
    if not tags:
        raise ValueError(f"No stable Python image found for {minor}{suffix}")
    return max(tags, key=lambda tag: int(tag.split("-")[0].split(".")[-1]))


def replace(path, pattern, replacement):
    original = path.read_text()
    updated, count = re.subn(pattern, replacement, original)
    if not count:
        raise ValueError(f"No version reference matched in {path}")
    path.write_text(updated)


def write_node_version(root, version):
    template = root / "template"
    (template / ".node-version").write_text(version + "\n")
    for path in ("frontend/Dockerfile", "bitbucket-pipelines.yml"):
        replace(
            template / path, r"node:\d+\.\d+\.\d+-bookworm", f"node:{version}-bookworm"
        )
    replace(template / "flake.nix", r"nodejs_\d+", f'nodejs_{version.split(".")[0]}')


def update_python_runtime(root):
    template = root / "template"
    current = re.search(
        r"FROM python:(\S+)", (template / "backend/Dockerfile").read_text()
    ).group(1)
    metadata = fetch(
        "https://raw.githubusercontent.com/docker-library/official-images/master/library/python"
    )
    tag = python_version(metadata, current)
    for path in ("backend/Dockerfile", "bitbucket-pipelines.yml"):
        replace(template / path, "python:" + re.escape(current), f"python:{tag}")
    (template / ".python-version").write_text(tag.split("-")[0] + "\n")


def update_frontend_packages(root):
    # Start fresh to upgrade transitive dependencies too. Never run lifecycle
    # scripts while resolving, and never rewrite the template's package.json.
    manifest = json.loads((root / "template/frontend/package.json").read_text())
    name = manifest["name"]
    manifest["name"] = "scaf-template"
    with tempfile.TemporaryDirectory() as directory:
        workdir = Path(directory)
        (workdir / "package.json").write_text(json.dumps(manifest, indent=2) + "\n")
        subprocess.run(
            [
                "npm",
                "install",
                "--package-lock-only",
                "--ignore-scripts",
                "--no-audit",
                "--no-fund",
            ],
            cwd=workdir,
            check=True,
        )
        lock = json.loads((workdir / "package-lock.json").read_text())
    lock["name"] = name
    lock["packages"][""]["name"] = name
    (root / "template/frontend/package-lock.json").write_text(
        json.dumps(lock, indent=2) + "\n"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("group", choices=GROUPS)
    args = parser.parse_args()
    if args.group == "frontend-runtime":
        write_node_version(
            ROOT, node_version(json.loads(fetch("https://nodejs.org/dist/index.json")))
        )
    elif args.group == "backend-runtime":
        update_python_runtime(ROOT)
    elif args.group == "python":
        from python_locks import update_locks

        update_locks(ROOT)
    else:
        update_frontend_packages(ROOT)


if __name__ == "__main__":
    main()
