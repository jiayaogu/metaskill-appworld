# Intermediate 8h Qwen3.8-flash ACE offline/online results

Completed: 2026-10-21 (America/Toronto)

## Scope

This report covers one shared no-GT offline adaptation run and four test conditions on the reviewed intermediate one-third manifests. All Generator, Reflector, and Curator calls used the actual provider model `qwen3.8-flash`, temperature 0, model seed 100, AppWorld seed 123, and a 40-step cap.

The official AppWorld aggregate JSON/TXT files are the metric source of truth. Costs are reconstructed from `logs/lm_calls.jsonl`, charging uncached input at $0.64/M tokens, cached input at $0.08/M, and output at $2.16/M. Native `misc/cost.txt` values are not used because the custom model alias is absent from the runtime LiteLLM price map.

## Main results

| Split | Mode | Successful tasks | TGC | Successful families | SGC | Test-stream cost | Standalone cost |
|---|---|---:|---:|---:|---:|---:|---:|
| normal | offline frozen | 52/57 | 91.2% | 16/19 | 84.2% | $4.10846888 | $8.20607072 |
| normal | online adaptive | 51/57 | 89.5% | 16/19 | 84.2% | $9.88644232 | $9.88644232 |
| challenge | offline frozen | 117/138 | 84.8% | 33/46 | 71.7% | $15.18353976 | $19.28114160 |
| challenge | online adaptive | 130/138 | 94.2% | 39/46 | 84.8% | $47.73720088 | $47.73720088 |

Standalone offline cost includes the shared $4.09760184 adaptation cost. The shared run is counted only once in the actual five-run project total of **$81.01325368**.

The offline adaptation training diagnostic was 27/30 TGC (90.0%) and 7/10 SGC (70.0%). It is not one of the four test conditions.

## Difficulty breakdown

| Split | Mode | D1 TGC / SGC | D2 TGC / SGC | D3 TGC / SGC |
|---|---|---|---|---|
| train | offline adaptation | 12/12 (100.0%) / 4/4 (100.0%) | 11/12 (91.7%) / 3/4 (75.0%) | 4/6 (66.7%) / 0/2 (0.0%) |
| normal | offline frozen | 21/21 (100.0%) / 7/7 (100.0%) | 13/15 (86.7%) / 4/5 (80.0%) | 18/21 (85.7%) / 5/7 (71.4%) |
| normal | online adaptive | 19/21 (90.5%) / 6/7 (85.7%) | 15/15 (100.0%) / 5/5 (100.0%) | 17/21 (81.0%) / 5/7 (71.4%) |
| challenge | offline frozen | 23/24 (95.8%) / 7/8 (87.5%) | 47/51 (92.2%) / 14/17 (82.3%) | 47/63 (74.6%) / 12/21 (57.1%) |
| challenge | online adaptive | 23/24 (95.8%) / 7/8 (87.5%) | 47/51 (92.2%) / 13/17 (76.5%) | 60/63 (95.2%) / 19/21 (90.5%) |

## Offline/online paired comparison

`S` and `F` below are ordered as offline → online.

| Split | Task SS / FS / SF / FF | Family SS / FS / SF / FF | Δ TGC | Δ SGC |
|---|---|---|---:|---:|
| normal | 49 / 2 / 3 / 3 | 15 / 1 / 1 / 2 | -1.7 pp | 0.0 pp |
| challenge | 113 / 17 / 4 / 4 | 31 / 8 / 2 / 5 | +9.4 pp | +13.1 pp |

Normal positive task migrations: `d6ac34d_1`, `d6ac34d_2`.

Normal negative task migrations: `425a494_2`, `425a494_3`, `2c544f9_3`.

Challenge positive task migrations: `245cb43_2`, `f6be291_3`, `ec655df_1`, `ec655df_2`, `1a79e37_3`, `f3a6713_1`, `f3a6713_2`, `b6d1f70_2`, `b6d1f70_3`, `dc5c5c6_1`, `dc5c5c6_3`, `59bcfc8_1`, `59bcfc8_3`, `5800354_2`, `476b213_3`, `a97e35d_1`, `a1d3dfd_1`.

Challenge negative task migrations: `245cb43_3`, `e201314_2`, `476b213_2`, `d37c235_3`.

At family level, challenge gained `ec655df`, `f3a6713`, `b6d1f70`, `dc5c5c6`, `59bcfc8`, `5800354`, `a97e35d`, and `a1d3dfd`, while losing `e201314` and `d37c235`.

## Calls, tokens, and cost

| Runner | Calls | Uncached input | Cached input | Output | Fixed-rate cost |
|---|---:|---:|---:|---:|---:|
| offline adaptation | 609 | 2,808,130 | 9,180,928 | 724,965 | $4.09760184 |
| offline normal | 1,099 | 1,563,428 | 27,433,728 | 422,767 | $4.10846888 |
| offline challenge | 3,670 | 5,601,769 | 106,739,968 | 1,416,301 | $15.18353976 |
| online normal | 1,222 | 7,063,570 | 25,595,136 | 1,536,179 | $9.88644232 |
| online challenge | 2,782 | 43,589,890 | 127,243,008 | 4,472,329 | $47.73720088 |

## Step-cap diagnostics

- Offline adaptation and offline normal had no 40-step tasks.
- Offline challenge had 21 tasks at step 40; 17 did not call `complete_task`: `1a79e37_1`, `1a79e37_3`, `476b213_3`, `5800354_2`, `59bcfc8_1`, `59bcfc8_3`, `a97e35d_1`, `b6d1f70_2`, `b6d1f70_3`, `dc5c5c6_1`, `dc5c5c6_3`, `ec655df_1`, `ec655df_2`, `f3a6713_2`, `f6be291_1`, `f6be291_2`, `f6be291_3`.
- Online normal had one step-40/no-complete task: `986aa4e_3`.
- Online challenge had four step-40 tasks; `e201314_2`, `f6be291_1`, and `f6be291_2` did not call `complete_task`.
- The official post-run evaluator generated reports for every task, including step-cap cases.

## Playbooks

| Playbook | Bytes | Bracket-ID bullets | SHA-256 |
|---|---:|---:|---|
| initial | 1,469 | — | `3c4f46888c9159088c3eb8f70e879d4d28a5704ab9f15d132563ba0ee2730b7b` |
| offline final | 59,887 | 130 | `8b367c5b239498683bdd598217bef652cc0fb3ea46c7a80ea9a5ceea37e908e6` |
| online normal final | 112,074 | 221 | `7f75f2f2fe205870c1e6dd7c9411d1dff053ec7f5f13ea9b1a8ee6fc06cf3230` |
| online challenge final | 416,546 | 540 | `575d8e7d5ffde34ef9d454365d24a797baa6a48e3e4be31d0f24598d6ed1b3c8` |

The offline final playbook is byte-identical to its task-30 checkpoint and remained frozen across both offline evaluations.

## Artifact audit and interruption recovery

- All five formal runs have the expected 30/57/138/57/138 task directories and reports.
- Manifest IDs, task directories, and aggregate `individual` keys match exactly; there are no missing or extra formal tasks.
- Every task has the required layout and exactly 13 DB files.
- All API-call, LM-call, and DB JSONL files parse successfully.
- Aggregate JSON and TXT reports exist for every run.
- Offline-challenge and online-challenge each had one interrupted partial excluded from metrics and cost. Both are now preserved under `experiments/outputs/archived_incomplete_test_runs_20261026.intermediate8h/`; `ARCHIVE_MANIFEST.md` records their original run locations and hashes.
- Offline-challenge resumed from manifest item 62 using only items 62–138.
- Online-challenge resumed from item 90 using only items 90–138 and initialized from the evolved item-89 playbook, preserving online causality without replaying earlier tasks.

Task artifact versions are AppWorld code `0.1.4.dev0` and data `0.1.0`. The nested repository revision at closeout was `cc865ddf0aa2eb2dc35459190d5d3b660d2dfb56`.

