import fcntl
import io
import json
import os
import tempfile
import time
import unittest
from contextlib import redirect_stderr
from pathlib import Path

import execution_coordinator as coordinator
import execution_recovery as recovery
from execution_scheduler import ARM_ORDER, CampaignQueue


HASH = "a" * 64


def make_manifest(root, dataset, arm, count, campaign="formal-test"):
    run_id = f"reme_{campaign}_{dataset}_{arm}_r01_qwen3.8-flash_run_0"
    output_root = root / "outputs"
    value = {
        "schema_version": 2,
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
        "formal_accounting_sha256": HASH,
        "status": "planned",
    }
    path = output_root / run_id / "run_manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    recovery.atomic_write_json(path, value)
    value["manifest_path"] = str(path)
    return value


def make_matrix(root):
    counts = {
        "intermediate_8h_test_normal": 5,
        "intermediate_8h_test_challenge": 8,
        "quick2h_test_normal_v2": 2,
        "quick2h_test_challenge_v2": 1,
    }
    return [make_manifest(root, dataset, arm, count) for dataset, count in counts.items() for arm in ARM_ORDER]


def manifest_prefix(run_root, manifest):
    return list(manifest.get("completed_task_ids", []))


def _record_fake_activity(path, delta, run_id):
    path = Path(path)
    with path.open("a+", encoding="utf-8") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        stream.seek(0)
        rows = [json.loads(line) for line in stream if line.strip()]
        active = (rows[-1]["active"] if rows else 0) + delta
        maximum = max([row["maximum"] for row in rows] + [active])
        stream.seek(0, os.SEEK_END)
        stream.write(json.dumps({"run": run_id, "delta": delta, "active": active, "maximum": maximum}) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def fake_runner(manifest, service_python, es_url, *, port, task_timeout, ray_temp_dir, claim):
    activity = Path(manifest["output_root"]) / "fake_activity.jsonl"
    _record_fake_activity(activity, 1, manifest["experiment_name"])
    try:
        time.sleep(0.03)
        manifest.update(status="complete", completed_task_ids=list(manifest["task_ids"]))
        manifest["fake_runtime"] = {
            "port": port,
            "ray_temp_dir": str(ray_temp_dir),
            "recovery_token": claim.token,
            "recovery_generation": claim.generation,
            "service_python": str(service_python),
            "es_url": es_url,
            "task_timeout": task_timeout,
        }
        recovery.atomic_write_json(
            Path(manifest["output_root"]) / manifest["experiment_name"] / "run_manifest.json", manifest
        )
        return manifest
    finally:
        _record_fake_activity(activity, -1, manifest["experiment_name"])


def flaky_first_runner(manifest, *args, **kwargs):
    marker = Path(manifest["output_root"]) / manifest["experiment_name"] / "fake_attempts.txt"
    attempts = int(marker.read_text()) if marker.exists() else 0
    marker.write_text(str(attempts + 1))
    if manifest["dataset"] == "quick2h_test_normal_v2" and manifest["arm"] == "fixed" and attempts == 0:
        manifest.update(status="incomplete", completed_task_ids=[])
        recovery.atomic_write_json(
            Path(manifest["output_root"]) / manifest["experiment_name"] / "run_manifest.json", manifest
        )
        raise OSError("injected worker-level interruption")
    return fake_runner(manifest, *args, **kwargs)


def fail_one_first_wave_runner(manifest, *args, **kwargs):
    if manifest["dataset"] == "quick2h_test_normal_v2" and manifest["arm"] == "fixed":
        manifest.update(status="incomplete", completed_task_ids=[])
        recovery.atomic_write_json(
            Path(manifest["output_root"]) / manifest["experiment_name"] / "run_manifest.json", manifest
        )
        raise OSError("injected persistent interruption")
    return fake_runner(manifest, *args, **kwargs)


class CoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.appworld = self.root / "appworld"
        (self.appworld / "experiments/code/common").mkdir(parents=True)
        (self.appworld / "experiments/code/common/lm_logger.py").write_text("# fake\n")
        self.manifests = make_matrix(self.appworld)
        self.queue_path = self.root / "campaign/queue.json"
        self.runtime_root = self.root / "campaign/runtime"

    def tearDown(self):
        self.temp.cleanup()

    def create_queue(self):
        return coordinator.create_or_load_queue(self.queue_path, self.manifests, self.runtime_root)

    def config(self):
        service_python = self.root / "service-python"
        service_python.write_text("#!/bin/sh\n")
        service_python.chmod(0o700)
        return coordinator.CoordinatorConfig(
            campaign="formal-test",
            queue_path=str(self.queue_path),
            runtime_root=str(self.runtime_root),
            appworld_root=str(self.appworld),
            service_python=str(service_python),
            es_url="http://127.0.0.1:9200",
            task_timeout=10,
            heartbeat_interval=0.01,
            poll_interval=0.01,
        )

    def test_create_or_load_requires_fresh_manifest_and_one_queue(self):
        queue = self.create_queue()
        self.assertEqual(len(queue.snapshot()["runs"]), 12)
        loaded = self.create_queue()
        self.assertEqual(loaded.snapshot(), queue.snapshot())
        self.queue_path.unlink()
        first = self.manifests[0]
        first["status"] = "incomplete"
        recovery.atomic_write_json(Path(first["manifest_path"]), first)
        with self.assertRaises(coordinator.CoordinatorError):
            self.create_queue()

    def test_first_wave_gate_requires_authoritative_commit_from_all_three(self):
        queue = self.create_queue()
        gate = coordinator.first_wave_state(queue, manifest_prefix)
        self.assertFalse(gate["released"])
        for manifest in self.manifests:
            if manifest["dataset"] == "quick2h_test_normal_v2":
                manifest["completed_task_ids"] = manifest["task_ids"][:1]
                recovery.atomic_write_json(Path(manifest["manifest_path"]), manifest)
        gate = coordinator.first_wave_state(queue, manifest_prefix)
        self.assertTrue(gate["released"])

    def test_stopped_first_wave_without_commit_blocks_campaign(self):
        queue = self.create_queue()
        claim = queue.claim_next("worker")
        queue.finish_claim(claim, "stopped", [])
        gate = coordinator.first_wave_state(queue, manifest_prefix)
        self.assertTrue(gate["blocked"])
        self.assertFalse(gate["released"])

    def test_coordinator_runs_twelve_cells_with_gate_and_three_workers(self):
        self.create_queue()
        summary = coordinator.Coordinator(
            self.config(), runner=fake_runner, prefix_reader=manifest_prefix, start_method="fork"
        ).run()
        self.assertEqual(summary["status"], "complete")
        self.assertEqual(summary["counts"]["complete"], 12)
        rows = [json.loads(line) for line in (self.appworld / "outputs/fake_activity.jsonl").read_text().splitlines()]
        self.assertLessEqual(max(row["maximum"] for row in rows), 3)
        events = [json.loads(line) for line in self.config().event_path.read_text().splitlines()]
        claims = [row for row in events if row["event"] == "run_claimed"]
        self.assertEqual(len(claims), 12)
        self.assertEqual(
            {row["claim"]["run_id"] for row in claims[:3]},
            {f"reme_formal-test_quick2h_test_normal_v2_{arm}_r01_qwen3.8-flash_run_0" for arm in ARM_ORDER},
        )
        self.assertTrue(all(row["gate_released"] for row in claims[3:]))
        runtime = [
            coordinator.read_json(Path(manifest["manifest_path"]))["fake_runtime"] for manifest in self.manifests
        ]
        self.assertTrue(all(row["port"] in (18101, 18102, 18103) for row in runtime))
        self.assertEqual(len({row["ray_temp_dir"] for row in runtime}), 12)

    def test_resumable_run_is_reclaimed_before_fourth_cell(self):
        self.create_queue()
        summary = coordinator.Coordinator(
            self.config(), runner=flaky_first_runner, prefix_reader=manifest_prefix, start_method="fork"
        ).run()
        self.assertEqual(summary["status"], "complete")
        events = [json.loads(line) for line in self.config().event_path.read_text().splitlines()]
        claims = [row["claim"]["run_id"] for row in events if row["event"] == "run_claimed"]
        fixed = "reme_formal-test_quick2h_test_normal_v2_fixed_r01_qwen3.8-flash_run_0"
        first_non_wave = next(index for index, run_id in enumerate(claims) if "quick2h_test_normal_v2" not in run_id)
        self.assertEqual(claims[:first_non_wave].count(fixed), 2)

    def test_persistent_first_wave_failure_stops_new_claims_and_reports(self):
        self.create_queue()
        summary = coordinator.Coordinator(
            self.config(), runner=fail_one_first_wave_runner, prefix_reader=manifest_prefix, start_method="fork"
        ).run()
        self.assertEqual(summary["status"], "incomplete")
        self.assertEqual(summary["counts"]["stopped"], 1)
        events = [json.loads(line) for line in self.config().event_path.read_text().splitlines()]
        claims = [row["claim"]["run_id"] for row in events if row["event"] == "run_claimed"]
        self.assertTrue(all("quick2h_test_normal_v2" in run_id for run_id in claims))
        stopped = [row for row in events if row["event"] == "run_finished" and row["status"] == "stopped"]
        self.assertEqual(stopped[0]["error_type"], "OSError")

    def test_coordinator_lease_is_exclusive(self):
        with coordinator.coordinator_lease(self.queue_path):
            with self.assertRaises(coordinator.CoordinatorError):
                with coordinator.coordinator_lease(self.queue_path):
                    pass

    def test_cli_requires_explicit_formal_acknowledgement_and_inputs(self):
        parser = coordinator.build_parser()
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parser.parse_args([])
        args = parser.parse_args(
            [
                "--appworld-root",
                str(self.appworld),
                "--campaign",
                "formal-test",
                "--env-file",
                str(self.root / "env"),
                "--formal-accounting",
                str(self.root / "policy.json"),
                "--service-python",
                str(self.root / "python"),
                "--es-url",
                "http://127.0.0.1:9200",
                "--task-timeout",
                "3600",
            ]
        )
        with self.assertRaisesRegex(coordinator.CoordinatorError, "execute-formal"):
            coordinator._validate_cli(args)
        service_python = self.root / "python"
        service_python.write_text("#!/bin/sh\n", encoding="utf-8")
        service_python.chmod(0o700)
        args.execute_formal = True
        _, runtime_root, _ = coordinator._validate_cli(args)
        self.assertEqual(runtime_root, coordinator.DEFAULT_RAY_RUNTIME_ROOT)
        args.runtime_root = Path("/tmp") / ("long" * 20)
        with self.assertRaisesRegex(coordinator.CoordinatorError, "AF_UNIX"):
            coordinator._validate_cli(args)

    def test_service_python_path_preserves_virtualenv_symlink(self):
        target = self.root / "base-python"
        target.write_text("#!/bin/sh\n", encoding="utf-8")
        target.chmod(0o700)
        venv = self.root / "venv/bin"
        venv.mkdir(parents=True)
        link = venv / "python"
        link.symlink_to(target)
        self.assertEqual(coordinator.service_python_path(link), link.absolute())
        self.assertNotEqual(coordinator.service_python_path(link), target.resolve())


if __name__ == "__main__":
    unittest.main()
