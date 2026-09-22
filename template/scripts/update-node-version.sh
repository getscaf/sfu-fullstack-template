#!/usr/bin/env bash
set -euo pipefail

# Kept as a single script so the Docker Hub API is called once and the resolved
# version is shared across all file updates without needing a temp file.
#
# Docker Hub does not label which tag is the current Node LTS, so we resolve the
# `lts` tag's digest and match it back to the plain-major tag (e.g. `24`) that
# shares that digest.

tags=$(curl -fsSL "https://registry.hub.docker.com/v2/repositories/library/node/tags?page_size=100")

lts_digest=$(echo "$tags" | jq -r '.results[] | select(.name == "lts") | .digest')

if [ -z "$lts_digest" ] || [ "$lts_digest" = "null" ]; then
  echo "Could not resolve the digest for the node:lts tag" >&2
  exit 1
fi

major=$(echo "$tags" | jq -r --arg digest "$lts_digest" '
  [.results[] | select(.digest == $digest) | .name | select(test("^[0-9]+$")) | tonumber]
  | if length > 0 then max else empty end
')

if [ -z "$major" ]; then
  echo "Could not match the node:lts digest to a numbered tag" >&2
  exit 1
fi

echo "Pinning Node LTS version to ${major} (node:${major})"

update() { if [ -f "$1" ]; then sed -i "${@:2}" "$1"; fi; }

update frontend/Dockerfile "s|__NODE_LTS_VERSION__|${major}|g"
update flake.nix "s|__NODE_LTS_VERSION__|${major}|g"
update .github/workflows/main.yaml "s|__NODE_LTS_VERSION__|${major}|g"
update .github/workflows/semantic-release.yaml "s|__NODE_LTS_VERSION__|${major}|g"
update bitbucket-pipelines.yml "s|__NODE_LTS_VERSION__|${major}|g"
update Makefile "s|__NODE_LTS_VERSION__|${major}|g"
