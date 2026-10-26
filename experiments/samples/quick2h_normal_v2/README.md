# Quick2h normal v2: intrinsic-difficulty revision

This is a **new** `test_normal` sample for fast method tests. The historical
`quick2h_test_normal` manifest and its ACE results remain v1. The sample was
generated while train and test-challenge still used their original manifests;
the complete v2 suite now pairs it with `quick2h_train_v2` and
`quick2h_test_challenge_v2`.

## Why revise the normal sample?

The Qwen3.8-flash ACE online result was 15/15 on v1 quick2h normal and 51/57
on intermediate normal. Five families are too few to infer that the full
normal split is easy. The v1 official difficulty mix was already fairly close
to full normal, so simply adding D3 tasks would not fix the sampling problem.
This revision broadens scenario content and improves measured difficulty and
app-count fidelity without reading any baseline's successes or failures.

## Selection

The [reproducible script](../../code/sample_quick2h_normal_v2.py) enumerates
all feasible seven-family samples that retain at least four v1 families.
It uses only the 56 full-normal families' task instructions and intrinsic
ground-truth metadata. It requires two D1, two D2, and three D3 families,
plus Splitwise and Todoist coverage. The difficulty counts are the closest
seven-family counts to the full split's D1/D2/D3 proportions. Of 3,105
feasible candidates, it ranks the following distances lexicographically:

1. Maximum, then sum, of topic TV, difficulty TV, app-count TV, and error in
   quick2h-train-to-normal topic TV.
2. Maximum, then sum, of novelty-bin TV and quartile-bin TVs for `num_apis`,
   `num_api_calls`, and `num_solution_code_lines`.
3. Source-split family order as a deterministic tie-breaker.

The novelty representation is TF-IDF word unigrams/bigrams with English stop
words and sublinear term frequency, fitted on all source families; normal
families are binned at the full normal split's 25th and 75th percentiles of
similarity to full train. Complexity bins likewise use full-normal quartiles.
All TVs use unrounded probabilities. The exact cutoffs, probabilities, rank,
and candidate count are in [audit.json](audit.json).

## Result

| Item | Value |
| --- | --- |
| Retained v1 families | `f323bae`, `59fae45`, `dac78d9`, `3aa1a22` |
| Removed v1 family | `3b8fb7a` |
| Added families | `ff58e36` (D2, Venmo), `0a9d82a` (D3, Simple Note), `986aa4e` (D3, Todoist/Spotify) |
| Normal v2 | 7 families, 21 tasks |
| Train + normal v2 + original challenge | 5 + 7 + 5 families = 51 tasks |
| Complete v2 suite with train/challenge v2 | 5 + 7 + 6 families = 54 tasks |
| Complete-v2 estimated runtime | 118.8 minutes at 2.2 minutes/task; 1.2 minutes of nominal two-hour slack |
| Installed dataset | `data/datasets/quick2h_test_normal_v2.txt` |
| Manifest SHA-256 | `f42bacdfd70d33faf77d9cbc9be568a75e3f623d519bbc04205f7657deff4a04` |

The manifest keeps **full test-normal source order**, which matters for online
memory adaptation. It contains all three variants of each family. The
[reviewable manifest](test_normal.txt) and installed dataset are byte-identical.

| Distance to full normal | v1 (15 tasks) | v2 (21 tasks) |
| --- | ---: | ---: |
| Topic TV | 0.1131 | **0.0982** |
| Official difficulty TV | 0.0857 | **0.0536** |
| Number-of-apps TV | 0.1107 | **0.0536** |
| Novelty-bin TV | 0.1000 | 0.1071 |
| API-count quartile TV | 0.1286 | 0.1429 |
| Reference API-call quartile TV | 0.0714 | 0.1190 |
| Reference-code-length quartile TV | 0.0881 | 0.1071 |

Full normal has D1/D2/D3 proportions `57/48/63` out of 168 tasks
(`33.9%/28.6%/37.5%`). V2 has `6/6/9` out of 21
(`28.6%/28.6%/42.9%`); v1 had `6/3/6` out of 15
(`40%/20%/40%`). V2 therefore better matches the official difficulty mix,
although it still oversamples D3 slightly. The selected `986aa4e` family also
covers a high-complexity Todoist/Spotify workflow absent from v1.

Full train-to-normal topic TV is `0.3476`. The old sampled train-to-normal TV
was `0.4000`; using the unchanged quick2h train with v2 normal gives `0.4143`.
The absolute shift error increases from `0.0524` to `0.0667`, while normal
remains closer to train than the original quick2h challenge sample. This is a
small, explicit tradeoff for the improved within-normal topic, difficulty,
and app-count TVs.

The complete v2 suite's 118.8-minute runtime is an estimate, not a guarantee: the newly covered
complex tasks may take longer. It counts **one execution per task**. Running
both offline-frozen and online-adaptive conditions adds executions and needs
a separate time budget. V2 has no measured ACE TGC yet; it must be run under
a new experiment name before comparing results. Because tasks overlap with
the prior intermediate run, that comparison is diagnostic rather than an
independent holdout estimate.

Regenerate with:

```bash
.venv/bin/python ace-appworld/experiments/code/sample_quick2h_normal_v2.py
```
