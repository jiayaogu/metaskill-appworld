"""Provider-free transport and pinned method parity checks."""

import ast
import asyncio
import copy
import datetime
import gzip
import json
import os
import re
import subprocess
import tempfile
import types
import unittest
from pathlib import Path
from typing import Any, List
from unittest.mock import Mock
from unittest.mock import patch

import httpx
import requests
from jinja2 import Template
from openai import OpenAI, AsyncOpenAI

import execution_audit as audit
import execution_matrix as matrix
from prompt import NEW_PROMPT_TEMPLATE


class TransportTests(unittest.TestCase):
    def test_mapping_contains_accepts_dynamic_extensions_but_rejects_conflicts(self):
        base = {"properties": {"metadata": {"type": "object", "enabled": True}}}
        extended = {
            "properties": {
                "metadata": {
                    "type": "object",
                    "enabled": True,
                    "properties": {"utility": {"type": "long"}},
                }
            }
        }
        self.assertTrue(audit.mapping_contains(extended, base))
        self.assertFalse(audit.mapping_contains(base, extended))
        self.assertFalse(
            audit.mapping_contains(
                {"properties": {"metadata": {"type": "object", "enabled": False}}},
                base,
            )
        )

    def test_mapping_normalization_makes_implicit_object_defaults_explicit(self):
        mappings = {
            "properties": {
                "metadata": {
                    "properties": {"utility": {"type": "long"}},
                },
                "content": {"type": "text"},
            }
        }
        normalized = audit.normalize_es_mappings(mappings)
        self.assertEqual(normalized["properties"]["metadata"]["type"], "object")
        self.assertTrue(normalized["properties"]["metadata"]["enabled"])
        self.assertNotIn("type", normalized)
        self.assertNotIn("type", mappings["properties"]["metadata"])

    def test_caught_store_error_still_invalidates_service_request(self):
        async def fail():
            raise ConnectionError("injected ES failure")

        store = types.SimpleNamespace(list=fail)
        audit.audit_store_failures(store)
        identity = {"errors": []}
        with audit.audit_scope(identity):
            with self.assertRaises(ConnectionError):
                asyncio.run(store.list())
        self.assertEqual(identity["errors"], ["ConnectionError"])

    def test_audit_clock_is_not_appworld_simulated_time(self):
        from freezegun import freeze_time

        before = audit.now()
        with freeze_time("2000-01-01"):
            self.assertGreaterEqual(audit.now(), before)
            self.assertGreaterEqual(audit.shared_logger()._utc_now(), before)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "outputs/test_run_0"
        os.environ["APPWORLD_LM_LOGGER_MODULE_PATH"] = str(
            matrix.DEFAULT_APPWORLD_ROOT / "experiments/code/common/lm_logger.py"
        )

    def tearDown(self):
        self.temporary.cleanup()

    def rows(self, task):
        path = self.root / "tasks" / task / "logs/lm_calls.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()]

    def test_sdk_retries_each_have_physical_record(self):
        calls = []

        def provider(request):
            calls.append(json.loads(request.content))
            body = (
                {"error": {"message": "retry"}}
                if len(calls) == 1
                else {
                    "id": "response",
                    "object": "chat.completion",
                    "model": "qwen3.8-flash",
                    "choices": [
                        {"index": 0, "message": {"role": "assistant", "content": "answer"}, "finish_reason": "stop"}
                    ],
                    "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
                }
            )
            return httpx.Response(
                500 if len(calls) == 1 else 200,
                stream=httpx.ByteStream(json.dumps(body).encode()),
                headers={"content-type": "application/json", "retry-after-ms": "1"},
            )

        identity = {"run_directory": str(self.root), "task_id": "one", "phase": "executor", "request_id": "logical"}
        with (
            audit.audit_scope(identity),
            OpenAI(
                api_key="dummy",
                base_url="https://mock.invalid/v1",
                http_client=audit.provider_http_client(transport=httpx.MockTransport(provider)),
            ) as client,
        ):
            response = client.chat.completions.create(
                model="qwen3.8-flash", messages=[{"role": "user", "content": "hi"}]
            )
        self.assertEqual(response.choices[0].message.content, "answer")
        rows = self.rows("one")
        self.assertEqual(len(rows), 2)
        self.assertEqual([r["metadata"]["status"] for r in rows], ["error", "success"])
        self.assertEqual([r["metadata"]["attempt"] for r in rows], [1, 2])
        self.assertEqual(rows[0]["metadata"]["logical_call_id"], rows[1]["metadata"]["logical_call_id"])
        self.assertNotIn("dummy", json.dumps(rows))
        self.assertIsNone(audit.AUDIT.get())

    def test_concurrent_async_embedding_identity_and_vector_hashes(self):
        async def run():
            async def provider(request):
                await asyncio.sleep(0)
                return httpx.Response(
                    200,
                    stream=httpx.ByteStream(
                        json.dumps(
                            {
                                "model": "text-embedding-v4",
                                "usage": {"prompt_tokens": 2},
                                "data": [{"embedding": [0.1, 0.2], "index": 0}],
                            }
                        ).encode()
                    ),
                )

            async def one(task):
                identity = {"run_directory": str(self.root), "task_id": task, "phase": "retrieve_task_memory"}
                with audit.audit_scope(identity):
                    async with audit.provider_http_client(True, httpx.MockTransport(provider)) as client:
                        response = await client.post("https://mock.invalid/embeddings", json={"input": [task]})
                        self.assertEqual(response.json()["data"][0]["embedding"], [0.1, 0.2])

            await asyncio.gather(one("one"), one("two"))

        asyncio.run(run())
        for task in ("one", "two"):
            (row,) = self.rows(task)
            self.assertEqual(row["metadata"]["root_task_id"], task)
            self.assertEqual(row["output"]["vector_count"], 1)
            self.assertEqual(row["output"]["dimensions"], 2)
            self.assertNotIn("embedding", row["output"])
            self.assertEqual(len(row["output"]["vector_hashes"][0]), 64)

    def test_stream_failure_and_initialization_scope(self):
        class Broken(httpx.SyncByteStream):
            def __iter__(self):
                yield b'data: {"choices": []}\n\n'
                raise httpx.ReadError("injected stream break")

        def provider(request):
            return httpx.Response(200, stream=Broken())

        with audit.audit_scope({"run_directory": str(self.root), "phase": "load_memory"}):
            with audit.provider_http_client(transport=httpx.MockTransport(provider)) as client:
                with self.assertRaises(httpx.ReadError):
                    client.post("https://mock.invalid/completions", json={"model": "qwen3.8-flash"})
        path = self.root / "baseline_artifacts/reme/initialization_lm_calls.jsonl"
        row = json.loads(path.read_text())
        self.assertEqual(row["metadata"]["status"], "error")
        self.assertEqual(row["metadata"]["root_task_id"], "__initialization__")
        self.assertFalse((self.root / "tasks").exists())

    def test_sdk_done_terminal_is_success_for_sync_and_async_compressed_streams(self):
        chunk = {
            "id": "stream",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": "qwen3.8-flash",
            "choices": [],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
        }
        payload = gzip.compress(("data: " + json.dumps(chunk) + "\n\ndata: [DONE]\n\n").encode())

        def provider(request):
            return httpx.Response(
                200,
                headers={"content-encoding": "gzip", "content-type": "text/event-stream"},
                stream=httpx.ByteStream(payload),
            )

        with audit.audit_scope({"run_directory": str(self.root), "task_id": "sync"}):
            with OpenAI(
                api_key="dummy",
                base_url="https://mock.invalid/v1",
                http_client=audit.provider_http_client(transport=httpx.MockTransport(provider)),
            ) as client:
                with client.chat.completions.create(model="qwen3.8-flash", messages=[], stream=True) as stream:
                    self.assertEqual([c.usage.total_tokens for c in stream], [5])

        async def run():
            with audit.audit_scope({"run_directory": str(self.root), "task_id": "async"}):
                async with AsyncOpenAI(
                    api_key="dummy",
                    base_url="https://mock.invalid/v1",
                    http_client=audit.provider_http_client(True, httpx.MockTransport(provider)),
                ) as client:
                    stream = await client.chat.completions.create(model="qwen3.8-flash", messages=[], stream=True)
                    async with stream:
                        self.assertEqual([c.usage.total_tokens async for c in stream], [5])

        asyncio.run(run())
        for task in ("sync", "async"):
            (row,) = self.rows(task)
            self.assertEqual(row["metadata"]["status"], "success")
            self.assertEqual(row["output"]["usage"]["total_tokens"], 5)


class MethodParityTests(unittest.TestCase):
    def test_acknowledged_empty_summary_is_valid(self):
        source = (matrix.SOURCE_ROOT / "benchmark/appworld/appworld_react_agent.py").read_text()
        cls = self.source_class(source, Mock())
        agent = cls(index=0, task_ids=["task"], experiment_name="test")
        agent._memory_call = lambda *args: {"success": True, "metadata": {}}
        self.assertEqual(agent.summary_memory([]), [])

    def source_class(self, source, world, isolated=None):
        tree = ast.parse(source)
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "AppworldReactAgent")
        cls.decorator_list = []
        namespace = {
            "List": List,
            "Any": Any,
            "AppWorld": world,
            "OpenAI": lambda **kw: Mock(),
            "json": json,
            "re": re,
            "datetime": datetime,
            "Template": Template,
            "NEW_PROMPT_TEMPLATE": NEW_PROMPT_TEMPLATE,
            "logger": Mock(),
            "requests": requests,
            "tqdm": lambda iterable, **kw: iterable,
            "isolated_reward": isolated or Mock(side_effect=AssertionError("unexpected isolated reward")),
        }
        exec(compile(ast.Module(body=[cls], type_ignores=[]), "parity", "exec"), namespace)
        return namespace["AppworldReactAgent"]

    def test_original_core_ast_is_unchanged(self):
        original = subprocess.check_output(
            ["git", "show", "2f37a15:benchmark/appworld/appworld_react_agent.py"], cwd=matrix.SOURCE_ROOT, text=True
        )
        current = (matrix.SOURCE_ROOT / "benchmark/appworld/appworld_react_agent.py").read_text()
        old = next(n for n in ast.walk(ast.parse(original)) if isinstance(n, ast.FunctionDef) and n.name == "execute")
        new = next(n for n in ast.walk(ast.parse(current)) if isinstance(n, ast.FunctionDef) and n.name == "_execute")
        new.name = "execute"
        self.assertEqual(ast.dump(old), ast.dump(new))

    def test_reward_uses_isolated_official_evaluator(self):
        source = (matrix.SOURCE_ROOT / "benchmark/appworld/appworld_react_agent.py").read_text()
        calls = []
        cls = self.source_class(
            source,
            Mock(),
            isolated=lambda task_id, experiment_name: calls.append((task_id, experiment_name)) or 2 / 3,
        )
        world = types.SimpleNamespace(task_id="task", experiment_name="experiment")
        self.assertEqual(cls.get_reward(world), 2 / 3)
        self.assertEqual(calls, [("task", "experiment")])

    def test_middleware_auth_identity_and_swallowed_failure(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "run_manifest.json").write_text(json.dumps({"task_ids": ["one", "two"]}))
            service = types.SimpleNamespace(
                http_service=FastAPI(),
                service_context=types.SimpleNamespace(vector_stores={"default": types.SimpleNamespace()}),
            )
            memory_module = types.ModuleType("reme.core.schema.memory_node")
            memory_module.MemoryNode = Mock()
            with (
                patch.dict(os.environ, REME_AUDIT_RUN_DIRECTORY=str(root), REME_AUDIT_TOKEN="private-token"),
                patch.dict("sys.modules", {"reme.core.schema.memory_node": memory_module}),
            ):
                audit.install_service_audit(service)

            @service.http_service.post("/probe")
            async def probe():
                return {"task": audit.AUDIT.get()["task_id"]}

            @service.http_service.post("/swallowed")
            async def swallowed():
                audit.AUDIT.get()["errors"].append("injected operation failure")
                return {"success": True}

            with TestClient(service.http_service) as client:
                self.assertEqual(client.post("/probe").status_code, 403)
                for task in ("one", "two"):
                    headers = {"X-ReMe-Audit-Token": "private-token", "X-ReMe-Task": task}
                    self.assertEqual(client.post("/probe", headers=headers).json(), {"task": task})
                    self.assertEqual(client.post("/swallowed", headers=headers).status_code, 502)
                self.assertEqual(
                    client.post(
                        "/probe", headers={"X-ReMe-Audit-Token": "private-token", "X-ReMe-Task": "unknown"}
                    ).status_code,
                    400,
                )
            self.assertIsNone(audit.AUDIT.get())

    def test_success_failure_arm_order_matches_pinned_core(self):
        original = subprocess.check_output(
            ["git", "show", "2f37a15:benchmark/appworld/appworld_react_agent.py"], cwd=matrix.SOURCE_ROOT, text=True
        )
        current = (matrix.SOURCE_ROOT / "benchmark/appworld/appworld_react_agent.py").read_text()
        for success in (False, True):
            for arm in matrix.ARMS:
                traces, results = [], []
                for source in (original, current):
                    trace = []

                    class World:
                        def __init__(self, task_id, experiment_name):
                            self.task_id, self.count = task_id, 0
                            self.experiment_name = experiment_name
                            self.task = types.SimpleNamespace(instruction="do task", supervisor={}, app_descriptions={})
                            World.latest = self

                        def __enter__(self):
                            return self

                        def __exit__(self, *args):
                            trace.append("close")

                        def evaluate(self):
                            trace.append("evaluate")
                            self.count += 1
                            passed = success and self.count == 2
                            return types.SimpleNamespace(passes=[1] if passed else [], failures=[] if passed else [1])

                        def execute(self, code):
                            trace.append("action")
                            return "done"

                        def task_completed(self):
                            return True

                    def isolated(task_id, experiment_name):
                        tracker = World.latest.evaluate()
                        return len(tracker.passes) / (len(tracker.passes) + len(tracker.failures))

                    cls = self.source_class(source, World, isolated=isolated)
                    agent = cls(
                        index=0,
                        task_ids=["task"],
                        experiment_name="test",
                        use_memory=True,
                        use_memory_addition=arm != "fixed",
                        use_memory_deletion=arm != "fixed",
                    )

                    def retrieve(query):
                        trace.append("retrieve")
                        return {"metadata": {"memory_list": []}, "answer": ""}

                    def summary(trajectories):
                        trace.append("summary")
                        return []

                    agent.get_memory, agent.summary_memory = retrieve, summary
                    agent.call_llm = lambda messages: '```python\nprint("hi")\n```'
                    agent.add_memory = lambda memories: trace.append("add")
                    agent.update_memory_information = lambda memories, utility: trace.append(("record", utility))
                    agent.delete_memory = lambda: trace.append("delete")
                    result = agent.execute()[0]
                    result.pop("task_start_time")
                    results.append(result)
                    traces.append(trace)
                self.assertEqual(traces[0], traces[1])
                self.assertEqual(results[0], results[1])
                self.assertEqual("add" in traces[1], success and arm != "fixed")
                self.assertEqual("summary" in traces[1], arm != "fixed")
                self.assertEqual(traces[1][-1], "close")


if __name__ == "__main__":
    unittest.main()
