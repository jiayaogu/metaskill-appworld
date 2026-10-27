"""Provider-free tests for mandatory uncapped formal accounting."""

import json
import multiprocessing
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import execution_accounting as accounting


def start_worker(arguments):
    index, url, identity = arguments
    physical_id = accounting.new_physical_id()
    accounting.start(physical_id, url, {"model": "qwen3.8-flash"}, identity)
    accounting.settle(
        physical_id,
        {"usage": {"prompt_tokens": index + 1, "completion_tokens": 1}},
        False,
    )
    return physical_id


class FormalAccountingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.path = self.root / "formal.json"
        self.policy = {
            "schema_version": 1,
            "mode": "formal_accounting",
            "limit_usd": None,
            "models": {
                "qwen3.8-flash": {
                    "input": "0.64",
                    "output": "2.16",
                    "cached": "0.08",
                    "urls": ["https://chat.invalid/v1/chat/completions"],
                },
                "text-embedding-v4": {
                    "input": "0.07",
                    "output": "0",
                    "cached": "0",
                    "urls": ["https://embedding.invalid/v1/embeddings"],
                },
            },
        }
        self.path.write_text(json.dumps(self.policy))
        self.environment = patch.dict(
            os.environ,
            {accounting.ENVIRONMENT_KEY: str(self.path)},
            clear=False,
        )
        self.environment.start()
        os.environ.pop(accounting.SMOKE_ENVIRONMENT_KEY, None)

    def tearDown(self):
        self.environment.stop()
        self.temporary.cleanup()

    def identity(self, **updates):
        value = {
            "campaign": "formal-20261024",
            "run": "normal-fixed-r01",
            "stage": "task",
            "task": "task-one",
            "task_attempt_id": "task-one-a01",
            "attempt_kind": "primary",
            "ownership_generation": 1,
        }
        value.update(updates)
        return value

    def start(self, *, identity=None, model="qwen3.8-flash", url=None, request=None):
        physical_id = accounting.new_physical_id()
        accounting.start(
            physical_id,
            url or "https://chat.invalid/v1/chat/completions",
            request or {"model": model},
            identity or self.identity(),
        )
        return physical_id

    def test_policy_is_versioned_uncapped_and_separate_from_smoke(self):
        _, data, digest = accounting.policy()
        self.assertEqual(data["mode"], "formal_accounting")
        self.assertIsNone(data["limit_usd"])
        self.assertEqual(len(digest), 64)
        with patch.dict(os.environ, {accounting.SMOKE_ENVIRONMENT_KEY: "smoke.json"}):
            with self.assertRaisesRegex(accounting.AccountingError, "cannot both"):
                accounting.policy()
        self.policy["limit_usd"] = "999999"
        self.path.write_text(json.dumps(self.policy))
        with self.assertRaisesRegex(accounting.AccountingError, "must be null"):
            accounting.policy()

    def test_policy_hash_is_immutable_after_first_start(self):
        self.start()
        self.policy["description"] = "changed"
        self.path.write_text(json.dumps(self.policy))
        with self.assertRaisesRegex(accounting.AccountingError, "changed"):
            accounting.summary()

    def test_identity_allowlist_uuid_and_duplicate_validation(self):
        with self.assertRaisesRegex(accounting.AccountingError, "UUID4"):
            accounting.start(
                "not-global", "https://chat.invalid/v1/chat/completions", {"model": "qwen3.8-flash"}, self.identity()
            )
        with self.assertRaisesRegex(accounting.AccountingError, "identity"):
            accounting.start(
                accounting.new_physical_id(), "https://chat.invalid/v1/chat/completions", {"model": "qwen3.8-flash"}, {}
            )
        with self.assertRaisesRegex(accounting.AccountingError, "Unapproved"):
            self.start(url="https://other.invalid/v1/chat/completions")
        physical_id = self.start()
        with self.assertRaisesRegex(accounting.AccountingError, "Duplicate"):
            accounting.start(
                physical_id,
                "https://chat.invalid/v1/chat/completions",
                {"model": "qwen3.8-flash"},
                self.identity(),
            )

    def test_no_spend_threshold_under_concurrent_load(self):
        url = "https://chat.invalid/v1/chat/completions"
        arguments = [(index, url, self.identity(task_attempt_id=f"attempt-{index}")) for index in range(40)]
        with multiprocessing.get_context("fork").Pool(8) as pool:
            ids = pool.map(start_worker, arguments)
        self.assertEqual(len(set(ids)), 40)
        result = accounting.summary(campaign="formal-20261024")
        self.assertEqual(result["physical_requests"], 40)
        self.assertEqual(result["priced_requests"], 40)
        self.assertEqual(result["unsettled_requests"], 0)
        self.assertIsNone(result["limit_usd"])

    def test_summary_distinguishes_all_states_and_recovery_cost(self):
        priced = self.start()
        accounting.settle(
            priced,
            {"usage": {"prompt_tokens": 100, "completion_tokens": 20, "prompt_tokens_details": {"cached_tokens": 50}}},
            False,
        )
        unknown = self.start(identity=self.identity(task_attempt_id="task-one-a02", attempt_kind="recovery"))
        accounting.settle(unknown, {"usage": None}, False)
        failed_priced = self.start(identity=self.identity(task_attempt_id="task-one-a03", attempt_kind="recovery"))
        accounting.settle(failed_priced, {"usage": {"prompt_tokens": 10, "completion_tokens": 1}}, True)
        failed_unknown = self.start(identity=self.identity(task_attempt_id="task-one-a04", attempt_kind="recovery"))
        accounting.settle(failed_unknown, {}, True)
        self.start(identity=self.identity(task_attempt_id="task-one-a05", attempt_kind="recovery"))
        result = accounting.summary(run="normal-fixed-r01")
        self.assertEqual(result["priced_requests"], 1)
        self.assertEqual(result["unknown_requests"], 1)
        self.assertEqual(result["failed_requests"], 2)
        self.assertEqual(result["failed_priced_requests"], 1)
        self.assertEqual(result["failed_unknown_requests"], 1)
        self.assertEqual(result["unsettled_requests"], 1)
        self.assertEqual(result["by_attempt_kind"]["primary"]["physical_requests"], 1)
        self.assertEqual(result["by_attempt_kind"]["recovery"]["physical_requests"], 4)
        self.assertAlmostEqual(result["estimated_usd"], 0.00008776)
        self.assertIsNone(result["billed_dollars"])

    def test_embedding_usage_and_duplicate_settlement(self):
        physical_id = self.start(
            identity=self.identity(stage="initialization", task=None, task_attempt_id="initialization-a01"),
            model="text-embedding-v4",
            url="https://embedding.invalid/v1/embeddings",
            request={"model": "text-embedding-v4", "input": ["formal accounting test"]},
        )
        accounting.settle(physical_id, {"usage": {"prompt_tokens": 5}}, False)
        self.assertAlmostEqual(accounting.summary()["estimated_usd"], 0.00000035)
        with self.assertRaisesRegex(accounting.AccountingError, "Duplicate"):
            accounting.settle(physical_id, {"usage": {"prompt_tokens": 5}}, False)

    def test_reconcile_reports_join_orphans_duplicates_and_filters(self):
        joined = self.start()
        accounting.settle(joined, {"usage": {"prompt_tokens": 1, "completion_tokens": 1}}, False)
        ledger_only = self.start(identity=self.identity(task_attempt_id="task-one-a02", attempt_kind="recovery"))
        accounting.settle(ledger_only, {}, True)
        log_only = accounting.new_physical_id()
        result = accounting.reconcile(
            [{"id": joined}, {"id": log_only}, {"id": log_only}],
            campaign="formal-20261024",
            run="normal-fixed-r01",
        )
        self.assertEqual(result["status"], "mismatch")
        self.assertEqual(result["joined_ids"], [joined])
        self.assertEqual(result["ledger_only_ids"], [ledger_only])
        self.assertEqual(result["log_only_ids"], [log_only])
        self.assertEqual(result["duplicate_log_ids"], [log_only])
        matched = accounting.reconcile([{"id": joined}], task_attempt_id="task-one-a01")
        self.assertEqual(matched["status"], "matched")
        self.assertEqual(matched["summary"]["physical_requests"], 1)


if __name__ == "__main__":
    unittest.main()
