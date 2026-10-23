"""AppWorld lifecycle and narrow execution/completion capabilities.

Only this module constructs AppWorld for the unified runner. Baselines decide
when to open an episode and in what order to call the capabilities.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator

from appworld import AppWorld


class EpisodeService:
    def __init__(
        self,
        *,
        task_id: str,
        experiment_name: str,
        primary_task_dir: Path,
        appworld_kwargs: dict[str, Any] | None = None,
        world_factory: Callable[..., Any] = AppWorld,
    ) -> None:
        self.task_id = task_id
        self.experiment_name = experiment_name
        self.primary_task_dir = primary_task_dir
        self.appworld_kwargs = dict(appworld_kwargs or {})
        self.world_factory = world_factory
        self._world: Any | None = None

    @property
    def task(self) -> Any:
        return self._require_world().task

    @property
    def output_logs_directory(self) -> str:
        return self._require_world().output_logs_directory

    @property
    def output_misc_directory(self) -> str:
        return self._require_world().output_misc_directory

    @property
    def output_directory(self) -> str:
        return self._require_world().output_directory

    @property
    def environment_io(self) -> Any:
        return self._require_world().environment_io

    @property
    def is_open(self) -> bool:
        return self._world is not None

    def execute(self, code: str) -> str:
        return self._require_world().execute(code)

    def task_completed(self) -> bool:
        return bool(self._require_world().task_completed())

    def evaluate(self, suppress_errors: bool = True) -> Any:
        return self._require_world().evaluate(suppress_errors=suppress_errors)

    def save_logs(self) -> None:
        self._require_world().save_logs()

    def complete_task(self, answer: Any = None, status: str = "success") -> None:
        self._require_world().apis.supervisor.complete_task(answer=answer, status=status)

    def _require_world(self) -> Any:
        if self._world is None:
            raise RuntimeError("Open an AppWorld episode before using its ports")
        return self._world

    @contextmanager
    def open(
        self,
        *,
        kind: str = "primary",
        episode_id: str | None = None,
        experiment_name: str | None = None,
    ) -> Iterator[EpisodeService]:
        if self._world is not None:
            raise RuntimeError("An AppWorld episode is already active for this task")
        if kind == "primary":
            if experiment_name not in (None, self.experiment_name):
                raise ValueError("Primary episodes must use the canonical experiment name")
            selected_experiment = self.experiment_name
        else:
            if not episode_id:
                raise ValueError("Auxiliary episodes require an episode_id")
            selected_experiment = experiment_name or f"{self.experiment_name}__{kind}__{episode_id}"
            if selected_experiment == self.experiment_name:
                raise ValueError("Auxiliary AppWorld output must not overwrite the primary task")

        # AppWorld.initialize() removes its task output directory. ACE GT retries
        # reopen the primary episode, so retain the one canonical LLM file across
        # those resets without changing retry order or creating another LLM log.
        log_path = self.primary_task_dir / "logs" / "lm_calls.jsonl"
        previous_log = log_path.read_bytes() if kind == "primary" and log_path.is_file() else None
        try:
            world = self.world_factory(
                task_id=self.task_id,
                experiment_name=selected_experiment,
                **self.appworld_kwargs,
            )
        except BaseException:
            if previous_log is not None:
                log_path.parent.mkdir(parents=True, exist_ok=True)
                log_path.write_bytes(previous_log)
            raise
        if previous_log is not None:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_bytes(previous_log)

        self._world = world
        try:
            yield self
        finally:
            try:
                world.close()
            finally:
                self._world = None
