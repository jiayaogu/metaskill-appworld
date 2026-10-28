#!/usr/bin/env bash
# Rebuild the bundled ReMe AppWorld environment and run the 12 formal cells.
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)
# The AppWorld checkout supplies datasets and runner code; ReMe runs in place.
source_root="$repo_root/baselines/reme2f37a15"
assets="$source_root"
appworld="$repo_root"
appworld_venv="$repo_root/.venv-appworld"
reme_venv="$repo_root/.venv-reme"

usage() {
  cat <<'USAGE'
Usage:
  bash scripts/reproduce_reme_formal12.sh check
  bash scripts/reproduce_reme_formal12.sh setup
  bash scripts/reproduce_reme_formal12.sh run /absolute/path/to/provider.env
  bash scripts/reproduce_reme_formal12.sh all /absolute/path/to/provider.env

check verifies required dataset, AppWorld, and bundled ReMe source paths exist.
setup prepares the shared AppWorld environment and a separate Python 3.11
ReMe service environment. The bundled ReMe source runs in place.
run starts a dedicated local Elasticsearch container (unless REME_ES_URL is set),
plans 12 cells, and executes 702 primary task attempts with real provider calls.
Set REME_CAMPAIGN to resume a previously started campaign; otherwise each run gets
a fresh campaign name. Outputs and campaign accounting are written under
  experiments/outputs/.

Optional: REME_CHAT_INPUT_RATE, REME_CHAT_OUTPUT_RATE, REME_CHAT_CACHED_RATE,
REME_EMBED_INPUT_RATE (USD per million tokens, historical defaults 0.64, 2.16,
0.08, 0.07); REME_FORMAL_ACCOUNTING_POLICY; REME_BASE_PORT; REME_TASK_TIMEOUT;
REME_RUNTIME_ROOT; REME_ES_URL.
USAGE
}

fail() { printf 'Error: %s\n' "$*" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1 || fail "Required command missing: $1"; }

# Check the bundled ReMe tree used by the executor.
check_reme_source() {
  local root=$1 relative
  for relative in \
    pyproject.toml benchmark/appworld/execution_matrix.py \
    benchmark/appworld/execution_coordinator.py benchmark/appworld/execution_audit.py \
    benchmark/appworld/execution_accounting.py benchmark/appworld/execution_budget.py \
    benchmark/appworld/execution_recovery.py benchmark/appworld/execution_scheduler.py \
    benchmark/appworld/appworld_react_agent.py benchmark/appworld/appworld_reward.py \
    benchmark/appworld/prompt.py reme/config/service.yaml \
    docs/library/paper_data/task/appworld_qwen3_8b.jsonl; do
    [[ -f "$root/$relative" ]] || fail "Missing ReMe source or input: $root/$relative"
  done
}

# Fail before installation or provider calls if required checkout paths are missing.
check_sources() {
  local relative
  for relative in \
    pyproject.toml experiments/setup.py src/appworld/task.py \
    src/appworld/environment.py src/appworld/evaluator.py \
    experiments/code/common/lm_logger.py scripts/setup_appworld_venv.sh \
    data/datasets/intermediate_8h_test_normal.txt \
    data/datasets/intermediate_8h_test_challenge.txt \
    data/datasets/quick2h_test_normal_v2.txt \
    data/datasets/quick2h_test_challenge_v2.txt; do
    [[ -f "$appworld/$relative" ]] || fail "Missing AppWorld source or dataset: $appworld/$relative"
  done
  for relative in constraints.txt compose.yaml index-template.json; do
    [[ -f "$assets/$relative" ]] || fail "Missing ReMe setup asset: $assets/$relative"
  done
  check_reme_source "$source_root"
  printf 'Checkout OK: required AppWorld, ReMe, dataset, and setup asset paths exist.\n'
}

setup() {
  check_sources
  bash "$repo_root/scripts/setup_appworld_venv.sh" setup
  # Keep the ReMe service environment separate from the shared AppWorld runner.
  # The shared setup has hydrated AppWorld's Git LFS files.
  check_sources
  if [[ ! -x "$reme_venv/bin/python" ]]; then python3.11 -m venv "$reme_venv"; fi
  "$reme_venv/bin/python" -m pip install --upgrade pip setuptools wheel
  "$reme_venv/bin/python" -m pip install -c "$assets/constraints.txt" -e "$source_root[light,ray]" 'sqlalchemy[asyncio]'
  "$reme_venv/bin/python" -m pip check
  "$reme_venv/bin/python" -c 'from reme.reme import ReMe; from reme.core.service.http_service import HttpService'
  # Point offline tests at this checkout. Two parity tests need upstream ReMe Git history.
  (cd "$source_root" && APPWORLD_PROJECT_PATH="$appworld" PYTHONWARNINGS=ignore "$appworld_venv/bin/python" - <<'PY'
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path.cwd() / "benchmark/appworld"))
import execution_matrix

execution_matrix.DEFAULT_APPWORLD_ROOT = Path(os.environ["APPWORLD_PROJECT_PATH"]).resolve()

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
print(f"Running {len(selected)} ReMe tests against this checkout", flush=True)
result = unittest.TextTestRunner(verbosity=1).run(unittest.TestSuite(selected))
sys.exit(0 if result.wasSuccessful() else 1)
PY
  )
  printf 'Setup complete: ReMe source %s; service environment %s\n' "$source_root" "$reme_venv"
}

# Build the campaign's immutable cost policy from provider URLs and token rates.
# Formal accounting records estimated USD with no spending ceiling.
write_accounting_policy() {
  if [[ -n ${REME_FORMAL_ACCOUNTING_POLICY:-} ]]; then
    [[ -f "$REME_FORMAL_ACCOUNTING_POLICY" ]] || fail "Accounting policy missing: $REME_FORMAL_ACCOUNTING_POLICY"
    policy=$(cd "$(dirname "$REME_FORMAL_ACCOUNTING_POLICY")" && pwd -P)/$(basename "$REME_FORMAL_ACCOUNTING_POLICY")
    return
  fi
  local campaign_state="$appworld/experiments/outputs/.reme-formal-campaigns/$campaign"
  mkdir -p "$campaign_state"
  policy="$campaign_state/accounting_policy.json"
  "$reme_venv/bin/python" - "$provider_file" "$policy" <<'PY'
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
# Resuming a campaign with different rates or endpoints would mix cost evidence.
if path.exists() and path.read_bytes() != encoded:
    raise SystemExit(f"Accounting policy changed for existing campaign: {path}")
if not path.exists():
    path.write_bytes(encoded)
print(f"Accounting policy: {path}")
PY
}

# Start the owned local container, or validate the selected external ES endpoint.
# The index template keeps embedding vectors in _source for checkpoint recovery.
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
  # If the template already exists, verify its required setting before reuse.
  if ! curl --fail --silent --show-error -X PUT "$template_url?create=true" \
      -H 'Content-Type: application/json' --data-binary "@$assets/index-template.json" >/dev/null 2>&1; then
    curl --fail --silent --show-error "$template_url" | "$reme_venv/bin/python" -c '
import json,sys
value=json.load(sys.stdin)["index_templates"][0]["index_template"]["template"]["settings"]
setting=value.get("index.mapping.exclude_source_vectors")
if setting is None:
    setting=value.get("index",{}).get("mapping",{}).get("exclude_source_vectors")
if str(setting).lower() != "false": raise SystemExit("Existing Elasticsearch template does not preserve source vectors")
' || fail "Could not install or verify the ReMe Elasticsearch template"
  fi
}

# Check all local inputs before preparing services or making model requests.
run() {
  check_sources
  bash "$repo_root/scripts/setup_appworld_venv.sh" check
  [[ $# == 1 && -f $1 ]] || fail "run needs an existing provider .env file"
  provider_file=$(cd "$(dirname "$1")" && pwd -P)/$(basename "$1")
  [[ -x "$reme_venv/bin/python" ]] || fail "Run ReMe setup first"
  campaign=${REME_CAMPAIGN:-repro-$(date -u +%Y%m%d-%H%M%S)}
  [[ $campaign =~ ^[a-z0-9][a-z0-9_-]{0,39}$ ]] || fail "Invalid campaign name"
  write_accounting_policy
  prepare_elasticsearch
  export APPWORLD_PROJECT_PATH="$appworld"
  export APPWORLD_ROOT="$appworld"
  export REME_FORMAL_ACCOUNTING_FILE="$policy"
  export APPWORLD_LM_LOGGER_MODULE_PATH="$appworld/experiments/code/common/lm_logger.py"
  # Load every selected task without ground truth before planning any run.
  "$appworld_venv/bin/python" - <<'PY'
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
  # Plan a new campaign once; preserve all twelve manifests on resume.
  if (( ${#manifests[@]} == 0 )); then
    (cd "$source_root" && "$appworld_venv/bin/python" benchmark/appworld/execution_matrix.py \
      --appworld-root "$appworld" --campaign "$campaign" --formal-accounting "$policy")
  elif (( ${#manifests[@]} != 12 )); then
    fail "Campaign $campaign has ${#manifests[@]} manifests; expected 12"
  fi
  # The coordinator owns run scheduling, task order, recovery, and provider calls.
  printf 'Starting campaign %s; this makes real provider calls.\n' "$campaign"
  (cd "$source_root" && "$appworld_venv/bin/python" benchmark/appworld/execution_coordinator.py \
    --execute-formal --appworld-root "$appworld" --campaign "$campaign" \
    --env-file "$provider_file" --formal-accounting "$policy" \
    --service-python "$reme_venv/bin/python" --es-url "$es_url" \
    --task-timeout "${REME_TASK_TIMEOUT:-3600}" \
    --base-port "${REME_BASE_PORT:-18101}" \
    --runtime-root "${REME_RUNTIME_ROOT:-/tmp/rr}")
  printf 'Results: %s/reme_%s_*_run_0\n' "$outputs" "$campaign"
  printf 'Campaign summary: %s/.reme-formal-campaigns/%s/coordinator_summary.json\n' "$outputs" "$campaign"
}

case ${1:-} in
  check) [[ $# == 1 ]] || { usage; exit 2; }; check_sources ;;
  setup) [[ $# == 1 ]] || { usage; exit 2; }; setup ;;
  run) [[ $# == 2 ]] || { usage; exit 2; }; run "$2" ;;
  all) [[ $# == 2 ]] || { usage; exit 2; }; setup; run "$2" ;;
  -h|--help|help) usage ;;
  *) usage; exit 2 ;;
esac
