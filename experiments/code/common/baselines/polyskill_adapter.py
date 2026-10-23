"""PolySkill bridge to its extracted, unchanged per-task core sequence."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any

from appworld.common.path_store import path_store

from appworld_experiments.code.common.contracts import (
    BaselineServices,
    BaselineTaskResult,
    TaskContext,
)
from appworld_experiments.code.common.evaluator import TaskEvaluator


def _load_polyskill(source_root: Path) -> Any:
    sys.path.insert(0, str(source_root))
    try:
        return importlib.import_module("polyskill.appworld.runner")
    finally:
        sys.path.remove(str(source_root))


class PolySkillAdapter:
    name = "polyskill"

    def __init__(
        self,
        baseline_config: dict[str, Any],
        *,
        source_root: Path,
        pricing_registry_path: Path,
    ) -> None:
        if baseline_config.get("mode") != "online_adaptation":
            raise NotImplementedError("Current PolySkill core supports online adaptation only")
        if baseline_config.get("model", {}).get("name") != "qwen3.8-flash":
            raise ValueError("PolySkill unified model must be qwen3.8-flash")
        for block in ("induction", "replay_validation", "storage_update"):
            if baseline_config.get(block, {}).get("enabled", True) is not True:
                raise ValueError(f"PolySkill core requires {block}.enabled=true")
        self.config = baseline_config
        self.source = _load_polyskill(source_root)
        self.pricing_registry_path = pricing_registry_path
        self.registry = None
        self.llm = None
        self.agent = None
        self.skill_store = None

    def _prepare(self, context: TaskContext) -> None:
        source = self.source
        self.registry = source.PricingRegistry(self.pricing_registry_path)
        model_config = self.config.get("model", {})
        self.llm = source.OpenAICompatibleLLM(
            model="qwen3.8-flash",
            base_url=self.registry.base_url,
            temperature=float(model_config.get("temperature", 0.0)),
            max_tokens=int(model_config.get("max_tokens", 2048)),
        )
        self.agent = source.AppWorldPolySkillAgent(
            llm=self.llm,
            max_steps=int(self.config.get("max_steps", 12)),
        )
        skill_directory = self.config.get("skill_store", {}).get("directory", "skills")
        if not isinstance(skill_directory, str) or Path(skill_directory).name != skill_directory:
            raise ValueError("PolySkill skill_store.directory must be a simple directory name")
        self.skill_store = source.AppWorldSkillStore(context.artifacts_dir.parent / skill_directory)

    def run_task(self, context: TaskContext, services: BaselineServices) -> BaselineTaskResult:
        if self.agent is None:
            self._prepare(context)
        self.llm.call_logger = services.llm
        self.agent.episode_service = services.episodes
        appworld_root = Path(path_store.root)
        replay_experiment = f"{context.experiment_name}__replay_validation"

        def official_tracker(evaluator: TaskEvaluator):
            # Match PolySkill's existing evaluate_task_to_dict cache boundary.
            from appworld.apps.model_lib import CachedDBHandler

            CachedDBHandler.reset()
            try:
                result = evaluator.evaluate_task()
                return result.tracker.to_dict(stats_only=False), result.report
            finally:
                CachedDBHandler.reset()

        def evaluate_primary(task_id: str, experiment_name: str):
            if task_id != context.task_id or experiment_name != context.experiment_name:
                raise ValueError("PolySkill primary evaluation target differs from shared context")
            return official_tracker(services.evaluator)

        def evaluate_replay(task_id: str, experiment_name: str):
            if task_id != context.task_id or experiment_name != replay_experiment:
                raise ValueError("PolySkill replay evaluation target differs from shared context")
            evaluator = TaskEvaluator(
                task_id=task_id,
                experiment_name=experiment_name,
                primary_task_dir=appworld_root / "experiments/outputs" / experiment_name / "tasks" / task_id,
            )
            return official_tracker(evaluator)

        try:
            outcome = self.source.run_task_core(
                task_id=context.task_id,
                model="qwen3.8-flash",
                experiment_name=context.experiment_name,
                appworld_root=appworld_root,
                agent=self.agent,
                llm=self.llm,
                skill_store=self.skill_store,
                registry=self.registry,
                ledger_path=context.artifacts_dir / "cost_ledger.jsonl",
                artifact_dir=context.artifacts_dir,
                primary_evaluator=evaluate_primary,
                replay_evaluator=evaluate_replay,
                replay_experiment=replay_experiment,
            )
        finally:
            self.agent.episode_service = None
        return BaselineTaskResult(metadata=outcome)
