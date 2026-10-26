# Quick2h Qwen3.8-flash ACE offline/online 实验计划

日期：2026-10-18（America/Toronto）

## 0. 范围与命名澄清

本轮以用户明确指定的三个 quick2h manifest 为准：

- `data/datasets/quick2h_train.txt`；
- `data/datasets/quick2h_test_normal.txt`；
- `data/datasets/quick2h_test_challenge.txt`。

它们不是已有 `intermediate_8h_*` one-third 样本。quick2h 每个 split 含 5 个完整 scenario family、15 个 task；intermediate one-third 则是 30/57/138 tasks。为避免覆盖已经存在的 intermediate 计划、配置和 playbook，本计划使用独立的 `ACE_quick2h_offline_online` 命名空间。

本文定义实验协议；配置、provider 调用、运行和结果的当前状态以 `.agent-memory/CURRENT_STATUS.md` 为准。

## 1. 目标与四个结果条件

Actual model 固定为 provider 可调用的 `qwen3.8-flash`。比较四个 no-GT 条件：

1. **offline + test normal**：在 `quick2h_train` 上顺序 adaptation 并更新 playbook；冻结最终 playbook，在 `quick2h_test_normal` 上只做 Generator execution/evaluation，不更新 playbook。
2. **offline + test challenge**：使用同一次 `quick2h_train` adaptation 产生的同一份冻结 playbook，在 `quick2h_test_challenge` 上只做 Generator execution/evaluation，不更新 playbook。
3. **online test normal**：从初始 playbook 开始，在 `quick2h_test_normal` 有序流上边执行、边评测、边反思和更新；第 i 题的更新只影响后续题。
4. **online test challenge**：从另一份全新的初始 playbook 开始，在 `quick2h_test_challenge` 有序流上边执行、边评测、边反思和更新；不得继承 normal online 或 offline playbook。

四个结果条件对应五个 runner 阶段：

- 1 次共享 offline adaptation；
- 2 次 frozen offline evaluation generation；
- 2 次互相隔离的 online adaptation。

共享 offline adaptation 与 Cursor 历史中的 offline 协议一致。在训练输入、模型和随机设置完全相同的前提下，不为 normal/challenge 重复训练。若后续需要估计训练随机性，应另立 multi-seed 协议，而不是把两个相同训练 run 当作四条件所必需的步骤。

不运行 with-GT，不启用并行 adaptation，不启用 `BulletpointAnalyzer`，不使用 `sample_size` 截取数据集。

## 2. 输入

### 2.1 Dataset manifests

| Dataset name | Manifest | Families | Tasks | Family IDs | SHA-256 |
| --- | --- | ---: | ---: | --- | --- |
| `quick2h_train` | `data/datasets/quick2h_train.txt` | 5 | 15 | `ce359b5`, `b0a8eae`, `7d7fbf6`, `07b42fd`, `6ea6792` | `b67d763e2feb7e0d948bbf506d77b8d952c901f6e029b2ec207db89c57989c5a` |
| `quick2h_test_normal` | `data/datasets/quick2h_test_normal.txt` | 5 | 15 | `3b8fb7a`, `f323bae`, `59fae45`, `dac78d9`, `3aa1a22` | `ddffd3a8615732431098d6f173762c667428de4d8ba90922ec17feefbd08adce` |
| `quick2h_test_challenge` | `data/datasets/quick2h_test_challenge.txt` | 5 | 15 | `5238afc`, `c8f5f44`, `476b213`, `7bdaf23`, `adb1060` | `61b816fb6c9cf162383643782e0a9309e83253b2ed2be59346babbff3e402919` |

每个 family 保留 `_1`、`_2`、`_3` 三个 variant，因此官方 SGC 可以计算。运行时必须通过 `load_task_ids(dataset_name)` 读取 manifest，并用 `Task.load(task_id)` 做预检；不得手工解析文件，也不得以 `sample_size` 取文件前 N 项。

quick2h 的抽样目标、topic TV、difficulty TV、app-count TV 和 train-to-test shift 见 `experiments/quick2h_sampling.md`。该样本用于方法调试，不用于声称完整 split 的总体成功率。

### 2.2 每个 task 的 ACE 输入

Generator 每题接收：

- 当前完整 playbook；
- `task.instruction`；
- `task.supervisor`；
- allowed app descriptions / API documentation；
- `task.ground_truth.required_apis`；
- 本题截至当前 step 的 ReAct 对话与 AppWorld environment responses。

no-GT adaptation 的任务完成后：

- official evaluator 从 task ground truth 和最终 DB 生成 assertion report；
- Reflector 接收当前 playbook、assertion report 和裁剪后的执行轨迹，但 `ground_truth_code` 为空；
- Curator 接收 task、当前 playbook、reflection 和 conversation，只能提交当前顺序实现支持的合法 `ADD` operation。

Evaluator 使用 ground truth 计分不等于向 Generator、Reflector 或 Curator 暴露 ground-truth solution code。

### 2.3 模型、prompt 和固定参数

`qwen3.8-flash` 是 quick2h retry-2 成功实验中已验证的 **Actual model**；不得用曾经 provider 404 的 `qwen3-8b` 代替。Generator、Reflector 和 Curator 使用同一 model config。

| 参数 | 固定值 |
| --- | --- |
| model | `qwen3.8-flash` |
| provider | `openai`（OpenAI-compatible gateway） |
| completion method | `openai` |
| temperature | `0` |
| model seed | `100` |
| AppWorld random seed | `123` |
| max steps | `40` |
| epochs | `1` |
| batch size | `1`（顺序 adaptation） |
| LLM call logging | `true` |
| use GT code | `false` |
| use cache | `false` |
| ignore multiple code blocks | `true` |
| retry interval / max retries | `10s` / `50` |
| overall / configured per-task guard | `$1000` / `$10` |

模型 `stop`、penalty、`n` 和 `response_format` 应逐字段复制 verified quick2h retry-2 config。base URL 复用当前成功配置/环境，不在计划或日志中新增 secret。

初始 playbook：

```text
experiments/playbooks/appworld_initial_playbook.txt
```

prompts：

```text
experiments/prompts/appworld_react_generator_prompt.txt
experiments/prompts/appworld_react_reflector_no_gt_prompt.txt
experiments/prompts/appworld_react_curator_prompt.txt
```

正式运行前必须做一次最小 provider smoke test，确认 `qwen3.8-flash` 可调用且 response 包含可聚合的 usage fields。失败时停止，不得静默换模型。

## 3. 计划新增的配置、playbook 和输出路径

### 3.1 Configs

计划新增一个公共 Jsonnet library 和五份 runner config：

```text
experiments/configs/ACE_quick2h_offline_online/qwen3.8-flash/common.libsonnet
experiments/configs/ACE_quick2h_offline_online/qwen3.8-flash/offline_no_GT_adaptation.jsonnet
experiments/configs/ACE_quick2h_offline_online/qwen3.8-flash/offline_no_GT_evaluation_test_normal.jsonnet
experiments/configs/ACE_quick2h_offline_online/qwen3.8-flash/offline_no_GT_evaluation_test_challenge.jsonnet
experiments/configs/ACE_quick2h_offline_online/qwen3.8-flash/online_no_GT_test_normal.jsonnet
experiments/configs/ACE_quick2h_offline_online/qwen3.8-flash/online_no_GT_test_challenge.jsonnet
```

这些配置不得修改或复用为已有 full-scale、conditional quick2h 或 intermediate run 的 config。公共 library 只用于消除参数漂移；五份入口 config 必须显式区分 dataset、run type 和 trained playbook path。

### 3.2 Playbooks

三份互不覆盖的最终 playbook：

```text
experiments/playbooks/quick2h_offline_online/qwen3.8-flash/offline_no_GT.txt
experiments/playbooks/quick2h_offline_online/qwen3.8-flash/online_no_GT_test_normal.txt
experiments/playbooks/quick2h_offline_online/qwen3.8-flash/online_no_GT_test_challenge.txt
```

两个 frozen offline test runner 只读第一份文件。两个 online runner 各自从 `appworld_initial_playbook.txt` 初始化，并写入自己的目标文件。

### 3.3 Experiment output roots

```text
experiments/outputs/ACE_quick2h_offline_online/qwen3.8-flash/offline_no_GT_adaptation/
experiments/outputs/ACE_quick2h_offline_online/qwen3.8-flash/offline_no_GT_evaluation_test_normal/
experiments/outputs/ACE_quick2h_offline_online/qwen3.8-flash/offline_no_GT_evaluation_test_challenge/
experiments/outputs/ACE_quick2h_offline_online/qwen3.8-flash/online_no_GT_test_normal/
experiments/outputs/ACE_quick2h_offline_online/qwen3.8-flash/online_no_GT_test_challenge/
```

正式运行前若任何目标 output root 已存在，必须停止并检查；不能把新 run 混入已有目录。需要重跑时使用明确的新 run name，或在用户明确同意后归档旧目录。

## 4. 执行 DAG 与每阶段 input/output

```text
appworld_initial_playbook.txt
      |
      +--> A. offline adaptation: quick2h_train
      |         `--> frozen offline_no_GT.txt
      |                  |--> B. offline eval: quick2h_test_normal
      |                  `--> C. offline eval: quick2h_test_challenge
      |
      +--> D. online adaptation: quick2h_test_normal
      |         `--> online_no_GT_test_normal.txt
      |
      `--> E. online adaptation: quick2h_test_challenge
                `--> online_no_GT_test_challenge.txt
```

### A. 共享 offline adaptation

Input：

- dataset：`quick2h_train`（15 tasks / 5 families）；
- initial playbook：`appworld_initial_playbook.txt`；
- `qwen3.8-flash` Generator + Reflector + Curator；
- no-GT prompts 和固定参数。

每题顺序：Generator 执行 → official per-task evaluation → Reflector → Curator ADD → 将更新后的完整 playbook 持久化，供下一题使用。当前题不会因新 lesson 被重试。

Output：

- 15 个完整 task output directories；
- 每题 assertion report 和完整 logs；
- 最终 `offline_no_GT.txt`；
- 可选的训练诊断汇总 `evaluations/quick2h_train.{json,txt}`。

训练集得分只作为 adaptation sanity check，不进入四条件主表。

### B. Offline + test normal

Input：`quick2h_test_normal`、A 的 frozen playbook、仅 Generator。

Output：

- 15 个完整 task output directories；
- `evaluations/quick2h_test_normal.json`；
- `evaluations/quick2h_test_normal.txt`；
- 四条件报告的 offline-normal 行。

运行前后比较 frozen playbook SHA-256，必须相同。该 runner 不实例化 Reflector/Curator，也不写回 playbook。

### C. Offline + test challenge

Input：`quick2h_test_challenge`、与 B 完全相同的 frozen playbook、仅 Generator。

Output：

- 15 个完整 task output directories；
- `evaluations/quick2h_test_challenge.json`；
- `evaluations/quick2h_test_challenge.txt`；
- 四条件报告的 offline-challenge 行。

必须先生成 challenge trajectories/DBs，再运行 aggregate evaluator；不能重复历史上“没有 challenge outputs 就直接 evaluate”的错误。运行前后 frozen playbook hash 必须相同。

### D. Online test normal

Input：`quick2h_test_normal`、全新的 initial playbook、Generator + Reflector + Curator。

第 i 题先按最终 DB 计分，再执行 reflection/curation；其 ADD 只影响第 i+1 题及以后，不改变第 i 题分数。

Output：

- 15 个完整 task output directories；
- 独立 `online_no_GT_test_normal.txt`；
- `evaluations/quick2h_test_normal.{json,txt}`；
- 四条件报告的 online-normal 行。

### E. Online test challenge

Input：`quick2h_test_challenge`、另一份全新的 initial playbook、Generator + Reflector + Curator。

Output：

- 15 个完整 task output directories；
- 独立 `online_no_GT_test_challenge.txt`；
- `evaluations/quick2h_test_challenge.{json,txt}`；
- 四条件报告的 online-challenge 行。

E 不得继承 D 或 A 的最终 playbook。

## 5. 计划运行命令

从 `ace-appworld/` 执行，按依赖顺序逐阶段验收：

```bash
source .venv-clean-appworld/bin/activate
export APPWORLD_PROJECT_PATH="$PWD"

appworld run ACE_quick2h_offline_online/qwen3.8-flash/offline_no_GT_adaptation --root .
appworld evaluate ACE_quick2h_offline_online/qwen3.8-flash/offline_no_GT_adaptation quick2h_train --root .

appworld run ACE_quick2h_offline_online/qwen3.8-flash/offline_no_GT_evaluation_test_normal --root .
appworld evaluate ACE_quick2h_offline_online/qwen3.8-flash/offline_no_GT_evaluation_test_normal quick2h_test_normal --root .

appworld run ACE_quick2h_offline_online/qwen3.8-flash/offline_no_GT_evaluation_test_challenge --root .
appworld evaluate ACE_quick2h_offline_online/qwen3.8-flash/offline_no_GT_evaluation_test_challenge quick2h_test_challenge --root .

appworld run ACE_quick2h_offline_online/qwen3.8-flash/online_no_GT_test_normal --root .
appworld evaluate ACE_quick2h_offline_online/qwen3.8-flash/online_no_GT_test_normal quick2h_test_normal --root .

appworld run ACE_quick2h_offline_online/qwen3.8-flash/online_no_GT_test_challenge --root .
appworld evaluate ACE_quick2h_offline_online/qwen3.8-flash/online_no_GT_test_challenge quick2h_test_challenge --root .
```

`appworld run` 生成 trajectories、最终 DB 和 run logs；`appworld evaluate` 对既有 DB 运行官方 evaluator，生成/刷新逐任务 reports 和 aggregate files。evaluate 阶段不调用 LLM，也不更新 playbook。

## 6. 强制 output layout 与 schema 验收

五个 runner 的每个已执行 task 必须符合 `TASKLOADER_AND_EVALUATOR_AND_OUTPUT_README.md`：

```text
tasks/<task_id>/
├── checkpoints/
├── dbs/
│   ├── admin.jsonl
│   ├── amazon.jsonl
│   ├── api_docs.jsonl
│   ├── file_system.jsonl
│   ├── gmail.jsonl
│   ├── model_hashes.json
│   ├── phone.jsonl
│   ├── simple_note.jsonl
│   ├── splitwise.jsonl
│   ├── spotify.jsonl
│   ├── supervisor.jsonl
│   ├── todoist.jsonl
│   └── venmo.jsonl
├── evaluation/
│   ├── report.md
│   └── version.txt
├── logs/
│   ├── api_calls.jsonl
│   ├── environment_io.md
│   ├── lm_calls.jsonl
│   └── loggger.log
├── misc/
│   └── cost.txt
└── version/
    ├── code.txt
    └── data.txt
```

验收必须检查：

- 五个 runner 各有 15 个 task directory，总执行次数为 75；
- task IDs 与对应 manifest 完全一致，无缺失、无额外项；
- `checkpoints/` 即使为空也必须存在；
- DB JSONL 保持 AppWorld `[sql, params, flag]` dump format；
- `api_calls.jsonl` 每行严格为 `method`、`url`、`data` schema；
- `lm_calls.jsonl` 每行包含完整的 `id`、`input`、`output`，并保留 raw assistant text 和 usage；
- `environment_io.md` 每次 interaction 有编号 heading、分隔线、Python code fence 和 response fence；
- `evaluation/report.md` 有 `Overall Stats`、`Passes`、`Fails`；
- `misc/cost.txt` 和 version files 存在；
- aggregate summary 只作为附加产物，不能替代 task-level outputs；
- offline evaluation 的 LLM logs 只有 Generator calls；正常完成的 adaptation/online tasks 还应有任务结束后的 Reflector/Curator calls；step-cap/异常例外单独列出；
- 达到 40-step cap 的 task 仍保留 DB/logs，并由随后运行的 `appworld evaluate` 生成官方 report。

## 7. 指标与结果汇报

### 7.1 官方主指标

截至 2026-10-21 的最终结果指标主表如下。offline adaptation 训练结果与四个测试条件统一列出，但它只作为训练阶段结果，不计入四条件测试对比。四个测试条件均已完成 official aggregate evaluation；五个 runner 均通过严格 artifact/schema audit。

| Actual model | Split | Mode | Tasks | Families | Success tasks | TGC | Success families | SGC | Runner cost | Standalone E2E cost |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `qwen3.8-flash` | train | offline adaptation | 15 | 5 | 12/15 | 80.0% | 4/5 | 80.0% | $2.00344368 | $2.00344368 |
| `qwen3.8-flash` | normal | offline frozen | 15 | 5 | 15/15 | 100.0% | 5/5 | 100.0% | $0.91775736 | $2.92120104 |
| `qwen3.8-flash` | normal | online adaptive | 15 | 5 | 15/15 | 100.0% | 5/5 | 100.0% | $2.23988832 | $2.23988832 |
| `qwen3.8-flash` | challenge | offline frozen | 15 | 5 | 14/15 | 93.3% | 4/5 | 80.0% | $1.04329752 | $3.04674120 |
| `qwen3.8-flash` | challenge | online adaptive | 15 | 5 | 9/15 | 60.0% | 2/5 | 40.0% | $2.12916880 | $2.12916880 |

其中 offline adaptation 对应 `quick2h_train`；其 TGC/SGC 是训练阶段诊断指标，不属于四条件测试主结果。

Cost 来自 `logs/lm_calls.jsonl` 的实际 usage，按 input `$0.64/M`、output `$2.16/M`、cache-read `$0.08/M` 重算；cached input 已从普通 input 中扣除。五个 runner 明细为：offline adaptation 324 LLM calls、5,998,936 total tokens、$2.00344368；offline normal 281 calls、5,846,175 tokens、$0.91775736；offline challenge 321 calls、6,942,688 tokens、$1.04329752；online normal 317 calls、7,118,992 tokens、$2.23988832；online challenge 356 calls、7,362,054 tokens、$2.12916880。项目实际总成本（共享 adaptation 只计一次）为 `$8.33355568`。native `misc/cost.txt` 均为 0，不能作为权威成本。

必须报告：

- Task Goal Completion（TGC，严格成功 tasks / 全部 tasks）；
- Scenario Goal Completion（SGC，三个 variants 全部成功的 families / 全部 families）；
- 成功/失败 task 数和成功/失败 family 数；
- difficulty 1/2/3 分层的 task 数、TGC 和 SGC；若某层没有完整 family，明确标记而不伪造 SGC。

TGC 是成功率。SGC 是 family-level all-or-nothing，因此 partial-success family 会增加 TGC，但不会增加 SGC。

### 7.2 Offline/online 配对分析

normal 和 challenge 各自按同一 task ID 比较：

- offline success / online success；
- offline fail / online success；
- offline success / online fail；
- offline fail / online fail；
- online − offline 的 TGC/SGC 绝对百分点；
- family-level 迁移和产生 negative transfer 的 task IDs。

### 7.3 成本、运行与 playbook 诊断

每个 runner 报告：

- LLM call 数；
- prompt、cached prompt、completion token 数；
- provider 固定价格下的总成本和每任务平均成本；
- AppWorld API call 数；
- 40-step cap、provider error、缺失/无效 artifact 数；
- initial/final playbook SHA-256、字符数、section/bullet 数和净增长。

固定 quick2h 成本口径来自 `openai_cost_registry.json`：

- input：`$0.64 / 1M tokens`；
- output：`$2.16 / 1M tokens`；
- cache-read：`$0.08 / 1M tokens`。

虽然 `use_cache=false`，聚合器仍以实际 usage 为准；cached prompt tokens 必须从普通 prompt tokens 中扣除，不能双重计费。`misc/cost.txt` 必须存在，但历史上 native tracker 与自定义 gateway 可能不一致，因此最终成本以 `lm_calls.jsonl` usage + 冻结价格 registry 快照的后处理为主。

offline 成本分为共享 adaptation、split-specific frozen evaluation generation、二者相加的 standalone end-to-end cost。项目总花费只计算一次共享 adaptation。online 成本包括该测试流上的 Generator、Reflector、Curator。

### 7.4 Assertion 与 failure diagnostics

另外汇报：

- 每题 passed/failed assertion 数；
- step-cap 与 premature-completion task IDs；
- 如使用 `{M,I,A,P,U}` taxonomy，必须标注为人工/启发式诊断而非官方指标或已证明的因果分类；
- 失败案例引用 task-level `evaluation/report.md`、`environment_io.md` 和 `lm_calls.jsonl`，不能仅凭 aggregate JSON 推断原因。

### 7.5 持久化汇总

除官方 `evaluations/*.json|txt` 外，生成：

```text
experiments/quick2h_ace_offline_online_report.md
experiments/quick2h_ace_offline_online_summary.json
experiments/quick2h_ace_offline_online_checksums.json
```

上述三个持久化汇总已于 2026-10-21 生成；五个 runner 的 artifact audit 均为 PASS，issue、missing/extra task 和缺失 `complete_task` 数均为 0。

summary 至少记录 dataset checksums、config paths、experiment names、Git/code/data versions、actual model、参数、playbook hashes、官方指标、tokens/cost、artifact audit 和 wall-clock timestamps。outputs 当前可能被 Git ignore，因此 checksums/summary 不能替代原始 outputs 的归档。

## 8. 与 Cursor 历史和当前实现的一致性

本计划已按原始 Cursor session、当前 configs/runner 和输出契约核对：

- offline：train stream 上 adaptation，最终 playbook 冻结后用于 test，测试题之间不更新；
- online：没有独立 train stage，直接在有序 test stream 上边测边更新；
- no-GT 的 reflection/curation 在当前 task 计分后发生，只能影响后续 task，不重跑当前 task；
- 顺序 Generator 接收完整 playbook，没有显式 top-k retrieval；
- 顺序 Curator 为 ADD-only，现有 gate 主要验证 JSON、operation 和 section，不验证 lesson 的语义正确性或 assertion coverage；
- `qwen3.8-flash` 是 quick2h retry-2 已成功调用的 actual alias；`qwen3-8b` 历史上不可路由；
- verified quick2h 参数为 temperature 0、seed 100、AppWorld seed 123、40 steps、`use_cache=false`；
- 自定义 dataset 必须由 `load_task_ids()` 加载，不能用 `sample_size` 代替分层 manifest；
- challenge 必须先 run 产生 trajectories/DB，再 aggregate evaluate；
- official evaluator 生成 TGC/SGC 和 assertion reports；
- 每个 task 都必须保留 ACE/AppWorld 标准的 checkpoints、DBs、evaluation、完整 logs、misc 和 versions；
- native cost tracker 不是自定义 gateway 的可靠唯一成本源，需从 usage 按固定 registry 后处理。

## 9. 执行前/后门禁

执行前：

1. 记录 root/nested Git HEAD 与 dirty status，不覆盖现有用户修改；
2. 校验三个 manifest 的 hash、15 tasks、5 families 和每族三个 variants；
3. 用 `load_task_ids()`/`Task.load()` 预检 45 个唯一任务；
4. 渲染五份 Jsonnet，核对 actual model、dataset、run type、playbook paths、`use_cache=false`；
5. 确认 offline eval 为 `ace-evaluation`，两个 online runner 为独立 `ace-adaptation`；
6. 记录 initial playbook hash，确认两个 online run 的初始 hash 相同；
7. 做 provider/usage smoke test，冻结成本 registry 快照；
8. 确认五个 output roots 不存在。

执行后：

1. 对 75 个 task occurrences 做 layout/schema audit；
2. 对四个测试条件运行 official aggregate evaluator；
3. 验证 offline playbook 在 B/C 前后 hash 不变；
4. 验证两个 online run 从相同 initial hash 开始且互不继承；
5. 从 official JSON 生成主表、difficulty 表和 offline/online migration 表；
6. 从 LLM/API logs 聚合 calls、tokens、cost 和 step-cap diagnostics；
7. 写 Markdown、JSON summary 和 checksum manifest；
8. 更新 `.agent-memory/CURRENT_STATUS.md`；协议或解释口径有新增决策时追加 `.agent-memory/DECISIONS.md`。

## 10. 规模、时间与风险

三个 manifests 含 45 个唯一 tasks；五个 runner 总计执行 `15 + 15 + 15 + 15 + 15 = 75` 个 task occurrences。按 quick2h sampling 文档的 2.2 分钟/task 粗估约 165 分钟，不含 provider retry、aggregate evaluation、审计和失败恢复，因此“四条件”整体不再是严格两小时 wall-clock run。

主要风险：

- provider alias 或 usage schema 变化；
- step cap 导致任务没有正常 `complete_task()`；
- append-only lesson 引起 negative transfer；
- frozen playbook 被错误写回；
- online normal/challenge 之间错误继承；
- partial output 被误当作完整 run；
- native 与 post-hoc cost 不一致；
- ignored outputs/reports 缺乏持久保护；
- 5-family sample 太小，结果被过度外推。

通过模型预检、独立路径、hash invariants、逐任务 output audit、官方 evaluator、固定价格后处理和 checksummed summary 控制这些风险。
