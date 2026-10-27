"""Offline regression checks; never contact providers or a memory service."""

import tempfile
import unittest
import copy
import json
import os
import types
from unittest.mock import patch
from contextlib import contextmanager
from pathlib import Path

import execution_matrix as matrix
from execution_audit import pool_state, verify_mutation, checked_response


class MatrixTests(unittest.TestCase):
    def test_retry_archive_keeps_only_its_attempt_calls(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            task_log = root / "tasks/task/logs/lm_calls.jsonl"
            matrix.write_jsonl(
                task_log,
                [
                    {"id": "a1", "metadata": {"extra": {"task_attempt_id": "attempt-1"}}},
                    {"id": "a2", "metadata": {"extra": {"task_attempt_id": "attempt-2"}}},
                ],
            )
            archived = matrix.archive_partial_task(root, "task", "attempt-2")
            rows = [json.loads(line) for line in (archived / "logs/lm_calls.jsonl").read_text().splitlines()]
            self.assertEqual([row["id"] for row in rows], ["a2"])

    def test_retry_archive_rejects_mixed_attempt_attribution(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            task_log = root / "tasks/task/logs/lm_calls.jsonl"
            matrix.write_jsonl(
                task_log,
                [
                    {"id": "legacy", "metadata": {}},
                    {"id": "current", "metadata": {"extra": {"task_attempt_id": "attempt-2"}}},
                ],
            )
            with self.assertRaisesRegex(RuntimeError, "mixes attributed and unattributed"):
                matrix.archive_partial_task(root, "task", "attempt-2")

    def test_merge_attempt_logs_can_validate_without_publishing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "baseline_artifacts/reme/recovery/attempts/task/a1/task_output/logs/lm_calls.jsonl"
            current = root / "tasks/task/logs/lm_calls.jsonl"
            matrix.write_jsonl(archive, [{"id": "one", "metadata": {}}])
            matrix.write_jsonl(current, [{"id": "two", "metadata": {}}])
            rows = matrix.merge_attempt_call_logs(root, "task", write=False)
            self.assertEqual([row["id"] for row in rows], ["one", "two"])
            self.assertEqual([json.loads(line)["id"] for line in current.read_text().splitlines()], ["two"])
            matrix.merge_attempt_call_logs(root, "task")
            self.assertEqual([json.loads(line)["id"] for line in current.read_text().splitlines()], ["one", "two"])

    def test_service_retry_archives_prior_log_without_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            artifacts = Path(directory) / "baseline_artifacts/reme"
            artifacts.mkdir(parents=True)
            current = artifacts / "service.log"
            current.write_text("first attempt\n", encoding="utf-8")
            self.assertEqual(matrix.prepare_service_log(artifacts, "task/a2"), current)
            archive = artifacts / "recovery/service_logs/before-task_a2.log"
            self.assertEqual(archive.read_text(encoding="utf-8"), "first attempt\n")
            self.assertFalse(current.exists())
            current.write_text("second attempt\n", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                matrix.prepare_service_log(artifacts, "task/a2")
            self.assertEqual(current.read_text(encoding="utf-8"), "second attempt\n")

    def test_closed_evaluator_cleans_owned_cache_on_success_and_failure(self):
        with (
            patch("appworld.apps.model_lib.CachedDBHandler.is_empty", return_value=True) as empty,
            patch("appworld.apps.model_lib.CachedDBHandler.reset") as reset,
            patch("appworld.evaluator.evaluate_task", return_value=("tracker", "report")) as evaluate,
        ):
            self.assertEqual(matrix.evaluate_closed_task("one", "test"), ("tracker", "report"))
            reset.assert_called_once()
            evaluate.side_effect = RuntimeError("injected evaluator failure")
            with self.assertRaisesRegex(RuntimeError, "injected"):
                matrix.evaluate_closed_task("one", "test")
            self.assertEqual(reset.call_count, 2)
            empty.return_value = False
            with self.assertRaisesRegex(RuntimeError, "unexpected open"):
                matrix.evaluate_closed_task("one", "test")
            self.assertEqual(reset.call_count, 2)

    def test_dashscope_embedding_mapping_default_and_override(self):
        original = {
            "OPENAI_API_KEY": "chat-test",
            "OPENAI_BASE_URL": "https://chat.invalid/v1",
            "DASHSCOPE_API_KEY": "embedding-test",
        }
        mapped = matrix.service_environment(original)
        self.assertEqual(mapped["LLM_API_KEY"], "chat-test")
        self.assertEqual(mapped["EMBEDDING_API_KEY"], "embedding-test")
        self.assertEqual(mapped["EMBEDDING_BASE_URL"], "https://dashscope.aliyuncs.com/compatible-mode/v1")
        mapped = matrix.service_environment({**original, "DASHSCOPE_BASE_URL": "https://embedding.invalid/v1"})
        self.assertEqual(mapped["EMBEDDING_BASE_URL"], "https://embedding.invalid/v1")
        mapped = matrix.service_environment(
            {**original, "EMBEDDING_API_KEY": "explicit", "EMBEDDING_BASE_URL": "explicit-url"}
        )
        self.assertEqual(mapped["EMBEDDING_API_KEY"], "explicit")
        self.assertEqual(mapped["EMBEDDING_BASE_URL"], "explicit-url")

    def test_selected_dotenv_replaces_stale_roles_without_leaking_other_settings(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            path = Path(directory) / ".env"
            path.write_text(
                "OPENAI_API_KEY=chat-test\nOPENAI_BASE_URL=https://chat.invalid/v1\nDASHSCOPE_API_KEY=embed-test\nUNRELATED=do-not-load\n"
            )
            os.environ["EMBEDDING_API_KEY"] = "stale"
            matrix.load_provider_environment(path)
            self.assertEqual(os.environ["EMBEDDING_API_KEY"], "embed-test")
            self.assertNotIn("UNRELATED", os.environ)

    def test_service_environment_maps_openai_without_mutating_caller(self):
        original = {"OPENAI_API_KEY": "test-only", "OPENAI_BASE_URL": "http://127.0.0.1:1/v1"}
        mapped = matrix.service_environment(original)
        for prefix in ("LLM", "EMBEDDING"):
            self.assertEqual(mapped[f"{prefix}_API_KEY"], original["OPENAI_API_KEY"])
            self.assertEqual(mapped[f"{prefix}_BASE_URL"], original["OPENAI_BASE_URL"])
        self.assertNotIn("LLM_API_KEY", original)

    def test_service_environment_preserves_explicit_roles_and_rejects_missing_settings(self):
        original = {
            "OPENAI_API_KEY": "test-only",
            "OPENAI_BASE_URL": "http://127.0.0.1:1/v1",
            "LLM_API_KEY": "role-specific-test-only",
            "EMBEDDING_BASE_URL": "http://127.0.0.1:2/v1",
        }
        mapped = matrix.service_environment(original)
        self.assertEqual(mapped["LLM_API_KEY"], original["LLM_API_KEY"])
        self.assertEqual(mapped["EMBEDDING_BASE_URL"], original["EMBEDDING_BASE_URL"])
        with self.assertRaisesRegex(ValueError, "API_KEY"):
            matrix.service_environment({})
        with self.assertRaisesRegex(ValueError, "BASE_URL"):
            matrix.service_environment({"OPENAI_API_KEY": "test-only"})

    def test_matrix(self):
        manifests = matrix.build_matrix(matrix.DEFAULT_APPWORLD_ROOT, "offline-test")
        self.assertEqual(len(manifests), 12)
        self.assertEqual(sum(len(m["task_ids"]) for m in manifests), 702)
        self.assertEqual(len({m["experiment_name"] for m in manifests}), 12)
        self.assertEqual({m["repetition"] for m in manifests}, {1})
        self.assertEqual(
            {(m["dataset"], m["arm"]) for m in manifests},
            {(dataset, arm) for dataset in matrix.DATASETS for arm in matrix.ARMS},
        )
        for m in manifests:
            self.assertEqual(m["use_memory_addition"], m["arm"] != "fixed")
            self.assertEqual(m["use_memory_deletion"], m["arm"] != "fixed")
            self.assertEqual(m["initial_pool"] == "empty", m["arm"] == "cold_start")
            self.assertEqual(m["batch_size"], 1)

    def test_service_launch_isolates_workspace_and_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = {"output_root": directory, "experiment_name": "test-run", "task_ids": []}

            def identity(*args):
                return {
                    "metadata": {
                        "collection": manifest["collection"],
                        "backend": "es",
                        "model": "qwen3.8-flash",
                        "embedding_model": "text-embedding-v4",
                        "dimensions": 1024,
                    }
                }

            with (
                patch.dict(os.environ, {"OPENAI_API_KEY": "test-only", "OPENAI_BASE_URL": "http://localhost:1"}),
                patch("subprocess.Popen") as popen,
                patch("requests.get") as health,
                patch.object(matrix, "MemoryClient") as client,
            ):
                popen.return_value.poll.return_value = None
                health.return_value.status_code = 200
                client.return_value.call.side_effect = identity
                with matrix.isolated_service(manifest, "/test/python", "http://localhost:9200", 18002):
                    pass
                command = popen.call_args.args[0]
                workspace = Path(directory) / "test-run/baseline_artifacts/reme/service_workspace"
                self.assertEqual(popen.call_args.kwargs["cwd"], workspace)
                self.assertEqual(command[3], str(workspace))
                self.assertIn("working_dir=sys.argv[1]", command[2])
                self.assertIn("enable_load_env=False", command[2])
                self.assertEqual(popen.call_args.kwargs["env"]["PYTHONPATH"], str(matrix.SOURCE_ROOT))
                popen.return_value.terminate.assert_called_once()

    def test_loader_order_and_campaign_validation(self):
        with self.assertRaises(ValueError):
            matrix.build_matrix(matrix.DEFAULT_APPWORLD_ROOT, "../escape")
        with self.assertRaises(ValueError):
            matrix.build_matrix(matrix.DEFAULT_APPWORLD_ROOT, "test", lambda _: [])

    def test_pool_reset_and_cold_start(self):
        source = [json.loads(line) for line in matrix.POOL.read_text().splitlines() if line.strip()]

        class Client:
            def __init__(self):
                self.rows, self.imports = [], 0

            def snapshot(self):
                return copy.deepcopy(self.rows)

            def call(self, endpoint, payload):
                self.imports += 1
                self.rows = copy.deepcopy(source)

        with tempfile.TemporaryDirectory() as temporary:
            for arm in matrix.ARMS:
                for _ in matrix.DATASETS:
                    client, manifest = Client(), {"arm": arm}
                    matrix.initialize_pool(client, manifest, Path(temporary))
                    self.assertEqual(client.imports, int(arm != "cold_start"))
                    self.assertEqual(len(client.rows), 0 if arm == "cold_start" else 207)
                    if client.rows:
                        client.rows[0]["content"] = "changed by prior run"
            client = Client()
            client.rows = source[:1]
            with self.assertRaisesRegex(RuntimeError, "refusing to clear"):
                matrix.initialize_pool(client, {"arm": "dynamic"}, Path(temporary))
            self.assertEqual(client.imports, 0)

    def test_truncated_import_rejected(self):
        class Client:
            rows = []

            def snapshot(self):
                return self.rows

            def call(self, *args):
                self.rows = [json.loads(matrix.POOL.read_text().splitlines()[0])]

        with tempfile.TemporaryDirectory() as directory, self.assertRaises(RuntimeError):
            matrix.initialize_pool(Client(), {"arm": "fixed"}, Path(directory))

    def test_mutation_checks(self):
        rows = [
            {"memory_id": "one", "content": "a", "when_to_use": "b", "metadata": {"freq": 6, "utility": 3}},
            {"memory_id": "two", "content": "c", "when_to_use": "d", "metadata": {"freq": 5, "utility": 2}},
        ]
        payload = {"freq_threshold": 5, "utility_threshold": 0.5}
        verify_mutation("delete_task_memory", payload, {}, rows, rows[:1])
        with self.assertRaises(RuntimeError):
            verify_mutation("delete_task_memory", payload, {}, rows, [])
        with self.assertRaises(RuntimeError):
            verify_mutation("summary_task_memory", {}, {}, rows, [])
        with self.assertRaises(RuntimeError):
            verify_mutation("record_task_memory", {"memory_list": rows, "update_utility": True}, {}, rows, rows)
        with self.assertRaises(RuntimeError):
            verify_mutation("add_task_memory", {"memory_list": rows}, {}, [], [])
        self.assertEqual(pool_state(rows)["content_sha256"], pool_state(list(reversed(rows)))["content_sha256"])

    def test_http_200_failure_rejected(self):
        class Response:
            def raise_for_status(self):
                pass

            def json(self):
                return {"success": False}

        with self.assertRaises(RuntimeError):
            checked_response(Response())

    def test_failure_stops_before_next_task_and_closes_service(self):
        os.environ["APPWORLD_LM_LOGGER_MODULE_PATH"] = str(
            matrix.DEFAULT_APPWORLD_ROOT / "experiments/code/common/lm_logger.py"
        )
        calls = []

        class Client:
            def snapshot(self):
                return []

        @contextmanager
        def service(*args):
            try:
                yield Client(), "token"
            finally:
                calls.append("closed")

        def runner(manifest, task, *args):
            calls.append(task)
            raise RuntimeError("injected Ray failure")

        with tempfile.TemporaryDirectory() as directory:
            manifest = {
                "output_root": directory,
                "experiment_name": "test_run_0",
                "arm": "cold_start",
                "status": "planned",
                "task_ids": ["one", "two"],
            }
            with self.assertRaisesRegex(RuntimeError, "injected"):
                matrix.execute_run(manifest, None, None, service_factory=service, task_runner=runner)
            saved = json.loads((Path(directory) / "test_run_0/run_manifest.json").read_text())
            self.assertEqual(saved["status"], "incomplete")
            self.assertEqual(saved["completed_task_ids"], [])
        self.assertEqual(calls, ["one", "closed"])

    def test_output_collision_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, count in matrix.DATASETS.items():
                file = root / "data/datasets" / f"{name}.txt"
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_text("\n".join(f"task_{n}" for n in range(count)))
            first = matrix.plan_matrix(root, "test")
            with self.assertRaises(FileExistsError):
                matrix.plan_matrix(root, "test")
            self.assertEqual(len(list(root.glob("experiments/outputs/*/run_manifest.json"))), 12)
            self.assertEqual(first[0]["task_ids"][1], "task_1")

    def test_finalizer_validates_real_dump_shape_reward_and_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = {
                "output_root": directory,
                "experiment_name": "test_run_0",
                "arm": "fixed",
                "use_memory_addition": False,
                "use_memory_deletion": False,
            }
            task_dir = Path(directory) / "test_run_0/tasks/task"
            required = [
                "logs/api_calls.jsonl",
                "logs/environment_io.md",
                "logs/loggger.log",
                "evaluation/report.md",
                "evaluation/version.txt",
                "version/code.txt",
                "version/data.txt",
            ]
            for name in required:
                path = task_dir / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("Overall Stats\nPasses\nFails" if name.endswith("report.md") else "")
            for name in ("dbs", "checkpoints", "misc"):
                (task_dir / name).mkdir(exist_ok=True)
            for app in (
                "admin",
                "amazon",
                "api_docs",
                "file_system",
                "gmail",
                "phone",
                "simple_note",
                "splitwise",
                "spotify",
                "supervisor",
                "todoist",
                "venmo",
            ):
                (task_dir / "dbs" / f"{app}.jsonl").write_text(
                    json.dumps(["INSERT INTO x VALUES (?)", [1], False]) + "\n"
                )
            (task_dir / "dbs/model_hashes.json").write_text("{}")
            matrix.write_jsonl(
                task_dir / "logs/lm_calls.jsonl",
                [
                    {
                        "id": "physical",
                        "output": {"usage": None},
                        "metadata": {"phase": "executor", "status": "success", "root_task_id": "task"},
                    }
                ],
            )
            events_path = Path(directory) / "test_run_0/baseline_artifacts/reme/task/memory_events.jsonl"
            matrix.write_jsonl(
                events_path,
                [
                    {"endpoint": endpoint, "status": "success", "started_at": "2026-10-24T01"}
                    for endpoint in ["retrieve_task_memory", "record_task_memory"]
                ],
            )
            result = {"task_id": "task", "after_score": 1}
            with patch(
                "appworld.evaluator.evaluate_task", return_value=(types.SimpleNamespace(passes=[1], failures=[]), "")
            ):
                audit = matrix.finalize_task(manifest, result, "2026-10-24T00", [], [])
                self.assertEqual(audit["official_reward"], 1)
                self.assertTrue((events_path.parent / "task_audit.json").exists())
                self.assertEqual(json.loads((task_dir / "misc/cost.txt").read_text())["status"], "unavailable")
                with self.assertRaisesRegex(RuntimeError, "reward"):
                    matrix.finalize_task(manifest, {**result, "after_score": 0}, "2026-10-24T00", [], [])
                (task_dir / "dbs/admin.jsonl").write_text('{"fake": "row"}\n')
                with self.assertRaisesRegex(ValueError, "DB row"):
                    matrix.finalize_task(manifest, result, "2026-10-24T00", [], [])

    def test_sequential_commit_precedes_next_submission_and_aggregate(self):
        events = []

        class Client:
            def snapshot(self):
                return []

        @contextmanager
        def service(*args):
            yield Client(), "token"

        def runner(manifest, task, *args):
            events.append("submit:" + task)
            return {"task_id": task, "after_score": 0}

        def finalizer(manifest, result, *args):
            task = result["task_id"]
            events.append("commit:" + task)
            matrix.write_json(
                Path(manifest["output_root"]) / manifest["experiment_name"] / "tasks" / task / "misc/cost.txt",
                {"status": "unavailable"},
            )

        with tempfile.TemporaryDirectory() as directory:
            manifest = {
                "output_root": directory,
                "experiment_name": "test_run_0",
                "arm": "cold_start",
                "status": "planned",
                "task_ids": ["one", "two"],
                "dataset": "fixture",
            }

            def evaluate(**kwargs):
                events.append("aggregate")
                self.assertEqual(kwargs["experiment_name"], "test_run_0")
                self.assertEqual(kwargs["dataset_name"], "fixture")
                root = Path(directory) / "test_run_0/evaluations"
                matrix.write_json(root / "fixture.json", {})
                (root / "fixture.txt").write_text("official fixture")

            with patch("appworld.evaluator.evaluate_dataset", side_effect=evaluate):
                matrix.execute_run(
                    manifest, None, None, service_factory=service, task_runner=runner, finalizer=finalizer
                )
            self.assertEqual(manifest["status"], "complete")
            self.assertTrue((Path(directory) / "test_run_0/baseline_artifacts/reme/memory_final.jsonl").is_file())
        self.assertEqual(events, ["submit:one", "commit:one", "submit:two", "commit:two", "aggregate"])


if __name__ == "__main__":
    unittest.main()
