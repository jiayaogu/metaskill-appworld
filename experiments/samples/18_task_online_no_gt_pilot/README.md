# Memory-pressure scores for the 18-task online pilot

Source manifest: `data/datasets/18_task_online_no_gt_pilot.txt`.
It contains 18 train tasks grouped into six complete three-variant scenario
families. Apply the [reusable screening test](../memory_pressure_screening.md)
to each family. The [scorecard](scores.yaml) records an integer score,
concrete family evidence, and a one-sentence justification for every
M/I/A/P/U dimension.

| Family | M | I | A | P | U | Candidate | Strong dimensions | Total pressure |
| --- | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: |
| `07b42fd` | 2 | 2 | 2 | 1 | 2 | Yes | 4 | 9 |
| `e3d6c94` | 2 | 2 | 2 | 1 | 2 | Yes | 4 | 9 |
| `76f2c72` | 2 | 2 | 2 | 0 | 2 | No | 4 | 8 |
| `2a163ab` | 2 | 2 | 2 | 1 | 2 | Yes | 4 | 9 |
| `3c13f5a` | 2 | 2 | 2 | 1 | 2 | Yes | 4 | 9 |
| `d0b1f43` | 2 | 2 | 2 | 0 | 2 | No | 4 | 8 |

`76f2c72` and `d0b1f43` are answer-only families. Their evaluators check
the final numeric answer and the absence of model changes, which does not
identify whether a wrong total came from filtering, extraction, or
aggregation. They therefore receive P=0 and fail
`candidate = all(score >= 1)`. The other four families pass. These are
intrinsic-data scores; no baseline outcome was used.
