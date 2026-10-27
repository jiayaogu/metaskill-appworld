"""Provider-free failure-injection tests for durable run recovery state."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import execution_recovery as recovery


FROZEN_SHA256 = "a" * 64
INDEX_CONFIG = {
    "backend": "es",
    "dimensions": 3,
    "similarity": "cosine",
    "number_of_shards": 1,
    "number_of_replicas": 0,
}
VECTORS = [
    {
        "vector_id": "two",
        "content": "second",
        "vector": [0.25, -0.5, 1.0],
        "metadata": {"freq": 7, "utility": 3, "time_created": "2026-10-24 10:00:00"},
    },
    {
        "vector_id": "one",
        "content": "first",
        "vector": [0.0, 0.125, -1.5],
        "metadata": {"freq": 2, "utility": 1, "time_modified": "2026-10-24 11:00:00"},
    },
]


class RecoveryFixture(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "run"
        self.root.mkdir()

    def tearDown(self):
        self.temporary.cleanup()

    def checkpoint(self, claim, sequence=0, task_id=None, records=VECTORS):
        return recovery.create_checkpoint(
            self.root / recovery.CHECKPOINT_DIRECTORY / f"{sequence:06d}",
            sequence=sequence,
            task_id=task_id,
            records=records,
            dimensions=3,
            index_config=INDEX_CONFIG,
            owner_token=claim.token,
            owner_generation=claim.generation,
            metadata={
                "attempt_id": f"attempt-{sequence}",
                "official_reward": None if sequence == 0 else 1,
            },
        )

    def commit(self, claim, checkpoint, prefix, previous):
        record = recovery.make_commit_record(
            run_root=self.root,
            checkpoint=checkpoint,
            frozen_manifest_sha256=FROZEN_SHA256,
            previous_commit_sha256=previous,
            committed_task_ids=prefix,
        )
        path, published = recovery.publish_commit(self.root, record, claim)
        return path, published, recovery.file_sha256(path)


class AtomicWriteTests(RecoveryFixture):
    def test_atomic_json_and_jsonl_replace_complete_files(self):
        json_path = self.root / "state/state.json"
        jsonl_path = self.root / "state/events.jsonl"
        with patch.object(recovery.os, "fsync", wraps=os.fsync) as fsync:
            recovery.atomic_write_json(json_path, {"value": 1})
        self.assertGreaterEqual(fsync.call_count, 2)
        recovery.atomic_write_jsonl(jsonl_path, [{"event": 1}, {"event": 2}])
        self.assertEqual(json.loads(json_path.read_text()), {"value": 1})
        self.assertEqual(
            [json.loads(line) for line in jsonl_path.read_text().splitlines()],
            [{"event": 1}, {"event": 2}],
        )
        self.assertFalse(any(path.name.endswith(".tmp") for path in json_path.parent.iterdir()))

    def test_replace_failure_preserves_old_file_and_removes_temporary(self):
        path = self.root / "state.json"
        recovery.atomic_write_json(path, {"old": True})
        with patch.object(recovery.os, "replace", side_effect=OSError("injected replace failure")):
            with self.assertRaisesRegex(OSError, "injected"):
                recovery.atomic_write_json(path, {"new": True})
        self.assertEqual(json.loads(path.read_text()), {"old": True})
        self.assertFalse(any(candidate.name.endswith(".tmp") for candidate in self.root.iterdir()))

    def test_immutable_publication_is_idempotent_but_never_overwrites(self):
        path = self.root / "commits/000000.json"
        self.assertTrue(recovery.publish_immutable_json(path, {"sequence": 0}))
        self.assertFalse(recovery.publish_immutable_json(path, {"sequence": 0}))
        with self.assertRaises(recovery.CommitConflict):
            recovery.publish_immutable_json(path, {"sequence": 1})
        self.assertEqual(json.loads(path.read_text()), {"sequence": 0})

    def test_link_failure_publishes_nothing_and_removes_temporary(self):
        path = self.root / "commits/000000.json"
        with patch.object(recovery.os, "link", side_effect=OSError("injected link failure")):
            with self.assertRaisesRegex(OSError, "injected"):
                recovery.publish_immutable_json(path, {"sequence": 0})
        self.assertFalse(path.exists())
        self.assertEqual(list(path.parent.iterdir()), [])


class ClaimTests(RecoveryFixture):
    def test_claim_lock_generation_and_stale_owner_fencing(self):
        first = recovery.RunClaim.acquire(self.root, "run-1", owner_token="owner-one")
        self.assertEqual(first.generation, 1)
        with self.assertRaises(recovery.ClaimBusy):
            recovery.RunClaim.acquire(self.root, "run-1", owner_token="duplicate")
        first.abandon()

        second = recovery.RunClaim.acquire(self.root, "run-1", owner_token="owner-two")
        self.assertEqual(second.generation, 2)
        with self.assertRaises(recovery.StaleOwner):
            first.assert_current()
        self.assertEqual(second.assert_current()["owner_token"], "owner-two")
        second.release()
        with self.assertRaises(recovery.StaleOwner):
            second.assert_current()

        third = recovery.RunClaim.acquire(self.root, "run-1", owner_token="owner-three")
        self.assertEqual(third.generation, 3)
        third.release()

    def test_claim_state_cannot_be_reused_for_a_different_run(self):
        claim = recovery.RunClaim.acquire(self.root, "run-1")
        claim.release()
        with self.assertRaisesRegex(recovery.RecoveryError, "different run"):
            recovery.RunClaim.acquire(self.root, "run-2")


class CheckpointTests(RecoveryFixture):
    def test_checkpoint_preserves_exact_vectors_metadata_and_hashes(self):
        with recovery.RunClaim.acquire(self.root, "run-1", owner_token="owner") as claim:
            checkpoint = self.checkpoint(claim)
            self.assertEqual([row["vector_id"] for row in checkpoint.records], ["one", "two"])
            expected = {row["vector_id"]: row for row in VECTORS}
            self.assertEqual({row["vector_id"]: row for row in checkpoint.records}, expected)
            self.assertEqual(checkpoint.records_sha256, recovery.vector_records_sha256(VECTORS, 3))
            self.assertEqual(
                checkpoint.manifest["index_config_sha256"],
                recovery.json_sha256(INDEX_CONFIG),
            )
            loaded = recovery.load_checkpoint(checkpoint.path, expected_dimensions=3)
            self.assertEqual(loaded.records, checkpoint.records)
            self.assertEqual(loaded.manifest_sha256, checkpoint.manifest_sha256)

    def test_invalid_vectors_are_rejected(self):
        duplicate = [VECTORS[0], {**VECTORS[1], "vector_id": VECTORS[0]["vector_id"]}]
        for records in (
            duplicate,
            [{**VECTORS[0], "vector": [0.0]}],
            [{**VECTORS[0], "vector": [0.0, float("nan"), 1.0]}],
            [{**VECTORS[0], "metadata": []}],
        ):
            with (
                self.subTest(records=records),
                self.assertRaises(recovery.RecoveryError),
            ):
                recovery.normalize_vector_records(records, 3)

    def test_checkpoint_vector_tampering_is_detected(self):
        with recovery.RunClaim.acquire(self.root, "run-1") as claim:
            checkpoint = self.checkpoint(claim)
            vectors = checkpoint.path / "vectors.jsonl"
            vectors.write_text(vectors.read_text().replace("0.125", "0.126"))
            with self.assertRaisesRegex(recovery.RecoveryError, "file hash"):
                recovery.load_checkpoint(checkpoint.path)

    def test_checkpoint_rename_failure_leaves_no_partial_checkpoint(self):
        claim = recovery.RunClaim.acquire(self.root, "run-1")
        destination = self.root / recovery.CHECKPOINT_DIRECTORY / "000000"
        with patch.object(
            recovery.os,
            "rename",
            side_effect=OSError("injected checkpoint publication"),
        ):
            with self.assertRaisesRegex(OSError, "injected"):
                self.checkpoint(claim)
        self.assertFalse(destination.exists())
        self.assertEqual(list(destination.parent.iterdir()), [])
        claim.release()


class CommitPrefixTests(RecoveryFixture):
    def test_checkpoint_without_marker_is_uncommitted_then_marker_is_authoritative(
        self,
    ):
        with recovery.RunClaim.acquire(self.root, "run-1") as claim:
            checkpoint = self.checkpoint(claim)
            prefix = recovery.discover_committed_prefix(self.root, ["one"], FROZEN_SHA256, expected_dimensions=3)
            self.assertFalse(prefix.initialized)
            self.assertEqual(prefix.next_task_id, "one")

            marker, published, marker_hash = self.commit(claim, checkpoint, [], None)
            self.assertTrue(published)
            self.assertTrue(marker.is_file())
            prefix = recovery.discover_committed_prefix(self.root, ["one"], FROZEN_SHA256, expected_dimensions=3)
            self.assertTrue(prefix.initialized)
            self.assertEqual(prefix.last_commit_sha256, marker_hash)
            self.assertEqual(prefix.last_checkpoint.path, checkpoint.path)

    def test_worker_replacement_extends_valid_prefix_without_replaying_tasks(self):
        first = recovery.RunClaim.acquire(self.root, "run-1", owner_token="first")
        zero = self.checkpoint(first)
        _, _, previous = self.commit(first, zero, [], None)
        first.abandon()

        second = recovery.RunClaim.acquire(self.root, "run-1", owner_token="second")
        recovered = recovery.discover_committed_prefix(
            self.root, ["task-a", "task-b"], FROZEN_SHA256, expected_dimensions=3
        )
        self.assertEqual(recovered.task_ids, ())
        self.assertEqual(recovered.next_task_id, "task-a")
        one = self.checkpoint(second, 1, "task-a")
        _, _, previous = self.commit(second, one, ["task-a"], previous)
        second.release()

        final = recovery.discover_committed_prefix(
            self.root, ["task-a", "task-b"], FROZEN_SHA256, expected_dimensions=3
        )
        self.assertEqual(final.task_ids, ("task-a",))
        self.assertEqual(final.next_task_id, "task-b")
        self.assertEqual(final.owner_generation, 2)
        self.assertEqual(final.last_commit_sha256, previous)

    def test_stale_owner_cannot_publish_after_takeover(self):
        first = recovery.RunClaim.acquire(self.root, "run-1")
        checkpoint = self.checkpoint(first)
        record = recovery.make_commit_record(
            run_root=self.root,
            checkpoint=checkpoint,
            frozen_manifest_sha256=FROZEN_SHA256,
            previous_commit_sha256=None,
            committed_task_ids=[],
        )
        first.abandon()
        second = recovery.RunClaim.acquire(self.root, "run-1")
        with self.assertRaises(recovery.StaleOwner):
            recovery.publish_commit(self.root, record, first)
        with self.assertRaises(recovery.StaleOwner):
            recovery.publish_commit(self.root, record, second)
        second.release()

    def test_invalid_commit_cannot_poison_immutable_marker_path(self):
        with recovery.RunClaim.acquire(self.root, "run-1") as claim:
            checkpoint = self.checkpoint(claim)
            record = recovery.make_commit_record(
                run_root=self.root,
                checkpoint=checkpoint,
                frozen_manifest_sha256=FROZEN_SHA256,
                previous_commit_sha256=None,
                committed_task_ids=[],
            )
            record["checkpoint"]["records_sha256"] = "b" * 64
            with self.assertRaisesRegex(recovery.RecoveryError, "does not match"):
                recovery.publish_commit(self.root, record, claim)
            marker = self.root / recovery.COMMIT_DIRECTORY / "000000.json"
            self.assertFalse(marker.exists())

    def test_gap_wrong_task_and_checkpoint_tampering_are_rejected(self):
        with recovery.RunClaim.acquire(self.root, "run-1") as claim:
            zero = self.checkpoint(claim)
            marker, _, previous = self.commit(claim, zero, [], None)
            record = json.loads(marker.read_text())
            record["committed_task_ids"] = ["wrong"]
            recovery.atomic_write_json(marker, record)
            with self.assertRaisesRegex(recovery.RecoveryError, "frozen run"):
                recovery.discover_committed_prefix(self.root, ["task-a"], FROZEN_SHA256)

        with tempfile.TemporaryDirectory() as directory:
            other = Path(directory) / "run"
            other.mkdir()
            claim = recovery.RunClaim.acquire(other, "run-2")
            checkpoint = recovery.create_checkpoint(
                other / recovery.CHECKPOINT_DIRECTORY / "000001",
                sequence=1,
                task_id="task-a",
                records=VECTORS,
                dimensions=3,
                index_config=INDEX_CONFIG,
                owner_token=claim.token,
                owner_generation=claim.generation,
            )
            record = recovery.make_commit_record(
                run_root=other,
                checkpoint=checkpoint,
                frozen_manifest_sha256=FROZEN_SHA256,
                previous_commit_sha256="b" * 64,
                committed_task_ids=["task-a"],
            )
            recovery.publish_commit(other, record, claim)
            with self.assertRaisesRegex(recovery.RecoveryError, "gap"):
                recovery.discover_committed_prefix(other, ["task-a"], FROZEN_SHA256)
            claim.release()


class RetryCounterTests(RecoveryFixture):
    def test_retry_limit_cannot_be_configured_above_formal_cap(self):
        with self.assertRaisesRegex(ValueError, "between zero and 2"):
            recovery.retry_count(self.root, "task", max_restarts=3)

    def test_retry_counter_persists_across_worker_replacement_and_caps_at_two(self):
        first = recovery.RunClaim.acquire(self.root, "run-1", owner_token="first")
        self.assertEqual(
            recovery.record_infrastructure_restart(self.root, first, "task", "task-a"),
            1,
        )
        first.abandon()

        second = recovery.RunClaim.acquire(self.root, "run-1", owner_token="second")
        self.assertEqual(recovery.retry_count(self.root, "task", "task-a"), 1)
        self.assertEqual(
            recovery.record_infrastructure_restart(self.root, second, "task", "task-a"),
            2,
        )
        with self.assertRaises(recovery.RetryLimitExceeded):
            recovery.record_infrastructure_restart(self.root, second, "task", "task-a")
        self.assertEqual(recovery.retry_count(self.root, "task", "task-a"), 2)
        self.assertEqual(
            recovery.record_infrastructure_restart(self.root, second, "initialization"),
            1,
        )
        with self.assertRaises(recovery.StaleOwner):
            recovery.record_infrastructure_restart(self.root, first, "task", "task-b")
        second.release()

    def test_retry_state_replace_failure_does_not_consume_restart(self):
        claim = recovery.RunClaim.acquire(self.root, "run-1")
        with patch.object(recovery.os, "replace", side_effect=OSError("injected retry publication")):
            with self.assertRaisesRegex(OSError, "injected"):
                recovery.record_infrastructure_restart(self.root, claim, "initialization")
        self.assertEqual(recovery.retry_count(self.root, "initialization"), 0)
        claim.release()


if __name__ == "__main__":
    unittest.main()
