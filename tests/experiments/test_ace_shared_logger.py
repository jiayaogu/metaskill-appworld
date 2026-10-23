from __future__ import annotations

import json
from pathlib import Path

from appworld_experiments.code.ace import lite_llm_generator
from appworld_experiments.code.ace.lite_llm_generator import LiteLLMGenerator
from appworld_experiments.code.common.lm_logger import task_lm_logger


def test_ace_generate_delegates_to_task_logger_without_changing_response(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(lite_llm_generator, "token_counter", lambda **kwargs: 1)
    generator = LiteLLMGenerator.__new__(LiteLLMGenerator)
    generator.model = "qwen3.8-flash"
    generator.max_input_tokens = None
    generator.max_output_tokens = None
    generator.max_retries = 2
    generator.retry_after_n_seconds = None
    generator.generation_kwargs = {"completion_method": "openai"}
    generator.completion_cost = lambda **kwargs: 0.5
    provider_calls: list[dict] = []

    def provider(**arguments):
        provider_calls.append(arguments)
        return {"choices": [{"message": {"content": "answer"}}], "usage": {"total_tokens": 2}}

    generator.chat_completion = provider
    generator.log_file_path = None
    logger = task_lm_logger(tmp_path, "experiment", "ace", "task_1")
    generator.set_call_logger(logger, phase="reflector")
    generator.log_calls_to(file_path=str(tmp_path / "wrong.jsonl"))

    output = generator.generate(messages=[{"role": "user", "content": "hello"}])

    assert output == {"content": "answer", "cost": 0.5}
    assert len(provider_calls) == 1
    assert not (tmp_path / "wrong.jsonl").exists()
    records = [json.loads(line) for line in logger.path.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 1
    assert records[0]["metadata"]["phase"] == "reflector"
    assert records[0]["output"]["cost"] == 0.5
