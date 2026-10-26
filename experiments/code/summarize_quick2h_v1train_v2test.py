#!/usr/bin/env python3
"""Audit the v1-train/v2-test ACE extension and render a report section."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import summarize_quick2h_offline_online as shared


EXPERIMENTS = shared.EXPERIMENTS
PROJECT_ROOT = shared.PROJECT_ROOT
CAMPAIGN = "ACE_quick2h_v1train_v2test_20261026_retry1"
CONFIG_ROOT = EXPERIMENTS / "configs" / "ACE_quick2h_v2_offline_online" / "qwen3.8-flash"
PLAYBOOK_ROOT = EXPERIMENTS / "playbooks" / "quick2h_v1train_v2test_20261026_retry1" / "qwen3.8-flash"
TRAIN_OUTPUT_ROOT = EXPERIMENTS / "outputs" / "ACE_quick2h_offline_online" / "qwen3.8-flash"
TRAIN_PLAYBOOK = EXPERIMENTS / "playbooks" / "quick2h_offline_online" / "qwen3.8-flash" / "offline_no_GT.txt"
OUTPUT_ROOT = EXPERIMENTS / "outputs" / CAMPAIGN / "qwen3.8-flash"
ARCHIVE_ROOT = EXPERIMENTS / "outputs" / "archived_incomplete_test_runs_20261026.ACEv2"
PARTIAL_ROOT = ARCHIVE_ROOT / "ACE_quick2h_v1train_v2test_20261026" / "qwen3.8-flash"
PARTIAL_RETRY_TRAIN_ROOT = ARCHIVE_ROOT / CAMPAIGN / "qwen3.8-flash" / "offline_no_GT_adaptation"
PARTIAL_RETRY_CHALLENGE_ROOT = ARCHIVE_ROOT / (CAMPAIGN + "_interrupted") / "qwen3.8-flash"
SUMMARY_PATH = EXPERIMENTS / "quick2h_ace_v1train_v2test_summary.json"
SECTION_PATH = EXPERIMENTS / "quick2h_ace_v1train_v2test_report_section.md"
CHECKSUM_PATH = EXPERIMENTS / "quick2h_ace_v1train_v2test_checksums.json"
RECOVERY_MANIFEST = PARTIAL_RETRY_CHALLENGE_ROOT / "recovery_manifest.json"
ONLINE_RECOVERY2_MANIFEST = PARTIAL_RETRY_CHALLENGE_ROOT / "online_challenge_recovery2_manifest.json"
ONLINE_RECOVERY3_MANIFEST = PARTIAL_RETRY_CHALLENGE_ROOT / "online_challenge_recovery3_manifest.json"
OFFLINE_RECOVERY_MANIFEST = PARTIAL_RETRY_CHALLENGE_ROOT / "offline_challenge_recovery_manifest.json"

RUNS = {
    "offline_adaptation": {
        "experiment": "offline_no_GT_adaptation",
        "dataset": "quick2h_train",
        "mode": "offline adaptation",
        "split": "train v1",
        "playbook": "offline_no_GT.txt",
        "main_result": False,
    },
    "offline_normal": {
        "experiment": "offline_no_GT_evaluation_test_normal_v2",
        "dataset": "quick2h_test_normal_v2",
        "mode": "offline frozen",
        "split": "normal v2",
        "playbook": "offline_no_GT.txt",
        "main_result": True,
    },
    "offline_challenge": {
        "experiment": "offline_no_GT_evaluation_test_challenge_v2",
        "dataset": "quick2h_test_challenge_v2",
        "mode": "offline frozen",
        "split": "challenge v2",
        "playbook": "offline_no_GT.txt",
        "main_result": True,
    },
    "online_normal": {
        "experiment": "online_no_GT_test_normal_v2",
        "dataset": "quick2h_test_normal_v2",
        "mode": "online adaptive",
        "split": "normal v2",
        "playbook": "online_no_GT_test_normal_v2.txt",
        "main_result": True,
    },
    "online_challenge": {
        "experiment": "online_no_GT_test_challenge_v2",
        "dataset": "quick2h_test_challenge_v2",
        "mode": "online adaptive",
        "split": "challenge v2",
        "playbook": "online_no_GT_test_challenge_v2.txt",
        "main_result": True,
    },
}


def report_section(summary: dict) -> str:
    runs = summary["runs"]
    adaptation_cost = runs["offline_adaptation"]["usage"]["fixed_registry_cost_usd"]
    order = ["offline_adaptation", "offline_normal", "online_normal", "offline_challenge", "online_challenge"]
    lines = [
        "## V1 train → V2 test extension (2026-10-26)",
        "",
        f"Generated: {summary['generated_at']}",
        "",
        "Offline adaptation on `quick2h_train` (v1, 15 tasks) was completed in the earlier "
        "`ACE_quick2h_offline_online/qwen3.8-flash/offline_no_GT_adaptation` run; its complete "
        "playbook is reused unchanged for both V2 frozen tests. Two redundant fresh training "
        "attempts stalled at the provider and were interrupted; their partial artifacts are excluded. "
        "The online challenge run also resumed at task 5 after a stalled request, preserving its "
        "four completed tasks and updated playbook; the incomplete task directory was archived "
        "and rerun with a 300-second infrastructure timeout. Its exact task-boundary evidence is "
        f"`{RECOVERY_MANIFEST.relative_to(PROJECT_ROOT)}`. It resumed again from task 14 after another stalled "
        "request, recorded in `online_challenge_recovery2_manifest.json`, and reran the final "
        "task after a third stall (`online_challenge_recovery3_manifest.json`). The frozen challenge run "
        "likewise resumed for "
        "its final three tasks after a provider stall; its incomplete task was archived in "
        "`offline_challenge_recovery_manifest.json` under the same interrupted output root. "
        "Frozen offline and independently adaptive online runs use `quick2h_test_normal_v2` (21 tasks) "
        "and `quick2h_test_challenge_v2` (18 tasks). The online streams each start from the initial playbook. "
        "The challenge dataset is byte-identical to `experiments/samples/quick2h_challenge_v2/test_challenge.txt`. "
        "Training TGC/SGC below are diagnostics; the four test rows are the comparison results.",
        "",
        "| Dataset | Mode | Successful tasks | TGC | Successful families | SGC | Runner cost | Standalone E2E cost |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for key in order:
        run = runs[key]
        metrics = run["metrics"]
        cost = run["usage"]["fixed_registry_cost_usd"]
        standalone = adaptation_cost + cost if key in {"offline_normal", "offline_challenge"} else cost
        lines.append(
            f"| `{run['dataset']}` | {run['mode']} | {metrics['success_tasks']}/{metrics['tasks']} | "
            f"{metrics['tgc']:.1f}% | {metrics['success_families']}/{metrics['families']} | "
            f"{metrics['sgc']:.1f}% | ${cost:.8f} | ${standalone:.8f} |"
        )
    total_cost = sum(run["usage"]["fixed_registry_cost_usd"] for run in runs.values())
    v2_cost = total_cost - adaptation_cost
    interrupted_cost = summary["excluded_partial"]["usage"]["fixed_registry_cost_usd"]
    lines += [
        "",
        f"New V2 completed-run logged usage cost (four tests): ${v2_cost:.8f}.",
        f"Five completed runs' logged usage, counting the historical shared adaptation once: ${total_cost:.8f}. "
        "This is not an additional five-run charge for this extension.",
        f"Excluded interrupted attempts have {summary['excluded_partial']['usage']['llm_calls']} "
        f"logged LLM calls and ${summary['excluded_partial']['usage']['fixed_registry_cost_usd']:.8f} "
        "in additional usage-based cost. Calls that timed out without usage are not priced here; "
        "the provider's actual bill is unverified.",
        f"New extension work including completed V2 runs and logged interrupted usage: "
        f"${v2_cost + interrupted_cost:.8f}; this excludes the reused historical training cost "
        "and any unlogged provider charges.",
        "",
        "### Difficulty breakdown",
        "",
        "| Dataset | Mode | Difficulty | Successful tasks | TGC | Successful families | SGC |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for key in order[1:]:
        run = runs[key]
        for difficulty, item in run["metrics"]["by_difficulty"].items():
            sgc = "n/a" if item["sgc"] is None else f"{item['sgc']:.1f}%"
            lines.append(
                f"| `{run['dataset']}` | {run['mode']} | {difficulty} | "
                f"{item['success_tasks']}/{item['tasks']} | {item['tgc']:.1f}% | "
                f"{item['success_families']}/{item['complete_families']} | {sgc} |"
            )
    lines += ["", "### Paired outcomes", ""]
    for split in ["normal", "challenge"]:
        migration = summary["migration"][split]
        lines.append(
            f"- {split} v2: both succeed {migration['counts']['both_success']}; "
            f"offline fail → online succeed {migration['counts']['offline_fail_online_success']}; "
            f"offline succeed → online fail {migration['counts']['offline_success_online_fail']}; "
            f"both fail {migration['counts']['both_fail']}. "
            f"Online − offline: TGC {migration['tgc_delta_points']:+.1f} pp, "
            f"SGC {migration['sgc_delta_points']:+.1f} pp."
        )
        lines.append(
            f"- {split} v2 offline failures: "
            f"{', '.join(runs['offline_' + split]['metrics']['failed_tasks']) or 'none'}; "
            f"online failures: {', '.join(runs['online_' + split]['metrics']['failed_tasks']) or 'none'}."
        )
    lines += [
        "",
        "### Usage and artifact audit",
        "",
        "| Runner | LLM calls | Prompt tokens | Cached prompt | Completion tokens | AppWorld API calls | Artifacts | Missing `complete_task` |",
        "| --- | ---: | ---: | ---: | ---: | ---: | --- | ---: |",
    ]
    for key in order:
        run = runs[key]
        usage = run["usage"]
        audit = run["artifact_audit"]
        lines.append(
            f"| {key} | {usage['llm_calls']} | {usage['prompt_tokens']} | "
            f"{usage['cached_prompt_tokens']} | {usage['completion_tokens']} | {usage['api_calls']} | "
            f"{'PASS' if audit['valid'] else 'FAIL'} (issues={audit['issue_count']}, "
            f"missing={len(run['missing_task_ids'])}, extra={len(run['extra_task_ids'])}) | "
            f"{len(run['no_complete_task_ids'])} |"
        )
    lines += [
        "",
        "Cost uses logged usage and fixed rates: uncached input $0.64/M, cached input $0.08/M, "
        "completion $2.16/M. It is an estimate, not verified provider billing. "
        "Provider responses may omit optional `moderation` metadata; the audit requires the "
        "response content, usage, cost, and other recorded identity fields.",
        "",
        "### Inputs and playbooks",
        "",
        "| Artifact | SHA-256 |",
        "| --- | --- |",
    ]
    for name, digest in summary["dataset_sha256"].items():
        lines.append(f"| `{name}.txt` | `{digest}` |")
    for name, item in summary["playbooks"].items():
        lines.append(f"| {name} playbook ({item['bullet_count']} bullets) | `{item['sha256']}` |")
    lines += [
        "",
        "Official V2 per-task and aggregate evaluations are under "
        "`experiments/outputs/ACE_quick2h_v1train_v2test_20261026_retry1/qwen3.8-flash/`; "
        "the completed training evaluation is under "
        "`experiments/outputs/ACE_quick2h_offline_online/qwen3.8-flash/offline_no_GT_adaptation/`. "
        "The machine-readable summary is `experiments/quick2h_ace_v1train_v2test_summary.json`.",
        f"Interrupted artifacts were moved without deleting run files; see "
        f"`{(ARCHIVE_ROOT / 'ARCHIVE_MANIFEST.md').relative_to(PROJECT_ROOT)}` for restoration paths.",
        "",
        "These samples are small and overlap with earlier intermediate experiments; treat the scores as method diagnostics, "
        "not independent full-split estimates. The model is identified by the provider alias `qwen3.8-flash`; "
        "the provider does not supply a verified immutable backend version for comparing the historical training "
        "run with these V2 tests.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    archive = shared.load_json(ARCHIVE_ROOT / "ARCHIVE_MANIFEST.json")
    assert len(archive["items"]) == 3

    def resolved_recovery(path: Path) -> dict:
        record = shared.load_json(path)
        original = Path(record["archived_partial_task"])
        relative = original.relative_to("ace-appworld/experiments/outputs")
        resolved = ARCHIVE_ROOT / relative
        assert resolved.is_dir()
        record["resolved_archived_partial_task"] = str(resolved.relative_to(PROJECT_ROOT))
        return record

    previous = shared.load_json(EXPERIMENTS / "quick2h_ace_offline_online_summary.json")
    assert shared.sha256(TRAIN_PLAYBOOK) == previous["playbooks"]["offline"]["sha256"]
    assert shared.sha256(PROJECT_ROOT / "data/datasets/quick2h_train.txt") == previous["dataset_sha256"]["quick2h_train"]
    assert shared.sha256(PROJECT_ROOT / "data/datasets/quick2h_test_challenge_v2.txt") == shared.sha256(
        EXPERIMENTS / "samples/quick2h_challenge_v2/test_challenge.txt"
    )
    recovery = resolved_recovery(RECOVERY_MANIFEST)
    challenge_ids = shared.load_task_ids("quick2h_test_challenge_v2")
    prefix = recovery["completed_prefix"]
    assert challenge_ids[:len(prefix)] == prefix
    assert challenge_ids[len(prefix):] == recovery["remaining_task_ids"]
    online_recovery2 = resolved_recovery(ONLINE_RECOVERY2_MANIFEST)
    online_prefix2 = online_recovery2["completed_prefix"]
    assert challenge_ids[:len(online_prefix2)] == online_prefix2
    assert challenge_ids[len(online_prefix2):] == online_recovery2["remaining_task_ids"]
    online_recovery3 = resolved_recovery(ONLINE_RECOVERY3_MANIFEST)
    online_prefix3 = online_recovery3["completed_prefix"]
    assert challenge_ids[:len(online_prefix3)] == online_prefix3
    assert challenge_ids[len(online_prefix3):] == online_recovery3["remaining_task_ids"]
    offline_recovery = resolved_recovery(OFFLINE_RECOVERY_MANIFEST)
    offline_prefix = offline_recovery["completed_prefix"]
    assert challenge_ids[:len(offline_prefix)] == offline_prefix
    assert challenge_ids[len(offline_prefix):] == offline_recovery["remaining_task_ids"]
    assert shared.sha256(TRAIN_PLAYBOOK) == offline_recovery["frozen_playbook_sha256"]
    runs = {}
    for key, spec in RUNS.items():
        shared.OUTPUT_ROOT = TRAIN_OUTPUT_ROOT if key == "offline_adaptation" else OUTPUT_ROOT
        runs[key] = shared.summarize_run(key, spec)
    playbooks = {
        "initial": shared.playbook_stats(EXPERIMENTS / "playbooks" / "appworld_initial_playbook.txt"),
        "offline": shared.playbook_stats(TRAIN_PLAYBOOK),
        "online_normal": shared.playbook_stats(PLAYBOOK_ROOT / "online_no_GT_test_normal_v2.txt"),
        "online_challenge": shared.playbook_stats(PLAYBOOK_ROOT / "online_no_GT_test_challenge_v2.txt"),
    }
    datasets = ["quick2h_train", "quick2h_test_normal_v2", "quick2h_test_challenge_v2"]
    summary = {
        "generated_at": datetime.now(ZoneInfo("America/Toronto")).isoformat(),
        "actual_model": "qwen3.8-flash",
        "campaign": CAMPAIGN,
        "rates": shared.RATES,
        "git": {"root": shared.git_info(PROJECT_ROOT.parent), "ace_appworld": shared.git_info(PROJECT_ROOT)},
        "dataset_sha256": {
            name: shared.sha256(PROJECT_ROOT / "data" / "datasets" / f"{name}.txt") for name in datasets
        },
        "runs": runs,
        "migration": {
            split: shared.migration(runs["offline_" + split], runs["online_" + split])
            for split in ["normal", "challenge"]
        },
        "playbooks": playbooks,
        "archive": {"manifest": str((ARCHIVE_ROOT / "ARCHIVE_MANIFEST.json").relative_to(PROJECT_ROOT))},
        "recovery": {
            "online_challenge_first": recovery,
            "online_challenge_second": online_recovery2,
            "online_challenge_third": online_recovery3,
            "offline_challenge": offline_recovery,
        },
        "excluded_partial": {
            "output_roots": [str(path.relative_to(PROJECT_ROOT)) for path in (PARTIAL_ROOT, PARTIAL_RETRY_TRAIN_ROOT, PARTIAL_RETRY_CHALLENGE_ROOT)],
            "status": "interrupted work after provider stalls; excluded from scores",
            "usage": shared.usage_from_calls(
                [
                    call
                    for root in (PARTIAL_ROOT, PARTIAL_RETRY_TRAIN_ROOT, PARTIAL_RETRY_CHALLENGE_ROOT)
                    for path in sorted(root.rglob("lm_calls.jsonl"))
                    for call in shared.load_jsonl(path)
                ]
            ),
        },
    }
    SUMMARY_PATH.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    SECTION_PATH.write_text(report_section(summary))
    checksum_paths: set[Path] = set(CONFIG_ROOT.glob("*"))
    checksum_paths.update(PROJECT_ROOT / "data" / "datasets" / f"{name}.txt" for name in datasets)
    checksum_paths.update(PLAYBOOK_ROOT.glob("*.txt"))
    checksum_paths.add(TRAIN_PLAYBOOK)
    checksum_paths.update(path for path in (TRAIN_OUTPUT_ROOT / "offline_no_GT_adaptation").rglob("*") if path.is_file())
    checksum_paths.update(path for path in OUTPUT_ROOT.rglob("*") if path.is_file())
    checksum_paths.update(path for path in PARTIAL_ROOT.rglob("*") if path.is_file())
    checksum_paths.update(path for path in PARTIAL_RETRY_CHALLENGE_ROOT.rglob("*") if path.is_file())
    checksum_paths.update(path for path in ARCHIVE_ROOT.glob("ARCHIVE_MANIFEST.*") if path.is_file())
    checksum_paths.update([SUMMARY_PATH, SECTION_PATH])
    checksums = {
        str(path.relative_to(PROJECT_ROOT)): shared.sha256(path)
        for path in sorted(checksum_paths)
        if path.is_file()
    }
    CHECKSUM_PATH.write_text(json.dumps({"generated_at": summary["generated_at"], "sha256": checksums}, indent=2, sort_keys=True) + "\n")
    print(f"Wrote {SUMMARY_PATH}")
    print(f"Wrote {SECTION_PATH}")
    print(f"Wrote {CHECKSUM_PATH}")


if __name__ == "__main__":
    main()
