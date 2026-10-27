# Install a clean AppWorld environment for all baselines

This guide sets up a clean ACE AppWorld environment from source.

## Reproduce the ACE intermediate8h and quick2h v2 comparisons

Clone this experiment repository, then use its [single reproduction script](scripts/reproduce_ace_appworld.sh). The script prepares an isolated workspace and executes the three ACE arms: offline adaptation, frozen-playbook evaluation, and online adaptation. Each comparison has one offline training run, two frozen tests sharing its new playbook, and two independent online streams: **10 sequential `appworld run` and `appworld evaluate` pairs** in total. `plan` prints the commands without calling the model.

```bash
git clone https://github.com/jgu13/metaskill-appworld.git ace-appworld
cd ace-appworld
bash scripts/reproduce_ace_appworld.sh plan
bash scripts/reproduce_ace_appworld.sh setup
read -r -s -p 'Qwen endpoint API key: ' OPENAI_API_KEY; echo; export OPENAI_API_KEY
bash scripts/reproduce_ace_appworld.sh run
```

Use a revision containing `scripts/reproduce_ace_appworld.sh`; the pinned historical runner commit predates this guide. `bash scripts/reproduce_ace_appworld.sh all` combines setup and run once the key is available. Full runs make real provider calls. The key must work with the OpenAI-compatible Qwen3.8-flash endpoint specified in the configs; changing the endpoint or model changes the experiment conditions.

**Pinned versions and environments.** The script clones [upstream ACE](https://github.com/ace-agent/ace.git) at [commit `82709de050e1db6e6ef2f07bcb0393560b94992a`](https://github.com/ace-agent/ace/commit/82709de050e1db6e6ef2f07bcb0393560b94992a) for its standalone environment. [Upstream ACE has no GitHub release](https://github.com/ace-agent/ace/releases). The actual AppWorld ACE integration runs from this fork at pinned commit `634d67c3bf54a2fb1fa55f4b1200a3ea91b162ce`; the script clones that commit into a separate workspace, leaving the checkout containing this README untouched. Install Git, Git LFS, Python 3.11, and [`uv`](https://docs.astral.sh/uv/getting-started/installation/) first. `setup` creates `.repro-ace-appworld/ace-reference/.venv` with `uv sync --frozen` (uv can obtain Python 3.12) and `.repro-ace-appworld/ace-appworld/.venv` with AppWorld installed from source, then downloads AppWorld data. Set `ACE_REPRO_WORKSPACE=/absolute/path/to/workspace` to change the destination.

| Comparison | Offline adaptation | Frozen evaluation | Online adaptation |
| --- | --- | --- | --- |
| Intermediate8h | `intermediate_8h_train` (30 tasks) | `intermediate_8h_test_normal` (57), `intermediate_8h_test_challenge` (138) | The same test manifests, each with an independent playbook |
| Quick2h v2 tests | **`quick2h_train` v1** (15 tasks) | `quick2h_test_normal_v2` (21), `quick2h_test_challenge_v2` (18) | The same v2 test manifests, each with an independent playbook |

The historical quick2h v2 comparison used an offline playbook trained on **v1** `quick2h_train`. Training on `quick2h_train_v2` would test a different protocol. The checked-in configs are in [`ACE_intermediate_8h`](experiments/configs/ACE_intermediate_8h/qwen3.8-flash/), [`ACE_quick2h_v2_offline_online`](experiments/configs/ACE_quick2h_v2_offline_online/qwen3.8-flash/), and the v1 training config in [`ACE_quick2h_offline_online`](experiments/configs/ACE_quick2h_offline_online/qwen3.8-flash/). They specify the model alias, endpoint, seeds, prompts, 40-step limit, and no-ground-truth adaptation.

New outputs appear under `.repro-ace-appworld/ace-appworld/experiments/outputs/`; the script refuses existing run directories and clears checked-in result playbooks only inside its isolated clone before training. Each task has `logs/lm_calls.jsonl`, `logs/environment_io.md`, `logs/api_calls.jsonl`, and `evaluation/report.md`; each run has `evaluations/<dataset>.json`. Compare TGC/SGC with the [intermediate8h](experiments/intermediate_8h_ace_offline_online_report.md) and [quick2h v2](experiments/quick2h_ace_offline_online_report.md) reports. The original quick2h v2 output used a retry name; new outputs use `ACE_quick2h_v2_offline_online`. Historical run outputs remain Git-ignored, and live model responses may change the reproduced scores.

## Reproduce the ReMe AppWorld results

Clone this [AppWorld fork](https://github.com/jiayaogu/metaskill-appworld), then use its [single reproduction script](scripts/reproduce_reme_formal12.sh). It prepares a separate workspace and runs the **12 formal ReMe cells**: fixed, dynamic, and cold start on Intermediate8h test normal/challenge and Quick2h **v2** test normal/challenge (702 ordered primary task attempts). This is the protocol reported in the [ReMe results report](experiments/intermediate_8h_reme_online_report.md). The experiment outputs are intentionally absent from Git; the script creates new local outputs.

The [bundled ReMe source](baselines/reme2f37a15/) is the frozen code used by the formal campaign. It is based on upstream **`2f37a159b72a04ac1885a7db7f1a663a833e7791`** (ReMe v3/0.3.1.10 code line) with the audited AppWorld driver and approved `qwen3.8-flash` and sequential-execution changes. The archived [source patch](baselines/reme2f37a15/formal12-source.patch) records the changes from upstream; the script copies the ready-to-run source directly and does not apply the patch. It checks all 250 frozen ReMe source files against the campaign's [source hashes](baselines/reme2f37a15/source-sha256.json). It also clones this AppWorld fork at `634d67c3bf54a2fb1fa55f4b1200a3ea91b162ce`, which contains the four subset manifests and the shared call logger. That separate checkout keeps outputs out of the source tree.

**Prerequisites:** Linux, Git and Git LFS, Python 3.11 with `venv`, Docker Compose, `curl`, network access to install packages and download AppWorld data, and API access to `qwen3.8-flash` and 1024-dimensional `text-embedding-v4`. The script creates two virtual environments: `.repro-reme/ace-appworld/.venv` for the AppWorld runner and `.repro-reme/ReMe-2f37a15/.venv` for the isolated ReMe service. Its default Elasticsearch container listens only on `127.0.0.1:19200` and keeps a persistent Docker volume.

Create a provider file with your real credentials and compatible OpenAI-style base URLs; keep it outside Git. The chat endpoint must serve `qwen3.8-flash`, and the embedding endpoint must serve `text-embedding-v4`. For example, save this as `.repro-reme/provider.env` and replace the placeholders:

```dotenv
OPENAI_API_KEY=your-chat-api-key
OPENAI_BASE_URL=https://your-chat-provider.example/v1
DASHSCOPE_API_KEY=your-embedding-api-key
DASHSCOPE_BASE_URL=https://your-embedding-provider.example/compatible-mode/v1
```

Clone this repository and run **one script** from its root after creating the provider file:

```bash
git clone https://github.com/jiayaogu/metaskill-appworld.git ace-appworld
cd ace-appworld
# Save the provider.env values above in .repro-reme/provider.env first.
bash scripts/reproduce_reme_formal12.sh all "$PWD/.repro-reme/provider.env"
```

`all` installs the two environments and AppWorld data, starts Elasticsearch, plans the matrix, and executes the runs with real, billable API calls. Use `setup` to prepare only, then `run /absolute/path/to/provider.env` to execute later. Setup checks the frozen hashes and runs 97 provider-free ReMe tests; two historical tests requiring the original ReMe Git history are excluded from this vendored-source setup. Set `REME_CAMPAIGN=<same-name>` to resume a started campaign; without it, each invocation creates a fresh campaign name. `REME_ES_URL` selects an existing Elasticsearch service instead of starting Docker. The script generates an uncapped formal accounting policy with the original experiment's historical USD-per-million-token rates; set the `REME_*_RATE` variables listed in `--help` to price a different provider. These rates affect **estimated cost**, not benchmark scoring.

The ReMe experiment settings live in [`baselines/reme2f37a15/benchmark/appworld/execution_matrix.py`](baselines/reme2f37a15/benchmark/appworld/execution_matrix.py) and [`baselines/reme2f37a15/reme/config/service.yaml`](baselines/reme2f37a15/reme/config/service.yaml); the bundled starting memory is `baselines/reme2f37a15/docs/library/paper_data/task/appworld_qwen3_8b.jsonl`. The four ordered task lists are in `.repro-reme/ace-appworld/data/datasets/{intermediate_8h_test_normal,intermediate_8h_test_challenge,quick2h_test_normal_v2,quick2h_test_challenge_v2}.txt`. The `experiments/configs/ACE_*/` JSONnet files configure **ACE**, not these ReMe runs. The [dependency constraints](baselines/reme2f37a15/constraints.txt), [Elasticsearch setup](baselines/reme2f37a15/compose.yaml), and [index template](baselines/reme2f37a15/index-template.json) are tracked with the source.

Results are saved under `.repro-reme/ace-appworld/experiments/outputs/reme_<campaign>_<dataset>_<arm>_r01_qwen3.8-flash_run_0/`. Each completed run has `evaluations/<dataset>.json`, `run_manifest.json`, task logs under `tasks/<task-id>/logs/`, memory events under `baseline_artifacts/reme/<task-id>/memory_events.jsonl`, and `cost_evidence.json`. The campaign summary is under `experiments/outputs/.reme-formal-campaigns/<campaign>/coordinator_summary.json`. Live model responses can vary, so scores need not be byte-for-byte identical to the historical report.

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

The `formal12-20261025-a` campaign completed all 12 ReMe runs and 702 ordered task attempts. Here, “completed” means the run and its official evaluation finished; individual benchmark tasks may still have failed. These outputs are **local to this workstation (70.28.108.234) and are not in the GitHub repository**. The table uses complete absolute paths, not online links. The tracked [ReMe results report](experiments/intermediate_8h_reme_online_report.md) summarizes scores and costs. A comprehensive failure case analysis can be found at [ReMe Failure case analysis](experiments/Intermediate_8h_reme_online_failure_case_analysis.md).

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

These 14 Qwen3.8-flash comparison runs are stored **on this workstation (70.28.108.234)**, outside Git. GitHub cannot open their run files. The table uses complete local paths so another user on the same workstation can find them directly. “Completed” means an official aggregate evaluation exists; individual tasks may still have failed.

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
