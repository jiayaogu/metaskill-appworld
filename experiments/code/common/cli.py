"""Validate and run a shared AppWorld baseline config.

Run with `python -m appworld_experiments.code.common.cli ...` from the AppWorld
environment. `run` never starts a real provider call until config preflight and
an empty output target have both succeeded.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from dotenv import load_dotenv

from appworld.common.path_store import path_store

from appworld_experiments.code.common.appworld_runner import run_dataset
from appworld_experiments.code.common.baselines import make_adapter
from appworld_experiments.code.common.config import RunSpec, load_run_config
from appworld_experiments.code.common.evaluator import evaluate_dataset
from appworld_experiments.code.common.lm_logger import task_lm_logger
from appworld_experiments.code.common.output_contract import (
    validate_dataset_output,
    validate_task_output,
)
from appworld_experiments.code.common.task_loader import load_task_stream


def _manifest_path(spec: RunSpec) -> Path:
    return spec.output_root / spec.experiment_name / "run_manifest.json"


def _run(spec: RunSpec) -> None:
    if spec.runtime.get("dry_run", False):
        print(json.dumps(spec.manifest(), indent=2, sort_keys=True))
        return
    if spec.runtime.get("resume", False):
        raise NotImplementedError("Unified resume requires checkpoint-prefix parity tests")
    if int(spec.runtime.get("num_processes", 1)) != 1:
        raise NotImplementedError("Unified task parallelism is not migrated")
    experiment_dir = spec.output_root / spec.experiment_name
    if experiment_dir.exists():
        raise FileExistsError(
            f"Refusing to overwrite an existing experiment directory: {experiment_dir}"
        )
    if spec.provider_env_file is not None:
        load_dotenv(spec.provider_env_file, override=False)
    if spec.api_key_env not in os.environ:
        raise ValueError(f"Provider API key env is unset: {spec.api_key_env}")
    if spec.api_key_env != "OPENAI_API_KEY":
        os.environ["OPENAI_API_KEY"] = os.environ[spec.api_key_env]
    if spec.base_url_env in os.environ and spec.base_url_env != "OPENAI_BASE_URL":
        os.environ["OPENAI_BASE_URL"] = os.environ[spec.base_url_env]
    adapter = make_adapter(spec)
    previous_root = path_store.root
    path_store.update_root(str(spec.appworld_root))
    try:
        load_task_stream(spec.dataset_name, num_epochs=spec.num_epochs)
        experiment_dir.mkdir(parents=True)
        _manifest_path(spec).write_text(
            json.dumps(spec.manifest(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        run_dataset(
            adapter=adapter,
            dataset_name=spec.dataset_name,
            experiment_name=spec.experiment_name,
            logger_factory=lambda context: task_lm_logger(
                spec.output_root, spec.experiment_name, spec.baseline, context.task_id
            ),
            num_epochs=spec.num_epochs,
            appworld_kwargs=spec.appworld_kwargs,
            output_root=spec.output_root,
            suppress_evaluation_errors=spec.evaluation.get("suppress_errors", True),
        )
    finally:
        path_store.update_root(previous_root)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("validate-config", "run", "evaluate", "validate-output"):
        command = sub.add_parser(name)
        command.add_argument("config", type=Path)
    args = parser.parse_args(argv)
    spec = load_run_config(args.config)
    if args.command == "validate-config":
        print(json.dumps(spec.manifest(), indent=2, sort_keys=True))
        return 0
    if args.command == "run":
        _run(spec)
        return 0
    previous_root = path_store.root
    path_store.update_root(str(spec.appworld_root))
    try:
        if args.command == "evaluate":
            evaluate_dataset(
                experiment_name=spec.experiment_name,
                dataset_name=spec.dataset_name,
                suppress_errors=spec.evaluation.get("suppress_errors", True),
            )
        else:
            for task_id in spec.ordered_task_ids:
                validate_task_output(spec.output_root / spec.experiment_name / "tasks" / task_id)
        validate_dataset_output(spec.output_root, spec.experiment_name, spec.dataset_name)
    finally:
        path_store.update_root(previous_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
