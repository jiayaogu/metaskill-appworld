"""Coarse ReMe bridge to its existing AppWorld task core.

Task selection, AppWorld lifecycle, official evaluation, and the canonical LLM
sink remain shared. The ReMe core owns memory-pre, executor turns, and
memory-post ordering.
"""

from __future__ import annotations

import importlib
import os
from pathlib import Path
import sys
from typing import Any

from appworld_experiments.code.common.config import RunSpec
from appworld_experiments.code.common.contracts import (
    BaselineServices,
    BaselineTaskResult,
    TaskContext,
)
from appworld_experiments.code.common.lm_logger import subprocess_logger_environment


_PILOT_MEMORY_DEFAULTS = {
    "top_k": 5,
    "max_experiences_per_task": 3,
    "dedup_threshold": 0.95,
    "delete_alpha": 5,
    "delete_beta": 0.5,
    "success_only_update": True,
    "family_local": True,
}


def _path(value: Any, base: Path, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} is required")
    expanded = os.path.expandvars(value)
    if "${" in expanded:
        raise ValueError(f"{label} contains an unset environment variable")
    path = Path(expanded).expanduser()
    return (path if path.is_absolute() else base / path).resolve()


class ReMeAdapter:
    name = "reme"

    def __init__(self, spec: RunSpec) -> None:
        config = spec.baseline_config
        if config.get("mode") not in {"online_adaptation", "offline_adaptation"}:
            raise ValueError("ReMe unified core supports online/offline adaptation only")
        legacy_keys = {
            "protocol_version", "qualification", "scored_attempts_per_task",
            "script_layout", "prompts", "artifacts",
        } & set(config)
        if legacy_keys:
            raise ValueError(f"Legacy pilot-only ReMe config keys are not unified inputs: {sorted(legacy_keys)}")
        memory = config.get("memory", {})
        if not isinstance(memory, dict) or any(
            memory.get(key, default) != default for key, default in _PILOT_MEMORY_DEFAULTS.items()
        ):
            raise ValueError("ReMe memory settings must match the existing AppWorld baseline core")
        source_pins = config.get("source_pins", {})
        if not isinstance(source_pins, dict):
            raise ValueError("ReMe source_pins must be a mapping")
        reme_root = _path(
            source_pins.get("reme_root"), spec.source_config_path.parent,
            "baseline_config.source_pins.reme_root",
        )
        reme_python = _path(
            source_pins.get("reme_python"), spec.source_config_path.parent,
            "baseline_config.source_pins.reme_python",
        )
        if not (reme_root / "scripts" / "appworld_unified_core.py").is_file():
            raise FileNotFoundError(f"ReMe AppWorld task core is absent: {reme_root}")
        if not reme_python.is_file():
            raise FileNotFoundError(f"ReMe Python executable is absent: {reme_python}")
        execution = config.get("execution", {})
        if not isinstance(execution, dict):
            raise ValueError("ReMe execution must be a mapping")
        command = execution.get("executor_command")
        if command is None:
            command = [str(reme_python), "-m", "metaskill_org.benchmarking.appworld_openai_wrapper"]
        if not isinstance(command, list) or not command or any(not isinstance(item, str) or not item for item in command):
            raise ValueError("ReMe executor_command must be a nonempty string list")
        if str(reme_root) not in sys.path:
            sys.path.insert(0, str(reme_root))
        module = importlib.import_module("metaskill_org.benchmarking.appworld_unified_core")
        self.core = module.ReMeAppWorldTaskCore(
            appworld_root=spec.appworld_root,
            reme_root=reme_root,
            reme_python=reme_python,
            executor_command=command,
            models=config["models"],
            pricing_registry_path=spec.pricing_registry_path,
            appworld_config=spec.appworld_kwargs,
            max_steps=int(execution.get("outer_max_steps", 30)),
            executor_timeout_seconds=int(execution.get("executor_timeout_seconds", 240)),
            forward_executor_environment=execution.get("forward_executor_env", []),
            forward_memory_environment=execution.get("forward_memory_env", []),
            require_usage_sidecar=execution.get("require_usage_sidecar", True),
        )

    def run_task(self, context: TaskContext, services: BaselineServices) -> BaselineTaskResult:
        result = self.core.run_task(
            context,
            services,
            logger_environment=subprocess_logger_environment(services.llm),
        )
        return BaselineTaskResult(metadata={
            "task_goal_completion": result.get("task_goal_completion"),
            "requirement_pass_rate": result.get("requirement_pass_rate"),
        })
