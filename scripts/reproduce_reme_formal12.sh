#!/usr/bin/env bash
# Rebuild the bundled ReMe AppWorld environment and run the 12 formal cells.
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)
source_root="$repo_root/baselines/reme2f37a15"
assets="$source_root"
workspace=${REME_REPRO_WORKSPACE:-"$repo_root/.repro-reme"}
appworld_commit=634d67c3bf54a2fb1fa55f4b1200a3ea91b162ce
appworld_url=https://github.com/jiayaogu/metaskill-appworld.git

usage() {
  cat <<'USAGE'
Usage:
  bash scripts/reproduce_reme_formal12.sh setup
  bash scripts/reproduce_reme_formal12.sh run /absolute/path/to/provider.env
  bash scripts/reproduce_reme_formal12.sh all /absolute/path/to/provider.env

setup clones the pinned AppWorld commit, copies the bundled frozen ReMe source,
creates separate Python 3.11 environments, and downloads official AppWorld data.
run starts a dedicated local Elasticsearch container (unless REME_ES_URL is set),
plans 12 cells, and executes 702 primary task attempts with real provider calls.
Set REME_CAMPAIGN to resume a previously started campaign; otherwise each run gets
a fresh campaign name. By default, outputs stay under this checkout at
  .repro-reme/ace-appworld/experiments/outputs/.

Optional: REME_CHAT_INPUT_RATE, REME_CHAT_OUTPUT_RATE, REME_CHAT_CACHED_RATE,
REME_EMBED_INPUT_RATE (USD per million tokens, historical defaults 0.64, 2.16,
0.08, 0.07); REME_FORMAL_ACCOUNTING_POLICY; REME_BASE_PORT; REME_TASK_TIMEOUT;
REME_RUNTIME_ROOT; REME_ES_URL; REME_REPRO_WORKSPACE.
USAGE
}

fail() { printf 'Error: %s\n' "$*" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1 || fail "Required command missing: $1"; }

clone_pin() {
  local url=$1 directory=$2 commit=$3
  if [[ ! -d "$directory/.git" ]]; then
    [[ ! -e "$directory" || -z $(ls -A "$directory" 2>/dev/null) ]] || fail "Refusing nonempty directory: $directory"
    git clone "$url" "$directory"
  fi
  if [[ $(git -C "$directory" rev-parse HEAD) != "$commit" ]]; then
    [[ -z $(git -C "$directory" status --porcelain) ]] || fail "Dirty checkout at $directory; cannot switch commits"
    git -C "$directory" cat-file -e "$commit^{commit}" 2>/dev/null || git -C "$directory" fetch origin "$commit"
    git -C "$directory" checkout --detach "$commit"
  fi
  [[ $(git -C "$directory" rev-parse HEAD) == "$commit" ]] || fail "Wrong commit at $directory"
}

verify_inputs() {
  python3.11 - "$assets/source-sha256.json" "${1:-$reme}" "$appworld" <<'PY'
import hashlib, json, sys
from pathlib import Path
manifest = json.loads(Path(sys.argv[1]).read_text())
for key, root in (("reme_source_sha256", Path(sys.argv[2])), ("appworld_sha256", Path(sys.argv[3]))):
    for relative, expected in manifest[key].items():
        path = root / relative
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise SystemExit(f"Source/data checksum mismatch: {path}")
print(f"Verified {len(manifest['reme_source_sha256'])} ReMe and {len(manifest['appworld_sha256'])} AppWorld files")
PY
}

setup() {
  need git
  need python3.11
  need git-lfs
  mkdir -p "$workspace"
  workspace=$(cd "$workspace" && pwd -P)
  appworld="$workspace/ace-appworld"
  reme="$workspace/ReMe-2f37a15"
  clone_pin "$appworld_url" "$appworld" "$appworld_commit"
  # The frozen test suite and default CLI lookup expect ../ace/ace-appworld.
  mkdir -p "$workspace/ace"
  if [[ -e "$workspace/ace/ace-appworld" || -L "$workspace/ace/ace-appworld" ]]; then
    [[ -L "$workspace/ace/ace-appworld" && $(readlink "$workspace/ace/ace-appworld") == ../ace-appworld ]] \
      || fail "Unexpected AppWorld compatibility path: $workspace/ace/ace-appworld"
  else
    ln -s ../ace-appworld "$workspace/ace/ace-appworld"
  fi
  git -C "$appworld" lfs install --local
  git -C "$appworld" lfs pull
  verify_inputs "$source_root"
  if [[ ! -d "$reme" ]]; then
    mkdir -p "$reme"
    cp -a "$source_root/." "$reme/"
  fi
  verify_inputs
  if [[ ! -x "$appworld/.venv/bin/python" ]]; then python3.11 -m venv "$appworld/.venv"; fi
  if [[ ! -x "$reme/.venv/bin/python" ]]; then python3.11 -m venv "$reme/.venv"; fi
  "$appworld/.venv/bin/python" -m pip install --upgrade pip setuptools wheel
  (cd "$appworld" && .venv/bin/python -m pip install -e . -e 'experiments[simplified]' \
    'ray==2.59.0' 'loguru>=0.7.3' 'pydantic==2.13.5' 'together==1.5.35')
  (cd "$appworld" && APPWORLD_PROJECT_PATH="$appworld" .venv/bin/appworld install --repo)
  (cd "$appworld" && APPWORLD_PROJECT_PATH="$appworld" .venv/bin/appworld download data)
  "$reme/.venv/bin/python" -m pip install --upgrade pip setuptools wheel
  "$reme/.venv/bin/python" -m pip install -c "$assets/constraints.txt" -e "$reme[light,ray]" 'sqlalchemy[asyncio]'
  "$appworld/.venv/bin/python" -m pip check
  "$reme/.venv/bin/python" -m pip check
  "$reme/.venv/bin/python" -c 'from reme.reme import ReMe; from reme.core.service.http_service import HttpService'
  # Two historical parity tests call `git show 2f37a15`; this vendored source has no ReMe Git history.
  # The frozen source and its AppWorld inputs have already passed the manifest hash checks above.
  (cd "$reme" && PYTHONWARNINGS=ignore "$appworld/.venv/bin/python" - <<'PY'
import sys
import unittest

excluded_names = {
    "test_original_core_ast_is_unchanged",
    "test_success_failure_arm_order_matches_pinned_core",
}
selected, excluded = [], []

def collect(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            collect(item)
        elif item.id().rsplit(".", 1)[-1] in excluded_names:
            excluded.append(item.id())
        else:
            selected.append(item)

collect(unittest.defaultTestLoader.discover("benchmark/appworld", pattern="test_*.py"))
if len(excluded) != 2:
    raise SystemExit(f"Expected two Git-history parity tests, found {excluded}")
print(f"Running {len(selected)} ReMe tests; frozen source and input hashes verified", flush=True)
result = unittest.TextTestRunner(verbosity=1).run(unittest.TestSuite(selected))
sys.exit(0 if result.wasSuccessful() else 1)
PY
  )
  printf 'Setup complete: %s\n' "$workspace"
}

write_accounting_policy() {
  if [[ -n ${REME_FORMAL_ACCOUNTING_POLICY:-} ]]; then
    [[ -f "$REME_FORMAL_ACCOUNTING_POLICY" ]] || fail "Accounting policy missing: $REME_FORMAL_ACCOUNTING_POLICY"
    policy=$(cd "$(dirname "$REME_FORMAL_ACCOUNTING_POLICY")" && pwd -P)/$(basename "$REME_FORMAL_ACCOUNTING_POLICY")
    return
  fi
  mkdir -p "$workspace/accounting"
  policy="$workspace/accounting/$campaign.json"
  "$reme/.venv/bin/python" - "$provider_file" "$policy" <<'PY'
import json, os, sys
from pathlib import Path
from dotenv import dotenv_values
values = dotenv_values(sys.argv[1], interpolate=False)
if not values.get("OPENAI_API_KEY") or not values.get("OPENAI_BASE_URL"):
    raise SystemExit("Provider file needs OPENAI_API_KEY and OPENAI_BASE_URL")
chat = values.get("LLM_BASE_URL") or values["OPENAI_BASE_URL"]
embed = values.get("EMBEDDING_BASE_URL") or (
    (values.get("DASHSCOPE_BASE_URL") or "https://dashscope.aliyuncs.com/compatible-mode/v1")
    if values.get("DASHSCOPE_API_KEY") else values["OPENAI_BASE_URL"]
)
def rate(name, default):
    from decimal import Decimal
    value = os.environ.get(name, default)
    number = Decimal(value)
    if not number.is_finite() or number < 0:
        raise SystemExit(f"Invalid nonnegative price: {name}")
    return value
data = {
    "schema_version": 1, "mode": "formal_accounting", "limit_usd": None,
    "scope": "ReMe AppWorld 12-run reproduction; 702 primary task attempts",
    "rate_basis": "Historical USD-per-million-token estimates; override rates for your provider; not an invoice or spending cap",
    "models": {
        "qwen3.8-flash": {
            "input": rate("REME_CHAT_INPUT_RATE", "0.64"),
            "output": rate("REME_CHAT_OUTPUT_RATE", "2.16"),
            "cached": rate("REME_CHAT_CACHED_RATE", "0.08"),
            "urls": sorted({chat.rstrip("/") + "/chat/completions", values["OPENAI_BASE_URL"].rstrip("/") + "/chat/completions"}),
        },
        "text-embedding-v4": {
            "input": rate("REME_EMBED_INPUT_RATE", "0.07"),
            "output": "0", "cached": "0",
            "urls": [embed.rstrip("/") + "/embeddings"],
        },
    },
}
path = Path(sys.argv[2]); encoded = (json.dumps(data, indent=2, sort_keys=True) + "\n").encode()
if path.exists() and path.read_bytes() != encoded:
    raise SystemExit(f"Accounting policy changed for existing campaign: {path}")
if not path.exists():
    path.write_bytes(encoded)
print(f"Accounting policy: {path}")
PY
}

prepare_elasticsearch() {
  need curl
  if [[ -z ${REME_ES_URL:-} ]]; then
    need docker
    docker compose -f "$assets/compose.yaml" up -d --wait --wait-timeout 180
    es_url=http://127.0.0.1:19200
  else
    es_url=${REME_ES_URL%/}
  fi
  curl --fail --silent --show-error "$es_url/_cluster/health?wait_for_status=yellow&timeout=30s" >/dev/null
  local template_url="$es_url/_index_template/reme-formal12-source-vectors"
  if ! curl --fail --silent --show-error -X PUT "$template_url?create=true" \
      -H 'Content-Type: application/json' --data-binary "@$assets/index-template.json" >/dev/null 2>&1; then
    curl --fail --silent --show-error "$template_url" | "$reme/.venv/bin/python" -c '
import json,sys
value=json.load(sys.stdin)["index_templates"][0]["index_template"]["template"]["settings"]
setting=value.get("index.mapping.exclude_source_vectors")
if setting is None:
    setting=value.get("index",{}).get("mapping",{}).get("exclude_source_vectors")
if str(setting).lower() != "false": raise SystemExit("Existing Elasticsearch template does not preserve source vectors")
' || fail "Could not install or verify the ReMe Elasticsearch template"
  fi
}

run() {
  need python3.11
  need git
  [[ $# == 1 && -f $1 ]] || fail "run needs an existing provider .env file"
  provider_file=$(cd "$(dirname "$1")" && pwd -P)/$(basename "$1")
  mkdir -p "$workspace"
  workspace=$(cd "$workspace" && pwd -P)
  appworld="$workspace/ace-appworld"
  reme="$workspace/ReMe-2f37a15"
  [[ -x "$appworld/.venv/bin/python" && -x "$reme/.venv/bin/python" ]] || fail "Run setup first"
  [[ $(git -C "$appworld" rev-parse HEAD) == "$appworld_commit" ]] || fail "AppWorld commit changed"
  verify_inputs "$source_root"
  verify_inputs
  campaign=${REME_CAMPAIGN:-repro-$(date -u +%Y%m%d-%H%M%S)}
  [[ $campaign =~ ^[a-z0-9][a-z0-9_-]{0,39}$ ]] || fail "Invalid campaign name"
  write_accounting_policy
  prepare_elasticsearch
  export APPWORLD_PROJECT_PATH="$appworld"
  export APPWORLD_ROOT="$appworld"
  export REME_FORMAL_ACCOUNTING_FILE="$policy"
  export APPWORLD_LM_LOGGER_MODULE_PATH="$appworld/experiments/code/common/lm_logger.py"
  "$appworld/.venv/bin/python" - <<'PY'
from appworld import load_task_ids
from appworld.task import Task
for dataset in ("intermediate_8h_test_normal", "intermediate_8h_test_challenge", "quick2h_test_normal_v2", "quick2h_test_challenge_v2"):
    for task_id in load_task_ids(dataset):
        task = Task.load(task_id, load_ground_truth=False)
        task.close()
print("All selected AppWorld tasks load successfully")
PY
  local outputs="$appworld/experiments/outputs"
  shopt -s nullglob
  local manifests=("$outputs"/reme_"$campaign"_*_run_0/run_manifest.json)
  shopt -u nullglob
  if (( ${#manifests[@]} == 0 )); then
    (cd "$reme" && "$appworld/.venv/bin/python" benchmark/appworld/execution_matrix.py \
      --appworld-root "$appworld" --campaign "$campaign" --formal-accounting "$policy")
  elif (( ${#manifests[@]} != 12 )); then
    fail "Campaign $campaign has ${#manifests[@]} manifests; expected 12"
  fi
  printf 'Starting campaign %s; this makes real provider calls.\n' "$campaign"
  (cd "$reme" && "$appworld/.venv/bin/python" benchmark/appworld/execution_coordinator.py \
    --execute-formal --appworld-root "$appworld" --campaign "$campaign" \
    --env-file "$provider_file" --formal-accounting "$policy" \
    --service-python "$reme/.venv/bin/python" --es-url "$es_url" \
    --task-timeout "${REME_TASK_TIMEOUT:-3600}" \
    --base-port "${REME_BASE_PORT:-18101}" \
    --runtime-root "${REME_RUNTIME_ROOT:-/tmp/rr}")
  printf 'Results: %s/reme_%s_*_run_0\n' "$outputs" "$campaign"
  printf 'Campaign summary: %s/.reme-formal-campaigns/%s/coordinator_summary.json\n' "$outputs" "$campaign"
}

case ${1:-} in
  setup) [[ $# == 1 ]] || { usage; exit 2; }; setup ;;
  run) [[ $# == 2 ]] || { usage; exit 2; }; run "$2" ;;
  all) [[ $# == 2 ]] || { usage; exit 2; }; setup; run "$2" ;;
  -h|--help|help) usage ;;
  *) usage; exit 2 ;;
esac
