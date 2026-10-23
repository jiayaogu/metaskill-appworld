"""Strict shared run-config compiler; baseline algorithm fields stay opaque."""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

from appworld_experiments.code.common.task_loader import load_task_stream


SCHEMA_VERSION = "appworld-baseline-run-v1"
CHAT_MODEL = "qwen3.8-flash"
EMBEDDING_MODEL = "text-embedding-v4"
MODES = {"offline_adaptation", "online_adaptation", "evaluation"}
BASELINES = {"ace", "reasoningbank", "polyskill", "reme"}
_SELECTORS = {"task_ids", "family_ids", "families", "variants", "arms", "split", "model_matrix"}
_TOP_KEYS = {
    "schema_version", "baseline", "experiment_name", "task_source", "runtime", "appworld",
    "evaluation", "output", "logging", "provider_environment", "pricing", "safety_limits",
    "baseline_config",
}
_SHARED_KEYS = {
    "task_source": {"dataset_name", "num_epochs"},
    "runtime": {"num_processes", "process_index", "resume", "dry_run"},
    "appworld": {
        "root", "random_seed", "max_interactions", "timeout_seconds",
        "raise_on_unsafe_syntax", "raise_on_failure",
    },
    "evaluation": {
        "enabled", "suppress_errors", "save_task_reports", "aggregate", "dataset_output_name",
    },
    "output": {"canonical_root", "baseline_artifacts_subdir"},
    "logging": {"llm_calls"},
    "provider_environment": {"env_file", "api_key_env", "base_url_env"},
    "pricing": {"registry_path", "require_known_price"},
    "safety_limits": {
        "max_environment_executions", "max_wall_time_seconds_per_task",
        "max_cost_usd_per_task", "max_cost_usd_overall",
    },
}
_BASELINE_KEYS = {
    "ace": {
        "mode", "run_type", "batch_size", "curator_batch_size", "curator_parallel",
        "curator_max_workers", "use_bulletpoint_analyzer", "bulletpoint_analyzer_threshold",
        "augmented_shuffling", "augmented_shuffling_factor", "agent",
    },
    "reasoningbank": {
        "mode", "model", "max_steps", "max_tokens", "temperature", "memory_temperature",
        "max_memory_items", "max_observation_chars", "request_timeout_seconds",
        "provider_retries", "embedding_cache", "retrieval_fallback", "memory", "cost",
    },
    "polyskill": {
        "mode", "model", "max_steps", "skill_store", "induction", "replay_validation",
        "storage_update", "diagnostics",
    },
    "reme": {
        "mode", "source_pins", "models", "memory", "execution",
    },
}
_NESTED_BASELINE_KEYS = {
    "reasoningbank": {
        "model": {"name"},
        "memory": {
            "state_file", "events_file", "trained_bank_file",
            "preserve_active_items_across_tasks",
        },
        "cost": {"ledger_file", "summary_file"},
    },
    "polyskill": {
        "model": {"name", "base_url_source", "api_key_env", "temperature", "max_tokens"},
        "skill_store": {"directory", "format", "prompt_recent_skill_limit"},
        "induction": {
            "enabled", "only_after_official_success", "require_nonempty_executed_code",
        },
        "replay_validation": {
            "enabled", "task_policy", "auxiliary_experiment_suffix",
            "count_in_primary_metrics", "store_only_after_success",
        },
        "storage_update": {"enabled", "normalize_with_same_model", "validated_by"},
        "diagnostics": {
            "write_trajectory", "write_memory_events", "write_failure_analysis",
        },
    },
    "reme": {
        "source_pins": {"reme_root", "reme_python"},
        "models": {"executor", "summarizer", "embedding", "embedding_dimensions"},
        "memory": {
            "top_k", "max_experiences_per_task", "dedup_threshold", "delete_alpha",
            "delete_beta", "success_only_update", "family_local",
        },
        "execution": {
            "outer_max_steps", "executor_timeout_seconds", "executor_command",
            "forward_executor_env", "forward_memory_env", "require_usage_sidecar",
        },
    },
}
_ACE_AGENT_KEYS = {
    "type", "generator_model_config", "reflector_model_config", "curator_model_config",
    "generator_prompt_file_path", "reflector_prompt_file_path", "curator_prompt_file_path",
    "initial_playbook_file_path", "trained_playbook_file_path", "ignore_multiple_calls",
    "max_prompt_length", "max_output_length", "max_steps", "max_cost_overall",
    "max_cost_per_task", "use_reflector", "use_gt_code", "num_retries_with_gt",
    "logger_config", "appworld_config", "log_lm_calls",
}
_ACE_MODEL_KEYS = {
    "name", "provider", "completion_method", "base_url", "temperature", "seed", "stop",
    "logprobs", "top_logprobs", "frequency_penalty", "presence_penalty", "n",
    "response_format", "retry_after_n_seconds", "use_cache", "max_retries",
    "token_cost_data", "max_tokens", "max_completion_tokens", "top_p", "api_key",
}


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"{label} must be a mapping with string keys")
    return value


def _only_keys(value: Mapping[str, Any], allowed: set[str], label: str) -> None:
    unknown = set(value) - allowed
    if unknown:
        raise ValueError(f"Unknown {label} keys: {sorted(unknown)}")


def _reject_task_selectors(value: Any, path: str = "config") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in _SELECTORS:
                raise ValueError(f"Direct selector {path}.{key} is forbidden; use task_source.dataset_name")
            _reject_task_selectors(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_task_selectors(item, f"{path}[{index}]")


def _validate_baseline_shape(baseline: str, config: dict[str, Any]) -> None:
    for name, allowed in _NESTED_BASELINE_KEYS.get(baseline, {}).items():
        if name in config:
            _only_keys(_mapping(config[name], f"baseline_config.{name}"), allowed,
                       f"baseline_config.{name}")
    if baseline == "ace":
        agent = _mapping(config.get("agent"), "baseline_config.agent")
        _only_keys(agent, _ACE_AGENT_KEYS, "baseline_config.agent")
        for role in ("generator", "reflector", "curator"):
            key = f"{role}_model_config"
            if key in agent:
                _only_keys(_mapping(agent[key], f"baseline_config.agent.{key}"),
                           _ACE_MODEL_KEYS, f"baseline_config.agent.{key}")
        if "appworld_config" in agent or "log_lm_calls" in agent:
            raise ValueError("ACE AppWorld settings and LLM logging belong to the shared config")


def _resolve_path(raw: Any, base: Path, label: str) -> Path:
    if not isinstance(raw, str) or not raw:
        raise ValueError(f"{label} must be a non-empty path")
    expanded = os.path.expandvars(raw)
    if re.search(r"\$\{[^}]+\}", expanded):
        raise ValueError(f"{label} contains an unset environment variable")
    path = Path(expanded).expanduser()
    return (path if path.is_absolute() else base / path).resolve()


@dataclass(frozen=True)
class RunSpec:
    baseline: str
    mode: str
    dataset_name: str
    experiment_name: str
    num_epochs: int
    appworld_root: Path
    appworld_kwargs: dict[str, Any]
    output_root: Path
    pricing_registry_path: Path
    provider_env_file: Path | None
    api_key_env: str
    base_url_env: str
    source_config_path: Path
    baseline_config: dict[str, Any]
    runtime: dict[str, Any]
    evaluation: dict[str, Any]
    config_hash: str
    dataset_hash: str
    ordered_task_ids: tuple[str, ...]

    def manifest(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "baseline": self.baseline,
            "mode": self.mode,
            "dataset_name": self.dataset_name,
            "experiment_name": self.experiment_name,
            "model_name": CHAT_MODEL,
            "config_hash": self.config_hash,
            "dataset_hash": self.dataset_hash,
            "ordered_task_ids": list(self.ordered_task_ids),
            "appworld_root": str(self.appworld_root),
            "output_root": str(self.output_root),
        }


def load_run_config(path: Path) -> RunSpec:
    path = path.resolve()
    raw_bytes = path.read_bytes()
    raw = yaml.safe_load(raw_bytes)
    config = _mapping(raw, "run config")
    _only_keys(config, _TOP_KEYS, "run config")
    _reject_task_selectors(config)
    if config.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"schema_version must be {SCHEMA_VERSION}")
    baseline = config.get("baseline")
    if baseline not in BASELINES:
        raise ValueError(f"baseline must be one of {sorted(BASELINES)}")
    for section, allowed in _SHARED_KEYS.items():
        _only_keys(_mapping(config.get(section, {}), section), allowed, section)

    task_source = _mapping(config.get("task_source"), "task_source")
    dataset_name = task_source.get("dataset_name")
    if not isinstance(dataset_name, str) or not dataset_name:
        raise ValueError("task_source.dataset_name is required")
    num_epochs = task_source.get("num_epochs", 1)
    if isinstance(num_epochs, bool) or not isinstance(num_epochs, int) or num_epochs < 1:
        raise ValueError("task_source.num_epochs must be a positive integer")

    baseline_config = _mapping(config.get("baseline_config"), "baseline_config")
    _only_keys(baseline_config, _BASELINE_KEYS[baseline], "baseline_config")
    _validate_baseline_shape(baseline, baseline_config)
    mode = baseline_config.get("mode")
    if mode not in MODES:
        raise ValueError(f"baseline_config.mode must be one of {sorted(MODES)}")
    if baseline in {"reasoningbank", "polyskill"} and mode != "online_adaptation":
        raise NotImplementedError(f"{baseline} unified adapter currently supports online_adaptation only")
    if baseline == "reme" and mode == "evaluation":
        raise ValueError("ReMe supports online_adaptation or offline_adaptation, not evaluation")
    if baseline == "ace" and int(baseline_config.get("batch_size", 1)) != 1:
        raise NotImplementedError("ACE batch adapter is not yet implemented")

    expected_name = f"{baseline}_{dataset_name}_{mode}_{CHAT_MODEL}"
    if config.get("experiment_name") != expected_name:
        raise ValueError(f"experiment_name must be {expected_name!r}")
    evaluation = _mapping(config.get("evaluation", {}), "evaluation")
    if evaluation.get("dataset_output_name") != dataset_name:
        raise ValueError("evaluation.dataset_output_name must equal task_source.dataset_name")
    if any(evaluation.get(key) is False for key in ("enabled", "save_task_reports", "aggregate")):
        raise ValueError("Official task and aggregate evaluation cannot be disabled")
    logging = _mapping(config.get("logging", {}), "logging")
    llm_calls = _mapping(logging.get("llm_calls", {}), "logging.llm_calls")
    _only_keys(llm_calls, {"enabled", "fail_closed", "process_safe"}, "logging.llm_calls")
    if any(llm_calls.get(key) is not True for key in ("enabled", "fail_closed", "process_safe")):
        raise ValueError("Canonical LLM logging must be enabled, fail-closed, and process-safe")

    _validate_models(baseline, baseline_config)
    if baseline == "ace":
        agent = _mapping(baseline_config["agent"], "baseline_config.agent")
        for key in (
            "generator_prompt_file_path", "reflector_prompt_file_path",
            "curator_prompt_file_path", "initial_playbook_file_path",
            "trained_playbook_file_path",
        ):
            if key not in agent or agent[key] is None:
                continue
            resolved = _resolve_path(agent[key], path.parent, f"baseline_config.agent.{key}")
            if (key != "trained_playbook_file_path" or mode == "evaluation") and not resolved.is_file():
                raise ValueError(f"ACE input file does not exist: {resolved}")
            agent[key] = str(resolved)
    appworld = _mapping(config.get("appworld", {}), "appworld")
    appworld_root = _resolve_path(appworld.get("root"), path.parent, "appworld.root")
    dataset_file = appworld_root / "data" / "datasets" / f"{dataset_name}.txt"
    if not dataset_file.is_file():
        raise ValueError(f"Unknown AppWorld dataset: {dataset_name!r}")
    output = _mapping(config.get("output", {}), "output")
    output_root = _resolve_path(output.get("canonical_root"), path.parent, "output.canonical_root")
    if output_root != appworld_root / "experiments" / "outputs":
        raise ValueError("output.canonical_root must equal AppWorld's experiment outputs directory")
    pricing = _mapping(config.get("pricing", {}), "pricing")
    pricing_registry_path = _resolve_path(
        pricing.get("registry_path"), path.parent, "pricing.registry_path"
    )
    if not pricing_registry_path.is_file():
        raise ValueError(f"Pricing registry does not exist: {pricing_registry_path}")
    provider_environment = _mapping(config.get("provider_environment", {}), "provider_environment")
    env_file_value = provider_environment.get("env_file")
    provider_env_file = (
        _resolve_path(env_file_value, path.parent, "provider_environment.env_file")
        if env_file_value is not None
        else None
    )
    if provider_env_file is not None and not provider_env_file.is_file():
        raise ValueError(f"Provider env file does not exist: {provider_env_file}")

    # AppWorld's task loader is the authority; temporarily point it at this run's root.
    from appworld.common.path_store import path_store

    previous_root = path_store.root
    try:
        path_store.update_root(str(appworld_root))
        task_refs = load_task_stream(dataset_name, num_epochs=1)
        ordered_task_ids = tuple(ref.task_id for ref in task_refs)
    finally:
        path_store.update_root(previous_root)
    if not ordered_task_ids:
        raise ValueError(f"Dataset {dataset_name!r} contains no tasks")
    runtime = _mapping(config.get("runtime", {}), "runtime")
    if mode == "online_adaptation" and int(runtime.get("num_processes", 1)) != 1:
        raise ValueError("Online memory adaptation requires sequential task order")

    appworld_kwargs = {key: value for key, value in appworld.items() if key != "root" and value is not None}
    return RunSpec(
        baseline=baseline,
        mode=mode,
        dataset_name=dataset_name,
        experiment_name=expected_name,
        num_epochs=num_epochs,
        appworld_root=appworld_root,
        appworld_kwargs=appworld_kwargs,
        output_root=output_root,
        pricing_registry_path=pricing_registry_path,
        provider_env_file=provider_env_file,
        api_key_env=str(provider_environment.get("api_key_env", "OPENAI_API_KEY")),
        base_url_env=str(provider_environment.get("base_url_env", "OPENAI_BASE_URL")),
        source_config_path=path,
        baseline_config=baseline_config,
        runtime=runtime,
        evaluation=evaluation,
        config_hash=hashlib.sha256(raw_bytes).hexdigest(),
        dataset_hash=hashlib.sha256(dataset_file.read_bytes()).hexdigest(),
        ordered_task_ids=ordered_task_ids,
    )


def _validate_models(baseline: str, config: Mapping[str, Any]) -> None:
    if baseline == "ace":
        agent = _mapping(config.get("agent"), "baseline_config.agent")
        for role in ("generator", "reflector", "curator"):
            model_config = agent.get(f"{role}_model_config")
            if model_config is not None and _mapping(model_config, f"{role}_model_config").get("name") != CHAT_MODEL:
                raise ValueError(f"ACE {role} model must be {CHAT_MODEL}")
        if "generator_model_config" not in agent:
            raise ValueError("ACE generator_model_config is required")
    elif baseline in {"reasoningbank", "polyskill"}:
        if _mapping(config.get("model"), "baseline_config.model").get("name") != CHAT_MODEL:
            raise ValueError(f"{baseline} model must be {CHAT_MODEL}")
    else:
        models = _mapping(config.get("models"), "baseline_config.models")
        if models.get("executor") != CHAT_MODEL or models.get("summarizer") != CHAT_MODEL:
            raise ValueError(f"ReMe chat models must be {CHAT_MODEL}")
        if models.get("embedding") != EMBEDDING_MODEL:
            raise ValueError(f"ReMe embedding model must be {EMBEDDING_MODEL}")
        if models.get("embedding_dimensions") != 1024:
            raise ValueError("ReMe embedding_dimensions must match the existing 1024-dimensional core")
