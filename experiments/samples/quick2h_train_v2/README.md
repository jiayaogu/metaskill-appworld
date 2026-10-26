# Quick2h train v2: intrinsic-difficulty revision

This is a **new** train sample for the difficulty-aware quick2h v2 suite. The
historical `quick2h_train` manifest and completed experiment results remain v1.
The complete v2 suite uses this 15-task train sample, 21-task normal v2, and
18-task challenge v2.

## Selection

The [reproducible script](../../code/sample_quick2h_train_v2.py) applies the
same outcome-blind procedure as the two test-v2 samplers. It reads only task
instructions and intrinsic ground-truth metadata. It never reads experiment
outputs, evaluator reports, or baseline successes and failures.

Normal v2 and challenge v2 already contain 39 tasks. The two-hour budget
therefore keeps train v2 at five complete families:

```text
15 train v2 + 21 normal v2 + 18 challenge v2 = 54 tasks
54 tasks * 2.2 minutes/task = 118.8 minutes
```

Five families represent the full train D1/D2/D3 proportions exactly with two
D1, two D2, and one D3 family. The search enumerates all samples retaining at
least four of the five v1 families and preserving this `2/2/1` difficulty mix.
For each candidate, it computes topic, difficulty, and app-count TV to full
train, plus the errors in train-to-normal-v2 and train-to-challenge-v2 topic
TV. Those are the primary ranking values. Quartile-bin TVs for `num_apis`,
`num_api_calls`, and `num_solution_code_lines` are secondary ranking values.
Source-split order is the deterministic final tie-breaker.

The search evaluated 46 feasible candidates. The exact full/sample vectors,
quartile cutoffs, distances, rank, and test-v2 dependencies are recorded in
[audit.json](audit.json).

## Result

| Item | Value |
| --- | --- |
| Retained v1 families | `ce359b5`, `b0a8eae`, `7d7fbf6`, `6ea6792` |
| Removed v1 family | `07b42fd` (D1, Spotify) |
| Added family | `e3d6c94` (D1, Spotify) |
| Train v2 | 5 families, 15 tasks |
| Complete v2 suite | 5 train + 7 normal + 6 challenge families = 54 tasks |
| Estimated one-pass runtime | 118.8 minutes at 2.2 minutes/task; 1.2 minutes of nominal slack |
| Installed dataset | `data/datasets/quick2h_train_v2.txt` |
| Manifest SHA-256 | `8dfbb6c74d9b439beace18241f5775ebf115344953febdb97329461bed6fc33e` |

The replacement preserves the primary content representation: both removed
and added families are D1, one-app Spotify tasks. `e3d6c94` nevertheless has
more involved intrinsic reference requirements: its variants use 8 APIs,
40–50 reference API calls, and 32–34 reference solution lines, compared with
6 APIs, 15 calls, and 21–23 lines for `07b42fd`.

| Distance to full train | v1 (15 tasks) | v2 (15 tasks) |
| --- | ---: | ---: |
| Topic TV | 0.0833 | 0.0833 |
| Official difficulty TV | 0.0000 | 0.0000 |
| Number-of-apps TV | 0.1333 | 0.1333 |
| API-count quartile TV | 0.3000 | **0.1000** |
| Reference API-call quartile TV | 0.1444 | **0.1111** |
| Reference-code-length quartile TV | 0.2778 | **0.1222** |

Because the replacement has the same ten-topic contribution, the two retained
distribution shifts are unchanged:

| Pair | Full split TV | v2 sample TV | Absolute error |
| --- | ---: | ---: | ---: |
| Train v2 → normal v2 | 0.3476 | 0.4143 | 0.0667 |
| Train v2 → challenge v2 | 0.6595 | 0.7778 | 0.1183 |

The manifest preserves **full train order** and contains all three variants of
each family. The [reviewable manifest](train.txt) and installed dataset are
byte-identical. The 118.8-minute estimate has almost no slack and counts one
execution per task. Train v2 has no measured baseline result yet, and future
v2 scores should remain separate from completed v1 experiments.

Regenerate with:

```bash
.venv/bin/python ace-appworld/experiments/code/sample_quick2h_train_v2.py
```
