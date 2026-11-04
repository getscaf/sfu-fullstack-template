import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / ".github/scripts"))
import dependency_pins as pins


class RuntimePinsTests(unittest.TestCase):
    def runtime_fixture(self, directory):
        root = Path(directory)
        source = Path(__file__).resolve().parents[1]
        for name in (
            "backend/Dockerfile",
            "frontend/Dockerfile",
            "bitbucket-pipelines.yml",
            "flake.nix",
            ".python-version",
            ".node-version",
        ):
            target = root / "template" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / "template" / name, target)
        return root

    def test_python_updates_both_stages_and_ci_without_changing_node(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.runtime_fixture(directory)
            with patch.object(
                pins, "fetch", return_value="Tags: 3.13.99-slim-bookworm"
            ):
                pins.update_python_runtime(root)
                first = {
                    path.relative_to(root): path.read_bytes()
                    for path in root.rglob("*")
                    if path.is_file()
                }
                pins.update_python_runtime(root)
            self.assertEqual(
                first,
                {
                    path.relative_to(root): path.read_bytes()
                    for path in root.rglob("*")
                    if path.is_file()
                },
            )
            self.assertEqual(
                (root / "template/backend/Dockerfile")
                .read_text()
                .count("FROM python:3.13.99-slim-bookworm"),
                2,
            )
            self.assertEqual(
                (root / "template/.python-version").read_text(), "3.13.99\n"
            )
            self.assertIn(
                "image: python:3.13.99-slim-bookworm",
                (root / "template/bitbucket-pipelines.yml").read_text(),
            )
            node = (root / "template/.node-version").read_text().strip()
            self.assertIn(
                f"node:{node}-bookworm",
                (root / "template/bitbucket-pipelines.yml").read_text(),
            )

    def test_python_preserves_an_existing_debian_distribution(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.runtime_fixture(directory)
            for name in ("backend/Dockerfile", "bitbucket-pipelines.yml"):
                path = root / "template" / name
                path.write_text(
                    path.read_text().replace("-slim-bookworm", "-slim-trixie")
                )
            with patch.object(pins, "fetch", return_value="Tags: 3.13.99-slim-trixie"):
                pins.update_python_runtime(root)
            self.assertEqual(
                (root / "template/backend/Dockerfile")
                .read_text()
                .count("FROM python:3.13.99-slim-trixie"),
                2,
            )

    def test_frontend_runtime_update_is_repeatable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.runtime_fixture(directory)
            pins.write_node_version(root, "24.99.0")
            first = {
                path.relative_to(root): path.read_bytes()
                for path in root.rglob("*")
                if path.is_file()
            }
            pins.write_node_version(root, "24.99.0")
            self.assertEqual(
                first,
                {
                    path.relative_to(root): path.read_bytes()
                    for path in root.rglob("*")
                    if path.is_file()
                },
            )

    def test_node_uses_latest_stable_lts_patch(self):
        releases = [
            {"version": "v26.2.0", "lts": False},
            {"version": "v24.9.0", "lts": "Krypton"},
            {"version": "v24.10.1", "lts": "Krypton"},
            {"version": "v24.11.0-rc.1", "lts": "Krypton"},
            {"version": "v22.20.0", "lts": "Jod"},
        ]
        self.assertEqual(pins.node_version(releases), "24.10.1")

    def test_missing_lts_fails(self):
        with self.assertRaises(ValueError):
            pins.node_version([{"version": "v26.0.0", "lts": False}])

    def test_python_preserves_minor_and_distribution(self):
        metadata = "\n".join(
            [
                "Tags: 3.14.1-slim-bookworm, 3.14-slim-bookworm",
                "Tags: 3.13.9-slim-bookworm, 3.13-slim-bookworm",
                "Tags: 3.13.10-slim-bookworm, 3.13.10-slim",
                "Tags: 3.13.11rc1-slim-bookworm",
            ]
        )
        self.assertEqual(
            pins.python_version(metadata, "3.13.5-slim-bookworm"),
            "3.13.10-slim-bookworm",
        )
        with self.assertRaises(ValueError):
            pins.python_version(metadata, "3.12.1-slim-bookworm")

    def test_updating_frontend_runtime_keeps_consumers_consistent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "template/frontend").mkdir(parents=True)
            (root / "template/frontend/Dockerfile").write_text(
                "FROM node:22.20.0-bookworm AS base\nFROM base AS build\n"
            )
            (root / "template/.node-version").write_text("22.20.0\n")
            (root / "template/flake.nix").write_text("nodejs_22\n")
            (root / "template/bitbucket-pipelines.yml").write_text(
                "image: python:3.13.5-slim-bookworm\n  image: node:22.20.0-bookworm\n"
            )
            pins.write_node_version(root, "24.10.1")
            self.assertEqual((root / "template/.node-version").read_text(), "24.10.1\n")
            self.assertIn(
                "node:24.10.1-bookworm",
                (root / "template/frontend/Dockerfile").read_text(),
            )
            self.assertIn(
                "python:3.13.5-slim-bookworm",
                (root / "template/bitbucket-pipelines.yml").read_text(),
            )
            self.assertEqual((root / "template/flake.nix").read_text(), "nodejs_24\n")


class FrontendLockTests(unittest.TestCase):
    def fixture(self, directory):
        root = Path(directory)
        frontend = root / "template/frontend"
        frontend.mkdir(parents=True)
        manifest = {
            "name": "{{ copier__project_name }}",
            "version": "0.1.0",
            "dependencies": {"example": "*"},
        }
        (frontend / "package.json").write_text(json.dumps(manifest))
        (frontend / "package-lock.json").write_text("old lock\n")
        return root, frontend, manifest

    def test_fresh_resolution_restores_both_copier_names_without_changing_manifest(
        self,
    ):
        with tempfile.TemporaryDirectory() as directory:
            root, frontend, manifest = self.fixture(directory)
            original = (frontend / "package.json").read_bytes()

            def resolve(command, *, cwd, check):
                self.assertTrue(check)
                self.assertIn("--ignore-scripts", command)
                self.assertIn("--package-lock-only", command)
                self.assertFalse((cwd / "package-lock.json").exists())
                rendered = json.loads((cwd / "package.json").read_text())
                self.assertEqual(rendered["dependencies"], manifest["dependencies"])
                (cwd / "package-lock.json").write_text(
                    json.dumps({"name": rendered["name"], "packages": {"": rendered}})
                )

            with patch.object(pins.subprocess, "run", side_effect=resolve):
                pins.update_frontend_packages(root)
            lock = json.loads((frontend / "package-lock.json").read_text())
            self.assertEqual(lock["name"], manifest["name"])
            self.assertEqual(lock["packages"][""]["name"], manifest["name"])
            self.assertEqual((frontend / "package.json").read_bytes(), original)

    def test_resolution_failure_preserves_manifest_and_existing_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            root, frontend, _ = self.fixture(directory)
            original = {path.name: path.read_bytes() for path in frontend.iterdir()}
            with patch.object(
                pins.subprocess,
                "run",
                side_effect=subprocess.CalledProcessError(1, "npm"),
            ):
                with self.assertRaises(subprocess.CalledProcessError):
                    pins.update_frontend_packages(root)
            self.assertEqual(
                original, {path.name: path.read_bytes() for path in frontend.iterdir()}
            )


if __name__ == "__main__":
    unittest.main()
