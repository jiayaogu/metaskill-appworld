from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from appworld.task import Task
from appworld_experiments.code.common.config import load_run_config


@pytest.fixture(autouse=True)
def stub_task_preflight(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, bool]]:
    calls: list[tuple[str, bool]] = []

    def load(*, task_id: str, load_ground_truth: bool = False) -> object:
        calls.append((task_id, load_ground_truth))
        return object()

    monkeypatch.setattr(Task, "load", load)
    return calls


def _config(tmp_path: Path, *, dataset_name: str = "a_new_registered_dataset") -> tuple[Path, dict]:
    root = tmp_path / "appworld"
    dataset_dir = root / "data" / "datasets"
    dataset_dir.mkdir(parents=True)
    (root / "data" / "tasks").mkdir()
    (dataset_dir / f"{dataset_name}.txt").write_text("abc123_1\nxyz999_2\n", encoding="utf-8")
    pricing = tmp_path / "pricing.json"
    pricing.write_text("{}", encoding="utf-8")
    config = {
        "schema_version": "appworld-baseline-run-v1",
        "baseline": "reasoningbank",
        "experiment_name": f"reasoningbank_{dataset_name}_online_adaptation_qwen3.8-flash",
        "task_source": {"dataset_name": dataset_name, "num_epochs": 1},
        "runtime": {"num_processes": 1},
        "appworld": {"root": str(root), "random_seed": 123},
        "evaluation": {"dataset_output_name": dataset_name, "enabled": True, "aggregate": True},
        "output": {"canonical_root": str(root / "experiments" / "outputs")},
        "logging": {"llm_calls": {"enabled": True, "fail_closed": True, "process_safe": True}},
        "pricing": {"registry_path": str(pricing)},
        "baseline_config": {
            "mode": "online_adaptation",
            "model": {"name": "qwen3.8-flash"},
        },
    }
    return tmp_path / "run.yaml", config


def _write(path: Path, config: dict) -> None:
    path.write_text(yaml.safe_dump(config), encoding="utf-8")


def test_any_registered_dataset_compiles_without_baseline_whitelist(
    tmp_path: Path, stub_task_preflight: list[tuple[str, bool]]
) -> None:
    path, config = _config(tmp_path)
    _write(path, config)
    spec = load_run_config(path)
    assert spec.dataset_name == "a_new_registered_dataset"
    assert spec.ordered_task_ids == ("abc123_1", "xyz999_2")
    assert spec.manifest()["experiment_name"] == config["experiment_name"]
    assert spec.evaluation["dataset_output_name"] == spec.dataset_name
    assert stub_task_preflight == [("abc123_1", False), ("xyz999_2", False)]


def test_rejects_dataset_name_mismatch_and_direct_ids(tmp_path: Path) -> None:
    path, config = _config(tmp_path)
    config["evaluation"]["dataset_output_name"] = config["experiment_name"]
    _write(path, config)
    with pytest.raises(ValueError, match="dataset_output_name"):
        load_run_config(path)

    config["evaluation"]["dataset_output_name"] = config["task_source"]["dataset_name"]
    config["task_source"]["task_ids"] = ["abc123_1"]
    _write(path, config)
    with pytest.raises(ValueError, match="Direct selector"):
        load_run_config(path)


def test_rejects_model_drift_and_unavailable_parallel_memory(tmp_path: Path) -> None:
    path, config = _config(tmp_path)
    config["baseline_config"]["model"]["name"] = "gpt-4.1"
    _write(path, config)
    with pytest.raises(ValueError, match="model must be qwen3.8-flash"):
        load_run_config(path)

    config["baseline_config"]["model"]["name"] = "qwen3.8-flash"
    config["runtime"]["num_processes"] = 2
    _write(path, config)
    with pytest.raises(ValueError, match="sequential task order"):
        load_run_config(path)


def test_rejects_nested_model_override_and_reme_arms(tmp_path: Path) -> None:
    path, config = _config(tmp_path)
    config["baseline_config"]["model"]["fallback_model"] = "other-model"
    _write(path, config)
    with pytest.raises(ValueError, match="Unknown baseline_config.model keys"):
        load_run_config(path)

    config["baseline"] = "reme"
    config["experiment_name"] = (
        f"reme_{config['task_source']['dataset_name']}_online_adaptation_qwen3.8-flash"
    )
    config["baseline_config"] = {
        "mode": "online_adaptation",
        "models": {
            "executor": "qwen3.8-flash",
            "summarizer": "qwen3.8-flash",
            "embedding": "text-embedding-v4",
        },
        "arms": ["reme"],
    }
    _write(path, config)
    with pytest.raises(ValueError, match="Direct selector"):
        load_run_config(path)


def test_reme_config_uses_registered_dataset_without_arms(
    tmp_path: Path, stub_task_preflight: list[tuple[str, bool]]
) -> None:
    path, config = _config(tmp_path, dataset_name="another_registered_dataset")
    config["baseline"] = "reme"
    config["experiment_name"] = (
        "reme_another_registered_dataset_online_adaptation_qwen3.8-flash"
    )
    config["baseline_config"] = {
        "mode": "online_adaptation",
        "source_pins": {"reme_root": "/example/ReMe", "reme_python": "/example/python"},
        "models": {
            "executor": "qwen3.8-flash",
            "summarizer": "qwen3.8-flash",
            "embedding": "text-embedding-v4",
            "embedding_dimensions": 1024,
        },
        "memory": {"top_k": 5, "family_local": True},
        "execution": {"outer_max_steps": 30},
    }
    _write(path, config)

    spec = load_run_config(path)

    assert spec.dataset_name == "another_registered_dataset"
    assert spec.ordered_task_ids == ("abc123_1", "xyz999_2")
    assert spec.evaluation["dataset_output_name"] == spec.dataset_name
    assert stub_task_preflight == [("abc123_1", False), ("xyz999_2", False)]

    config["baseline_config"]["models"]["executor"] = "gpt-4.1"
    _write(path, config)
    with pytest.raises(ValueError, match="ReMe chat models must be qwen3.8-flash"):
        load_run_config(path)

    config["baseline_config"]["models"]["executor"] = "qwen3.8-flash"
    config["baseline_config"]["models"]["embedding_dimensions"] = 512
    _write(path, config)
    with pytest.raises(ValueError, match="embedding_dimensions must match"):
        load_run_config(path)
