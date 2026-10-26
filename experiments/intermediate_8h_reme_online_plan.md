# ReMe Three-Arm AppWorld Reproduction Plan

Date: 2026-10-23 (America/Toronto). Revised 2026-10-24: one run per arm/dataset, as requested by the user.

Status: plan only. This supersedes the earlier two-stream, cold-start-only intermediate-8h plan. No scored ReMe run is claimed. The method reference is ReMe commit `2f37a159b72a04ac1885a7db7f1a663a833e7791` (`2f37a15`), specifically `benchmark/appworld/run_appworld.py`, `benchmark/appworld/appworld_react_agent.py`, and the `reme2` service flow in `reme/config/service.yaml`. The isolated worktree `../../../reme-2f37a15-qwen38/` applies the approved chat-model override to `qwen3.8-flash` and the requested `batch_size=1` override; it is not a byte-identical checkout. The user approved loading the bundled AppWorld experience pool instead of training new pools from the intermediate-8h or quick2h-v2 train subsets.

## 1. Objective and frozen datasets

Compare ReMe (fixed), ReMe (dynamic), and ReMe (cold start) independently on each subset:

| AppWorld dataset | Tasks | Families | SHA-256 of dataset file |
| --- | ---: | ---: | --- |
| `intermediate_8h_test_normal` | 57 | 19 | `2d2355a0bb55e00ff72a60731b7e8ffdbc2536cdf43526721f5c993b157dbaf8` |
| `intermediate_8h_test_challenge` | 138 | 46 | `c27f9d6df4e5967f57a67ab981c98a97193adfd1e00306f89dc7529c035e9795` |
| `quick2h_test_normal_v2` | 21 | 7 | `f42bacdfd70d33faf77d9cbc9be568a75e3f623d519bbc04205f7657deff4a04` |
| `quick2h_test_challenge_v2` | 18 | 6 | `558ee0e389f64e5fb7fca9a02253a72dd4840df1eae19033b32d94c934086cd9` |

Use `load_task_ids(dataset_name)` and each file's order. The four datasets are separate test streams; no test-derived memory crosses datasets. Give every (dataset, arm, run index) a unique memory namespace, AppWorld experiment name, output root, and run manifest. The user-requested `num_runs=1` override gives 12 arm/dataset cells, 12 run instances, and 702 primary task attempts before any infrastructure retry. Obtain budget approval before launching them.

Use **one common bundled starting snapshot** for fixed and dynamic across all four test subsets: `docs/library/paper_data/task/appworld_qwen3_8b.jsonl` from `2f37a15`. It contains 207 procedural records and has SHA-256 `a1cbe575b1f6dc98b35908b4f4b62796d41cdddcb023dd043c96e2abaeac7921`. Its records are AppWorld-specific; however, they do not include task IDs or a provenance manifest, so the exact acquisition tasks cannot be independently verified from the artifact. Do not claim it was built from either local subset train file. No new initial-pool acquisition is required for this plan.

Each fixed and dynamic test run starts from an independent import of these **same bytes**. Normal and challenge never share test-time updates. Cold start starts from an empty collection.

## 2. Arm definitions

| Arm | Starting pool for each run | `use_memory` | `use_memory_addition` | `use_memory_deletion` |
| --- | --- | --- | --- | --- |
| ReMe (fixed) | Fresh import of the bundled `appworld_qwen3_8b.jsonl` | `True` | `False` | `False` |
| ReMe (dynamic) | Fresh import of that **same** bundled file | `True` | `True` | `True` |
| ReMe (cold start) | Empty pool in the same memory service/schema | `True` | `True` | `True` |

Dynamic is the fixed configuration with the original agent's addition/deletion switches enabled. **The checked-in `main()` only configures fixed; no dynamic preset is checked in at this commit.** This is an explicit minimal derivation, not a claim to have found the authors' dynamic launch command. Cold start must run the **identical dynamic workflow**; initial pool contents are its only method difference. Do not use `use_memory=False` for cold start, because that bypasses retrieval and the update workflow.

### Bundled-pool load contract

Follow `run_appworld.py:145-175`: before each independent fixed or dynamic run, call the `reme2` service's `POST /load_memory` with `{"load_file_path": "docs/library/paper_data/task/appworld_qwen3_8b.jsonl", "clear_existing": true}`. The path is resolved by the **service process**, so verify its working directory and the file bytes visible to that process. The pinned `LoadMemory` operator clears the active vector collection, parses each JSONL line as a `MemoryNode`, converts records to vector nodes, and inserts them. The bundled file has no vectors; the configured vector store embeds each `when_to_use` field on import. Use the original AppWorld quickstart's `reme2` service and Elasticsearch collection with the approved `qwen3.8-flash` chat model and original `text-embedding-v4` embedding model (1024 dimensions), or document and parity-test any unavoidable deployment substitution. The bundled file retains its historical `appworld_qwen3_8b.jsonl` name and bytes; changing the serving model does not regenerate that pool.

Because `clear_existing` clears the **whole active collection**, isolate each run with a dedicated collection/service or a verified clear-and-reload boundary; never use one live collection for overlapping arm/dataset runs. For cold start, clear the collection and verify zero records, but retain the same service, model, retrieval, update, and deletion settings as dynamic. Verify that seeded loads have exactly 207 records, no parse skips, the expected memory IDs/content, and the expected collection size before the first task. The checked-in runner loads once before its four-run loop; this plan deliberately reloads before **each** run to prevent cross-run carryover.

## 3. Exact code-config lock

All three test arms use the same source-pinned AppWorld agent, prompt, and `reme2` memory-service code. Except for dataset selection, unique output/collection identities, per-run reset, the approved chat-model, batch-size and run-count overrides, and the arm switches above, keep these evaluation values:

| Source | Locked setting |
| --- | --- |
| `run_appworld.py:160-193` | `max_workers=16`, requested override `batch_size=1`, requested override `num_runs=1` (source default: 4), `num_trials=1`, approved model override `model_name="qwen3.8-flash"`, `use_memory=True`, memory URL default `http://0.0.0.0:8002/`, `delete_freq=5`, `freq_threshold=5`, `utility_threshold=0.5`. The `run_agent` function default is also `batch_size=1`. |
| `appworld_react_agent.py:32-48` | Executor `temperature=0.9`, `max_interactions=30`, `max_response_size=129024`, and original ReAct prompt/code-execution loop. |
| `appworld_react_agent.py:77-86` | Original OpenAI-compatible call, `seed=0`, `enable_thinking=False`, and original retry policy. |
| `appworld_react_agent.py:264-274` | Task-initial retrieval, `top_k=5`; LLM reranking, score filtering, and query rewriting disabled. |
| `appworld_react_agent.py:294-345` | Original summary, validation, add, record, and delete API calls and thresholds. |
| `reme/config/service.yaml` and `benchmark/appworld/quickstart.md` | The original `reme2` HTTP flows, approved `qwen3.8-flash` service LLM override, `text-embedding-v4` at 1024 dimensions, and Elasticsearch collection. Freeze actual service settings, dependencies, and hashes before launch. Do not substitute the separate `reme_ai` service. |

Use a distinct experiment suffix for each arm/run so AppWorld artifacts cannot overwrite each other. This is output isolation, not an algorithm change. Preserve the source's `num_trials=1` and original agent code; do not silently add the paper's higher reflection limit, the local pilot's three-experience cap, or a different extraction pipeline. No family-local filter appears in the pinned AppWorld retrieval call: a task may retrieve any eligible experience in its run's shared pool, regardless of family.

The current unified AppWorld runner requires `qwen3.8-flash`, the local ReMe embedding setting `text-embedding-v4`, and sequential ReMe online execution. The model and batch-size overrides align its chat model and one-task-at-a-time order, but the historical Ray actor and `reme2` service workflow still cannot execute unchanged through that runner. Use the isolated `2f37a15` worktree or implement a narrowly scoped compatibility path with parity tests. Do not weaken the unified runner's global constraints or call its existing pilot implementation an exact `2f37a15` reproduction.

## 4. Memory lifecycle and source-level caveats

At task start, the agent retrieves experience. It then executes in AppWorld and gets `after_score` from `world.evaluate()`. If addition is enabled, it sends the trajectory to `summary_task_memory` and calls `add_task_memory` when `after_score == 1`. With memory enabled it also records retrieved-memory frequency/utility; if deletion is enabled it calls `delete_task_memory` after the task. A failed task can change utility statistics and trigger deletion. The pinned deletion operator uses `freq >= 5` and **`utility/freq < 0.5`**, not an inclusive boundary.

The pinned `reme2` service defines `summary_task_memory` as preprocessing, success/failure/comparative extraction, validation, and deduplication; it does **not** insert the result. `add_task_memory` is a separate insertion flow, called by the agent only when `after_score == 1`. This corrects the previous plan's warning, which mistakenly cited the separate `reme_ai` service. Verify the boundary with a failed and a successful task before scored execution: failures must not add new experience IDs, although they may change retrieved-memory metadata or trigger deletion. Use the same workflow in dynamic and cold start.

The fixed flags disable the explicit summary/add and delete branches, but the agent still calls `record_task_memory`. Require the fixed arm's **experience IDs, membership, and content** to remain unchanged during test evaluation; audit that invariant after every task. Metadata such as retrieval frequency/utility may still change under the pinned code, so do not claim the vector store is byte-for-byte immutable. Report metadata mutations separately; suppressing the record call would be a distinct, non-pinned strict-freeze variant.

## 5. Task order and run isolation

The historical runner submits Ray batches of eight, but this worktree uses `batch_size=1`. Its batch loop awaits `ray.get` for the sole task before shutting down Ray and starting the next batch. The agent makes synchronous memory-service calls before returning from `execute()`. With an isolated service and no failed or unacknowledged memory call, task `i` therefore cannot retrieve experience created by future tasks; it can use only the starting pool and updates committed by tasks `1..i-1`. Record task submission, retrieval, evaluation, and memory-write timestamps, batch indices, and retrieved IDs to verify this order. Treat a Ray-task or memory-service failure as a readiness failure, not proof of a causally valid run.

Strict no-future-task online adaptation is now the primary ordering requirement. Keep `max_workers=16` unchanged: because it selects the Ray branch but each batch contains one task, it does not cause within-run task overlap. Do not add a batch-snapshot barrier or silently change to a different execution branch. The `batch_size=1` setting is an explicit deviation from `2f37a15` and must be reported alongside the model override.

Reload the exact **bundled pool** before **each** fixed or dynamic run and verify an empty collection before **each** cold-start run. The same bundled snapshot initializes all four test datasets independently, with no cross-test transfer. The checked-in fixed script loads a pool only once before the four-run loop; simply flipping its flags would otherwise carry dynamic updates across nominal runs. Per-run reset is a documented experimental-isolation adjustment so all 12 arm/dataset cells start independently; do not claim the release script already resets between runs. Never carry final memory from one arm or dataset to another.

## 6. Per-task execution and evidence contract

This is the **target execution contract**, not a claim that the isolated worktree already provides all of these artifacts. Keep the `2f37a15` task algorithm and the approved model/`batch_size=1` overrides; add only narrowly scoped dataset/run selection, output isolation, logging, and audit shims. The historical script currently selects `test_normal`, runs the fixed arm, appends one JSONL result file, and reuses its experiment name across four runs. It does **not** provide the shared per-call logger, per-run memory reset, unique task-output roots, or the full three-arm matrix yet. Do not launch scored runs until these gaps are closed and parity-tested.

For each independent `(dataset, arm, repetition)` run, use this sequence:

1. **Initialize the run.** Resolve one unique experiment name and AppWorld root, freeze the ordered dataset IDs and source/config hashes, and start an isolated `reme2` collection. Load and verify the 207-record bundled pool for fixed/dynamic or verify zero records for cold start. Import-time embeddings and any other setup provider calls are run-scoped, not falsely attributed to the first test task. Write the run manifest and initial memory snapshot/hash before task 1.
2. **Load task `i` without an oracle.** Use `load_task_ids(dataset_name)` in file order and preflight with `Task.load(task_id, load_ground_truth=False)`. The historical runner currently does only the first operation; preflight is an added safety check. Open `AppWorld(task_id, experiment_name=<run_base>_run_0)` with the same task-side defaults as `2f37a15`. AppWorld initializes a private output DB from the task input, creates task directories, and persists initial state/logs. The local evaluator may read ground truth, but the solver prompt and any API-plan artifact must not receive `ground_truth.required_apis`, reference code, or private test data. Compute `before_score` with the original `world.evaluate()` call.
3. **Form the API approach inside the original ReAct loop.** `prompt_messages()` renders `NEW_PROMPT_TEMPLATE` from supervisor information and app descriptions, then appends the task instruction. If memory is enabled, `retrieve_task_memory` searches the entire current run collection by instruction (`top_k=5`, no LLM rerank/score filter/query rewrite) and appends returned experiences. There is **no separate API-planning model call** in the pinned method: the executor chooses an API plan through its ordinary responses and can inspect `apis.api_docs.show_app_descriptions`, `show_api_descriptions`, and `show_api_doc` in AppWorld. Capture the actual API-doc calls and any plan expressed in the model's trajectory. If an explicit API-plan summary is needed for analysis, derive it **after** execution from that evidence and label it post hoc; do not inject a newly generated API shortlist or oracle API list into the solver.
4. **Call the executor and apply actions.** On each of at most 30 interactions, call the OpenAI-compatible `qwen3.8-flash` executor with the original messages, `temperature=0.9`, `seed=0`, `enable_thinking=False`, and original retry policy. Record **each physical provider attempt**, including failures and retries, before accepting its response. Preserve the original first-Python-block extraction and `world.execute(code)` behavior; append the environment observation to history. AppWorld records `api_docs` and application API calls in `logs/api_calls.jsonl`, code/observations in `logs/environment_io.md`, and updates its output `dbs/` after executed actions. Stop when `world.task_completed()` or the interaction cap is reached. A completion call is an AppWorld supervisor API action, not a substitute for official evaluation.
5. **Score, then update ReMe memory.** Compute `after_score` through the original `world.evaluate()` against the task's output DB; preserve `before_score`, `after_score`, `uplift_score`, completion status, and trajectory in the original result schema. Fixed does not summarize/add/delete, but still calls `record_task_memory` for retrieved IDs. Dynamic and cold start call `summary_task_memory` even after failure; only `after_score == 1` may call `add_task_memory`. All arms record retrieved-memory frequency/utility, and dynamic/cold start then call `delete_task_memory` with the original thresholds. The summary flow does not insert. Log each HTTP request/response, retrieved/added/updated/deleted ID, collection count, and before/after state hash in a memory-event ledger. AppWorld `dbs/` and ReMe's Elasticsearch collection are separate: do not put experience updates into AppWorld task DB dumps or treat those dumps as the memory pool.
6. **Finalize task evidence before advancing.** Wait for all task-scoped HTTP/model calls and the Ray actor to finish; reject a swallowed `ray.get` error or failed/unacknowledged memory call. Close AppWorld, verify the final DBs and logs, and call official `evaluate_task(..., save_report=True)` after close if the existing `world.evaluate()` report is missing or stale. Its strict task result must agree with the reward used for the update decision; do not recompute the reward *after* memory update to change that decision. Only then commit the task audit record and start task `i+1`. With one task per Ray batch and an isolated collection, this is the no-future-task boundary.
7. **Aggregate after the final task.** Run the official `evaluate_dataset(experiment_name, dataset_name, save_reports=True)` for that run, producing `evaluations/<dataset_name>.json` and `.txt`. Verify every task directory and official report before calculating TGC/SGC or comparing arms. A missing task, report, model-call trace, or memory event is an incomplete run, not a zero-scored benchmark failure.

### Shared call logging and storage ownership

Use `ace-appworld/experiments/code/common/lm_logger.py` as the single canonical writer of each task's `logs/lm_calls.jsonl`. Wrap the pinned executor's `OpenAI.chat.completions.create` boundary and the `reme2` service's chat and embedding provider boundaries without changing prompts, retry order, or service flows. Every physical request needs a unique ID, logical-call/retry linkage, UTC start/end, phase (`executor`, `memory_retrieval`, `memory_summary`, `memory_validation`, `memory_addition`, etc.), model, redacted request/response or error, usage, and task/run identity. For embeddings, retain usage, dimensions/count and vector hashes rather than full vectors. The service is long-lived, so propagate identity **per HTTP request** through its async flow/provider calls; a process-global environment variable cannot safely attribute calls to one task. Log setup/import calls in a separate run-scoped ledger using the same record discipline. Never mix HTTP memory events or AppWorld API calls into `lm_calls.jsonl`: those have their own ledgers. The current `2f37a15` worktree lacks these instrumentation hooks; the unified ReMe pilot's logger integration is not evidence that the pinned `reme2` path already has them.

Use the canonical AppWorld output root resolved before launch; target `ace-appworld/experiments/outputs/` for this comparison. The historical runner instead sets `APPWORLD_ROOT="."` and writes relative to its AppWorld working directory, so prove that the adapted runner and official evaluator resolve the **same** intended root before accepting outputs. Give each of the 12 run instances a distinct `<run_base>` (for example, `reme_<dataset>_<arm>_r01_qwen3.8-flash`). With `num_trials=1`, the pinned agent passes `<run_base>_run_0` to AppWorld; **that full value is `<experiment_name>` below and must also be passed to the official evaluator**. Do not let the historical four-run loop reuse one name and overwrite task directories. Run each arm/dataset exactly once, retaining repetition index 1 (`r01`) for output compatibility.

```text
ace-appworld/experiments/outputs/<experiment_name>/
├── run_manifest.json                         # dataset order, arm, repetition, source/model/pool hashes
├── baseline_artifacts/reme/
│   ├── initialization_lm_calls.jsonl          # planned run-scoped pool-import provider calls
│   ├── memory_initial.jsonl                   # planned starting pool snapshot
│   ├── memory_final.jsonl                     # planned final pool snapshot
│   └── <task_id>/
│       ├── memory_events.jsonl                # planned retrieval/add/record/delete events and IDs
│       └── task_audit.json                    # planned order, reward, DB/memory hashes, completion status
├── tasks/<task_id>/
│   ├── checkpoints/
│   ├── dbs/                                    # AppWorld's per-app JSONL dumps and model_hashes.json
│   ├── evaluation/{report.md,version.txt}     # official assertion-level report
│   ├── logs/{api_calls.jsonl,environment_io.md,lm_calls.jsonl,loggger.log}
│   ├── misc/cost.txt                           # task cost or explicit unavailable reason
│   └── version/{code.txt,data.txt}
└── evaluations/<dataset_name>.{json,txt}      # official dataset aggregate
```

The pinned `./exp_result/<model_name>/<dataset>_<suffix>.jsonl` is a secondary ReMe trajectory/score artifact, **not** a replacement for the AppWorld tree. Retain its original fields in an isolated run artifact if useful, but do not append all repetitions to one file without run identity. Validate the required per-task files and DB dump formats against `ace-appworld/TASKLOADER_AND_EVALUATOR_AND_OUTPUT_README.md`. Record service collection snapshots and mutation events outside `tasks/<task_id>/dbs/`.

## 7. Readiness gates

1. Materialize the `2f37a15` source, prompt, `reme2` service flow, and bundled JSONL with the approved `qwen3.8-flash` chat-model and `batch_size=1` overrides in the isolated worktree. Verify the pool's SHA-256 and 207 unique records. Diff compatibility shims against the commit and document them. Fail closed if `qwen3.8-flash` or the pinned `text-embedding-v4` service model is unavailable; make no further silent substitution.
2. Verify all four test dataset hashes, task counts, and AppWorld loader order. Preflight each test task without passing ground truth to the solver. Do not claim subset-train provenance for the bundled pool; inspect and report any demonstrable exact task overlap if provenance can be established, without filtering or changing the approved pool.
3. Smoke-test `POST /load_memory` against the pinned `reme2` service: correct server-side path, `clear_existing=true`, 207 imported IDs, searchable `when_to_use` embeddings, and no stale collection entries. Separately prove a cold-start collection is empty. Require identical imported IDs/content before every fixed and dynamic run, regardless of dataset.
4. On a small registered test fixture, show that fixed disables explicit add/delete, while dynamic and cold start call identical retrieval, scoring, summary, addition, utility, and deletion paths. Verify success-only insertion, failed-task metadata/deletion behavior, and the strict `0.5` deletion boundary.
5. Prove output and collection isolation for all 12 run identities; record memory initialization, initial/final pool hashes, retrieved/added/deleted IDs, resolved provider/service model IDs, usage, and concurrency timestamps. Check for cross-arm, cross-run, and cross-dataset contamination. Verify one-task-at-a-time order through a successful memory commit before the next retrieval.
6. Before a scored run, instrument and parity-test the pinned executor and `reme2` service so the shared logger captures every physical executor, memory-chat, and embedding provider attempt under the correct task or run identity. Prove that AppWorld output DBs, app API/environment logs, ReMe memory-event ledgers, per-task official reports, `misc/cost.txt`, and aggregate `evaluations/<dataset_name>.json|txt` exist in the target root. Verify no overwritten task directory across repetitions, no missing model calls, and no change to the agent's reward/update timing. Fail on infrastructure errors rather than counting them as benchmark failures.
7. Estimate cost and time from smoke runs for 702 test attempts, repeated vector imports, and test-time memory-service calls. Obtain explicit budget approval before formal launch; `8h` and `quick2h` are sampling labels, not wall-time estimates. If a source/config/compatibility gate fails, stop and report it.

This document is an execution plan, not authorization to launch provider-backed runs.

## 8. Formal execution and analysis

For each test dataset and arm, perform one independently initialized run under the locked evaluation configuration. Fixed and dynamic each load the approved bundled pool before their run; cold start begins with an empty collection. Arm order is operational only because memory and outputs are reset and isolated between runs. Archive source/service revisions, all four test dataset hashes, bundled-pool checksum and import audit, ordered task IDs, resolved models, memory initialization proof, task-level timestamps and experience events, provider usage/cost, official reports, aggregate scores, and final pool checksums.

Report each arm × dataset separately: the single run's strict TGC and SGC, per-task outcomes, retrieval/addition/deletion counts, cost, runtime, and anomalies. With one run per cell, do not report across-run mean/spread or claim replication-based uncertainty. Fixed versus dynamic estimates the effect of enabling refinement from the pretrained pool. Dynamic versus cold start estimates the effect of that initial pool with the **same** update workflow. Audit and report whether each run actually preserved file-order, no-future-task memory causality; do not claim it for a run with failed task or memory-service calls. Archive ignored experiment outputs and checksums before cleanup.

Final acceptance requires the verified bundled-pool imports, all 12 isolated test run instances and their official aggregate files, verified initialization/reset evidence, a completed source/service/endpoint/concurrency audit, and an explicit record of every deviation or missing result.
