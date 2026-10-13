import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jinja2 import Environment, StrictUndefined
from packaging.requirements import Requirement

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / ".github/scripts"))
import python_locks as locks

INPUTS = {
    "base": """django
{% if copier__use_celery %}celery{% endif %}
{% if copier__use_sentry %}sentry-sdk[django]{% endif %}
{% if copier__create_nextjs_frontend %}strawberry-graphql-django{% endif %}
""",
    "local": "-r base.txt\ndebugpy\n",
    "production": """-r base.txt
gunicorn
{% if copier__mail_service == 'Amazon SES' %}django-anymail[amazon_ses]
{% elif copier__mail_service == 'Mailgun' %}django-anymail[mailgun]
{% else %}django-anymail{% endif %}
""",
    "tests": "-r base.txt\npytest\n",
    "build": "uv\nsetuptools\nwheel\n",
}
RESOLUTIONS = {
    "django": {"django==5.2.1", "asgiref==3.8.1"},
    "celery": {"celery==5.5.1", "kombu==5.5.0"},
    "sentry-sdk[django]": {"sentry-sdk[django]==2.0", "urllib3==2.4.0"},
    "strawberry-graphql-django": {
        "strawberry-graphql-django==0.63.0",
        "graphql-core==3.2.6",
    },
    "debugpy": {"debugpy==1.8.14"},
    "gunicorn": {"gunicorn==23.0"},
    "django-anymail[amazon_ses]": {"django-anymail[amazon_ses]==13.0", "boto3==1.38.0"},
    "django-anymail[mailgun]": {"django-anymail[mailgun]==13.0", "requests==2.32.3"},
    "django-anymail": {"django-anymail==13.0"},
    "pytest": {"pytest==8.3.5", "packaging==25.0"},
    "uv": {"uv==0.6.14"},
    "setuptools": {"setuptools==80.0.0"},
    "wheel": {"wheel==0.45.1", "packaging==25.0"},
}


def resolve_fixture(inputs, output, python, constraints=None, strip_extras=False):
    """Replace the network resolver with fixed, complete dependency closures."""
    resolved = set()
    for input_path in inputs:
        for line in input_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("-r "):
                resolved.update(
                    resolve_fixture([input_path.parent / line[3:]], output, python)
                )
            else:
                resolved.update(RESOLUTIONS[line])
    # These fixture source declarations allow either exact constrained version.
    # This exposes differing lock versions that are individually compatible.
    constrained = (
        locks.pinned_versions(constraints.read_text().splitlines())
        if constraints
        else {}
    )
    result = set()
    for line in resolved:
        requirement = Requirement(line)
        name = next(iter(locks.pinned_versions([line])))
        version = constrained.get(name, next(iter(requirement.specifier)).version)
        extras = (
            ""
            if strip_extras or not requirement.extras
            else "[" + ",".join(sorted(requirement.extras)) + "]"
        )
        result.add(f"{requirement.name}{extras}=={version}")
    output.write_text("\n".join(sorted(result)) + "\n")
    return result


class PythonLockTests(unittest.TestCase):
    def test_factored_lock_preserves_every_optional_configuration(self):
        variants = []
        for context in locks.contexts():
            lines = {"django==5.2.1", "shared==1.0"}
            if context["copier__use_celery"]:
                lines.add("celery==5.5.1")
            if context["copier__use_sentry"]:
                lines.add("sentry-sdk[django]==2.0")
            if (
                context["copier__create_nextjs_frontend"]
                or context["copier__use_celery"]
            ):
                lines.add("either-feature==1.1")
            if context["copier__mail_service"] == "Amazon SES":
                lines.add("django-anymail[amazon-ses]==13.0")
            else:
                lines.add("django-anymail==13.0")
            variants.append((context, lines))
        template = locks.factor_locks(variants)
        env = Environment(undefined=StrictUndefined)
        for context, expected in variants:
            with self.subTest(context=context):
                rendered = env.from_string(template).render(context)
                actual = {
                    line
                    for line in rendered.splitlines()
                    if line and not line.startswith("#")
                }
                self.assertEqual(actual, expected)
        self.assertEqual(len(variants), 24)
        self.assertEqual(template.count("django==5.2.1"), 1)

    def test_empty_variants_do_not_produce_a_lock(self):
        with self.assertRaises(ValueError):
            locks.factor_locks([])

    def test_package_names_use_canonical_separators(self):
        self.assertEqual(
            locks.pinned_versions({"Some.PACKAGE[extra]==1.0", "some___package==1.0"}),
            {"some-package": "1.0"},
        )

    def test_conflicting_pins_with_canonical_package_names_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "Conflicting pins for some-package"):
            locks.pinned_versions({"Some.PACKAGE==1.0", "some___package==2.0"})

    def test_unpinned_requirements_are_rejected(self):
        for line in (
            "django",
            "django>=5.2",
            "django==5.2.*",
            "django===5.2",
            "django==5.2,!=5.2.1",
            "django @ https://example.org/django.whl",
        ):
            with self.subTest(line=line):
                with self.assertRaisesRegex(ValueError, "Unpinned requirement"):
                    locks.pinned_versions([line])

    def test_factoring_is_deterministic_for_reordered_variants(self):
        variants = []
        for context in locks.contexts():
            lines = {"shared==1.0"}
            if context["copier__use_celery"]:
                lines.add("celery==5.5.1")
            if context["copier__mail_service"] == "Mailgun":
                lines.add("mailgun-only==1.0")
            variants.append((context, lines))
        self.assertEqual(
            locks.factor_locks(variants), locks.factor_locks(list(reversed(variants)))
        )

    def test_extra_names_are_canonicalized_and_combined(self):
        self.assertEqual(
            locks.requirement_extras(
                [
                    "Django_Anymail[amazon_ses]==13.0",
                    "django-anymail[mailgun]==13.0",
                ]
            ),
            {"django-anymail": {"amazon-ses", "mailgun"}},
        )

    def test_compile_targets_stable_linux_pinned_python_and_preserves_extras(self):
        with tempfile.TemporaryDirectory() as directory:
            workdir = Path(directory)
            source, output, constraints = (
                workdir / name for name in ("base.in", "lock.txt", "constraints.txt")
            )
            source.write_text("sentry-sdk[django]\n")
            constraints.write_text("sentry-sdk==2.0\n")

            def resolver(command, check):
                self.assertTrue(check)
                output.write_text("# Resolver comment\nsentry-sdk[django]==2.0\n\n")

            with patch.object(locks.subprocess, "run", side_effect=resolver) as run:
                actual = locks.compile_lock([source], output, "3.13.16", constraints)
            self.assertEqual(actual, {"sentry-sdk[django]==2.0"})
            command = run.call_args.args[0]
            self.assertEqual(command[:4], ["uv", "pip", "compile", str(source)])
            for flag, value in (
                ("--python-version", "3.13.16"),
                ("--python-platform", "linux"),
                ("--prerelease", "disallow"),
                ("--constraint", str(constraints)),
            ):
                self.assertEqual(command[command.index(flag) + 1], value)
            for flag in ("--no-header", "--no-annotate", "--no-strip-extras"):
                self.assertIn(flag, command)

            with patch.object(locks.subprocess, "run", side_effect=resolver) as run:
                locks.compile_lock([source], output, "3.13.16", strip_extras=True)
            self.assertNotIn("--no-strip-extras", run.call_args.args[0])


class PythonLockWorkflowTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.requirements = self.root / "template/backend/requirements"
        self.requirements.mkdir(parents=True)
        (self.root / "template/.python-version").write_text("3.13.16\n")
        for role, text in INPUTS.items():
            (self.requirements / f"{role}.in").write_text(text)
        variants = {role: [] for role in locks.ROLES}
        workdir = self.root / "work"
        workdir.mkdir()
        for context in locks.contexts():
            locks.render_inputs(self.requirements, workdir, context)
            for role in locks.ROLES:
                lines = resolve_fixture(
                    [workdir / f"{role}.in"], workdir / "lock.txt", "3.13.16"
                )
                variants[role].append((context, lines))
        for role in locks.ROLES:
            (self.requirements / f"{role}.txt").write_text(
                locks.factor_locks(variants[role])
            )

    def test_check_rejects_missing_transitive_dependency_in_one_role(self):
        base = self.requirements / "base.txt"
        base.write_text(base.read_text().replace("asgiref==3.8.1\n", ""))
        with patch.object(locks, "compile_lock", side_effect=resolve_fixture):
            with self.assertRaisesRegex(
                ValueError, "Incomplete or stale Python locks for base"
            ):
                locks.check_locks(self.root)

    def test_check_rejects_missing_optional_extras_even_with_complete_dependencies(
        self,
    ):
        base = self.requirements / "base.txt"
        base.write_text(
            base.read_text().replace("sentry-sdk[django]==2.0", "sentry-sdk==2.0")
        )
        with patch.object(locks, "compile_lock", side_effect=resolve_fixture):
            with self.assertRaisesRegex(
                ValueError, "Incomplete or stale Python locks for base"
            ):
                locks.check_locks(self.root)

    def test_check_rejects_shared_version_differences_across_feature_contexts(self):
        for role in ("base", "local", "production", "tests"):
            path = self.requirements / f"{role}.txt"
            text = path.read_text().replace(
                "asgiref==3.8.1",
                "{% if copier__use_celery %}asgiref==3.8.2{% else %}asgiref==3.8.1{% endif %}",
            )
            path.write_text(text)
        with patch.object(locks, "compile_lock", side_effect=resolve_fixture):
            with self.assertRaisesRegex(ValueError, "Conflicting pins for asgiref"):
                locks.check_locks(self.root)

    def lock_contents(self):
        return {
            role: (self.requirements / f"{role}.txt").read_bytes()
            for role in locks.ROLES
        }

    def test_late_resolution_failure_preserves_all_existing_locks(self):
        for role in locks.ROLES:
            (self.requirements / f"{role}.txt").write_text(f"# Existing {role} lock\n")
        existing = self.lock_contents()
        count = 0

        def fail_later(*args, **kwargs):
            nonlocal count
            count += 1
            if count == 10:
                raise subprocess.CalledProcessError(1, ["uv", "pip", "compile"])
            return resolve_fixture(*args, **kwargs)

        with patch.object(locks, "compile_lock", side_effect=fail_later):
            with self.assertRaises(subprocess.CalledProcessError):
                locks.update_locks(self.root)
        self.assertEqual(self.lock_contents(), existing)

    def test_late_factoring_failure_preserves_all_existing_locks(self):
        for role in locks.ROLES:
            (self.requirements / f"{role}.txt").write_text(f"# Existing {role} lock\n")
        existing = self.lock_contents()
        factor = locks.factor_locks
        count = 0

        def fail_later(variants):
            nonlocal count
            count += 1
            if count == 3:
                raise ValueError("Cannot factor this role")
            return factor(variants)

        with patch.object(locks, "compile_lock", side_effect=resolve_fixture):
            with patch.object(locks, "factor_locks", side_effect=fail_later):
                with self.assertRaisesRegex(ValueError, "Cannot factor this role"):
                    locks.update_locks(self.root)
        self.assertEqual(self.lock_contents(), existing)

    def test_check_accepts_complete_locks_without_changing_files(self):
        existing = self.lock_contents()
        with patch.object(locks, "compile_lock", side_effect=resolve_fixture):
            locks.check_locks(self.root)
        self.assertEqual(self.lock_contents(), existing)

    def test_update_resolves_one_shared_set_then_constrains_every_role(self):
        calls = []

        def record_resolution(
            inputs, output, python, constraints=None, strip_extras=False
        ):
            calls.append(
                (
                    tuple(path.name for path in inputs),
                    python,
                    strip_extras,
                    constraints.read_text() if constraints else None,
                )
            )
            return resolve_fixture(inputs, output, python, constraints, strip_extras)

        with patch.object(locks, "compile_lock", side_effect=record_resolution):
            locks.update_locks(self.root)
        aggregate = [call for call in calls if call[3] is None]
        self.assertEqual(len(aggregate), 1)
        self.assertTrue(aggregate[0][2])
        constraints = {call[3] for call in calls if call[3] is not None}
        self.assertEqual(len(constraints), 1)
        shared = locks.pinned_versions(next(iter(constraints)).splitlines())
        for line in {line for lines in RESOLUTIONS.values() for line in lines}:
            expected = locks.pinned_versions([line])
            for name, version in expected.items():
                self.assertEqual(shared[name], version)
        for inputs, python, strip_extras, constraint in calls[1:]:
            self.assertEqual(len(inputs), 1)
            self.assertIn(inputs[0], {f"{role}.in" for role in locks.ROLES})
            self.assertEqual(python, "3.13.16")
            self.assertFalse(strip_extras)
            self.assertIsNotNone(constraint)

    def test_generated_locks_roundtrip_for_all_roles_and_24_configurations(self):
        with patch.object(locks, "compile_lock", side_effect=resolve_fixture):
            locks.update_locks(self.root)
        workdir = self.root / "verify"
        workdir.mkdir()
        all_lines = set()
        for context in locks.contexts():
            locks.render_inputs(self.requirements, workdir, context)
            for role in locks.ROLES:
                with self.subTest(context=context, role=role):
                    template = (self.requirements / f"{role}.txt").read_text()
                    rendered = locks.ENV.from_string(template).render(context)
                    actual = {
                        line
                        for line in rendered.splitlines()
                        if line and not line.startswith("#")
                    }
                    expected = resolve_fixture(
                        [workdir / f"{role}.in"], workdir / "expected.txt", "3.13.16"
                    )
                    self.assertEqual(actual, expected)
                    all_lines.update(actual)
        # A shared package has one pin, including when extras differ by variant.
        locks.pinned_versions(all_lines)
        self.assertEqual(len(locks.contexts()), 24)

    def test_repeated_updates_are_byte_identical(self):
        original = self.lock_contents()
        with patch.object(locks, "compile_lock", side_effect=resolve_fixture):
            locks.update_locks(self.root)
            first = self.lock_contents()
            locks.update_locks(self.root)
        self.assertEqual(first, original)
        self.assertEqual(self.lock_contents(), first)
        for text in first.values():
            self.assertNotIn(str(self.root).encode(), text)


if __name__ == "__main__":
    unittest.main()
