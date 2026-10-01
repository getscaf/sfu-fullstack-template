#!/usr/bin/env bash
set -euo pipefail

# Kept as a single script so the version is resolved once and shared across all
# file updates without needing a temp file.
#
# We resolve the current Active LTS major from nodejs.org's official release
# index rather than scraping Docker Hub tags. Every entry carries an `lts` field
# (the codename, or false), so the Active LTS is simply the highest major among
# LTS releases — Node majors only increase and a newer major becomes LTS only
# after the previous one, so the max is always the Active LTS. Docker's
# `node:<major>` tag always exists for that major, so the pin stays valid.

releases=$(curl -fsSL "https://nodejs.org/dist/index.json")

major=$(echo "$releases" | jq -r '
  [.[] | select(.lts != false) | .version | ltrimstr("v") | split(".")[0] | tonumber]
  | if length > 0 then max else empty end
')

if [ -z "$major" ]; then
  echo "Could not resolve the current Node LTS major from nodejs.org" >&2
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
