"""The only task-selection path in the unified runner."""

from __future__ import annotations

from dataclasses import dataclass

from appworld.task import Task, load_task_ids, valid_dataset_names


@dataclass(frozen=True)
class TaskRef:
    task_id: str
    dataset_index: int
    epoch: int


def load_task_stream(dataset_name: str, *, num_epochs: int = 1) -> tuple[TaskRef, ...]:
    """Resolve any AppWorld-registered dataset, preserving its file order."""

    if dataset_name not in valid_dataset_names():
        raise ValueError(f"Unknown AppWorld dataset {dataset_name!r}")
    if num_epochs < 1:
        raise ValueError("num_epochs must be at least 1")

    task_ids = load_task_ids(dataset_name=dataset_name)
    if not task_ids:
        raise ValueError(f"AppWorld dataset {dataset_name!r} has no tasks")
    # Preflight all tasks before the first AppWorld output directory is created.
    for task_id in task_ids:
        Task.load(task_id=task_id, load_ground_truth=False)

    return tuple(
        TaskRef(task_id=task_id, dataset_index=index, epoch=epoch)
        for epoch in range(num_epochs)
        for index, task_id in enumerate(task_ids)
    )
