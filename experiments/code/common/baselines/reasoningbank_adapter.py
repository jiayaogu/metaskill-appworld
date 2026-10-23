"""ReasoningBank bridge that calls its existing run_task order unchanged."""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path
from typing import Any

from appworld_experiments.code.common.contracts import (
    BaselineServices,
    BaselineTaskResult,
    TaskContext,
)


def _load_reasoningbank_module(source: Path) -> Any:
    module_name = "unified_reasoningbank_appworld"
    if module_name in sys.modules:
        return sys.modules[module_name]
    spec = importlib.util.spec_from_file_location(module_name, source)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot import ReasoningBank AppWorld module: {source}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    sys.path.insert(0, str(source.parent))
    try:
        spec.loader.exec_module(module)
    except BaseException:
        del sys.modules[module_name]
        raise
    finally:
        sys.path.remove(str(source.parent))
    return module


def _artifact_file(root: Path, name: str) -> Path:
    if not isinstance(name, str) or Path(name).name != name or name in ("", ".", ".."):
        raise ValueError("ReasoningBank artifact filenames must be simple names")
    return root / name


class ReasoningBankAdapter:
    name = "reasoningbank"

    def __init__(
        self,
        baseline_config: dict[str, Any],
        *,
        source: Path,
        price_file: Path,
        random_seed: int = 123,
    ) -> None:
        if baseline_config.get("mode") != "online_adaptation":
            raise NotImplementedError("Current ReasoningBank core supports online adaptation only")
        if baseline_config.get("model", {}).get("name") != "qwen3.8-flash":
            raise ValueError("ReasoningBank unified model must be qwen3.8-flash")
        if baseline_config.get("retrieval_fallback", "local_lexical") != "local_lexical":
            raise ValueError("ReasoningBank core currently uses local lexical retrieval fallback")
        self.config = baseline_config
        self.source = source
        self.price_file = price_file
        self.random_seed = random_seed
        self.module = _load_reasoningbank_module(source)
        self.runner = None
        self.client = None
        self.cost_tracker = None
        self.memory_bank = None

    def _prepare(self, context: TaskContext) -> None:
        artifact_root = context.artifacts_dir.parent
        config = self.config
        args = argparse.Namespace(
            output_dir=str(artifact_root),
            random_seed=self.random_seed,
            max_memory_items=int(config.get("max_memory_items", 6)),
            embedding_cache=config.get("embedding_cache"),
            max_steps=int(config.get("max_steps", 40)),
            max_observation_chars=int(config.get("max_observation_chars", 20000)),
            memory_temperature=float(config.get("memory_temperature", 0.3)),
        )
        self.runner = self.module.ReasoningBankAppWorldRunner(args)
        memory_files = config.get("memory", {})
        cost_files = config.get("cost", {})
        self.client = self.module.OpenAIChatClient(
            model="qwen3.8-flash",
            temperature=float(config.get("temperature", 0.0)),
            max_tokens=int(config.get("max_tokens", 8192)),
            timeout=float(config.get("request_timeout_seconds", 120)),
            retries=int(config.get("provider_retries", 4)),
        )
        self.cost_tracker = self.module.OpenAICostTracker(
            _artifact_file(artifact_root, cost_files.get("ledger_file", "cost_ledger.jsonl")),
            self.price_file,
        )
        self.memory_bank = self.module.MemoryBank(
            _artifact_file(artifact_root, memory_files.get("state_file", "memory_state.json")),
            _artifact_file(artifact_root, memory_files.get("events_file", "memory_events.jsonl")),
        )

    def run_task(self, context: TaskContext, services: BaselineServices) -> BaselineTaskResult:
        if self.runner is None:
            self._prepare(context)
        self.client.call_logger = services.llm

        def open_world(*, task_id: str, experiment_name: str, random_seed: int):
            if task_id != context.task_id or experiment_name != context.experiment_name:
                raise ValueError("ReasoningBank task/experiment differs from the shared context")
            if random_seed != self.random_seed:
                raise ValueError("ReasoningBank random seed differs from shared AppWorld config")
            return services.episodes.open(kind="primary")

        result = self.runner.run_task(
            AppWorld=open_world,
            client=self.client,
            cost_tracker=self.cost_tracker,
            memory_bank=self.memory_bank,
            experiment_name=context.experiment_name,
            model="qwen3.8-flash",
            task_id=context.task_id,
            epoch=context.epoch + 1,
            run_dir=context.artifacts_dir.parent,
            runtime_dir=context.primary_task_dir.parents[1],
        )
        return BaselineTaskResult(metadata=result)
