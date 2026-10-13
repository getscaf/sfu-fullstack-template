# Build all of the dependencies then we will build the actual application image
FROM python:3.13.16-slim-bookworm AS build

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV BOGUS=1

ARG DEVEL=no
ARG TEST=no

RUN apt-get update \
    && apt-get install --no-install-recommends -y \
    build-essential \
    ca-certificates \
    curl \
    gettext \
    gnupg \
    && mkdir -p /etc/apt/keyrings \
    && apt-get install --no-install-recommends -y \
    libffi-dev \
    libpq-dev \
    libssl-dev \
    postgresql-client \
    postgresql-client-common


# We create an /app directory with a virtual environment in it to store our
# application in.
RUN set -x \
    && python3 -m venv /app

# Now that we've created our virtual environment, we'll go ahead and update
# our $PATH to refer to it first.
ENV VIRTUAL_ENV="/app"
ENV PATH="$VIRTUAL_ENV/bin:${PATH}"

COPY requirements /tmp/requirements

# Install the committed build-tool pins before the application dependencies.
RUN pip --no-cache-dir install --no-deps -r /tmp/requirements/build.txt

RUN set -x \
    && if [ "$DEVEL" = "yes" ]; then uv pip --no-cache install --no-deps --no-build-isolation -r /tmp/requirements/local.txt; fi

RUN set -x \
    && uv pip --no-cache install --no-deps --no-build-isolation \
    -r /tmp/requirements/production.txt \
    -r /tmp/requirements/base.txt

RUN set -x \
    && if [ "$TEST" = "yes" ]; then uv pip --no-cache install --no-deps --no-build-isolation \
    -r /tmp/requirements/tests.txt; fi

# Now we can build the application image
FROM python:3.13.16-slim-bookworm

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH="/app"
ENV PATH="/app/bin:${PATH}"
ENV BOGUS=1

WORKDIR /app/src

ARG DEVEL=no
# this is used by Sentry to associate errors with releases
ARG RELEASE="dev"

# This is a work around because otherwise postgresql-client bombs out trying
# to create symlinks to these directories.
RUN set -x \
    && mkdir -p /usr/share/man/man1 \
    && mkdir -p /usr/share/man/man7

RUN apt-get update \
    # psycopg2 dependencies
    && apt-get install --no-install-recommends -y \
    ca-certificates \
    curl \
    gettext \
    libpq5 \
    gnupg \
    && mkdir -p /etc/apt/keyrings \
    && apt-get install --no-install-recommends -y \
    $(if [ "$DEVEL" = "yes" ]; then echo 'bash postgresql-client'; fi) \
    # awscli
    && apt-get install -y \
    awscli \
    # cleaning up unused files
    && apt-get remove -y \
    curl \
    gnupg \
    && apt-get purge -y --auto-remove -o APT::AutoRemove::RecommendsImportant=false \
    && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

RUN adduser --system --no-create-home django
COPY --chown=django:django --from=build /app/ /app/
COPY --chown=django:django config/ /app/src/config/
COPY --chown=django:django manage.py /app/src/
COPY --chown=django:django {{ copier__project_slug }}/ /app/src/{{ copier__project_slug }}/

USER django
