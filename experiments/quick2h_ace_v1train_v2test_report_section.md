## V1 train → V2 test extension (2026-10-26)

Generated: 2026-10-26T15:41:38.382314-04:00

Offline adaptation on `quick2h_train` (v1, 15 tasks) was completed in the earlier `ACE_quick2h_offline_online/qwen3.8-flash/offline_no_GT_adaptation` run; its complete playbook is reused unchanged for both V2 frozen tests. Two redundant fresh training attempts stalled at the provider and were interrupted; their partial artifacts are excluded. The online challenge run also resumed at task 5 after a stalled request, preserving its four completed tasks and updated playbook; the incomplete task directory was archived and rerun with a 300-second infrastructure timeout. Its exact task-boundary evidence is `experiments/outputs/archived_incomplete_test_runs_20261026.ACEv2/ACE_quick2h_v1train_v2test_20261026_retry1_interrupted/qwen3.8-flash/recovery_manifest.json`. It resumed again from task 14 after another stalled request, recorded in `online_challenge_recovery2_manifest.json`, and reran the final task after a third stall (`online_challenge_recovery3_manifest.json`). The frozen challenge run likewise resumed for its final three tasks after a provider stall; its incomplete task was archived in `offline_challenge_recovery_manifest.json` under the same interrupted output root. Frozen offline and independently adaptive online runs use `quick2h_test_normal_v2` (21 tasks) and `quick2h_test_challenge_v2` (18 tasks). The online streams each start from the initial playbook. The challenge dataset is byte-identical to `experiments/samples/quick2h_challenge_v2/test_challenge.txt`. Training TGC/SGC below are diagnostics; the four test rows are the comparison results.

| Dataset | Mode | Successful tasks | TGC | Successful families | SGC | Runner cost | Standalone E2E cost |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `quick2h_train` | offline adaptation | 12/15 | 80.0% | 4/5 | 80.0% | $2.00344368 | $2.00344368 |
| `quick2h_test_normal_v2` | offline frozen | 20/21 | 95.2% | 6/7 | 85.7% | $1.32771752 | $3.33116120 |
| `quick2h_test_normal_v2` | online adaptive | 21/21 | 100.0% | 7/7 | 100.0% | $2.58406744 | $2.58406744 |
| `quick2h_test_challenge_v2` | offline frozen | 14/18 | 77.8% | 4/6 | 66.7% | $1.58000368 | $3.58344736 |
| `quick2h_test_challenge_v2` | online adaptive | 16/18 | 88.9% | 4/6 | 66.7% | $2.78875816 | $2.78875816 |

New V2 completed-run logged usage cost (four tests): $8.28054680.
Five completed runs' logged usage, counting the historical shared adaptation once: $10.28399048. This is not an additional five-run charge for this extension.
Excluded interrupted attempts have 340 logged LLM calls and $1.54416048 in additional usage-based cost. Calls that timed out without usage are not priced here; the provider's actual bill is unverified.
New extension work including completed V2 runs and logged interrupted usage: $9.82470728; this excludes the reused historical training cost and any unlogged provider charges.

### Difficulty breakdown

| Dataset | Mode | Difficulty | Successful tasks | TGC | Successful families | SGC |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `quick2h_test_normal_v2` | offline frozen | 1 | 6/6 | 100.0% | 2/2 | 100.0% |
| `quick2h_test_normal_v2` | offline frozen | 2 | 6/6 | 100.0% | 2/2 | 100.0% |
| `quick2h_test_normal_v2` | offline frozen | 3 | 8/9 | 88.9% | 2/3 | 66.7% |
| `quick2h_test_normal_v2` | online adaptive | 1 | 6/6 | 100.0% | 2/2 | 100.0% |
| `quick2h_test_normal_v2` | online adaptive | 2 | 6/6 | 100.0% | 2/2 | 100.0% |
| `quick2h_test_normal_v2` | online adaptive | 3 | 9/9 | 100.0% | 3/3 | 100.0% |
| `quick2h_test_challenge_v2` | offline frozen | 1 | 3/3 | 100.0% | 1/1 | 100.0% |
| `quick2h_test_challenge_v2` | offline frozen | 2 | 6/6 | 100.0% | 2/2 | 100.0% |
| `quick2h_test_challenge_v2` | offline frozen | 3 | 5/9 | 55.6% | 1/3 | 33.3% |
| `quick2h_test_challenge_v2` | online adaptive | 1 | 3/3 | 100.0% | 1/1 | 100.0% |
| `quick2h_test_challenge_v2` | online adaptive | 2 | 5/6 | 83.3% | 1/2 | 50.0% |
| `quick2h_test_challenge_v2` | online adaptive | 3 | 8/9 | 88.9% | 2/3 | 66.7% |

### Paired outcomes

- normal v2: both succeed 20; offline fail → online succeed 1; offline succeed → online fail 0; both fail 0. Online − offline: TGC +4.8 pp, SGC +14.3 pp.
- normal v2 offline failures: 986aa4e_3; online failures: none.
- challenge v2: both succeed 13; offline fail → online succeed 3; offline succeed → online fail 1; both fail 1. Online − offline: TGC +11.1 pp, SGC +0.0 pp.
- challenge v2 offline failures: c8f5f44_2, c9458ed_1, c9458ed_2, c9458ed_3; online failures: 476b213_2, c8f5f44_2.

### Usage and artifact audit

| Runner | LLM calls | Prompt tokens | Cached prompt | Completion tokens | AppWorld API calls | Artifacts | Missing `complete_task` |
| --- | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| offline_adaptation | 324 | 5599702 | 4361984 | 399234 | 1664 | PASS (issues=0, missing=0, extra=0) | 0 |
| offline_normal | 406 | 8295231 | 7613696 | 130759 | 984 | PASS (issues=0, missing=0, extra=0) | 1 |
| online_normal | 452 | 7986727 | 6145536 | 423177 | 1071 | PASS (issues=0, missing=0, extra=0) | 0 |
| offline_challenge | 451 | 10035793 | 9311232 | 171938 | 1068 | PASS (issues=0, missing=0, extra=0) | 1 |
| online_challenge | 476 | 10394565 | 8598784 | 440535 | 1907 | PASS (issues=0, missing=0, extra=0) | 0 |

Cost uses logged usage and fixed rates: uncached input $0.64/M, cached input $0.08/M, completion $2.16/M. It is an estimate, not verified provider billing. Provider responses may omit optional `moderation` metadata; the audit requires the response content, usage, cost, and other recorded identity fields.

### Inputs and playbooks

| Artifact | SHA-256 |
| --- | --- |
| `quick2h_train.txt` | `b67d763e2feb7e0d948bbf506d77b8d952c901f6e029b2ec207db89c57989c5a` |
| `quick2h_test_normal_v2.txt` | `f42bacdfd70d33faf77d9cbc9be568a75e3f623d519bbc04205f7657deff4a04` |
| `quick2h_test_challenge_v2.txt` | `558ee0e389f64e5fb7fca9a02253a72dd4840df1eae19033b32d94c934086cd9` |
| initial playbook (8 bullets) | `3c4f46888c9159088c3eb8f70e879d4d28a5704ab9f15d132563ba0ee2730b7b` |
| offline playbook (72 bullets) | `ff47dbf949d06a08d47c378f1f5f891d5e700702e00af816222653123bf06028` |
| online_normal playbook (83 bullets) | `3e3da2abcd8af6875d08edc05406becca5388006e6398303e0a33c058fd40853` |
| online_challenge playbook (85 bullets) | `40c8d5f5b43ace85229a771d28d4b2454f869f11b05db81bd0d4e6e64a177c1e` |

Official V2 per-task and aggregate evaluations are under `experiments/outputs/ACE_quick2h_v1train_v2test_20261026_retry1/qwen3.8-flash/`; the completed training evaluation is under `experiments/outputs/ACE_quick2h_offline_online/qwen3.8-flash/offline_no_GT_adaptation/`. The machine-readable summary is `experiments/quick2h_ace_v1train_v2test_summary.json`.
Interrupted artifacts were moved without deleting run files; see `experiments/outputs/archived_incomplete_test_runs_20261026.ACEv2/ARCHIVE_MANIFEST.md` for restoration paths.

These samples are small and overlap with earlier intermediate experiments; treat the scores as method diagnostics, not independent full-split estimates. The model is identified by the provider alias `qwen3.8-flash`; the provider does not supply a verified immutable backend version for comparing the historical training run with these V2 tests.
