"""Outer task stream. Baseline adapters own all within-task sequencing."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from appworld.common.path_store import path_store
from appworld.task import Task

from appworld_experiments.code.common.contracts import (
    BaselineAdapter,
    BaselineServices,
    BaselineTaskResult,
    LLMLoggerPort,
    TaskContext,
)
from appworld_experiments.code.common.episodes import EpisodeService
from appworld_experiments.code.common.evaluator import TaskEvaluator, evaluate_dataset
from appworld_experiments.code.common.output_contract import (
    validate_dataset_output,
    validate_task_output,
)
from appworld_experiments.code.common.task_loader import load_task_stream


def run_dataset(
    *,
    adapter: BaselineAdapter,
    dataset_name: str,
    experiment_name: str,
    logger_factory: Callable[[TaskContext], LLMLoggerPort],
    num_epochs: int = 1,
    appworld_kwargs: dict[str, Any] | None = None,
    output_root: Path | None = None,
    suppress_evaluation_errors: bool = True,
    validate_outputs: bool = True,
) -> list[BaselineTaskResult]:
    """Run an ordered dataset without prescribing the adapter's inner loop.

    `logger_factory` is required: Section 3 supplies the canonical logger.
    The adapter must open episodes through `services.episodes` and may call
    environment, completion, and evaluator ports in its original order.
    """

    task_refs = load_task_stream(dataset_name, num_epochs=num_epochs)
    dataset_size = len(task_refs) // num_epochs
    canonical_root = Path(path_store.experiment_outputs).resolve()
    root = canonical_root if output_root is None else output_root.resolve()
    if root != canonical_root:
        raise ValueError("output_root must match AppWorld's experiment_outputs path")
    results: list[BaselineTaskResult] = []
    for ref in task_refs:
        task_dir = root / experiment_name / "tasks" / ref.task_id
        artifacts_dir = root / experiment_name / "baseline_artifacts" / adapter.name / ref.task_id
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        context = TaskContext(
            task_id=ref.task_id,
            dataset_name=dataset_name,
            dataset_index=ref.dataset_index,
            dataset_size=dataset_size,
            total_tasks=len(task_refs),
            epoch=ref.epoch,
            experiment_name=experiment_name,
            primary_task_dir=task_dir,
            artifacts_dir=artifacts_dir,
            task=Task.load(task_id=ref.task_id, load_ground_truth=False),
        )
        episodes = EpisodeService(
            task_id=ref.task_id,
            experiment_name=experiment_name,
            primary_task_dir=task_dir,
            appworld_kwargs=appworld_kwargs,
        )
        logger = logger_factory(context)
        if logger.path != task_dir / "logs" / "lm_calls.jsonl":
            raise ValueError("Logger must write only to the canonical primary task path")
        evaluator = TaskEvaluator(
            task_id=ref.task_id,
            experiment_name=experiment_name,
            primary_task_dir=task_dir,
        )
        services = BaselineServices(
            episodes=episodes,
            environment=episodes,
            completion=episodes,
            evaluator=evaluator,
            llm=logger,
            artifacts=artifacts_dir,
        )
        result = adapter.run_task(context, services)
        if episodes.is_open:
            raise RuntimeError("Baseline adapter returned with an open AppWorld episode")
        evaluator.ensure_final_primary_report_if_needed(
            suppress_errors=suppress_evaluation_errors
        )
        if validate_outputs:
            validate_task_output(task_dir)
        results.append(result)

    evaluate_dataset(
        experiment_name=experiment_name,
        dataset_name=dataset_name,
        suppress_errors=suppress_evaluation_errors,
    )
    if validate_outputs:
        validate_dataset_output(root, experiment_name, dataset_name)
    return results
