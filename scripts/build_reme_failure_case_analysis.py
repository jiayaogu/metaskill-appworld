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
import os
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ROOT / "experiments/outputs"
REPORT = ROOT / "experiments/Intermediate_8h_reme_online_failure_case_analysis.md"
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
    "fd1f8fa_2": ("Fetched only the default first page of `show_liked_songs` (five songs), then removed other liked songs from the queue; seven required songs were missing.", "A pre-task liked-song pagination memory (44c5f7…) existed in the snapshot but was absent from the top five and prompt; I."),
    "d6ac34d_1": ("After copying yesterday's habit note, `create_note` omitted `pinned=True`; the new note was false, rather than the expected true.", "The top five held generic authentication/note-editing advice, not a pinned-note rule; fixed does not run proposal/update; ?."),
    "d6ac34d_2": ("Created today's habit note without `pinned=True`; the new note was false, rather than the expected true.", "As in variant 1, the top five lacked a pinned-note rule; fixed does not run proposal/update; ?."),
    "d6ac34d_3": ("Created today's habit note without `pinned=True`; the new note was false, rather than the expected true.", "As in variant 1, the top five lacked a pinned-note rule; fixed does not run proposal/update; ?."),
    "3b8fb7a_3": ("In 30 model turns, submitted the unclosed `print(notes` 26 times, each causing a syntax error; no Venmo payment/request or target DB change occurred.", "The applicable note-expense-to-Venmo memory (7128f4…) was retrieved and visible in the prompt, but the model did not execute the workflow; A."),
    "425a494_2": ("Counted `genre` over `liked_albums`, although the task asked for genres of liked songs in the album library; answered `edm` instead of `classical`.", "The top five lacked a correct song-level genre-counting rule; a generic Spotify memory alone does not establish A; ?."),
    "2c544f9_1": ("Completed the transfer but additionally linked a card and topped up the balance, changing `venmo.BankTransfer`, Gmail, and file state outside the allowed set.", "The top five mainly concerned notes/payment requests; no applicable rule against top-up side effects was established; ?."),
    "2c544f9_2": ("Completed the transfer, but extra card-linking/top-up changed BankTransfer, Gmail, and file state; the official assertion allowed only target-transfer-related models.", "The top five lacked a rule for these ancillary state changes; ?."),
    "2c544f9_3": ("Also caused top-up and mail/file side effects; sent the transfer but exhausted 30 turns without `complete_task`, leaving the answer absent.", "The top five lacked a rule for these ancillary state changes; ?."),
    "b9c5c9a_1": ("Read only each person's latest message and used literal keywords such as `yes`/`coming` for RSVP; wrote `unknown` for Thomas and Tracy instead of the expected `yes`.", "The visible CSV memory concerned nested data structures, not RSVP semantics; it does not establish A or I; ?."),
    "b6d1104_1": ("Appended the new 05/23 entry after older months; the official requirement placed the newest month first.", "Retrieved generic note/expense memories contained no month-order rule; ?."),
    "b6d1104_3": ("Likewise appended 05/23 after 04/23 through 11/22, violating the required month order.", "Retrieved memories did not contain the required month ordering; ?."),
    "166f4ff_2": ("Used the timestamp `now - 9×24h`, rather than midnight of the first day, as the lower bound for ten days including today; answered 821 versus 833 (difference 12). Boundary omission is an inference from the code, not transaction-by-transaction proof.", "The top-five date/transaction memories lacked an explicit first-day-midnight rule; the amount gap alone does not establish I or A; ?."),
    "83a7951_2": ("Spent all 30 turns querying and matching two systems and downloading receipts; never called `splitwise.record_payment`, so both target group payments were absent.", "The top five covered Venmo/note payments, not an explicit Venmo-to-Splitwise workflow; ?."),
    "83a7951_3": ("Recorded only the $40 payment in Group 1 within 30 turns; after downloading the second receipt, it never recorded the $1,000 payment in Group 73.", "The top five did not explicitly cover two transactions mapped to two group payments; ?."),
    "3aa1a22_1": ("Produced 11 syntax errors in 30 turns and later degenerated into ineffective `print` calls; apart from reading the date, it neither accepted invitations nor deleted messages.", "Visible memories covered generic phone authentication/message deletion, not the full conditional invitation workflow; ?."),
    "3aa1a22_2": ("Deleted filtered voice messages solely because the senders were not contacts, without confirming they were target invitations; IDs 16753 and 16663 were extra deletions.", "The top five contained generic deletion/authentication advice but no invitation-content constraint; ?."),
    "3aa1a22_3": ("Accepted five groups by invitation code and contact status without filtering messages to this week; the official target was three groups, with IDs 76 and 122 extra.", "The top five contained generic message advice but no precise date-filtering rule; ?."),
    "986aa4e_1": ("Spent 30 turns exploring APIs/searching songs, including ten syntax errors; neither changed the Spotify playlist nor completed/commented on the Todoist task.", "The visible song-ID-to-title memory covered only a partial step, not the whole cross-app workflow; ?."),
    "986aa4e_2": ("Added/removed Spotify playlist songs but exhausted 30 turns while exploring Todoist comment APIs; neither completed the task nor posted a comment.", "Visible memories mainly concerned Spotify or unrelated notes, not the Todoist finishing steps; ?."),
}

# These labels describe the observable execution failure, not a proven ReMe
# memory-module cause. The two medium rows have a narrower evidentiary limit.
UNCLASSIFIED_EXECUTION = {
    "d6ac34d_1": ("Required parameter omitted", "Strong: API input, final DB, and assertion agree"),
    "d6ac34d_2": ("Required parameter omitted", "Strong: API input, final DB, and assertion agree"),
    "d6ac34d_3": ("Required parameter omitted", "Strong: API input, final DB, and assertion agree"),
    "425a494_2": ("Wrong counting unit", "Strong: queried entities, answer, and assertion agree"),
    "2c544f9_1": ("Unintended side effects", "Strong: transfer and extra DB changes are verifiable"),
    "2c544f9_2": ("Unintended side effects", "Strong: transfer and extra DB changes are verifiable"),
    "2c544f9_3": ("Side effects / turn limit", "Strong: extra DB changes and absent completion are verifiable"),
    "b9c5c9a_1": ("Incorrect RSVP classification", "Medium: result and classification code are visible; message semantics were not fully printed"),
    "b6d1104_1": ("Wrong text order", "Strong: saved note and requirement are verifiable"),
    "b6d1104_3": ("Wrong text order", "Strong: saved note and requirement are verifiable"),
    "166f4ff_2": ("Wrong date lower bound (inferred)", "Medium: cutoff timestamp and amount gap are visible; transaction-level source is unproven"),
    "83a7951_2": ("Cross-app write unfinished", "Strong: no `record_payment` call or target records"),
    "83a7951_3": ("Cross-app write unfinished", "Strong: only one `record_payment` call and target record"),
    "3aa1a22_1": ("Syntax errors / stalled execution", "Strong: audit error turns and absence of target changes are verifiable"),
    "3aa1a22_2": ("Overbroad target filter", "Strong: delete calls and extra message IDs are verifiable"),
    "3aa1a22_3": ("Missing time filter", "Strong: filtering code and extra group IDs are verifiable"),
    "986aa4e_1": ("Syntax errors / turn limit", "Strong: task audit and absence of target changes are verifiable"),
    "986aa4e_2": ("Cross-app finishing steps omitted", "Strong: Spotify changes and missing Todoist changes are verifiable"),
}


def json_lines(path: Path):
    with path.open() as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def link(path: Path, label: str) -> str:
    relative = Path(os.path.relpath(path, REPORT.parent))
    return f"[{label}]({relative.as_posix()})"


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
        "# ReMe Intermediate8h / Quick2h Failure-Case Analysis",
        "",
        "Scope: the 12 completed runs in `formal12-20261025-a`, using `qwen3.8-flash` and ReMe's fixed, dynamic, and cold-start arms. Labels follow the M/I/A/P/U definitions in [Failure_modes_skill.md](../Failure_modes_skill.md). This report analyzes tasks that **failed at least one official requirement**; a task with multiple failed assertions counts as one case.",
        "",
        "## Key findings",
        "",
        "- Official results: 409/702 strict successes and **293/702 failures**. Intermediate8h contributed 260/585 failures; Quick2h, 33/117. The tables count failed tasks, not SGC failures or partial-assertion scores.",
        "- All 190 failed dynamic/cold-start tasks called `summary_task_memory`: **65 returned no candidates** and **125 returned at least one**; **none called `add_task_memory`**. These are direct observations of the post-task feedback path, not proof that P or U caused the same task's execution failure.",
        "- The 103 failed fixed-arm tasks do not run proposal or addition by design, so absence of an update is not automatically U. Case-level review confirmed one I and one A; the other fixed-arm failures remain `?` where module attribution lacks evidence.",
        "- Verified execution mistakes include omitting `pinned=True`, reading only the first default page of liked songs, deleting unrelated messages, ignoring a relative-date window, and failing to clear an existing cart. These are case-specific execution facts; the assertion alone does not establish a memory-module label.",
        "",
        "## Method and label policy",
        "",
        "For each task, we read the official `evaluations/<dataset>.json` and `evaluation/report.md`, then compared the first chat prompt in `lm_calls.jsonl`, environment interactions in `environment_io.md`, application calls in `api_calls.jsonl`, retrieval/summary/addition events in `memory_events.jsonl`, the full trajectory in `task_audit.json`, and the pre-run memory pool. Some syntax-error turns appear only in the task audit/model requests, so the numbered interactions in `environment_io.md` can be fewer than model turns. The ledger links source files for every failed task. `api_calls.jsonl` does not contain full API response bodies; unprinted responses cannot be inferred from the environment log. Official assertions verify final DB state, and key cases were also checked against specific calls and state differences.",
        "",
        "Confirm `I` only when an applicable memory existed before the task but was absent from the retrieved top five and prompt; confirm `A` only when a correct memory was visible yet execution still misapplied it; `M` requires evidence that the representation could not carry the experience. Empty retrieval alone is not I, and this audit found no sufficient structural evidence for M. Starred `P*` and `U*` are **mechanical post-task feedback screens**: the former means the failure summary yielded no candidate, while the latter means a candidate existed but was not written under the strict-success-only addition gate. `P*` does not prove what should have been proposed; `U*` does not prove that a candidate was correct or caused this task's failure by being absent. Do not combine them with strongly evidenced I/A/P/U as causal counts. Asterisk-free labels require case-level evidence. `?` means the strict module classification is unresolved, even if a direct execution failure is visible. Primary labels are mutually exclusive; when execution and feedback issues coexist, the table uses the earlier or better-substantiated module and explains the relationship in prose.",
        "",
        "## Failed tasks and feedback-stage overview",
        "",
        "| Dataset | Arm | Tasks | Failures | I (strong) | A (strong) | P (strong) | U (strong) | P* (weak) | U* (medium) | ? |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for dataset, arm, run, task_count, c in runs:
        failed = sum(c.values())
        lines.append(f"| {link(run, dataset)} | {arm} | {task_count} | {failed} | {c['I']} | {c['A']} | {c['P']} | {c['U']} | {c['P*']} | {c['U*']} | {c['?']} |")
    lines.append(f"| **Total** | — | **702** | **293** | **{totals['I']}** | **{totals['A']}** | **{totals['P']}** | **{totals['U']}** | **{totals['P*']}** | **{totals['U*']}** | **{totals['?']}** |")
    lines.extend([
        "",
        "Starred labels count where the feedback path stopped; they **are not a complete causal decomposition of the 293 failed tasks**. Fixed has no post-failure learning branch. Dynamic/cold-start `P*` and `U*` occur after the current task is scored. A `U*` candidate may be wrong, overbroad, or duplicative and needs case review before a strict U label.",
        "",
        "## Individually audited cases",
        "",
        "### 1. Intermediate8h normal / fixed: applicable pagination memory not retrieved (I, strong)",
        "",
        f"`fd1f8fa_2` had to remove unliked songs from a Spotify queue. The {case_link('intermediate_8h_test_normal','fixed','fd1f8fa_2','eval')} shows five songs in the final queue instead of 12, seven missing. Before the task, {case_link('intermediate_8h_test_normal','fixed','fd1f8fa_2','initial')} contained memory `44c5f7af67dc4316a3bf039208eac11b`, explicitly advising pagination over liked songs. The pre-retrieval snapshot in {case_link('intermediate_8h_test_normal','fixed','fd1f8fa_2','mem')} contained that ID, but the retrieved top five and {case_link('intermediate_8h_test_normal','fixed','fd1f8fa_2','lm')} prompt did not. The executor called `show_liked_songs(access_token=...)` only once in {case_link('intermediate_8h_test_normal','fixed','fd1f8fa_2','env')}, received five liked IDs, and deleted other queue songs using only those IDs; {case_link('intermediate_8h_test_normal','fixed','fd1f8fa_2','api')} confirms multiple deletions. Execution was incomplete too, but the earlier retrieval miss is the primary I label under the decision tree. One case does not establish I prevalence across the fixed arm.",
        "",
        "### 2. Intermediate8h normal / dynamic: three omitted pinned flags, no corrective lesson proposed (P, strong)",
        "",
        "All three `d6ac34d_1/_2/_3` variants failed because the newly created note had `pinned=False` rather than the expected `True` (official reports: "
        + ", ".join(case_link('intermediate_8h_test_normal','dynamic',f'd6ac34d_{i}','eval') for i in (1,2,3))
        + "). The executor inspected the `create_note` documentation but omitted `pinned=True` in all actual calls ("
        + ", ".join(case_link('intermediate_8h_test_normal','dynamic',f'd6ac34d_{i}','env') for i in (1,2,3))
        + "). Each task retrieved five memories, but the first mainly concerned authentication/editing existing notes, not the `pinned` parameter. All three `summary_task_memory` calls returned no candidates ("
        + ", ".join(case_link('intermediate_8h_test_normal','dynamic',f'd6ac34d_{i}','mem') for i in (1,2,3))
        + "). The failure evidence supports a corrective rule to pass the intended pinned state explicitly when creating a note, yet no such candidate was proposed; hence P. The later variants still lacking this lesson is a consequence, not evidence of I.",
        "",
        "### 3. Intermediate8h challenge / dynamic: cart contamination, useful candidate not written (U, strong)",
        "",
        f"The {case_link('intermediate_8h_test_challenge','dynamic','245cb43_3','eval')} for `245cb43_3` shows seven ordered items instead of one, and the first was not the target compass. In {case_link('intermediate_8h_test_challenge','dynamic','245cb43_3','env')}, the executor called `add_product_to_cart(...)` without the documented `clear_cart_first=True`; `place_order` then submitted the whole cart. The post-failure {case_link('intermediate_8h_test_challenge','dynamic','245cb43_3','mem')} explicitly proposed clearing/checking the cart before ordering and preferring `clear_cart_first=True`, but no `add_task_memory` event followed. The success-only gate left this targeted lesson unwritten, supporting strict U. This U describes a **failure to update memory for future tasks**; the current order failed directly because the cart was not isolated.",
        "",
        "### 4. Quick2h normal / dynamic: unrelated voice messages deleted, no candidate proposed (P, strong)",
        "",
        f"The {case_link('quick2h_test_normal_v2','dynamic','3aa1a22_2','eval')} for `3aa1a22_2` shows voice-message IDs `{{16753,17034,17036,16663}}` deleted, versus only `{{17034,17036}}` expected. A branch in {case_link('quick2h_test_normal_v2','dynamic','3aa1a22_2','env')} added every filtered message from a non-contact sender to the deletion list without rechecking that it was a target Splitwise invitation; {case_link('quick2h_test_normal_v2','dynamic','3aa1a22_2','api')} records four deletion requests. Although {case_link('quick2h_test_normal_v2','dynamic','3aa1a22_2','mem')} retrieved generic message-deletion advice, the post-failure summary returned zero candidates and did not propose checking invitation content and the time window before applying the contact condition. The primary label is P. Generic paginated-deletion advice is not equivalent to the precise filter this task required.",
        "",
        "### 5. Quick2h normal / dynamic: wrong time window led to extra group joins, useful candidate not written (U, strong)",
        "",
        f"`3aa1a22_3` had to process Splitwise invitations within a relative-date window. The {case_link('quick2h_test_normal_v2','dynamic','3aa1a22_3','eval')} shows groups `{{67,76,179,122,188}}` joined instead of `{{67,188,179}}`, two extra. In {case_link('quick2h_test_normal_v2','dynamic','3aa1a22_3','env')}, selection used `code =>` and contact status but did not check message times against the task date before acting. The summary candidate in {case_link('quick2h_test_normal_v2','dynamic','3aa1a22_3','mem')} explicitly called for converting relative dates to a concrete time window and filtering by `sent_at`; no addition event followed the failed task, supporting strict U. Repeated accept attempts returning 'already a member' do not themselves prove extra joins; the official newly joined group set does.",
        "",
        "## Cross-case interpretation and improvement priorities",
        "",
        "1. **Fix set boundaries before acting.** Check cart contents and `clear_cart_first` before buying; combine content, date, and contact conditions before bulk message actions; page APIs until exhausted; and pass task-required Boolean values when creating records. Specific assertions and calls support these mechanisms without consulting private answers.",
        "2. **Separate retrieval from proposal.** The fixed-arm Spotify case meets strict I prerequisites; the note cases are post-failure P. Do not infer a retrieval failure merely because later tasks still lack the lesson. Retrieval evaluation should compare applicable pre-task memory IDs with actual top-k results and prompt visibility, not just count nonempty hits.",
        "3. **Evaluate safe writes from failures.** A candidate proposed in dynamic/cold start is not automatically trustworthy. A future experiment could replay failed trajectories offline, validate corrective rules against official assertions, and apply privacy, deduplication, and scope checks before writing. This is a recommendation, **not an operation performed in these runs**.",
        "4. **Do not call a post-score memory gate the cause of the current failure.** Every failed task entered summary/addition decisions only after scoring. U in this report describes lost learning for later tasks; by itself it cannot explain why its own task was not completed.",
        "",
        "## Targeted review: 20 fixed-arm failures from the original lines 73–92",
        "",
        "All 20 are from `intermediate_8h_test_normal/fixed`. We checked each official assertion, executed API/code, and the five memories visible at the first model turn; `task_audit.json` also supplies syntax-error turns omitted from `environment_io.md`. **One case meets I, one meets A, and 18 do not meet the strict M/I/A/P/U evidence threshold.** `?` does not mean the execution mistake is unknown; it means the available evidence does not attribute that mistake to a specific memory module. Fixed has no post-failure proposer/updater by design, so its absence of a write is not P or U.",
        "",
        "### Confirmed memory-module attributions (2 cases)",
        "",
        "| Task | Label | Direct execution failure / observed result | Memory evidence and attribution boundary | Evidence |",
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
        "### Eighteen failures not assigned to a memory module: execution cause by task",
        "",
        "The 'cause' below is the traceable **proximate execution cause**: how the model's code/calls produced the failed official assertion. It is not a proven internal model motive or ReMe memory-module cause. `?` applies only to M/I/A/P/U classification. 'Strong' means calls, final state, and assertions directly support the proximate cause; 'medium' marks unprinted semantic content or an unverified transaction-level causal link.",
        "",
        "| Task | Execution-failure type | Cause and failed result | Proximate-cause evidence | Why memory-module label remains ? | Evidence |",
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
        "For `166f4ff_2`, the code demonstrably used `now - 9 days` with a time-of-day component and answered 821 versus the official 833. Whether the **entire** difference comes from the boundary day has not been checked transaction by transaction, so the table marks that explanation as an inference. For `b9c5c9a_1`, two RSVPs were demonstrably written as `unknown` when `yes` was expected; the unprinted message responses are not assigned invented wording. Raising any other case to I/A requires proof of an applicable pre-task rule and its retrieval/execution relationship, not merely an API mistake or repeated family failure.",
        "",
        "## Evidence ledger for every failed task",
        "",
        "Each row is one formal task with `success=false` (293 rows). All used `qwen3.8-flash` / ReMe; `family/variant` splits the task ID at its final underscore. The failed-assertions column lists every official failed requirement; actual/expected values and private-test traces are in the linked official report. The action column prioritizes up to two non-authentication mutating app API endpoints (or read calls otherwise); the API log holds complete calls and arguments. Model/environment turn counts and failed outputs come from the task audit and environment log. `R/S/W` counts retrieved memories, post-failure summary candidates, and memory-add events (W is always zero here). A nonempty `Experience 1:` appeared in the first model prompt exactly when R > 0, checked row by row; empty retrieval may still leave an empty experience heading. Evidence links point, in order, to official assertions, environment, API, LLM, memory events, task audit, and final DB.",
        "",
        "| Dataset | Arm | Task (family/variant) | D | Failed assertions | Actions/turns | R/S/W | Primary label · evidence level | Evidence | Reason and limits |",
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
        action_text = ", ".join(shown) or "No app API"
        if len(action_names) > len(shown):
            action_text += f"; {len(action_names)} endpoint types total"
        action_text += f"; {row['llm_rounds']} model/{row['interactions']} environment turns"
        if row["execution_errors"]:
            action_text += f"/{row['execution_errors']} failed outputs"
        label = row["label"]
        if tid in FOCUSED and row["dataset"] == "intermediate_8h_test_normal" and row["arm"] == "fixed":
            reason = FOCUSED[tid][0] + " " + FOCUSED[tid][1]
        elif label == "I":
            reason = "An applicable liked-song pagination memory existed before the task but was absent from the top five; using only the first page led to incorrect queue deletions."
        elif label == "P" and tid.startswith("d6ac34d_"):
            reason = "The new note omitted `pinned=True`; post-failure summary was empty, so later variants did not receive this parameter lesson."
        elif label == "P":
            reason = "The deletion branch failed to verify invitation content and deleted two extra messages; post-failure summary was empty."
        elif label == "U" and tid == "245cb43_3":
            reason = "The order included existing cart items; summary proposed `clear_cart_first`, but the failure gate prevented writing it."
        elif label == "U":
            reason = "Two invitations outside the target date were accepted; summary proposed a `sent_at` window, but the failure gate prevented writing it."
        elif label == "P*":
            reason = "Summary returned no candidates. This screens a feedback/proposal gap; the exact lesson that should be learned was not semantically verified for this task."
        elif label == "U*":
            reason = "Summary produced a candidate, but the failure gate prevented addition; candidate correctness and effects on later tasks were not checked case by case."
        else:
            reason = "Memories were retrieved, but no applicable omitted rule or misused visible rule was proved; fixed has no proposal/addition branch."
        evidence = " / ".join([
            link(task / "evaluation/report.md", "Eval"),
            link(task / "logs/environment_io.md", "Env"),
            link(task / "logs/api_calls.jsonl", "API"),
            link(task / "logs/lm_calls.jsonl", "LLM"),
            link(mem, "Mem"),
            link(run / "baseline_artifacts/reme" / tid / "task_audit.json", "Audit"),
            link(task / "dbs", "DB"),
        ])
        lines.append("| " + " | ".join([
            cell(row["dataset"]), row["arm"], link(task / "evaluation/report.md", f"{tid} ({row['family']}/{row['variant']})"),
            str(row["difficulty"]), reqs, cell(action_text),
            f"{row['retrieved']}/{row['candidates']}/0", f"{label} · {row['quality']}", evidence, cell(reason),
        ]) + " |")
    lines.extend([
        "",
        "## Reproducibility and limits",
        "",
        "- The ledger is generated by [`build_reme_failure_case_analysis.py`](../scripts/build_reme_failure_case_analysis.py) from the formal run artifacts. It fails rather than silently changing statistics if the task set, retrieval/prompt correspondence, or memory-add behavior on failed tasks changes.",
        "- Some official failed assertions state only `answers match`, which does not identify an API-level cause; P*/U* on those rows remain feedback observations. We did not manually interpret complete code/DB traces for all 293 tasks, so no unsupported overall I/A/M prevalence is reported.",
        "- Provenance identifying which training tasks produced the 207 bundled memories is unavailable. Fixed and dynamic start from the same pool, but it cannot be claimed to come entirely from the named training split. Each run has an isolated memory set; chronology and 'pre-task' claims apply only within that run.",
        "- This report did not alter experimental artifacts, application DBs, or Elasticsearch; it only wrote this analysis.",
        "",
    ])
    return "\n".join(lines)


if __name__ == "__main__":
    rows, runs = collect()
    REPORT.write_text(render(rows, runs), encoding="utf-8")
    print(f"Wrote {REPORT}: {len(rows)} failures, {len(runs)} runs")
    print(dict(Counter(row["label"] for row in rows)))
