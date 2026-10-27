import json
import multiprocessing
import tempfile
import unittest
from pathlib import Path

import execution_scheduler as scheduler
import execution_recovery as recovery


HASH = "a" * 64


def manifest(root, dataset, arm, count, campaign="formal-test"):
    run_id = f"reme_{campaign}_{dataset}_{arm}_r01_qwen3.8-flash_run_0"
    output_root = root / "outputs"
    value = {
        "campaign": campaign,
        "dataset": dataset,
        "task_ids": [f"{dataset}-{index:03d}" for index in range(count)],
        "dataset_sha256": HASH,
        "arm": arm,
        "repetition": 1,
        "run_base": run_id.removesuffix("_run_0"),
        "experiment_name": run_id,
        "appworld_root": str(root),
        "output_root": str(output_root),
        "model": "qwen3.8-flash",
        "embedding_model": "text-embedding-v4",
        "embedding_dimensions": 1024,
        "batch_size": 1,
        "num_trials": 1,
        "use_memory_addition": arm != "fixed",
        "use_memory_deletion": arm != "fixed",
        "initial_pool": "empty" if arm == "cold_start" else "pool.jsonl",
        "pool_sha256": HASH,
        "source_commit": "2f37a15",
        "source_sha256": {"benchmark/appworld/execution_matrix.py": HASH},
        "shared_logger_sha256": HASH,
        "status": "planned",
    }
    path = output_root / run_id / "run_manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
    value["manifest_path"] = str(path)
    return value


def matrix(root):
    rows = []
    counts = {
        "intermediate_8h_test_normal": 57,
        "intermediate_8h_test_challenge": 138,
        "quick2h_test_normal_v2": 21,
        "quick2h_test_challenge_v2": 18,
    }
    for dataset in reversed(tuple(counts)):
        for arm in reversed(tuple(scheduler.ARM_ORDER)):
            rows.append(manifest(root, dataset, arm, counts[dataset]))
    return rows


def claim_worker(queue_path, worker_id, gate, results):
    gate.wait()
    claim = scheduler.CampaignQueue(queue_path).claim_next(worker_id)
    results.put(None if claim is None else claim.public_dict())


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.queue_path = self.root / "campaign" / "queue.json"

    def tearDown(self):
        self.temp.cleanup()

    def create(self, rows=None):
        return scheduler.CampaignQueue.create(
            self.queue_path,
            rows or matrix(self.root),
            self.root / "runtime",
            base_port=18101,
        )

    def test_order_starts_quick_normal_then_longest_with_fixed_ties(self):
        queue = self.create()
        order = [(run["dataset"], run["arm"]) for run in queue.snapshot()["runs"]]
        expected = []
        for dataset in (
            "quick2h_test_normal_v2",
            "intermediate_8h_test_challenge",
            "intermediate_8h_test_normal",
            "quick2h_test_challenge_v2",
        ):
            expected.extend((dataset, arm) for arm in ("fixed", "dynamic", "cold_start"))
        self.assertEqual(order, expected)

    def test_queue_is_atomic_persistent_and_refuses_replacement(self):
        queue = self.create()
        first = queue.snapshot()
        second = scheduler.CampaignQueue(self.queue_path).snapshot()
        self.assertEqual(first, second)
        self.assertEqual(first["max_concurrent_claims"], 3)
        self.assertEqual(list(self.queue_path.parent.glob(".*.tmp")), [])
        with self.assertRaises(FileExistsError):
            self.create()

    def test_concurrent_claims_are_exclusive_and_capped_at_three(self):
        self.create()
        context = multiprocessing.get_context("fork")
        gate = context.Event()
        results = context.Queue()
        workers = [
            context.Process(target=claim_worker, args=(self.queue_path, f"worker-{index}", gate, results))
            for index in range(8)
        ]
        for worker in workers:
            worker.start()
        gate.set()
        claimed = [results.get(timeout=10) for _ in workers]
        for worker in workers:
            worker.join(timeout=10)
            self.assertEqual(worker.exitcode, 0)
        claimed = [row for row in claimed if row is not None]
        self.assertEqual(len(claimed), 3)
        self.assertEqual({row["slot"] for row in claimed}, {0, 1, 2})
        self.assertEqual({row["port"] for row in claimed}, {18101, 18102, 18103})
        run_ids = {row["run_id"] for row in claimed}
        self.assertEqual(len(run_ids), 3)
        self.assertEqual(
            run_ids,
            {
                f"reme_formal-test_quick2h_test_normal_v2_{arm}_r01_qwen3.8-flash_run_0"
                for arm in ("fixed", "dynamic", "cold_start")
            },
        )
        self.assertEqual(len({row["ray_temp_dir"] for row in claimed}), 3)
        self.assertNotIn("token", claimed[0])

    def test_same_worker_reattaches_and_released_slot_advances_queue(self):
        queue = self.create()
        first = queue.claim_next("worker-a")
        self.assertEqual(queue.claim_next("worker-a"), first)
        second = queue.claim_next("worker-b")
        third = queue.claim_next("worker-c")
        self.assertIsNone(queue.claim_next("worker-d"))
        first_tasks = next(run["task_ids"] for run in queue.snapshot()["runs"] if run["run_id"] == first.run_id)
        queue.finish_claim(first, "complete", first_tasks)
        fourth = queue.claim_next("worker-d")
        self.assertEqual(fourth.slot, first.slot)
        self.assertEqual(fourth.port, first.port)
        self.assertNotEqual(fourth.ray_temp_dir, first.ray_temp_dir)
        fourth_run = next(run for run in queue.snapshot()["runs"] if run["run_id"] == fourth.run_id)
        self.assertEqual((fourth_run["dataset"], fourth_run["arm"]), ("intermediate_8h_test_challenge", "fixed"))
        self.assertTrue(queue.validate_claim(second))
        self.assertTrue(queue.validate_claim(third))

    def test_ray_temp_paths_are_short_and_unique_for_unix_sockets(self):
        queue = scheduler.CampaignQueue.create(
            self.queue_path,
            matrix(self.root),
            Path("/tmp/rr"),
        )
        claims = [queue.claim_next(f"worker-{index}") for index in range(3)]
        paths = [claim.ray_temp_dir for claim in claims]
        self.assertEqual(len(set(paths)), 3)
        self.assertTrue(all(len(str(Path(path) / ("x" * 8))) <= 39 for path in paths))

    def test_generation_token_fences_replaced_worker(self):
        queue = self.create()
        old = queue.claim_next("worker-old")
        replacement = queue.replace_claim(old, "worker-new")
        self.assertEqual(replacement.generation, old.generation + 1)
        self.assertFalse(queue.validate_claim(old))
        self.assertTrue(queue.validate_claim(replacement))
        with self.assertRaises(scheduler.StaleClaim):
            queue.heartbeat(old)
        with self.assertRaises(scheduler.StaleClaim):
            queue.finish_claim(old, "resumable")

    def test_optional_recovery_claim_reuses_queue_owner_token(self):
        queue = self.create()
        claim = queue.claim_next("worker-a")
        with queue.acquire_recovery_claim(claim) as run_claim:
            self.assertEqual(run_claim.token, claim.token)
            self.assertEqual(str(run_claim.run_root), claim.run_root)
            with self.assertRaises(recovery.ClaimBusy):
                queue.acquire_recovery_claim(claim)

    def test_frozen_manifest_verification_detects_source_change(self):
        rows = matrix(self.root)
        queue = self.create(rows)
        run_id = queue.snapshot()["runs"][0]["run_id"]
        queue.verify_manifest(run_id)
        path = Path(queue.snapshot()["runs"][0]["manifest_path"])
        changed = json.loads(path.read_text())
        changed["source_sha256"]["benchmark/appworld/execution_matrix.py"] = "b" * 64
        path.write_text(json.dumps(changed))
        with self.assertRaises(scheduler.FrozenManifestMismatch):
            queue.verify_manifest(run_id)
        with self.assertRaises(scheduler.FrozenManifestMismatch):
            queue.claim_next("worker-a")

    def test_rebuild_from_manifests_uses_committed_prefix_and_preserves_claims(self):
        rows = matrix(self.root)
        queue = self.create(rows)
        active = queue.claim_next("worker-a")
        data = queue.snapshot()
        complete_run = data["runs"][1]
        complete_path = Path(complete_run["manifest_path"])
        complete_manifest = json.loads(complete_path.read_text())
        complete_manifest.update(status="complete", completed_task_ids=complete_run["task_ids"])
        complete_path.write_text(json.dumps(complete_manifest))
        active_path = Path(active.manifest_path)
        active_manifest = json.loads(active_path.read_text())
        active_manifest.update(status="incomplete", completed_task_ids=active_manifest["task_ids"][:1])
        active_path.write_text(json.dumps(active_manifest))

        rebuilt = queue.rebuild_from_manifests(preserve_claims=True)
        by_id = {run["run_id"]: run for run in rebuilt["runs"]}
        self.assertEqual(by_id[active.run_id]["status"], "claimed")
        self.assertEqual(by_id[active.run_id]["completed_task_ids"], active_manifest["task_ids"][:1])
        self.assertEqual(by_id[complete_run["run_id"]]["status"], "complete")

        rebuilt = queue.rebuild_from_manifests(preserve_claims=False)
        by_id = {run["run_id"]: run for run in rebuilt["runs"]}
        self.assertEqual(by_id[active.run_id]["status"], "resumable")
        self.assertIsNone(by_id[active.run_id]["claim"])

    def test_rebuild_rejects_non_prefix_commit_history(self):
        queue = self.create()

        def invalid(run):
            return {"status": "resumable", "completed_task_ids": [run["task_ids"][1]]}

        with self.assertRaises(scheduler.QueueError):
            queue.rebuild_statuses(invalid, preserve_claims=False)


if __name__ == "__main__":
    unittest.main()
