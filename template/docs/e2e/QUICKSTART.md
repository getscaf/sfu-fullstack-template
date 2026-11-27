# Local Tilt E2E verification

From the root of a generated Scaf project, install Docker, kind, kubectl, Tilt,
and the Python version in `.python-version`. With Docker running, execute:

```bash
python3 -m venv e2e/.venv
source e2e/.venv/bin/activate
python -m pip install -r e2e/requirements.txt
bash e2e/scripts/e2e-run.sh
```

The command starts a fresh kind cluster and runs the project's Tiltfile.
The tests check that Home and About load. In Wagtail projects, they also sign in
to the CMS, edit and publish the example page, and verify the new content on the
public page.

The runner deletes its cluster when it finishes and prints the path to its
reports under `e2e/reports/`. See [Setup and troubleshooting](SETUP.md) for
readiness checks, failure logs, and cleanup.
