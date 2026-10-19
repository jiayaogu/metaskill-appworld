# Failure Modes Skill

This document defines a reusable failure-mode annotation procedure for AppWorld-style
baseline outputs. It is intended for ACE and for any other method that follows the
same per-task output structure:

```text
experiments/outputs/<experiment_name>/tasks/<task_id>/
├── checkpoints/
├── dbs/
├── evaluation/
│   ├── report.md
│   └── version.txt
├── logs/
│   ├── api_calls.jsonl
│   ├── environment_io.md
│   ├── lm_calls.jsonl
│   └── loggger.log
├── misc/
│   └── cost.txt
└── version/
    ├── code.txt
    └── data.txt
```

The goal is to assign failed tasks to the memory-design failure space:

```text
{M, I, A, P, U}
```

where:

- `M`: memory representation failure
- `I`: incorrect memory retrieval
- `A`: retrieved memory not converted into a task-specific procedure
- `P`: memory proposal failure
- `U`: memory update failure

The procedure below is evidence-driven. Do not assign labels from task success/failure
alone. Official assertions identify the failure predicate, but failure modes require
additional evidence from execution logs, LLM calls, and memory/update artifacts.

## 1. Definitions

### M: Memory representation failure

Use `M` when the needed experience cannot be represented by the current memory schema,
granularity, scope, or indexable structure.

Strict criteria:

- The failure is not just cold start.
- The failure is not just empty memory.
- The failure is not just failed retrieval.
- The evidence shows that the correct lesson would require a memory structure that the
  system cannot express.

Typical evidence:

- The assertion failure requires a structured condition that cannot be encoded in the
  available memory format.
- The trajectory contains the relevant evidence, but the memory schema has no way to
  represent the necessary scope, index, or dependency.
- Repeated downstream failures occur even though the system sees the evidence and tries
  to store it, but the representation is structurally inadequate.

Do not label `M` merely because the memory is empty at the first task in a family.
Cold-start absence is not a representation failure.

### I: Incorrect memory retrieval

Use `I` when the correct memory already exists in the memory store before task `n`, but
does not enter the retrieved subset or prompt context used for task `n`.

Strict criteria:

- The relevant memory exists in `m_{n-1}` before the task begins.
- The current task fails.
- The relevant memory is absent from the retrieved set, prompt context, or memory IDs
  used by the agent for the failed task.

Typical evidence:

- A memory item or playbook rule exists before the task.
- The task's `lm_calls.jsonl` prompt does not contain the relevant rule.
- For methods that explicitly log retrieval, the task has empty or incomplete retrieval
  output, e.g. ReMe `memory-pre.json` has `retrieved_ids=[]`, ReMe `searches.jsonl`
  has `selected_ids=[]`, or ReasoningBank summaries have missing
  `retrieved_memory_ids`, even though the memory store contains the correct item.

Do not label `I` if the memory was never written. If the store is empty because earlier
failed tasks did not produce accepted memory, the root cause is usually `P` or `U`, not
retrieval.

### A: Retrieved memory not converted into task-specific procedure

Use `A` when the correct memory exists and is visible to the agent, but the final plan,
code, tool calls, or database updates do not instantiate it correctly for the task.

Strict criteria:

- The relevant rule or memory is present in the prompt, playbook, retrieved memory, or
  other task context.
- The task still fails.
- The execution trace shows an incorrect or incomplete procedure.

Typical evidence:

- `lm_calls.jsonl` contains the relevant memory or playbook rule in the prompt.
- The model response does not apply the rule, applies only part of it, or composes it
  incorrectly.
- `environment_io.md` shows wrong API calls, missing filters, missing updates, wrong
  parameters, or incomplete database changes.
- `api_calls.jsonl` confirms that the intended endpoint was not called, or was called
  with incorrect parameters.
- `evaluation/report.md` fails on the specific expected state change or answer.

This is the main label for "the system knew the right thing but did not execute the
right task-specific procedure."

### P: Memory proposal failure

Use `P` when failure evidence exists, but the learning/proposal mechanism does not
identify the correct lesson to store.

Strict criteria:

- The task failed.
- `evaluation/report.md`, `environment_io.md`, or `api_calls.jsonl` contains enough
  evidence to infer the corrective lesson.
- The method does not propose the correct lesson, or proposes an irrelevant/wrong
  diagnosis.

Typical evidence:

- The failed assertion clearly points to the missing condition.
- The reflector/analyzer/curator output misses the causal failure.
- A new memory item is proposed, but it does not correspond to the actual assertion
  failure.
- A first variant in a family fails before useful family memory exists, and the method
  fails to extract a useful lesson from that evidence.

`P` answers the question: "Did the system learn the right lesson from the evidence?"

### U: Memory update failure

Use `U` when the useful lesson should be written into memory, but the update does not
happen correctly, or the written memory harms later tasks.

Strict criteria:

- A useful lesson is available, proposed, or expected from the failure evidence.
- The memory update is missing, malformed, misplaced, over-general, or harmful.

Typical evidence:

- The curator/update operation is empty, e.g. `operations: []`, after a failed task.
- The updated memory file does not change after a failed task.
- The proposed lesson is correct but is not written to the memory store.
- The memory is written in the wrong section or with the wrong scope.
- A later task fails because a previous update was too broad or misleading.
- A success-only update policy prevents failed trajectories from producing memory, so
  later tasks retrieve nothing.

`U` answers the question: "Was the memory actually updated correctly?"

## 2. Evidence Sources

Use the following files for annotation. Do not rely on a single file unless the failure
mode is unambiguous.

### Official evaluation report

Path:

```text
tasks/<task_id>/evaluation/report.md
```

Use it to answer:

- Did the task fail?
- Which assertions failed?
- What state, answer, or model change was expected?
- What was actually produced?

This is the primary source of failure evidence. It gives the failed predicate, not the
root cause.

### Aggregate evaluation outputs

Paths:

```text
evaluations/<dataset>.json
evaluations/<dataset>.txt
```

Use them to answer:

- Which tasks failed?
- What are TGC and SGC?
- Which tasks need failure-mode annotation?

TGC is a task-level success rate. SGC is a family-level all-or-nothing success rate.
Failure-mode counts should be over failed tasks, not over successful tasks.

### LLM call log

Path:

```text
tasks/<task_id>/logs/lm_calls.jsonl
```

Use it to answer:

- What prompt/messages did the model see?
- Which memory/playbook/retrieved rules were visible?
- What did the model propose or plan?
- Did the model produce a correct or incorrect lesson?
- Did the model call update/curation logic?

Each line is one LLM call. The model output is:

```text
output.choices[*].message.content
```

This file is critical for distinguishing `I`, `A`, `P`, and `U`.

### Environment trace

Path:

```text
tasks/<task_id>/logs/environment_io.md
```

Use it to answer:

- What code did the agent execute?
- What did the environment return?
- Did the agent execute the intended procedure?
- Did it call the right API with the right filters and parameters?

This file is especially important for `A`.

### API call log

Path:

```text
tasks/<task_id>/logs/api_calls.jsonl
```

Use it to answer:

- Which AppWorld API endpoints were called?
- Were required app actions performed?
- Were calls missing, repeated, or incorrectly parameterized?

This file helps verify the executed procedure and supports `A` labels.

### Final database state

Path:

```text
tasks/<task_id>/dbs/
```

Use it to answer:

- What final state did the task produce?
- Are expected database changes present?
- Are extra or wrong records present?

The evaluator uses this state to compute assertions. It is supporting evidence, not a
standalone failure-mode label.

### Memory or playbook artifacts

Common paths:

```text
trained_playbook.txt
memory_state.json
memory_events.jsonl
trained_memory_bank.txt
logs/lm_calls.jsonl
run logs
```

Use them to answer:

- Did the relevant memory exist before the failed task?
- Was it retrieved or included in the prompt?
- Did the system propose a new lesson after failure?
- Was the lesson written to memory?
- Did the update later harm future tasks?

These files are essential for `I`, `P`, and `U`.

## 3. Annotation Workflow

### Step 1: Identify failed tasks

Read:

```text
evaluations/<dataset>.json
tasks/<task_id>/evaluation/report.md
```

Only failed tasks receive failure-mode labels. Successful tasks receive no failure-mode
label.

### Step 2: Extract failed assertions

From `evaluation/report.md`, record:

- failed requirement text
- assertion trace
- expected value or expected DB change
- actual value or actual DB state

This defines the failure predicate.

Example:

```text
>> Failed Requirement
assert model changes match venmo.TransactionLike.
```

This says the final task state did not include the expected Venmo transaction-like
changes. It does not yet say why.

### Step 3: Compare intended procedure with actual execution

Read:

```text
logs/lm_calls.jsonl
logs/environment_io.md
logs/api_calls.jsonl
```

Ask:

- Did the model plan the correct procedure?
- Did it execute the correct API calls?
- Did it apply the right filters?
- Did it make the required database changes?

If the correct memory/rule was visible but execution was wrong, label `A`.

### Step 4: Check memory existence and retrieval

Before labeling `I`, prove both:

1. The correct memory existed before the failed task.
2. The failed task did not retrieve or include it.

If memory did not exist, do not label `I`. Move to `P` or `U`.

### Step 5: Check proposal and update

After a failed task, inspect the method's reflection, proposal, curation, or update
artifacts.

Ask:

- Did the system identify the correct lesson? If not, label `P`.
- Did it identify the lesson but fail to write it? If yes, label `U`.
- Did it write a harmful or over-general memory that caused later failure? If yes,
  label `U`.

### Step 6: Use `M` only for representation limits

Use `M` only when the memory representation itself cannot express the needed lesson.

Do not use `M` for:

- first task in a family
- empty memory
- missing update
- failed retrieval
- lack of successful prior experience

Those are usually `P` or `U`.

## 4. Decision Tree

Use this decision tree for each failed task.

```text
Task failed?
  No -> no failure-mode label.
  Yes -> inspect assertion failure.

Did the needed memory already exist before the task?
  Yes:
    Was it retrieved or included in prompt/context?
      No -> I.
      Yes:
        Did the agent instantiate and execute it correctly?
          No -> A.
          Yes -> inspect whether assertion failure comes from representation mismatch or external issue.
  No:
    Did the failure evidence support a useful lesson?
      No -> uncertain / insufficient evidence.
      Yes:
        Did the system propose the correct lesson?
          No -> P.
          Yes:
            Was it written correctly and scoped correctly?
              No -> U.
              Yes:
                Did it later harm future tasks?
                  Yes -> U.
                  No -> uncertain / method-specific issue.

Does the failure require a memory schema that cannot express the needed lesson?
  Yes -> M.
```

When evidence supports multiple labels, either:

- record all supported labels if the table allows non-exclusive counts; or
- record the earliest responsible module in the pipeline if exactly one primary label
  is required.

State which policy is used in the report.

## 5. How Assertions Are Used

Assertions are used to collect failure evidence, not to directly assign module labels.

`evaluation/report.md` answers:

- What failed?
- What should have happened?
- What actually happened?

It does not answer:

- Was memory retrieved?
- Was memory absent?
- Was a rule present but not applied?
- Did the updater fail?

Therefore, assertion evidence must be combined with:

- `lm_calls.jsonl`
- `environment_io.md`
- `api_calls.jsonl`
- memory/playbook artifacts

Example:

The same assertion failure:

```text
assert model changes match venmo.TransactionLike.
```

can imply different labels depending on additional evidence:

- `A`: the rule was visible, but the agent did not call the correct Venmo API.
- `I`: the rule existed in memory but was not retrieved.
- `P`: the previous failure showed the rule, but the system never proposed it.
- `U`: the system proposed the rule but did not write it, or wrote it incorrectly.
- `M`: the required rule cannot be represented by the memory schema.

## 6. Mapping Legacy or Method-Specific Labels

If a method already emits internal labels, map them carefully.

For ACE playbook-style labels:

```text
Playbook Rewrite failure -> P
Playbook Retrieval incorrectness -> I
Retrieved rule did not convert into task-specific procedure -> A
Playbook was not updated -> U
Playbook update harmed future tasks -> U
```

This mapping is heuristic. Always preserve the evidence used for the mapping.

For methods with explicit retrieval IDs:

```text
retrieved_ids=[] / selected_ids=[] / missing retrieved_memory_ids
  and memory store contains correct memory -> I

retrieved_ids=[] / selected_ids=[] / missing retrieved_memory_ids
  and memory store is empty -> not I; usually P or U
```

For success-only update methods:

```text
failed task -> no memory written -> later retrieval empty
```

This should usually be counted as `U`, not `I`, because the later failure is caused by
missing update/acquisition, not incorrect retrieval.

## 7. Quick2h-Style Heuristic

When a completed run does not emit human failure labels and memory evidence is limited,
the quick2h reports use an explicit task-order heuristic over family variants.

For each failed task:

```text
first variant in a family fails -> P
later variant fails after an earlier same-family success -> A
later variant fails after an earlier same-family failure -> U
```

Under this heuristic:

- `M` is not assigned unless there is direct representation evidence.
- `I` is not assigned unless there is proof that correct memory existed and was not
  retrieved.

This heuristic is weaker than full evidence tracing, but it is reproducible and avoids
pretending that unavailable retrieval/update evidence exists.

## 8. Required Annotation Record

For each failed task, record:

```text
dataset:
task_id:
family_id:
variant_index:
model:
method:
success: false
failed_assertions:
evidence_files:
  - evaluation/report.md
  - logs/lm_calls.jsonl
  - logs/environment_io.md
  - logs/api_calls.jsonl
  - memory/playbook artifact if available
assigned_failure_modes:
primary_failure_mode:
rationale:
```

The rationale should explain:

- which assertion failed;
- what the agent actually did;
- what memory was present or absent;
- whether the memory was retrieved;
- whether the agent used it correctly;
- whether the method proposed or wrote the correct update.

## 9. Evidence Quality Levels

Use evidence quality levels when reporting uncertainty.

### Strong evidence

Use when logs directly support the label.

Examples:

- Memory item exists before task but is absent from retrieved IDs -> strong `I`.
- Correct rule visible in prompt, wrong API call in environment trace -> strong `A`.
- Correct lesson proposed, no memory update written -> strong `U`.

### Medium evidence

Use when evidence is indirect but consistent.

Examples:

- First variant failure with clear assertion evidence but no updater trace -> medium `P`.
- Later variant failure after prior same-family success -> medium `A`.

### Weak evidence

Use when assigning labels by heuristic only.

Examples:

- Family-order heuristic without direct memory trace.
- Missing logs but clear aggregate failure.

Reports should state when counts are heuristic.

## 10. Common Mistakes

### Mistake: treating cold start as M

Empty memory on a first task is not `M`. It is simply no prior experience. If the failed
task provides evidence that should be learned but no useful update happens, use `P` or
`U`.

### Mistake: treating empty retrieval as I

Empty retrieval is `I` only if the correct memory exists. If the memory store is empty
because no update happened, use `P` or `U`.

### Mistake: assigning A from assertions alone

An assertion failure proves the task failed, not that a retrieved memory was misapplied.
Use `A` only when the relevant memory/rule was visible to the agent.

### Mistake: ignoring update evidence

If a task fails and later tasks fail similarly, check whether the method wrote any memory
after the first failure. If not, the root cause is often `U`.

### Mistake: using TGC as failure count

TGC is success rate. Failed tasks are:

```text
task_count - successful_tasks
```

SGC is family-level all-or-nothing and cannot be converted directly into task failure
counts.

## 11. Minimal Report Text

When documenting a failure-mode table, include a short methods note:

```text
Failure-mode labels are assigned only to failed tasks. Official AppWorld assertions in
evaluation/report.md identify the failure predicate. Module labels are assigned by
cross-checking assertion failures against LLM call logs, environment traces, API calls,
final DB state, and memory/update artifacts. Counts may be non-exclusive when multiple
modules are supported by evidence; otherwise the primary label is the earliest
responsible module in the memory pipeline.
```

For heuristic quick2h-style labels, add:

```text
These runs do not emit built-in human failure labels. The table uses a task-order
heuristic over family variants: first-variant failures are counted as P; later failures
after a prior same-family success are counted as A; later failures after an earlier
same-family failure are counted as U. M and I require direct evidence and are not
assigned by this heuristic.
```
