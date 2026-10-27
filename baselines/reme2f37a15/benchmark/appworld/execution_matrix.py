"""Isolated, ordered execution of the approved source-pinned ReMe comparison.

Planning is provider-free. Execution is explicitly selected and uses the original
Ray actor, one task per batch, with an independently owned service per run.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from execution_audit import MemoryClient, now, pool_state, shared_logger
import execution_accounting
import execution_budget
import execution_recovery

SOURCE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_APPWORLD_ROOT = SOURCE_ROOT.parent / "ace" / "ace-appworld"
DATASETS = {
    "intermediate_8h_test_normal": 57,
    "intermediate_8h_test_challenge": 138,
    "quick2h_test_normal_v2": 21,
    "quick2h_test_challenge_v2": 18,
}
ARMS = {"fixed": (False, False), "dynamic": (True, True), "cold_start": (True, True)}
REPETITIONS = 1
POOL = SOURCE_ROOT / "docs/library/paper_data/task/appworld_qwen3_8b.jsonl"
POOL_SHA256 = "a1cbe575b1f6dc98b35908b4f4b62796d41cdddcb023dd043c96e2abaeac7921"


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    execution_recovery.atomic_write_json(path, value)


def configure_appworld(root):
    root = Path(root).resolve(strict=True)
    os.environ["APPWORLD_ROOT"] = str(root)
    from appworld.common.path_store import path_store

    path_store.update_root(str(root))
    if Path(path_store.experiment_outputs).resolve() != root / "experiments/outputs":
        raise RuntimeError("Runner and AppWorld output roots disagree")
    return root


def build_matrix(root, campaign, loader=None):
    root = Path(root).resolve(strict=True)
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,39}", campaign):
        raise ValueError("Campaign must be a short lowercase path-safe identifier")
    if file_hash(POOL) != POOL_SHA256:
        raise ValueError("Bundled pool bytes differ from the approved source")
    formal_accounting_sha256 = None
    if os.environ.get(execution_accounting.ENVIRONMENT_KEY):
        formal_accounting_sha256 = execution_accounting.policy()[2]
    manifests = []
    for dataset, count in DATASETS.items():
        dataset_file = root / "data/datasets" / f"{dataset}.txt"
        ids = [line.strip() for line in dataset_file.read_text().splitlines() if line.strip()]
        if len(ids) != count or len(set(ids)) != count:
            raise ValueError(f"Unexpected task count or duplicate task in {dataset}")
        if any(not re.fullmatch(r"[a-zA-Z0-9_-]+", task) for task in ids):
            raise ValueError("Invalid task ID")
        if loader is not None and list(loader(dataset)) != ids:
            raise ValueError(f"AppWorld loader changed file order for {dataset}")
        for arm, (addition, deletion) in ARMS.items():
            for repetition in range(1, REPETITIONS + 1):
                base = f"reme_{campaign}_{dataset}_{arm}_r{repetition:02d}_qwen3.8-flash"
                manifests.append(
                    {
                        "schema_version": 2,
                        "status": "planned",
                        "campaign": campaign,
                        "dataset": dataset,
                        "task_ids": ids,
                        "dataset_sha256": file_hash(dataset_file),
                        "arm": arm,
                        "repetition": repetition,
                        "run_base": base,
                        "experiment_name": base + "_run_0",
                        "appworld_root": str(root),
                        "output_root": str(root / "experiments/outputs"),
                        "model": "qwen3.8-flash",
                        "embedding_model": "text-embedding-v4",
                        "embedding_dimensions": 1024,
                        "batch_size": 1,
                        "max_workers": 16,
                        "num_trials": 1,
                        "use_memory_addition": addition,
                        "use_memory_deletion": deletion,
                        "initial_pool": "empty" if arm == "cold_start" else str(POOL),
                        "pool_sha256": POOL_SHA256,
                        "source_commit": "2f37a15",
                        "source_sha256": {
                            str(p.relative_to(SOURCE_ROOT)): file_hash(p)
                            for p in (
                                list((SOURCE_ROOT / "reme").rglob("*.py"))
                                + list((SOURCE_ROOT / "benchmark/appworld").glob("*.py"))
                                + [SOURCE_ROOT / "reme/config/service.yaml"]
                            )
                        },
                        "shared_logger_sha256": (
                            file_hash(root / "experiments/code/common/lm_logger.py")
                            if (root / "experiments/code/common/lm_logger.py").exists()
                            else None
                        ),
                        "formal_accounting_sha256": formal_accounting_sha256,
                    }
                )
    return manifests


def plan_matrix(root, campaign, loader=None):
    manifests = build_matrix(root, campaign, loader)
    paths = [Path(m["output_root"]) / m["experiment_name"] for m in manifests]
    if any(path.exists() for path in paths):
        raise FileExistsError("Campaign output already exists; choose a fresh campaign")
    for path, manifest in zip(paths, manifests):
        path.mkdir(parents=True, exist_ok=False)
        write_json(path / "run_manifest.json", manifest)
    return manifests


def write_jsonl(path, rows):
    execution_recovery.atomic_write_jsonl(path, rows)


def frozen_manifest_sha256(manifest):
    keys = (
        "campaign",
        "dataset",
        "task_ids",
        "dataset_sha256",
        "arm",
        "repetition",
        "run_base",
        "experiment_name",
        "appworld_root",
        "output_root",
        "model",
        "embedding_model",
        "embedding_dimensions",
        "batch_size",
        "num_trials",
        "use_memory_addition",
        "use_memory_deletion",
        "initial_pool",
        "pool_sha256",
        "source_commit",
        "source_sha256",
        "shared_logger_sha256",
        "formal_accounting_sha256",
    )
    return execution_recovery.json_sha256({key: manifest.get(key) for key in keys})


def initialize_pool(client, manifest, artifacts):
    """Only reset our new, verified empty collection; never clear a user's pool."""
    if client.snapshot():
        raise RuntimeError("New run collection is not empty; refusing to clear it")
    expected = []
    if manifest["arm"] != "cold_start":
        if file_hash(POOL) != POOL_SHA256:
            raise ValueError("Pool bytes changed before import")
        expected = [json.loads(line) for line in POOL.read_text().splitlines() if line.strip()]
        if pool_state(expected)["count"] != 207:
            raise ValueError("Expected 207 distinct bundled IDs")
        client.call("load_memory", {"load_file_path": str(POOL), "clear_existing": True})
    actual = client.snapshot()
    before, after = pool_state(expected), pool_state(actual)
    if before["ids"] != after["ids"] or before["content_sha256"] != after["content_sha256"]:
        raise RuntimeError("Initial memory ID/content verification failed")
    actual_by_id = {r["memory_id"]: r for r in actual}
    for record in expected:
        observed = actual_by_id[record["memory_id"]]
        for key in ("freq", "utility"):
            if observed.get("metadata", {}).get(key, 0) != record.get("metadata", {}).get(key, 0):
                raise RuntimeError("Imported memory frequency/utility differs from bundled pool")
    write_jsonl(artifacts / "memory_initial.jsonl", actual)
    manifest["initial_memory"] = after
    return actual


def execution_identity(manifest, claim, stage, task_id, task_attempt_id, attempt_kind):
    return {
        "run_directory": str(Path(manifest["output_root"]) / manifest["experiment_name"]),
        "campaign": manifest["campaign"],
        "run": manifest["experiment_name"],
        "stage": stage,
        "phase": stage,
        "task_id": task_id,
        "task_attempt_id": task_attempt_id,
        "attempt_kind": attempt_kind,
        "ownership_generation": claim.generation,
        "owner_token": claim.token,
        "request_id": uuid.uuid4().hex,
    }


def publish_memory_checkpoint(manifest, claim, sequence, checkpoint_data, task_id, committed_task_ids, metadata):
    root = Path(manifest["output_root"]) / manifest["experiment_name"]
    label = "initialization" if task_id is None else re.sub(r"[^a-zA-Z0-9_.-]", "_", task_id)
    attempt = re.sub(r"[^a-zA-Z0-9_.-]", "_", str(metadata.get("task_attempt_id", "checkpoint")))
    path = root / execution_recovery.CHECKPOINT_DIRECTORY / f"{sequence:06d}-{label}-g{claim.generation}-{attempt[:40]}"
    checkpoint = execution_recovery.create_checkpoint(
        path,
        sequence=sequence,
        records=checkpoint_data["records"],
        dimensions=manifest["embedding_dimensions"],
        index_config=checkpoint_data["index_config"],
        owner_token=claim.token,
        owner_generation=claim.generation,
        task_id=task_id,
        metadata=metadata,
    )
    prefix = execution_recovery.discover_committed_prefix(
        root,
        manifest["task_ids"],
        frozen_manifest_sha256(manifest),
        expected_dimensions=manifest["embedding_dimensions"],
    )
    record = execution_recovery.make_commit_record(
        run_root=root,
        checkpoint=checkpoint,
        frozen_manifest_sha256=frozen_manifest_sha256(manifest),
        previous_commit_sha256=prefix.last_commit_sha256,
        committed_task_ids=committed_task_ids,
    )
    marker, _ = execution_recovery.publish_commit(root, record, claim)
    return checkpoint, marker


def restore_checkpoint(client, checkpoint):
    restored = client.restore(
        {
            "records": list(checkpoint.records),
            "records_sha256": checkpoint.records_sha256,
            "index_config": checkpoint.manifest["index_config"],
        }
    )
    if (
        restored["records_sha256"] != checkpoint.records_sha256
        or restored["index_config_sha256"] != checkpoint.manifest["index_config_sha256"]
    ):
        raise RuntimeError("Restored memory differs from the committed checkpoint")
    return restored


def archive_partial_task(root, task_id, attempt_id):
    source = Path(root) / "tasks" / task_id
    if not source.exists():
        return None
    call_log = source / "logs/lm_calls.jsonl"
    if call_log.exists():
        rows = [json.loads(line) for line in call_log.read_text().splitlines() if line.strip()]
        attempt_ids = [
            row.get("metadata", {}).get("extra", {}).get("task_attempt_id") for row in rows
        ]
        if any(value is not None for value in attempt_ids):
            if any(value is None for value in attempt_ids):
                raise RuntimeError("Partial task log mixes attributed and unattributed calls")
            selected = [row for row, value in zip(rows, attempt_ids) if value == attempt_id]
            if rows and not selected:
                raise RuntimeError("Partial task log lacks calls for the archived attempt")
        else:
            # Legacy recovery fixtures predate physical-attempt identity. They
            # cannot contain cross-attempt accumulation, so preserve them.
            selected = rows
        identifiers = [row.get("id") for row in selected]
        if any(not isinstance(identifier, str) or not identifier for identifier in identifiers):
            raise RuntimeError("Partial task log contains an invalid physical call ID")
        if len(identifiers) != len(set(identifiers)):
            raise RuntimeError("Partial task log duplicates a physical call ID")
        write_jsonl(call_log, selected)
    destination = (
        Path(root)
        / execution_recovery.RECOVERY_DIRECTORY
        / "attempts"
        / task_id
        / re.sub(r"[^a-zA-Z0-9_.-]", "_", attempt_id)
        / "task_output"
    )
    if destination.exists():
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    source.replace(destination)
    return destination


def merge_attempt_call_logs(root, task_id, *, write=True):
    root = Path(root)
    canonical = root / "tasks" / task_id / "logs/lm_calls.jsonl"
    paths = sorted(
        (root / execution_recovery.RECOVERY_DIRECTORY / "attempts" / task_id).glob("*/task_output/logs/lm_calls.jsonl")
    )
    if canonical.exists():
        paths.append(canonical)
    rows, by_id = [], {}
    for path in paths:
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            physical_id = row.get("id")
            if not isinstance(physical_id, str) or not physical_id:
                raise RuntimeError(f"Invalid physical call ID in {path}")
            if physical_id not in by_id:
                by_id[physical_id] = row
                rows.append(row)
            elif by_id[physical_id] != row:
                raise RuntimeError(f"Conflicting physical call duplicate in {path}: {physical_id}")
    if rows and write:
        write_jsonl(canonical, rows)
    return rows


def service_environment(environment=None):
    """Map explicit role settings, DashScope embeddings, then OpenAI fallbacks."""
    environment = dict(os.environ if environment is None else environment)
    if environment.get("DASHSCOPE_API_KEY") and not environment.get("EMBEDDING_API_KEY"):
        environment["EMBEDDING_API_KEY"] = environment["DASHSCOPE_API_KEY"]
        if not environment.get("EMBEDDING_BASE_URL"):
            environment["EMBEDDING_BASE_URL"] = (
                environment.get("DASHSCOPE_BASE_URL") or "https://dashscope.aliyuncs.com/compatible-mode/v1"
            )
    for prefix in ("LLM", "EMBEDDING"):
        for suffix in ("API_KEY", "BASE_URL"):
            name = f"{prefix}_{suffix}"
            if not environment.get(name):
                environment[name] = environment.get(f"OPENAI_{suffix}", "")
            if not environment[name]:
                raise ValueError(f"Set {name} or OPENAI_{suffix} before launching the service")
    return environment


def load_provider_environment(path):
    """Read only the explicitly selected file; never print or persist its secrets."""
    from dotenv import dotenv_values

    values = dotenv_values(Path(path).resolve(strict=True), interpolate=False)
    names = (
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "DASHSCOPE_API_KEY",
        "DASHSCOPE_BASE_URL",
        "LLM_API_KEY",
        "LLM_BASE_URL",
        "EMBEDDING_API_KEY",
        "EMBEDDING_BASE_URL",
    )
    selected = {name: values[name] for name in names if values.get(name)}
    if not selected.get("OPENAI_API_KEY") or not selected.get("OPENAI_BASE_URL"):
        raise ValueError("Selected provider file must contain OPENAI_API_KEY and OPENAI_BASE_URL")
    selected = service_environment(selected)
    for name in names:
        os.environ.pop(name, None)
    os.environ.update(selected)


def prepare_service_log(artifacts, task_attempt_id):
    """Preserve a prior service attempt before opening the canonical log."""

    artifacts = Path(artifacts)
    current = artifacts / "service.log"
    if not current.exists():
        return current
    safe_attempt = re.sub(r"[^a-zA-Z0-9_.-]", "_", str(task_attempt_id))
    archive = artifacts / execution_recovery.RECOVERY_DIRECTORY.name / "service_logs" / f"before-{safe_attempt}.log"
    archive.parent.mkdir(parents=True, exist_ok=True)
    if archive.exists():
        raise FileExistsError(archive)
    current.replace(archive)
    return current


@contextmanager
def isolated_service(
    manifest,
    service_python,
    es_url,
    port,
    claim=None,
    task_attempt_id="initialization",
    attempt_kind="primary",
):
    import requests

    root = Path(manifest["output_root"]) / manifest["experiment_name"]
    artifacts = root / "baseline_artifacts/reme"
    artifacts.mkdir(parents=True, exist_ok=True)
    workspace = (artifacts / "service_workspace").resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    collection = "reme_" + uuid.uuid4().hex
    manifest["collection"] = collection
    if claim:
        claim.assert_current()
    write_json(root / "run_manifest.json", manifest)
    client_identity = (
        execution_identity(manifest, claim, "initialization", None, task_attempt_id, attempt_kind)
        if claim
        else {"run_directory": str(root)}
    )
    environment = {
        **service_environment(),
        "PYTHONPATH": str(SOURCE_ROOT),
        "REME_AUDIT_RUN_DIRECTORY": str(root),
        "REME_AUDIT_TOKEN": token,
        **(
            {
                "REME_AUDIT_OWNER_TOKEN": claim.token,
                "REME_AUDIT_OWNER_GENERATION": str(claim.generation),
            }
            if claim
            else {}
        ),
        **{
            key: os.environ[key]
            for key in (execution_budget.ENVIRONMENT_KEY, execution_accounting.ENVIRONMENT_KEY)
            if key in os.environ
        },
    }
    command = [
        str(service_python),
        "-c",
        "import sys; from reme import extension, memory; from reme.reme import ReMe; "
        "ReMe(*sys.argv[2:], config_path='service', working_dir=sys.argv[1], "
        "enable_load_env=False).run_service()",
        str(workspace),
        "backend=http",
        "http.host=127.0.0.1",
        f"http.port={port}",
        "llms.default.model_name=qwen3.8-flash",
        "embedding_models.default.model_name=text-embedding-v4",
        "embedding_models.default.dimensions=1024",
        "embedding_models.default.enable_cache=false",
        "vector_stores.default.backend=es",
        f"vector_stores.default.collection_name={collection}",
        f"vector_stores.default.hosts={es_url}",
    ]
    base_url = f"http://127.0.0.1:{port}/"
    client = MemoryClient(base_url, client_identity, token)
    service_log = prepare_service_log(artifacts, task_attempt_id)
    with service_log.open("x") as log:
        process = subprocess.Popen(command, cwd=workspace, env=environment, stdout=log, stderr=log)
        try:
            deadline = time.monotonic() + 120
            while True:
                if process.poll() is not None:
                    raise RuntimeError("Isolated reme2 service exited; see service.log")
                try:
                    response = requests.get(base_url + "health", timeout=1)
                    if response.status_code == 200:
                        break
                except requests.RequestException:
                    pass
                if time.monotonic() > deadline:
                    raise TimeoutError("Isolated service startup timed out")
                time.sleep(0.5)
            identity = client.call("audit/identity", {})["metadata"]
            expected = {
                "collection": collection,
                "backend": "es",
                "model": "qwen3.8-flash",
                "embedding_model": "text-embedding-v4",
                "dimensions": 1024,
            }
            if identity != expected:
                raise RuntimeError("Service identity/model/backend mismatch")
            manifest["service_identity"] = identity
            yield client, token
        finally:
            process.terminate()
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def run_one_task(
    manifest,
    task_id,
    index,
    client,
    token,
    timeout,
    claim=None,
    task_attempt_id=None,
    attempt_kind="primary",
    ray_temp_dir=None,
):
    import ray
    from appworld_react_agent import AppworldReactAgent

    root = Path(manifest["output_root"]) / manifest["experiment_name"]
    identity = (
        execution_identity(manifest, claim, "executor", task_id, task_attempt_id, attempt_kind)
        if claim
        else {"run_directory": str(root), "task_id": task_id, "phase": "executor", "request_id": uuid.uuid4().hex}
    )
    ray_options = dict(
        num_cpus=1,
        include_dashboard=False,
        namespace=re.sub(r"[^a-zA-Z0-9_.-]", "_", manifest["experiment_name"]),
        runtime_env={
            "env_vars": {
                "APPWORLD_ROOT": manifest["appworld_root"],
                "APPWORLD_LM_LOGGER_MODULE_PATH": os.environ["APPWORLD_LM_LOGGER_MODULE_PATH"],
                **{
                    key: os.environ[key]
                    for key in (
                        "OPENAI_API_KEY",
                        "OPENAI_BASE_URL",
                        execution_budget.ENVIRONMENT_KEY,
                        execution_accounting.ENVIRONMENT_KEY,
                    )
                    if key in os.environ
                },
            }
        },
    )
    if ray_temp_dir:
        ray_temp_dir = Path(ray_temp_dir).resolve()
        ray_temp_dir.mkdir(parents=True, exist_ok=False)
        ray_options["_temp_dir"] = str(ray_temp_dir)
    ray.init(**ray_options)
    try:
        actor = AppworldReactAgent.remote(
            index=index,
            task_ids=[task_id],
            experiment_name=manifest["run_base"],
            model_name=manifest["model"],
            num_trials=1,
            use_memory=True,
            memory_base_url=client.base_url,
            use_memory_addition=manifest["use_memory_addition"],
            use_memory_deletion=manifest["use_memory_deletion"],
            delete_freq=5,
            freq_threshold=5,
            utility_threshold=0.5,
            audit_identity=identity,
            audit_token=token,
        )
        result = ray.get(actor.execute.remote(), timeout=timeout)
        if not isinstance(result, list) or len(result) != 1 or result[0].get("task_id") != task_id:
            raise RuntimeError("Ray task did not return exactly one matching result")
        return result[0]
    finally:
        ray.shutdown()


def evaluate_closed_task(task_id, experiment_name):
    """Own only the parent evaluator's cache, after the Ray world is closed."""
    from appworld.apps.model_lib import CachedDBHandler
    from appworld.evaluator import evaluate_task

    if not CachedDBHandler.is_empty():
        raise RuntimeError("Parent evaluator has an unexpected open database cache")
    try:
        return evaluate_task(task_id=task_id, experiment_name=experiment_name, save_report=True)
    finally:
        # evaluate_task intentionally leaves its DB cache for live-world callers.
        # This parent has no live AppWorld; aggregate evaluation requires empty.
        CachedDBHandler.reset()


def finalize_task(manifest, result, started, before, after, task_attempt_id=None):
    root = Path(manifest["output_root"]) / manifest["experiment_name"]
    task = result["task_id"]
    directory = root / "tasks" / task
    tracker, _ = evaluate_closed_task(task, manifest["experiment_name"])
    reward = len(tracker.passes) / (len(tracker.passes) + len(tracker.failures))
    if reward != result["after_score"]:
        raise RuntimeError(
            "Post-close official reward disagrees with memory-update reward: "
            f"official={reward!r}, update={result['after_score']!r}"
        )
    required = (
        "logs/api_calls.jsonl",
        "logs/environment_io.md",
        "logs/lm_calls.jsonl",
        "evaluation/report.md",
        "evaluation/version.txt",
        "version/code.txt",
        "version/data.txt",
        "dbs/model_hashes.json",
        "logs/loggger.log",
    )
    for path in required:
        if not (directory / path).is_file():
            raise FileNotFoundError(directory / path)
    for path in ("checkpoints", "dbs", "misc"):
        if not (directory / path).is_dir():
            raise FileNotFoundError(directory / path)
    dbs = list((directory / "dbs").glob("*.jsonl"))
    required_apps = {
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
    }
    if not required_apps.issubset({p.stem for p in dbs}):
        raise RuntimeError("Missing required AppWorld DB dumps")
    json.loads((directory / "dbs/model_hashes.json").read_text())
    for db in dbs:
        for line in db.read_text().splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if (
                not isinstance(row, list)
                or len(row) != 3
                or not isinstance(row[0], str)
                or not isinstance(row[1], list)
                or not isinstance(row[2], bool)
            ):
                raise ValueError(f"Invalid AppWorld DB row: {db}")
    for line in (directory / "logs/api_calls.jsonl").read_text().splitlines():
        row = json.loads(line)
        if set(row) != {"method", "url", "data"} or not isinstance(row["data"], dict):
            raise ValueError("Invalid AppWorld API-call schema")
    report = (directory / "evaluation/report.md").read_text()
    if any(section not in report for section in ("Overall Stats", "Passes", "Fails")):
        raise ValueError("Incomplete official evaluation report")
    calls = merge_attempt_call_logs(root, task, write=False)
    attempt_calls = calls
    if task_attempt_id is not None:
        attempt_calls = [
            call
            for call in calls
            if call.get("metadata", {}).get("extra", {}).get("task_attempt_id") == task_attempt_id
        ]
    if not attempt_calls or not any(c["metadata"]["phase"] == "executor" for c in attempt_calls):
        raise RuntimeError("Missing executor call evidence")
    if any(c["metadata"]["status"] != "success" or c["metadata"]["root_task_id"] != task for c in attempt_calls):
        raise RuntimeError("Failed or misattributed provider call in the committed attempt")
    events_path = root / "baseline_artifacts/reme" / task / "memory_events.jsonl"
    events = [json.loads(line) for line in events_path.read_text().splitlines()]
    expected = ["retrieve_task_memory"]
    if manifest["use_memory_addition"]:
        expected += ["summary_task_memory"] + (["add_task_memory"] if reward == 1 else [])
    expected += ["record_task_memory"] + (["delete_task_memory"] if manifest["use_memory_deletion"] else [])
    attempt_events = events
    if task_attempt_id is not None:
        attempt_events = [event for event in events if event.get("task_attempt_id") == task_attempt_id]
    operations = [e for e in attempt_events if not e["endpoint"].startswith("audit/")]
    if [e["endpoint"] for e in operations] != expected or any(e["status"] != "success" for e in attempt_events):
        raise RuntimeError("Memory call order/acknowledgement mismatch")
    if any(e["started_at"] < started for e in operations):
        raise RuntimeError("Memory call predates task submission")
    initial, final = pool_state(before), pool_state(after)
    if manifest["arm"] == "fixed" and initial["content_sha256"] != final["content_sha256"]:
        raise RuntimeError("Fixed arm changed experience IDs or content")
    # Without verified provider rates, dollar cost must never silently become zero.
    usage = [c["output"].get("usage") for c in calls]
    cost = {
        "status": "unavailable",
        "reason": "Provider-specific rates not supplied; see physical call usage",
        "physical_calls": len(calls),
        "usage": usage,
        "missing_usage_calls": sum(u is None for u in usage),
    }
    if os.environ.get(execution_budget.ENVIRONMENT_KEY):
        cost = execution_budget.cost_evidence(calls)
    elif os.environ.get(execution_accounting.ENVIRONMENT_KEY):
        reconciliation = execution_accounting.reconcile(
            calls,
            campaign=manifest["campaign"],
            run=manifest["experiment_name"],
            task=task,
        )
        cost = {
            **reconciliation["summary"],
            "status": "formal_accounting",
            "reconciliation": {
                key: reconciliation[key]
                for key in (
                    "status",
                    "ledger_only_ids",
                    "log_only_ids",
                    "duplicate_log_ids",
                    "invalid_log_ids",
                )
            },
        }
    # Publish the deduplicated all-attempt canonical log only after every
    # fail-closed validation above passes. A failed attempt therefore remains
    # attempt-local when archive_partial_task preserves it for recovery.
    write_jsonl(directory / "logs/lm_calls.jsonl", calls)
    write_json(directory / "misc/cost.txt", cost)
    audit = {
        "task_id": task,
        "started_at": started,
        "committed_at": now(),
        "result": result,
        "committed_task_attempt_id": task_attempt_id,
        "retained_physical_calls": len(calls),
        "committed_attempt_physical_calls": len(attempt_calls),
        "before": initial,
        "after": final,
        "official_reward": reward,
        "accounting": cost,
        "files": {str(p.relative_to(directory)): file_hash(p) for p in directory.rglob("*") if p.is_file()},
    }
    write_json(events_path.parent / "task_audit.json", audit)
    return audit


def aggregate_run(manifest):
    from appworld.evaluator import evaluate_dataset

    root = Path(manifest["output_root"]) / manifest["experiment_name"]
    kwargs = {
        "experiment_name": manifest["experiment_name"],
        "dataset_name": manifest["dataset"],
        "save_reports": True,
    }
    name = manifest["dataset"]
    if manifest.get("smoke"):
        kwargs.update(dataset_name="on_only", task_id=manifest["task_ids"][0])
        name = "on_only_" + manifest["task_ids"][0]
    evaluate_dataset(**kwargs)
    for suffix in ("json", "txt"):
        if not (root / "evaluations" / f"{name}.{suffix}").is_file():
            raise FileNotFoundError("Official aggregate missing")


def execute_run_legacy(
    manifest,
    service_python,
    es_url,
    port=8002,
    task_timeout=3600,
    service_factory=isolated_service,
    task_runner=run_one_task,
    finalizer=finalize_task,
):
    root = Path(manifest["output_root"]) / manifest["experiment_name"]
    artifacts = root / "baseline_artifacts/reme"
    if manifest["status"] != "planned" or (root / "tasks").exists():
        raise ValueError("Resume/overwrite is unsupported; use a fresh campaign")
    manifest.update(status="running", started_at=now(), completed_task_ids=[])
    clock_start = time.monotonic()
    write_json(root / "run_manifest.json", manifest)
    try:
        with service_factory(manifest, service_python, es_url, port) as (client, token):
            before = initialize_pool(client, manifest, artifacts)
            for index, task_id in enumerate(manifest["task_ids"]):
                started = now()
                result = task_runner(manifest, task_id, index, client, token, task_timeout)
                after = client.snapshot()
                finalizer(manifest, result, started, before, after)
                with (artifacts / "legacy_results.jsonl").open("a") as stream:
                    stream.write(json.dumps(result) + "\n")
                manifest["completed_task_ids"].append(task_id)
                write_json(root / "run_manifest.json", manifest)
                before = after
            write_jsonl(artifacts / "memory_final.jsonl", before)
            manifest["final_memory"] = pool_state(before)
            initialization_log = artifacts / "initialization_lm_calls.jsonl"
            initialization_calls = (
                [json.loads(line) for line in initialization_log.read_text().splitlines()]
                if initialization_log.exists()
                else []
            )
            costs = {
                task: json.loads((root / "tasks" / task / "misc/cost.txt").read_text()) for task in manifest["task_ids"]
            }
            write_json(
                artifacts / "cost_evidence.json",
                {
                    "tasks": costs,
                    "initialization_usage": [c["output"].get("usage") for c in initialization_calls],
                    "initialization_physical_calls": len(initialization_calls),
                    "dollars": None,
                    "reason": "Unverified provider rates; not a zero-cost run",
                },
            )
            if os.environ.get(execution_budget.ENVIRONMENT_KEY):
                initialization_cost = execution_budget.cost_evidence(initialization_calls)
                write_json(
                    artifacts / "cost_evidence.json",
                    {
                        "status": "published_rate_estimate",
                        "tasks": costs,
                        "initialization": initialization_cost,
                        "dollars": initialization_cost["dollars"] + sum(c["dollars"] for c in costs.values()),
                        "billed_dollars": None,
                        "budget": execution_budget.summary(),
                    },
                )
        aggregate_run(manifest)
        manifest.update(status="complete", finished_at=now())
    except BaseException as error:
        manifest.update(
            status="incomplete",
            finished_at=now(),
            error_type=type(error).__name__,
            error=shared_logger().redact_secrets(str(error)),
        )
        raise
    finally:
        manifest["wall_seconds"] = time.monotonic() - clock_start
        write_json(root / "run_manifest.json", manifest)


def _append_jsonl_synced(path, row):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(row, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def _formal_cost_evidence(manifest):
    return execution_accounting.summary(campaign=manifest["campaign"], run=manifest["experiment_name"])


def execute_formal_run(
    manifest,
    service_python,
    es_url,
    port=18101,
    task_timeout=3600,
    ray_temp_dir=None,
    claim=None,
    service_factory=isolated_service,
    task_runner=run_one_task,
    finalizer=finalize_task,
):
    """Execute or resume one formal run from immutable task-boundary commits."""
    root = Path(manifest["output_root"]) / manifest["experiment_name"]
    artifacts = root / "baseline_artifacts/reme"
    if manifest.get("formal_accounting_sha256") != execution_accounting.policy()[2]:
        raise ValueError("Formal accounting policy differs from the frozen manifest")
    owned_claim = claim is None
    if claim is None:
        claim = execution_recovery.RunClaim.acquire(root, manifest["experiment_name"])
    clock_start = time.monotonic()
    try:
        while True:
            claim.assert_current()
            frozen_hash = frozen_manifest_sha256(manifest)
            prefix = execution_recovery.discover_committed_prefix(
                root,
                manifest["task_ids"],
                frozen_hash,
                expected_dimensions=manifest["embedding_dimensions"],
            )
            manifest["completed_task_ids"] = list(prefix.task_ids)
            if prefix.initialized and prefix.next_task_id is None:
                try:
                    aggregate_run(manifest)
                    for field in ("finished_at", "error_type", "error"):
                        manifest.pop(field, None)
                    manifest.update(status="complete", finished_at=now(), active_stage=None)
                    write_json(artifacts / "cost_evidence.json", _formal_cost_evidence(manifest))
                    write_json(root / "run_manifest.json", manifest)
                    return manifest
                except Exception as error:
                    manifest.update(
                        status="incomplete",
                        active_stage="aggregation",
                        error_type=type(error).__name__,
                        error=shared_logger().redact_secrets(str(error)),
                        accounting=_formal_cost_evidence(manifest),
                    )
                    write_json(root / "run_manifest.json", manifest)
                    restart = execution_recovery.record_infrastructure_restart(
                        root, claim, "aggregation", max_restarts=2
                    )
                    time.sleep(min(30, 2 ** (restart - 1)))
                    continue

            stage = "initialization" if not prefix.initialized else "task"
            task_id = prefix.next_task_id if prefix.initialized else None
            interrupted_attempt = manifest.get("active_task_attempt_id")
            interrupted_matches = (
                interrupted_attempt
                and manifest.get("active_stage") == stage
                and manifest.get("active_task_id") == task_id
                and manifest.get("last_recovery_accounted_attempt_id") != interrupted_attempt
            )
            if interrupted_matches:
                execution_recovery.record_infrastructure_restart(root, claim, stage, task_id, max_restarts=2)
                manifest["last_recovery_accounted_attempt_id"] = interrupted_attempt
                write_json(root / "run_manifest.json", manifest)
            restarts = execution_recovery.retry_count(root, stage, task_id, max_restarts=2)
            attempt_kind = "primary" if restarts == 0 else "recovery"
            task_attempt_id = (
                f"{stage}-{len(prefix.task_ids):06d}-g{claim.generation}-a{restarts + 1}-{uuid.uuid4().hex[:12]}"
            )
            previous_attempt = manifest.get("active_task_attempt_id")
            if task_id and (root / "tasks" / task_id).exists():
                archive_partial_task(root, task_id, previous_attempt or f"orphan-{uuid.uuid4().hex[:12]}")
            for field in ("finished_at", "error_type", "error"):
                manifest.pop(field, None)
            manifest.update(
                status="running",
                started_at=manifest.get("started_at", now()),
                active_stage=stage,
                active_task_id=task_id,
                active_task_attempt_id=task_attempt_id,
                active_attempt_kind=attempt_kind,
                ownership=claim.identity,
            )
            write_json(root / "run_manifest.json", manifest)
            try:
                with service_factory(
                    manifest,
                    service_python,
                    es_url,
                    port,
                    claim=claim,
                    task_attempt_id=task_attempt_id,
                    attempt_kind=attempt_kind,
                ) as (client, token):
                    if prefix.initialized:
                        restore_checkpoint(client, prefix.last_checkpoint)
                    else:
                        initialize_pool(client, manifest, artifacts)
                        checkpoint_data = client.checkpoint()
                        checkpoint, marker = publish_memory_checkpoint(
                            manifest,
                            claim,
                            0,
                            checkpoint_data,
                            None,
                            [],
                            {
                                "task_attempt_id": task_attempt_id,
                                "attempt_kind": attempt_kind,
                                "accounting": _formal_cost_evidence(manifest),
                            },
                        )
                        prefix = execution_recovery.discover_committed_prefix(
                            root,
                            manifest["task_ids"],
                            frozen_hash,
                            expected_dimensions=manifest["embedding_dimensions"],
                        )
                        manifest.update(
                            completed_task_ids=[],
                            initialization_commit=str(marker.relative_to(root)),
                            initialization_checkpoint=str(checkpoint.path.relative_to(root)),
                        )
                        write_json(root / "run_manifest.json", manifest)

                    before = client.snapshot()
                    for index in range(len(prefix.task_ids), len(manifest["task_ids"])):
                        claim.assert_current()
                        task_id = manifest["task_ids"][index]
                        task_restarts = execution_recovery.retry_count(root, "task", task_id, max_restarts=2)
                        attempt_kind = "primary" if task_restarts == 0 else "recovery"
                        task_attempt_id = (
                            f"task-{index + 1:06d}-g{claim.generation}-a{task_restarts + 1}-{uuid.uuid4().hex[:12]}"
                        )
                        if (root / "tasks" / task_id).exists():
                            archive_partial_task(
                                root,
                                task_id,
                                manifest.get("active_task_attempt_id") or f"orphan-{uuid.uuid4().hex[:12]}",
                            )
                        manifest.update(
                            active_stage="task",
                            active_task_id=task_id,
                            active_task_attempt_id=task_attempt_id,
                            active_attempt_kind=attempt_kind,
                        )
                        write_json(root / "run_manifest.json", manifest)
                        started = now()
                        task_ray_dir = (
                            str(Path(ray_temp_dir) / hashlib.sha256(task_attempt_id.encode()).hexdigest()[:8])
                            if ray_temp_dir is not None
                            else None
                        )
                        result = task_runner(
                            manifest,
                            task_id,
                            index,
                            client,
                            token,
                            task_timeout,
                            claim=claim,
                            task_attempt_id=task_attempt_id,
                            attempt_kind=attempt_kind,
                            ray_temp_dir=task_ray_dir,
                        )
                        after = client.snapshot()
                        audit = finalizer(
                            manifest,
                            result,
                            started,
                            before,
                            after,
                            task_attempt_id=task_attempt_id,
                        )
                        calls = merge_attempt_call_logs(root, task_id)
                        checkpoint_data = client.checkpoint()
                        task_audit_path = artifacts / task_id / "task_audit.json"
                        metadata = {
                            "task_attempt_id": task_attempt_id,
                            "attempt_kind": attempt_kind,
                            "result": result,
                            "official_reward": audit.get("official_reward") if isinstance(audit, dict) else None,
                            "task_audit_sha256": file_hash(task_audit_path) if task_audit_path.exists() else None,
                            "canonical_physical_call_ids": [call["id"] for call in calls],
                            "accounting": _formal_cost_evidence(manifest),
                        }
                        checkpoint, marker = publish_memory_checkpoint(
                            manifest,
                            claim,
                            index + 1,
                            checkpoint_data,
                            task_id,
                            manifest["task_ids"][: index + 1],
                            metadata,
                        )
                        _append_jsonl_synced(artifacts / "legacy_results.jsonl", result)
                        manifest["completed_task_ids"] = manifest["task_ids"][: index + 1]
                        manifest.update(
                            last_commit=str(marker.relative_to(root)),
                            last_checkpoint=str(checkpoint.path.relative_to(root)),
                            active_stage=None,
                            active_task_id=None,
                            active_task_attempt_id=None,
                        )
                        write_json(root / "run_manifest.json", manifest)
                        prefix = execution_recovery.discover_committed_prefix(
                            root,
                            manifest["task_ids"],
                            frozen_hash,
                            expected_dimensions=manifest["embedding_dimensions"],
                        )
                        before = after
                    final_checkpoint = execution_recovery.discover_committed_prefix(
                        root,
                        manifest["task_ids"],
                        frozen_hash,
                        expected_dimensions=manifest["embedding_dimensions"],
                    ).last_checkpoint
                    write_jsonl(artifacts / "memory_final.jsonl", final_checkpoint.records)
                    manifest["final_memory"] = {
                        "count": len(final_checkpoint.records),
                        "records_sha256": final_checkpoint.records_sha256,
                    }
                # Aggregation is outside the service; a failure resumes without model calls.
                continue
            except Exception as error:
                claim.assert_current()
                manifest.update(
                    status="incomplete",
                    finished_at=now(),
                    error_type=type(error).__name__,
                    error=shared_logger().redact_secrets(str(error)),
                    accounting=_formal_cost_evidence(manifest),
                )
                write_json(root / "run_manifest.json", manifest)
                latest = execution_recovery.discover_committed_prefix(
                    root,
                    manifest["task_ids"],
                    frozen_hash,
                    expected_dimensions=manifest["embedding_dimensions"],
                )
                if len(latest.task_ids) > len(prefix.task_ids):
                    continue
                retry_stage = "initialization" if not latest.initialized else "task"
                retry_task = latest.next_task_id if latest.initialized else None
                restart = execution_recovery.record_infrastructure_restart(
                    root, claim, retry_stage, retry_task, max_restarts=2
                )
                manifest["last_recovery_accounted_attempt_id"] = manifest.get("active_task_attempt_id")
                write_json(root / "run_manifest.json", manifest)
                time.sleep(min(30, 2 ** (restart - 1)))
    finally:
        manifest["wall_seconds"] = manifest.get("wall_seconds", 0) + (time.monotonic() - clock_start)
        if claim:
            try:
                claim.assert_current()
                write_json(root / "run_manifest.json", manifest)
            except execution_recovery.StaleOwner:
                pass
        if owned_claim:
            claim.release()


def execute_run(
    manifest,
    service_python,
    es_url,
    port=8002,
    task_timeout=3600,
    service_factory=isolated_service,
    task_runner=run_one_task,
    finalizer=finalize_task,
    claim=None,
    ray_temp_dir=None,
):
    if os.environ.get(execution_accounting.ENVIRONMENT_KEY):
        return execute_formal_run(
            manifest,
            service_python,
            es_url,
            port=port,
            task_timeout=task_timeout,
            ray_temp_dir=ray_temp_dir,
            claim=claim,
            service_factory=service_factory,
            task_runner=task_runner,
            finalizer=finalizer,
        )
    return execute_run_legacy(
        manifest,
        service_python,
        es_url,
        port=port,
        task_timeout=task_timeout,
        service_factory=service_factory,
        task_runner=task_runner,
        finalizer=finalizer,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--appworld-root", type=Path, default=DEFAULT_APPWORLD_ROOT)
    parser.add_argument("--campaign", required=True)
    parser.add_argument("--execute", action="store_true", help="Makes real provider calls; requires accounting")
    parser.add_argument("--smoke", action="store_true", help="One task per arm, repetition 1; not a scored dataset run")
    parser.add_argument("--service-python", type=Path)
    parser.add_argument("--env-file", type=Path, help="Explicit provider dotenv; overrides inherited provider settings")
    parser.add_argument("--smoke-budget", type=Path, help="Approved shared reservation policy; required for live smoke")
    parser.add_argument(
        "--formal-accounting",
        type=Path,
        help="Mandatory uncapped accounting policy for non-smoke formal execution or planning",
    )
    parser.add_argument("--es-url")
    parser.add_argument("--port", type=int, default=8002)
    parser.add_argument("--task-timeout", type=int, default=3600)
    args = parser.parse_args()
    if args.env_file:
        load_provider_environment(args.env_file)
    if args.execute and (not args.service_python or not args.es_url):
        parser.error("--execute requires --service-python and --es-url")
    if args.task_timeout <= 0:
        parser.error("--task-timeout must be positive")
    if args.execute and args.smoke and not args.smoke_budget:
        parser.error("--execute --smoke requires --smoke-budget")
    if args.execute and not args.smoke and not args.formal_accounting:
        parser.error("formal --execute requires --formal-accounting")
    if args.smoke_budget and args.formal_accounting:
        parser.error("smoke budget and formal accounting are mutually exclusive")
    if args.smoke_budget:
        if not args.smoke:
            parser.error("--smoke-budget is only for smoke execution")
        os.environ[execution_budget.ENVIRONMENT_KEY] = str(args.smoke_budget.resolve(strict=True))
        execution_budget.policy()
    if args.formal_accounting:
        if args.smoke:
            parser.error("--formal-accounting cannot be used with --smoke")
        os.environ[execution_accounting.ENVIRONMENT_KEY] = str(args.formal_accounting.resolve(strict=True))
        execution_accounting.policy()
    root = configure_appworld(args.appworld_root)
    os.environ["APPWORLD_LM_LOGGER_MODULE_PATH"] = str(root / "experiments/code/common/lm_logger.py")
    from appworld import load_task_ids

    manifests = plan_matrix(root, args.campaign, load_task_ids)
    if args.execute:
        from appworld.task import Task

        selected = manifests
        if args.smoke:
            selected = [m for m in manifests if m["dataset"] == "quick2h_test_normal_v2" and m["repetition"] == 1]
            for manifest in selected:
                manifest.update(smoke=True, task_ids=manifest["task_ids"][:1])
        for task_id in dict.fromkeys(t for m in selected for t in m["task_ids"]):
            task = Task.load(task_id, load_ground_truth=False)
            task.close()
        for manifest in selected:
            execute_run(manifest, args.service_python, args.es_url, args.port, args.task_timeout)
        return
    print(
        json.dumps(
            {
                "runs": len(manifests),
                "task_attempts": sum(len(m["task_ids"]) for m in manifests),
                "status": "planned",
                "provider_calls": 0,
            }
        )
    )


if __name__ == "__main__":
    main()
