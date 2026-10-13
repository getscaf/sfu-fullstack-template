# :technologist: How to set up your local environment for development

## Requirements

To work with Kubernetes, you need to install some additional software packages.
Depending on your operating system, the installation instructions may vary.

The documentation and scripts in the repo are written to work with `kubectl`, `kind` and `Tilt`.

Consult the links below if you prefer to use Minikube or Docker Desktop instead:
* [minikube](https://minikube.sigs.k8s.io/docs/start/).
* [Docker](https://docs.docker.com/get-docker/).

## Setup your environment

1. Get the repository

       $ git clone {{ copier__repo_url }}
       $ cd {{ copier__project_slug }}
       $ cp -n .envrc.example .envrc

2. Prepare the environment variables. Edit the `.envrc` file to work for your environment.

   ```bash
   # Example .envrc.local file
   export DEBUG=true
   export LOG_LEVEL=debug
   export LOCAL_DEV_SETTING=custom_value
   ```

## Run the kubernetes cluster and the {{ copier__project_slug }} app to develop the code

First load the environment variables, then run:

      $ make setup
      $ tilt up

:information_source: It may take a little bit of time for all the services to start up, and it's possible for
the first run to fail because of timing conflicts. If you do see messages indicating there
were errors during the first run, stop all the containers using Ctrl-C, and then try it again.

You are now ready to edit the code.
The app will be automatically reloaded when its files change.

To delete resources created by Tilt once you are done working:

       $ tilt down

This will not delete persistent volumes created by Tilt, and you should be able to start Tilt again with your data intact.

To remove the cluster entirely:

       $ kind delete cluster --name {{ copier__project_slug }}

To switch between different Scaf project contexts:

      $ tilt down    # inside the codebase of the previous project
      $ make setup   # inside the codebase of the project you want to work on
      $ tilt up

## Next steps

Creating a superuser account in the backend is useful so you have access to
Django Admin that will be accessible at [http://localhost:8000/admin](http://localhost:8000/admin)

To create a superuser use the following commands:

    $ make shell-backend
    $ ./manage.py createsuperuser
{% if copier__create_nextjs_frontend %}
This project has a NextJS frontend configured. You can access it at [http://localhost:3000/](http://localhost:3000/).
{% endif %}

## Update dependencies

This project inherits committed dependency locks and explicit runtime versions
from the template revision used to generate it. Setup installs those pins
without resolving newer versions. The `.python-version` and `.node-version`
files record the full runtime versions used by Docker and CI. Select these
versions when running checks on the host. Nix packages are outside this exact
runtime guarantee; the Nix Node attribute follows only the major version.

### Python dependencies

Edit the relevant `backend/requirements/*.in` declarations, then explicitly
regenerate the locks:

```bash
make compile
```

This uses the Python image in `backend/Dockerfile`. It refreshes `build.txt`
first, then `base.txt`, `production.txt`, `tests.txt`, and `local.txt`, using
`base.txt` as a shared constraint for the latter three roles. `build.txt` pins
pip, setuptools, wheel, uv, and their dependencies. Application installations
use these tools with `--no-deps --no-build-isolation`, including when a package
must build from a source distribution. Keep source constraints, such as the
debugger version pin, unless you deliberately change them.

Review and commit the edited `.in` files together with all changed `.txt`
locks. Run formatting and lint checks, backend tests, and rebuild the backend
image through the project's normal CI or Tilt workflow before merging.
{% if copier__create_nextjs_frontend %}
### Frontend dependencies

Edit `frontend/package.json`, then refresh its lock with the pinned Node image:

```bash
make compile-frontend
make check-lint-and-test-frontend
```

`make compile-frontend` runs `npm update --package-lock-only --ignore-scripts`
against the existing lock. This explicit update respects manifest ranges,
including Apollo compatibility constraints. It does not perform the fresh
transitive resolution used by the template's nightly updater. Ordinary
installs and checks use `npm ci`; run `make init-frontend-dependencies` to
install the committed lock through Docker.

Review and commit `frontend/package.json` and `frontend/package-lock.json`
together, then run frontend lint, typecheck, tests, and an image build before
merging.
{% endif %}
### Runtime changes

For a deliberate Python upgrade, update `.python-version` and every Python
stage in `backend/Dockerfile` together. Also update the Python image in
`bitbucket-pipelines.yml` if that file is present. The template's automated
policy updates patches within the current minor and Debian distribution;
changing either is a deliberate project decision. Recompile and validate the
Python locks when changing the runtime.
For Node, update `.node-version` and the major in `flake.nix` together. Use a
full stable LTS version for CI.
{% if copier__create_nextjs_frontend %}
Also update `frontend/Dockerfile` and the frontend image in
`bitbucket-pipelines.yml` if that file is present. Retain the chosen Debian
distribution, and validate `npm ci`, frontend checks, and the image build.
{% endif %}
GitHub workflows, where present, read the version files. Make targets derive
their images from the Dockerfiles. Commit the coordinated runtime files and
any resulting lock changes together. Apt packages and image digests are
outside the runtime and package pinning policy.

## Resource Limits Consideration

Resource limits have been predefined for both Django and NextJS services to ensure optimal performance and efficient resource utilization:

- **Django**:
  - Requests: `cpu: 200m`, `memory: 300Mi`
  - Limits: `cpu: 250m`, `memory: 400Mi`
{% if copier__create_nextjs_frontend %}
- **NextJS**:
  - Requests: `cpu: 100m`, `memory: 200Mi`
  - Limits: `cpu: 250m`, `memory: 300Mi`
{% endif %}

Ensure these values are appropriate for your environment. If needed, adjust them based on real workload observations in a staging or production environment to balance performance and resource consumption.
