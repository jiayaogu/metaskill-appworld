"""Coarse ports exposed to baseline-owned task loops."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class TaskContext:
    task_id: str
    dataset_name: str
    dataset_index: int
    dataset_size: int
    total_tasks: int
    epoch: int
    experiment_name: str
    primary_task_dir: Path
    artifacts_dir: Path
    task: Any  # Task.load(..., load_ground_truth=False); no GT in the context


@dataclass
class BaselineTaskResult:
    """Optional adapter result; the baseline retains its own durable state."""

    metadata: dict[str, Any] = field(default_factory=dict)


class ExecutionPort(Protocol):
    def execute(self, code: str) -> str: ...


class CompletionPort(Protocol):
    def task_completed(self) -> bool: ...

    def complete_task(self, answer: Any = None, status: str = "success") -> None: ...


class EvaluationPort(Protocol):
    def evaluate_task(self, *, suppress_errors: bool = True) -> Any: ...

    def ensure_final_primary_report_if_needed(self) -> Any: ...


class LLMLoggerPort(Protocol):
    @property
    def path(self) -> Path: ...


@dataclass
class BaselineServices:
    episodes: Any  # EpisodeService; avoid a runtime import cycle
    environment: ExecutionPort
    completion: CompletionPort
    evaluator: EvaluationPort
    llm: LLMLoggerPort
    artifacts: Path


class BaselineAdapter(Protocol):
    name: str

    def run_task(self, context: TaskContext, services: BaselineServices) -> BaselineTaskResult: ...
