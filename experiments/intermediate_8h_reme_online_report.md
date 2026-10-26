# ReMe AppWorld 三臂正式实验结果与执行流程

完成日期：2026-10-25。正式 campaign：`formal12-20261025-a`。本报告依据 12 份已完成的 `run_manifest.json`、官方 `evaluations/<dataset>.json`、各 run 的 `cost_evidence.json`，以及逐任务审计和正式调用账本。此前的[执行计划](intermediate_8h_reme_online_plan.md)记录的是启动前方案；本报告记录实际执行结果。

## 实验范围与方法

在四条独立、按数据集文件顺序执行的测试流上，分别运行 fixed、dynamic 和 cold start 三个 ReMe arm；每个单元只运行一次（`r01`，`num_trials=1`），共 12 runs、702 个主任务。`intermediate_8h_test_normal` 有 57 个任务 / 19 个场景，`intermediate_8h_test_challenge` 有 138 / 46，`quick2h_test_normal_v2` 有 21 / 7，`quick2h_test_challenge_v2` 有 18 / 6。`8h` 和 `2h` 是采样套件名称，并非本次 run 的限时。

三个 arm 基于 ReMe `2f37a15` 的 AppWorld ReAct 执行器和 `reme2` 服务，并应用本实验批准的模型、顺序及审计适配。聊天模型是 `qwen3.8-flash`；导入、检索和新增经验使用 1024 维 `text-embedding-v4`。执行器每轮 `temperature=0.9`、`seed=0`、`enable_thinking=False`，最多 30 次交互。`batch_size=1`，同一 run 内任务逐个提交；campaign 最多同时运行三个彼此隔离的 run。固定和动态 arm **各自在每条测试流开始前**导入相同字节的 207 条随源码附带的 `appworld_qwen3_8b.jsonl`；cold start 从空集合开始。该预置经验文件缺乏训练任务来源清单，因此不能声称它由这里的 intermediate 或 quick2h 训练子集生成。

| Arm | 初始经验 | 检索 | 测试中总结/新增 | 记录检索经验的频次/效用 | 删除 |
|---|---|---|---|---|---|
| fixed | 独立导入 207 条 | 是 | 否 | 是 | 否 |
| dynamic | 独立导入同样的 207 条 | 是 | 是；只有严格成功才调用新增 | 是 | 是 |
| cold start | 空集合 | 是 | 与 dynamic 相同 | 是 | 是 |

fixed 冻结的是经验 ID、成员关系和正文；`record_task_memory` 仍可改变频次和效用元数据。dynamic 与 cold start 的更新流程相同，差别是起始集合。三个 arm、四条数据流使用各自的服务端口、Elasticsearch 集合和输出目录；前一条测试流的经验不会传给后一条。

## 主任务执行工作流

1. **读取任务并建立独立状态。** Driver 用 AppWorld 的 `load_task_ids(dataset_name)` 取得文件顺序，逐项以 `Task.load(task_id, load_ground_truth=False)` 预检。run 创建自己的 `run_manifest.json`、ReMe 集合及初始经验快照和 checkpoint zero；随后用 `AppWorld(task_id, experiment_name=<run_base>_run_0)` 打开任务。AppWorld 从任务输入建立独立的应用数据库输出目录。正式 runner 在求解前通过隔离的官方评估进程计算 `before_score`；私人断言和参考答案由评估端使用，没有传入执行器的提示词。
2. **检索经验并组装提示词。** `prompt_messages()` 将 supervisor 信息、应用说明和当前任务指令放进 `NEW_PROMPT_TEMPLATE`。它向本 run 的 `retrieve_task_memory` 发送原始任务指令，取最多五条相关经验；本次配置关闭 LLM 重排、分数过滤与查询改写。检索结果附在任务提示词中。检索覆盖本 run 当前集合，不按场景家族过滤，因此只能利用初始池和已经提交的先前任务更新。
3. **在 ReAct 轮次中确定 API 做法。** 本方法没有独立的 API 规划模型调用，也没有可单独读取的预先生成计划文件。执行器在普通回答中形成做法，可通过 `apis.api_docs.show_app_descriptions()`、`show_api_descriptions()`、`show_api_doc()` 查看说明，再决定下一段 Python 代码。具体采用的 API 和任何自然语言计划只能从该任务的 `logs/environment_io.md`、`logs/api_calls.jsonl` 和保留的轨迹中回溯；这些是执行证据，不应误称为事前规划产物。
4. **调用模型并执行应用 API。** 每轮向 `qwen3.8-flash` 发起 chat completion，取回答中的第一段 Python 代码，交给 `world.execute(code)`；环境返回的文本再追加到下一轮模型上下文。代码可读取或修改 AppWorld 应用状态，也可调用 `apis.supervisor.complete_task(answer=...)`。最多 30 轮，遇到 `world.task_completed()` 提前停止。模型物理请求记在 `logs/lm_calls.jsonl`；应用 API 调用的方法、URL 和入参记在 `logs/api_calls.jsonl`。
5. **保存返回与数据库。** `world.execute()` 将执行代码和**环境向执行器呈现的输出文本**写入 `logs/environment_io.md`，随后将当前应用 DB 变更保存至 `tasks/<task_id>/dbs/`，并保存 API/环境日志；任务初始化也保存初态。`api_calls.jsonl` 本身不保存每个 API 的完整响应体。若代码没有打印某个返回值，也不能假定该返回值完整留在环境输出中；模型请求/响应另由 `lm_calls.jsonl` 记录。`complete_task` 的确认消息和任务状态会保存，但该确认不等于通过官方测试。AppWorld 的应用 DB 与 ReMe 的 Elasticsearch 经验库是两套不同状态。
6. **评分后更新经验。** 执行结束时，隔离评估进程从已保存的应用 DB 计算 `after_score`，`uplift_score = after_score - before_score`。dynamic/cold 对成功和失败轨迹都会调用 `summary_task_memory`（轨迹预处理、成功/失败/比较提取、验证、去重）；这个调用只产生候选经验，不会自动写入。仅当 `after_score == 1` 时才调用 `add_task_memory`。三个 arm 都用 `record_task_memory` 更新本任务检索到的经验的频次，并在严格成功时提高效用；dynamic/cold 随后调用 `delete_task_memory`，条件是 `freq >= 5` 且 `utility/freq < 0.5`。合法的失败任务照常提交，失败也可能影响旧经验元数据及删除判断。
7. **核对、提交，再继续。** 任务关闭后再次运行官方 `evaluate_task(..., save_report=True)`，将其 `passes / (passes + failures)` 与用于经验更新的 `after_score` 核对。审计还检查应用 DB、模型和 API 日志、记忆 HTTP 事件的顺序和确认、成本账本及 checkpoint。完整的经验记录与 1024 维向量先写入 checkpoint，再发布不可变任务 commit；只有完成提交才开始下一任务。全部任务结束后，官方 `evaluate_dataset(..., save_reports=True)` 生成 `evaluations/<dataset>.json` 和 `.txt`。

### 官方测试怎样评分

AppWorld 的任务专属评估代码读取起始和最终应用 DB、公开/私有测试数据及必要时的标准答案，执行断言。断言可以检查 `complete_task` 的答案，也可以检查应用记录新增、删除、修改后的实际状态。每任务断言数并非固定：本次官方输出中最少 2、最多 14 条；四个数据集在**一个 arm 的最终聚合**中分别有 384、1,110、126、132 条断言槽位，合计 1,752；三个 arm 的 12 份最终聚合共覆盖 5,256 条。求解前、求解后、关闭任务后和数据集聚合阶段会再次运行评估，因此 5,256 是最终聚合记录的断言槽位数，不能解释为全部评估调用的总执行次数。

单项 reward 为 `通过断言数 / 该任务断言总数`，范围 0–1，供 ReMe 更新决策使用；正式 **TGC** 采用更严格的二值判定：只有该任务所有断言都通过才算成功。**SGC** 是场景级严格成功率：同一场景的所有任务变体都成功，场景才计 1。D1/D2/D3 来自官方逐任务 JSON 的 `individual[task_id].difficulty` 字段。下表的分子按 `success == true` 逐项计数，而不是把部分断言分数当作任务成功。

## 正式结果：TGC、SGC 与成本

表中的 arm 链接直接指向相应 run 目录。成本含该 run 的初始化导入、执行器以及 ReMe 记忆服务产生的实际物理模型调用，按固定费率和记录的 usage 估算：chat 每百万未缓存输入 / 缓存输入 / 输出 token 分别为 $0.64 / $0.08 / $2.16；embedding 每百万输入 token 为 $0.07。`billed_dollars` 在这 12 组中均为 `null`，故不表示账单实收金额。`Calls` 是已归属且结算的物理请求数；经验数为初始 → 最终。

| 数据集 | Arm / run 目录 | TGC | SGC | Calls | 经验数 | Cost (USD) |
|---|---|---:|---:|---:|---:|---:|
| intermediate normal (57 / 19) | [fixed][in-f] | 37/57 (64.9%) | 8/19 (42.1%) | 1,128 | 207 → 207 | $1.59500344 |
| intermediate normal | [dynamic][in-d] | 43/57 (75.4%) | 11/19 (57.9%) | 1,508 | 207 → 201 | $2.64533523 |
| intermediate normal | [cold start][in-c] | 41/57 (71.9%) | 10/19 (52.6%) | 1,477 | 0 → 12 | $2.38837501 |
| intermediate challenge (138 / 46) | [fixed][ic-f] | 68/138 (49.3%) | 15/46 (32.6%) | 3,233 | 207 → 207 | $5.61754780 |
| intermediate challenge | [dynamic][ic-d] | 69/138 (50.0%) | 15/46 (32.6%) | 4,257 | 207 → 168 | $9.07258326 |
| intermediate challenge | [cold start][ic-c] | 67/138 (48.5%) | 12/46 (26.1%) | 4,357 | 0 → 10 | $9.55702753 |
| quick2h normal v2 (21 / 7) | [fixed][qn-f] | 16/21 (76.2%) | 3/7 (42.9%) | 413 | 207 → 207 | $0.68752144 |
| quick2h normal v2 | [dynamic][qn-d] | 19/21 (90.5%) | 6/7 (85.7%) | 549 | 207 → 208 | $0.80635436 |
| quick2h normal v2 | [cold start][qn-c] | 18/21 (85.7%) | 5/7 (71.4%) | 563 | 0 → 8 | $0.95681588 |
| quick2h challenge v2 (18 / 6) | [fixed][qc-f] | 10/18 (55.6%) | 1/6 (16.7%) | 443 | 207 → 207 | $0.71994577 |
| quick2h challenge v2 | [dynamic][qc-d] | 11/18 (61.1%) | 1/6 (16.7%) | 582 | 207 → 206 | $1.00481352 |
| quick2h challenge v2 | [cold start][qc-c] | 10/18 (55.6%) | 3/6 (50.0%) | 538 | 0 → 5 | $0.82194460 |
| **12-run 合计（按任务/场景汇总）** | — | **409/702 (58.3%)** | **90/234 (38.5%)** | **19,048** | 各 run 独立 | **$35.87326784** |

各 run 只执行一次，表中百分比是观察结果，没有重复运行的方差或置信区间。官方 cold-start intermediate challenge 文件报告 TGC 48.5%；其整数计数 67/138 的直接商为 48.5507%，显示差异来自官方聚合的一位小数计算口径，逐任务成功标记与 reward 核对一致。按 arm 汇总：fixed TGC 131/234、SGC 27/78、$8.62001845；dynamic 142/234、33/78、$13.52908637；cold start 136/234、30/78、$13.72416302。dynamic 在四条流的任务成功数都不低于 fixed；这只是单次运行的配对观察，不构成统计显著性结论。

## 按官方难度 D1/D2/D3 的 TGC

每格为 **严格成功任务数 / 该难度任务数（百分比）**。同一数据集的三个 arm 共享完全相同的任务与难度分母。这里统计的是任务 TGC，不是断言通过率或场景 SGC。

| 数据集 | Arm | D1 TGC | D2 TGC | D3 TGC |
|---|---|---:|---:|---:|
| intermediate normal | fixed | 18/21 (85.7%) | 7/15 (46.7%) | 12/21 (57.1%) |
| intermediate normal | dynamic | 19/21 (90.5%) | 8/15 (53.3%) | 16/21 (76.2%) |
| intermediate normal | cold start | 18/21 (85.7%) | 8/15 (53.3%) | 15/21 (71.4%) |
| intermediate challenge | fixed | 19/24 (79.2%) | 26/51 (51.0%) | 23/63 (36.5%) |
| intermediate challenge | dynamic | 20/24 (83.3%) | 26/51 (51.0%) | 23/63 (36.5%) |
| intermediate challenge | cold start | 21/24 (87.5%) | 23/51 (45.1%) | 23/63 (36.5%) |
| quick2h normal v2 | fixed | 6/6 (100.0%) | 3/6 (50.0%) | 7/9 (77.8%) |
| quick2h normal v2 | dynamic | 6/6 (100.0%) | 4/6 (66.7%) | 9/9 (100.0%) |
| quick2h normal v2 | cold start | 6/6 (100.0%) | 3/6 (50.0%) | 9/9 (100.0%) |
| quick2h challenge v2 | fixed | 2/3 (66.7%) | 5/6 (83.3%) | 3/9 (33.3%) |
| quick2h challenge v2 | dynamic | 2/3 (66.7%) | 5/6 (83.3%) | 4/9 (44.4%) |
| quick2h challenge v2 | cold start | 1/3 (33.3%) | 6/6 (100.0%) | 3/9 (33.3%) |

Intermediate challenge 的 D3 在三个 arm 均为 23/63（36.5%），是本组难度切分中最明显的共同低分区域；quick2h challenge 每种难度只有 3、6 或 9 个任务，单个任务会使百分比明显跳动。跨数据集或跨难度比较时应同时看分子和分母。

## 产物位置与完整性

全部 run 保存在 `ace-appworld/experiments/outputs/`，命名规则是 `reme_formal12-20261025-a_<dataset>_<arm>_r01_qwen3.8-flash_run_0/`；上表的 arm 链接给出了 12 个**实际目录名**。每个目录包含 `run_manifest.json`、`tasks/<task_id>/dbs/`、`tasks/<task_id>/logs/{api_calls.jsonl,environment_io.md,lm_calls.jsonl}`、`tasks/<task_id>/evaluation/report.md`、`baseline_artifacts/reme/<task_id>/{memory_events.jsonl,task_audit.json}`、经验初末快照、`cost_evidence.json` 及官方 `evaluations/<dataset>.{json,txt}`。例如 [quick2h normal fixed 官方 JSON][qn-f-eval] 可逐任务核对成功与难度字段；[campaign queue][queue] 和 [coordinator summary][summary] 给出调度终态，跨 run 的物理请求记于[正式账本][ledger]。

最终审计核对了 12/12 个 complete 且已释放的 run、702/702 个主任务、714/714 个初始化和任务不可变 commit/checkpoint、全部哈希链及 1024 维向量、最终经验、官方 reward 和成本账本。19,048 条物理请求的 start 与 settle 一一对应，canonical 任务日志 ID 也一一匹配；failed、unknown、unsettled、duplicate、orphan、retry、recovery 计数均为零。估算成本合计使用 179,862,399 tokens。Coordinator 的历史摘要留有一个所有 run 完成后 worker-1 在退出阶段被 SIGTERM 的记录；任务、计分和成本产物均已完整提交，此退出竞态在 campaign 结束后修复，不能追溯视为本次运行源码的一部分。

实现核查入口：[formal driver](../../../reme-2f37a15-qwen38/benchmark/appworld/execution_matrix.py)、[ReAct agent](../../../reme-2f37a15-qwen38/benchmark/appworld/appworld_react_agent.py)、[记忆服务流程](../../../reme-2f37a15-qwen38/reme/config/service.yaml)、[AppWorld 环境持久化](../src/appworld/environment.py)、[官方评估器](../src/appworld/evaluator.py)。

[in-f]: outputs/reme_formal12-20261025-a_intermediate_8h_test_normal_fixed_r01_qwen3.8-flash_run_0/
[in-d]: outputs/reme_formal12-20261025-a_intermediate_8h_test_normal_dynamic_r01_qwen3.8-flash_run_0/
[in-c]: outputs/reme_formal12-20261025-a_intermediate_8h_test_normal_cold_start_r01_qwen3.8-flash_run_0/
[ic-f]: outputs/reme_formal12-20261025-a_intermediate_8h_test_challenge_fixed_r01_qwen3.8-flash_run_0/
[ic-d]: outputs/reme_formal12-20261025-a_intermediate_8h_test_challenge_dynamic_r01_qwen3.8-flash_run_0/
[ic-c]: outputs/reme_formal12-20261025-a_intermediate_8h_test_challenge_cold_start_r01_qwen3.8-flash_run_0/
[qn-f]: outputs/reme_formal12-20261025-a_quick2h_test_normal_v2_fixed_r01_qwen3.8-flash_run_0/
[qn-d]: outputs/reme_formal12-20261025-a_quick2h_test_normal_v2_dynamic_r01_qwen3.8-flash_run_0/
[qn-c]: outputs/reme_formal12-20261025-a_quick2h_test_normal_v2_cold_start_r01_qwen3.8-flash_run_0/
[qc-f]: outputs/reme_formal12-20261025-a_quick2h_test_challenge_v2_fixed_r01_qwen3.8-flash_run_0/
[qc-d]: outputs/reme_formal12-20261025-a_quick2h_test_challenge_v2_dynamic_r01_qwen3.8-flash_run_0/
[qc-c]: outputs/reme_formal12-20261025-a_quick2h_test_challenge_v2_cold_start_r01_qwen3.8-flash_run_0/
[qn-f-eval]: outputs/reme_formal12-20261025-a_quick2h_test_normal_v2_fixed_r01_qwen3.8-flash_run_0/evaluations/quick2h_test_normal_v2.json
[queue]: outputs/.reme-formal-campaigns/formal12-20261025-a/queue.json
[summary]: outputs/.reme-formal-campaigns/formal12-20261025-a/coordinator_summary.json
[ledger]: ../../../reme-2f37a15-qwen38/.local-elasticsearch/formal-accounting-20261024.ledger.jsonl
