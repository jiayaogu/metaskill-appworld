#!/usr/bin/env bash
# Reproduce the Qwen3.8-flash ACE intermediate8h and quick2h-v2 comparisons.
set -euo pipefail

repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
workspace=${ACE_REPRO_WORKSPACE:-"$repo_root/.repro-ace-appworld"}
[[ $workspace == /* ]] || workspace=$repo_root/$workspace
ace_url=https://github.com/ace-agent/ace.git
ace_commit=82709de050e1db6e6ef2f07bcb0393560b94992a
appworld_url=https://github.com/jgu13/metaskill-appworld.git
appworld_commit=634d67c3bf54a2fb1fa55f4b1200a3ea91b162ce

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

usage() {
  cat <<'EOF'
Usage: bash scripts/reproduce_ace_appworld.sh {plan|setup|run|all}

  plan   Print the 10 run/evaluate pairs; no network or model calls.
  setup  Clone pinned ACE and AppWorld sources into ACE_REPRO_WORKSPACE,
         create separate virtual environments, and install AppWorld data.
  run    Execute all 10 runs sequentially, then official evaluations.
  all    setup followed by run.

Set ACE_REPRO_WORKSPACE to choose an empty, persistent workspace. The default
is <this repository>/.repro-ace-appworld. `run` requires OPENAI_API_KEY and
uses the Qwen3.8-flash endpoint defined in the checked-in Jsonnet configs.
It makes real provider calls. Existing output directories are never overwritten.
EOF
}

fail() { printf 'Error: %s\n' "$*" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1 || fail "Required command missing: $1"; }

clone_pin() {
  local url=$1 destination=$2 commit=$3
  if [[ ! -e $destination ]]; then
    git clone -- "$url" "$destination"
  fi
  [[ -d $destination/.git ]] || fail "Not a Git checkout: $destination"
  if [[ $(git -C "$destination" rev-parse HEAD) != "$commit" ]]; then
    [[ -z $(git -C "$destination" status --porcelain) ]] || fail "Dirty checkout: $destination"
    git -C "$destination" cat-file -e "$commit^{commit}" 2>/dev/null || git -C "$destination" fetch origin "$commit"
    git -C "$destination" checkout --detach "$commit"
  fi
  [[ $(git -C "$destination" rev-parse HEAD) == "$commit" ]] || fail "Wrong source commit: $destination"
}

print_plan() {
  printf 'ACE reference: %s @ %s\n' "$ace_url" "$ace_commit"
  printf 'AppWorld runner: %s @ %s\n' "$appworld_url" "$appworld_commit"
  printf 'Workspace: %s\n' "$workspace"
  printf 'Config root: <workspace>/ace-appworld/experiments/configs/\n'
  printf 'Output root: <workspace>/ace-appworld/experiments/outputs/\n'
  for i in "${!runs[@]}"; do
    printf '%2d. appworld run %s --root .\n' "$((i + 1))" "${runs[$i]}"
    printf '    appworld evaluate %s %s --root .  (%s tasks)\n' \
      "${runs[$i]}" "${datasets[$i]}" "${expected_counts[$i]}"
  done
  printf 'Quick2h v2 frozen tests use the playbook trained on quick2h_train (v1).\n'
}

setup() {
  need git
  need git-lfs
  need python3.11
  need uv
  mkdir -p -- "$workspace"
  workspace=$(cd -- "$workspace" && pwd -P)
  local ace_ref=$workspace/ace-reference
  local appworld=$workspace/ace-appworld
  clone_pin "$ace_url" "$ace_ref" "$ace_commit"
  clone_pin "$appworld_url" "$appworld" "$appworld_commit"
  (cd "$ace_ref" && uv sync --frozen)
  git -C "$appworld" lfs install --local
  git -C "$appworld" lfs pull
  if [[ ! -x $appworld/.venv/bin/python ]]; then python3.11 -m venv "$appworld/.venv"; fi
  "$appworld/.venv/bin/python" -m pip install --upgrade pip setuptools wheel
  (cd "$appworld" && .venv/bin/python -m pip install -e . -e 'experiments[simplified]')
  (cd "$appworld" && APPWORLD_PROJECT_PATH="$appworld" .venv/bin/appworld install --repo)
  (cd "$appworld" && APPWORLD_PROJECT_PATH="$appworld" .venv/bin/appworld download data)
  "$appworld/.venv/bin/python" -m pip check
  printf 'Setup complete. ACE venv: %s/.venv; AppWorld runner venv: %s/.venv\n' "$ace_ref" "$appworld"
}

check_inputs() {
  local appworld=$1
  "$appworld/.venv/bin/python" - "$appworld" <<'PY'
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

clear_reference_playbooks() {
  local appworld=$1
  local folder file relative
  for folder in \
    experiments/playbooks/intermediate_8h/qwen3.8-flash \
    experiments/playbooks/quick2h_offline_online/qwen3.8-flash \
    experiments/playbooks/quick2h_v1train_v2test_20261026_retry1/qwen3.8-flash; do
    while IFS= read -r -d '' file; do
      relative=${file#"$appworld"/}
      git -C "$appworld" ls-files --error-unmatch -- "$relative" >/dev/null 2>&1 || fail "Untracked playbook: $file"
      git -C "$appworld" show "HEAD:$relative" | cmp -s - "$file" || fail "Modified playbook: $file"
      rm -- "$file"
    done < <(find "$appworld/$folder" -maxdepth 1 -type f -name '*.txt' -print0)
  done
  printf 'Cleared checked-in result playbooks from the isolated runner clone.\n'
}

verify_result() {
  local appworld=$1 run=$2 dataset=$3 count=$4
  "$appworld/.venv/bin/python" - "$appworld" "$run" "$dataset" "$count" <<'PY'
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
  local appworld=$workspace/ace-appworld
  [[ -x $appworld/.venv/bin/appworld ]] || fail "Run setup first: $appworld"
  [[ $(git -C "$appworld" rev-parse HEAD) == "$appworld_commit" ]] || fail "Wrong AppWorld commit"
  [[ -n ${OPENAI_API_KEY:-} ]] || fail "Set OPENAI_API_KEY for the configured Qwen3.8-flash endpoint"
  for run in "${runs[@]}"; do
    [[ ! -e $appworld/experiments/outputs/$run && ! -L $appworld/experiments/outputs/$run ]] || fail "Output already exists: $appworld/experiments/outputs/$run"
    [[ -f $appworld/experiments/configs/$run.jsonnet ]] || fail "Missing config: $run"
  done
  (cd "$appworld" && git diff --quiet -- src experiments/code experiments/configs data/datasets) || fail "Runner code, configs, or dataset manifests changed"
  (cd "$appworld" && git diff --cached --quiet -- src experiments/code experiments/configs data/datasets) || fail "Staged runner inputs changed"
  export APPWORLD_PROJECT_PATH=$appworld
  (cd "$appworld" && check_inputs "$appworld")
  clear_reference_playbooks "$appworld"
  for i in "${!runs[@]}"; do
    printf '\n[%d/%d] %s on %s\n' "$((i + 1))" "${#runs[@]}" "${runs[$i]}" "${datasets[$i]}"
    (cd "$appworld" && .venv/bin/appworld run "${runs[$i]}" --root .)
    (cd "$appworld" && .venv/bin/appworld evaluate "${runs[$i]}" "${datasets[$i]}" --root .)
    verify_result "$appworld" "${runs[$i]}" "${datasets[$i]}" "${expected_counts[$i]}"
  done
  printf '\nAll 10 ACE runs completed. Outputs: %s/experiments/outputs/\n' "$appworld"
}

case ${1:-} in
  plan) [[ $# == 1 ]] || fail "Unexpected arguments"; print_plan ;;
  setup) [[ $# == 1 ]] || fail "Unexpected arguments"; setup ;;
  run) [[ $# == 1 ]] || fail "Unexpected arguments"; run_all ;;
  all) [[ $# == 1 ]] || fail "Unexpected arguments"; setup; run_all ;;
  *) usage >&2; exit 2 ;;
esac
