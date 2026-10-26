# Quick2h challenge v2: intrinsic-difficulty revision

This is a **new** `test_challenge` sample for fast method tests. The historical
`quick2h_test_challenge` manifest and its completed results remain v1. This
sample was generated against the original train distribution; the complete v2
suite now uses the topic-equivalent 15-task train v2, 21-task normal v2, and
this 18-task challenge v2.

## Selection

The [reproducible script](../../code/sample_quick2h_challenge_v2.py) applies
the same outcome-blind procedure as normal v2. It reads only task instructions
and intrinsic ground-truth metadata. It never reads experiment outputs,
evaluator reports, or any baseline's successes and failures.

The two-hour budget limits challenge v2 to six complete families:

```text
15 train + 21 normal v2 + 18 challenge v2 = 54 tasks
54 tasks * 2.2 minutes/task = 118.8 minutes
```

Six families approximate the full challenge D1/D2/D3 mix most closely with
one D1, two D2, and three D3 families. The search enumerates all samples that
retain at least four of the five v1 families and cover Amazon and Gmail, the
major challenge-only application content. It found 9,106 feasible candidates
and ranked them lexicographically by:

1. Maximum, then sum, of topic TV, difficulty TV, app-count TV, and error in
   quick2h-train-to-challenge topic TV.
2. Maximum, then sum, of novelty-bin TV and quartile-bin TVs for `num_apis`,
   `num_api_calls`, and `num_solution_code_lines`.
3. Source-split family order as a deterministic tie-breaker.

Novelty uses the same TF-IDF representation as normal v2: word unigrams and
bigrams, English stop words, and sublinear term frequency. Similarity is to
the nearest full-train family, using the full challenge split's 25th and 75th
percentile bin boundaries. Complexity bins use full-challenge quartiles. The
exact probabilities, cutoffs, distances, and rank are in [audit.json](audit.json).

## Result

| Item | Value |
| --- | --- |
| Retained v1 families | `5238afc`, `c8f5f44`, `476b213`, `adb1060` |
| Removed v1 family | `7bdaf23` |
| Added families | `c9458ed` (D3, Amazon/Phone), `a3ba388` (D2, Gmail/File system) |
| Challenge v2 | 6 families, 18 tasks |
| Complete v2 suite | 5 train + 7 normal + 6 challenge families = 54 tasks |
| Estimated one-pass runtime | 118.8 minutes at 2.2 minutes/task; 1.2 minutes of nominal slack |
| Installed dataset | `data/datasets/quick2h_test_challenge_v2.txt` |
| Manifest SHA-256 | `558ee0e389f64e5fb7fca9a02253a72dd4840df1eae19033b32d94c934086cd9` |

The manifest preserves **full test-challenge order**, which is required for a
reproducible online adaptation stream, and contains all three variants of each
family. The [reviewable manifest](test_challenge.txt) and installed dataset
are byte-identical.

| Distance to full challenge | v1 (15 tasks) | v2 (18 tasks) |
| --- | ---: | ---: |
| Topic TV | 0.1448 | **0.1147** |
| Official difficulty TV | 0.0676 | **0.0324** |
| Number-of-apps TV | 0.1237 | **0.0983** |
| Novelty-bin TV | 0.1482 | **0.0851** |
| API-count quartile TV | 0.2129 | **0.1463** |
| Reference API-call quartile TV | **0.0940** | 0.1055 |
| Reference-code-length quartile TV | 0.2542 | **0.0959** |

Full challenge has D1/D2/D3 proportions `24/50/65` out of 139 families
(`17.3%/36.0%/46.8%`). V2 has `1/2/3` families
(`16.7%/33.3%/50.0%`), while v1 had `1/2/2`
(`20%/40%/40%`). V2 therefore closely matches the official difficulty mix.
Its app-count mix also improves, and `c9458ed` adds a multi-step
Amazon/Phone purchase workflow.

Full train-to-challenge topic TV is `0.6595`. The original sampled
train-to-challenge TV was `0.7333`; v2 gives `0.7778`. Thus v2 improves its
within-challenge fidelity on the main intrinsic distributions but exaggerates
the train-to-challenge topic shift: absolute shift error rises from `0.0739`
to `0.1183`. Challenge v2 remains much farther from sampled train than normal
v2 (`0.4143`), preserving the direction of the original split difference.

The 118.8-minute estimate has almost no slack and is not a runtime guarantee.
It counts one execution per task; running several baselines or both
offline-frozen and online-adaptive conditions requires a separate budget.
Challenge v2 has no measured result yet. Because it overlaps with earlier
intermediate experiments, future v2 scores are diagnostic rather than an
independent holdout estimate.

Regenerate with:

```bash
.venv/bin/python ace-appworld/experiments/code/sample_quick2h_challenge_v2.py
```
