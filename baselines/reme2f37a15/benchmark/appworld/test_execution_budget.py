"""Budget tests use temporary files and mock transports; no provider requests."""

import asyncio
import gzip
import json
import multiprocessing
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

import execution_audit as audit
import execution_budget as budget
import execution_matrix as matrix


def reserve_worker(index):
    try:
        budget.reserve(
            str(index),
            "https://mock.invalid/chat/completions",
            {"model": "qwen3.8-flash"},
            {"run_directory": "/tmp/test"},
        )
        return True
    except budget.BudgetStopped:
        return False


class BudgetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.path = self.root / "policy.json"
        self.config = {
            "limit_usd": "10",
            "prior_allowance_usd": "1",
            "models": {
                "qwen3.8-flash": {
                    "input": "0.64",
                    "output": "2.16",
                    "cached": "0.08",
                    "reserve_usd": "2",
                    "urls": ["https://mock.invalid/chat/completions"],
                },
                "text-embedding-v4": {
                    "input": "0.07",
                    "output": "0",
                    "cached": "0",
                    "reserve_usd": "0.01",
                    "urls": ["https://mock.invalid/embeddings"],
                },
            },
        }
        self.path.write_text(json.dumps(self.config))
        self.environment = patch.dict(
            os.environ,
            {
                budget.ENVIRONMENT_KEY: str(self.path),
                "APPWORLD_LM_LOGGER_MODULE_PATH": str(
                    matrix.DEFAULT_APPWORLD_ROOT / "experiments/code/common/lm_logger.py"
                ),
            },
        )
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
        self.temp.cleanup()

    def reserve(self, name="one", url="https://mock.invalid/chat/completions", model="qwen3.8-flash"):
        return budget.reserve(name, url, {"model": model}, {"run_directory": str(self.root)})

    def test_concurrent_processes_cannot_overreserve(self):
        with multiprocessing.get_context("fork").Pool(6) as pool:
            accepted = pool.map(reserve_worker, range(12))
        self.assertEqual(sum(accepted), 4)
        self.assertEqual(budget.summary()["held_with_prior_usd"], 9)

    def test_usage_settlement_and_cache_not_double_counted(self):
        self.reserve()
        budget.settle(
            "one",
            {"usage": {"prompt_tokens": 100, "completion_tokens": 20, "prompt_tokens_details": {"cached_tokens": 50}}},
            False,
        )
        self.assertAlmostEqual(budget.summary()["estimated_usd"], 0.0000792)
        with self.assertRaises(budget.BudgetStopped):
            budget.settle("one", {"usage": {}}, False)

    def test_missing_usage_and_errors_retain_reservation(self):
        self.reserve("missing")
        self.reserve("failed")
        self.reserve("unfinished")
        budget.settle("missing", {}, False)
        budget.settle("failed", {"usage": {"prompt_tokens": 1, "completion_tokens": 1}}, True)
        self.assertEqual(budget.summary()["held_with_prior_usd"], 7)
        self.assertEqual(budget.summary()["unresolved_requests"], 3)

    def test_rejects_unknown_endpoint_model_and_changed_policy(self):
        for kwargs in ({"url": "https://other.invalid/chat/completions"}, {"model": "other"}):
            with self.assertRaises(budget.BudgetStopped):
                self.reserve(**kwargs)
        self.reserve()
        self.config["limit_usd"] = "11"
        self.path.write_text(json.dumps(self.config))
        with self.assertRaises(budget.BudgetStopped):
            self.reserve("two")

    def test_exhaustion_stops_before_transport(self):
        for index in range(4):
            self.reserve(str(index))
        sent = []
        with audit.audit_scope({"run_directory": str(self.root)}):
            with audit.provider_http_client(
                transport=httpx.MockTransport(lambda request: sent.append(request))
            ) as client:
                with self.assertRaises(budget.BudgetStopped):
                    client.post("https://mock.invalid/chat/completions", json={"model": "qwen3.8-flash"})
        self.assertEqual(sent, [])

    def test_async_embedding_cost_joins_canonical_physical_id(self):
        async def run():
            def provider(request):
                return httpx.Response(
                    200,
                    headers={"content-encoding": "gzip"},
                    stream=httpx.ByteStream(
                        gzip.compress(
                            json.dumps(
                                {
                                    "model": "text-embedding-v4",
                                    "usage": {"prompt_tokens": 5},
                                    "data": [{"index": 0, "embedding": [0.1] * 1024}],
                                }
                            ).encode()
                        )
                    ),
                )

            with audit.audit_scope({"run_directory": str(self.root), "phase": "load_memory"}):
                async with audit.provider_http_client(True, httpx.MockTransport(provider)) as client:
                    await client.post(
                        "https://mock.invalid/embeddings", json={"model": "text-embedding-v4", "input": ["hi"]}
                    )

        asyncio.run(run())
        calls = [
            json.loads(line)
            for line in (self.root / "baseline_artifacts/reme/initialization_lm_calls.jsonl").read_text().splitlines()
        ]
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["output"]["dimensions"], 1024)
        self.assertEqual(calls[0]["output"]["vector_count"], 1)
        self.assertEqual(calls[0]["output"]["model"], "text-embedding-v4")
        self.assertAlmostEqual(budget.cost_evidence(calls)["dollars"], 0.00000035)
        self.assertEqual(budget.summary()["unresolved_requests"], 0)


if __name__ == "__main__":
    unittest.main()
