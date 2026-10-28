#!/usr/bin/env bash
# Reproduce the Qwen3.8-flash ACE intermediate8h and quick2h-v2 comparisons.
set -euo pipefail

repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
workspace=${ACE_REPRO_WORKSPACE:-"$repo_root/.repro-ace-appworld"}
[[ $workspace == /* ]] || workspace=$repo_root/$workspace
venv=$repo_root/.venv-appworld

# Required source and input paths supplied by the user's AppWorld checkout.
required_paths=(
  pyproject.toml
  experiments/setup.py
  experiments/__init__.py
  experiments/code/__init__.py
  src/appworld
  experiments/code/ace
  experiments/code/common
  experiments/configs/ACE_intermediate_8h
  experiments/configs/ACE_quick2h_offline_online
  experiments/configs/ACE_quick2h_v2_offline_online
  data/datasets
  experiments/prompts
  experiments/playbooks/appworld_initial_playbook.txt
  scripts/setup_appworld_venv.sh
)

runs=(
  ACE_intermediate_8h/qwen3.8-flash/offline_no_GT_adaptation
  ACE_intermediate_8h/qwen3.8-flash/offline_no_GT_evaluation_test_normal
  ACE_intermediate_8h/qwen3.8-flash/offline_no_GT_evaluation_test_challenge
  ACE_intermediate_8h/qwen3.8-flash/online_no_GT_test_normal
  ACE_intermediate_8h/qwen3.8-flash/online_no_GT_test_challenge
  ACE_quick2h_offline_online/qwen3.8-flash/offline_no_GT_adaptation
  ACE_quick2h_v2_offline_online/qwen3.8-flash/offline_no_GT_evaluation_test_normal_v2
  ACE_quick2h_v2_offline_online/qwen3.8-flash/offline_no_GT_evaluation_test_challenge_v2
  ACE_quick2h_v2_offline_online/qwen3.8-flash/online_no_GT_test_normal_v2
  ACE_quick2h_v2_offline_online/qwen3.8-flash/online_no_GT_test_challenge_v2
)
datasets=(
  intermediate_8h_train
  intermediate_8h_test_normal
  intermediate_8h_test_challenge
  intermediate_8h_test_normal
  intermediate_8h_test_challenge
  quick2h_train
  quick2h_test_normal_v2
  quick2h_test_challenge_v2
  quick2h_test_normal_v2
  quick2h_test_challenge_v2
)
expected_counts=(30 57 138 57 138 15 21 18 21 18)
playbooks=(
  intermediate_offline.txt
  intermediate_offline.txt
  intermediate_offline.txt
  intermediate_online_normal.txt
  intermediate_online_challenge.txt
  quick_offline.txt
  quick_offline.txt
  quick_offline.txt
  quick_online_normal.txt
  quick_online_challenge.txt
)

usage() {
  cat <<'EOF'
Usage: bash scripts/reproduce_ace_appworld.sh {plan|check|setup|run|all}

  plan   Print the 10 run/evaluate pairs; no network or model calls.
  check  Verify required ACE/AppWorld source and experiment input paths exist.
  setup  Prepare the shared AppWorld environment and install AppWorld data.
  run    Execute all 10 runs sequentially, then official evaluations.
  all    setup followed by run.

The checked-out AppWorld repository supplies the ACE runner; no ACE or AppWorld
clone is created. The shared environment is <this repository>/.venv-appworld.
Set ACE_REPRO_WORKSPACE for new playbooks (default: .repro-ace-appworld).
Run outputs go to
this repository's experiments/outputs/. `run` requires OPENAI_API_KEY and makes
real provider calls. Existing output or playbook paths are never overwritten.
EOF
}

fail() { printf 'Error: %s\n' "$*" >&2; exit 1; }
check_checkout() {
  local path run dataset
  for path in "${required_paths[@]}"; do
    [[ -e $repo_root/$path ]] || fail "Missing required path: $path"
  done
  for run in "${runs[@]}"; do
    [[ -f $repo_root/experiments/configs/$run.jsonnet ]] || fail "Missing config: $run"
  done
  for dataset in "${datasets[@]}"; do
    [[ -f $repo_root/data/datasets/$dataset.txt ]] || fail "Missing dataset: $dataset"
  done
  printf 'Checkout OK: required ACE/AppWorld source and experiment input paths exist.\n'
}

print_plan() {
  printf 'ACE/AppWorld checkout: %s\n' "$repo_root"
  printf 'Shared AppWorld environment: %s\n' "$venv"
  printf 'New playbooks: %s/playbooks/\n' "$workspace"
  printf 'Config root: %s/experiments/configs/\n' "$repo_root"
  printf 'Output root: %s/experiments/outputs/\n' "$repo_root"
  for i in "${!runs[@]}"; do
    printf '%2d. appworld run %s --override <playbook: %s> --root .\n' \
      "$((i + 1))" "${runs[$i]}" "${playbooks[$i]}"
    printf '    appworld evaluate %s %s --root .  (%s tasks)\n' \
      "${runs[$i]}" "${datasets[$i]}" "${expected_counts[$i]}"
  done
  printf 'Quick2h v2 frozen tests use the playbook trained on quick2h_train (v1).\n'
}

setup() {
  check_checkout
  bash "$repo_root/scripts/setup_appworld_venv.sh" setup
  printf 'Setup complete. AppWorld/ACE environment: %s\n' "$venv"
}

check_inputs() {
  "$venv/bin/python" - "$repo_root" <<'PY'
import sys
from pathlib import Path
from appworld.task import Task, load_task_ids

root = Path(sys.argv[1])
expected = {
    "intermediate_8h_train": 30,
    "intermediate_8h_test_normal": 57,
    "intermediate_8h_test_challenge": 138,
    "quick2h_train": 15,
    "quick2h_test_normal_v2": 21,
    "quick2h_test_challenge_v2": 18,
}
for dataset, count in expected.items():
    assert (root / "data/datasets" / f"{dataset}.txt").is_file(), dataset
    ids = load_task_ids(dataset)
    assert len(ids) == count and len(set(ids)) == count, (dataset, len(ids))
    for task_id in ids:
        Task.load(task_id=task_id)
    print(f"Input OK: {dataset}: {count} tasks")
PY
}

make_override() {
  local playbook=$1
  "$venv/bin/python" - "$playbook" <<'PY'
import json
import sys
print(json.dumps({"config": {"agent": {"trained_playbook_file_path": sys.argv[1]}}}))
PY
}

verify_result() {
  local run=$1 dataset=$2 count=$3
  "$venv/bin/python" - "$repo_root" "$run" "$dataset" "$count" <<'PY'
import json
import sys
from pathlib import Path

root, run, dataset, expected_count = Path(sys.argv[1]), sys.argv[2], sys.argv[3], int(sys.argv[4])
output = root / "experiments/outputs" / run
ids = [line.strip() for line in (root / "data/datasets" / f"{dataset}.txt").read_text().splitlines() if line.strip()]
assert len(ids) == expected_count and len(set(ids)) == expected_count
result = json.loads((output / "evaluations" / f"{dataset}.json").read_text())
assert set(result["individual"]) == set(ids), (run, "official evaluation task IDs differ")
task_dirs = {p.name for p in (output / "tasks").iterdir() if p.is_dir()}
assert task_dirs == set(ids), (run, "task directories differ")
for task_id in ids:
    task = output / "tasks" / task_id
    for suffix in ("logs/lm_calls.jsonl", "logs/environment_io.md", "logs/api_calls.jsonl", "evaluation/report.md"):
        assert (task / suffix).is_file(), task / suffix
aggregate = result["aggregate"]
print(f"PASS {run}: {expected_count} tasks; TGC={aggregate['task_goal_completion']}%; SGC={aggregate['scenario_goal_completion']}%")
PY
}

run_all() {
  check_checkout
  bash "$repo_root/scripts/setup_appworld_venv.sh" check
  [[ -n ${OPENAI_API_KEY:-} ]] || fail "Set OPENAI_API_KEY for the configured Qwen3.8-flash endpoint"
  for run in "${runs[@]}"; do
    [[ ! -e $repo_root/experiments/outputs/$run && ! -L $repo_root/experiments/outputs/$run ]] || fail "Output already exists: $repo_root/experiments/outputs/$run"
  done
  local book
  for book in "${playbooks[@]}"; do
    [[ ! -e $workspace/playbooks/$book && ! -L $workspace/playbooks/$book ]] || fail "Playbook already exists: $workspace/playbooks/$book"
  done
  export APPWORLD_PROJECT_PATH=$repo_root
  (cd "$repo_root" && check_inputs)
  mkdir -p -- "$workspace/playbooks"
  local override
  for i in "${!runs[@]}"; do
    printf '\n[%d/%d] %s on %s\n' "$((i + 1))" "${#runs[@]}" "${runs[$i]}" "${datasets[$i]}"
    override=$(make_override "$workspace/playbooks/${playbooks[$i]}")
    (cd "$repo_root" && "$venv/bin/appworld" run "${runs[$i]}" --override "$override" --root .)
    (cd "$repo_root" && "$venv/bin/appworld" evaluate "${runs[$i]}" "${datasets[$i]}" --root .)
    verify_result "${runs[$i]}" "${datasets[$i]}" "${expected_counts[$i]}"
  done
  printf '\nAll 10 ACE runs completed. Outputs: %s/experiments/outputs/\n' "$repo_root"
}

case ${1:-} in
  plan) [[ $# == 1 ]] || fail "Unexpected arguments"; print_plan ;;
  check) [[ $# == 1 ]] || fail "Unexpected arguments"; check_checkout ;;
  setup) [[ $# == 1 ]] || fail "Unexpected arguments"; setup ;;
  run) [[ $# == 1 ]] || fail "Unexpected arguments"; run_all ;;
  all) [[ $# == 1 ]] || fail "Unexpected arguments"; setup; run_all ;;
  *) usage >&2; exit 2 ;;
esac
