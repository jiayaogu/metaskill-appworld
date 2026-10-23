"""Read-only checks for AppWorld-owned and shared task artifacts."""

from __future__ import annotations

from pathlib import Path


TASK_FILES = (
    "logs/api_calls.jsonl",
    "logs/environment_io.md",
    "logs/lm_calls.jsonl",
    "evaluation/report.md",
    "evaluation/version.txt",
    "version/code.txt",
    "version/data.txt",
)
TASK_DIRECTORIES = ("dbs", "checkpoints", "logs", "evaluation", "version")


def validate_task_output(task_directory: Path) -> None:
    missing = [
        str(task_directory / relative)
        for relative in TASK_DIRECTORIES
        if not (task_directory / relative).is_dir()
    ]
    missing.extend(
        str(task_directory / relative)
        for relative in TASK_FILES
        if not (task_directory / relative).is_file()
    )
    if missing:
        raise FileNotFoundError("Missing canonical task outputs:\n" + "\n".join(missing))


def validate_dataset_output(output_root: Path, experiment_name: str, dataset_name: str) -> None:
    directory = output_root / experiment_name / "evaluations"
    missing = [
        str(directory / f"{dataset_name}.{suffix}")
        for suffix in ("json", "txt")
        if not (directory / f"{dataset_name}.{suffix}").is_file()
    ]
    if missing:
        raise FileNotFoundError("Missing official aggregate outputs:\n" + "\n".join(missing))
