# Reusable memory-pressure screening test

Use this rubric to score an AppWorld **scenario family** (all three task
variants with the same ID prefix) for test-time memory adaptation. It is the
screening test used for the conditioned quick2h sample. It is separate from
the AppWorld task evaluator: evaluator requirements are evidence for the
screen, not the screening rule itself.

## Allowed evidence and procedure

1. Read all three task instructions in `data/tasks/<family>_{1,2,3}/specs.json`.
2. Inspect intrinsic API requirements, cross-variant structure, and the
   conditions in each variant's `ground_truth/evaluation.py`. Inspect
   trajectories or reference solutions only when legitimately available.
3. Do **not** use whether ACE, ReasoningBank, PolySkill, ReMe, or another
   baseline succeeded or failed.
4. Score each dimension **exactly 0, 1, or 2**. For every score, record one
   short, concrete observation from the family and a one-sentence
   justification. Difficulty alone is never evidence for a positive score.

## Scoring tests

### M — Memory-structure stress

- **0:** No meaningful reusable procedure across variants, or variants are
  essentially identical.
- **1:** Variants share a reusable procedure but differ in at least one
  task-specific binding, entity, condition, threshold, or object set.
- **2:** Score 1 holds, and blindly transferring variant-specific information
  to another variant could cause an error. The family requires separating
  reusable invariants from scoped information.

### I — Retrieval stress

- **0:** The task requires only one obvious reusable procedure and has no
  meaningful competing memories.
- **1:** Solving the task requires multiple relevant reusable rules **or**
  there are plausible but inapplicable distractor rules.
- **2:** Multiple relevant rules must be retrieved jointly **and** plausible
  distractors exist; missing or incorrectly retrieving one component would
  change the correct procedure.

### A — Adaptation stress

- **0:** A retrieved generic rule can be executed almost directly.
- **1:** Correct execution requires at least one non-trivial task-specific
  binding, filtering step, entity resolution, or ordered action.
- **2:** Correct execution requires composition of at least two non-trivial
  operations, such as multiple predicates, set intersection or difference,
  aggregation, multi-step dependencies, an output contract, or explicit
  postcondition checking.

### P — Evidence-sampling stress

- **0:** Failure feedback is only binary or ambiguous and does not expose a
  useful diagnosis.
- **1:** Evaluator or trajectory evidence can localize a failure and support
  a reusable lesson.
- **2:** Feedback identifies a diagnosable root cause, but the trajectory
  also contains plausible competing explanations. Learning requires selecting
  the causal evidence instead of an irrelevant event.

For P, check the feedback the intended memory learner can actually access.
An answer-only evaluator with only an answer-match and a no-model-change
check usually supports **P=0**. Separate evaluator requirements can support
**P=1** if the learner receives them. Do not award **P=2** merely because a
task is complicated; identify a real trajectory with competing explanations.

### U — Memory-update stress

- **0:** Earlier variants provide little or no reusable information for later
  variants.
- **1:** At least one lesson from an earlier variant should transfer to a
  later variant.
- **2:** The family contains both information that **should** transfer and
  variant-specific information that **should not** transfer. It tests useful
  updates and over-generalization or negative transfer.

## Decision and ranking

```python
scores = {"M": z_M, "I": z_I, "A": z_A, "P": z_P, "U": z_U}
candidate = all(1 <= score <= 2 for score in scores.values())
strong_dimensions = sum(score == 2 for score in scores.values())
total_pressure = sum(scores.values())
# Among candidates, rank by strong_dimensions, then total_pressure.
```

Keep scores for **rejected** families too. A failed dimension is diagnostic
information, not a reason to omit the family from the score record. Do not
infer that eligibility proves statistical representativeness: sampling
distribution and memory-pressure eligibility are separate checks.

## Score-record fields

Use the same shape as
[`quick2h_conditioal/scores.yaml`](quick2h_conditioal/scores.yaml):

```yaml
family_id:
  M: {score: 2, evidence: "Observed variant difference.", justification: "Why this tests M."}
  I: {score: 1, evidence: "Observed relevant rules.", justification: "Why this tests I."}
  A: {score: 2, evidence: "Observed operations.", justification: "Why this tests A."}
  P: {score: 0, evidence: "Only answer-match feedback.", justification: "Why this cannot diagnose a failure."}
  U: {score: 2, evidence: "Transferable rule and scoped value.", justification: "Why both update and negative transfer are testable."}
```
