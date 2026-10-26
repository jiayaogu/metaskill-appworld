# Intermediate 8h Qwen3.8-flash ACE offline/online 实验计划

日期：2026-10-18（America/Toronto）

## 1. 目标与实验口径

本计划在 intermediate one-third 样本上，使用 verified quick2h conditional ACE 结果中的 actual model `qwen3.8-flash` 比较四个 no-GT 条件：

1. offline + test normal；
2. offline + test challenge；
3. online test normal；
4. online test challenge。

Actual model 固定为 `qwen3.8-flash`，不是 Solver 展示名 `Qwen` 或原始失败别名 `qwen3-8b`。四个条件使用同一套生成参数，只改变 playbook 的训练/更新时机和测试 split。主结果使用 AppWorld 官方严格指标，逐任务输出必须遵守仓库根目录下 `TASKLOADER_AND_EVALUATOR_AND_OUTPUT_README.md` 的 layout 和 schema。

四组条件对应五次 `appworld run`：一次共享的 offline adaptation、两次冻结 playbook 的 offline test generation，以及两次彼此隔离的 online adaptation。两个 offline 测试条件读取同一个最终 playbook，且不得修改它。共享一次 offline adaptation 与 Cursor 历史中的 offline 协议一致，也避免在完全相同的训练输入和随机设置上重复训练两次。

本计划不运行 with-GT，不启用并行 adaptation，不启用 `BulletpointAnalyzer`，也不把 `sample_size` 当作采样手段。

## 2. 已核验的输入

### 2.1 数据集清单

| Dataset name | 文件 | 场景族 | 任务数 | SHA-256 |
| --- | --- | ---: | ---: | --- |
| `intermediate_8h_train` | `data/datasets/intermediate_8h_train.txt` | 10 | 30 | `f35369eef5c7d5925d56be16b38d4b6ab4be19e9bd4a88cdb61c0033d7430bb9` |
| `intermediate_8h_test_normal` | `data/datasets/intermediate_8h_test_normal.txt` | 19 | 57 | `2d2355a0bb55e00ff72a60731b7e8ffdbc2536cdf43526721f5c993b157dbaf8` |
| `intermediate_8h_test_challenge` | `data/datasets/intermediate_8h_test_challenge.txt` | 46 | 138 | `c27f9d6df4e5967f57a67ab981c98a97193adfd1e00306f89dc7529c035e9795` |

三份文件与 `experiments/samples/intermediate_1of3/{train,test_normal,test_challenge}.txt` 逐字节一致。每个入选场景族都保留 `_1`、`_2`、`_3` 三个变体。运行时由 `load_task_ids(dataset_name)` 读取清单，并用 `Task.load(task_id)` 校验任务；不得手工解析清单，也不得截取文件前 N 个任务。

### 2.2 任务级输入

Generator 每题接收：

- 当前完整 playbook；
- `task.instruction`；
- `task.supervisor`；
- allowed app descriptions；
- `task.ground_truth.required_apis`；
- 本题到当前步骤为止的 ReAct 对话和环境返回。

no-GT adaptation 中，Reflector 接收当前 playbook、官方 assertion report 和裁剪后的完整对话，但 `ground_truth_code` 为空；Curator 接收任务、当前 playbook、reflection 和对话。官方 evaluator 可以读取 ground truth 来计分，但 ground-truth solution code 不进入 Generator/Reflector/Curator prompt。

### 2.3 Actual model 与固定运行参数

模型来自 `.agent-memory/CURRENT_STATUS.md` 的 `Verified quick2h conditional ACE results` 中 Qwen 的 `Actual model`。Generator、Reflector、Curator 均使用 `qwen3.8-flash`，并沿用其 quick2h retry-2 成功配置。

| Actual model | quick2h 成功配置来源 | `use_cache` | 固定价格：input / output / cache-read（USD/M tokens） |
| --- | --- | --- | --- |
| `qwen3.8-flash` | Qwen retry-2 成功别名 | `false` | 0.64 / 2.16 / 0.08 |

公共参数为：

| 参数 | 值 |
| --- | --- |
| provider | `openai`（OpenAI-compatible gateway） |
| completion method | `openai` |
| base URL | 与 verified quick2h 成功配置相同，由配置/环境提供；不得写入新 secret |
| temperature | `0` |
| model seed | `100` |
| AppWorld random seed | `123` |
| max steps | `40` |
| epochs | `1` |
| batch size | `1`（顺序 adaptation） |
| LLM call logging | `true` |
| use GT code | `false` |
| ignore multiple code blocks | `true`，只执行首个 Python block |
| overall cost guard | `$1000` per runner instance |
| configured per-task guard | `$10`，但当前 `CostTracker.exceeded()` 不可靠地强制该字段 |

初始 playbook 为：

```text
experiments/playbooks/appworld_initial_playbook.txt
```

prompts 沿用现有 no-GT 顺序配置：

```text
experiments/prompts/appworld_react_generator_prompt.txt
experiments/prompts/appworld_react_reflector_no_gt_prompt.txt
experiments/prompts/appworld_react_curator_prompt.txt
```

正式运行前必须对 `qwen3.8-flash` 做一次最小调用探测，并确认 response usage 字段可用于成本聚合。如果该名称不可用，应停止并记录错误，不得静默换成 `qwen3-8b` 或其他别名；任何模型变更都需要单独批准，并重新定义全部四个条件。

## 3. 配置、playbook 与输出命名

新增以下五份独立配置；不能修改或复用现有 full-scale/quick2h 配置文件：

```text
experiments/configs/ACE_intermediate_8h/qwen3.8-flash/offline_no_GT_adaptation.jsonnet
experiments/configs/ACE_intermediate_8h/qwen3.8-flash/offline_no_GT_evaluation_test_normal.jsonnet
experiments/configs/ACE_intermediate_8h/qwen3.8-flash/offline_no_GT_evaluation_test_challenge.jsonnet
experiments/configs/ACE_intermediate_8h/qwen3.8-flash/online_no_GT_test_normal.jsonnet
experiments/configs/ACE_intermediate_8h/qwen3.8-flash/online_no_GT_test_challenge.jsonnet
```

三个互不覆盖的最终 playbook：

```text
experiments/playbooks/intermediate_8h/qwen3.8-flash/offline_no_GT.txt
experiments/playbooks/intermediate_8h/qwen3.8-flash/online_no_GT_test_normal.txt
experiments/playbooks/intermediate_8h/qwen3.8-flash/online_no_GT_test_challenge.txt
```

输出根目录与 experiment name 一一对应：

```text
experiments/outputs/ACE_intermediate_8h/qwen3.8-flash/offline_no_GT_adaptation/
experiments/outputs/ACE_intermediate_8h/qwen3.8-flash/offline_no_GT_evaluation_test_normal/
experiments/outputs/ACE_intermediate_8h/qwen3.8-flash/offline_no_GT_evaluation_test_challenge/
experiments/outputs/ACE_intermediate_8h/qwen3.8-flash/online_no_GT_test_normal/
experiments/outputs/ACE_intermediate_8h/qwen3.8-flash/online_no_GT_test_challenge/
```

若任一目标输出根目录已存在，正式运行前必须停止并检查。不得把新任务混入旧目录；应选择新的带时间戳 run name 或在用户明确同意后归档旧目录。

## 4. 执行 DAG 与每阶段 input/output

以下 DAG 使用 `qwen3.8-flash` 执行一次；offline、online-normal、online-challenge 的 playbook 路径彼此隔离。

```text
initial playbook
      |
      +--> offline adaptation on train --> frozen offline playbook
      |                                      |--> offline test normal --> official aggregate
      |                                      `--> offline test challenge --> official aggregate
      |
      +--> online test normal (independent evolving playbook) --> official aggregate
      |
      `--> online test challenge (independent evolving playbook) --> official aggregate
```

### A. 共享 offline adaptation

Input：

- dataset：`intermediate_8h_train`（30 tasks / 10 families）；
- actual model：`qwen3.8-flash`，三个 ACE 角色均使用该模型；
- initial playbook：`appworld_initial_playbook.txt`；
- Generator + Reflector + Curator；
- no-GT prompts 和上表固定参数。

每题状态转移：

1. Generator 使用当前 playbook 执行最多 40 个 ReAct step；
2. 到达 `complete_task()` 或 overall cost guard 后，`evaluate_task()` 读取最终 DB 并生成 assertion report；
3. Reflector 使用 report 与轨迹反思，但不读取 GT solution code；
4. Curator 只允许向白名单 section 提交 `ADD`，合法条目追加到 playbook；
5. 更新后的完整 playbook 写回最终文件，供下一训练题使用。当前题不会在 no-GT 模式下因新 lesson 而重试。

Output：

- 30 个完整 task output directories；
- 每题训练期 assertion report；
- Generator、Reflector、Curator 的 `lm_calls.jsonl`；
- 最终 offline playbook，以及当前实现每 30 题生成的辅助 snapshot；
- `evaluations/intermediate_8h_train.{json,txt}` 形式的诊断性官方评测。训练集指标只作 sanity check，不作为四条件主结果。

### B. Offline + test normal

Input：

- dataset：`intermediate_8h_test_normal`（57 tasks / 19 families）；
- actual model：`qwen3.8-flash`；
- A 阶段最终 offline playbook 的冻结副本；
- 仅 Generator，不创建 Reflector/Curator。

Output：

- 57 个完整 task output directories；
- `evaluations/intermediate_8h_test_normal.json`；
- `evaluations/intermediate_8h_test_normal.txt`；
- 主结果报告中的 offline-normal 行。

验收时比较运行前后 offline playbook SHA-256，必须完全相同。

### C. Offline + test challenge

Input：

- dataset：`intermediate_8h_test_challenge`（138 tasks / 46 families）；
- actual model：`qwen3.8-flash`；
- 与 B 阶段完全相同的冻结 offline playbook；
- 仅 Generator，不创建 Reflector/Curator。

Output：

- 138 个完整 task output directories；
- `evaluations/intermediate_8h_test_challenge.json`；
- `evaluations/intermediate_8h_test_challenge.txt`；
- 主结果报告中的 offline-challenge 行。

验收时再次确认 offline playbook hash 未改变。必须先执行 138 个 challenge 任务，再调用 aggregate evaluator；不能重现历史上“没有 challenge trajectories 就直接 evaluate”的错误。

### D. Online test normal

Input：

- dataset：`intermediate_8h_test_normal`（57 tasks / 19 families）；
- actual model：`qwen3.8-flash`；
- 全新读取 `appworld_initial_playbook.txt`，不得从 offline 最终 playbook 启动；
- Generator + Reflector + Curator；
- 独立的 online-normal 最终 playbook 路径。

每题同时是测试和 adaptation：先执行并对最终 DB 计分，再 reflection/curation。第 i 题写入的 ADD 只影响第 i+1 题及以后，不改变第 i 题成绩，也不触发第 i 题重跑。

Output：

- 57 个完整 task output directories；
- 独立的 online-normal 最终 playbook；
- `evaluations/intermediate_8h_test_normal.{json,txt}`；
- 主结果报告中的 online-normal 行。

### E. Online test challenge

Input：

- dataset：`intermediate_8h_test_challenge`（138 tasks / 46 families）；
- actual model：`qwen3.8-flash`；
- 再次从全新的 `appworld_initial_playbook.txt` 启动，不能继承 online-normal 或 offline playbook；
- Generator + Reflector + Curator；
- 独立的 online-challenge 最终 playbook 路径。

Output：

- 138 个完整 task output directories；
- 独立的 online-challenge 最终 playbook；
- `evaluations/intermediate_8h_test_challenge.{json,txt}`；
- 主结果报告中的 online-challenge 行。

## 5. 运行与评测命令

从 `ace-appworld/` 执行。按依赖顺序完成并验收每个阶段，不把五个 runner 无监督并发启动：

```bash
source .venv-clean-appworld/bin/activate
export APPWORLD_PROJECT_PATH="$PWD"

appworld run ACE_intermediate_8h/qwen3.8-flash/offline_no_GT_adaptation --root .
appworld evaluate ACE_intermediate_8h/qwen3.8-flash/offline_no_GT_adaptation intermediate_8h_train --root .

appworld run ACE_intermediate_8h/qwen3.8-flash/offline_no_GT_evaluation_test_normal --root .
appworld evaluate ACE_intermediate_8h/qwen3.8-flash/offline_no_GT_evaluation_test_normal intermediate_8h_test_normal --root .

appworld run ACE_intermediate_8h/qwen3.8-flash/offline_no_GT_evaluation_test_challenge --root .
appworld evaluate ACE_intermediate_8h/qwen3.8-flash/offline_no_GT_evaluation_test_challenge intermediate_8h_test_challenge --root .

appworld run ACE_intermediate_8h/qwen3.8-flash/online_no_GT_test_normal --root .
appworld evaluate ACE_intermediate_8h/qwen3.8-flash/online_no_GT_test_normal intermediate_8h_test_normal --root .

appworld run ACE_intermediate_8h/qwen3.8-flash/online_no_GT_test_challenge --root .
appworld evaluate ACE_intermediate_8h/qwen3.8-flash/online_no_GT_test_challenge intermediate_8h_test_challenge --root .
```

`appworld run` 负责生成 trajectories 和最终 DB；`appworld evaluate` 对已存在的 DB 做官方全数据集汇总，并补齐/刷新每题 `evaluation/report.md`。评测命令不调用 LLM，也不更新 playbook。

## 6. 强制 output layout 与验收

上述五个 runner 对每个已执行任务都必须产生：

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

验收脚本必须检查：

- 五个 runner 的 task directory 数量分别为 30、57、138、57、138；
- 每个 dataset 中 `evaluations/*.json` 的 `individual` 数量与 manifest 相同；
- 所有 task ID 都来自对应 manifest，且没有缺失或额外 ID；
- 上述目录和文件全部存在；`checkpoints/` 可以为空，但必须存在；
- `api_calls.jsonl`、`lm_calls.jsonl` 每行均为合法 JSON；
- `environment_io.md` 包含编号 interaction、Python code fence 和环境返回 fence；
- `evaluation/report.md` 包含 `Overall Stats`、`Passes`、`Fails`；
- offline evaluation 的 `lm_calls.jsonl` 只有 Generator 调用；正常到达 `complete_task()` 或 cost guard 的 offline adaptation/online 任务还应包含任务结束后的 Reflector/Curator 调用，step-cap 例外必须单独列出；
- aggregate summary 只是附加产物，不能替代 task-level outputs。

如果任务达到 40-step 上限而没有正常调用 `complete_task()`，仍需保留完整 DB/logs，并通过随后执行的 `appworld evaluate` 生成官方 report；最终报告中单独统计这类任务。

## 7. 指标与结果汇报

### 7.1 官方主指标

`qwen3.8-flash` 的四条件主表必须报告：

- Task Goal Completion（TGC，严格任务成功率）；
- Scenario Goal Completion（SGC，场景族三个变体全部成功）；
- 成功任务数 / 总任务数；
- 成功场景数 / 总场景数；
- difficulty 1/2/3 各自的 TGC 与 SGC。

当前结果表（已完成结果取自官方 aggregate evaluation；Cost 按第 7.3 节固定费率后处理）。其中 offline adaptation 是训练集诊断行，后四行是四条件测试主表：

| Actual model | Split | Mode | Tasks | Families | TGC | SGC | D1 TGC/SGC | D2 TGC/SGC | D3 TGC/SGC | Cost (USD) | 状态 |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- | ---: | --- |
| `qwen3.8-flash` | train | offline adaptation | 30 | 10 | **90.0% (27/30)** | **70.0% (7/10)** | 100.0% / 100.0% | 91.7% / 75.0% | 66.7% / 0.0% | **$4.09760184** | 已完成；训练集 sanity check，非测试主结果 |
| `qwen3.8-flash` | normal | offline frozen | 57 | 19 | **91.2% (52/57)** | **84.2% (16/19)** | 100.0% / 100.0% | 86.7% / 80.0% | 85.7% / 71.4% | **$4.10846888 test-only; $8.20607072 incl. shared adaptation** | 已完成并通过 official evaluation |
| `qwen3.8-flash` | normal | online adaptive | 57 | 19 | **89.5% (51/57)** | **84.2% (16/19)** | 90.5% / 85.7% | 100.0% / 100.0% | 81.0% / 71.4% | **$9.88644232** | 已完成并通过 official evaluation |
| `qwen3.8-flash` | challenge | offline frozen | 138 | 46 | **84.8% (117/138)** | **71.7% (33/46)** | 95.8% / 87.5% | 92.2% / 82.3% | 74.6% / 57.1% | **$15.18353976 test-only; $19.28114160 incl. shared adaptation** | 已完成并通过 official evaluation |
| `qwen3.8-flash` | challenge | online adaptive | 138 | 46 | **94.2% (130/138)** | **84.8% (39/46)** | 95.8% / 87.5% | 92.2% / 76.5% | 95.2% / 90.5% | **$47.73720088** | 已完成并通过 official evaluation |

已完成 runner 的指标来源：

- offline adaptation：`offline_no_GT_adaptation/evaluations/intermediate_8h_train.json`；
- offline-normal：`offline_no_GT_evaluation_test_normal/evaluations/intermediate_8h_test_normal.json`；
- offline-challenge：`offline_no_GT_evaluation_test_challenge/evaluations/intermediate_8h_test_challenge.json`；
- online-normal：`online_no_GT_test_normal/evaluations/intermediate_8h_test_normal.json`；
- online-challenge：`online_no_GT_test_challenge/evaluations/intermediate_8h_test_challenge.json`；
- 成本均由各 task 的 `logs/lm_calls.jsonl` 聚合，未采用原生 `misc/cost.txt` 中不可用的零值。

五个 runner 的固定费率项目总成本为 **$81.01325368**；共享 offline adaptation 只计一次。

### 7.2 Offline/online 配对比较

对 normal 和 challenge 分别用同一 task ID 做迁移表：

- offline 成功、online 成功；
- offline 失败、online 成功；
- offline 成功、online 失败；
- offline 失败、online 失败；
- online − offline 的 TGC/SGC 绝对百分点变化。

这能同时显示 online adaptation 的收益与 negative transfer，沿用历史 full-scale 分析口径。

### 7.3 成本与运行诊断

每个 runner 另报：

- LLM call 数；
- prompt、cached prompt、completion token 数；
- 固定 provider 价格下的 USD 成本总计和每任务均值；
- AppWorld API call 数；
- 达到 40-step 上限的任务数；
- 缺失/无效 artifact 数；
- 初始与最终 playbook 的 SHA-256、字符数和 bullet 数。

成本以 `logs/lm_calls.jsonl` 的 usage 和运行前冻结的 `openai_cost_registry.json` 快照为准。`qwen3.8-flash` 的固定价格为 input `$0.64/M`、output `$2.16/M`、cache-read `$0.08/M`；虽然配置使用 `use_cache=false`，聚合器仍应按实际 usage 字段处理 cached tokens。cached tokens 必须先从普通 prompt tokens 中扣除，再按 cache-read 价格计费，不能重复收费。若运行前 provider 价格已变化，必须保留 quick2h 固定口径用于横向可比，同时另列新口径，不得无说明覆盖。`misc/cost.txt` 必须存在，但由于 native tracker 与自定义 gateway 的历史不一致，它不是最终报告的唯一成本来源。

offline 成本分三列报告：共享 adaptation cost、该 split 的 frozen test-generation cost、二者相加的 standalone end-to-end cost。项目总花费只计算一次共享 adaptation，不在 normal 和 challenge 之间重复累加。online 成本包含该测试流上的 Generator、Reflector 和 Curator。

### 7.4 持久化汇总

官方结果保留在各 experiment output 的 `evaluations/*.json|txt`。另外生成不会替代官方 artifacts 的可审计汇总：

```text
experiments/intermediate_8h_ace_offline_online_report.md
experiments/intermediate_8h_ace_offline_online_summary.json
```

汇总 JSON 至少记录 dataset checksum、config path、experiment name、代码/data 版本、requested solver label `Qwen`、actual model `qwen3.8-flash`、参数、playbook hashes、官方指标、token/cost 口径、artifact audit 和运行时间。所有主表和成本表以 actual model 为主键，不用 Solver 名 `Qwen` 或失败别名 `qwen3-8b` 替代 provider alias。这样即使被 `.gitignore` 忽略的 `experiments/outputs/` 未被提交，仍有可审查的结果索引；原始 outputs 仍需另行归档或制作 checksum manifest。

## 8. 与 Cursor 历史和当前实现的一致性

本协议与历史结论一致：

- offline 先在 train 上顺序更新 playbook，再冻结后用于 test；测试题之间不更新 memory；
- online 不存在独立训练阶段，直接在有序测试流上边测边更新；
- no-GT lesson 在任务评测后产生，只能影响后续任务，不能修复刚失败的当前任务；
- 顺序 Generator 接收完整 playbook，不存在显式 top-k retrieval；
- 顺序 Curator 只允许 ADD，JSON/schema/section whitelist 是格式 gate，不是 assertion coverage 或语义正确性 gate；
- full-scale 历史实验使用 `deepseek-v3`，但本次 intermediate 实验按用户指定和 verified quick2h conditional 的 `Actual model` 列使用 `qwen3.8-flash`；公共参数仍为 temperature 0、seed 100、40 steps；
- 过去 challenge 汇总失败是因为只生成了 normal trajectories；本计划为 challenge 明确安排 generation 和 aggregate evaluation 两个步骤；
- `appworld evaluate` 使用官方 `evaluate_dataset()` 生成 TGC/SGC 和逐任务 assertion report。

## 9. 执行前/后门禁

执行前：

1. 记录 root 与 nested repository 的 HEAD/dirty status，不覆盖现有用户修改；
2. 校验三个 manifest checksum、30/57/138 任务数和 10/19/46 场景族；
3. 用 `load_task_ids()` 和 `Task.load()` 对全部 225 个唯一任务做只读预检；
4. 验证三个 playbook 目标路径互不相同，两个 online runner 的 initial hash 相同；
5. 渲染五份 Jsonnet 配置并检查 actual model、`dataset`、run type、playbook path 和 `use_cache=false`；
6. 对 `qwen3.8-flash` 做 provider/model/usage-field smoke test；
7. 确认目标 output roots 不存在，并记录成本注册表快照。

执行后：

1. 对五个 runner 做逐任务 layout/schema audit；
2. 对四个测试条件运行官方 aggregate evaluator；
3. 验证 offline playbook 在两个测试 run 前后 hash 不变；
4. 验证两个 online run 都从相同 initial hash 开始，且 split 之间没有互相继承；
5. 从官方 JSON 生成四条件主表、difficulty 表和迁移表；
6. 从 LLM/API logs 聚合 tokens、calls 和固定价格成本；
7. 写入 Markdown/JSON 汇总与 checksum manifest；
8. 更新 `.agent-memory/CURRENT_STATUS.md`，如实验协议产生新决策则追加 `.agent-memory/DECISIONS.md`，不覆盖历史记录。

## 10. 时间与风险

共享一次 offline 训练后，五次 runner 共执行 420 个任务：`30 + 57 + 138 + 57 + 138`。按采样文档的 2.2 分钟/任务粗估约 924 分钟（15 小时 24 分钟），不含 provider 重试、aggregate evaluation、artifact audit 和失败恢复。若为 normal/challenge 重复 offline training，会增加 30 次任务执行且没有新的实验信息，因此本计划不重复。

主要风险：provider alias 失效、长任务达到 step cap、native cost 为零或累计口径不清、输出目录局部完成后错误续跑、append-only playbook 负迁移，以及 outputs/reports 被 Git 忽略。应通过模型预检、独立 run name、逐任务 audit、固定价格后处理和持久化 summary/checksum 降低风险。
