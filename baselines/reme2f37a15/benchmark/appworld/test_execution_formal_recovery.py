"""Provider-free integration tests for the formal execution recovery loop."""

import copy
import json
import os
import tempfile
import types
import unittest
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import execution_accounting as accounting
import execution_budget as budget
import execution_matrix as matrix
import execution_recovery as recovery


INITIAL_RECORDS = [
    {
        "vector_id": "base",
        "content": "base memory",
        "vector": [0.125, -0.25, 0.5],
        "metadata": {
            "freq": 7,
            "utility": 3,
            "time_created": "2026-10-24 10:00:00",
            "time_modified": "2026-10-24 11:00:00",
        },
    }
]
INDEX_CONFIG = {
    "backend": "es",
    "dimensions": 3,
    "similarity": "cosine",
    "number_of_shards": 1,
    "number_of_replicas": 0,
    "refresh_interval": "1s",
}


class InjectedCrash(BaseException):
    """Model abrupt worker death, which the in-process retry loop cannot catch."""


def is_subsequence(expected, observed):
    iterator = iter(observed)
    return all(any(candidate == item for candidate in iterator) for item in expected)


class FakeMemoryClient:
    def __init__(self, harness, attempt_id):
        self.harness = harness
        self.attempt_id = attempt_id
        self.records = []

    def snapshot(self):
        self.harness.events.append(
            (
                "snapshot",
                self.attempt_id,
                tuple(row["vector_id"] for row in self.records),
            )
        )
        return copy.deepcopy(self.records)

    def checkpoint(self):
        ids = tuple(sorted(row["vector_id"] for row in self.records))
        self.harness.events.append(("checkpoint", self.attempt_id, ids))
        return {
            "records": copy.deepcopy(self.records),
            "index_config": copy.deepcopy(INDEX_CONFIG),
        }

    def restore(self, payload):
        if self.records:
            raise AssertionError("Formal recovery must restore only into a fresh empty service")
        self.harness.restores.append(copy.deepcopy(payload))
        self.harness.events.append(
            (
                "restore",
                self.attempt_id,
                tuple(row["vector_id"] for row in payload["records"]),
            )
        )
        self.records = copy.deepcopy(payload["records"])
        return {
            "records_sha256": recovery.vector_records_sha256(self.records, 3),
            "index_config_sha256": recovery.json_sha256(payload["index_config"]),
        }


class FormalRecoveryHarness(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        temporary = Path(self.temporary.name)
        self.output_root = temporary / "outputs"
        self.run_root = self.output_root / "formal_fixture_run_0"
        self.run_root.mkdir(parents=True)
        self.policy_path = temporary / "formal-accounting.json"
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
                            "urls": ["https://chat.invalid/v1/chat/completions"],
                        },
                        "text-embedding-v4": {
                            "input": "0.07",
                            "output": "0",
                            "cached": "0",
                            "urls": ["https://embedding.invalid/v1/embeddings"],
                        },
                    },
                },
                sort_keys=True,
            )
            + "\n"
        )
        self.environment = patch.dict(
            os.environ,
            {accounting.ENVIRONMENT_KEY: str(self.policy_path)},
            clear=False,
        )
        self.environment.start()
        os.environ.pop(budget.ENVIRONMENT_KEY, None)
        self.events = []
        self.services = []
        self.restores = []
        self.task_attempts = Counter()
        self.task_attempt_kinds = {}
        self.rewards = {}
        self.task_hook = None
        self.aggregate_calls = 0
        self.manifest = self.make_manifest(["task-a", "task-b"])

    def tearDown(self):
        self.environment.stop()
        self.temporary.cleanup()

    def make_manifest(self, tasks):
        policy_sha256 = accounting.policy()[2]
        manifest = {
            "schema_version": 2,
            "status": "planned",
            "campaign": "formal-fixture",
            "dataset": "fixture_dataset",
            "task_ids": list(tasks),
            "dataset_sha256": "1" * 64,
            "arm": "cold_start",
            "repetition": 1,
            "run_base": "formal_fixture",
            "experiment_name": self.run_root.name,
            "appworld_root": str(Path(self.temporary.name) / "appworld"),
            "output_root": str(self.output_root),
            "model": "qwen3.8-flash",
            "embedding_model": "text-embedding-v4",
            "embedding_dimensions": 3,
            "batch_size": 1,
            "num_trials": 1,
            "use_memory_addition": True,
            "use_memory_deletion": True,
            "initial_pool": "fixture",
            "pool_sha256": "2" * 64,
            "source_commit": "2f37a15",
            "source_sha256": {"fixture.py": "3" * 64},
            "shared_logger_sha256": "4" * 64,
            "formal_accounting_sha256": policy_sha256,
        }
        matrix.write_json(self.run_root / "run_manifest.json", manifest)
        return manifest

    def fake_initialize_pool(self, client, manifest, artifacts):
        self.assertEqual(client.records, [])
        self.events.append(("initialize", client.attempt_id))
        client.records = copy.deepcopy(INITIAL_RECORDS)
        return client.snapshot()

    @contextmanager
    def fake_service(self, manifest, service_python, es_url, port, **kwargs):
        client = FakeMemoryClient(self, kwargs["task_attempt_id"])
        self.services.append(client)
        self.events.append(("service-open", kwargs["task_attempt_id"], kwargs["attempt_kind"]))
        try:
            yield client, "fake-token"
        finally:
            self.events.append(("service-close", kwargs["task_attempt_id"]))

    def write_call(self, task_id, physical_id, status):
        path = self.run_root / "tasks" / task_id / "logs/lm_calls.jsonl"
        matrix.write_jsonl(
            path,
            [
                {
                    "id": physical_id,
                    "output": {"usage": None},
                    "metadata": {"status": status, "root_task_id": task_id},
                }
            ],
        )

    def fake_task_runner(self, manifest, task_id, index, client, token, timeout, **kwargs):
        self.task_attempts[task_id] += 1
        attempt = self.task_attempts[task_id]
        self.task_attempt_kinds[(task_id, attempt)] = kwargs["attempt_kind"]
        self.events.append(("task", task_id, attempt, kwargs["attempt_kind"]))
        self.write_call(task_id, f"{task_id}-physical-{attempt}", "success")
        if self.task_hook is not None:
            self.task_hook(task_id, attempt, client, kwargs)
        client.records.append(
            {
                "vector_id": task_id,
                "content": f"committed memory for {task_id}",
                "vector": [float(index + 1), 0.25, -0.5],
                "metadata": {
                    "freq": attempt,
                    "utility": int(self.rewards.get(task_id, 1)),
                },
            }
        )
        return {"task_id": task_id, "after_score": self.rewards.get(task_id, 1)}

    def fake_finalizer(self, manifest, result, started, before, after, **kwargs):
        task_id = result["task_id"]
        self.events.append(("finalize", task_id, result["after_score"]))
        audit_path = self.run_root / "baseline_artifacts/reme" / task_id / "task_audit.json"
        matrix.write_json(
            audit_path,
            {
                "task_id": task_id,
                "official_reward": result["after_score"],
                "committed_task_attempt_id": kwargs["task_attempt_id"],
            },
        )
        return {"official_reward": result["after_score"]}

    def fake_aggregate(self, manifest):
        self.aggregate_calls += 1
        self.events.append(("aggregate", self.aggregate_calls))

    def execute(self, manifest=None, *, service_factory=None, task_runner=None, finalizer=None):
        manifest = manifest or self.manifest
        with (
            patch.object(matrix, "initialize_pool", side_effect=self.fake_initialize_pool),
            patch.object(matrix, "aggregate_run", side_effect=self.fake_aggregate),
            patch.object(matrix.time, "sleep", return_value=None),
            patch.object(
                matrix,
                "shared_logger",
                return_value=types.SimpleNamespace(redact_secrets=lambda value: value),
            ),
        ):
            return matrix.execute_run(
                manifest,
                None,
                None,
                service_factory=service_factory or self.fake_service,
                task_runner=task_runner or self.fake_task_runner,
                finalizer=finalizer or self.fake_finalizer,
            )

    def prefix(self, manifest=None):
        manifest = manifest or self.manifest
        return recovery.discover_committed_prefix(
            self.run_root,
            manifest["task_ids"],
            matrix.frozen_manifest_sha256(manifest),
            expected_dimensions=3,
        )

    def seed_complete_prefix(self, manifest=None):
        manifest = manifest or self.manifest
        claim = recovery.RunClaim.acquire(self.run_root, manifest["experiment_name"])
        try:
            matrix.publish_memory_checkpoint(
                manifest,
                claim,
                0,
                {
                    "records": copy.deepcopy(INITIAL_RECORDS),
                    "index_config": copy.deepcopy(INDEX_CONFIG),
                },
                None,
                [],
                {"task_attempt_id": "seed-initialization", "attempt_kind": "primary"},
            )
            records = copy.deepcopy(INITIAL_RECORDS)
            for index, task_id in enumerate(manifest["task_ids"]):
                records.append(
                    {
                        "vector_id": task_id,
                        "content": f"seed {task_id}",
                        "vector": [float(index + 1), 0.25, -0.5],
                        "metadata": {"freq": 1, "utility": 1},
                    }
                )
                matrix.publish_memory_checkpoint(
                    manifest,
                    claim,
                    index + 1,
                    {
                        "records": copy.deepcopy(records),
                        "index_config": copy.deepcopy(INDEX_CONFIG),
                    },
                    task_id,
                    manifest["task_ids"][: index + 1],
                    {"task_attempt_id": f"seed-{task_id}", "attempt_kind": "primary"},
                )
        finally:
            claim.release()


class FormalRecoveryExecutionTests(FormalRecoveryHarness):
    def test_checkpoint_zero_precedes_each_ordered_task_commit(self):
        result = self.execute()
        self.assertEqual(result["status"], "complete")
        normalized = []
        for event in self.events:
            if event[0] == "checkpoint":
                normalized.append(("checkpoint", event[2]))
            elif event[0] in {"task", "finalize"}:
                normalized.append((event[0], event[1]))
            elif event[0] in {"initialize", "aggregate"}:
                normalized.append((event[0],))
        self.assertTrue(
            is_subsequence(
                [
                    ("initialize",),
                    ("checkpoint", ("base",)),
                    ("task", "task-a"),
                    ("finalize", "task-a"),
                    ("checkpoint", ("base", "task-a")),
                    ("task", "task-b"),
                    ("finalize", "task-b"),
                    ("checkpoint", ("base", "task-a", "task-b")),
                    ("aggregate",),
                ],
                normalized,
            )
        )
        prefix = self.prefix()
        self.assertEqual(prefix.task_ids, ("task-a", "task-b"))
        self.assertIsNone(prefix.next_task_id)
        self.assertEqual(
            sorted(path.name for path in (self.run_root / recovery.COMMIT_DIRECTORY).glob("*.json")),
            ["000000.json", "000001.json", "000002.json"],
        )

    def test_crash_after_committed_task_resumes_without_replaying_it(self):
        def crash_on_second(task_id, attempt, client, kwargs):
            if task_id == "task-b" and attempt == 1:
                raise InjectedCrash("after task-a commit")

        self.task_hook = crash_on_second
        with self.assertRaisesRegex(InjectedCrash, "task-a commit"):
            self.execute()
        self.assertEqual(self.prefix().task_ids, ("task-a",))
        self.task_hook = None
        self.execute()
        self.assertEqual(self.task_attempts["task-a"], 1)
        self.assertEqual(self.task_attempts["task-b"], 2)
        self.assertEqual(self.prefix().task_ids, ("task-a", "task-b"))

    def test_crash_during_mutation_restores_exact_checkpoint_and_retries_only_uncommitted_task(
        self,
    ):
        observed_retry_state = []

        def crash_during_first_attempt(task_id, attempt, client, kwargs):
            if attempt == 1:
                client.records.append(
                    {
                        "vector_id": "dirty-uncommitted",
                        "content": "must disappear",
                        "vector": [9.0, 9.0, 9.0],
                        "metadata": {"freq": 99},
                    }
                )
                raise InjectedCrash("during memory mutation")
            observed_retry_state.append(copy.deepcopy(client.records))

        self.manifest = self.make_manifest(["task-a"])
        self.task_hook = crash_during_first_attempt
        with self.assertRaisesRegex(InjectedCrash, "memory mutation"):
            self.execute()
        self.assertEqual(self.prefix().task_ids, ())
        self.execute()
        self.assertEqual(observed_retry_state, [INITIAL_RECORDS])
        self.assertEqual(self.task_attempts, Counter({"task-a": 2}))
        self.assertEqual(self.restores[-1]["records"], INITIAL_RECORDS)

    def test_worker_replacement_counts_interrupted_attempt_as_recovery(self):
        self.manifest = self.make_manifest(["task-a"])

        def crash_once(task_id, attempt, client, kwargs):
            if attempt == 1:
                raise InjectedCrash("worker disappeared")

        self.task_hook = crash_once
        with self.assertRaisesRegex(InjectedCrash, "disappeared"):
            self.execute()
        self.execute()
        self.assertEqual(
            (
                recovery.retry_count(self.run_root, "task", "task-a"),
                self.task_attempt_kinds[("task-a", 2)],
            ),
            (1, "recovery"),
        )

    def test_crash_after_commit_before_manifest_update_uses_marker_on_resume(self):
        self.manifest = self.make_manifest(["task-a"])
        original_append = matrix._append_jsonl_synced
        with patch.object(
            matrix,
            "_append_jsonl_synced",
            side_effect=InjectedCrash("after commit marker"),
        ):
            with self.assertRaisesRegex(InjectedCrash, "commit marker"):
                self.execute()
        self.assertEqual(self.prefix().task_ids, ("task-a",))
        saved = json.loads((self.run_root / "run_manifest.json").read_text())
        self.assertEqual(saved.get("completed_task_ids"), [])
        service_count = len(self.services)
        task_count = sum(self.task_attempts.values())
        with patch.object(matrix, "_append_jsonl_synced", side_effect=original_append):
            self.execute()
        self.assertEqual(len(self.services), service_count)
        self.assertEqual(sum(self.task_attempts.values()), task_count)
        self.assertEqual(self.manifest["status"], "complete")

    def test_aggregation_only_resume_invokes_no_service_or_task(self):
        self.manifest = self.make_manifest(["task-a"])
        self.seed_complete_prefix()

        @contextmanager
        def forbidden_service(*args, **kwargs):
            raise AssertionError("aggregation-only resume launched a service")
            yield

        def forbidden_task(*args, **kwargs):
            raise AssertionError("aggregation-only resume replayed a task")

        result = self.execute(service_factory=forbidden_service, task_runner=forbidden_task)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(self.aggregate_calls, 1)
        self.assertEqual(self.services, [])
        self.assertEqual(self.task_attempts, Counter())

    def test_persistent_task_restart_counter_stops_after_two_restarts(self):
        self.manifest = self.make_manifest(["task-a"])

        def always_fail(task_id, attempt, client, kwargs):
            raise RuntimeError(f"injected task failure {attempt}")

        self.task_hook = always_fail
        with self.assertRaises(recovery.RetryLimitExceeded):
            self.execute()
        self.assertEqual(self.task_attempts, Counter({"task-a": 3}))
        self.assertEqual(recovery.retry_count(self.run_root, "task", "task-a"), 2)
        self.assertEqual(
            [self.task_attempt_kinds[("task-a", attempt)] for attempt in (1, 2, 3)],
            ["primary", "recovery", "recovery"],
        )

    def test_attempt_archive_and_merge_keep_failed_and_committed_rows(self):
        self.manifest = self.make_manifest(["task-a"])

        def fail_once(task_id, attempt, client, kwargs):
            if attempt == 1:
                self.write_call(task_id, "failed-physical", "error")
                raise RuntimeError("injected recoverable failure")

        self.task_hook = fail_once
        self.execute()
        saved = json.loads((self.run_root / "run_manifest.json").read_text())
        self.assertNotIn("error", saved)
        self.assertNotIn("error_type", saved)
        canonical = self.run_root / "tasks/task-a/logs/lm_calls.jsonl"
        rows = [json.loads(line) for line in canonical.read_text().splitlines()]
        self.assertEqual([row["id"] for row in rows], ["failed-physical", "task-a-physical-2"])
        archived = list(
            (self.run_root / recovery.RECOVERY_DIRECTORY / "attempts/task-a").glob("*/task_output/logs/lm_calls.jsonl")
        )
        self.assertEqual(len(archived), 1)
        checkpoint = self.prefix().last_checkpoint
        self.assertEqual(
            checkpoint.manifest["metadata"]["canonical_physical_call_ids"],
            ["failed-physical", "task-a-physical-2"],
        )

    def test_legitimate_benchmark_failure_is_committed_without_retry(self):
        self.manifest = self.make_manifest(["task-a"])
        self.rewards["task-a"] = 0
        result = self.execute()
        self.assertEqual(result["status"], "complete")
        self.assertEqual(self.task_attempts, Counter({"task-a": 1}))
        checkpoint = self.prefix().last_checkpoint
        self.assertEqual(checkpoint.manifest["metadata"]["official_reward"], 0)
        self.assertEqual(checkpoint.manifest["metadata"]["result"]["after_score"], 0)
        self.assertEqual(recovery.retry_count(self.run_root, "task", "task-a"), 0)


if __name__ == "__main__":
    unittest.main()
