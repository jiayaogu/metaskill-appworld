"""Provider-neutral, task-owned log of physical model calls.

The caller retains provider arguments, retry policy, response objects, and
cost accounting. This module is the sole writer of canonical lm_calls.jsonl.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Protocol, TypeVar


ResponseT = TypeVar("ResponseT")
_SECRET_KEY = re.compile(r"(?i)(api[_-]?key|access[_-]?token|authorization|password|secret)")
_BEARER = re.compile(r"(?i)\bBearer\s+[^\s]+")
_SK_KEY = re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b")


class LLMLoggingError(RuntimeError):
    """Infrastructure failure; never retry it as a provider failure."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _plain(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if hasattr(value, "model_dump"):
        return _plain(value.model_dump())
    if hasattr(value, "to_dict"):
        return _plain(value.to_dict())
    if hasattr(value, "dict"):
        return _plain(value.dict())
    return repr(value)


def redact_secrets(value: Any) -> Any:
    value = _plain(value)
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if _SECRET_KEY.search(key) else redact_secrets(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    if isinstance(value, str):
        return _SK_KEY.sub("[REDACTED]", _BEARER.sub("Bearer [REDACTED]", value))
    return value


class Serializer(Protocol):
    def request(self, request: Any) -> Any: ...

    def response(self, response: Any) -> Any: ...


class OpenAISerializer:
    def request(self, request: Any) -> Any:
        return _plain(request)

    def response(self, response: Any) -> Any:
        return _plain(response)


class LiteLLMSerializer(OpenAISerializer):
    """Retain LiteLLM's compatible response, including usage and ACE cost."""


class EmbeddingSerializer(OpenAISerializer):
    def response(self, response: Any) -> Any:
        raw = _plain(response)
        if not isinstance(raw, dict):
            return {"representation": type(response).__name__}
        data = raw.get("data", raw.get("embeddings", []))
        if not isinstance(data, list):
            data = []
        hashes = []
        for item in data:
            vector = item.get("embedding") if isinstance(item, dict) else item
            if vector is not None:
                encoded = json.dumps(vector, separators=(",", ":")).encode("utf-8")
                hashes.append(hashlib.sha256(encoded).hexdigest())
        return {
            "model": raw.get("model"),
            "usage": raw.get("usage"),
            "vector_count": len(data),
            "vector_hashes": hashes,
            "dimensions": (
                len(data[0].get("embedding", []))
                if data and isinstance(data[0], dict)
                else len(data[0]) if data and isinstance(data[0], list) else None
            ),
        }


@dataclass(frozen=True)
class LLMCallContext:
    phase: str
    component: str | None = None
    logical_call_id: str | None = None
    physical_call_id: str | None = None
    attempt: int | None = None
    step: int | None = None
    epoch: int | None = None
    episode_id: str | None = None
    episode_kind: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class ProcessSafeJsonlSink:
    """Append one line under an interprocess lock on the canonical file."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.touch(exist_ok=True)
        except Exception as error:
            raise LLMLoggingError(f"Failed to create canonical LLM log {self.path}") from error

    def append(self, record: dict[str, Any]) -> bool:
        try:
            encoded = (json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a+b") as stream:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
                try:
                    stream.seek(0)
                    for line in stream:
                        if json.loads(line)["id"] == record["id"]:
                            return False
                    stream.seek(0, os.SEEK_END)
                    stream.write(encoded)
                    stream.flush()
                    os.fsync(stream.fileno())
                finally:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
            return True
        except Exception as error:
            raise LLMLoggingError(f"Failed to append canonical LLM log {self.path}") from error


class LLMCallLogger:
    def __init__(
        self,
        *,
        sink: ProcessSafeJsonlSink,
        experiment_name: str,
        baseline: str,
        root_task_id: str,
    ) -> None:
        self.sink = sink
        self.experiment_name = experiment_name
        self.baseline = baseline
        self.root_task_id = root_task_id

    @property
    def path(self) -> Path:
        return self.sink.path

    @classmethod
    def from_environment(cls) -> LLMCallLogger:
        path = Path(os.environ["APPWORLD_LM_CALLS_PATH"]).resolve()
        task_id = os.environ["APPWORLD_LM_TASK_ID"]
        experiment_name = os.environ["APPWORLD_LM_EXPERIMENT_NAME"]
        baseline = os.environ["APPWORLD_LM_BASELINE"]
        if (
            path.name != "lm_calls.jsonl"
            or path.parent.name != "logs"
            or path.parent.parent.name != task_id
            or path.parent.parent.parent.name != "tasks"
            or path.parent.parent.parent.parent.name != experiment_name
            or path.parent.parent.parent.parent.parent.name != "outputs"
        ):
            raise ValueError("APPWORLD_LM_CALLS_PATH is not the current primary task's canonical path")
        return cls(
            sink=ProcessSafeJsonlSink(path),
            experiment_name=experiment_name,
            baseline=baseline,
            root_task_id=task_id,
        )

    def _record(
        self,
        *,
        physical_id: str,
        request: Any,
        output: Any,
        context: LLMCallContext,
        started_at: str,
        status: str,
    ) -> None:
        metadata = {
            "experiment_name": self.experiment_name,
            "baseline": self.baseline,
            "root_task_id": self.root_task_id,
            "phase": context.phase,
            "component": context.component,
            "logical_call_id": context.logical_call_id,
            "attempt": context.attempt,
            "step": context.step,
            "epoch": context.epoch,
            "episode_id": context.episode_id,
            "episode_kind": context.episode_kind,
            "status": status,
            "started_at": started_at,
            "finished_at": _utc_now(),
            "extra": context.metadata,
        }
        self.sink.append(
            {
                "id": physical_id,
                "input": redact_secrets(request),
                "output": redact_secrets(output),
                "metadata": redact_secrets(metadata),
            }
        )

    def invoke(
        self,
        *,
        provider_call: Callable[[], ResponseT],
        request: Any,
        context: LLMCallContext,
        serializer: Serializer,
    ) -> ResponseT:
        physical_id = context.physical_call_id or uuid.uuid4().hex
        started_at = _utc_now()
        safe_request = serializer.request(request)
        try:
            response = provider_call()
        except Exception as error:
            self._record(
                physical_id=physical_id,
                request=safe_request,
                output={"error_type": type(error).__name__, "error": str(error)},
                context=context,
                started_at=started_at,
                status="error",
            )
            raise
        try:
            serialized_response = serializer.response(response)
        except Exception as error:
            raise LLMLoggingError("Failed to serialize provider response") from error
        self._record(
            physical_id=physical_id,
            request=safe_request,
            output=serialized_response,
            context=context,
            started_at=started_at,
            status="success",
        )
        return response

    async def ainvoke(
        self,
        *,
        provider_call: Callable[[], Awaitable[ResponseT]],
        request: Any,
        context: LLMCallContext,
        serializer: Serializer,
    ) -> ResponseT:
        physical_id = context.physical_call_id or uuid.uuid4().hex
        started_at = _utc_now()
        safe_request = serializer.request(request)
        try:
            response = await provider_call()
        except Exception as error:
            self._record(
                physical_id=physical_id,
                request=safe_request,
                output={"error_type": type(error).__name__, "error": str(error)},
                context=context,
                started_at=started_at,
                status="error",
            )
            raise
        try:
            serialized_response = serializer.response(response)
        except Exception as error:
            raise LLMLoggingError("Failed to serialize provider response") from error
        self._record(
            physical_id=physical_id,
            request=safe_request,
            output=serialized_response,
            context=context,
            started_at=started_at,
            status="success",
        )
        return response


def task_lm_logger(output_root: Path, experiment_name: str, baseline: str, task_id: str) -> LLMCallLogger:
    path = output_root / experiment_name / "tasks" / task_id / "logs" / "lm_calls.jsonl"
    return LLMCallLogger(
        sink=ProcessSafeJsonlSink(path),
        experiment_name=experiment_name,
        baseline=baseline,
        root_task_id=task_id,
    )


def subprocess_logger_environment(
    logger: LLMCallLogger, *, episode_id: str | None = None, episode_kind: str | None = None
) -> dict[str, str]:
    """Pass canonical task ownership to ReMe chat/embedding workers."""

    return {
        "APPWORLD_LM_CALLS_PATH": str(logger.path.resolve()),
        "APPWORLD_LM_TASK_ID": logger.root_task_id,
        "APPWORLD_LM_EXPERIMENT_NAME": logger.experiment_name,
        "APPWORLD_LM_BASELINE": logger.baseline,
        "APPWORLD_LM_LOGGER_MODULE_PATH": str(Path(__file__).resolve()),
        "APPWORLD_LM_EPISODE_ID": episode_id or "",
        "APPWORLD_LM_EPISODE_KIND": episode_kind or "",
    }
