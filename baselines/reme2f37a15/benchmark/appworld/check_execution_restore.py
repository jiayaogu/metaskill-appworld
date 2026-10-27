"""Provider-free live Elasticsearch checkpoint/restore verification.

The provider environment is loaded because the real ReMe service validates its
model configuration at startup.  Every state operation in this check supplies
stored vectors directly; no chat or embedding request is permitted or needed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

import execution_accounting
import execution_budget
import execution_matrix
import execution_recovery


def deterministic_records():
    def vector(*coordinates):
        return list(coordinates) + [0.0] * (1024 - len(coordinates))

    return execution_recovery.normalize_vector_records(
        [
            {
                "vector_id": "alpha",
                "content": "alpha exact-vector fixture",
                "vector": vector(1.0, 0.0, 0.0),
                "metadata": {
                    "memory_type": "task",
                    "freq": 11,
                    "utility": 9,
                    "time_created": "2026-10-24 10:00:00",
                    "time_modified": "2026-10-24 10:01:00",
                },
            },
            {
                "vector_id": "beta",
                "content": "beta exact-vector fixture",
                "vector": vector(0.0, 1.0, 0.0),
                "metadata": {
                    "memory_type": "task",
                    "freq": 7,
                    "utility": 4,
                    "time_created": "2026-10-24 10:02:00",
                    "time_modified": "2026-10-24 10:03:00",
                },
            },
            {
                "vector_id": "gamma",
                "content": "gamma exact-vector fixture",
                "vector": vector(0.5, 0.5, 0.0),
                "metadata": {
                    "memory_type": "task",
                    "freq": 5,
                    "utility": 5,
                    "time_created": "2026-10-24 10:04:00",
                    "time_modified": "2026-10-24 10:05:00",
                },
            },
        ],
        1024,
    )


def select_free_ports(count=2):
    sockets = []
    try:
        for _ in range(count):
            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            sockets.append(listener)
        return [listener.getsockname()[1] for listener in sockets]
    finally:
        for listener in sockets:
            listener.close()


def validate_ports(ports):
    if len(ports) != 2 or len(set(ports)) != 2:
        raise ValueError("Exactly two distinct service ports are required")
    listeners = []
    try:
        for port in ports:
            if type(port) is not int or not 1 <= port <= 65535:
                raise ValueError("Service ports must be integers in 1-65535")
            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            listener.bind(("127.0.0.1", port))
            listener.listen(1)
            listeners.append(listener)
    finally:
        for listener in listeners:
            listener.close()


def count_provider_rows(run_root):
    rows = []
    for path in sorted(Path(run_root).glob("**/*lm_calls.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append((path, json.loads(line)))
    return rows


def archive_service_log(run_root, label):
    source = Path(run_root) / "baseline_artifacts/reme/service.log"
    destination = source.with_name(f"service-{label}.log")
    if not source.is_file() or destination.exists():
        raise RuntimeError("Expected one new isolated-service log")
    source.replace(destination)
    return destination


def seed_collection(es_url, collection, records):
    """Seed the source fixture directly, without invoking any model provider."""

    for record in records:
        response = requests.put(
            f"{es_url.rstrip('/')}/{collection}/_doc/{record['vector_id']}",
            params={"refresh": "true"},
            json=record,
            timeout=10,
        )
        response.raise_for_status()


def file_sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def ranking(search):
    return [hit["vector_id"] for hit in search["hits"]]


def score_vectors(search):
    return [hit.get("score") for hit in search["hits"]]


def check_scores_equal(first, second, tolerance=1e-12):
    if len(first) != len(second):
        return False
    for left, right in zip(first, second):
        if left is None or right is None:
            if left != right:
                return False
        elif abs(left - right) > tolerance:
            return False
    return True


def run(args):
    report_path = args.report.resolve()
    # Preserve the venv's python symlink: resolving it to the base interpreter
    # discards pyvenv.cfg discovery and therefore the service dependencies.
    service_python = Path(os.path.abspath(args.service_python))
    if not service_python.is_file():
        raise FileNotFoundError(service_python)
    env_file = args.env_file.resolve(strict=True)
    work_root = args.work_root.resolve() if args.work_root else report_path.parent / f"{report_path.stem}-artifacts"
    if work_root.exists():
        raise FileExistsError(f"Check work root already exists: {work_root}")
    work_root.mkdir(parents=True)
    run_root = work_root / "live_restore_run_0"
    run_root.mkdir()

    ports = args.ports or select_free_ports()
    validate_ports(ports)
    response = requests.get(args.es_url, timeout=5)
    response.raise_for_status()
    es_identity = response.json()

    execution_matrix.load_provider_environment(env_file)
    os.environ.pop(execution_budget.ENVIRONMENT_KEY, None)
    os.environ.pop(execution_accounting.ENVIRONMENT_KEY, None)
    appworld_root = args.appworld_root.resolve(strict=True)
    logger_path = appworld_root / "experiments/code/common/lm_logger.py"
    if not logger_path.is_file():
        raise FileNotFoundError(logger_path)
    os.environ["APPWORLD_LM_LOGGER_MODULE_PATH"] = str(logger_path)

    manifest = {
        "schema_version": 2,
        "status": "diagnostic",
        "campaign": "live-restore-check",
        "dataset": "synthetic",
        "task_ids": [],
        "experiment_name": run_root.name,
        "output_root": str(work_root),
        "appworld_root": str(appworld_root),
        "model": "qwen3.8-flash",
        "embedding_model": "text-embedding-v4",
        "embedding_dimensions": 1024,
    }
    execution_recovery.atomic_write_json(run_root / "run_manifest.json", manifest)
    records = deterministic_records()
    query_vector = [1.0, 0.0, 0.0] + [0.0] * 1021
    collections = []
    service_logs = []

    with execution_recovery.RunClaim.acquire(
        run_root, manifest["experiment_name"], owner_token="live-restore-check-owner"
    ) as claim:
        with execution_matrix.isolated_service(
            manifest,
            service_python,
            args.es_url,
            ports[0],
            claim=claim,
            task_attempt_id="live-restore-source",
            attempt_kind="primary",
        ) as (source, _):
            empty = source.checkpoint()
            if empty["records"]:
                raise RuntimeError("Source collection was not fresh and empty")
            seed_collection(args.es_url, manifest["collection"], records)
            source_checkpoint = source.checkpoint()
            source_search = source.vector_search(query_vector, limit=3)
            collections.append(manifest["collection"])
        service_logs.append(archive_service_log(run_root, "source"))

        checkpoint = execution_recovery.create_checkpoint(
            run_root / execution_recovery.CHECKPOINT_DIRECTORY / "000000-live-es",
            sequence=0,
            records=source_checkpoint["records"],
            dimensions=1024,
            index_config=source_checkpoint["index_config"],
            owner_token=claim.token,
            owner_generation=claim.generation,
            metadata={
                "kind": "live-local-es-restore-check",
                "source_collection": collections[0],
                "source_ranking": ranking(source_search),
            },
        )
        loaded = execution_recovery.load_checkpoint(checkpoint.path, expected_dimensions=1024)

        with execution_matrix.isolated_service(
            manifest,
            service_python,
            args.es_url,
            ports[1],
            claim=claim,
            task_attempt_id="live-restore-destination",
            attempt_kind="recovery",
        ) as (destination, _):
            destination_empty = destination.checkpoint()
            if destination_empty["records"]:
                raise RuntimeError("Destination collection was not fresh and empty")
            destination.restore(
                {
                    "records": list(loaded.records),
                    "records_sha256": loaded.records_sha256,
                    "index_config": loaded.manifest["index_config"],
                }
            )
            destination_checkpoint = destination.checkpoint()
            destination_search = destination.vector_search(query_vector, limit=3)
            collections.append(manifest["collection"])
        service_logs.append(archive_service_log(run_root, "destination"))
        owner_generation = claim.generation

    normalized_expected = execution_recovery.normalize_vector_records(records, 1024)
    exact_records = (
        source_checkpoint["records"] == list(loaded.records) == destination_checkpoint["records"] == normalized_expected
    )
    exact_index_config = (
        source_checkpoint["index_config"] == loaded.manifest["index_config"] == destination_checkpoint["index_config"]
    )
    exact_hashes = (
        source_checkpoint["records_sha256"] == loaded.records_sha256 == destination_checkpoint["records_sha256"]
        and source_checkpoint["index_config_sha256"]
        == loaded.manifest["index_config_sha256"]
        == destination_checkpoint["index_config_sha256"]
    )
    source_ranking = ranking(source_search)
    destination_ranking = ranking(destination_search)
    rankings_equal = source_ranking == destination_ranking
    scores_equal = check_scores_equal(score_vectors(source_search), score_vectors(destination_search))
    provider_rows = count_provider_rows(run_root)
    assertions = {
        "fresh_collections": len(collections) == 2 and collections[0] != collections[1],
        "exact_records": exact_records,
        "exact_index_config": exact_index_config,
        "exact_hashes": exact_hashes,
        "ranking_identical": rankings_equal,
        "ranking_expected": source_ranking == ["alpha", "gamma", "beta"],
        "scores_identical": scores_equal,
        "provider_requests_zero": len(provider_rows) == 0,
    }
    if not all(assertions.values()):
        failed = sorted(key for key, passed in assertions.items() if not passed)
        raise RuntimeError(f"Live restore assertions failed: {failed}")

    report = {
        "schema_version": 1,
        "status": "pass",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "provider_requests": 0,
        "es": {
            "url": args.es_url,
            "cluster_name": es_identity.get("cluster_name"),
            "version": (es_identity.get("version") or {}).get("number"),
            "collections": collections,
        },
        "service": {
            "ports": ports,
            "owner_generation": owner_generation,
            "logs": [
                {
                    "path": str(path),
                    "sha256": file_sha256(path),
                }
                for path in service_logs
            ],
        },
        "checkpoint": {
            "path": str(loaded.path),
            "manifest_sha256": loaded.manifest_sha256,
            "records_sha256": loaded.records_sha256,
            "index_config_sha256": loaded.manifest["index_config_sha256"],
            "record_count": len(loaded.records),
        },
        "source_search": source_search,
        "destination_search": destination_search,
        "assertions": assertions,
        "work_root": str(work_root),
    }
    execution_recovery.atomic_write_json(report_path, report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path, help="New or replaceable JSON report path")
    parser.add_argument("--work-root", type=Path)
    parser.add_argument(
        "--appworld-root",
        type=Path,
        default=execution_matrix.DEFAULT_APPWORLD_ROOT,
    )
    parser.add_argument("--service-python", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--es-url", default="http://127.0.0.1:9200")
    parser.add_argument("--ports", type=int, nargs=2)
    args = parser.parse_args()
    try:
        report = run(args)
    except BaseException as error:
        failure = {
            "schema_version": 1,
            "status": "fail",
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "error_type": type(error).__name__,
            "error": str(error),
        }
        execution_recovery.atomic_write_json(args.report.resolve(), failure)
        raise
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
