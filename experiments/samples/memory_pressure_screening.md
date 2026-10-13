# Reusable AppWorld scenario sampling criteria

Use the distribution criteria below for the ordinary quick2h sample. For a
conditioned sample, first apply the memory-pressure screen later in this
document, then apply the **same distribution criteria** to its eligible
families. An AppWorld **scenario family** consists of all three tasks with the
same ID prefix. The screen is separate from the AppWorld task evaluator:
evaluator requirements are evidence for scoring, not the screening rule itself.

## Total-variation-preserving sampling criteria

The distance is **total variation** (TV), sometimes called total variation
distance; it is not statistical *total variance*. Let `F_train`, `F_normal`,
and `F_challenge` be the complete source sets, and `S_d` a selected subset of
`F_d`. Always compare a sample to **its own** source split when measuring
within-split fidelity. Compare sampled train with sampled test when measuring
whether the original train-to-test difference survives.

### Unit, budget, and candidate pool

1. Sample complete families without replacement; include `_1`, `_2`, and
   `_3` for every selected ID. Validate that each ID belongs to exactly one
   intended source split and that all three tasks exist.
2. Choose scenario counts before selection. With three tasks per family, the
   estimated task time is `3 * (n_train + n_normal + n_challenge) * minutes_per_task`.
   Leave room for setup and variance in task time. The quick2h setting uses
   five families per split: 45 tasks, about 99 minutes at 2.2 minutes/task.
3. For ordinary quick2h, the candidate pool is each complete source split.
   For conditioned quick2h, the candidate pool contains only families passing
   all five M/I/A/P/U tests below; the **reference distribution remains the
   complete source split**. Report when screening makes a target feature
   unavailable rather than silently changing the reference.

### Fixed content representation and TV

Use the same categories and tagging rules for source and sample. For the
quick2h topic representation, use Amazon, Gmail, Todoist, Splitwise, Spotify,
Venmo, Simple Note, Phone, File system, and Other. Tag explicit app mentions;
also tag phone/text/voice-message and file-system/`~/` references. Give an
instruction with no matched tag `Other`. If variant `v` in family `s` has tags
`T[s,v]`, give each of its tags weight `1 / (3 * len(T[s,v]))`. Thus each
family has total weight one, even when a task has multiple topics. For any
family set `G`, average family weights to obtain `p_G[k]`. Calculate

```text
p_G[k] = (1 / |G|) * sum_s_in_G (1 / 3) * sum_v=1..3 1[k in T[s,v]] / |T[s,v]|
TV(P, Q) = (1 / 2) * sum_k |P[k] - Q[k]|
```

TV is between 0 and 1. Zero means equal probability on these *measured*
categories; one means disjoint support. Neither value proves equality or
difference of the complete semantic task distributions. Use unrounded vectors
for calculations and round only for display.

Also form scenario-weighted categorical distributions of `difficulty` and
`num_apps` from each variant's `data/tasks/<id>/ground_truth/metadata.json`;
each variant contributes one-third of its family's weight. For test novelty,
concatenate each family's three instructions, represent the full source corpus
with TF-IDF word unigrams/bigrams (English stop words, sublinear term
frequency), and compute each test family's maximum cosine similarity to a
**full-train** family. Freeze the vectorizer and the full test split's 25th
and 75th percentile cutoffs before selecting samples. Bin test families into
low, middle, and high similarity; compare the sample and full split's bin
proportions by TV. Use the same preprocessing for every candidate and report
the exact settings or code when creating a new sample.

### Selection and acceptance checks

Search feasible family subsets jointly across the three splits. For each
candidate, calculate topic, difficulty, app-count, and (for tests) novelty-bin
TV to the candidate's own full source split. Also calculate the
**train-to-test TV gap**: for `t` in `{normal, challenge}`, compute

```text
source_shift[t] = TV(p_F_train, p_F_t)
sample_shift[t] = TV(p_S_train, p_S_t)
shift_error[t]  = |sample_shift[t] - source_shift[t]|
```

For a reproducible **new** selection, rank feasible joint subsets
lexicographically by the following tuple (smaller is better):

```text
primary = [topic_TV_to_source[d] for d in splits] + [shift_error[t] for t in tests]
auxiliary = [difficulty_TV[d] for d in splits]
          + [app_count_TV[d] for d in splits]
          + [novelty_bin_TV[t] for t in tests]
rank = (max(primary), sum(primary), max(auxiliary), sum(auxiliary))
```

Here the `auxiliary` line denotes the concatenation of the difficulty,
app-count, and novelty-bin TV lists. Retain the original train/test ordering
when feasible (here, challenge is farther from train than normal). This is a
**joint** check: small sample-to-source TVs separately do not guarantee
matching train-to-test TVs. Keep examples of test-only content that the full
train set lacks, when the eligible pool permits it. For the current source
splits, that includes Todoist or Splitwise in normal and Amazon or Gmail in
challenge. Record the full-set and sample prevalence of the union of these
unseen apps; these incidence counts are separate from normalized topic
probabilities. Apply the optional memory-pressure ranking only after the
distribution ranking, so it does not erase the measured split contrast.

There is no universal TV cutoff that proves representativeness with five
families. Record the best feasible candidate found, the search method or
seed, and **all** measured TVs. When the conditioned pool cannot reproduce a
source feature, state the remaining mismatch. Do not call a deliberately
balanced five-family sample a probability sample or use it to estimate
full-split success rates.

The existing quick2h sample has topic TV to its source of 0.0833 (train),
0.1131 (normal), and 0.1448 (challenge). Its train-to-normal and
train-to-challenge topic TVs are 0.4000 and 0.7333, versus 0.3476 and 0.6595
in the complete data. These are **example outcomes**, not required thresholds.
See [quick2h_sampling.md](../quick2h_sampling.md) for its manifests and full
metric table.

## Conditional memory-pressure screen

### Allowed evidence and procedure

1. Read all three task instructions in `data/tasks/<family>_{1,2,3}/specs.json`.
2. Inspect intrinsic API requirements, cross-variant structure, and the
   conditions in each variant's `ground_truth/evaluation.py`. Inspect
   trajectories or reference solutions only when legitimately available.
3. Do **not** use whether ACE, ReasoningBank, PolySkill, ReMe, or another
   baseline succeeded or failed.
4. Score each dimension **exactly 0, 1, or 2**. For every score, record one
   short, concrete observation from the family and a one-sentence
   justification. Difficulty alone is never evidence for a positive score.

### Scoring tests

#### M — Memory-structure stress

- **0:** No meaningful reusable procedure across variants, or variants are
  essentially identical.
- **1:** Variants share a reusable procedure but differ in at least one
  task-specific binding, entity, condition, threshold, or object set.
- **2:** Score 1 holds, and blindly transferring variant-specific information
  to another variant could cause an error. The family requires separating
  reusable invariants from scoped information.

#### I — Retrieval stress

- **0:** The task requires only one obvious reusable procedure and has no
  meaningful competing memories.
- **1:** Solving the task requires multiple relevant reusable rules **or**
  there are plausible but inapplicable distractor rules.
- **2:** Multiple relevant rules must be retrieved jointly **and** plausible
  distractors exist; missing or incorrectly retrieving one component would
  change the correct procedure.

#### A — Adaptation stress

- **0:** A retrieved generic rule can be executed almost directly.
- **1:** Correct execution requires at least one non-trivial task-specific
  binding, filtering step, entity resolution, or ordered action.
- **2:** Correct execution requires composition of at least two non-trivial
  operations, such as multiple predicates, set intersection or difference,
  aggregation, multi-step dependencies, an output contract, or explicit
  postcondition checking.

#### P — Evidence-sampling stress

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

#### U — Memory-update stress

- **0:** Earlier variants provide little or no reusable information for later
  variants.
- **1:** At least one lesson from an earlier variant should transfer to a
  later variant.
- **2:** The family contains both information that **should** transfer and
  variant-specific information that **should not** transfer. It tests useful
  updates and over-generalization or negative transfer.

### Decision and ranking

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

### Score-record fields

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

## Reuse record for each new sample

Save three split manifests with full task IDs and a short audit beside them:

| Item | Record |
| --- | --- |
| Design | Ordinary or conditioned; source manifests; candidate counts; selected family IDs; budget estimate; search method and seed |
| Eligibility | M/I/A/P/U evidence cards for reviewed families when conditioned; eligible count per split; unavailable source features |
| Within-split fidelity | For each split: `TV(topic sample, topic source)`, difficulty TV, app-count TV, and test novelty-bin TV |
| Retained train/test shift | Full and sample train→normal and train→challenge topic TVs, their absolute errors, and whether their ordering agrees |
| Test-only content | Full and sample counts for apps absent from train, plus which such app types are covered |

Keep these two TV questions separate in both the audit and any plots or tables.
The first checks resemblance to each split; the second checks whether the
train/test content shift has been retained. The [LaTeX summary
table](../quick2h_topic_distribution.tex) shows both for the existing two
samples.
