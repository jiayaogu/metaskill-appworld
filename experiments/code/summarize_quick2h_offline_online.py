#!/usr/bin/env python3
"""Audit and summarize the quick2h ACE offline/online experiment."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from appworld.task import load_task_ids


PROJECT_ROOT = Path(__file__).resolve().parents[2]
EXPERIMENTS = PROJECT_ROOT / "experiments"
OUTPUT_ROOT = EXPERIMENTS / "outputs" / "ACE_quick2h_offline_online" / "qwen3.8-flash"
CONFIG_ROOT = EXPERIMENTS / "configs" / "ACE_quick2h_offline_online" / "qwen3.8-flash"
PLAYBOOK_ROOT = EXPERIMENTS / "playbooks" / "quick2h_offline_online" / "qwen3.8-flash"

REPORT_PATH = EXPERIMENTS / "quick2h_ace_offline_online_report.md"
SUMMARY_PATH = EXPERIMENTS / "quick2h_ace_offline_online_summary.json"
CHECKSUM_PATH = EXPERIMENTS / "quick2h_ace_offline_online_checksums.json"

RATES = {
    "input_usd_per_1m_tokens": 0.64,
    "output_usd_per_1m_tokens": 2.16,
    "cache_read_usd_per_1m_tokens": 0.08,
}

RUNS = {
    "offline_adaptation": {
        "experiment": "offline_no_GT_adaptation",
        "dataset": "quick2h_train",
        "mode": "offline adaptation",
        "split": "train",
        "playbook": "offline_no_GT.txt",
        "main_result": False,
    },
    "offline_normal": {
        "experiment": "offline_no_GT_evaluation_test_normal",
        "dataset": "quick2h_test_normal",
        "mode": "offline frozen",
        "split": "normal",
        "playbook": "offline_no_GT.txt",
        "main_result": True,
    },
    "offline_challenge": {
        "experiment": "offline_no_GT_evaluation_test_challenge",
        "dataset": "quick2h_test_challenge",
        "mode": "offline frozen",
        "split": "challenge",
        "playbook": "offline_no_GT.txt",
        "main_result": True,
    },
    "online_normal": {
        "experiment": "online_no_GT_test_normal",
        "dataset": "quick2h_test_normal",
        "mode": "online adaptive",
        "split": "normal",
        "playbook": "online_no_GT_test_normal.txt",
        "main_result": True,
    },
    "online_challenge": {
        "experiment": "online_no_GT_test_challenge",
        "dataset": "quick2h_test_challenge",
        "mode": "online adaptive",
        "split": "challenge",
        "playbook": "online_no_GT_test_challenge.txt",
        "main_result": True,
    },
}

DB_FILES = [
    "admin.jsonl",
    "amazon.jsonl",
    "api_docs.jsonl",
    "file_system.jsonl",
    "gmail.jsonl",
    "model_hashes.json",
    "phone.jsonl",
    "simple_note.jsonl",
    "splitwise.jsonl",
    "spotify.jsonl",
    "supervisor.jsonl",
    "todoist.jsonl",
    "venmo.jsonl",
]

REQUIRED_RELATIVE_PATHS = [
    "evaluation/report.md",
    "evaluation/version.txt",
    "logs/api_calls.jsonl",
    "logs/environment_io.md",
    "logs/lm_calls.jsonl",
    "logs/loggger.log",
    "misc/cost.txt",
    "version/code.txt",
    "version/data.txt",
]

LM_INPUT_FIELDS = {
    "provider",
    "model",
    "messages",
    "tools",
    "temperature",
    "seed",
    "stop",
    "logprobs",
    "top_logprobs",
    "frequency_penalty",
    "presence_penalty",
    "n",
    "response_format",
    "completion_method",
}

LM_OUTPUT_FIELDS = {
    "choices",
    "usage",
    "cost",
    "id",
    "model",
    "created",
    "object",
    "service_tier",
    "system_fingerprint",
    # The provider may omit optional moderation metadata from otherwise complete responses.
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def load_jsonl(path: Path) -> list[Any]:
    items: list[Any] = []
    for line_number, line in enumerate(path.read_text().splitlines(), start=1):
        if not line.strip():
            continue
        try:
            items.append(json.loads(line))
        except json.JSONDecodeError as error:
            raise ValueError(f"{path}:{line_number}: invalid JSON: {error}") from error
    return items


def git_info(path: Path) -> dict[str, Any]:
    def run(*args: str) -> str:
        return subprocess.check_output(["git", "-C", str(path), *args], text=True).strip()

    return {
        "head": run("rev-parse", "HEAD"),
        "branch": run("branch", "--show-current"),
        "dirty": bool(run("status", "--short")),
    }


def count_playbook_bullets(text: str) -> int:
    return sum(
        bool(
            re.match(
                r"^\s*(?:[-*]\s+|\[[A-Za-z]+(?:[.-]\d+)\]|[A-Za-z]+\.\d+\s+)",
                line,
            )
        )
        for line in text.splitlines()
    )


def playbook_stats(path: Path) -> dict[str, Any]:
    text = path.read_text()
    return {
        "path": str(path.relative_to(PROJECT_ROOT)),
        "sha256": sha256(path),
        "bytes": path.stat().st_size,
        "characters": len(text),
        "nonempty_lines": sum(bool(line.strip()) for line in text.splitlines()),
        "bullet_count": count_playbook_bullets(text),
    }


def usage_from_calls(calls: list[dict[str, Any]]) -> dict[str, Any]:
    prompt = completion = cached = 0
    for call in calls:
        usage = (call.get("output") or {}).get("usage") or {}
        prompt += int(usage.get("prompt_tokens") or 0)
        completion += int(usage.get("completion_tokens") or 0)
        details = usage.get("prompt_tokens_details") or {}
        cached += int(details.get("cached_tokens") or 0)
    uncached = max(prompt - cached, 0)
    cost = (
        uncached * RATES["input_usd_per_1m_tokens"]
        + cached * RATES["cache_read_usd_per_1m_tokens"]
        + completion * RATES["output_usd_per_1m_tokens"]
    ) / 1_000_000
    return {
        "llm_calls": len(calls),
        "prompt_tokens": prompt,
        "cached_prompt_tokens": cached,
        "uncached_prompt_tokens": uncached,
        "completion_tokens": completion,
        "total_tokens": prompt + completion,
        "fixed_registry_cost_usd": round(cost, 8),
    }


def audit_task(task_dir: Path) -> dict[str, Any]:
    issues: list[str] = []
    for directory in ["checkpoints", "dbs", "evaluation", "logs", "misc", "version"]:
        if not (task_dir / directory).is_dir():
            issues.append(f"missing directory: {directory}")

    for name in DB_FILES:
        if not (task_dir / "dbs" / name).is_file():
            issues.append(f"missing file: dbs/{name}")
    for relative in REQUIRED_RELATIVE_PATHS:
        if not (task_dir / relative).is_file():
            issues.append(f"missing file: {relative}")

    db_dir = task_dir / "dbs"
    for name in DB_FILES:
        path = db_dir / name
        if not path.is_file():
            continue
        try:
            if name == "model_hashes.json":
                load_json(path)
            else:
                for index, item in enumerate(load_jsonl(path), start=1):
                    if not isinstance(item, list) or len(item) != 3:
                        issues.append(f"invalid AppWorld DB item: dbs/{name}:{index}")
        except (ValueError, json.JSONDecodeError) as error:
            issues.append(str(error))

    api_path = task_dir / "logs" / "api_calls.jsonl"
    api_calls: list[dict[str, Any]] = []
    if api_path.is_file():
        try:
            api_calls = load_jsonl(api_path)
            for index, item in enumerate(api_calls, start=1):
                if not isinstance(item, dict) or set(item) != {"method", "url", "data"}:
                    issues.append(f"invalid api_calls schema at item {index}")
        except ValueError as error:
            issues.append(str(error))

    lm_path = task_dir / "logs" / "lm_calls.jsonl"
    lm_calls: list[dict[str, Any]] = []
    if lm_path.is_file():
        try:
            lm_calls = load_jsonl(lm_path)
            for index, item in enumerate(lm_calls, start=1):
                if not isinstance(item, dict) or not {"id", "input", "output"} <= set(item):
                    issues.append(f"invalid lm_calls top-level schema at item {index}")
                    continue
                missing_input = LM_INPUT_FIELDS - set(item.get("input") or {})
                missing_output = LM_OUTPUT_FIELDS - set(item.get("output") or {})
                if missing_input:
                    issues.append(f"lm_calls item {index} missing input fields: {sorted(missing_input)}")
                if missing_output:
                    issues.append(f"lm_calls item {index} missing output fields: {sorted(missing_output)}")
        except ValueError as error:
            issues.append(str(error))

    environment_path = task_dir / "logs" / "environment_io.md"
    completed = False
    if environment_path.is_file():
        environment_text = environment_path.read_text()
        completed = "complete_task" in environment_text
        if "### Environment Interaction " not in environment_text:
            issues.append("environment_io.md lacks interaction heading")
        if "```python" not in environment_text:
            issues.append("environment_io.md lacks Python code fence")
        if "----------------------------------------------------------------------------" not in environment_text:
            issues.append("environment_io.md lacks ACE separator")

    report_path = task_dir / "evaluation" / "report.md"
    if report_path.is_file():
        report_text = report_path.read_text()
        for section in ["Overall Stats", "Passes", "Fails"]:
            if section not in report_text:
                issues.append(f"evaluation/report.md lacks {section}")

    return {
        "task_id": task_dir.name,
        "issues": issues,
        "api_calls": len(api_calls),
        "reached_complete_task": completed,
        **usage_from_calls(lm_calls),
    }


def official_metrics(evaluation: dict[str, Any]) -> dict[str, Any]:
    individual = evaluation["individual"]
    success_map = {task_id: bool(item["success"]) for task_id, item in individual.items()}
    by_difficulty: dict[str, Any] = {}
    grouped: dict[int, list[str]] = defaultdict(list)
    for task_id, item in individual.items():
        grouped[int(item["difficulty"])].append(task_id)
    for difficulty, task_ids in sorted(grouped.items()):
        successes = sum(success_map[task_id] for task_id in task_ids)
        families: dict[str, list[str]] = defaultdict(list)
        for task_id in task_ids:
            families[task_id.rsplit("_", 1)[0]].append(task_id)
        complete_families = {
            family: ids for family, ids in families.items() if len(ids) == 3
        }
        family_successes = sum(
            all(success_map[task_id] for task_id in ids)
            for ids in complete_families.values()
        )
        by_difficulty[str(difficulty)] = {
            "tasks": len(task_ids),
            "success_tasks": successes,
            "tgc": round(100 * successes / len(task_ids), 1),
            "complete_families": len(complete_families),
            "success_families": family_successes,
            "sgc": (
                round(100 * family_successes / len(complete_families), 1)
                if complete_families
                else None
            ),
        }
    families: dict[str, list[str]] = defaultdict(list)
    for task_id in individual:
        families[task_id.rsplit("_", 1)[0]].append(task_id)
    successful_families = sum(
        len(ids) == 3 and all(success_map[task_id] for task_id in ids)
        for ids in families.values()
    )
    return {
        "tgc": evaluation["aggregate"]["task_goal_completion"],
        "sgc": evaluation["aggregate"]["scenario_goal_completion"],
        "tasks": len(individual),
        "success_tasks": sum(success_map.values()),
        "failed_tasks": sorted(task_id for task_id, success in success_map.items() if not success),
        "families": len(families),
        "success_families": successful_families,
        "by_difficulty": by_difficulty,
        "success_map": success_map,
    }


def summarize_run(key: str, spec: dict[str, Any]) -> dict[str, Any]:
    run_root = OUTPUT_ROOT / spec["experiment"]
    evaluation_path = run_root / "evaluations" / f"{spec['dataset']}.json"
    if not evaluation_path.is_file():
        raise FileNotFoundError(f"Missing official evaluation: {evaluation_path}")
    evaluation = load_json(evaluation_path)
    metrics = official_metrics(evaluation)
    expected_ids = load_task_ids(spec["dataset"])
    actual_ids = sorted(path.name for path in (run_root / "tasks").iterdir() if path.is_dir())
    task_audits = [audit_task(run_root / "tasks" / task_id) for task_id in expected_ids]
    totals = {
        field: sum(item[field] for item in task_audits)
        for field in [
            "api_calls",
            "llm_calls",
            "prompt_tokens",
            "cached_prompt_tokens",
            "uncached_prompt_tokens",
            "completion_tokens",
            "total_tokens",
            "fixed_registry_cost_usd",
        ]
    }
    totals["fixed_registry_cost_usd"] = round(totals["fixed_registry_cost_usd"], 8)
    artifact_issues = {
        audit["task_id"]: audit["issues"] for audit in task_audits if audit["issues"]
    }
    return {
        "key": key,
        **spec,
        "output_root": str(run_root.relative_to(PROJECT_ROOT)),
        "evaluation_path": str(evaluation_path.relative_to(PROJECT_ROOT)),
        "expected_task_ids": expected_ids,
        "actual_task_ids": actual_ids,
        "missing_task_ids": sorted(set(expected_ids) - set(actual_ids)),
        "extra_task_ids": sorted(set(actual_ids) - set(expected_ids)),
        "metrics": metrics,
        "usage": totals,
        "no_complete_task_ids": sorted(
            audit["task_id"] for audit in task_audits if not audit["reached_complete_task"]
        ),
        "artifact_audit": {
            "valid": not artifact_issues and set(expected_ids) == set(actual_ids),
            "issue_count": sum(len(issues) for issues in artifact_issues.values()),
            "issues_by_task": artifact_issues,
        },
    }


def migration(offline: dict[str, Any], online: dict[str, Any]) -> dict[str, Any]:
    offline_map = offline["metrics"]["success_map"]
    online_map = online["metrics"]["success_map"]
    categories = {
        "both_success": [],
        "offline_fail_online_success": [],
        "offline_success_online_fail": [],
        "both_fail": [],
    }
    for task_id in sorted(offline_map):
        pair = (offline_map[task_id], online_map[task_id])
        if pair == (True, True):
            categories["both_success"].append(task_id)
        elif pair == (False, True):
            categories["offline_fail_online_success"].append(task_id)
        elif pair == (True, False):
            categories["offline_success_online_fail"].append(task_id)
        else:
            categories["both_fail"].append(task_id)
    return {
        **categories,
        "counts": {key: len(value) for key, value in categories.items()},
        "tgc_delta_points": round(online["metrics"]["tgc"] - offline["metrics"]["tgc"], 1),
        "sgc_delta_points": round(online["metrics"]["sgc"] - offline["metrics"]["sgc"], 1),
    }


def markdown(summary: dict[str, Any]) -> str:
    runs = summary["runs"]
    lines = [
        "# Quick2h Qwen3.8-flash ACE offline/online results",
        "",
        f"Generated: {summary['generated_at']}",
        "",
        "## Official results",
        "",
        "| Split | Mode | Success tasks | TGC | Success families | SGC |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for key in ["offline_normal", "online_normal", "offline_challenge", "online_challenge"]:
        run = runs[key]
        metrics = run["metrics"]
        lines.append(
            f"| {run['split']} | {run['mode']} | {metrics['success_tasks']}/{metrics['tasks']} "
            f"| {metrics['tgc']:.1f}% | {metrics['success_families']}/{metrics['families']} "
            f"| {metrics['sgc']:.1f}% |"
        )
    lines += [
        "",
        "## Difficulty breakdown",
        "",
        "| Split | Mode | Difficulty | Success tasks | TGC | Complete families | SGC |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for key in ["offline_normal", "online_normal", "offline_challenge", "online_challenge"]:
        run = runs[key]
        for difficulty, item in run["metrics"]["by_difficulty"].items():
            sgc = "n/a" if item["sgc"] is None else f"{item['sgc']:.1f}%"
            lines.append(
                f"| {run['split']} | {run['mode']} | {difficulty} | "
                f"{item['success_tasks']}/{item['tasks']} | {item['tgc']:.1f}% | "
                f"{item['success_families']}/{item['complete_families']} | {sgc} |"
            )
    lines += ["", "## Offline/online migration", ""]
    for split in ["normal", "challenge"]:
        item = summary["migration"][split]
        lines += [
            f"### {split}",
            "",
            f"- Both succeed: {item['counts']['both_success']} — {', '.join(item['both_success']) or 'None'}",
            f"- Offline fail → online succeed: {item['counts']['offline_fail_online_success']} — {', '.join(item['offline_fail_online_success']) or 'None'}",
            f"- Offline succeed → online fail: {item['counts']['offline_success_online_fail']} — {', '.join(item['offline_success_online_fail']) or 'None'}",
            f"- Both fail: {item['counts']['both_fail']} — {', '.join(item['both_fail']) or 'None'}",
            f"- Online − offline: TGC {item['tgc_delta_points']:+.1f} points; SGC {item['sgc_delta_points']:+.1f} points.",
            "",
        ]
    lines += [
        "## Usage and fixed-registry cost",
        "",
        "| Runner | LLM calls | Prompt tokens | Cached | Completion tokens | API calls | Cost (USD) |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for key, run in runs.items():
        usage = run["usage"]
        lines.append(
            f"| {key} | {usage['llm_calls']} | {usage['prompt_tokens']} | "
            f"{usage['cached_prompt_tokens']} | {usage['completion_tokens']} | "
            f"{usage['api_calls']} | ${usage['fixed_registry_cost_usd']:.6f} |"
        )
    adaptation_cost = runs["offline_adaptation"]["usage"]["fixed_registry_cost_usd"]
    offline_normal_cost = runs["offline_normal"]["usage"]["fixed_registry_cost_usd"]
    offline_challenge_cost = runs["offline_challenge"]["usage"]["fixed_registry_cost_usd"]
    project_total_cost = sum(run["usage"]["fixed_registry_cost_usd"] for run in runs.values())
    lines += [
        "",
        "Rates: input $0.64/M, output $2.16/M, cache-read $0.08/M. Cached input is excluded from ordinary input before pricing.",
        "",
        f"Offline-normal standalone end-to-end cost: ${adaptation_cost + offline_normal_cost:.6f} "
        f"(shared adaptation ${adaptation_cost:.6f} + frozen normal ${offline_normal_cost:.6f}).",
        f"Offline-challenge standalone end-to-end cost: ${adaptation_cost + offline_challenge_cost:.6f} "
        f"(shared adaptation ${adaptation_cost:.6f} + frozen challenge ${offline_challenge_cost:.6f}).",
        f"Actual five-run project cost with adaptation counted once: ${project_total_cost:.6f}.",
        "",
        "## Artifact audit",
        "",
    ]
    for key, run in runs.items():
        audit = run["artifact_audit"]
        lines.append(
            f"- `{key}`: {'PASS' if audit['valid'] else 'FAIL'}; "
            f"issues={audit['issue_count']}; missing_tasks={len(run['missing_task_ids'])}; "
            f"extra_tasks={len(run['extra_task_ids'])}; no_complete_task={len(run['no_complete_task_ids'])}."
        )
    lines += [
        "",
        "## Playbooks",
        "",
        "| Playbook | SHA-256 | Characters | Bullets |",
        "| --- | --- | ---: | ---: |",
    ]
    for name, item in summary["playbooks"].items():
        lines.append(
            f"| {name} | `{item['sha256']}` | {item['characters']} | {item['bullet_count']} |"
        )
    lines += [
        "",
        "## Interpretation",
        "",
        "This is a five-family-per-split method-debugging sample. TGC is task-level strict success; SGC counts a family only when all three variants succeed. Do not treat these pilot rates as full-split estimates.",
        "",
        "Official evaluation JSON/TXT and every task-level AppWorld artifact remain the primary evidence. This report is an auditable derived summary.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    runs = {key: summarize_run(key, spec) for key, spec in RUNS.items()}
    initial_playbook = EXPERIMENTS / "playbooks" / "appworld_initial_playbook.txt"
    playbooks = {
        "initial": playbook_stats(initial_playbook),
        "offline": playbook_stats(PLAYBOOK_ROOT / "offline_no_GT.txt"),
        "online_normal": playbook_stats(PLAYBOOK_ROOT / "online_no_GT_test_normal.txt"),
        "online_challenge": playbook_stats(PLAYBOOK_ROOT / "online_no_GT_test_challenge.txt"),
    }
    summary = {
        "generated_at": datetime.now(ZoneInfo("America/Toronto")).isoformat(),
        "actual_model": "qwen3.8-flash",
        "rates": RATES,
        "git": {
            "root": git_info(PROJECT_ROOT.parent),
            "ace_appworld": git_info(PROJECT_ROOT),
        },
        "dataset_sha256": {
            dataset: sha256(PROJECT_ROOT / "data" / "datasets" / f"{dataset}.txt")
            for dataset in ["quick2h_train", "quick2h_test_normal", "quick2h_test_challenge"]
        },
        "runs": runs,
        "migration": {
            "normal": migration(runs["offline_normal"], runs["online_normal"]),
            "challenge": migration(runs["offline_challenge"], runs["online_challenge"]),
        },
        "playbooks": playbooks,
    }

    checksum_paths: set[Path] = set()
    checksum_paths.update(CONFIG_ROOT.glob("*"))
    checksum_paths.update(PROJECT_ROOT / "data" / "datasets" / f"{name}.txt" for name in [
        "quick2h_train",
        "quick2h_test_normal",
        "quick2h_test_challenge",
    ])
    checksum_paths.update(path for path in PLAYBOOK_ROOT.glob("*.txt"))
    for spec in RUNS.values():
        run_root = OUTPUT_ROOT / spec["experiment"]
        checksum_paths.update(path for path in run_root.rglob("*") if path.is_file())
    checksums = {
        str(path.relative_to(PROJECT_ROOT)): sha256(path)
        for path in sorted(checksum_paths)
        if path.is_file()
    }

    SUMMARY_PATH.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    REPORT_PATH.write_text(markdown(summary))
    CHECKSUM_PATH.write_text(
        json.dumps(
            {
                "generated_at": summary["generated_at"],
                "sha256": checksums,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    print(f"Wrote {REPORT_PATH}")
    print(f"Wrote {SUMMARY_PATH}")
    print(f"Wrote {CHECKSUM_PATH}")


if __name__ == "__main__":
    main()
