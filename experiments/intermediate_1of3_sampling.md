# One-third AppWorld intermediate sample

This is an **unconditioned** intermediate subset selected from the complete
`train`, `test_normal`, and `test_challenge` splits. It does not apply the
M/I/A/P/U memory-pressure screen. The sampling unit is a complete scenario
family (`_1`, `_2`, `_3`), and each source split is sampled separately. Counts
are the nearest whole number to one third of each source split.

| Split | Full scenarios | Intermediate scenarios | Intermediate tasks | Fraction of source |
| --- | ---: | ---: | ---: | ---: |
| Train | 30 | 10 | 30 | 33.33% |
| Test normal | 56 | 19 | 57 | 33.93% |
| Test challenge | 139 | 46 | 138 | 33.09% |
| **Total** | **225** | **75** | **225** | **33.33%** |

At the pilot estimate of 2.2 minutes per task, running all 225 tasks takes
about **495 minutes (8 hours 15 minutes)**, excluding setup and retries. This
is an intermediate evaluation set, not a two-hour quick check.

## Selection method

The reproducible selector is
[`sample_intermediate_1of3.py`](code/sample_intermediate_1of3.py). It follows
the [reusable distribution criteria](samples/memory_pressure_screening.md):

1. Read only intrinsic task instructions and `ground_truth/metadata.json`;
   keep all three variants of every selected family. Baseline outcomes are not
   used.
2. Give each family equal total weight over its three variants. Tag the same
   ten instruction topics as the quick2h report, splitting multi-topic task
   weight equally. Calculate `TV(P,Q) = 0.5 * sum_k |P[k]-Q[k]|` on unrounded
   topic probabilities.
3. Search joint split subsets, ranking the maximum and sum of (a) each
   sample-to-own-source topic TV and (b) the absolute error in train-to-normal
   and train-to-challenge topic TV. Then break ties using difficulty, app-count,
   and test-novelty-bin TVs. Test novelty uses each family's nearest full-train
   TF-IDF cosine similarity and fixed 25th/75th percentile cutoffs from its
   full test split. The selector uses seed `20261015`, 600,000 stochastic
   proposals, and local one-family-swap refinement; this is a search result,
   not a proof of global optimality.
4. Require normal to retain Todoist or Splitwise, challenge to retain both
   Amazon and Gmail, and sampled train→challenge topic TV to exceed
   train→normal TV. Check source membership, uniqueness, and all three variants.

The selected task IDs are in
[`samples/intermediate_1of3/train.txt`](samples/intermediate_1of3/train.txt),
[`test_normal.txt`](samples/intermediate_1of3/test_normal.txt), and
[`test_challenge.txt`](samples/intermediate_1of3/test_challenge.txt). The
[machine-readable audit](samples/intermediate_1of3/audit.json) includes every
selected family ID, the complete topic vectors, preprocessing settings, TV
values, and unseen-app counts.

## Distribution audit

Each TV in this table compares a sample to **its own full source split**. The
quick2h topic column is the earlier five-family-per-split sample for context.

| Split | Intermediate topic TV | Quick2h topic TV | Difficulty TV | App-count TV | Novelty-bin TV |
| --- | ---: | ---: | ---: | ---: | ---: |
| Train | **0.0333** | 0.0833 | 0.0000 | 0.1667 | — |
| Test normal | **0.0374** | 0.1131 | 0.0291 | 0.0686 | 0.0263 |
| Test challenge | **0.0159** | 0.1448 | 0.0111 | 0.0170 | 0.0127 |

The topic mix is closer to all three full splits than the quick2h topic mix.
Difficulty and test-novelty-bin TVs are also small. The intermediate train
app-count TV, **0.1667**, is larger than quick2h's **0.1333**; the larger sample
does not improve every descriptive statistic.

The topic probabilities below show the measured content distribution. Each
cell is **full split → intermediate**, in percent. Multi-topic variants share
their weight, so these are not overlapping app-incidence rates.

| Topic | Train | Test normal | Test challenge |
| --- | ---: | ---: | ---: |
| Amazon | 0.00 → 0.00 | 0.00 → 0.00 | 43.65 → 44.20 |
| Gmail | 0.00 → 0.00 | 0.00 → 0.00 | 11.87 → 11.96 |
| Todoist | 0.00 → 0.00 | 3.57 → 2.63 | 0.72 → 0.00 |
| Splitwise | 0.00 → 0.00 | 3.57 → 5.26 | 1.08 → 1.09 |
| Spotify | 50.00 → 50.00 | 21.43 → 21.05 | 6.35 → 5.80 |
| Venmo | 20.00 → 20.00 | 34.52 → 34.21 | 7.19 → 7.61 |
| Simple Note | 8.33 → 5.00 | 18.75 → 18.42 | 3.24 → 3.26 |
| Phone | 8.33 → 10.00 | 9.23 → 10.53 | 6.83 → 6.52 |
| File system | 13.33 → 15.00 | 7.14 → 7.89 | 10.43 → 10.87 |
| Other | 0.00 → 0.00 | 1.79 → 0.00 | 8.63 → 8.70 |

### Retained train/test difference

These TV values compare **train to test within each set**, rather than sample
to source. The absolute error is `|intermediate TV - full TV|`.

| Pair | Full topic TV | Quick2h topic TV | Intermediate topic TV | Intermediate absolute error |
| --- | ---: | ---: | ---: | ---: |
| Train → test normal | 0.347619 | 0.400000 | **0.360526** | **0.012907** |
| Train → test challenge | 0.659472 | 0.733333 | **0.659420** | **0.000052** |

Challenge remains farther from train than normal does. The intermediate
train-to-test TV errors are smaller than quick2h's errors of 0.0524 and
0.0739, respectively.

### Unseen test content

The following counts are scenario incidence, not topic probability. A family
is counted once if any of its three instructions names Amazon, Gmail,
Todoist, or Splitwise, which are absent from the training instructions under
this tagging rule.

| Split | Full families with an unseen app | Intermediate families with an unseen app | Types represented in intermediate |
| --- | ---: | ---: | --- |
| Train | 0/30 | 0/10 | — |
| Test normal | 7/56 | 3/19 | Todoist 1, Splitwise 2 |
| Test challenge | 94/139 | 30/46 | Amazon 24, Gmail 7, Splitwise 1 |

The challenge sample misses the one Todoist family in the full challenge
split. The ten-topic TV is a coarse content proxy and does not prove that
rare operations or the complete semantic task distribution are preserved.
This deliberately balanced sample is useful for intermediate method checks;
it is not a probability sample for unbiased full-split success estimates.

## Run and reproduce

Copies of the manifests are installed as
`data/datasets/intermediate_8h_{train,test_normal,test_challenge}.txt`.
Set the ACE config's `dataset` to the corresponding name. Do not rely on
`sample_size`: the runner takes the first tasks in manifest order.

To regenerate the selection from the project repository root:

```bash
../.venv/bin/python experiments/code/sample_intermediate_1of3.py
```

If `data/datasets/` is regenerated, restore its dataset files from the
reviewable manifests:

```bash
for split in train test_normal test_challenge; do
    cp "experiments/samples/intermediate_1of3/${split}.txt" \
       "data/datasets/intermediate_1of3_${split}.txt"
done
```
