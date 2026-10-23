"""Coarse ACE bridge; no shared action/observation/memory state machine."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import appworld_experiments.code.ace  # noqa: F401; register ACE agent types
from appworld_experiments.code.ace.adaptation_agent import StarAgent
from appworld_experiments.code.ace.base_agent import BaseAgent
from appworld_experiments.code.ace.evaluation_agent import Agent
from appworld_experiments.code.common.contracts import (
    BaselineServices,
    BaselineTaskResult,
    TaskContext,
)


class ACEAdapter:
    name = "ace"

    def __init__(
        self, baseline_config: dict[str, Any], *, appworld_kwargs: dict[str, Any] | None = None
    ) -> None:
        config = deepcopy(baseline_config)
        self.mode = config.pop("mode")
        self.run_type = config.pop("run_type")
        self.batch_size = int(config.pop("batch_size", 1))
        batch_options = {
            "curator_batch_size": config.pop("curator_batch_size", None),
            "curator_parallel": config.pop("curator_parallel", True),
            "curator_max_workers": config.pop("curator_max_workers", None),
            "use_bulletpoint_analyzer": config.pop("use_bulletpoint_analyzer", False),
            "bulletpoint_analyzer_threshold": config.pop("bulletpoint_analyzer_threshold", 0.90),
            "augmented_shuffling": config.pop("augmented_shuffling", True),
            "augmented_shuffling_factor": config.pop("augmented_shuffling_factor", None),
        }
        self.agent_config = config.pop("agent")
        if config:
            raise ValueError(f"Unknown ACE adapter config keys: {sorted(config)}")
        if self.batch_size != 1:
            raise NotImplementedError(
                "ACE parallel/batched adaptation needs its own coarse batch adapter; "
                "this task adapter does not reorder or flatten batches"
            )
        if (
            batch_options["curator_batch_size"] is not None
            or batch_options["curator_max_workers"] is not None
            or batch_options["curator_parallel"] is not True
            or batch_options["use_bulletpoint_analyzer"]
            or batch_options["bulletpoint_analyzer_threshold"] != 0.90
            or batch_options["augmented_shuffling"] is not True
            or batch_options["augmented_shuffling_factor"] is not None
        ):
            raise ValueError("Batch-only ACE options require the separate batch adapter")
        if appworld_kwargs:
            agent_world = self.agent_config.setdefault("appworld_config", {})
            for key, value in appworld_kwargs.items():
                if key in agent_world and agent_world[key] != value:
                    raise ValueError(f"ACE appworld_config.{key} differs from shared AppWorld config")
                agent_world[key] = value
        if self.run_type == "ace-adaptation":
            if self.mode not in ("online_adaptation", "offline_adaptation"):
                raise ValueError("ACE adaptation run_type requires an adaptation mode")
            self.agent = StarAgent.from_dict(self.agent_config)
        elif self.run_type == "ace-evaluation":
            if self.mode != "evaluation":
                raise ValueError("ACE evaluation run_type requires evaluation mode")
            self.agent = Agent.from_dict(self.agent_config)
        elif self.run_type == "non-ace-evaluation":
            if self.mode != "evaluation":
                raise ValueError("non-ACE evaluation run_type requires evaluation mode")
            self.agent = BaseAgent.from_dict(self.agent_config)
        else:
            raise ValueError(f"Unsupported ACE run_type: {self.run_type}")
        self._started = False

    def run_task(self, context: TaskContext, services: BaselineServices) -> BaselineTaskResult:
        if not self._started:
            self.agent.logger.initialize(
                experiment_name=context.experiment_name,
                num_tasks=context.total_tasks,
                num_processes=1,
                process_index=0,
            )
            self._started = True
        self.agent.shared_services = services
        if hasattr(self.agent, "current_task_index"):
            self.agent.current_task_index = context.epoch * context.dataset_size + context.dataset_index
        if isinstance(self.agent, StarAgent):
            role_models = (
                (self.agent.generator_model, "generator"),
                (self.agent.reflector_model, "reflector"),
                (self.agent.curator_model, "curator"),
            )
        else:
            role_models = ((self.agent.language_model, "generator"),)
        for model, phase in role_models:
            model.set_call_logger(services.llm, phase=phase)
        try:
            self.agent.solve_task(context.task_id, context.experiment_name)
        finally:
            self.agent.shared_services = None
        return BaselineTaskResult()
