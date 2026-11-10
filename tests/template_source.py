"""Export template source from the working tree without ignored local artifacts."""

import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def export_template_source(destination, *, root=ROOT):
    destination = Path(destination)
    root = Path(root)
    names = subprocess.check_output(
        [
            "git",
            "ls-files",
            "-co",
            "--exclude-standard",
            "-z",
            "--",
            "copier.yml",
            "template",
        ],
        cwd=root,
        text=True,
    ).split("\0")
    for name in set(names):
        if name and (root / name).is_file():
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(root / name, target)
