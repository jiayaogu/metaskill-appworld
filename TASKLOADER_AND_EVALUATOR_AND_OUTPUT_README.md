# Output Layout (MUST FOLLOW)

Every downstream baseline must write one task output directory per executed AppWorld task using the same layout as ACE/AppWorld. Do not only save an aggregate summary, and do not replace the AppWorld output layout with a custom trace format.

The required per-task output root is:

```text
ace-appworld/experiments/outputs/<experiment_name>/tasks/<task_id>/
```

Each executed task must follow this layout:

```text
<experiment_name>/tasks/<task_id>/
├── checkpoints
├── dbs
│   ├── admin.jsonl
│   ├── amazon.jsonl
│   ├── api_docs.jsonl
│   ├── file_system.jsonl
│   ├── gmail.jsonl
│   ├── model_hashes.json
│   ├── phone.jsonl
│   ├── simple_note.jsonl
│   ├── splitwise.jsonl
│   ├── spotify.jsonl
│   ├── supervisor.jsonl
│   ├── todoist.jsonl
│   └── venmo.jsonl
├── evaluation
│   ├── report.md
│   └── version.txt
├── logs
│   ├── api_calls.jsonl
│   ├── environment_io.md
│   ├── lm_calls.jsonl
│   └── loggger.log
├── misc
│   └── cost.txt
└── version
    ├── code.txt
    └── data.txt
```

## Required subdirectories and files

### `checkpoints/`

Stores AppWorld state checkpoints created during execution. The directory must exist for every executed task, even if a baseline does not actively use intermediate checkpoints.

### `dbs/`

Stores the final task output databases after the agent has interacted with the AppWorld environment. The evaluator reads this directory to compare the final task state against ground truth.

Required files:

```text
admin.jsonl
amazon.jsonl
api_docs.jsonl
file_system.jsonl
gmail.jsonl
model_hashes.json
phone.jsonl
simple_note.jsonl
splitwise.jsonl
spotify.jsonl
supervisor.jsonl
todoist.jsonl
venmo.jsonl
```

These files should be produced by running the task through AppWorld APIs, not by manually fabricating the output DB.

DB JSONL item format must follow the AppWorld DB dump format. Each non-empty line in an app DB file is a JSON array emitted by AppWorld, not a custom dict:

```json
[
  "INSERT INTO table_name (...) VALUES (?, ?, ...)",
  ["param_1", "param_2", "..."],
  false
]
```

Meaning:

- item 0: SQL statement string.
- item 1: ordered SQL parameter list.
- item 2: AppWorld DB dump boolean flag. Preserve the value emitted by AppWorld.

`model_hashes.json` is a JSON file, not JSONL, and must be preserved as emitted by AppWorld.

### `evaluation/`

Stores official AppWorld evaluation outputs.

Required files:

```text
evaluation/report.md
evaluation/version.txt
```

`report.md` is produced by the AppWorld evaluator and contains per-assertion pass/fail details. `version.txt` records the AppWorld code version used for evaluation.

The evaluator writes these files when called with `save_report=True`, e.g.:

```python
from appworld.evaluator import evaluate_task

test_tracker, report = evaluate_task(
    task_id="<task_id>",
    experiment_name="<experiment_name>",
    save_report=True,
)
```

`evaluation/report.md` must contain these sections:

```text
Overall Stats
Passes
Fails
```

The required content is:

- `Overall Stats`: `Num Passed Tests`, `Num Failed Tests`, and `Num Total Tests`.
- `Passes`: one `>> Passed Requirement` block per passed assertion, or an empty/none equivalent if there are no passes.
- `Fails`: one `>> Failed Requirement` block per failed assertion, including the failing requirement and traceback/code context, or `None` if there are no failures.

Example of one passed assertion and one failed assertion:

````text
──────────────────────────────────── Passes ────────────────────────────────────
>> Passed Requirement
assert answers match.

──────────────────────────────────── Fails ─────────────────────────────────────
>> Failed Requirement
assert the set of message_ids from removed phone.UserTextMessage or
phone.UserVoiceMessage records matches private_data.to_delete_message_ids
(ignore order).
```python
with test(
    """
    assert the set of message_ids from removed phone.UserTextMessage or
    phone.UserVoiceMessage records matches private_data.to_delete_message_ids
    (ignore order).
    """
):
    removed_message_ids = set_of(removed_messages, "id")
```
----------
AssertionError:  {16812, 16814} == {16816, 16812, 16814}

In right but not left:
[16816]
````

### `logs/`

Stores complete task execution logs.

Required files:

```text
logs/api_calls.jsonl
logs/environment_io.md
logs/lm_calls.jsonl
logs/loggger.log
```

File meanings:

- `api_calls.jsonl`: AppWorld app/API calls made during execution.
- `environment_io.md`: code sent to the AppWorld environment and the environment response.
- `lm_calls.jsonl`: all LLM calls made by the agent during `appworld run`; each line contains the request messages and model response. The evaluator does not create this file.
- `loggger.log`: ACE/AppWorld runtime logger output.

If a task used an LLM, `lm_calls.jsonl` must be present. One task can have many LLM calls, so `lm_calls.jsonl` is a sequence of calls, not a single final output.

#### `logs/api_calls.jsonl` item schema

Every line must be one JSON object with exactly the ACE/AppWorld API-call shape:

```json
{
  "method": "get",
  "url": "/supervisor/account_passwords",
  "data": {}
}
```

Required fields:

- `method`: HTTP-style method string used by the AppWorld API call, e.g. `get`, `post`, `patch`, `delete`.
- `url`: AppWorld API route, e.g. `/supervisor/account_passwords`.
- `data`: JSON object containing request parameters/body. Use `{}` when the call has no parameters.

Do not add a different schema for downstream baselines. `logs/api_calls.jsonl` must be parseable by the same code that parses ACE outputs.

#### `logs/lm_calls.jsonl` item schema

Every line must be one JSON object for one LLM call:

```json
{
  "id": "<call_id>",
  "input": {
    "provider": "openai",
    "model": "gpt-4.1",
    "messages": [],
    "tools": null,
    "temperature": 0,
    "seed": 100,
    "stop": null,
    "logprobs": false,
    "top_logprobs": null,
    "frequency_penalty": 0,
    "presence_penalty": 0,
    "n": 1,
    "response_format": {"type": "text"},
    "completion_method": "chat.completions"
  },
  "output": {
    "choices": [],
    "usage": {},
    "cost": null,
    "id": "<provider_response_id>",
    "model": "<provider_model>",
    "created": 0,
    "object": "chat.completion",
    "service_tier": null,
    "system_fingerprint": null,
    "moderation": null
  }
}
```

Required top-level fields:

- `id`: ACE call ID.
- `input`: request metadata and full prompt/messages.
- `output`: normalized provider response.

Required `input` fields:

- `provider`
- `model`
- `messages`
- `tools`
- `temperature`
- `seed`
- `stop`
- `logprobs`
- `top_logprobs`
- `frequency_penalty`
- `presence_penalty`
- `n`
- `response_format`
- `completion_method`

Required `output` fields:

- `choices`
- `usage`
- `cost`
- `id`
- `model`
- `created`
- `object`
- `service_tier`
- `system_fingerprint`
- `moderation`

Each item in `output.choices` should preserve the normalized provider choice object, including:

```json
{
  "finish_reason": "stop",
  "index": 0,
  "logprobs": null,
  "message": {
    "role": "assistant",
    "content": "<raw assistant text>",
    "refusal": null,
    "annotations": [],
    "audio": null,
    "function_call": null,
    "tool_calls": null
  }
}
```

`output.choices[*].message.content` is the raw assistant text for that LLM call. This is the required place to store model output.

#### `logs/environment_io.md` required sections

`environment_io.md` must contain one section per AppWorld environment interaction:

````markdown
### Environment Interaction 1
----------------------------------------------------------------------------
```python
# code sent to the AppWorld environment
...
```

```
environment output
```
````

Required for each interaction:

- A heading: `### Environment Interaction <N>`.
- The ACE horizontal separator line: `----------------------------------------------------------------------------`.
- A Python fenced code block containing the code executed in the environment.
- A plain fenced code block containing the environment response.

#### `logs/loggger.log`

`loggger.log` is free-form runtime logger output, but the file must exist for each executed task and should include enough runtime messages to diagnose task execution failures.

### `misc/`

Stores task-level miscellaneous metadata.

Required file:

```text
misc/cost.txt
```

`cost.txt` should contain the task-level LLM cost in USD when available. If exact cost cannot be computed, the file should still exist and the baseline report must clearly document why the cost is unavailable.

### `version/`

Stores version metadata for the run.

Required files:

```text
version/code.txt
version/data.txt
```

`code.txt` records the AppWorld code/package version. `data.txt` records the AppWorld data version.

## Minimum compliance checklist

For every executed task, downstream baselines must verify:

- `dbs/` exists and contains the final output DB files.
- `logs/` exists and contains `api_calls.jsonl`, `environment_io.md`, `lm_calls.jsonl`, and `loggger.log`.
- `misc/cost.txt` exists.
- `version/code.txt` and `version/data.txt` exist.
- After evaluation, `evaluation/report.md` and `evaluation/version.txt` exist.
- Aggregate summaries must not replace task-level outputs.


# Task Loader and Evaluator

Use the AppWorld APIs from `ace-appworld` directly. Do not reimplement dataset-file parsing, task loading, or evaluation logic in downstream baselines.

## Task Loader

### Input locations

Dataset split files live under:

```text
ace-appworld/data/datasets/
├── train.txt
├── dev.txt
├── test_normal.txt
├── test_challenge.txt
└── 18_task_online_no_gt_pilot.txt
```

Each split file contains task IDs. The corresponding task inputs live under:

```text
ace-appworld/data/tasks/<task_id>/
├── specs.json
├── dbs/
└── ground_truth/
```

For example:

```text
ace-appworld/data/tasks/07b42fd_1/
```

### Loading script locations

Use the AppWorld loader APIs here:

```text
ace-appworld/src/appworld/task.py
```

The two main APIs are:

```python
from appworld.task import Task, load_task_ids
```

ACE already uses these APIs in:

```text
ace-appworld/experiments/code/ace/run.py
```

The ACE flow is:

```text
read dataset from config
-> load_task_ids(dataset_name)
-> Task.load(task_id=task_id) for sanity checking
-> agent.solve_tasks(task_ids, experiment_name, ...)
```

### Normal steps to load a dataset

Use `load_task_ids()` to load the split. Do not manually read `data/datasets/*.txt`.

`load_task_ids()` is implemented in:

```text
ace-appworld/src/appworld/task.py
```

```python
from appworld.task import Task, load_task_ids

dataset_name = "test_normal"
task_ids = load_task_ids(dataset_name)
```

Then load individual tasks with `Task.load()`:

```python
task = Task.load(
    task_id="07b42fd_1",
    storage_type="memory",
    load_ground_truth=True,
    ground_truth_mode="minimal",
)
```

Minimal dataset-loading template:

```python
from appworld.task import Task, load_task_ids

task_ids = load_task_ids("test_normal")

for task_id in task_ids:
    task = Task.load(task_id=task_id)
    print(task_id, task.instruction)
```

Useful fields on the loaded task:

```python
task.id           # Unique AppWorld task ID, e.g. "07b42fd_1".
task.instruction  # Natural-language task instruction given to the agent.
task.supervisor   # Main user / supervisor profile for the task.
task.allowed_apps # Apps available to the task, excluding admin internals.
task.api_docs     # API documentation collection for the allowed apps.
task.ground_truth # Ground-truth metadata, public/private data, answer, and evaluator.
```

## Evaluator

### Input locations

Evaluation reads the task input and ground truth from:

```text
ace-appworld/data/tasks/<task_id>/
```

It reads the model or agent output database from the experiment output directory:

```text
ace-appworld/experiments/outputs/<experiment_name>/tasks/<task_id>/dbs/
```

The output DBs are created when an agent runs a task through AppWorld, normally via:

```python
from appworld.environment import AppWorld

with AppWorld(task_id="07b42fd_1", experiment_name="your_experiment_name") as world:
    # agent executes tool/code actions through world.execute(...)
    ...
```

### Evaluator script locations

Use the AppWorld evaluator APIs here:

```text
ace-appworld/src/appworld/evaluator.py
```

The main APIs are:

```python
from appworld.evaluator import evaluate_task, evaluate_dataset
```

The AppWorld CLI wraps the same evaluator:

```bash
appworld evaluate <experiment_name> <dataset_name> --root .
```

### Minimal steps to output `report.md`

First, make sure the task has been run and output DBs exist:

```text
ace-appworld/experiments/outputs/<experiment_name>/tasks/<task_id>/dbs/
```

Then evaluate one task:

```python
from appworld.evaluator import evaluate_task

test_tracker, report = evaluate_task(
    task_id="07b42fd_1",
    experiment_name="your_experiment_name",
    save_report=True,
)
```

This writes the task-level report to:

```text
ace-appworld/experiments/outputs/<experiment_name>/tasks/<task_id>/evaluation/report.md
```

To evaluate a full split:

```python
from appworld.evaluator import evaluate_dataset

metrics = evaluate_dataset(
    experiment_name="your_experiment_name",
    dataset_name="test_normal",
    save_reports=True,
)
```

This writes aggregate evaluation files to:

```text
ace-appworld/experiments/outputs/<experiment_name>/evaluations/test_normal.json
ace-appworld/experiments/outputs/<experiment_name>/evaluations/test_normal.txt
```

Equivalent CLI:

```bash
cd ace-appworld
source .venv/bin/activate
export APPWORLD_PROJECT_PATH="$(pwd)"

appworld evaluate your_experiment_name test_normal --root .
```

To evaluate only one task from the CLI:

```bash
appworld evaluate your_experiment_name on_only --task-id 07b42fd_1 --root .
```

### Minimal unified template

```python
from appworld.task import Task, load_task_ids
from appworld.evaluator import evaluate_dataset, evaluate_task

task_ids = load_task_ids("test_normal")

for task_id in task_ids:
    task = Task.load(task_id=task_id)
    print(task_id, task.instruction)

task_tracker, report = evaluate_task(
    task_id=task_ids[0],
    experiment_name="your_experiment_name",
    save_report=True,
)

metrics = evaluate_dataset(
    experiment_name="your_experiment_name",
    dataset_name="test_normal",
    save_reports=True,
)
```
