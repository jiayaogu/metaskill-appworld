# Task Loader and Evaluator README

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
