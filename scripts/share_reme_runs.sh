#!/usr/bin/env bash
# Make the 12 completed ReMe formal runs visible in another local checkout.
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
project_root=$(cd -- "$script_dir/.." && pwd)
source_outputs=/home/jiayao/Metaskill-library/baselines/ace/ace-appworld/experiments/outputs
destination_outputs=$project_root/experiments/outputs
mode=link
dry_run=false

usage() {
  cat <<'EOF'
Usage: bash scripts/share_reme_runs.sh [--link|--copy] [--source-outputs DIR] [--destination-outputs DIR] [--dry-run]

Links the 12 completed formal12-20261025-a ReMe runs into this checkout's
experiments/outputs/ by default. --copy makes independent copies. Source runs
must already be available locally; this script cannot download them from GitHub.
Existing run paths are never overwritten. --dry-run validates and lists actions.
EOF
}

while (($#)); do
  case "$1" in
    --link) mode=link; shift ;;
    --copy) mode=copy; shift ;;
    --dry-run) dry_run=true; shift ;;
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

datasets=(
  intermediate_8h_test_normal
  intermediate_8h_test_challenge
  quick2h_test_normal_v2
  quick2h_test_challenge_v2
)
arms=(fixed dynamic cold_start)
runs=()

# Preflight the entire set before writing anything to the destination.
for dataset in "${datasets[@]}"; do
  for arm in "${arms[@]}"; do
    run=reme_formal12-20261025-a_${dataset}_${arm}_r01_qwen3.8-flash_run_0
    source_run=$source_outputs/$run
    destination_run=$destination_outputs/$run
    [[ -d $source_run && -f $source_run/run_manifest.json && -d $source_run/tasks &&
       -f $source_run/evaluations/$dataset.json ]] || {
      printf 'Missing or incomplete source run: %s\n' "$source_run" >&2
      exit 1
    }
    grep -q '"status": "complete"' "$source_run/run_manifest.json" || {
      printf 'Source manifest is not complete: %s\n' "$source_run/run_manifest.json" >&2
      exit 1
    }
    if [[ -e $destination_run || -L $destination_run ]]; then
      if [[ $destination_run == "$source_run" ]] ||
         { [[ $mode == link && -L $destination_run ]] &&
           [[ $(realpath -e -- "$destination_run") == "$source_run" ]]; }; then
        : # Already available at the requested destination.
      else
        printf 'Destination already exists; refusing to overwrite: %s\n' "$destination_run" >&2
        exit 1
      fi
    fi
    runs+=("$run")
  done
done

created=0
skipped=0
for run in "${runs[@]}"; do
  source_run=$source_outputs/$run
  destination_run=$destination_outputs/$run
  if [[ $destination_run == "$source_run" ]] ||
     { [[ $mode == link && -L $destination_run ]] &&
       [[ $(realpath -e -- "$destination_run") == "$source_run" ]]; }; then
    ((skipped += 1))
    continue
  fi
  if [[ $dry_run == true ]]; then
    printf 'Would %s %s -> %s\n' "$mode" "$source_run" "$destination_run"
  else
    mkdir -p -- "$destination_outputs"
    if [[ $mode == link ]]; then
      ln -s -- "$source_run" "$destination_run"
    else
      cp -a -- "$source_run" "$destination_run"
    fi
    printf '%s %s\n' "$mode" "$destination_run"
  fi
  ((created += 1))
done
printf 'Done: %d %s(s), %d already present%s.\n' "$created" "$mode" "$skipped" \
  "$( [[ $dry_run == true ]] && printf ' (dry run)' || true )"
