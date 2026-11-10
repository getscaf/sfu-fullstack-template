"""Generate the exact working tree without running setup hooks or creating commits."""

import importlib.util
import os
import tempfile
from pathlib import Path

from copier import run_copy

from tests.template_source import export_template_source


def generate_project(destination, *, nextjs=True, wagtail=True, **answers):
    with tempfile.TemporaryDirectory(prefix="scaf-template-") as source:
        source = Path(source)
        export_template_source(source)
        run_copy(
            str(source),
            str(destination),
            data={
                "copier__project_name_raw": "CMS Demo",
                "copier__project_slug": "cms_demo",
                "copier__domain_name": "example.test",
                "copier__create_nextjs_frontend": nextjs,
                "copier__use_wagtail": wagtail,
                **answers,
            },
            defaults=True,
            overwrite=True,
            skip_tasks=True,
            unsafe=True,
            quiet=True,
        )
    spec = importlib.util.spec_from_file_location(
        "generated_tasks", Path(destination) / "tasks.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    previous = Path.cwd()
    try:
        os.chdir(destination)
        module.cleanup_generated_files()
    finally:
        os.chdir(previous)
    return Path(destination)
