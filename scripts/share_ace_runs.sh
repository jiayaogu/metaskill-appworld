#!/usr/bin/env bash
# Make the 14 completed ACE comparison runs visible in another local checkout.
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
project_root=$(cd -- "$script_dir/.." && pwd)
source_outputs=/home/jiayao/Metaskill-library/baselines/ace/ace-appworld/experiments/outputs
destination_outputs=$project_root/experiments/outputs
mode=link

usage() {
  cat <<'EOF'
Usage: bash scripts/share_ace_runs.sh [--link|--copy] [--source-outputs DIR] [--destination-outputs DIR]

Links the 14 completed intermediate8h and quick2h ACE comparison runs into
this checkout's experiments/outputs/ by default. --copy makes independent
copies instead. Existing run paths are never overwritten.
EOF
}

while (($#)); do
  case "$1" in
    --link) mode=link; shift ;;
    --copy) mode=copy; shift ;;
    --source-outputs|--destination-outputs)
      (($# >= 2)) || { usage >&2; exit 2; }
      if [[ $1 == --source-outputs ]]; then
        source_outputs=$2
      else
        destination_outputs=$2
      fi
      shift 2
      ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'Unknown argument: %s\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
done

source_outputs=$(realpath -e -- "$source_outputs")
destination_outputs=$(realpath -m -- "$destination_outputs")

runs=(
  ACE_intermediate_8h/qwen3.8-flash/offline_no_GT_adaptation
  ACE_intermediate_8h/qwen3.8-flash/offline_no_GT_evaluation_test_normal
  ACE_intermediate_8h/qwen3.8-flash/offline_no_GT_evaluation_test_challenge
  ACE_intermediate_8h/qwen3.8-flash/online_no_GT_test_normal
  ACE_intermediate_8h/qwen3.8-flash/online_no_GT_test_challenge
  ACE_quick2h_offline_online/qwen3.8-flash/offline_no_GT_adaptation
  ACE_quick2h_offline_online/qwen3.8-flash/offline_no_GT_evaluation_test_normal
  ACE_quick2h_offline_online/qwen3.8-flash/offline_no_GT_evaluation_test_challenge
  ACE_quick2h_offline_online/qwen3.8-flash/online_no_GT_test_normal
  ACE_quick2h_offline_online/qwen3.8-flash/online_no_GT_test_challenge
  ACE_quick2h_v1train_v2test_20261026_retry1/qwen3.8-flash/offline_no_GT_evaluation_test_normal_v2
  ACE_quick2h_v1train_v2test_20261026_retry1/qwen3.8-flash/offline_no_GT_evaluation_test_challenge_v2
  ACE_quick2h_v1train_v2test_20261026_retry1/qwen3.8-flash/online_no_GT_test_normal_v2
  ACE_quick2h_v1train_v2test_20261026_retry1/qwen3.8-flash/online_no_GT_test_challenge_v2
)

# Check every path before creating any link or copy.
for run in "${runs[@]}"; do
  source_run=$source_outputs/$run
  destination_run=$destination_outputs/$run
  [[ -d $source_run ]] || { printf 'Missing source run: %s\n' "$source_run" >&2; exit 1; }
  if [[ -e $destination_run || -L $destination_run ]]; then
    if [[ $destination_run == "$source_run" ]] ||
       { [[ -L $destination_run ]] && [[ $(realpath -e -- "$destination_run") == "$source_run" ]]; }; then
      continue
    fi
    printf 'Destination already exists; refusing to overwrite: %s\n' "$destination_run" >&2
    exit 1
  fi
done

created=0
skipped=0
for run in "${runs[@]}"; do
  source_run=$source_outputs/$run
  destination_run=$destination_outputs/$run
  if [[ $destination_run == "$source_run" ]] ||
     { [[ -L $destination_run ]] && [[ $(realpath -e -- "$destination_run") == "$source_run" ]]; }; then
    ((skipped += 1))
    continue
  fi
  mkdir -p -- "$(dirname -- "$destination_run")"
  if [[ $mode == link ]]; then
    ln -s -- "$source_run" "$destination_run"
  else
    cp -a -- "$source_run" "$destination_run"
  fi
  ((created += 1))
  printf '%s %s\n' "$mode" "$destination_run"
done
printf 'Done: %d %s(s), %d already present.\n' "$created" "$mode" "$skipped"
