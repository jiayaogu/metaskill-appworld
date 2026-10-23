"""Boundary tests for the shared AppWorld shell; no baseline core is invoked."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from appworld_experiments.code.common import task_loader
from appworld_experiments.code.common.episodes import EpisodeService
from appworld_experiments.code.common.output_contract import validate_dataset_output


def test_loader_accepts_any_registered_dataset_and_preserves_order(monkeypatch: pytest.MonkeyPatch) -> None:
    loaded: list[tuple[str, bool]] = []
    monkeypatch.setattr(task_loader, "valid_dataset_names", lambda: ["arbitrary_new_dataset"])
    monkeypatch.setattr(
        task_loader,
        "load_task_ids",
        lambda *, dataset_name: ["second_1", "first_1"],
    )
    monkeypatch.setattr(
        task_loader.Task,
        "load",
        lambda *, task_id, load_ground_truth: loaded.append((task_id, load_ground_truth)),
    )

    refs = task_loader.load_task_stream("arbitrary_new_dataset", num_epochs=2)

    assert [(ref.task_id, ref.dataset_index, ref.epoch) for ref in refs] == [
        ("second_1", 0, 0),
        ("first_1", 1, 0),
        ("second_1", 0, 1),
        ("first_1", 1, 1),
    ]
    assert loaded == [("second_1", False), ("first_1", False)]


def test_loader_rejects_only_unregistered_dataset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(task_loader, "valid_dataset_names", lambda: ["train", "new_dataset"])
    with pytest.raises(ValueError, match="Unknown AppWorld dataset"):
        task_loader.load_task_stream("missing_dataset")


def test_episode_ports_and_primary_retry_keep_one_canonical_log(tmp_path: Path) -> None:
    task_dir = tmp_path / "experiment" / "tasks" / "task_1"
    calls: list[tuple[object, ...]] = []

    class FakeWorld:
        def __init__(self, *, task_id: str, experiment_name: str) -> None:
            calls.append(("open", task_id, experiment_name))
            # Mirrors AppWorld._prepare_directories() for this task.
            if task_dir.exists():
                import shutil

                shutil.rmtree(task_dir)
            (task_dir / "logs").mkdir(parents=True)
            self.task = SimpleNamespace(id=task_id)
            self.output_logs_directory = str(task_dir / "logs")
            self.environment_io = [{"input": "test", "output": "observation"}]
            self.apis = SimpleNamespace(
                supervisor=SimpleNamespace(
                    complete_task=lambda **kwargs: calls.append(("complete", kwargs))
                )
            )

        def execute(self, code: str) -> str:
            calls.append(("execute", code))
            return "observation"

        def task_completed(self) -> bool:
            calls.append(("task_completed",))
            return True

        def save_logs(self) -> None:
            calls.append(("save_logs",))

        def evaluate(self, *, suppress_errors: bool = True) -> object:
            calls.append(("evaluate", suppress_errors))
            return "official evaluation"

        def close(self) -> None:
            calls.append(("close",))

    episodes = EpisodeService(
        task_id="task_1",
        experiment_name="experiment",
        primary_task_dir=task_dir,
        world_factory=FakeWorld,
    )
    # ReMe memory-pre can call the model before the first AppWorld open.
    log_path = task_dir / "logs" / "lm_calls.jsonl"
    log_path.parent.mkdir(parents=True)
    log_path.write_text('{"id":"memory-pre"}\n', encoding="utf-8")
    with episodes.open() as ports:
        assert log_path.read_text(encoding="utf-8") == '{"id":"memory-pre"}\n'
        assert ports.task.id == "task_1"
        assert ports.execute("print(1)") == "observation"
        assert ports.task_completed()
        assert ports.environment_io == [{"input": "test", "output": "observation"}]
        ports.save_logs()
        assert ports.evaluate(suppress_errors=True) == "official evaluation"
        ports.complete_task(answer="yes")

    log_path.write_text('{"id":"memory-pre"}\n{"id":"first"}\n', encoding="utf-8")
    with episodes.open() as ports:
        assert log_path.read_text(encoding="utf-8") == '{"id":"memory-pre"}\n{"id":"first"}\n'
        assert ports.execute("print(2)") == "observation"

    assert log_path.read_text(encoding="utf-8") == '{"id":"memory-pre"}\n{"id":"first"}\n'
    assert calls == [
        ("open", "task_1", "experiment"),
        ("execute", "print(1)"),
        ("task_completed",),
        ("save_logs",),
        ("evaluate", True),
        ("complete", {"answer": "yes", "status": "success"}),
        ("close",),
        ("open", "task_1", "experiment"),
        ("execute", "print(2)"),
        ("close",),
    ]


def test_aggregate_validator_uses_dataset_name(tmp_path: Path) -> None:
    directory = tmp_path / "run" / "evaluations"
    directory.mkdir(parents=True)
    (directory / "dev.json").write_text("{}", encoding="utf-8")
    (directory / "dev.txt").write_text("report", encoding="utf-8")
    validate_dataset_output(tmp_path, "run", "dev")
    with pytest.raises(FileNotFoundError, match="another_dataset.json"):
        validate_dataset_output(tmp_path, "run", "another_dataset")
