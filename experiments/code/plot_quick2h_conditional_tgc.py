"""Plot cumulative ACE TGC for a quick2h conditional test split.

Run from the workspace root with the system Python that provides matplotlib:
    /usr/bin/python3 ace-appworld/experiments/code/plot_quick2h_conditional_tgc.py --split test_challenge
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import OrderedDict
from itertools import combinations
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = PROJECT_ROOT / "experiments/outputs/ACE_18_task_online_no_GT_pilot"
FIGURES = PROJECT_ROOT / "experiments/figures"
MODELS = OrderedDict(
    [
        ("DeepSeek", ("deepseek-v3.retry2-deepseek-v4-flash-0731", "#0072B2", "-", "o")),
        ("Gemini", ("gemini-3.5-flash-lite", "#CC79A7", "-.", "s")),
        ("GPT-4.1", ("gpt-4.1", "#D55E00", "-", "^")),
        ("Qwen3", ("qwen3-8b.retry2-qwen3.8-flash", "#009E73", "--", "D")),
    ]
)


def load_task_order(dataset: Path) -> list[str]:
    task_ids = [line.strip() for line in dataset.read_text().splitlines() if line.strip()]
    if len(task_ids) != 15 or len(set(task_ids)) != 15:
        raise ValueError(f"Expected 15 unique tasks in {dataset}, found {len(task_ids)}")
    return task_ids


def validate_executor_order(task_ids: list[str], dataset_name: str) -> None:
    """Check the order recorded when each model's executor started its tasks."""
    log_root = OUTPUT_ROOT / "run_logs"
    for label, (run_name, _, _, _) in MODELS.items():
        if label in ("DeepSeek", "Qwen3"):
            log = (
                log_root
                / "quick2h_retry2_aliases"
                / f"ACE_18_task_online_no_GT_pilot__{dataset_name}__{run_name}.run.log"
            )
        else:
            log = log_root / dataset_name / f"{run_name}.run.log"
        content = log.read_text()
        executed = re.findall(r"^│ Task ID: ([a-f0-9]{7}_[123])\s+│$", content, re.MULTILINE)
        if executed != task_ids:
            raise ValueError(
                f"{label}: executor order in {log} differs from dataset order; "
                f"executed={executed}, dataset={task_ids}"
            )
        if f"{len(task_ids)} of {len(task_ids)} tasks completed." not in content:
            raise ValueError(f"{label}: no final task completion marker in {log}")


def load_outcomes(task_ids: list[str], outputs: Path, dataset_name: str) -> dict[str, list[int]]:
    outcomes = {}
    for label, (run_name, _, _, _) in MODELS.items():
        evaluation = outputs / run_name / "evaluations" / f"{dataset_name}.json"
        result = json.loads(evaluation.read_text())
        individual = result["individual"]
        if set(individual) != set(task_ids):
            missing = sorted(set(task_ids) - set(individual))
            extra = sorted(set(individual) - set(task_ids))
            raise ValueError(f"{label}: evaluation task IDs differ; missing={missing}, extra={extra}")
        flags = []
        for task_id in task_ids:
            success = individual[task_id]["success"]
            if not isinstance(success, bool):
                raise TypeError(f"{label} {task_id}: success must be boolean")
            flags.append(int(success))
        final_tgc = 100 * sum(flags) / len(flags)
        reported_tgc = result["aggregate"]["task_goal_completion"]
        if round(final_tgc, 1) != reported_tgc:
            raise ValueError(f"{label}: final {final_tgc:.1f}% differs from official {reported_tgc}%")
        outcomes[label] = flags
    return outcomes


def cumulative_tgc(flags: list[int]) -> list[float]:
    successes = 0
    values = []
    for n, success in enumerate(flags, start=1):
        successes += success
        values.append(100 * successes / n)
    return values


def write_csv(task_ids: list[str], outcomes: dict[str, list[int]], stem: str) -> Path:
    path = FIGURES / f"{stem}.csv"
    curves = {model: cumulative_tgc(flags) for model, flags in outcomes.items()}
    columns = ["n", "task_id", "scenario_id"]
    for model in MODELS:
        slug = model.lower().replace("-", "_").replace(".", "_")
        columns.extend((f"{slug}_success", f"{slug}_cumulative_tgc_percent"))
    with path.open("w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(columns)
        for index, task_id in enumerate(task_ids):
            row = [index + 1, task_id, task_id.rsplit("_", 1)[0]]
            for model in MODELS:
                row.extend((outcomes[model][index], f"{curves[model][index]:.6f}"))
            writer.writerow(row)
    return path


def plot(task_ids: list[str], outcomes: dict[str, list[int]], split: str, stem: str) -> list[Path]:
    fig, ax = plt.subplots(figsize=(10, 5.8), dpi=180)
    x = list(range(1, len(task_ids) + 1))
    for model, (_, color, linestyle, marker) in MODELS.items():
        flags = outcomes[model]
        final = 100 * sum(flags) / len(flags)
        ax.plot(
            x,
            cumulative_tgc(flags),
            label=f"{model}: {final:.1f}% ({sum(flags)}/{len(flags)})",
            color=color,
            linestyle=linestyle,
            linewidth=2.4,
            marker=marker,
            markersize=4.7,
            markerfacecolor="white",
            markeredgewidth=1.5,
        )
    ax.set(title=f"ACE cumulative TGC on quick2h conditional {split.replace('_', '-')}")
    ax.set_xlabel("Tasks completed in verified executor order (N)")
    ax.set_ylabel("Cumulative TGC (%)")
    ax.set_xlim(0, len(task_ids))
    ax.set_ylim(0, 105)
    ax.set_xticks(range(0, len(task_ids) + 1))
    ax.set_yticks(range(0, 101, 20))
    ax.grid(axis="y", color="#D8DDE3", linewidth=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(loc="lower right", frameon=True, facecolor="white", edgecolor="#D8DDE3")
    overlap = [
        f"{first} and {second} overlap"
        for first, second in combinations(MODELS, 2)
        if outcomes[first] == outcomes[second]
    ]
    note = "N=0 has no TGC value; curves begin at N=1."
    if overlap:
        note += " " + "; ".join(overlap) + "."
    fig.text(
        0.1,
        0.02,
        note,
        fontsize=9,
        color="#4B5563",
    )
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    paths = []
    for suffix in ("png", "pdf", "svg"):
        path = FIGURES / f"{stem}.{suffix}"
        fig.savefig(path, dpi=180)
        paths.append(path)
    plt.close(fig)
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=("test_normal", "test_challenge"), default="test_normal")
    args = parser.parse_args()
    dataset_name = f"quick2h_conditional_{args.split}"
    dataset = PROJECT_ROOT / "data/datasets" / f"{dataset_name}.txt"
    outputs = OUTPUT_ROOT / dataset_name
    stem = f"{dataset_name}_cumulative_tgc"
    FIGURES.mkdir(parents=True, exist_ok=True)
    task_ids = load_task_order(dataset)
    validate_executor_order(task_ids, dataset_name)
    outcomes = load_outcomes(task_ids, outputs, dataset_name)
    csv_path = write_csv(task_ids, outcomes, stem)
    figure_paths = plot(task_ids, outcomes, args.split, stem)
    for model, flags in outcomes.items():
        failures = [f"{n}:{task_id}" for n, (task_id, success) in enumerate(zip(task_ids, flags), 1) if not success]
        print(f"{model}: {sum(flags)}/{len(flags)}; failures={failures or 'none'}")
    print(csv_path)
    for path in figure_paths:
        print(path)


if __name__ == "__main__":
    main()
