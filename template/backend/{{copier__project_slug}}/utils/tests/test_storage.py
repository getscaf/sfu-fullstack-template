import os
import subprocess
import sys
from textwrap import dedent
from unittest.mock import patch

from django.conf import settings
from django.test import SimpleTestCase, override_settings


class ProductionStorageTests(SimpleTestCase):
    def test_storage_aliases_credentials_and_private_uploads(self):
        # production imports and mutates objects shared with base/test settings.
        # Exercise its real wiring in a fresh interpreter, never in this session.
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                dedent(
                    """
                import unittest
                from unittest.mock import patch
                import django
                from django.conf import settings
                from django.core.files.storage import storages

                django.setup()
                check = unittest.TestCase()
                for alias, prefix in [("default", "media"), ("staticfiles", "static")]:
                    storage = storages[alias]
                    check.assertEqual(storage.bucket_name, "test-assets")
                    check.assertEqual(storage.location, prefix)
                    with patch("storages.backends.s3.boto3.Session") as session:
                        storage._create_session()
                        check.assertEqual(session.call_args.kwargs["aws_access_key_id"], "dummy-s3-key")
                        check.assertEqual(session.call_args.kwargs["aws_secret_access_key"], "dummy-s3-secret")
                    check.assertIsNone(settings.AWS_DEFAULT_ACL)
                    check.assertNotIn("ACL", storage._get_write_parameters("test.txt"))
                    check.assertEqual(storage.url("test.txt"), f"https://sandbox.example.test/{prefix}/test.txt")
            """
                ),
            ],
            cwd=settings.ROOT_DIR,
            env={
                # Preserve interpreter/runtime configuration (Nix, PYTHONPATH,
                # library paths), but isolate cloud credentials and app settings.
                **{
                    key: value
                    for key, value in os.environ.items()
                    if not key.startswith(("AWS_", "DJANGO_", "MAILGUN_", "SENTRY_"))
                },
                "DJANGO_SETTINGS_MODULE": "config.settings.production",
                "DJANGO_READ_DOT_ENV_FILE": "False",
                "DJANGO_SECRET_KEY": "test-only",
                "DATABASE_URL": "sqlite:///:memory:",
                "REDIS_URL": "redis://localhost:6379/1",
                "CELERY_BROKER_URL": "redis://localhost:6379/0",
                "DJANGO_ADMIN_URL": "admin/",
                "DJANGO_AWS_STORAGE_BUCKET_NAME": "test-assets",
                "AWS_S3_CUSTOM_DOMAIN": "sandbox.example.test",
                "AWS_S3_ACCESS_KEY_ID": "dummy-s3-key",
                "AWS_S3_SECRET_ACCESS_KEY": "dummy-s3-secret",
                "AWS_EC2_METADATA_DISABLED": "true",
                "MAILGUN_API_KEY": "dummy-mailgun-key",
                "MAILGUN_DOMAIN": "mail.example.test",
                "SENTRY_DSN": "",
            },
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_no_s3_keys_preserves_sdk_discovery(self):
        from ..cloud_storage import S3MediaStorage

        with override_settings(
            AWS_S3_ACCESS_KEY_ID=None, AWS_S3_SECRET_ACCESS_KEY=None
        ), patch.dict(
            os.environ, {"AWS_EC2_METADATA_DISABLED": "true"}, clear=True
        ), patch(
            "storages.backends.s3.boto3.Session"
        ) as session:
            S3MediaStorage()._create_session()
            self.assertIsNone(session.call_args.kwargs["aws_access_key_id"])
            self.assertIsNone(session.call_args.kwargs["aws_secret_access_key"])
