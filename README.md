# Install a clean AppWorld environment for all baselines

This guide sets up a clean ACE AppWorld environment from source.

## Prerequisites

```bash
git lfs install # if not installed already
git clone https://github.com/ace-agent/ace-appworld.git ace-appworld
cd ace-appworld

export APPWORLD_PROJECT_PATH="$(pwd)"

python3.11 -m venv .venv-clean-appworld
source .venv-clean-appworld/bin/activate

python -m pip install --upgrade pip setuptools wheel
pip install -e .
pip install -e "experiments[simplified]"

appworld install --repo # install AppWorld
appworld download data
```

## Re-enter an Existing Environment

```bash
cd /home/jiayao/Metaskill-library/baselines/ace/ace-appworld
source .venv-clean-appworld/bin/activate
export APPWORLD_PROJECT_PATH="$(pwd)"
```

## Sanity Check

```bash
python -c "import click, typer; print('click', click.__version__); print('typer', typer.__version__)"
appworld --help
```

Expected:

- `click` should be `8.1.8`.
- `appworld --help` should run without a Typer/Click crash.

## Notes

- Do not install this environment with `pip install appworld`; use the local source checkout.
- `APPWORLD_PROJECT_PATH` should point to the `ace-appworld` repository root whenever you run AppWorld experiments.

# Set up baseline environment

## Set up ACE environment

```bash
cd ..
git clone https://github.com/ace-agent/ace.git
cd ace

# Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install ACE and core dependencies
uv sync

# Set up API keys
cp .env.example .env
# set the API key(s) and base url in .env as you need
```

If you would like to use keys other than the default provider api key provided by sambanova, you need to change the `provider` field of the corresponding jsonnet file. For example:
```json
local generator_model_config = {
    "name": "your-choice-of-LLM",
    "provider": "api-providers-name",
    "temperature": 0,
    "seed": 100,
    "stop": ["<|endoftext|>", "<|eot_id|>", "<|start_header_id|>"],
    "logprobs": false,
    "top_logprobs": null,
    "frequency_penalty": 0,
    "presence_penalty": 0,
    "n": 1,
    "response_format": {"type": "text"},
    "retry_after_n_seconds": 10,
    "use_cache": true,
    "max_retries": 50,
};
```

# Task loader and evaluator APIs 
Guidance on how to load task datasets and how to produce per-task evaluation output layout is written in [TASKLOADER_AND_EVALUATOR_AND_OUTPUT_README.md](TASKLOADER_AND_EVALUATOR_AND_OUTPUT_README.md)

# Experiment datasets

Dataset manifests are stored under `data/datasets/`. The task counts below are
computed from the non-empty task IDs in each manifest. Every scenario contains
three task variants.

| Dataset | Split | Manifest | Scenarios | Tasks |
| --- | --- | --- | ---: | ---: |
| Intermediate8h | Train | [`data/datasets/intermediate_8h_train.txt`](data/datasets/intermediate_8h_train.txt) | 10 | 30 |
| Intermediate8h | Test normal | [`data/datasets/intermediate_8h_test_normal.txt`](data/datasets/intermediate_8h_test_normal.txt) | 19 | 57 |
| Intermediate8h | Test challenge | [`data/datasets/intermediate_8h_test_challenge.txt`](data/datasets/intermediate_8h_test_challenge.txt) | 46 | 138 |
| **Intermediate8h total** |  |  | **75** | **225** |
| Quick2h | Train | [`data/datasets/quick2h_train.txt`](data/datasets/quick2h_train.txt) | 5 | 15 |
| Quick2h | Test normal | [`data/datasets/quick2h_test_normal.txt`](data/datasets/quick2h_test_normal.txt) | 5 | 15 |
| Quick2h | Test challenge | [`data/datasets/quick2h_test_challenge.txt`](data/datasets/quick2h_test_challenge.txt) | 5 | 15 |
| **Quick2h total** |  |  | **15** | **45** |
| Quick2h v2 | Train | [`data/datasets/quick2h_train_v2.txt`](data/datasets/quick2h_train_v2.txt) | 5 | 15 |
| Quick2h v2 | Test normal | [`data/datasets/quick2h_test_normal_v2.txt`](data/datasets/quick2h_test_normal_v2.txt) | 7 | 21 |
| Quick2h v2 | Test challenge | [`data/datasets/quick2h_test_challenge_v2.txt`](data/datasets/quick2h_test_challenge_v2.txt) | 6 | 18 |
| **Quick2h v2 total** |  |  | **18** | **54** |

# Completed ReMe formal runs and task traces

The `formal12-20261025-a` campaign completed all 12 ReMe runs and 702 ordered task attempts. Here, “completed” means the run and its official evaluation finished; individual benchmark tasks may still have failed. These outputs are **local to this workstation and are not in the GitHub repository**. The table uses complete absolute paths, not online links. The tracked [ReMe results report](experiments/intermediate_8h_reme_online_report.md) summarizes scores and costs.

| Dataset | Arm | Complete path on this workstation | Aggregate JSON | Example task ID |
| --- | --- | --- | --- | --- |
| `intermediate_8h_test_normal` | `fixed` | `/home/jiayao/Metaskill-library/baselines/ace/ace-appworld/experiments/outputs/reme_formal12-20261025-a_intermediate_8h_test_normal_fixed_r01_qwen3.8-flash_run_0` | `intermediate_8h_test_normal.json` | `fd1f8fa_1` |
| `intermediate_8h_test_normal` | `dynamic` | `/home/jiayao/Metaskill-library/baselines/ace/ace-appworld/experiments/outputs/reme_formal12-20261025-a_intermediate_8h_test_normal_dynamic_r01_qwen3.8-flash_run_0` | `intermediate_8h_test_normal.json` | `fd1f8fa_1` |
| `intermediate_8h_test_normal` | `cold_start` | `/home/jiayao/Metaskill-library/baselines/ace/ace-appworld/experiments/outputs/reme_formal12-20261025-a_intermediate_8h_test_normal_cold_start_r01_qwen3.8-flash_run_0` | `intermediate_8h_test_normal.json` | `fd1f8fa_1` |
| `intermediate_8h_test_challenge` | `fixed` | `/home/jiayao/Metaskill-library/baselines/ace/ace-appworld/experiments/outputs/reme_formal12-20261025-a_intermediate_8h_test_challenge_fixed_r01_qwen3.8-flash_run_0` | `intermediate_8h_test_challenge.json` | `b3bdcc1_1` |
| `intermediate_8h_test_challenge` | `dynamic` | `/home/jiayao/Metaskill-library/baselines/ace/ace-appworld/experiments/outputs/reme_formal12-20261025-a_intermediate_8h_test_challenge_dynamic_r01_qwen3.8-flash_run_0` | `intermediate_8h_test_challenge.json` | `b3bdcc1_1` |
| `intermediate_8h_test_challenge` | `cold_start` | `/home/jiayao/Metaskill-library/baselines/ace/ace-appworld/experiments/outputs/reme_formal12-20261025-a_intermediate_8h_test_challenge_cold_start_r01_qwen3.8-flash_run_0` | `intermediate_8h_test_challenge.json` | `b3bdcc1_1` |
| `quick2h_test_normal_v2` | `fixed` | `/home/jiayao/Metaskill-library/baselines/ace/ace-appworld/experiments/outputs/reme_formal12-20261025-a_quick2h_test_normal_v2_fixed_r01_qwen3.8-flash_run_0` | `quick2h_test_normal_v2.json` | `ff58e36_1` |
| `quick2h_test_normal_v2` | `dynamic` | `/home/jiayao/Metaskill-library/baselines/ace/ace-appworld/experiments/outputs/reme_formal12-20261025-a_quick2h_test_normal_v2_dynamic_r01_qwen3.8-flash_run_0` | `quick2h_test_normal_v2.json` | `ff58e36_1` |
| `quick2h_test_normal_v2` | `cold_start` | `/home/jiayao/Metaskill-library/baselines/ace/ace-appworld/experiments/outputs/reme_formal12-20261025-a_quick2h_test_normal_v2_cold_start_r01_qwen3.8-flash_run_0` | `quick2h_test_normal_v2.json` | `ff58e36_1` |
| `quick2h_test_challenge_v2` | `fixed` | `/home/jiayao/Metaskill-library/baselines/ace/ace-appworld/experiments/outputs/reme_formal12-20261025-a_quick2h_test_challenge_v2_fixed_r01_qwen3.8-flash_run_0` | `quick2h_test_challenge_v2.json` | `5238afc_1` |
| `quick2h_test_challenge_v2` | `dynamic` | `/home/jiayao/Metaskill-library/baselines/ace/ace-appworld/experiments/outputs/reme_formal12-20261025-a_quick2h_test_challenge_v2_dynamic_r01_qwen3.8-flash_run_0` | `quick2h_test_challenge_v2.json` | `5238afc_1` |
| `quick2h_test_challenge_v2` | `cold_start` | `/home/jiayao/Metaskill-library/baselines/ace/ace-appworld/experiments/outputs/reme_formal12-20261025-a_quick2h_test_challenge_v2_cold_start_r01_qwen3.8-flash_run_0` | `quick2h_test_challenge_v2.json` | `5238afc_1` |

To expose all 12 runs under `experiments/outputs/` in another checkout on this workstation, run from that checkout's `ace-appworld/` directory:

```bash
bash scripts/share_reme_runs.sh --dry-run
bash scripts/share_reme_runs.sh            # symbolic links; source must remain available
# or: bash scripts/share_reme_runs.sh --copy  # independent copies
```

The script refuses to overwrite existing destinations and accepts `--source-outputs DIR` and `--destination-outputs DIR` for other local layouts. It cannot fetch runs from GitHub: on another machine, transfer the source run directories first, then use `--source-outputs` and `--copy`. Neither linking nor copying pushes the ignored outputs to GitHub.

For any run root above, choose a task ID from `run_manifest.json` → `task_ids` (or browse `tasks/`), then open:

```text
<run-root>/tasks/<task-id>/logs/lm_calls.jsonl        # LLM/provider calls and responses
<run-root>/tasks/<task-id>/logs/environment_io.md      # executed code and environment output
<run-root>/tasks/<task-id>/logs/api_calls.jsonl        # normalized AppWorld API calls
<run-root>/tasks/<task-id>/evaluation/report.md        # official per-task assertions and score
<run-root>/baseline_artifacts/reme/<task-id>/memory_events.jsonl  # ReMe retrieval/summary/update events
<run-root>/evaluations/<dataset>.json                   # official whole-dataset result
<run-root>/evaluations/<dataset>.txt                    # readable whole-dataset result
```

For example, these are the complete local paths for task `ff58e36_1` in the quick2h-normal fixed run (the actual evaluation filename is `report.md`, not `reports.md`):

```text
/home/jiayao/Metaskill-library/baselines/ace/ace-appworld/experiments/outputs/reme_formal12-20261025-a_quick2h_test_normal_v2_fixed_r01_qwen3.8-flash_run_0/tasks/ff58e36_1/logs/lm_calls.jsonl
/home/jiayao/Metaskill-library/baselines/ace/ace-appworld/experiments/outputs/reme_formal12-20261025-a_quick2h_test_normal_v2_fixed_r01_qwen3.8-flash_run_0/tasks/ff58e36_1/logs/environment_io.md
/home/jiayao/Metaskill-library/baselines/ace/ace-appworld/experiments/outputs/reme_formal12-20261025-a_quick2h_test_normal_v2_fixed_r01_qwen3.8-flash_run_0/tasks/ff58e36_1/logs/api_calls.jsonl
/home/jiayao/Metaskill-library/baselines/ace/ace-appworld/experiments/outputs/reme_formal12-20261025-a_quick2h_test_normal_v2_fixed_r01_qwen3.8-flash_run_0/tasks/ff58e36_1/evaluation/report.md
/home/jiayao/Metaskill-library/baselines/ace/ace-appworld/experiments/outputs/reme_formal12-20261025-a_quick2h_test_normal_v2_fixed_r01_qwen3.8-flash_run_0/baseline_artifacts/reme/ff58e36_1/memory_events.jsonl
```

# Completed ACE run outputs and task traces

These 14 Qwen3.8-flash comparison runs are stored **on this workstation**, outside Git. GitHub cannot open their run files. The table uses complete local paths so another user on the same workstation can find them directly. “Completed” means an official aggregate evaluation exists; individual tasks may still have failed.

To make these runs appear under `experiments/outputs/` in another checkout on this workstation, run this from that checkout’s `ace-appworld/` directory:

```bash
bash scripts/share_ace_runs.sh
```

The script creates symbolic links by default, checks all 14 source directories before changing anything, and refuses to overwrite existing data. Use `bash scripts/share_ace_runs.sh --copy` for independent copies (about 1.9 GB), or `--source-outputs DIR` / `--destination-outputs DIR` to override either root. The source files must remain in place for symbolic links to work. The local `experiments/outputs/` directory is Git-ignored; running the script does not publish the runs.

| Campaign | Run | Complete path on this workstation | Aggregate JSON | Example task ID |
| --- | --- | --- | --- | --- |
| Intermediate8h | `offline_no_GT_adaptation` | `/home/jiayao/Metaskill-library/baselines/ace/ace-appworld/experiments/outputs/ACE_intermediate_8h/qwen3.8-flash/offline_no_GT_adaptation` | `intermediate_8h_train.json` | `22cc237_1` |
| Intermediate8h | `offline_no_GT_evaluation_test_normal` | `/home/jiayao/Metaskill-library/baselines/ace/ace-appworld/experiments/outputs/ACE_intermediate_8h/qwen3.8-flash/offline_no_GT_evaluation_test_normal` | `intermediate_8h_test_normal.json` | `024c982_1` |
| Intermediate8h | `offline_no_GT_evaluation_test_challenge` | `/home/jiayao/Metaskill-library/baselines/ace/ace-appworld/experiments/outputs/ACE_intermediate_8h/qwen3.8-flash/offline_no_GT_evaluation_test_challenge` | `intermediate_8h_test_challenge.json` | `18670a5_1` |
| Intermediate8h | `online_no_GT_test_normal` | `/home/jiayao/Metaskill-library/baselines/ace/ace-appworld/experiments/outputs/ACE_intermediate_8h/qwen3.8-flash/online_no_GT_test_normal` | `intermediate_8h_test_normal.json` | `024c982_1` |
| Intermediate8h | `online_no_GT_test_challenge` | `/home/jiayao/Metaskill-library/baselines/ace/ace-appworld/experiments/outputs/ACE_intermediate_8h/qwen3.8-flash/online_no_GT_test_challenge` | `intermediate_8h_test_challenge.json` | `18670a5_1` |
| Quick2h v1 | `offline_no_GT_adaptation` | `/home/jiayao/Metaskill-library/baselines/ace/ace-appworld/experiments/outputs/ACE_quick2h_offline_online/qwen3.8-flash/offline_no_GT_adaptation` | `quick2h_train.json` | `07b42fd_1` |
| Quick2h v1 | `offline_no_GT_evaluation_test_normal` | `/home/jiayao/Metaskill-library/baselines/ace/ace-appworld/experiments/outputs/ACE_quick2h_offline_online/qwen3.8-flash/offline_no_GT_evaluation_test_normal` | `quick2h_test_normal.json` | `3aa1a22_1` |
| Quick2h v1 | `offline_no_GT_evaluation_test_challenge` | `/home/jiayao/Metaskill-library/baselines/ace/ace-appworld/experiments/outputs/ACE_quick2h_offline_online/qwen3.8-flash/offline_no_GT_evaluation_test_challenge` | `quick2h_test_challenge.json` | `476b213_1` |
| Quick2h v1 | `online_no_GT_test_normal` | `/home/jiayao/Metaskill-library/baselines/ace/ace-appworld/experiments/outputs/ACE_quick2h_offline_online/qwen3.8-flash/online_no_GT_test_normal` | `quick2h_test_normal.json` | `3aa1a22_1` |
| Quick2h v1 | `online_no_GT_test_challenge` | `/home/jiayao/Metaskill-library/baselines/ace/ace-appworld/experiments/outputs/ACE_quick2h_offline_online/qwen3.8-flash/online_no_GT_test_challenge` | `quick2h_test_challenge.json` | `476b213_1` |
| Quick2h v2 | `offline_no_GT_evaluation_test_normal_v2` | `/home/jiayao/Metaskill-library/baselines/ace/ace-appworld/experiments/outputs/ACE_quick2h_v1train_v2test_20261026_retry1/qwen3.8-flash/offline_no_GT_evaluation_test_normal_v2` | `quick2h_test_normal_v2.json` | `0a9d82a_1` |
| Quick2h v2 | `offline_no_GT_evaluation_test_challenge_v2` | `/home/jiayao/Metaskill-library/baselines/ace/ace-appworld/experiments/outputs/ACE_quick2h_v1train_v2test_20261026_retry1/qwen3.8-flash/offline_no_GT_evaluation_test_challenge_v2` | `quick2h_test_challenge_v2.json` | `476b213_1` |
| Quick2h v2 | `online_no_GT_test_normal_v2` | `/home/jiayao/Metaskill-library/baselines/ace/ace-appworld/experiments/outputs/ACE_quick2h_v1train_v2test_20261026_retry1/qwen3.8-flash/online_no_GT_test_normal_v2` | `quick2h_test_normal_v2.json` | `0a9d82a_1` |
| Quick2h v2 | `online_no_GT_test_challenge_v2` | `/home/jiayao/Metaskill-library/baselines/ace/ace-appworld/experiments/outputs/ACE_quick2h_v1train_v2test_20261026_retry1/qwen3.8-flash/online_no_GT_test_challenge_v2` | `quick2h_test_challenge_v2.json` | `476b213_1` |

For any row, append `/evaluations/<Aggregate JSON>` to its complete run path for the official whole-run result. To inspect a task, append `/tasks/<task-id>/` and open the four files below. `evaluation/report.md` is the actual singular filename.

```text
<complete-run-path>/tasks/<task-id>/logs/lm_calls.jsonl
<complete-run-path>/tasks/<task-id>/logs/environment_io.md
<complete-run-path>/tasks/<task-id>/logs/api_calls.jsonl
<complete-run-path>/tasks/<task-id>/evaluation/report.md
```

For example, the complete paths for one Quick2h v2 online-normal task are:

```text
/home/jiayao/Metaskill-library/baselines/ace/ace-appworld/experiments/outputs/ACE_quick2h_v1train_v2test_20261026_retry1/qwen3.8-flash/online_no_GT_test_normal_v2/tasks/0a9d82a_1/logs/lm_calls.jsonl
/home/jiayao/Metaskill-library/baselines/ace/ace-appworld/experiments/outputs/ACE_quick2h_v1train_v2test_20261026_retry1/qwen3.8-flash/online_no_GT_test_normal_v2/tasks/0a9d82a_1/logs/environment_io.md
/home/jiayao/Metaskill-library/baselines/ace/ace-appworld/experiments/outputs/ACE_quick2h_v1train_v2test_20261026_retry1/qwen3.8-flash/online_no_GT_test_normal_v2/tasks/0a9d82a_1/logs/api_calls.jsonl
/home/jiayao/Metaskill-library/baselines/ace/ace-appworld/experiments/outputs/ACE_quick2h_v1train_v2test_20261026_retry1/qwen3.8-flash/online_no_GT_test_normal_v2/tasks/0a9d82a_1/evaluation/report.md
```

The Quick2h v2 **config** directory was renamed to `experiments/configs/ACE_quick2h_v2_offline_online/`; its completed **output** directory retains `ACE_quick2h_v1train_v2test_20261026_retry1`.

Other historical full-split ACE outputs on this workstation are:

```text
/home/jiayao/Metaskill-library/baselines/ace/ace-appworld/experiments/outputs/ACE_offline_no_GT_adaptation
/home/jiayao/Metaskill-library/baselines/ace/ace-appworld/experiments/outputs/ACE_offline_no_GT_evaluation
/home/jiayao/Metaskill-library/baselines/ace/ace-appworld/experiments/outputs/ACE_online_no_GT
```

The historical offline adaptation has per-task reports but no aggregate JSON. Exploratory pilot outputs are under `/home/jiayao/Metaskill-library/baselines/ace/ace-appworld/experiments/outputs/ACE_18_task_online_no_GT_pilot`; check each pilot subrun individually. For the output schema, see [the task loader and evaluator guide](TASKLOADER_AND_EVALUATOR_AND_OUTPUT_README.md). For scores and costs, see the [Intermediate8h ACE report](experiments/intermediate_8h_ace_offline_online_report.md) and [Quick2h ACE report](experiments/quick2h_ace_offline_online_report.md).
