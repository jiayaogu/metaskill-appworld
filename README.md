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

## Completed ReMe formal runs and task traces

The `formal12-20261025-a` campaign completed all 12 ReMe runs and 702 ordered task attempts. Here, “completed” means the run and its official evaluation finished; individual benchmark tasks may still have failed. The run directories below are relative to this `ace-appworld/` directory. Each link opens that run's `run_manifest.json`; its parent directory is the run root. The [ReMe results report](experiments/intermediate_8h_reme_online_report.md) summarizes scores and costs.

| Dataset (tasks per arm) | Fixed run | Dynamic run | Cold-start run |
|---|---|---|---|
| `intermediate_8h_test_normal` (57) | [fixed](experiments/outputs/reme_formal12-20261025-a_intermediate_8h_test_normal_fixed_r01_qwen3.8-flash_run_0/run_manifest.json) | [dynamic](experiments/outputs/reme_formal12-20261025-a_intermediate_8h_test_normal_dynamic_r01_qwen3.8-flash_run_0/run_manifest.json) | [cold_start](experiments/outputs/reme_formal12-20261025-a_intermediate_8h_test_normal_cold_start_r01_qwen3.8-flash_run_0/run_manifest.json) |
| `intermediate_8h_test_challenge` (138) | [fixed](experiments/outputs/reme_formal12-20261025-a_intermediate_8h_test_challenge_fixed_r01_qwen3.8-flash_run_0/run_manifest.json) | [dynamic](experiments/outputs/reme_formal12-20261025-a_intermediate_8h_test_challenge_dynamic_r01_qwen3.8-flash_run_0/run_manifest.json) | [cold_start](experiments/outputs/reme_formal12-20261025-a_intermediate_8h_test_challenge_cold_start_r01_qwen3.8-flash_run_0/run_manifest.json) |
| `quick2h_test_normal_v2` (21) | [fixed](experiments/outputs/reme_formal12-20261025-a_quick2h_test_normal_v2_fixed_r01_qwen3.8-flash_run_0/run_manifest.json) | [dynamic](experiments/outputs/reme_formal12-20261025-a_quick2h_test_normal_v2_dynamic_r01_qwen3.8-flash_run_0/run_manifest.json) | [cold_start](experiments/outputs/reme_formal12-20261025-a_quick2h_test_normal_v2_cold_start_r01_qwen3.8-flash_run_0/run_manifest.json) |
| `quick2h_test_challenge_v2` (18) | [fixed](experiments/outputs/reme_formal12-20261025-a_quick2h_test_challenge_v2_fixed_r01_qwen3.8-flash_run_0/run_manifest.json) | [dynamic](experiments/outputs/reme_formal12-20261025-a_quick2h_test_challenge_v2_dynamic_r01_qwen3.8-flash_run_0/run_manifest.json) | [cold_start](experiments/outputs/reme_formal12-20261025-a_quick2h_test_challenge_v2_cold_start_r01_qwen3.8-flash_run_0/run_manifest.json) |

For any run root in the table, choose a task ID from `run_manifest.json` → `task_ids` (or browse `tasks/`), then open:

```text
<run-root>/tasks/<task-id>/logs/lm_calls.jsonl        # LLM/provider calls and responses
<run-root>/tasks/<task-id>/logs/environment_io.md      # executed code and environment output
<run-root>/tasks/<task-id>/logs/api_calls.jsonl        # normalized AppWorld API calls
<run-root>/tasks/<task-id>/evaluation/report.md        # official per-task assertions and score
<run-root>/baseline_artifacts/reme/<task-id>/memory_events.jsonl  # ReMe retrieval/summary/update events
<run-root>/evaluations/<dataset>.json                   # official whole-dataset result
<run-root>/evaluations/<dataset>.txt                    # readable whole-dataset result
```

For example, task `ff58e36_1` in the quick2h-normal fixed run has [LLM calls](experiments/outputs/reme_formal12-20261025-a_quick2h_test_normal_v2_fixed_r01_qwen3.8-flash_run_0/tasks/ff58e36_1/logs/lm_calls.jsonl), [environment I/O](experiments/outputs/reme_formal12-20261025-a_quick2h_test_normal_v2_fixed_r01_qwen3.8-flash_run_0/tasks/ff58e36_1/logs/environment_io.md), [API calls](experiments/outputs/reme_formal12-20261025-a_quick2h_test_normal_v2_fixed_r01_qwen3.8-flash_run_0/tasks/ff58e36_1/logs/api_calls.jsonl), an [evaluation report](experiments/outputs/reme_formal12-20261025-a_quick2h_test_normal_v2_fixed_r01_qwen3.8-flash_run_0/tasks/ff58e36_1/evaluation/report.md), and [ReMe memory events](experiments/outputs/reme_formal12-20261025-a_quick2h_test_normal_v2_fixed_r01_qwen3.8-flash_run_0/baseline_artifacts/reme/ff58e36_1/memory_events.jsonl). The actual evaluation filename is `report.md`, not `reports.md`.

## Completed ACE run outputs and task traces

The 14 Qwen3.8-flash comparison runs below completed with official aggregate evaluations. Each example task links to a real task directory containing all four trace files. A task may have failed its goal while its run still completed; inspect its report for the task outcome. Paths are relative to this README.

| Campaign | Run output | Official aggregate | Example task trace |
| --- | --- | --- | --- |
| Intermediate8h | [offline_no_GT_adaptation](experiments/outputs/ACE_intermediate_8h/qwen3.8-flash/offline_no_GT_adaptation/) | [JSON](experiments/outputs/ACE_intermediate_8h/qwen3.8-flash/offline_no_GT_adaptation/evaluations/intermediate_8h_train.json) | [22cc237_1](experiments/outputs/ACE_intermediate_8h/qwen3.8-flash/offline_no_GT_adaptation/tasks/22cc237_1/) |
| Intermediate8h | [offline_no_GT_evaluation_test_normal](experiments/outputs/ACE_intermediate_8h/qwen3.8-flash/offline_no_GT_evaluation_test_normal/) | [JSON](experiments/outputs/ACE_intermediate_8h/qwen3.8-flash/offline_no_GT_evaluation_test_normal/evaluations/intermediate_8h_test_normal.json) | [024c982_1](experiments/outputs/ACE_intermediate_8h/qwen3.8-flash/offline_no_GT_evaluation_test_normal/tasks/024c982_1/) |
| Intermediate8h | [offline_no_GT_evaluation_test_challenge](experiments/outputs/ACE_intermediate_8h/qwen3.8-flash/offline_no_GT_evaluation_test_challenge/) | [JSON](experiments/outputs/ACE_intermediate_8h/qwen3.8-flash/offline_no_GT_evaluation_test_challenge/evaluations/intermediate_8h_test_challenge.json) | [18670a5_1](experiments/outputs/ACE_intermediate_8h/qwen3.8-flash/offline_no_GT_evaluation_test_challenge/tasks/18670a5_1/) |
| Intermediate8h | [online_no_GT_test_normal](experiments/outputs/ACE_intermediate_8h/qwen3.8-flash/online_no_GT_test_normal/) | [JSON](experiments/outputs/ACE_intermediate_8h/qwen3.8-flash/online_no_GT_test_normal/evaluations/intermediate_8h_test_normal.json) | [024c982_1](experiments/outputs/ACE_intermediate_8h/qwen3.8-flash/online_no_GT_test_normal/tasks/024c982_1/) |
| Intermediate8h | [online_no_GT_test_challenge](experiments/outputs/ACE_intermediate_8h/qwen3.8-flash/online_no_GT_test_challenge/) | [JSON](experiments/outputs/ACE_intermediate_8h/qwen3.8-flash/online_no_GT_test_challenge/evaluations/intermediate_8h_test_challenge.json) | [18670a5_1](experiments/outputs/ACE_intermediate_8h/qwen3.8-flash/online_no_GT_test_challenge/tasks/18670a5_1/) |
| Quick2h v1 | [offline_no_GT_adaptation](experiments/outputs/ACE_quick2h_offline_online/qwen3.8-flash/offline_no_GT_adaptation/) | [JSON](experiments/outputs/ACE_quick2h_offline_online/qwen3.8-flash/offline_no_GT_adaptation/evaluations/quick2h_train.json) | [07b42fd_1](experiments/outputs/ACE_quick2h_offline_online/qwen3.8-flash/offline_no_GT_adaptation/tasks/07b42fd_1/) |
| Quick2h v1 | [offline_no_GT_evaluation_test_normal](experiments/outputs/ACE_quick2h_offline_online/qwen3.8-flash/offline_no_GT_evaluation_test_normal/) | [JSON](experiments/outputs/ACE_quick2h_offline_online/qwen3.8-flash/offline_no_GT_evaluation_test_normal/evaluations/quick2h_test_normal.json) | [3aa1a22_1](experiments/outputs/ACE_quick2h_offline_online/qwen3.8-flash/offline_no_GT_evaluation_test_normal/tasks/3aa1a22_1/) |
| Quick2h v1 | [offline_no_GT_evaluation_test_challenge](experiments/outputs/ACE_quick2h_offline_online/qwen3.8-flash/offline_no_GT_evaluation_test_challenge/) | [JSON](experiments/outputs/ACE_quick2h_offline_online/qwen3.8-flash/offline_no_GT_evaluation_test_challenge/evaluations/quick2h_test_challenge.json) | [476b213_1](experiments/outputs/ACE_quick2h_offline_online/qwen3.8-flash/offline_no_GT_evaluation_test_challenge/tasks/476b213_1/) |
| Quick2h v1 | [online_no_GT_test_normal](experiments/outputs/ACE_quick2h_offline_online/qwen3.8-flash/online_no_GT_test_normal/) | [JSON](experiments/outputs/ACE_quick2h_offline_online/qwen3.8-flash/online_no_GT_test_normal/evaluations/quick2h_test_normal.json) | [3aa1a22_1](experiments/outputs/ACE_quick2h_offline_online/qwen3.8-flash/online_no_GT_test_normal/tasks/3aa1a22_1/) |
| Quick2h v1 | [online_no_GT_test_challenge](experiments/outputs/ACE_quick2h_offline_online/qwen3.8-flash/online_no_GT_test_challenge/) | [JSON](experiments/outputs/ACE_quick2h_offline_online/qwen3.8-flash/online_no_GT_test_challenge/evaluations/quick2h_test_challenge.json) | [476b213_1](experiments/outputs/ACE_quick2h_offline_online/qwen3.8-flash/online_no_GT_test_challenge/tasks/476b213_1/) |
| Quick2h v2 | [offline_no_GT_evaluation_test_normal_v2](experiments/outputs/ACE_quick2h_v1train_v2test_20261026_retry1/qwen3.8-flash/offline_no_GT_evaluation_test_normal_v2/) | [JSON](experiments/outputs/ACE_quick2h_v1train_v2test_20261026_retry1/qwen3.8-flash/offline_no_GT_evaluation_test_normal_v2/evaluations/quick2h_test_normal_v2.json) | [0a9d82a_1](experiments/outputs/ACE_quick2h_v1train_v2test_20261026_retry1/qwen3.8-flash/offline_no_GT_evaluation_test_normal_v2/tasks/0a9d82a_1/) |
| Quick2h v2 | [offline_no_GT_evaluation_test_challenge_v2](experiments/outputs/ACE_quick2h_v1train_v2test_20261026_retry1/qwen3.8-flash/offline_no_GT_evaluation_test_challenge_v2/) | [JSON](experiments/outputs/ACE_quick2h_v1train_v2test_20261026_retry1/qwen3.8-flash/offline_no_GT_evaluation_test_challenge_v2/evaluations/quick2h_test_challenge_v2.json) | [476b213_1](experiments/outputs/ACE_quick2h_v1train_v2test_20261026_retry1/qwen3.8-flash/offline_no_GT_evaluation_test_challenge_v2/tasks/476b213_1/) |
| Quick2h v2 | [online_no_GT_test_normal_v2](experiments/outputs/ACE_quick2h_v1train_v2test_20261026_retry1/qwen3.8-flash/online_no_GT_test_normal_v2/) | [JSON](experiments/outputs/ACE_quick2h_v1train_v2test_20261026_retry1/qwen3.8-flash/online_no_GT_test_normal_v2/evaluations/quick2h_test_normal_v2.json) | [0a9d82a_1](experiments/outputs/ACE_quick2h_v1train_v2test_20261026_retry1/qwen3.8-flash/online_no_GT_test_normal_v2/tasks/0a9d82a_1/) |
| Quick2h v2 | [online_no_GT_test_challenge_v2](experiments/outputs/ACE_quick2h_v1train_v2test_20261026_retry1/qwen3.8-flash/online_no_GT_test_challenge_v2/) | [JSON](experiments/outputs/ACE_quick2h_v1train_v2test_20261026_retry1/qwen3.8-flash/online_no_GT_test_challenge_v2/evaluations/quick2h_test_challenge_v2.json) | [476b213_1](experiments/outputs/ACE_quick2h_v1train_v2test_20261026_retry1/qwen3.8-flash/online_no_GT_test_challenge_v2/tasks/476b213_1/) |

For any task, replace `<run>` and `<task_id>` in these paths with a run and task ID from the table or its `tasks/` directory:

```text
<run>/tasks/<task_id>/logs/lm_calls.jsonl
<run>/tasks/<task_id>/logs/environment_io.md
<run>/tasks/<task_id>/logs/api_calls.jsonl
<run>/tasks/<task_id>/evaluation/report.md
```

For a concrete Quick2h v2 online-normal task, open [LLM calls](experiments/outputs/ACE_quick2h_v1train_v2test_20261026_retry1/qwen3.8-flash/online_no_GT_test_normal_v2/tasks/0a9d82a_1/logs/lm_calls.jsonl), [environment I/O](experiments/outputs/ACE_quick2h_v1train_v2test_20261026_retry1/qwen3.8-flash/online_no_GT_test_normal_v2/tasks/0a9d82a_1/logs/environment_io.md), [API calls](experiments/outputs/ACE_quick2h_v1train_v2test_20261026_retry1/qwen3.8-flash/online_no_GT_test_normal_v2/tasks/0a9d82a_1/logs/api_calls.jsonl), or the [per-task evaluation report](experiments/outputs/ACE_quick2h_v1train_v2test_20261026_retry1/qwen3.8-flash/online_no_GT_test_normal_v2/tasks/0a9d82a_1/evaluation/report.md). The report filename is `report.md` (singular). See [the output layout guide](TASKLOADER_AND_EVALUATOR_AND_OUTPUT_README.md) for the full schema.

The earlier full-split ACE outputs are [offline adaptation](experiments/outputs/ACE_offline_no_GT_adaptation/), [offline evaluation](experiments/outputs/ACE_offline_no_GT_evaluation/), and [online evaluation](experiments/outputs/ACE_online_no_GT/). The adaptation output has 90 per-task reports but no aggregate evaluation JSON; the latter two have official aggregates. Exploratory pilot outputs are under [ACE_18_task_online_no_GT_pilot](experiments/outputs/ACE_18_task_online_no_GT_pilot/) and should be checked per subrun. Interrupted and smoke artifacts are documented in the archive manifests under `experiments/outputs/archived_incomplete_test_runs_*`.

Detailed comparison results: [Intermediate8h ACE report](experiments/intermediate_8h_ace_offline_online_report.md) and [Quick2h ACE report](experiments/quick2h_ace_offline_online_report.md).
