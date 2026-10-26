# Two-hour AppWorld conditional sample: quick2h_conditional

The reusable TV-preserving selection and memory-pressure screening criteria
are in [memory_pressure_screening.md](samples/memory_pressure_screening.md).

## Motivation and conditioning target

This sample is separate from [quick2h_sampling.md](quick2h_sampling.md). A scenario
family is the three tasks with the same ID prefix. The purpose is a fast
method-debugging run that covers each source split's task content while requiring
every selected family to exercise test-time memory adaptation.

The full splits have distinct content distributions. The table counts a family
if any of its three instructions explicitly names the app; rows overlap.

| App in instructions | Train (30) | Test normal (56) | Test challenge (139) |
| --- | ---: | ---: | ---: |
| Spotify | 16 (53.3%) | 14 (25.0%) | 14 (10.1%) |
| Venmo | 7 (23.3%) | 23 (41.1%) | 14 (10.1%) |
| Simple Note | 4 (13.3%) | 14 (25.0%) | 7 (5.0%) |
| Amazon | 0 | 0 | 74 (53.2%) |
| Gmail | 0 | 0 | 19 (13.7%) |
| Todoist | 0 | 3 (5.4%) | 1 (0.7%) |
| Splitwise | 0 | 4 (7.1%) | 2 (1.4%) |
| **Any Amazon/Gmail/Todoist/Splitwise** | **0** | **7 (12.5%)** | **94 (67.6%)** |

Thus normal test already contains app content absent from train (for example
Splitwise), and challenge has much more unseen app content (especially Amazon
and Gmail). On the ten-topic instruction representation defined below, the
**full train-to-normal distance is 0.348** and **full train-to-challenge distance
is 0.659**. These are total variation (TV) distances, so 0 means identical
topic mixes and 1 means disjoint mixes. They quantify the content shift, not
whether individual tasks are solvable from training.

The conditional target is the original split's content mix **subject to**
`candidate = all(score >= 1 for score in [M, I, A, P, U])`. M is reusable
structure with scoped exceptions; I is retrieval of relevant rules amid
possible distractors; A is task-specific adaptation; P is informative failure
evidence; U is useful updates without negative transfer. Scores are 0, 1 or 2.
Only intrinsic task instructions, evaluator conditions and cross-variant
structure were used. No ACE, ReasoningBank, PolySkill, ReMe or other baseline
outcome was read for selection or scoring.

Eligibility itself may depend on task content, so the eligible-family
distribution need not equal the original split distribution. With five
families per split, the goal is **measured approximation and preservation of
the train/test contrast**, not a claim of identical distributions.

## Selected families

Each source split contributes **five complete families**, or 15 tasks. The
three manifests total **45 tasks**. At the previously observed 2.2 minutes
per task, execution is approximately **99 minutes**, leaving 21 minutes in a
two-hour budget. This timing is an estimate; these pressure-selected tasks may
take longer.

| Source split | Dataset name | Family IDs | Main content represented |
| --- | --- | --- | --- |
| Train | `quick2h_conditional_train` | `e3d6c94`, `c901732`, `afc0fce`, `7d7fbf6`, `29caf6f` | Spotify selection/playlists, Venmo, file archives, Simple Note + phone |
| Test normal | `quick2h_conditional_test_normal` | `fd1f8fa`, `ccf4b82`, `3b8fb7a`, `f323bae`, `3aa1a22` | Spotify, Venmo, Simple Note, files, unseen Splitwise + phone |
| Test challenge | `quick2h_conditional_test_challenge` | `07bb666`, `b0934aa`, `6d59d90`, `a3ba388`, `321ec38` | unseen Amazon and Gmail, Venmo, files, email + phone |

The reviewable manifests and [per-family M/I/A/P/U evidence card](samples/quick2h_conditioal/scores.yaml)
are under the existing `experiments/samples/quick2h_conditional/` directory
. For every selected
family, the card gives an integer score, a concrete observation across its
three variants or evaluator checks, and a one-sentence reason for each
dimension. Every family has **M=2, I=2, A=2, P=1, U=2**: each is a candidate,
with four strong dimensions and total pressure 9. They tie on the optional
ranking. The ranking is among these reviewed candidates; it is not an
exhaustive ranking of all 225 source families.

P is conservatively 1: the evaluator separates failure conditions, but a
P=2 claim would require observing an actual trajectory with plausible
competing causal explanations. The ACE adaptation runner can pass a detailed
evaluator report, including failed requirements and traces, to its reflector.
If a different test setup exposes only a binary success flag, rerate P for
that setup before interpreting the diagnostic.

## Distribution check

TV below compares each **conditional sample to its own complete source
split**, not train directly to test. For topics, each task instruction receives
tags from explicit app names plus phone and file-system references, or
`Other` when none occur. Multiple tags share one-third of their family's
weight. Difficulty and app count come from intrinsic task metadata. For test
novelty, concatenate each family's three instructions, compute TF-IDF
unigrams/bigrams with English stop words and sublinear term frequency, take
cosine similarity to the closest train family, then bin by the full test
split's 25th/75th percentiles.

### Ten-topic probability vectors

The coordinate order for every vector is
`[Amazon, Gmail, Todoist, Splitwise, Spotify, Venmo, Simple Note, Phone, File system, Other]`.
Each scenario has weight 1; its three task variants each have weight 1/3,
divided equally among the topics tagged in that variant. These are topic
**probabilities**, not counts of scenarios mentioning an app. All entries are
rounded to four decimal places.

```text
conditional train          = [0.0000, 0.0000, 0.0000, 0.0000, 0.4000, 0.2000, 0.1000, 0.1000, 0.2000, 0.0000]
conditional test_normal    = [0.0000, 0.0000, 0.0000, 0.1000, 0.2000, 0.3000, 0.2000, 0.1000, 0.1000, 0.0000]
conditional test_challenge = [0.5000, 0.1000, 0.0000, 0.0000, 0.0000, 0.1000, 0.0000, 0.2000, 0.1000, 0.0000]
```

| Split | Topic TV | Difficulty TV | App-count TV | Novelty-bin TV |
| --- | ---: | ---: | ---: | ---: |
| Train | 0.1000 | 0.0000 | 0.1333 | — |
| Test normal | 0.1131 | 0.1393 | 0.1107 | 0.1500 |
| Test challenge | 0.2233 | 0.0676 | 0.1237 | 0.1036 |

### Does the sample resemble each source split?

The table above measures three independent descriptive features, plus test
novelty. Training difficulty is matched exactly; the normal and challenge
samples are close on difficulty and app count. Topic mix is less exact in
challenge (TV 0.2233), mainly because phone tasks are 20.0% of this tiny
sample's topic weight versus 6.8% of the full split, while Spotify and some
rare topics are absent.

For a more concrete view, the next table gives the share of families whose
instructions explicitly name an app. Each cell is **full split → sample**;
apps can co-occur, so columns do not sum to 100%.

| App | Train | Test normal | Test challenge |
| --- | ---: | ---: | ---: |
| Spotify | 53.3% → 40% | 25.0% → 20% | 10.1% → 0% |
| Venmo | 23.3% → 20% | 41.1% → 40% | 10.1% → 20% |
| Simple Note | 13.3% → 20% | 25.0% → 40% | 5.0% → 0% |
| Amazon | 0% → 0% | 0% → 0% | 53.2% → 60% |
| Gmail | 0% → 0% | 0% → 0% | 13.7% → 20% |
| Todoist | 0% → 0% | 5.4% → 0% | 0.7% → 0% |
| Splitwise | 0% → 0% | 7.1% → 20% | 1.4% → 0% |

For a check beyond app keywords, each family's three instructions were
concatenated and represented by normalized TF-IDF unigrams/bigrams
(English stop words removed, sublinear term frequency). The Euclidean distance
between the sample and full-split text centroids is a **text-content proxy**,
not proof of equal task distributions. As a size-matched reference, 100,000
uniform samples of five families were drawn without replacement from each full
split (seed 20261013). The final two columns say what fraction of those random
samples had a distance **at least as large** as this conditional sample; larger
percentages indicate closer matching than a typical random sample.

| Split | Topic TV | Random median topic TV | Random draws with at least as large topic TV | TF-IDF centroid distance | Random draws with at least as large text distance |
| --- | ---: | ---: | ---: | ---: | ---: |
| Train | 0.1000 | 0.2833 | 98.6% | 0.3948 | 74.2% |
| Test normal | 0.1131 | 0.3399 | 99.6% | 0.4089 | 94.9% |
| Test challenge | 0.2233 | 0.3957 | 99.0% | 0.4227 | 96.0% |

These random-draw comparisons are descriptive benchmarks, **not p-values**:
the sample was deliberately selected to match the splits, and the benchmark
does not enforce memory-pressure eligibility. Good centroid agreement also
does not guarantee coverage of rare task types.

### Is the original train/test difference retained?

| Pair | Full-split topic TV | Conditional-sample topic TV | Change |
| --- | ---: | ---: | ---: |
| Train → test normal | 0.3476 | 0.3000 | -0.0476 |
| Train → test challenge | 0.6595 | 0.7000 | +0.0405 |

The large ordering survives: challenge remains much further from train than
normal does. The sample's distances are within about 0.05 TV of the full-split
distances on this topic representation. Explicitly new app content also
survives: Amazon, Gmail, Todoist or Splitwise occurs in **0/5 train**,
**1/5 normal** (full split: 7/56), and **4/5 challenge** families (full split:
94/139). In particular, the normal sample contains Splitwise and the
challenge sample contains Amazon and Gmail.

This establishes preservation of the **measured coarse content shift**, not
that five families per split are statistically interchangeable with the full
splits. The challenge topic TV of 0.2233 and missing rare app topics are
material limits. Use these 45 tasks for fast method checks; use the full
splits or a substantially larger probability sample to estimate population
success rates.

## Use

Copies of the manifests are installed as
`data/datasets/quick2h_conditional_{train,test_normal,test_challenge}.txt`.
That data directory is ignored by Git. If regenerated, restore the dataset
files from the AppWorld project directory:

```bash
for split in train test_normal test_challenge; do
    cp "experiments/samples/quick2h_conditioal/${split}.txt" "data/datasets/quick2h_conditional_${split}.txt"
done
```

Existing conditional test configs in
`experiments/configs/ACE_18_task_online_no_GT_pilot/quick2h_conditional_test_normal/`
and `quick2h_conditional_test_challenge/` list the 15 task IDs directly;
all eight configs in each directory match the corresponding manifest. For a
config that loads by dataset name, use the names in the table above. Keep all
three variants of each family; AppWorld scenario completion aggregates over
those three tasks. Do not use the runner's `sample_size` here, because it
takes the first N manifest entries and changes the planned content mix.
