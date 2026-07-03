#!/usr/bin/env bash
set -euo pipefail

# Kept as a single script so the Docker Hub API is called once and the resolved
# version is shared across all file updates without needing a temp file.

tags=$(curl -fsSL "https://registry.hub.docker.com/v2/repositories/library/python/tags?page_size=100")

minor=$(echo "$tags" | jq -r '
  [.results[].name | select(test("^[0-9]+\\.[0-9]+-slim$")) | rtrimstr("-slim")]
  | map(split(".") | map(tonumber))
  | max_by(.[0] * 1000 + .[1])
  | join(".")
')

full=$(echo "$tags" | jq -r --arg minor "$minor" '
  [.results[].name | select(test("^" + $minor + "\\.[0-9]+-slim$")) | rtrimstr("-slim")]
  | map(split(".") | map(tonumber))
  | if length > 0 then max_by(.[2]) | join(".") else $minor end
')

echo "Updating Python version to ${minor} (Docker: ${full})"

update() { if [ -f "$1" ]; then sed -i "${@:2}" "$1"; fi; }

update backend/Dockerfile "s|python:[0-9]\+\.[0-9]\+\(\.[0-9]\+\)\?-slim|python:${full}-slim|g"
update Makefile "s|python:[0-9]\+\.[0-9]\+\(\.[0-9]\+\)\?-slim|python:${full}-slim|g"  # not in django-template
update bitbucket-pipelines.yml "s|image: python:[0-9]\+\.[0-9]\+|image: python:${minor}|g"  # not in django-template
update .github/workflows/main.yaml "s|python-version: \"[0-9]\+\.[0-9]\+\"|python-version: \"${minor}\"|g"  # not in django-template
