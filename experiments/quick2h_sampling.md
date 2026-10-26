# Two-hour ACE AppWorld pilot sample

The reusable selection and audit criteria, including the topic TV definition
and train-to-test shift check, are in
[memory_pressure_screening.md](samples/memory_pressure_screening.md).

## Motivation: scenario content differs across splits

The source splits have different task-content mixes. A scenario is the group of
three tasks sharing the same ID prefix. The table counts a scenario when **any**
of its three instructions explicitly names an app. A scenario involving multiple
apps appears in multiple rows, so the rows do not sum to the split size.

| App named in scenario instructions | Train (30 scenarios) | Test normal (56) | Test challenge (139) |
| --- | ---: | ---: | ---: |
| Spotify | 16 (53.3%) | 14 (25.0%) | 14 (10.1%) |
| Venmo | 7 (23.3%) | 23 (41.1%) | 14 (10.1%) |
| Simple Note | 4 (13.3%) | 14 (25.0%) | 7 (5.0%) |
| Amazon | 0 | 0 | 74 (53.2%) |
| Gmail | 0 | 0 | 19 (13.7%) |
| Todoist | 0 | 3 (5.4%) | 1 (0.7%) |
| Splitwise | 0 | 4 (7.1%) | 2 (1.4%) |
| **Any app absent from train above** | **0** | **7 (12.5%)** | **94 (67.6%)** |

The last row is the union of Amazon, Gmail, Todoist, and Splitwise, counted once
per scenario. It is a conservative measure of unseen content: it excludes new
operations within familiar apps and email tasks that do not explicitly say
“Gmail.” For example, normal-test tasks include Todoist reassignment and
Splitwise expense recording; challenge tasks include Amazon orders and Gmail
thread management.

For a numeric content-distribution comparison, each scenario contributes one
unit of weight across its three instructions. Each instruction is tagged by
explicit app names, phone and file-system references, or `Other`; a multi-topic
instruction divides its weight equally across its tags. On this ten-topic
representation, total variation distance is **0.348** between train and normal
test and **0.659** between train and challenge test (0 means identical, 1 means
disjoint). These are distances between task-topic mixes, not between arbitrary
scenario IDs. The pilot therefore samples each split against its **own** full
content distribution and retains examples of unseen test content.

## Pilot sample

This pilot has five complete scenarios from each of `train`, `test_normal`, and
`test_challenge`. Each scenario contributes its `_1`, `_2`, and `_3` tasks, for
45 tasks total. At 2.2 minutes per task, task execution takes about 99 minutes.

| Source split | Sample dataset name | Scenarios | Tasks | Scenario IDs |
| --- | --- | ---: | ---: | --- |
| `train` | `quick2h_train` | 5 | 15 | `ce359b5`, `b0a8eae`, `7d7fbf6`, `07b42fd`, `6ea6792` |
| `test_normal` | `quick2h_test_normal` | 5 | 15 | `3b8fb7a`, `f323bae`, `59fae45`, `dac78d9`, `3aa1a22` |
| `test_challenge` | `quick2h_test_challenge` | 5 | 15 | `5238afc`, `c8f5f44`, `476b213`, `7bdaf23`, `adb1060` |

The reviewable manifests are in `experiments/samples/quick2h/`. Copies are
already installed in `data/datasets/` for this workspace. If the data directory
is regenerated, restore them from the AppWorld project directory with:

```bash
for split in train test_normal test_challenge; do
    cp "experiments/samples/quick2h/${split}.txt" "data/datasets/quick2h_${split}.txt"
done
```

Set the experiment config's `dataset` to the corresponding sample dataset name.
Do not use `sample_size` for this purpose: the ACE runner takes the first N
tasks in file order, which distorts the challenge-set content mix.

Selection balanced instruction-derived app topics, scenario difficulty, and
number of apps separately within each source split. The two test samples also
cover different levels of instruction similarity to the full training set.
The normal sample includes a Splitwise scenario, and the challenge sample
includes Amazon purchasing, Gmail/file handling, and email scheduling.

### Ten-topic probability vectors

The coordinate order for every vector is
`[Amazon, Gmail, Todoist, Splitwise, Spotify, Venmo, Simple Note, Phone, File system, Other]`.
Each scenario has weight 1; its three task variants each have weight 1/3,
divided equally among the topics tagged in that variant. These are topic
**probabilities**, not counts of scenarios mentioning an app. All entries are
rounded to four decimal places.

```text
quick2h train          = [0.0000, 0.0000, 0.0000, 0.0000, 0.5000, 0.2000, 0.1000, 0.0000, 0.2000, 0.0000]
quick2h test_normal    = [0.0000, 0.0000, 0.0000, 0.1000, 0.2000, 0.3000, 0.2000, 0.1000, 0.1000, 0.0000]
quick2h test_challenge = [0.4333, 0.1000, 0.0000, 0.0000, 0.0667, 0.1000, 0.0000, 0.0000, 0.1000, 0.2000]
```

| Source split | Topic TV | Difficulty TV | App-count TV | Novelty-bin TV |
| --- | ---: | ---: | ---: | ---: |
| `train` | 0.0833 | 0.0000 | 0.1333 | — |
| `test_normal` | 0.1131 | 0.0857 | 0.1107 | 0.1000 |
| `test_challenge` | 0.1448 | 0.0676 | 0.1237 | 0.1482 |

TV is total variation distance between the sample and its **own full split**.
Topics are based on explicit app names plus phone and file-system references;
multi-topic tasks divide their weight equally. Novelty bins use TF-IDF cosine
similarity to the nearest training scenario (bottom 25%, middle 50%, top 25%).

To measure the **train-to-test shift within the quick2h sample**, compare the
sampled train topic distribution with each sampled test topic distribution
using the same ten topics and
`TV(P, Q) = 1/2 * sum_k |P_k - Q_k|`:

| Train-to-test pair | Full-split topic TV | Quick2h sample topic TV | Sample minus full |
| --- | ---: | ---: | ---: |
| Train → test normal | 0.3476 | **0.4000** | +0.0524 |
| Train → test challenge | 0.6595 | **0.7333** | +0.0739 |

These values compare **two sampled splits**, unlike the preceding table's
sample-to-own-source distances. The quick2h sample retains the ordering:
challenge remains substantially further from train than normal test, although
both sampled train-to-test distances are slightly larger than in the full data.

This is a method-debugging sample. Five scenarios per split are too few for a
reliable estimate of full-split success rates or rare-task performance. Report
pilot results separately from full-split results. AppWorld scenario goal
completion can be computed because all three tasks of each selected scenario
are included.

## Normal v2 for difficulty-aware fast tests

The original 15-task `quick2h_test_normal` is retained for its completed
experiments. A separate, outcome-blind [normal v2 sample](samples/quick2h_normal_v2/README.md)
provides 21 tasks from seven complete families under the name
`quick2h_test_normal_v2`. It retains four original families, removes
`3b8fb7a`, and adds `ff58e36`, `0a9d82a`, and `986aa4e` in full-split order.
The original quick2h train manifest remains unchanged. Challenge now also has
a separate v2 manifest described below; all completed v1 results remain tied
to the original manifests.

| Full-normal fidelity | Original normal | Normal v2 |
| --- | ---: | ---: |
| Topic TV | 0.1131 | **0.0982** |
| Official difficulty TV | 0.0857 | **0.0536** |
| App-count TV | 0.1107 | **0.0536** |
| Quick2h train → normal topic TV | 0.4000 | 0.4143 |

The full train → normal topic TV is 0.3476. Thus the new normal sample
improves its own topic and intrinsic-difficulty match, while the retained
train-to-normal shift is slightly too large. The three-split one-pass budget
with original challenge is 15 + 21 + 15 = **51 tasks**. With challenge v2 it
is 15 + 21 + 18 = **54 tasks**, estimated at **118.8 minutes** using the
previous 2.2-minute/task rate. This is an estimate with almost no runtime slack,
especially for complex tasks. The [manifest](samples/quick2h_normal_v2/test_normal.txt),
[installed dataset](../data/datasets/quick2h_test_normal_v2.txt),
[audit](samples/quick2h_normal_v2/audit.json), and
[generator](code/sample_quick2h_normal_v2.py) are kept separate from v1.
No ACE result has yet been measured on v2.

## Challenge v2 for difficulty-aware fast tests

The separate, outcome-blind [challenge v2 sample](samples/quick2h_challenge_v2/README.md)
provides 18 tasks from six complete families under
`quick2h_test_challenge_v2`. It retains four original families, removes
`7bdaf23`, and adds `c9458ed` and `a3ba388` in full-split order.

| Full-challenge fidelity | Original challenge | Challenge v2 |
| --- | ---: | ---: |
| Topic TV | 0.1448 | **0.1147** |
| Official difficulty TV | 0.0676 | **0.0324** |
| App-count TV | 0.1237 | **0.0983** |
| Novelty-bin TV | 0.1482 | **0.0851** |
| Quick2h train → challenge topic TV | 0.7333 | 0.7778 |

The full train → challenge topic TV is 0.6595. Challenge v2 improves all four
listed within-split fidelity measures but increases the train-to-challenge
shift error from 0.0739 to 0.1183. It still preserves the intended ordering:
challenge v2 is much farther from train than normal v2. The
[manifest](samples/quick2h_challenge_v2/test_challenge.txt),
[installed dataset](../data/datasets/quick2h_test_challenge_v2.txt),
[audit](samples/quick2h_challenge_v2/audit.json), and
[generator](code/sample_quick2h_challenge_v2.py) are separate from v1. No
baseline result has yet been measured on challenge v2.

## Train v2 for difficulty-aware fast tests

The separate, outcome-blind [train v2 sample](samples/quick2h_train_v2/README.md)
keeps the train allocation at 15 tasks from five complete families under
`quick2h_train_v2`. It retains four original families and replaces the D1
Spotify family `07b42fd` with the D1 Spotify family `e3d6c94` in full-train
order. The replacement preserves topic, difficulty, app-count, and both
train-to-test topic TVs while improving the intrinsic complexity match.

| Full-train fidelity | Original train | Train v2 |
| --- | ---: | ---: |
| Topic TV | 0.0833 | 0.0833 |
| Official difficulty TV | 0.0000 | 0.0000 |
| App-count TV | 0.1333 | 0.1333 |
| API-count quartile TV | 0.3000 | **0.1000** |
| Reference API-call quartile TV | 0.1444 | **0.1111** |
| Reference-code-length quartile TV | 0.2778 | **0.1222** |

The complete v2 suite is therefore:

```text
quick2h_train_v2              15 tasks / 5 families
quick2h_test_normal_v2        21 tasks / 7 families
quick2h_test_challenge_v2     18 tasks / 6 families
total                         54 tasks / 18 families
```

At 2.2 minutes per task this is estimated at 118.8 minutes, leaving only 1.2
nominal minutes of slack. The [manifest](samples/quick2h_train_v2/train.txt),
[installed dataset](../data/datasets/quick2h_train_v2.txt),
[audit](samples/quick2h_train_v2/audit.json), and
[generator](code/sample_quick2h_train_v2.py) are separate from v1. No baseline
result has yet been measured on train v2.
