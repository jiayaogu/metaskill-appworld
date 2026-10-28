#!/usr/bin/env bash
# Prepare one AppWorld environment shared by the ACE and ReMe reproduction scripts.
set -euo pipefail

repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
venv="$repo_root/.venv-appworld"
stamp="$venv/.reproduction-setup-stamp"

fail() { printf 'Error: %s\n' "$*" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1 || fail "Required command missing: $1"; }

# Include package metadata and this install recipe in the reuse decision.
expected_stamp() {
  git -C "$repo_root" hash-object pyproject.toml experiments/setup.py
  git -C "$repo_root" hash-object scripts/setup_appworld_venv.sh
}

check_packages() {
  [[ -x "$venv/bin/python" && -x "$venv/bin/appworld" ]] || return 1
  "$venv/bin/python" -m pip check >/dev/null 2>&1 || return 1
  "$venv/bin/python" - <<'PY' >/dev/null 2>&1
import sys
from importlib.metadata import version
from importlib.util import find_spec
from packaging.version import Version

assert sys.version_info[:2] == (3, 11)
for package, expected in {
    "ray": "2.59.0",
    "pydantic": "2.13.5",
    "together": "1.5.35",
    "click": "8.1.8",
}.items():
    assert version(package) == expected, package
assert Version(version("loguru")) >= Version("0.7.3")
assert find_spec("appworld") is not None
assert find_spec("appworld_experiments") is not None
PY
}

data_ready() {
  [[ -f "$repo_root/data/base_dbs/version.txt" && -d "$repo_root/data/tasks" \
    && -d "$repo_root/data/api_docs" ]]
}

check_ready() {
  [[ -f "$stamp" ]] || return 1
  [[ $(cat "$stamp") == "$(expected_stamp)" ]] || return 1
  data_ready || return 1
  check_packages
}

setup() {
  need git
  need git-lfs
  need python3.11
  [[ -d "$repo_root/.git" ]] || fail "Clone the ace-appworld Git repository first"
  git -C "$repo_root" lfs install --local
  git -C "$repo_root" lfs pull
  if check_ready; then
    printf 'Reusing shared AppWorld environment: %s\n' "$venv"
    return
  fi
  rm -f -- "$stamp"
  if [[ ! -x "$venv/bin/python" ]]; then python3.11 -m venv "$venv"; fi
  "$venv/bin/python" -m pip install --upgrade pip setuptools wheel
  # ReMe needs Ray/loguru; ACE and ReMe then use the same tested AppWorld stack.
  (cd "$repo_root" && "$venv/bin/python" -m pip install -e . -e 'experiments[simplified]' \
    'ray==2.59.0' 'loguru>=0.7.3' 'pydantic==2.13.5' 'together==1.5.35')
  (cd "$repo_root" && APPWORLD_PROJECT_PATH="$repo_root" "$venv/bin/appworld" install --repo)
  if data_ready; then
    printf 'Using AppWorld data already present in this checkout.\n'
  else
    # AppWorld replaces data/ during download, including this fork's custom splits.
    # Preserve every existing dataset manifest and restore it even if download fails.
    local dataset_backup download_status=0
    dataset_backup=$(mktemp -d "$venv/.datasets-backup.XXXXXX")
    if [[ -d "$repo_root/data/datasets" ]]; then
      cp -a "$repo_root/data/datasets" "$dataset_backup/datasets"
    fi
    (cd "$repo_root" && APPWORLD_PROJECT_PATH="$repo_root" "$venv/bin/appworld" download data) \
      || download_status=$?
    if [[ -d "$dataset_backup/datasets" ]]; then
      mkdir -p "$repo_root/data/datasets"
      cp -a "$dataset_backup/datasets/." "$repo_root/data/datasets/"
    fi
    rm -rf -- "$dataset_backup"
    (( download_status == 0 )) || fail "AppWorld data download failed with exit code $download_status"
  fi
  check_packages || fail "Shared AppWorld environment failed dependency checks"
  data_ready || fail "AppWorld data was not installed"
  expected_stamp >"$stamp.tmp"
  mv -- "$stamp.tmp" "$stamp"
  printf 'Shared AppWorld environment ready: %s\n' "$venv"
}

case ${1:-setup} in
  setup) [[ $# -le 1 ]] || fail "Unexpected arguments"; setup ;;
  check) [[ $# == 1 ]] || fail "Unexpected arguments"; check_ready || fail "Run scripts/setup_appworld_venv.sh first" ;;
  -h|--help|help) printf 'Usage: bash scripts/setup_appworld_venv.sh [setup|check]\n' ;;
  *) fail "Unknown command: $1" ;;
esac
