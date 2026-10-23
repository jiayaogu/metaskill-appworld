# Unified AppWorld Baseline Execution Plan

Status: in-progress implementation plan. Scope: ACE, ReasoningBank, PolySkill, ReMe. Sections 1–4 have partial code and focused offline tests. ReMe now has a coarse adapter and single-task entry point, but scored parity and resume acceptance in Section 6 are not complete. Do not use this as evidence that a baseline is fully migrated.

## 1. Contract and file ownership

Run one baseline, one dataset, one mode, and one model per experiment. `dataset_name` may be **any dataset name currently registered by AppWorld** from a `.txt` file under `ace-appworld/data/datasets/`; no baseline-specific dataset whitelist exists. The shared runner loads tasks, provides AppWorld capabilities, writes canonical LLM logs, and invokes official evaluation. Each adapter calls its existing baseline core; the core retains its own action, observation, retry, replay, reflection, and memory update order.

| Owner | Responsibility | Required boundary |
|---|---|---|
| Shared task loader | Read `ace-appworld/data/datasets/<dataset_name>.txt` with `load_task_ids(dataset_name)`; preserve file order; preflight each ID with `Task.load(task_id, load_ground_truth=False)` | Configs and adapters cannot provide task IDs, family IDs, manifests, variants, or a second ordering policy |
| Shared `EpisodeService` | Open/close `AppWorld(task_id, experiment_name, ...)`; expose execution and completion ports; support isolated auxiliary experiments when requested | The baseline requests episodes and retains its existing retry/replay policy |
| Shared evaluator | Wrap `evaluate_task` for baseline feedback; ensure a final primary task report; call `evaluate_dataset(experiment_name, dataset_name)` after the stream | Baseline decides when it consumes evaluation feedback; final safeguard does not feed back into its completed core |
| Shared LLM logger | Append every physical provider attempt to the owning primary task's `logs/lm_calls.jsonl` | Baseline wrapper retains its provider call, retry policy, response type, and cost policy |
| Baseline core | Prompts, next action/code, observations, stop rules, retrieval, replay, reflection, and memory changes | Existing order and durable update boundaries remain unchanged |

The canonical output root is `ace-appworld/experiments/outputs/<experiment_name>/`. AppWorld owns task `dbs/`, `checkpoints/`, `logs/api_calls.jsonl`, `logs/environment_io.md`, and `version/`. The official evaluator owns `evaluation/report.md` and `evaluation/version.txt`. The shared logger alone owns `logs/lm_calls.jsonl`. Baseline trajectory, playbook, skill, memory, cost, and diagnostic files are additive sidecars.

For every primary task, require:

```text
experiments/outputs/<experiment_name>/tasks/<task_id>/
├── dbs/
├── checkpoints/
├── logs/
│   ├── api_calls.jsonl
│   ├── environment_io.md
│   └── lm_calls.jsonl
├── evaluation/
│   ├── report.md
│   └── version.txt
└── version/
    ├── code.txt
    └── data.txt
```

Aggregate files are `experiments/outputs/<experiment_name>/evaluations/<dataset_name>.json` and `.txt`. AppWorld's `evaluate_dataset` uses its `dataset_name` argument as the filename; set `evaluation.dataset_output_name` to exactly `{dataset_name}`. The experiment directory keeps runs with different baselines/modes separate.

## 2. Package and interfaces to implement

Create an importable package at `ace-appworld/experiments/code/common/`:

```text
common/
├── contracts.py          # TaskContext, BaselineServices, ports, results
├── task_loader.py        # dataset file, load_task_ids, Task.load
├── appworld_runner.py    # outer task stream and EpisodeService
├── evaluator.py          # official task and dataset evaluation
├── lm_logger.py          # sole canonical LLM JSONL writer
├── output_contract.py    # canonical file and schema validation
├── config.py             # strict config compiler and run manifest
└── cli.py                # validate-config, run, evaluate, validate-output

baselines/
├── ace_adapter.py
├── reasoningbank_adapter.py
├── polyskill_adapter.py
└── reme_adapter.py
```

Implement coarse integration ports in `contracts.py`. Their methods expose capabilities; they do not prescribe a per-step workflow:

```python
class BaselineAdapter(Protocol):
    name: str

    def run_task(self, context: TaskContext, services: BaselineServices) -> BaselineTaskResult:
        """Invoke the baseline's existing core task method."""


class ExecutionPort(Protocol):
    def execute(self, code: str) -> str: ...  # delegates to world.execute(code)


class CompletionPort(Protocol):
    def task_completed(self) -> bool: ...      # delegates to world.task_completed()
    def complete_task(self, answer: object = None, status: str = "success") -> None: ...
    # delegates to world.apis.supervisor.complete_task; not an evaluator


class EvaluationPort(Protocol):
    def evaluate_task(self, *, suppress_errors: bool = True) -> OfficialTaskResult: ...


@dataclass
class BaselineServices:
    episodes: EpisodeService
    environment: ExecutionPort
    completion: CompletionPort
    evaluator: EvaluationPort
    llm: LLMCallLogger  # already bound to this primary task's canonical file
    artifacts: ArtifactStore
```

`TaskContext` includes task ID, dataset position/epoch, experiment name, non-GT loaded task data, canonical primary task directory, and sidecar directory. A baseline that already uses GT must request it through an explicit, separately validated capability; the loader must not leak GT to no-GT runs. `EpisodeService.open(kind, episode_id)` supplies execution/completion/evaluation ports. It preserves each baseline's current retry setup; only auxiliary episodes that already need isolation (such as PolySkill replay) use a separate AppWorld experiment. AppWorld removes the task output directory when reinitializing the same primary task (as ACE GT retry does); preserve and restore the canonical `lm_calls.jsonl` across that reset, under the same task owner, before another provider call. It never creates another canonical LLM log: the task's logger remains bound to the primary task file, with episode identity in record metadata.

Implement the outer loop in `appworld_runner.py`:

```python
task_ids = load_task_ids(dataset_name=spec.task_source.dataset_name)
for task_id in task_ids:
    Task.load(task_id=task_id, load_ground_truth=False)  # preflight without GT leakage

adapter = make_adapter(spec.baseline, spec.baseline_config)  # once per stream
for epoch, task_id in ordered_task_refs(task_ids, spec.task_source.num_epochs):
    context = make_task_context(spec, task_id, epoch)
    services = make_services(context)  # logger path is the primary task path
    result = adapter.run_task(context, services)
    services.evaluator.ensure_final_primary_report_if_needed()
    validate_task_output(context)
    checkpoint_at_adapter_declared_boundary(adapter, context, result)

evaluate_dataset(
    experiment_name=spec.experiment_name,
    dataset_name=spec.task_source.dataset_name,
)
```

`ensure_final_primary_report_if_needed()` runs only if the primary task has no official report or its DB changed after the last official evaluation. It cannot move or repeat a baseline memory update. On infrastructure failure, record the error separately and do not convert it to a task score. Reject task parallelism for adapters whose online memory requires sequential task order. Resume only when config, dataset file, task prefix, and baseline checkpoint hashes match.

## 3. One canonical task LLM logger

Create `common/lm_logger.py`. Its `ProcessSafeJsonlSink` is the only writer of `experiments/outputs/<experiment_name>/tasks/<task_id>/logs/lm_calls.jsonl`. The runner constructs one logger per primary task before invoking the adapter:

```python
def task_lm_log_path(output_root: Path, experiment_name: str, task_id: str) -> Path:
    return output_root / experiment_name / "tasks" / task_id / "logs" / "lm_calls.jsonl"


task_logger = LLMCallLogger(
    sink=ProcessSafeJsonlSink(
        task_lm_log_path(output_root, context.experiment_name, context.task_id)
    ),
    experiment_name=context.experiment_name,
    baseline=adapter.name,
    root_task_id=context.task_id,
)
services.llm = task_logger
```

Implement `invoke` and `ainvoke` at the physical provider boundary. The caller supplies phase, component, logical call ID, attempt number, and optional episode metadata. The logger assigns one physical ID, serializes/redacts the request and response, appends exactly one record, and returns the original response object:

```python
def invoke(self, *, provider_call, request, context, serializer):
    physical_id = context.physical_call_id or uuid.uuid4().hex
    started = utc_now()
    safe_input = redact_secrets(serializer.request(request))
    try:
        response = provider_call()
    except Exception as error:
        self.sink.append(make_error_record(physical_id, safe_input, error, context, started))
        raise  # original provider exception reaches the baseline retry loop
    self.sink.append(make_success_record(
        physical_id, safe_input, redact_secrets(serializer.response(response)),
        context, started
    ))
    return response
```

`ainvoke` awaits `provider_call()` and uses the same record schema. `context.physical_call_id` is optional; use it only when a baseline's existing cost ledger needs the same ID. Use ACE compatible top-level `id`, `input`, `output`, and `metadata`; include `metadata.experiment_name`, `baseline`, `root_task_id`, `phase`, `component`, `logical_call_id`, `attempt`, `episode_id`, `episode_kind`, status, and timestamps. `LiteLLMSerializer`, `OpenAISerializer`, and `EmbeddingSerializer` handle provider formats. The embedding serializer stores model, dimensions, usage, vector count, and vector hashes; it does not duplicate full vectors. Redact credentials in requests, responses, and errors before append. Preserve provider usage and observed model identity.

`ProcessSafeJsonlSink.append()` serializes one UTF-8 JSON line, holds an interprocess file lock while appending, flushes, and raises `LLMLoggingError` on failure. Every baseline retry loop must re-raise `LLMLoggingError` immediately; it is not a provider retry. Existing cost ledgers may consume the returned response or normalized record but cannot write a second canonical LLM log. Resume and cost aggregation deduplicate by physical `id`.

All calls for a primary task use **that task's one file**, including post-environment memory updates, ACE reflection/curation, PolySkill replay and skill finalization, and ReMe chat/embedding subprocesses. Replay AppWorld DB/API/evaluation outputs use their isolated auxiliary experiment; their LLM records stay in the primary task file with `episode_kind="replay"` and `episode_id`. For a genuinely multi-task ACE batch call, choose the first task in dataset order as the single owning task, include the complete `task_ids` list in metadata, and record only references in other task sidecars. Never create a run-level or auxiliary `lm_calls.jsonl`.

### Baseline insertion points

| Baseline | Provider boundary | Logger phases | Remove old writer |
|---|---|---|---|
| ACE | `experiments/code/ace/lite_llm_generator.py`: `self.chat_completion(**arguments)` inside `LiteLLMGenerator.generate` retry loop | `generator`, `reflector`, `curator`; optional `analyzer`, `api_predictor` | `may_log_call` JSONL write and `log_calls_to(world=...)` binding |
| ReasoningBank | `ReasoningBank/AppWorld/reasoningbank_appworld.py`: `OpenAIChatClient.chat` inside its existing retry loop | `executor`, `memory_induction`, `memory_update` | three `append_jsonl(...lm_calls...)` blocks in `run_task` |
| PolySkill | `PolySkill/polyskill/appworld/llm.py`: `OpenAICompatibleLLM.complete` around `completion_fn(...)` | current values `executor`, `skill_induction`, `replay_validation`, `storage_update` | any competing canonical JSONL writer; keep `CostLedger.record_call` for cost |
| ReMe chat | `ReMe/scripts/appworld_openai_wrapper.py`: nested `call_provider` around `client.chat.completions.create` | `executor`, `executor_repair`, `memory_rewrite`, `memory_extract`, `memory_validate` | no reconstructed parent-side LLM trace |
| ReMe embedding | `ReMe/scripts/appworld_reme_bridge.py`: `await component.model(texts)` | `embedding`, with `metadata.purpose` | no reconstructed parent-side LLM trace |

Apply these wrappers without moving the surrounding baseline loops:

```python
# ACE: inside LiteLLMGenerator.generate's existing try block, replace only
# the provider call, cost assignment, and `self.may_log_call(...)`.
def call_and_cost():
    response = self.chat_completion(**arguments)
    response["cost"] = self.completion_cost(completion_response=response)
    return response

response = task_logger.invoke(
    provider_call=call_and_cost,
    request=arguments,
    context=make_lm_context(phase=self.role, logical_call_id=logical_id, attempt=attempt),
    serializer=LiteLLMSerializer(),
)
# Keep existing `except RETRY_ERROR`, backoff, postprocessing, and return.

# ReasoningBank: add `call_context` to OpenAIChatClient.chat's signature;
# construct `request` from its current model/messages/temperature/max_tokens.
# Replace the provider call inside its current retry loop (attempt is 0-based).
response = task_logger.invoke(
    provider_call=lambda: self.client.chat.completions.create(**request),
    request=request,
    context=make_lm_context(phase=call_context.phase,
                            logical_call_id=logical_id, attempt=attempt + 1,
                            step=call_context.step, epoch=call_context.epoch),
    serializer=OpenAISerializer(),
)
# Keep cost_tracker.track_response after success; remove only manual LLM JSONL appends.

# PolySkill: complete() already receives phase, ledger, metadata.
# Reuse its existing `call_id`; build `request` from current complete() args.
metadata = metadata or {}
call_id = uuid.uuid4().hex
response = task_logger.invoke(
    provider_call=lambda: self.completion_fn(**request),
    request=request,
    context=make_lm_context(phase=phase, episode_id=metadata.get("episode_id"),
                            physical_call_id=call_id),
    serializer=OpenAISerializer(),
)
ledger.record_call(phase=phase, response=response, call_id=call_id,
                   metadata=metadata)
return response_text(response)
```

In ACE and ReasoningBank retry loops, add `except LLMLoggingError: raise` before any broad provider-error handler. PolySkill has no internal provider retry loop; let `LLMLoggingError` propagate. Keep the original handlers and backoff code untouched. For ACE, bind `task_logger` and `self.role` (`generator`/`reflector`/`curator`) when constructing each role generator, initialize `logical_id` once before its retry loop, and derive `attempt` from the loop index without changing its retry count. In ReasoningBank, pass a distinct `call_context` from executor, memory-induction, and memory-update call sites; remove only the three manual canonical LLM JSONL appends.

For PolySkill replay, pass the **same primary task logger** into `run_replay_validation`; only add `episode_id`/`episode_kind="replay"` to call context. The current `execute → evaluate → induce → replay → replay-evaluate → finalize` sequence remains in `polyskill/appworld/runner.py`.

For ReMe, `ReMeAdapter.run_task()` passes `subprocess_logger_environment(services.llm)` to `ReMeAppWorldTaskCore.run_task()`. The core installs these values for exactly one task while preserving `_memory_pre → run_episode → _memory_post`; existing `_python_environment()` and `_invoke_executor()` copy that environment into the chat and embedding workers. Do not add a second logger writer or change the legacy helper call order:

```python
logger_environment = subprocess_logger_environment(services.llm)
result = core.run_task(context, services, logger_environment=logger_environment)
# ReMeAppWorldTaskCore applies logger_environment only around this task's
# existing memory and executor calls; subprocesses inherit os.environ.copy().

# In appworld_openai_wrapper.py, around each physical chat call:
response = LLMCallLogger.from_environment().invoke(
    provider_call=lambda: client.chat.completions.create(**kwargs),
    request=kwargs,
    context=make_lm_context(phase=phase, logical_call_id=logical_id, attempt=attempt),
    serializer=OpenAISerializer(),
)

# In appworld_reme_bridge.py, around the existing embedding call:
embedding_response = await LLMCallLogger.from_environment().ainvoke(
    provider_call=lambda: component.model(texts),
    request={"model": embedding_model, "input": texts, "dimensions": dimensions},
    context=make_lm_context(phase="embedding", metadata={"purpose": purpose}),
    serializer=EmbeddingSerializer(),
)
```

`from_environment()` rejects any path outside the current primary task's canonical `logs/lm_calls.jsonl`. JSON repair is a second logical/physical call (`executor_repair`); provider retries share one logical ID with increasing attempt numbers. Keep ReMe provider response, raw content, usage, and cost sidecars.

## 4. One shared run config

Implement a strict discriminated config in `common/config.py`. These are the shared fields for every run; adapter-specific fields go only under `baseline_config`. The `quick2h_test_normal` values below illustrate **one run**, not a default or an allowed-dataset restriction:

```yaml
schema_version: appworld-baseline-run-v1
baseline: ace  # ace | reasoningbank | polyskill | reme
experiment_name: ace_quick2h_test_normal_online_adaptation_qwen3.8-flash
task_source:
  dataset_name: quick2h_test_normal
  num_epochs: 1
runtime:
  num_processes: 1
  process_index: 0
  resume: false
  dry_run: false
appworld:
  root: ${APPWORLD_ROOT}
  random_seed: 123
  max_interactions: null
  timeout_seconds: null
  raise_on_unsafe_syntax: null
  raise_on_failure: null
evaluation:
  enabled: true
  suppress_errors: true
  save_task_reports: true
  aggregate: true
  dataset_output_name: quick2h_test_normal
output:
  canonical_root: ace-appworld/experiments/outputs
  baseline_artifacts_subdir: baseline_artifacts/ace
logging:
  llm_calls: {enabled: true, fail_closed: true, process_safe: true}
provider_environment:
  env_file: .env
  api_key_env: OPENAI_API_KEY
  base_url_env: OPENAI_BASE_URL
pricing:
  registry_path: ace-appworld/experiments/code/openai_cost_registry.json
  require_known_price: false
safety_limits:
  max_environment_executions: 100
  max_wall_time_seconds_per_task: null
  max_cost_usd_per_task: null
  max_cost_usd_overall: null
baseline_config: {}  # one of the validated blocks below
```

Derive `experiment_name` as `{baseline_name}_{dataset_name}_{offline_adaptation|online_adaptation|evaluation}_{model_name}`. `model_name` is always `qwen3.8-flash`; ReMe embedding remains `text-embedding-v4`. `evaluation.dataset_output_name` equals **only** `task_source.dataset_name`. Reject mismatches. On any dataset/mode/baseline change, regenerate the experiment name and dataset output name. The shared task loader is the only source of task IDs. Discover valid names with AppWorld's `valid_dataset_names()` or equivalent directory-based lookup, then call `load_task_ids(dataset_name=...)`; never hardcode `quick2h_*`, `18_task_online_no_gt_pilot`, or a per-baseline list. Reject unknown keys, direct task/family selectors, model matrices, aliases, fallback models, and incompatible mode/core combinations.

### ACE `baseline_config`

Example ACE block: shared `baseline: ace`, `dataset_name: quick2h_test_normal`, `mode: online_adaptation`, and `experiment_name: ace_quick2h_test_normal_online_adaptation_qwen3.8-flash`. Substitute any registered dataset name and regenerate both names; ACE's dataset choice is not fixed by this example:

```yaml
baseline_config:
  mode: online_adaptation  # offline_adaptation | online_adaptation | evaluation
  run_type: ace-adaptation  # ace-adaptation | ace-evaluation | non-ace-evaluation
  batch_size: 1
  curator_batch_size: null
  curator_parallel: true
  curator_max_workers: null
  use_bulletpoint_analyzer: false
  bulletpoint_analyzer_threshold: 0.90
  augmented_shuffling: true
  augmented_shuffling_factor: null
  agent:
    type: ace_adaptation_react
    generator_model_config: &ace_model
      name: qwen3.8-flash
      provider: openai
      completion_method: openai
      base_url: null
      temperature: 0
      seed: 100
      stop: ["<|endoftext|>", "<|eot_id|>", "<|start_header_id|>"]
      logprobs: false
      top_logprobs: null
      frequency_penalty: 0
      presence_penalty: 0
      n: 1
      response_format: {type: text}
      retry_after_n_seconds: 10
      use_cache: false
      max_retries: 50
      token_cost_data: null
    reflector_model_config: *ace_model
    curator_model_config: *ace_model
    generator_prompt_file_path: ace-appworld/experiments/prompts/appworld_react_generator_prompt.txt
    reflector_prompt_file_path: ace-appworld/experiments/prompts/appworld_react_reflector_no_gt_prompt.txt
    curator_prompt_file_path: ace-appworld/experiments/prompts/appworld_react_curator_prompt.txt
    initial_playbook_file_path: ace-appworld/experiments/playbooks/appworld_initial_playbook.txt
    trained_playbook_file_path: ace-appworld/experiments/playbooks/quick2h_offline_online/qwen3.8-flash/online_no_GT_test_normal.txt
    ignore_multiple_calls: true
    max_prompt_length: null
    max_output_length: 400000
    max_steps: 40
    max_cost_overall: 1000
    max_cost_per_task: 10
    use_reflector: true
    use_gt_code: false
    num_retries_with_gt: 5
    logger_config: {verbose: true, color: true}
```

Map legacy `agent.appworld_config.random_seed` into shared `appworld.random_seed`; map legacy `agent.log_lm_calls` into the shared logger. Reject model role drift. For `evaluation`, require the existing ACE evaluation agent type and trained playbook; do not instantiate Reflector/Curator. Keep ACE `StarAgent` loop, GT retry order, curator/reflection positions, batch behavior, and playbook persistence. The core calls injected ports in place of raw `AppWorld`/evaluator calls.

### ReasoningBank `baseline_config`

Example ReasoningBank block: shared `baseline: reasoningbank`, `dataset_name: 18_task_online_no_gt_pilot`, `experiment_name: reasoningbank_18_task_online_no_gt_pilot_online_adaptation_qwen3.8-flash`, `evaluation.dataset_output_name: 18_task_online_no_gt_pilot`, `appworld.random_seed: 123`. Substitute any registered dataset name and regenerate both names:

```yaml
baseline_config:
  mode: online_adaptation
  model: {name: qwen3.8-flash}
  max_steps: 40
  max_tokens: 8192
  temperature: 0.0
  memory_temperature: 0.3
  max_memory_items: 6
  max_observation_chars: 20000
  request_timeout_seconds: 120
  provider_retries: 4
  embedding_cache: null
  retrieval_fallback: local_lexical
  memory:
    state_file: memory_state.json
    events_file: memory_events.jsonl
    trained_bank_file: trained_memory_bank.txt
    preserve_active_items_across_tasks: true
  cost:
    ledger_file: cost_ledger.jsonl
    summary_file: cost_summary.json
```

In `ReasoningBank/AppWorld/reasoningbank_appworld.py`, keep `retrieve → executor loop → official evaluation → memory induction → memory update`. Replace its `--families`/`--models` task/model selection with the shared dataset/model config; reject direct selectors in the unified CLI. Remove output mirroring. Keep `OpenAICostTracker` and memory sidecars under `baseline_artifacts_subdir`.

### PolySkill `baseline_config`

Example PolySkill block: shared `baseline: polyskill`, `dataset_name: 18_task_online_no_gt_pilot`, `experiment_name: polyskill_18_task_online_no_gt_pilot_online_adaptation_qwen3.8-flash`, `evaluation.dataset_output_name: 18_task_online_no_gt_pilot`, `appworld.random_seed: null`. Substitute any registered dataset name and regenerate both names:

```yaml
baseline_config:
  mode: online_adaptation
  model:
    name: qwen3.8-flash
    base_url_source: pricing_registry
    api_key_env: OPENAI_API_KEY
    temperature: 0.0
    max_tokens: 2048
  max_steps: 12
  skill_store:
    directory: skills
    format: polyskill_appworld_v1
    prompt_recent_skill_limit: 8
  induction:
    enabled: true
    only_after_official_success: true
    require_nonempty_executed_code: true
  replay_validation:
    enabled: true
    task_policy: same_task
    auxiliary_experiment_suffix: replay_validation
    count_in_primary_metrics: false
    store_only_after_success: true
  storage_update:
    enabled: true
    normalize_with_same_model: true
    validated_by: same_task_replay
  diagnostics:
    write_trajectory: true
    write_memory_events: true
    write_failure_analysis: true
```

Replace `PILOT_TASK_IDS` as the source of task order in `polyskill/appworld/runner.py`; use the loader's ordered IDs. Preserve success-only induction, same-task replay, replay evaluation outside primary TGC/SGC, and storage only after replay success. Write `skills.json`, `trajectory.json`, `memory_events.jsonl`, `result.json`, and failure analysis as baseline sidecars.

### ReMe `baseline_config`

Example ReMe block: shared `baseline: reme`, `dataset_name: 18_task_online_no_gt_pilot`, `experiment_name: reme_18_task_online_no_gt_pilot_online_adaptation_qwen3.8-flash`, `evaluation.dataset_output_name: 18_task_online_no_gt_pilot`, `appworld.random_seed: 1729`, `appworld.max_interactions: 30`, `appworld.raise_on_unsafe_syntax: true`, `appworld.raise_on_failure: false`. Substitute any registered dataset name and regenerate both names. The baseline being preserved is the existing **ReMe AppWorld pilot method**, not an unused native `AgentWrapper` or a newly invented ReMe Job sequence:

```yaml
baseline_config:
  mode: online_adaptation  # or offline_adaptation; no arms
  source_pins:
    reme_root: ${REME_ROOT}  # absolute path; resolved before import
    reme_python: ${REME_PYTHON}  # ReMe environment executable
  models:
    executor: qwen3.8-flash
    summarizer: qwen3.8-flash
    embedding: text-embedding-v4
    embedding_dimensions: 1024
  memory:
    top_k: 5
    max_experiences_per_task: 3
    dedup_threshold: 0.95
    delete_alpha: 5
    delete_beta: 0.5
    success_only_update: true
    family_local: true
  execution:
    outer_max_steps: 30
    executor_timeout_seconds: 240
    executor_command: null  # defaults to reme_python -m metaskill_org.benchmarking.appworld_openai_wrapper
    forward_executor_env: []
    forward_memory_env: []
    require_usage_sidecar: true
```

`common/baselines/reme_adapter.py` invokes `ReMe/scripts/appworld_unified_core.py` once per task. Its `_memory_pre` and `_memory_post` functions live in `ReMe/scripts/appworld_memory_core.py`; they were extracted unchanged from the former study harness (19 relevant function ASTs matched during cleanup). `appworld_episode_bridge.run_episode()` keeps its executor-turn loop and requires the shared `EpisodeService`; its separate AppWorld constructor, standalone pilot CLI, and incompatible `metaskill-` experiment-name requirement were removed. Preserve the original **memory-pre → executor turns / `world.execute` → completion → official evaluation → memory-post** order. The shared task loader alone selects IDs; fixed-task/multi-arm schedulers, qualification, oracle, public-context export, and synthetic AppWorld output exporters were removed from the active ReMe source tree. Family-local checkpoint position is the encounter order within the selected dataset. The memory values above are fixed original pilot invariants; reject drift rather than silently changing them. The existing executor JSON decoding/repair and prompt templates remain in the baseline wrapper. `appworld_openai_wrapper.py` and `appworld_reme_bridge.py` retain provider calls and delegate each physical call to the shared task logger through the subprocess environment. Baseline artifacts are sidecars only; existing historical experiment outputs were not changed.

## 5. Config compilation and validation

Implement these checks in `common/config.py` before opening AppWorld:

1. Reject unknown keys. Accept only `task_source.dataset_name` and `num_epochs` as task source fields. Accept any name in AppWorld's dynamically discovered `valid_dataset_names()`; do not restrict names by baseline or by the examples above. Verify the dataset file exists, call `load_task_ids`, preserve order, and preflight every ID with `Task.load(task_id, load_ground_truth=False)`.
2. Validate that every chat/executor/memory model equals `qwen3.8-flash`; ReMe embedding must equal `text-embedding-v4`. Reject aliases, model matrices, fallbacks, and model environment overrides.
3. Derive `experiment_name` from baseline, dataset, mode, and model. Require `evaluation.dataset_output_name == task_source.dataset_name`.
4. Validate adapter mode support. `offline_adaptation`, `online_adaptation`, and `evaluation` have distinct memory update policies; ReMe supports the first two. Do not infer a mode from an experiment name.
5. Resolve relative paths against the config file, verify prompt/playbook/qualification files, pricing registry, Python executables, and source revisions. Keep credential values out of the resolved manifest.
6. Reject task parallelism when it changes online memory order. Reject shared safety ceilings lower than baseline limits.
7. Freeze config hash, dataset file hash and ordered task IDs, adapter/source revisions, AppWorld code/data versions, and output paths in `run_manifest.json`. On resume, require matching config, dataset, and completed-event prefix hashes.

Expose `validate-config`, `run`, `evaluate`, and `validate-output` in `common/cli.py`. Compatibility CLIs translate legacy options into the strict schema and fail on selectors/models outside it.

## 6. Migration and verification

1. Implement the shared ports, logger, config compiler, and output validator. Capture one ACE task and aggregate evaluation as golden fixtures.
2. Inject ports into ACE `StarAgent` and its role generators. Compare legacy and shared ordered traces, final DB hashes, official scores, playbook updates, and task LLM records. Do not change ACE prompts or control flow in this step.
3. Migrate ReasoningBank, PolySkill, then ReMe. For each, run one fixed task and one small registered dataset with a complete three-task family. Compare legacy and shared execution/evaluation/memory event order and official TGC/SGC.
4. Add replay and retry cases. Verify PolySkill replay AppWorld artifacts use an auxiliary experiment while all replay LLM records remain in the primary task's file. Verify ReMe chat, repair, memory, and embedding subprocess calls all write to that same task file.
5. Add resume checks at each baseline's native durable update boundary. Interrupt a run, resume, and verify task order, memory state, physical call IDs, and cost records are not duplicated.
6. ReMe's duplicate study construction, output mirroring, and synthetic file exporters have been removed from the active source tree after mechanically extracting its memory methods; preserve baseline-owned reasoning and memory loops. For other baselines, remove such duplicate code only after parity passes.

Acceptance checks:

- Every adapter receives loader-resolved tasks in dataset order and calls its original core with shared services; no shared `next_action → observe → update_memory` state machine exists.
- Each adapter accepts any AppWorld-registered dataset name; switching from `quick2h_test_normal` to `train`, `dev`, or another registered dataset changes the loader-selected tasks and derived output names without adding a baseline-specific dataset gate or changing its core algorithm.
- Every environment action reaches `world.execute` through the execution port. Completion checks and official evaluations reach AppWorld through their corresponding ports.
- Each primary task has AppWorld-native DB/API/environment/version files, one official task evaluation report, and one canonical task `lm_calls.jsonl`. Every physical provider attempt appears exactly once in an owning primary task file; there are no run-level or auxiliary LLM logs.
- `evaluate_dataset(experiment_name, dataset_name)` produces `evaluations/<dataset_name>.json` and `.txt`, with AppWorld metric semantics.
- Ordered core event traces, baseline memory transitions, final DB state, TGC/SGC, and resume behavior match the legacy implementation except for documented infrastructure/path changes.

Implementation checkpoint: `experiments/code/common/` contains the task loader, episode/evaluation ports, output checks, logger, config compiler, CLI, and ACE/ReasoningBank/PolySkill/ReMe adapter starts. ReMe's single-task entry point calls the extracted, unchanged memory core and existing executor-turn loop with shared `EpisodeService` injection; the incompatible old study scripts and tests are absent from the active ReMe tree. Config compilation delegates dataset order and non-GT task preflight to the shared loader and rejects unknown nested model/config fields; ACE's existing React core instantiates offline through its adapter. Provider wrappers have optional shared logger delegation. ACE batching, unified resume, and end-to-end parity remain unimplemented. No real provider run has been performed.
