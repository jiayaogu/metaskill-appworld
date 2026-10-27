"""Provider-free integration tests for the formal accounting audit dispatcher."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from openai import OpenAI

import execution_accounting as accounting
import execution_audit as audit
import execution_budget as budget
import execution_matrix as matrix
import execution_recovery as recovery


CHAT_URL = "https://mock.invalid/v1/chat/completions"


class FormalAuditIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "outputs/formal_test_run_0"
        self.root.mkdir(parents=True)
        self.policy_path = Path(self.temporary.name) / "formal-accounting.json"
        self.policy_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "mode": "formal_accounting",
                    "limit_usd": None,
                    "models": {
                        "qwen3.8-flash": {
                            "input": "0.64",
                            "output": "2.16",
                            "cached": "0.08",
                            "urls": [CHAT_URL],
                        }
                    },
                }
            )
        )
        claim_path = self.root / recovery.CLAIM_FILE
        claim_path.parent.mkdir(parents=True)
        claim_path.write_text(
            json.dumps(
                {
                    "schema_version": recovery.SCHEMA_VERSION,
                    "run_id": self.root.name,
                    "owner_token": "owner-one",
                    "generation": 1,
                    "status": "active",
                }
            )
        )
        self.environment = patch.dict(
            os.environ,
            {
                accounting.ENVIRONMENT_KEY: str(self.policy_path),
                "APPWORLD_LM_LOGGER_MODULE_PATH": str(
                    matrix.DEFAULT_APPWORLD_ROOT / "experiments/code/common/lm_logger.py"
                ),
            },
            clear=False,
        )
        self.environment.start()
        os.environ.pop(budget.ENVIRONMENT_KEY, None)

    def tearDown(self):
        self.environment.stop()
        self.temporary.cleanup()

    def identity(self):
        return {
            "run_directory": str(self.root),
            "task_id": "task-one",
            "phase": "executor",
            "request_id": "logical-one",
            "campaign": "formal-20261024",
            "run": self.root.name,
            "stage": "task",
            "task_attempt_id": "task-one-a01",
            "attempt_kind": "primary",
            "ownership_generation": 1,
            "owner_token": "owner-one",
            "attempts": {},
            "errors": [],
        }

    def rows(self):
        path = self.root / "tasks/task-one/logs/lm_calls.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()]

    @staticmethod
    def success_response():
        return {
            "id": "response",
            "object": "chat.completion",
            "model": "qwen3.8-flash",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "answer"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
        }

    def request_once(self, identity=None):
        def provider(_request):
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                stream=httpx.ByteStream(json.dumps(self.success_response()).encode()),
            )

        identity = identity or self.identity()
        with audit.audit_scope(identity):
            with audit.provider_http_client(transport=httpx.MockTransport(provider)) as client:
                response = client.post(CHAT_URL, json={"model": "qwen3.8-flash", "messages": []})
                response.raise_for_status()
        return identity

    def test_formal_start_and_settle_join_the_canonical_physical_id(self):
        self.request_once()
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        events = [json.loads(line) for line in accounting.ledger_path().read_text().splitlines()]
        self.assertEqual([event["event"] for event in events], ["start", "settle"])
        self.assertEqual({event["id"] for event in events}, {rows[0]["id"]})
        reconciliation = accounting.reconcile(rows, task_attempt_id="task-one-a01")
        self.assertEqual(reconciliation["status"], "matched")
        self.assertEqual(reconciliation["summary"]["priced_requests"], 1)

    def test_formal_execution_identity_remains_in_canonical_metadata_extra(self):
        self.request_once()
        (row,) = self.rows()
        self.assertEqual(row["metadata"]["root_task_id"], "task-one")
        self.assertEqual(
            row["metadata"]["extra"],
            {
                "http_status": 200,
                "campaign": "formal-20261024",
                "run": self.root.name,
                "stage": "task",
                "task_attempt_id": "task-one-a01",
                "attempt_kind": "primary",
                "ownership_generation": 1,
            },
        )

    def test_sdk_retries_are_distinct_from_the_task_attempt_identity(self):
        responses = []

        def provider(_request):
            responses.append(1)
            body = {"error": {"message": "retry"}} if len(responses) == 1 else self.success_response()
            return httpx.Response(
                500 if len(responses) == 1 else 200,
                headers={"content-type": "application/json", "retry-after-ms": "1"},
                stream=httpx.ByteStream(json.dumps(body).encode()),
            )

        identity = self.identity()
        with (
            audit.audit_scope(identity),
            OpenAI(
                api_key="dummy",
                base_url="https://mock.invalid/v1",
                http_client=audit.provider_http_client(transport=httpx.MockTransport(provider)),
            ) as client,
        ):
            response = client.chat.completions.create(
                model="qwen3.8-flash", messages=[{"role": "user", "content": "hello"}]
            )
        self.assertEqual(response.choices[0].message.content, "answer")
        rows = self.rows()
        self.assertEqual([row["metadata"]["attempt"] for row in rows], [1, 2])
        self.assertEqual({row["metadata"]["extra"]["task_attempt_id"] for row in rows}, {"task-one-a01"})
        self.assertEqual(len({row["id"] for row in rows}), 2)
        self.assertEqual(accounting.reconcile(rows, task_attempt_id="task-one-a01")["status"], "matched")
        summary = accounting.summary(task_attempt_id="task-one-a01")
        self.assertEqual(summary["failed_requests"], 1)
        self.assertEqual(summary["priced_requests"], 1)

    def test_smoke_and_formal_modes_are_mutually_exclusive_before_transport(self):
        sent = []
        with patch.dict(os.environ, {budget.ENVIRONMENT_KEY: str(Path(self.temporary.name) / "smoke.json")}):
            with audit.audit_scope(self.identity()):
                with audit.provider_http_client(
                    transport=httpx.MockTransport(lambda request: sent.append(request))
                ) as client:
                    with self.assertRaisesRegex(RuntimeError, "cannot both"):
                        client.post(CHAT_URL, json={"model": "qwen3.8-flash", "messages": []})
        self.assertEqual(sent, [])
        self.assertFalse(accounting.ledger_path().exists())
        self.assertFalse((self.root / "tasks/task-one/logs/lm_calls.jsonl").exists())

    def test_stale_owner_is_fenced_before_transport_or_accounting(self):
        claim_path = self.root / recovery.CLAIM_FILE
        claim = json.loads(claim_path.read_text())
        claim_path.write_text(json.dumps({**claim, "owner_token": "owner-two", "generation": 2}))
        sent = []
        with audit.audit_scope(self.identity()):
            with audit.provider_http_client(
                transport=httpx.MockTransport(lambda request: sent.append(request))
            ) as client:
                with self.assertRaisesRegex(recovery.StaleOwner, "fenced"):
                    client.post(CHAT_URL, json={"model": "qwen3.8-flash", "messages": []})
        self.assertEqual(sent, [])
        self.assertFalse(accounting.ledger_path().exists())
        self.assertFalse((self.root / "tasks/task-one/logs/lm_calls.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
