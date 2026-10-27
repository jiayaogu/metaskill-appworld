# AppWorld
Experiment Quick Start Guide

This guide helps you quickly set up and run AppWorld experiments with ReMe integration.

## Env Setup

### 1. Clone the Repository

```bash
git clone https://github.com/agentscope-ai/ReMe.git
cd ReMe/benchmark/appworld
```

### 2. Appworld Environment Setup

Create a new conda environment with Python 3.12:

```bash
conda create -p ./appworld-env python==3.12
conda activate ./appworld-env
```

Install required Python packages:

```bash
pip install -r requirements.txt
```

Install AppWorld and download the dataset:

```bash
pip install appworld
appworld install
appworld download data
```

**Note**: The AppWorld data will be saved in the current directory.

### 3. Start ReMe Service

Install ReMe (if not already installed)
If you haven't installed the ReMe environment yet, follow these steps:
```bash
# Go back to the project root
cd ../..

# Create ReMe environment
conda create -p ./reme-env python==3.12
conda activate ./reme-env

# Install ReMe
pip install .
```

Launch the ReMe service to enable memory library functionality:

```bash
reme2 \
  backend=http \
  http.port=8002 \
  llms.default.model_name=qwen3.8-flash \
  embedding_models.default.model_name=text-embedding-v4 \
  vector_stores.default.backend=es \
  vector_stores.default.collection_name=appworld \
  vector_stores.default.hosts=http://xx.yy.zz.mm:nn
```

### 4. Common Issues

**AppWorld data not found**: Ensure `appworld download data` completed successfully

**pydantic version issue**:  AppWorld depends on an older version of pydantic, which is why a separate environment is needed. If you encounter issues running the experiments, try `pip install appworld` to override the dependencies.



## Run Experiments

### Audited three-arm reproduction (2026-10-24)

The source-pinned reproduction now uses `execution_matrix.py`. `run_appworld.py`
delegates to that CLI; the old implicit fixed-only launch is retired. From this
worktree's root, generate all 12 **planned**, unscored run manifests without
contacting providers:

```bash
python benchmark/appworld/execution_matrix.py --campaign my-campaign --appworld-root /absolute/path/to/ace-appworld
```

The four registered subsets, arm switches, one run per arm/dataset, pool checksum,
output identities and task order are defined in `execution_matrix.py`. The matrix
contains 702 primary task attempts; run names retain `r01` and `num_trials=1`.
Existing campaign directories are rejected. Execution additionally requires `--execute`,
`--service-python /path/to/pinned-service-python` and `--es-url <Elasticsearch URL>`.
Use `--smoke` for one task per arm, with `--task-timeout 300` if a five-minute
per-task watchdog is desired. Smoke evaluates only that task using official
`on_only` output; it is not a complete dataset result. The watchdog is not a dollar
budget cap. Live smoke requires `--smoke-budget /absolute/path/to/policy.json`.
`execution_budget.py` enforces this opt-in policy at every physical provider
attempt, sharing an append-only, file-locked reservation ledger across the actor
and service processes. Keep the same policy/ledger across diagnostic retries.
Unknown endpoints/models are rejected; failed, interrupted or usage-less calls
retain their full reservations. Configure verified per-million-token rates and
conservative per-request bounds before execution. The policy's limit must be
below USD 100; account for earlier diagnostic calls with `prior_allowance_usd`.
These are published-rate cost estimates, not independently verified invoices.

Select the intended provider file with `--env-file /absolute/path/to/.env`, or
export the provider settings into the runner environment first. The explicit file
replaces inherited provider settings and loads only the recognized provider keys.
The isolated service uses `OPENAI_API_KEY` / `OPENAI_BASE_URL` for chat, and
`DASHSCOPE_API_KEY` for embeddings when present. `DASHSCOPE_BASE_URL` defaults to
`https://dashscope.aliyuncs.com/compatible-mode/v1`. Explicit `LLM_*` /
`EMBEDDING_*` role settings take precedence; without DashScope settings the
embedding client retains the OpenAI fallback. It does not auto-load unrelated
parent-directory dotenv files. The local reproduction's preferred file is
`../ReMe/benchmark/AppWorld/.env`; never copy its secret values into artifacts.
For Elasticsearch 9.2+, new run indexes must preserve source vectors (for example,
an index template for `reme_*` with `index.mapping.exclude_source_vectors=false`),
because the pinned adapter and audit snapshots read vectors from `_source`.
Local single-node replicas may remain unassigned; primary shards must be active.

Each run starts and closes its own local `reme2` process and randomly named ES
collection. Collections are retained for audit; no unrelated collection is cleared.
Fixed/dynamic verify a fresh 207-record import, and cold start verifies emptiness.
Every task must finish memory acknowledgements and evidence validation before the
next Ray actor starts. Errors mark the run incomplete and stop the campaign.
Official scores, snapshots, memory ledgers, provider logs and legacy trajectory
records live under the run's canonical AppWorld output directory. With a smoke
budget, cost evidence joins canonical physical IDs to settled usage reservations;
missing usage prevents acceptance. Without a pricing policy, dollar rates remain
explicitly unavailable rather than being assumed zero. The transport audit
decodes compressed response copies while forwarding original bytes unchanged.

Provider-free checks from the worktree root:

```bash
python -m unittest discover -s benchmark/appworld -p 'test_execution*.py' -v
```

On 2026-10-24, campaign `smoke-sg-20261024-d` passed the three-arm runtime and
minimum-task-layout checks with 33 focused tests. Fixed passed all six official
task checks; dynamic/cold start each passed five and correctly skipped insertion.
Thus this is readiness evidence, not full-dataset scoring, live successful-addition
coverage or full unified-shell migration acceptance. Local evidence is under
`.local-elasticsearch/checks/smoke-sg-20261024-d/acceptance.json`; earlier failed
diagnostic campaigns remain preserved. Formal budget approval is separate.
Use separate compatible environments for AppWorld and the pinned service.

### Historical runner reference

Run the main experiment script to compare performance with and without memory:

```bash
python run_appworld.py --campaign my-campaign
```

The old fixed-only runner behaved as follows (the audited CLI above supersedes it):
- Runs AppWorld tasks on the test-normal set
- Compares agent performance with ReMe memory (`use_memory=True`) vs without memory
- Runs one task per Ray batch in dataset order
- Runs each task multiple times for statistical significance
- Results are automatically saved to `./exp_result/` directory

**Configuration options in `run_appworld.py`:**
- `max_workers`: Number of parallel workers (default: 16)
- `num_runs`: Number of times each task is repeated (default: 4)
- `batch_size`: Number of concurrent tasks per batch (default: 1)
- `num_trials`: Maximum number of self-reflections, failure-aware reflection mechanism is triggered when num_trials>1 (default: 1)
- `model_name`: Task execution model (default: "qwen3.8-flash")
- `use_memory`: Whether to use ReMe memory library (default: True)
- `use_memory_addition`: Whether to enable selective addition (default: False)
- `use_memory_deletion`: Whether to enable utility-based deletion (default: False)

### 2. View Experiment Results

After running experiments, analyze the statistical results:

```bash
python run_exp_statistic.py
```

**What this script does:**
- Processes all result files in `./exp_result/`
- Calculates best@k, pass@k metrics for different k values
- Generates a summary table showing performance comparisons
- Saves results to `experiment_summary.csv`

**Metrics explained:**
- `best@k`: Takes groups of k runs per task, finds the maximum score in each group, then averages these maximums
- `pass@k`: Takes groups of k runs per task, measures the probability that at least one out of k independent task runs is successful.
- Higher k values show potential performance, lower k values show consistency
- In our AppWorld experiments, we report Task Goal Completion (TGC) metric, which measures percentage of tasks for which the agent passes all evaluation tests.

**Output Files**

- `./exp_result/*.jsonl`: Raw experiment results for each configuration
- `./exp_result/experiment_summary.csv`: Statistical summary table
- Console output: Real-time progress and summary statistics
