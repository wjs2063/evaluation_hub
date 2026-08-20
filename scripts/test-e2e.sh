#!/usr/bin/env bash

set -Eeuo pipefail

readonly E2E_PROJECT_NAME="evaluation-hub-e2e"
readonly E2E_COMPOSE_FILE="compose.e2e.yml"

compose_e2e() {
  docker compose \
    --project-name "$E2E_PROJECT_NAME" \
    --file "$E2E_COMPOSE_FILE" \
    "$@"
}

cleanup() {
  local exit_code=$?

  trap - EXIT INT TERM HUP
  echo "Cleaning up isolated Playwright stack..."
  if ! compose_e2e down --volumes --remove-orphans; then
    echo "Warning: failed to completely clean up the isolated Playwright stack." >&2
  fi
  exit "$exit_code"
}

trap cleanup EXIT INT TERM HUP

echo "Removing any stale isolated Playwright stack..."
compose_e2e down --volumes --remove-orphans

echo "Building backend and Playwright images from the current source..."
compose_e2e build backend playwright

echo "Starting the isolated database, MailCatcher, and backend..."
compose_e2e up \
  --detach \
  --wait \
  --wait-timeout 180 \
  db mailcatcher backend

echo "Running the Playwright suite..."
compose_e2e run --rm --no-deps playwright bunx playwright test "$@"
