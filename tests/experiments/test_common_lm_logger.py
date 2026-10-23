from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from appworld_experiments.code.common.lm_logger import (
    EmbeddingSerializer,
    LLMCallContext,
    LLMCallLogger,
    LLMLoggingError,
    OpenAISerializer,
    ProcessSafeJsonlSink,
    subprocess_logger_environment,
    task_lm_logger,
)


def _records(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_success_preserves_response_and_writes_only_task_log(tmp_path: Path) -> None:
    logger = task_lm_logger(tmp_path, "experiment", "ace", "task_1")
    response = {"usage": {"prompt_tokens": 3}, "choices": [{"message": {"content": "ok"}}]}
    result = logger.invoke(
        provider_call=lambda: response,
        request={"model": "qwen3.8-flash", "api_key": "secret", "messages": []},
        context=LLMCallContext(phase="generator", physical_call_id="physical-1"),
        serializer=OpenAISerializer(),
    )
    assert result is response
    assert logger.path == tmp_path / "experiment/tasks/task_1/logs/lm_calls.jsonl"
    assert list(tmp_path.rglob("lm_calls.jsonl")) == [logger.path]
    assert len(_records(logger.path)) == 1
    record = _records(logger.path)[0]
    assert record["id"] == "physical-1"
    assert record["input"]["api_key"] == "[REDACTED]"
    assert record["output"]["usage"]["prompt_tokens"] == 3
    assert record["metadata"]["phase"] == "generator"


def test_provider_failure_is_logged_and_original_exception_propagates(tmp_path: Path) -> None:
    logger = task_lm_logger(tmp_path, "experiment", "reme", "task_1")
    expected = ValueError("provider failed")

    def fail() -> None:
        raise expected

    with pytest.raises(ValueError) as caught:
        logger.invoke(
            provider_call=fail,
            request={"messages": []},
            context=LLMCallContext(phase="executor", logical_call_id="logical", attempt=2),
            serializer=OpenAISerializer(),
        )
    assert caught.value is expected
    record = _records(logger.path)[0]
    assert record["metadata"]["status"] == "error"
    assert record["metadata"]["attempt"] == 2


def test_resume_deduplicates_physical_call_id(tmp_path: Path) -> None:
    path = tmp_path / "experiment/tasks/task_1/logs/lm_calls.jsonl"
    sink = ProcessSafeJsonlSink(path)
    record = {"id": "same", "input": {}, "output": {}, "metadata": {}}
    assert sink.append(record)
    assert not sink.append(record)
    assert len(_records(path)) == 1


def test_embedding_records_hashes_not_vectors(tmp_path: Path) -> None:
    logger = task_lm_logger(tmp_path, "experiment", "reme", "task_1")
    logger.invoke(
        provider_call=lambda: {"model": "text-embedding-v4", "data": [{"embedding": [0.1, 0.2]}]},
        request={"model": "text-embedding-v4", "input": ["text"]},
        context=LLMCallContext(phase="embedding"),
        serializer=EmbeddingSerializer(),
    )
    output = _records(logger.path)[0]["output"]
    assert output["dimensions"] == 2
    assert output["vector_count"] == 1
    assert len(output["vector_hashes"][0]) == 64
    assert "data" not in output


def test_async_provider_is_logged(tmp_path: Path) -> None:
    logger = task_lm_logger(tmp_path, "experiment", "reme", "task_1")

    async def provider() -> dict:
        return {"usage": {"total_tokens": 1}}

    response = asyncio.run(
        logger.ainvoke(
            provider_call=provider,
            request={"input": "hi"},
            context=LLMCallContext(phase="memory_rewrite"),
            serializer=OpenAISerializer(),
        )
    )
    assert response["usage"]["total_tokens"] == 1
    assert _records(logger.path)[0]["metadata"]["phase"] == "memory_rewrite"


def test_sink_failure_is_infrastructure_error(tmp_path: Path) -> None:
    parent_is_file = tmp_path / "not_a_directory"
    parent_is_file.write_text("x", encoding="utf-8")
    with pytest.raises(LLMLoggingError):
        ProcessSafeJsonlSink(parent_is_file / "lm_calls.jsonl")


def test_subprocess_logger_environment_reopens_same_task_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    outputs = tmp_path / "experiments" / "outputs"
    logger = task_lm_logger(outputs, "experiment", "reme", "task_1")
    for key, value in subprocess_logger_environment(logger, episode_id="replay-1").items():
        monkeypatch.setenv(key, value)
    worker_logger = LLMCallLogger.from_environment()
    assert worker_logger.path == logger.path
    assert worker_logger.root_task_id == "task_1"

    monkeypatch.setenv("APPWORLD_LM_CALLS_PATH", str(tmp_path / "wrong.jsonl"))
    with pytest.raises(ValueError, match="canonical path"):
        LLMCallLogger.from_environment()
