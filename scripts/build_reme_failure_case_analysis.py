#!/usr/bin/env python3
"""Build the evidence ledger for the completed ReMe formal12 campaign.

This is a read-only analysis of run artifacts; only the requested Markdown report
is written. The P/U column describes the *post-task feedback stage*, not the
cause of the same task's failed execution. See the report's methods note.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from html import escape
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ROOT / "ace-appworld/experiments/outputs"
REPORT = ROOT / "reports/Intermediate_8h_reme_online_failure_case_analysis.md"
PREFIX = "reme_formal12-20261025-a_"
DATASETS = [
    "intermediate_8h_test_normal",
    "intermediate_8h_test_challenge",
    "quick2h_test_normal_v2",
    "quick2h_test_challenge_v2",
]
ARMS = ["fixed", "dynamic", "cold_start"]
OVERRIDES = {
    ("intermediate_8h_test_normal", "fixed", "fd1f8fa_2"): ("I", "strong"),
    ("intermediate_8h_test_normal", "fixed", "3b8fb7a_3"): ("A", "strong"),
    ("intermediate_8h_test_normal", "dynamic", "d6ac34d_1"): ("P", "strong"),
    ("intermediate_8h_test_normal", "dynamic", "d6ac34d_2"): ("P", "strong"),
    ("intermediate_8h_test_normal", "dynamic", "d6ac34d_3"): ("P", "strong"),
    ("intermediate_8h_test_challenge", "dynamic", "245cb43_3"): ("U", "strong"),
    ("quick2h_test_normal_v2", "dynamic", "3aa1a22_2"): ("P", "strong"),
    ("quick2h_test_normal_v2", "dynamic", "3aa1a22_3"): ("U", "strong"),
}

# Manually audited direct execution explanations for the exact rows requested
# by the user (the first 20 failed tasks in intermediate-normal/fixed).
FOCUSED = {
    "fd1f8fa_2": ("只取一次 show_liked_songs 的默认页（5 首），把其余已点赞队列歌曲误删；官方队列少 7 首。", "任务前已有明确的已点赞歌曲分页经验 44c5f7…，检索前快照含该 ID，top-5/提示词均缺失；I。"),
    "d6ac34d_1": ("复制昨日习惯便笺后调用 create_note 时漏传 pinned=True；新增记录为 False，预期 True。", "top-5 是认证/便笺修改等通用经验，未见 pinned 规则；fixed 不运行提炼，不能标 U；?。"),
    "d6ac34d_2": ("新建今日习惯便笺时未传 pinned=True；新增记录为 False，预期 True。", "与 _1 相同，top-5 未给出 pinned 规则；fixed 不运行提炼；?。"),
    "d6ac34d_3": ("新建今日习惯便笺时未传 pinned=True；新增记录为 False，预期 True。", "与 _1 相同，top-5 未给出 pinned 规则；fixed 不运行提炼；?。"),
    "3b8fb7a_3": ("30 轮中 26 次重复提交未闭合的 print(notes，均为 Syntax error；没有实际 Venmo 付款/请求，目标 DB 无变更。", "适用的‘便笺费用→Venmo’经验 7128f4…已检索并进入提示词，模型仍未形成可执行流程；A。"),
    "425a494_2": ("模型遍历 liked_albums 后按每张专辑的 genre 计数，而题目问专辑库里已点赞歌曲的 genre；回答 edm，标准答案 classical。", "top-5 没有针对歌曲级 genre 计数的正确规则，不能仅因有 Spotify 经验判 A；?。"),
    "2c544f9_1": ("最终转账成功，但为筹足余额另行绑卡/充值，产生 venmo.BankTransfer 与 Gmail/文件等超出允许集合的变更。", "top-5 主要是便笺/支付请求等经验，未证明有避免充值副作用的适用规则；?。"),
    "2c544f9_2": ("最终转账成功，但额外绑卡/充值造成 BankTransfer 与 Gmail/文件变更，官方仅允许目标转账相关模型。", "top-5 未给出针对该附带状态变更的规则；?。"),
    "2c544f9_3": ("同样产生充值及邮件/文件副作用；30 轮耗尽前虽发出转账，却未 complete_task，另有答案缺失。", "top-5 未给出针对附带状态变更的规则；?。"),
    "b9c5c9a_1": ("对每人只读 latest 消息并用 yes/coming 等字面关键词判 RSVP；Thomas、Tracy 写成 unknown，官方要求 yes。", "可见 CSV 经验讲嵌套数据结构，不是 RSVP 语义规则；无法据此判 A/I；?。"),
    "b6d1104_1": ("把 05/23 新条目追加在旧月份后面；官方要求最新月份排在前面。", "检索到便笺/费用通用经验，但无月序规则；?。"),
    "b6d1104_3": ("同样把 05/23 追加在 04/23…11/22 后面，月序不符。", "检索经验未包含该月序要求；?。"),
    "166f4ff_2": ("用 now-9×24h 的时刻作为‘含今天最近 10 天’下限，而非边界日零点；回答 821，官方为 833，差 12。边界漏计是代码支持的推断，未逐笔验证。", "top-5 日期/交易经验没有明确的含首日零点规则；不据金额差直接判 I/A；?。"),
    "83a7951_2": ("30 轮耗在双系统查询、匹配和下载两张收据；没有调用 splitwise.record_payment，目标群组付款均缺失。", "top-5 为 Venmo/便笺支付经验，缺少该 Venmo→Splitwise 流程的明确规则；?。"),
    "83a7951_3": ("30 轮内只记下 Group 1 的 40 美元付款；第二张收据刚下载，Group 73 的 1000 美元付款未写入。", "top-5 未明确覆盖双交易→双群组付款流程；?。"),
    "3aa1a22_1": ("30 轮中 11 次语法错误，后段退化成 print 等无效代码；除读取日期外未接受邀请或删除消息。", "可见经验只讲通用电话认证/消息删除，不足以证明完整条件性邀请流程已被正确记忆；?。"),
    "3aa1a22_2": ("按‘非联系人’直接删除筛选到的语音消息，没有再核实是否目标邀请；多删 ID 16753、16663。", "top-5 只有通用删除/认证经验，没有任务所需的邀请内容约束；?。"),
    "3aa1a22_3": ("依据邀请码与联系人筛选后接受 5 个群组，没有按‘本周’筛消息；官方仅要求 3 组，多出 76、122。", "top-5 只有通用消息经验，没有精确日期筛选规则；?。"),
    "986aa4e_1": ("30 轮耗在 API 探索/搜索歌曲，另有 10 次语法错误；未修改 Spotify 歌单，也未完成 Todoist 任务与评论。", "可见 song_id→歌名经验只覆盖局部步骤，不能证明完整跨应用流程已被记忆；?。"),
    "986aa4e_2": ("已增删 Spotify 歌单歌曲，但 30 轮耗尽在查看 Todoist 评论 API 前后；未更新任务完成状态或发评论。", "可见经验主要针对 Spotify 或无关便笺，不含该 Todoist 收尾流程；?。"),
}

# These labels describe the observable execution failure, not a proven ReMe
# memory-module cause. The two medium rows have a narrower evidentiary limit.
UNCLASSIFIED_EXECUTION = {
    "d6ac34d_1": ("必填参数遗漏", "强：API 入参、最终 DB 和断言一致"),
    "d6ac34d_2": ("必填参数遗漏", "强：API 入参、最终 DB 和断言一致"),
    "d6ac34d_3": ("必填参数遗漏", "强：API 入参、最终 DB 和断言一致"),
    "425a494_2": ("统计对象错误", "强：查询对象、回答和断言一致"),
    "2c544f9_1": ("非目标副作用", "强：转账及额外 DB 变更可核对"),
    "2c544f9_2": ("非目标副作用", "强：转账及额外 DB 变更可核对"),
    "2c544f9_3": ("非目标副作用／轮次耗尽", "强：额外 DB 变更及未完成标记可核对"),
    "b9c5c9a_1": ("RSVP 判定错误", "中：结果差异和判定代码可证；原消息语义未完整打印"),
    "b6d1104_1": ("文本顺序错误", "强：保存后的便笺和要求可核对"),
    "b6d1104_3": ("文本顺序错误", "强：保存后的便笺和要求可核对"),
    "166f4ff_2": ("日期下限错误（推断）", "中：时刻下限与金额差可证；未逐笔证明差额来源"),
    "83a7951_2": ("跨应用写入未完成", "强：无 record_payment 调用及目标记录"),
    "83a7951_3": ("跨应用写入未完成", "强：仅一笔 record_payment 及目标记录"),
    "3aa1a22_1": ("语法错误／执行停滞", "强：任务审计错误轮次与无目标变更可核对"),
    "3aa1a22_2": ("目标筛选过宽", "强：删除调用和额外消息 ID 可核对"),
    "3aa1a22_3": ("时间过滤遗漏", "强：筛选代码和额外群组 ID 可核对"),
    "986aa4e_1": ("语法错误／轮次耗尽", "强：任务审计与无目标变更可核对"),
    "986aa4e_2": ("跨应用收尾未完成", "强：Spotify 已改、Todoist 未改可核对"),
}


def json_lines(path: Path):
    with path.open() as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def link(path: Path, label: str) -> str:
    relative = path.relative_to(ROOT)
    return f"[{label}](../{relative.as_posix()})"


def plain(value: str) -> str:
    return " ".join(str(value).split())


def cell(value: str) -> str:
    return escape(plain(value), quote=False).replace("|", "&#124;")


def events_for(path: Path):
    wanted = {"retrieve_task_memory", "summary_task_memory", "add_task_memory"}
    events = {}
    for event in json_lines(path):
        endpoint = event.get("endpoint")
        if endpoint in wanted:
            events[endpoint] = event
    return events


def first_prompt(path: Path) -> str:
    for call in json_lines(path):
        messages = call.get("input", {}).get("messages")
        if messages:
            return messages[1]["content"]
    return ""


def classify(dataset: str, arm: str, task_id: str, candidates: int):
    override = OVERRIDES.get((dataset, arm, task_id))
    if override:
        return override
    if arm == "fixed":
        return "?", "unclassified"
    if candidates == 0:
        return "P*", "weak"
    return "U*", "medium"


def collect():
    rows = []
    runs = []
    for dataset in DATASETS:
        for arm in ARMS:
            matches = list(OUTPUTS.glob(f"{PREFIX}{dataset}_{arm}_r01_*_run_0"))
            if len(matches) != 1:
                raise RuntimeError(f"Expected one run for {dataset} {arm}: {matches}")
            run = matches[0]
            manifest = json.loads((run / "run_manifest.json").read_text())
            individual = json.loads((run / "evaluations" / f"{dataset}.json").read_text())["individual"]
            task_ids = manifest["task_ids"]
            if set(task_ids) != set(individual):
                raise RuntimeError(f"Task IDs differ for {run.name}")
            run_counts = Counter()
            for ordinal, task_id in enumerate(task_ids, 1):
                task = individual[task_id]
                if task["success"]:
                    continue
                task_root = run / "tasks" / task_id
                event_path = run / "baseline_artifacts/reme" / task_id / "memory_events.jsonl"
                ev = events_for(event_path)
                retrieve = ev.get("retrieve_task_memory", {})
                summary = ev.get("summary_task_memory", {})
                retrieved = retrieve.get("response", {}).get("metadata", {}).get("memory_list", [])
                proposals = summary.get("response", {}).get("metadata", {}).get("memory_list", [])
                added = "add_task_memory" in ev
                if arm != "fixed" and not summary:
                    raise RuntimeError(f"Missing summary event: {run.name}/{task_id}")
                if arm == "fixed" and summary:
                    raise RuntimeError(f"Unexpected summary event: {run.name}/{task_id}")
                if added:
                    raise RuntimeError(f"Failed task unexpectedly added memory: {run.name}/{task_id}")
                prompt = first_prompt(task_root / "logs/lm_calls.jsonl")
                visible = bool(re.search(r"Experience\s*1\s*:", prompt))
                if bool(retrieved) != visible:
                    raise RuntimeError(f"Retrieval/prompt mismatch: {run.name}/{task_id}")
                actions = []
                for call in json_lines(task_root / "logs/api_calls.jsonl"):
                    url = call.get("url", "")
                    if not url.startswith("/api_docs/") and not url.startswith("/supervisor/"):
                        actions.append(f"{call.get('method', '').upper()} {url}")
                io = (task_root / "logs/environment_io.md").read_text()
                audit_path = run / "baseline_artifacts/reme" / task_id / "task_audit.json"
                trajectory = json.loads(audit_path.read_text())["result"]["task_history"]
                llm_rounds = sum(message["role"] == "assistant" for message in trajectory)
                trajectory_errors = sum(
                    message["role"] == "user" and "Execution failed" in message["content"]
                    for message in trajectory
                )
                failures = task["failures"]
                if not failures:
                    raise RuntimeError(f"Failed task has no assertions: {run.name}/{task_id}")
                family, variant = task_id.rsplit("_", 1)
                label, quality = classify(dataset, arm, task_id, len(proposals))
                run_counts[label] += 1
                rows.append({
                    "dataset": dataset,
                    "arm": arm,
                    "run": run,
                    "task_id": task_id,
                    "ordinal": ordinal,
                    "family": family,
                    "variant": variant,
                    "difficulty": task["difficulty"],
                    "failures": failures,
                    "retrieved": len(retrieved),
                    "retrieved_ids": [x.get("memory_id") for x in retrieved],
                    "candidates": len(proposals),
                    "added": added,
                    "visible": visible,
                    "actions": actions,
                    "interactions": io.count("### Environment Interaction"),
                    "llm_rounds": llm_rounds,
                    "execution_errors": trajectory_errors,
                    "label": label,
                    "quality": quality,
                })
            runs.append((dataset, arm, run, len(task_ids), run_counts))
    if len(rows) != 293 or sum(count for _, _, _, count, _ in runs) != 702:
        raise RuntimeError("Formal campaign task counts changed; re-audit report")
    return rows, runs


def case_link(dataset: str, arm: str, task_id: str, kind: str):
    run = next(OUTPUTS.glob(f"{PREFIX}{dataset}_{arm}_r01_*_run_0"))
    task = run / "tasks" / task_id
    paths = {
        "eval": task / "evaluation/report.md",
        "env": task / "logs/environment_io.md",
        "api": task / "logs/api_calls.jsonl",
        "lm": task / "logs/lm_calls.jsonl",
        "mem": run / "baseline_artifacts/reme" / task_id / "memory_events.jsonl",
        "audit": run / "baseline_artifacts/reme" / task_id / "task_audit.json",
        "initial": run / "baseline_artifacts/reme/memory_initial.jsonl",
    }
    return link(paths[kind], kind)


def render(rows, runs):
    totals = Counter(row["label"] for row in rows)
    lines = [
        "# ReMe Intermediate8h / Quick2h 失败案例分析",
        "",
        "分析对象：`formal12-20261025-a` 的 12 个已完成 run；模型 `qwen3.8-flash`；方法为 ReMe 的 fixed、dynamic、cold start 三臂。依据 [Failure_modes_skill.md](../ace-appworld/Failure_modes_skill.md) 的 M/I/A/P/U 定义。这里只分析 **官方任务级未全通过** 的任务；一条任务有多项断言失败仍计为一例。",
        "",
        "## 核心结论",
        "",
        "- 官方结果是 409/702 成功、**293/702 失败**。Intermediate8h 260/585 失败；Quick2h 33/117 失败。下表按失败任务数计，不把 SGC 或部分断言分数当作失败案例数。",
        "- dynamic/cold 的 190 个失败任务均调用了 `summary_task_memory`，其中 **65 个返回零条候选**，**125 个返回至少一条候选**；失败任务 **0 个调用 `add_task_memory`**。这是失败后反馈链路的直接观察，不等于 P/U 分别造成同一个任务的执行失败。",
        "- fixed 的 103 个失败任务本来就不执行提炼或新增；不能把“没有更新”直接算成 U。逐条核查确认了 1 个 I、1 个 A；其余固定臂在本次证据级别下保留 `?`，不强行归因。",
        "- 已核实的执行型错误包括漏传 `pinned=True`、只取 liked songs 首个默认分页、对不相关消息执行删除、忽略相对日期窗口、未清空既有购物车等。这些是具体案例的执行事实；从断言本身不能推断记忆模块标签。",
        "",
        "## 方法与标签口径",
        "",
        "逐任务读取官方 `evaluations/<dataset>.json` 和 `evaluation/report.md`；对照 `lm_calls.jsonl` 的首次聊天提示词、`environment_io.md` 的环境交互、`api_calls.jsonl` 的应用调用、`memory_events.jsonl` 的检索/提炼/新增事件、`task_audit.json` 的完整任务轨迹及运行前经验池。部分语法错误轮次只在任务轨迹/模型请求中可见，`environment_io.md` 的编号交互数可能小于模型轮数。表格附录给每个失败任务提供源文件链接。`api_calls.jsonl` 没有完整 API 响应体；未打印的返回值不能从环境日志中推断。DB 终态由官方断言校验，关键案例另核对具体调用和状态差异。",
        "",
        "`I` 只在任务开始前确有适用经验且未进入检索前五/提示词时确认；`A` 只在正确经验实际可见而执行仍不当时确认；`M` 需证明表示结构无法承载经验。本次不从“空检索”自动推 I，也没有发现足以确认 M 的结构性证据。星号 `P*` / `U*` 是**反馈阶段的机械筛查标签**：前者表示失败后的摘要结果为空，后者表示有候选却因只在严格成功时新增的门禁而未写入。`P*` 不是“已证明候选应是什么”；`U*` 不是“已证明候选正确、且缺失导致当前任务失败”。它们不能与强证据的 I/A/P/U 混作因果计数。具体强证据个案会去掉星号。`?` 表示按严格规则无法归类，即使可指出直接执行原因，也不能自动推出记忆模块原因。主标签互斥；若同一任务同时有执行与反馈问题，表格保留较早或最可核实的模块，正文另说明其关系。",
        "",
        "## 失败任务与反馈阶段总览",
        "",
        "| 数据集 | arm | 总任务 | 失败 | I（强） | A（强） | P（强） | U（强） | P*（弱） | U*（中） | ? |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for dataset, arm, run, task_count, c in runs:
        failed = sum(c.values())
        lines.append(f"| {link(run, dataset)} | {arm} | {task_count} | {failed} | {c['I']} | {c['A']} | {c['P']} | {c['U']} | {c['P*']} | {c['U*']} | {c['?']} |")
    lines.append(f"| **合计** | — | **702** | **293** | **{totals['I']}** | **{totals['A']}** | **{totals['P']}** | **{totals['U']}** | **{totals['P*']}** | **{totals['U*']}** | **{totals['?']}** |")
    lines.extend([
        "",
        "星号标签仅可支持‘反馈链路在哪里停下’的计数，**不可解读为 293 个失败任务的完备因果分解**。fixed 无失败后的学习分支；dynamic/cold 的 `P*` 与 `U*` 在当前任务评分之后才发生。尤其 `U*` 候选可能不正确、过泛或重复，必须个案检查才能升级为严格 U。",
        "",
        "## 经过逐条核查的案例",
        "",
        "### 1. Intermediate8h normal / fixed：适用分页经验存在但未取回（I，强）",
        "",
        f"`fd1f8fa_2` 要删除 Spotify 队列中未点赞的歌曲。{case_link('intermediate_8h_test_normal','fixed','fd1f8fa_2','eval')} 显示最终队列只有 5 首，预期 12 首，缺 7 首。任务开始前的 {case_link('intermediate_8h_test_normal','fixed','fd1f8fa_2','initial')} 已有经验 `44c5f7af67dc4316a3bf039208eac11b`，明确提醒对已点赞歌曲做分页以保证覆盖；{case_link('intermediate_8h_test_normal','fixed','fd1f8fa_2','mem')} 的检索前快照包含该 ID，但实际 top-5 没有它，{case_link('intermediate_8h_test_normal','fixed','fd1f8fa_2','lm')} 提示词也未包含这条。{case_link('intermediate_8h_test_normal','fixed','fd1f8fa_2','env')} 只调用一次 `show_liked_songs(access_token=...)`，得到 5 个 liked IDs，然后按这 5 个 ID 删除队列其余歌曲；{case_link('intermediate_8h_test_normal','fixed','fd1f8fa_2','api')} 确认执行了多次删除。此处同时有执行不完整，但按决策树主标签为更早的检索缺失 I。不能仅凭该单例声称整个固定臂 I 的流行率。",
        "",
        "### 2. Intermediate8h normal / dynamic：三次漏设 pinned，未提炼纠错经验（P，强）",
        "",
        "`d6ac34d_1/_2/_3` 三个变体均因新建便笺 `pinned=False`、预期 `True` 而失败（逐任务官方报告："
        + "、".join(case_link('intermediate_8h_test_normal','dynamic',f'd6ac34d_{i}','eval') for i in (1,2,3))
        + "）。执行器已查看 `create_note` 文档，却在实际 `create_note(...)` 调用中都没有传 `pinned=True`（"
        + "、".join(case_link('intermediate_8h_test_normal','dynamic',f'd6ac34d_{i}','env') for i in (1,2,3))
        + "）。三个任务均检索到五条经验，但首条主要讲认证/修改现有便笺，并非 `pinned` 参数；三次 `summary_task_memory` 都返回空候选（"
        + "、".join(case_link('intermediate_8h_test_normal','dynamic',f'd6ac34d_{i}','mem') for i in (1,2,3))
        + "）。失败证据足以提出‘新建便笺时显式传入预期 pinned 状态’，却未形成候选，故确认为 P；后两个变体仍缺此经验是后果，但不应错判为 I。",
        "",
        "### 3. Intermediate8h challenge / dynamic：购物车污染，正确候选未写入（U，强）",
        "",
        f"`245cb43_3` 的 {case_link('intermediate_8h_test_challenge','dynamic','245cb43_3','eval')} 显示订单含 7 件而预期 1 件，首件还不是目标 compass；执行器 {case_link('intermediate_8h_test_challenge','dynamic','245cb43_3','env')} 调用了 `add_product_to_cart(...)` 但未使用已见文档中的 `clear_cart_first=True`，随后 `place_order` 会提交整车商品。失败后的 {case_link('intermediate_8h_test_challenge','dynamic','245cb43_3','mem')} 明确提出‘下单前清空/确认购物车，优先使用 clear_cart_first=True’，但没有 `add_task_memory` 事件；只在成功时新增的门禁使这条针对性经验未写入，故严格 U。该 U 描述**未来记忆更新失败**；当次订单失败的直接执行原因是未隔离购物车。",
        "",
        "### 4. Quick2h normal / dynamic：多删无关语音消息，摘要无候选（P，强）",
        "",
        f"`3aa1a22_2` 的 {case_link('quick2h_test_normal_v2','dynamic','3aa1a22_2','eval')} 显示实际删除语音消息 ID `{16753,17034,17036,16663}`，预期只有 `{17034,17036}`。{case_link('quick2h_test_normal_v2','dynamic','3aa1a22_2','env')} 的分支把‘发送者不在联系人中’的所有筛选消息加入删除列表，却没有在删除分支再次验证它确实是目标 Splitwise 邀请；{case_link('quick2h_test_normal_v2','dynamic','3aa1a22_2','api')} 有四次删除请求。虽然 {case_link('quick2h_test_normal_v2','dynamic','3aa1a22_2','mem')} 检索到了通用消息删除经验，失败后的摘要却返回零候选，没有提出‘先确认邀请内容与时间窗，再按联系人关系删除’的纠错规则，故主标签 P。不能将通用‘分页删除’经验等同于该任务所需的精确筛选经验。",
        "",
        "### 5. Quick2h normal / dynamic：错误时间窗导致额外入群，正确候选未写入（U，强）",
        "",
        f"`3aa1a22_3` 要处理特定相对日期的 Splitwise 邀请；{case_link('quick2h_test_normal_v2','dynamic','3aa1a22_3','eval')} 显示实际加入群组 ID `{67,76,179,122,188}`，预期 `{67,188,179}`，多了两组。{case_link('quick2h_test_normal_v2','dynamic','3aa1a22_3','env')} 依据 `code =>` 和联系人关系选择了五条，却未在执行动作前按任务日期核准消息时间。{case_link('quick2h_test_normal_v2','dynamic','3aa1a22_3','mem')} 的摘要候选明确要求把相对日期转为具体时间窗并用 `sent_at` 过滤，但失败任务没有新增事件，故严格 U。重复接受尝试返回‘already a member’不是额外入群的直接证据；官方新增群组集合才是。",
        "",
        "## 横向解释与改进优先级",
        "",
        "1. **先修执行前的集合边界**：购买前核对 cart 商品及 `clear_cart_first`；批量消息操作先合并内容、日期和联系人条件；分页 API 必须迭代到终止；新建记录显式传任务要求的布尔参数。上述案例均有具体断言与执行调用支持，不需要读取私有答案才能看到机制。",
        "2. **区分检索与提炼**：固定臂 Spotify 案例满足 I 的严格前置条件；便笺案例则是失败后 P，不能因后续无经验而说成检索错。检索评估应比较‘任务前已有的适用记忆 ID’与实际 top-k 和提示词，而非只统计非空命中。",
        "3. **评估失败经验的安全写入机制**：dynamic/cold 的候选经验并不等于可信经验。可离线回放失败轨迹、用官方断言验证纠错规则、经过隐私/去重/范围检查后再决定是否写入，而不是无条件放开失败任务写入。这是后续实验建议，**不是本次 run 已执行的操作**。",
        "4. **不要把评分后的记忆门禁当成当次失败根因**：本次所有失败任务在评分后才进入 summary/add 判断。报告中的 U 描述对后续任务学习的影响，不能单独解释它所属任务为何没完成。",
        "",
        "## 定向复核：原第 73–92 行的 20 个 fixed-arm 失败任务",
        "",
        "以下 20 项全部属于 `intermediate_8h_test_normal/fixed`。逐项复核了官方断言、实际 API/代码、首轮可见的五条经验，并用 `task_audit.json` 补上未出现在 `environment_io.md` 的语法错误轮次。**1 项满足 I，1 项满足 A，18 项暂不满足 M/I/A/P/U 的严格证据门槛**；`?` 不表示不知道执行哪里错，而是当前证据不足以把执行错误归咎于一个具体记忆模块。fixed 按设计无失败后 proposer/updater，不能用本次任务的“未写入”给它贴 P/U。",
        "",
        "### 已确认的记忆模块归因（2 项）",
        "",
        "| 任务 | 模式 | 直接失败原因 / 可观察结果 | 记忆证据与归因边界 | 核查入口 |",
        "|---|---|---|---|---|",
    ])
    focused_rows = [row for row in rows if row["dataset"] == "intermediate_8h_test_normal" and row["arm"] == "fixed"]
    if len(focused_rows) != 20 or set(FOCUSED) != {row["task_id"] for row in focused_rows}:
        raise RuntimeError("The targeted 20-task audit no longer matches its source rows")
    confirmed = [row for row in focused_rows if row["label"] != "?"]
    unclassified = [row for row in focused_rows if row["label"] == "?"]
    if len(confirmed) != 2 or len(unclassified) != 18 or set(UNCLASSIFIED_EXECUTION) != {row["task_id"] for row in unclassified}:
        raise RuntimeError("The targeted confirmed/unclassified split no longer matches its source rows")
    for row in confirmed:
        tid = row["task_id"]
        cause, memory = FOCUSED[tid]
        evidence = " / ".join(
            case_link("intermediate_8h_test_normal", "fixed", tid, kind)
            for kind in ("eval", "env", "api", "lm", "mem", "audit")
        )
        lines.append(
            f"| `{tid}` | {row['label']} · {row['quality']} | {cell(cause)} | {cell(memory)} | {evidence} |"
        )
    lines.extend([
        "",
        "### 尚未归入记忆模块的 18 个失败任务：逐项执行根因",
        "",
        "下表的‘根因’是能够追踪到的**执行层近因**（模型实际代码/调用如何造成官方断言失败），不是已证明的模型内部动机或 ReMe 记忆模块因果归因。`?` 仅针对 M/I/A/P/U 分类。‘强’表示近因有直接调用/最终状态/断言支持；‘中’表示还有未打印的语义内容或未逐笔核验的因果链。",
        "",
        "| 任务 | 执行根因类型 | 逐项根因与失败结果 | 近因证据强度 | 记忆模块为何仍是 ? | 核查入口 |",
        "|---|---|---|---|---|---|",
    ])
    for row in unclassified:
        tid = row["task_id"]
        cause, memory = FOCUSED[tid]
        kind, confidence = UNCLASSIFIED_EXECUTION[tid]
        evidence = " / ".join(
            case_link("intermediate_8h_test_normal", "fixed", tid, source)
            for source in ("eval", "env", "api", "lm", "mem", "audit")
        )
        lines.append(
            f"| `{tid}` | {cell(kind)} | {cell(cause)} | {cell(confidence)} | {cell(memory)} | {evidence} |"
        )
    lines.extend([
        "",
        "关于 `166f4ff_2`：可以直接证实代码使用带时分秒的 `now - 9 days`，且最终回答 821、官方要求 833；差额是否**全部**来自边界日尚未逐笔核对，故表中保留推断语气。`b9c5c9a_1` 可直接证实两个 RSVP 被写为 unknown、官方要求 yes，但未把未打印的消息响应臆断为某一句具体文本。其余条目如需提升到 I/A，还需证明一条任务前已存在的适用规则及其检索/执行关系，而不是只凭 API 错误或同一家族失败。",
        "",
        "## 全部失败任务证据账本",
        "",
        "以下每行是一个 `success=false` 的正式任务（共 293 行）。全体模型/方法均为 `qwen3.8-flash` / ReMe；`family/variant` 取任务 ID 的最后一个下划线分隔。`断言`列完整列出官方失败 requirement；实际值、期望值及私有测试 trace 在所链的官方报告。`动作`列优先列举最多两个非认证的修改类应用 API 端点（否则列读操作），完整调用与参数在 API 日志；模型/环境轮次及失败输出来自任务审计和环境日志。`R/S/W` 分别是检索条数、失败后的摘要候选数、新增事件数（本表 W 恒为 0）。首次模型提示词中有非空 `Experience 1:` 当且仅当 R>0，已逐行核对；空检索仍可能留下空的经验段落标题。`证据`列依次链接官方断言、环境、API、LLM、记忆事件、任务审计及最终 DB。",
        "",
        "| 数据集 | arm | 任务（family/variant） | D | 失败断言 | 动作/轮次 | R/S/W | 主标签·证据级 | 证据 | 理由与限制 |",
        "|---|---|---|---:|---|---|---:|---|---|---|",
    ])
    for row in rows:
        run = row["run"]
        tid = row["task_id"]
        task = run / "tasks" / tid
        mem = run / "baseline_artifacts/reme" / tid / "memory_events.jsonl"
        reqs = "<br>".join(cell(f["requirement"]) for f in row["failures"])
        action_names = []
        for action in row["actions"]:
            if action not in action_names:
                action_names.append(action)
        non_auth = [name for name in action_names if "/auth/" not in name]
        mutations = [name for name in non_auth if not name.startswith("GET ")]
        shown = (mutations or non_auth or action_names)[:2]
        action_text = ", ".join(shown) or "无应用 API"
        if len(action_names) > len(shown):
            action_text += f"；共{len(action_names)}类"
        action_text += f"；{row['llm_rounds']}模型/{row['interactions']}环境轮"
        if row["execution_errors"]:
            action_text += f"/{row['execution_errors']}次失败输出"
        label = row["label"]
        if tid in FOCUSED and row["dataset"] == "intermediate_8h_test_normal" and row["arm"] == "fixed":
            reason = FOCUSED[tid][0] + " " + FOCUSED[tid][1]
        elif label == "I":
            reason = "任务前存在已点赞歌曲分页经验但 top-5 未取回；只取首批后误删队列。"
        elif label == "P" and tid.startswith("d6ac34d_"):
            reason = "新建便笺漏设 pinned=True；失败后摘要为空，重复变体未学到该参数规则。"
        elif label == "P":
            reason = "删除分支缺邀请内容核准，多删两条；失败后摘要为空。"
        elif label == "U" and tid == "245cb43_3":
            reason = "订单含既有购物车商品；摘要提出 clear_cart_first，但失败门禁未写入。"
        elif label == "U":
            reason = "多接受两条非目标日期邀请；摘要提出 sent_at 时间窗，但失败门禁未写入。"
        elif label == "P*":
            reason = "摘要返回零候选；仅定位反馈提炼缺口，具体应学规则未逐条语义验证。"
        elif label == "U*":
            reason = "摘要有候选但失败门禁未新增；候选正确性/对后续任务影响未逐条验证。"
        else:
            reason = "检索有经验，但未证明存在未取回的适用规则或可见规则被误用；固定臂无提炼/新增。"
        evidence = " / ".join([
            link(task / "evaluation/report.md", "评"),
            link(task / "logs/environment_io.md", "环"),
            link(task / "logs/api_calls.jsonl", "API"),
            link(task / "logs/lm_calls.jsonl", "LLM"),
            link(mem, "忆"),
            link(run / "baseline_artifacts/reme" / tid / "task_audit.json", "审"),
            link(task / "dbs", "DB"),
        ])
        lines.append("| " + " | ".join([
            cell(row["dataset"]), row["arm"], link(task / "evaluation/report.md", f"{tid} ({row['family']}/{row['variant']})"),
            str(row["difficulty"]), reqs, cell(action_text),
            f"{row['retrieved']}/{row['candidates']}/0", f"{label} · {row['quality']}", evidence, cell(reason),
        ]) + " |")
    lines.extend([
        "",
        "## 可复核性与边界",
        "",
        "- 账本由同目录的 `build_reme_failure_case_analysis.py` 从正式 run 原始产物生成；若任务集合、检索提示词对应关系或失败任务的新增行为发生变化，脚本会报错而不是默默改统计。",
        "- 官方断言在某些失败任务中只给 `answers match`，这不足以指明 API 层根因；此类行的 P*/U* 仍只是反馈观察。报告没有对 293 个任务全部人工判读完整代码/DB，因此不报告未经证实的 I/A/M 总体频率。",
        "- 预置 207 条经验的训练来源清单缺失，fixed/dynamic 起点相同但不能声称其完全来自所列训练划分。每个 run 的经验集合相互隔离；本报告的时间顺序和‘任务前’只在相应 run 内成立。",
        "- 本报告没有修改实验产物、应用 DB 或 Elasticsearch，仅写出分析。",
        "",
    ])
    return "\n".join(lines)


if __name__ == "__main__":
    rows, runs = collect()
    REPORT.write_text(render(rows, runs), encoding="utf-8")
    print(f"Wrote {REPORT}: {len(rows)} failures, {len(runs)} runs")
    print(dict(Counter(row["label"] for row in rows)))
