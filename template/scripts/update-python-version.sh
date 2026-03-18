#!/usr/bin/env bash
set -euo pipefail

# Kept as a single script so the Docker Hub API is called once and the resolved
# version is shared across all file updates without needing a temp file.

tags=$(curl -fsSL "https://registry.hub.docker.com/v2/repositories/library/python/tags?page_size=100&name=slim-bookworm")

minor=$(echo "$tags" | jq -r '
  [.results[].name | select(test("^[0-9]+\\.[0-9]+-slim-bookworm$")) | rtrimstr("-slim-bookworm")]
  | map(split(".") | map(tonumber))
  | max_by(.[0] * 1000 + .[1])
  | join(".")
')

full=$(echo "$tags" | jq -r --arg minor "$minor" '
  [.results[].name | select(test("^" + $minor + "\\.[0-9]+-slim-bookworm$")) | rtrimstr("-slim-bookworm")]
  | map(split(".") | map(tonumber))
  | if length > 0 then max_by(.[2]) | join(".") else $minor end
')

echo "Updating Python version to ${minor} (Docker: ${full})"

update() { if [ -f "$1" ]; then sed -i "${@:2}" "$1"; fi; }

update backend/Dockerfile "s|__PYTHON_FULL_VERSION__|${full}|g"
update Makefile "s|__PYTHON_FULL_VERSION__|${full}|g"  # not in django-template
update bitbucket-pipelines.yml "s|image: python:__PYTHON_VERSION__|image: python:${minor}|g"  # not in django-template
update .github/workflows/main.yaml "s|python-version: \"__PYTHON_VERSION__\"|python-version: \"${minor}\"|g"  # not in django-template
update k8s/base/app.configmap.yaml "s|python__PYTHON_VERSION__|python${minor}|g"  # not in django-template
