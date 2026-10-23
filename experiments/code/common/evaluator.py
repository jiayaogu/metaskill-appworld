"""Official AppWorld evaluation entry points; no synthetic scores."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from appworld.evaluator import evaluate_dataset as appworld_evaluate_dataset
from appworld.evaluator import evaluate_task as appworld_evaluate_task


@dataclass(frozen=True)
class OfficialTaskResult:
    tracker: Any
    report: str | None


class TaskEvaluator:
    def __init__(
        self,
        *,
        task_id: str,
        experiment_name: str,
        primary_task_dir: Path,
        evaluate_task_fn: Callable[..., tuple[Any, str | None]] = appworld_evaluate_task,
    ) -> None:
        self.task_id = task_id
        self.experiment_name = experiment_name
        self.primary_task_dir = primary_task_dir
        self.evaluate_task_fn = evaluate_task_fn

    def evaluate_task(self, *, suppress_errors: bool = True) -> OfficialTaskResult:
        tracker, report = self.evaluate_task_fn(
            task_id=self.task_id,
            experiment_name=self.experiment_name,
            suppress_errors=suppress_errors,
            save_report=True,
        )
        return OfficialTaskResult(tracker=tracker, report=report)

    def ensure_final_primary_report_if_needed(self, *, suppress_errors: bool = True) -> Any:
        report_path = self.primary_task_dir / "evaluation" / "report.md"
        if report_path.is_file():
            report_mtime = report_path.stat().st_mtime_ns
            db_dir = self.primary_task_dir / "dbs"
            if db_dir.is_dir() and all(
                file.stat().st_mtime_ns <= report_mtime for file in db_dir.rglob("*") if file.is_file()
            ):
                return None
        return self.evaluate_task(suppress_errors=suppress_errors)


def evaluate_dataset(
    *,
    experiment_name: str,
    dataset_name: str,
    suppress_errors: bool = True,
    evaluate_dataset_fn: Callable[..., Any] = appworld_evaluate_dataset,
) -> Any:
    return evaluate_dataset_fn(
        experiment_name=experiment_name,
        dataset_name=dataset_name,
        suppress_errors=suppress_errors,
        save_reports=True,
    )
