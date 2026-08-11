#!/usr/bin/env bash
set -euo pipefail

mode="${1:-all-static}"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/../../../.." && pwd)"
uv_cache_dir="${TMPDIR:-/tmp}/evaluation-hub-skill-uv-cache"
mkdir -p "${uv_cache_dir}"

uv_run() {
  UV_CACHE_DIR="${uv_cache_dir}" uv run "$@"
}

frontend_check() {
  cd "${repo_root}/frontend"
  echo "[frontend] Biome"
  npx biome check src tests
  echo "[frontend] Production build"
  npm run build
}

backend_static_check() {
  cd "${repo_root}/backend"
  echo "[backend] Ruff"
  uv_run ruff check app
  uv_run ruff format app --check
  echo "[backend] Type checks"
  uv_run mypy app
  uv_run ty check app
}

backend_test_check() {
  cd "${repo_root}/backend"
  echo "[backend] Foundation and evaluation tests"
  uv_run pytest -q tests app/tests
}

case "${mode}" in
  frontend)
    frontend_check
    ;;
  backend-static)
    backend_static_check
    ;;
  all-static)
    frontend_check
    backend_static_check
    ;;
  async-tests)
    cd "${repo_root}/backend"
    uv_run pytest -q tests/test_async_behavior.py
    ;;
  evaluation-tests)
    cd "${repo_root}/backend"
    uv_run pytest -q app/tests/api/routes/test_evaluations.py
    ;;
  backend-tests)
    backend_test_check
    ;;
  ui)
    frontend_check
    if ! curl -fsS "http://127.0.0.1:5173/" >/dev/null; then
      echo "UI checks require: cd frontend && npm run dev -- --host 127.0.0.1" >&2
      exit 2
    fi
    cd "${repo_root}/frontend"
    npx playwright test \
      tests/sidebar.spec.ts \
      tests/evaluation-details.spec.ts \
      --project=chromium \
      --no-deps \
      --reporter=line
    ;;
  *)
    echo "Usage: $0 [frontend|backend-static|all-static|async-tests|evaluation-tests|backend-tests|ui]" >&2
    exit 2
    ;;
esac
