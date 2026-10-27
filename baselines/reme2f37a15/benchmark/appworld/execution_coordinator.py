"""Three-worker coordinator for the formal ReMe AppWorld campaign.

This module requires an already planned, source-hashed 12-run campaign.  It
does not create run manifests.  It creates or reloads one persistent
``CampaignQueue``, supervises at most three worker processes, and delegates one
complete run at a time to ``execution_matrix.execute_run``.

The first three queue entries are the quick2h-normal-v2 arms.  No later cell is
claimed until all three have at least one authoritative recovery commit.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import multiprocessing
import os
import queue as queue_module
import re
import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import urlparse

import execution_accounting
import execution_matrix
import execution_recovery
from execution_scheduler import (
    CLAIMABLE_STATES,
    FIRST_DATASET,
    CampaignQueue,
    Claim,
    FrozenManifestMismatch,
    QueueError,
    StaleClaim,
)


WORKERS = 3
DEFAULT_BASE_PORT = 18101
DEFAULT_RAY_RUNTIME_ROOT = Path("/tmp/rr")
EVENTS_FILE = "coordinator_events.jsonl"
SUMMARY_FILE = "coordinator_summary.json"


class CoordinatorError(RuntimeError):
    """Campaign coordination cannot continue safely."""


@dataclass(frozen=True)
class CoordinatorConfig:
    campaign: str
    queue_path: str
    runtime_root: str
    appworld_root: str
    service_python: str
    es_url: str
    task_timeout: int
    heartbeat_interval: float = 15.0
    poll_interval: float = 1.0
    max_supervisor_attempts: int = 3

    @property
    def event_path(self) -> Path:
        return Path(self.queue_path).parent / EVENTS_FILE

    @property
    def summary_path(self) -> Path:
        return Path(self.queue_path).parent / SUMMARY_FILE


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CoordinatorError(f"Cannot read JSON: {path}") from error
    if not isinstance(value, dict):
        raise CoordinatorError(f"Expected a JSON object: {path}")
    return value


def append_event(path: Path, event: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            stream.seek(0, os.SEEK_END)
            stream.write(json.dumps(dict(event), sort_keys=True, allow_nan=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


@contextmanager
def coordinator_lease(queue_path: Path):
    """Ensure only one coordinator parent actively supervises the queue."""

    lock_path = queue_path.with_suffix(queue_path.suffix + ".coordinator.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise CoordinatorError(f"Another coordinator owns {queue_path}") from error
        yield
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def _manifest_map(manifests: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    result = {str(manifest.get("experiment_name")): manifest for manifest in manifests}
    if len(result) != len(manifests) or any(not name for name in result):
        raise CoordinatorError("Campaign manifests have missing or duplicate experiment names")
    return result


def load_existing_campaign_manifests(
    appworld_root: Path,
    campaign: str,
    *,
    loader: Callable[[str], Sequence[str]] | None = None,
) -> list[dict[str, Any]]:
    """Load exactly the current 12 source-hashed manifests; never plan them."""

    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,39}", campaign):
        raise CoordinatorError("Campaign must be a short lowercase path-safe identifier")
    root = Path(appworld_root).resolve(strict=True)
    expected = execution_matrix.build_matrix(root, campaign, loader)
    expected_by_name = _manifest_map(expected)
    outputs = root / "experiments/outputs"
    paths = sorted(outputs.glob(f"reme_{campaign}_*_run_0/run_manifest.json"))
    observed = [read_json(path) for path in paths]
    observed_by_name = _manifest_map(observed)
    if len(expected) != 12 or set(observed_by_name) != set(expected_by_name):
        raise CoordinatorError("Existing campaign must contain exactly the expected 12 run manifests")
    for name, manifest in observed_by_name.items():
        if execution_matrix.frozen_manifest_sha256(manifest) != execution_matrix.frozen_manifest_sha256(
            expected_by_name[name]
        ):
            raise FrozenManifestMismatch(f"Existing manifest is stale or source/config changed: {name}")
        expected_path = outputs / name / "run_manifest.json"
        manifest["manifest_path"] = str(expected_path.resolve(strict=True))
    return [observed_by_name[manifest["experiment_name"]] for manifest in expected]


def _require_fresh_manifests(manifests: Sequence[Mapping[str, Any]]) -> None:
    for manifest in manifests:
        root = Path(str(manifest["manifest_path"])).parent
        if manifest.get("status") != "planned" or manifest.get("completed_task_ids"):
            raise CoordinatorError(f"New queue requires a fresh planned manifest: {root.name}")
        recovery_root = root / execution_recovery.RECOVERY_DIRECTORY
        if (
            (root / "tasks").exists()
            or (recovery_root / "commits").exists()
            or (recovery_root / "checkpoints").exists()
        ):
            raise CoordinatorError(f"New queue refuses existing task/recovery state: {root.name}")


def create_or_load_queue(
    queue_path: Path,
    manifests: Sequence[Mapping[str, Any]],
    runtime_root: Path,
    *,
    base_port: int = DEFAULT_BASE_PORT,
) -> CampaignQueue:
    queue_path = Path(queue_path).resolve()
    if queue_path.exists():
        campaign_queue = CampaignQueue(queue_path)
        snapshot = campaign_queue.snapshot()
        expected = _manifest_map(manifests)
        if snapshot["campaign"] != next(iter({manifest["campaign"] for manifest in manifests})):
            raise CoordinatorError("Queue campaign differs from the run manifests")
        if {run["run_id"] for run in snapshot["runs"]} != set(expected):
            raise CoordinatorError("Queue runs differ from the current manifest set")
        for run in snapshot["runs"]:
            campaign_queue.verify_manifest(run["run_id"])
        return campaign_queue
    _require_fresh_manifests(manifests)
    return CampaignQueue.create(
        queue_path,
        manifests,
        runtime_root,
        base_port=base_port,
        max_concurrent_claims=WORKERS,
    )


def discover_committed_task_ids(run_root: Path, manifest: Mapping[str, Any]) -> list[str]:
    prefix = execution_recovery.discover_committed_prefix(
        run_root,
        manifest["task_ids"],
        execution_matrix.frozen_manifest_sha256(manifest),
        expected_dimensions=manifest["embedding_dimensions"],
    )
    return list(prefix.task_ids)


def _run_manifest(run: Mapping[str, Any]) -> dict[str, Any]:
    return read_json(Path(str(run["manifest_path"])))


def first_wave_state(
    campaign_queue: CampaignQueue,
    prefix_reader: Callable[[Path, Mapping[str, Any]], Sequence[str]] = discover_committed_task_ids,
) -> dict[str, Any]:
    snapshot = campaign_queue.snapshot()
    first = [run for run in snapshot["runs"] if run["dataset"] == FIRST_DATASET]
    if len(first) != WORKERS:
        raise CoordinatorError("Queue must contain exactly three quick2h-normal-v2 first-wave runs")
    details = []
    for run in first:
        manifest = _run_manifest(run)
        committed = list(prefix_reader(Path(run["manifest_path"]).parent, manifest))
        details.append(
            {
                "run_id": run["run_id"],
                "queue_status": run["status"],
                "committed_tasks": len(committed),
            }
        )
    released = all(item["committed_tasks"] >= 1 for item in details)
    blocked = any(item["queue_status"] == "stopped" and item["committed_tasks"] == 0 for item in details)
    return {"released": released, "blocked": blocked, "runs": details}


def _owned_claim(snapshot: Mapping[str, Any], worker_id: str) -> Claim | None:
    owned = [run for run in snapshot["runs"] if (run.get("claim") or {}).get("worker_id") == worker_id]
    if len(owned) > 1:
        raise CoordinatorError(f"Worker owns multiple runs: {worker_id}")
    return Claim.from_run(owned[0]) if owned else None


def _may_claim(
    campaign_queue: CampaignQueue,
    worker_id: str,
    prefix_reader: Callable[[Path, Mapping[str, Any]], Sequence[str]],
) -> tuple[bool, dict[str, Any]]:
    snapshot = campaign_queue.snapshot()
    if _owned_claim(snapshot, worker_id) is not None:
        return True, {"released": False, "blocked": False, "runs": []}
    gate = first_wave_state(campaign_queue, prefix_reader)
    if gate["blocked"]:
        return False, gate
    if gate["released"]:
        return True, gate
    first_claimable = any(
        run["dataset"] == FIRST_DATASET and run["status"] in CLAIMABLE_STATES for run in snapshot["runs"]
    )
    return first_claimable, gate


class Heartbeat:
    def __init__(self, campaign_queue: CampaignQueue, claim: Claim, interval: float):
        self.queue = campaign_queue
        self.claim = claim
        self.interval = interval
        self.stop_event = threading.Event()
        self.error: BaseException | None = None
        self.thread = threading.Thread(target=self._run, name=f"heartbeat-{claim.worker_id}", daemon=True)

    def _run(self) -> None:
        while not self.stop_event.wait(self.interval):
            try:
                self.queue.heartbeat(self.claim)
            except BaseException as error:
                self.error = error
                return

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.stop_event.set()
        self.thread.join(timeout=max(1.0, self.interval * 2))


def _emit(event_queue, event: str, **values) -> None:
    event_queue.put({"at": execution_matrix.now(), "event": event, **values})


def _failure_status(error: BaseException, claim: Claim, max_attempts: int) -> str:
    fail_closed = (
        execution_recovery.RecoveryError,
        execution_accounting.AccountingError,
        FrozenManifestMismatch,
        QueueError,
    )
    if isinstance(error, fail_closed) or claim.generation >= max_attempts:
        return "stopped"
    return "resumable"


def worker_main(
    config: CoordinatorConfig,
    worker_index: int,
    stop_event,
    event_queue,
    runner: Callable[..., Any] = execution_matrix.execute_run,
    prefix_reader: Callable[[Path, Mapping[str, Any]], Sequence[str]] = discover_committed_task_ids,
) -> None:
    """Persistent worker loop; safe to use as a multiprocessing target."""

    worker_id = f"{config.campaign}-worker-{worker_index}"
    campaign_queue = CampaignQueue(config.queue_path)
    execution_matrix.configure_appworld(Path(config.appworld_root))
    os.environ["APPWORLD_LM_LOGGER_MODULE_PATH"] = str(
        Path(config.appworld_root) / "experiments/code/common/lm_logger.py"
    )
    _emit(event_queue, "worker_started", worker_id=worker_id)
    while not stop_event.is_set():
        allowed, gate = _may_claim(campaign_queue, worker_id, prefix_reader)
        if gate.get("blocked"):
            _emit(event_queue, "first_wave_blocked", worker_id=worker_id, gate=gate)
            stop_event.set()
            break
        if not allowed:
            if all(run["status"] in {"complete", "stopped"} for run in campaign_queue.snapshot()["runs"]):
                break
            stop_event.wait(config.poll_interval)
            continue
        # Keep the first-wave restriction inside the queue's atomic claim
        # transaction.  Another worker may claim the last eligible first-wave
        # row after _may_claim() returns but before this process acquires the
        # queue lock; an unconstrained claim would then leak into wave two.
        claim = campaign_queue.claim_next(worker_id, dataset=None if gate["released"] else FIRST_DATASET)
        if claim is None:
            if all(run["status"] in {"complete", "stopped"} for run in campaign_queue.snapshot()["runs"]):
                break
            stop_event.wait(config.poll_interval)
            continue
        _emit(
            event_queue, "run_claimed", worker_id=worker_id, claim=claim.public_dict(), gate_released=gate["released"]
        )
        manifest = read_json(Path(claim.manifest_path))
        completed: list[str] = []
        status = "stopped"
        error: BaseException | None = None
        try:
            try:
                recovery_claim = campaign_queue.acquire_recovery_claim(claim)
            except execution_recovery.ClaimBusy:
                _emit(event_queue, "reattach_wait", worker_id=worker_id, run_id=claim.run_id)
                stop_event.wait(config.poll_interval)
                continue
            with recovery_claim:
                campaign_queue.verify_manifest(claim.run_id)
                with Heartbeat(campaign_queue, claim, config.heartbeat_interval) as heartbeat:
                    runner(
                        manifest,
                        Path(config.service_python),
                        config.es_url,
                        port=claim.port,
                        task_timeout=config.task_timeout,
                        ray_temp_dir=claim.ray_temp_dir,
                        claim=recovery_claim,
                    )
                    if heartbeat.error is not None:
                        raise heartbeat.error
                manifest = read_json(Path(claim.manifest_path))
                completed = list(prefix_reader(Path(claim.run_root), manifest))
                status = (
                    "complete"
                    if completed == list(manifest["task_ids"]) and manifest.get("status") == "complete"
                    else "resumable"
                )
        except BaseException as caught:
            error = caught
            try:
                manifest = read_json(Path(claim.manifest_path))
                completed = list(prefix_reader(Path(claim.run_root), manifest))
            except BaseException as prefix_error:
                error = prefix_error
                completed = []
            status = _failure_status(error, claim, config.max_supervisor_attempts)
        try:
            campaign_queue.finish_claim(claim, status, completed)
        except StaleClaim:
            _emit(event_queue, "stale_finish_rejected", worker_id=worker_id, run_id=claim.run_id)
            stop_event.set()
            break
        _emit(
            event_queue,
            "run_finished",
            worker_id=worker_id,
            run_id=claim.run_id,
            status=status,
            committed_tasks=len(completed),
            error_type=type(error).__name__ if error is not None else None,
        )
        if status == "stopped" and manifest.get("dataset") == FIRST_DATASET and not completed:
            stop_event.set()
            break
    _emit(event_queue, "worker_finished", worker_id=worker_id)


class Coordinator:
    def __init__(
        self,
        config: CoordinatorConfig,
        *,
        runner: Callable[..., Any] = execution_matrix.execute_run,
        prefix_reader: Callable[[Path, Mapping[str, Any]], Sequence[str]] = discover_committed_task_ids,
        start_method: str = "spawn",
    ):
        self.config = config
        self.runner = runner
        self.prefix_reader = prefix_reader
        self.context = multiprocessing.get_context(start_method)

    def _drain(self, events, collected: list[dict[str, Any]]) -> None:
        while True:
            try:
                event = events.get_nowait()
            except queue_module.Empty:
                return
            append_event(self.config.event_path, event)
            collected.append(event)

    def run(self) -> dict[str, Any]:
        with coordinator_lease(Path(self.config.queue_path)):
            return self._run_locked()

    def _run_locked(self) -> dict[str, Any]:
        campaign_queue = CampaignQueue(self.config.queue_path)
        stop_event = self.context.Event()
        events = self.context.Queue()
        processes = [
            self.context.Process(
                target=worker_main,
                name=f"reme-{self.config.campaign}-worker-{index}",
                args=(self.config, index, stop_event, events, self.runner, self.prefix_reader),
            )
            for index in range(WORKERS)
        ]
        collected: list[dict[str, Any]] = []
        append_event(
            self.config.event_path,
            {"at": execution_matrix.now(), "event": "coordinator_started", "config": asdict(self.config)},
        )
        for process in processes:
            process.start()
        abnormal: list[dict[str, Any]] = []
        interrupted = False
        gate_reported = False
        try:
            while True:
                self._drain(events, collected)
                snapshot = campaign_queue.snapshot()
                terminal = all(run["status"] in {"complete", "stopped"} for run in snapshot["runs"])
                if not gate_reported:
                    gate = first_wave_state(campaign_queue, self.prefix_reader)
                    if gate["released"]:
                        append_event(
                            self.config.event_path,
                            {"at": execution_matrix.now(), "event": "first_wave_released", "gate": gate},
                        )
                        gate_reported = True
                    elif gate["blocked"]:
                        stop_event.set()
                for process in processes:
                    if process.exitcode not in (None, 0) and not any(row["worker"] == process.name for row in abnormal):
                        row = {"worker": process.name, "exitcode": process.exitcode}
                        abnormal.append(row)
                        append_event(
                            self.config.event_path,
                            {"at": execution_matrix.now(), "event": "worker_crashed", **row},
                        )
                        stop_event.set()
                # A stop request prevents new claims, but workers already inside
                # execute_run must reach their own safe boundary and release the
                # run-local recovery lock.  Never terminate a healthy active run
                # merely because another first-wave run stopped.
                if terminal or all(process.exitcode is not None for process in processes):
                    break
                time.sleep(self.config.poll_interval)
        except KeyboardInterrupt:
            interrupted = True
            stop_event.set()
        finally:
            stop_event.set()
            for process in processes:
                process.join(timeout=max(2.0, self.config.poll_interval * 4))
            for process in processes:
                if process.is_alive():
                    # This branch is expected only after all queue rows became
                    # terminal but a polling worker failed to observe the stop.
                    # An active-run shutdown waits in the supervision loop above.
                    process.terminate()
                    process.join(timeout=5)
                    abnormal.append({"worker": process.name, "exitcode": process.exitcode, "terminated": True})
            self._drain(events, collected)
            events.close()
            events.join_thread()
        snapshot = campaign_queue.snapshot()
        counts = {
            status: sum(run["status"] == status for run in snapshot["runs"])
            for status in ("pending", "resumable", "claimed", "complete", "stopped")
        }
        summary = {
            "campaign": self.config.campaign,
            "queue_path": self.config.queue_path,
            "finished_at": execution_matrix.now(),
            "status": "complete" if counts["complete"] == len(snapshot["runs"]) else "incomplete",
            "counts": counts,
            "worker_failures": abnormal,
            "interrupted": interrupted,
            "event_count": len(collected),
        }
        execution_recovery.atomic_write_json(self.config.summary_path, summary)
        append_event(self.config.event_path, {"at": execution_matrix.now(), "event": "coordinator_finished", **summary})
        return summary


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute-formal", action="store_true", help="Required acknowledgement; makes provider calls")
    parser.add_argument("--appworld-root", type=Path, required=True)
    parser.add_argument("--campaign", required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--formal-accounting", type=Path, required=True)
    parser.add_argument("--service-python", type=Path, required=True)
    parser.add_argument("--es-url", required=True)
    parser.add_argument("--task-timeout", type=positive_int, required=True)
    parser.add_argument("--queue-file", type=Path)
    parser.add_argument("--runtime-root", type=Path)
    parser.add_argument("--base-port", type=int, default=DEFAULT_BASE_PORT)
    parser.add_argument("--heartbeat-interval", type=float, default=15.0)
    parser.add_argument("--poll-interval", type=float, default=1.0)
    return parser


def service_python_path(path: Path) -> Path:
    """Return an absolute executable path without resolving a venv symlink."""

    executable = Path(os.path.abspath(path.expanduser()))
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise CoordinatorError("service-python must be an executable file")
    return executable


def _validate_cli(args) -> tuple[Path, Path, Path]:
    if not args.execute_formal:
        raise CoordinatorError("Refusing to run without --execute-formal")
    if args.heartbeat_interval <= 0 or args.poll_interval <= 0:
        raise CoordinatorError("Heartbeat and poll intervals must be positive")
    if not 1024 <= args.base_port <= 65533:
        raise CoordinatorError("base-port must leave three valid service ports")
    service_python = service_python_path(args.service_python)
    parsed = urlparse(args.es_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise CoordinatorError("es-url must be an absolute HTTP(S) URL")
    appworld_root = args.appworld_root.resolve(strict=True)
    outputs = appworld_root / "experiments/outputs"
    campaign_state = outputs / ".reme-formal-campaigns" / args.campaign
    queue_path = (args.queue_file or campaign_state / "queue.json").resolve()
    runtime_root = (args.runtime_root or DEFAULT_RAY_RUNTIME_ROOT).resolve()
    # Leave room for /<claim-token>/<attempt-hash>/session_.../sockets/plasma_store.
    if len(str(runtime_root / "ray" / ("x" * 12) / ("x" * 8))) > 39:
        raise CoordinatorError("runtime-root is too long for Ray AF_UNIX socket paths")
    return queue_path, runtime_root, service_python


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        queue_path, runtime_root, service_python = _validate_cli(args)
        os.environ.pop(execution_accounting.SMOKE_ENVIRONMENT_KEY, None)
        os.environ[execution_accounting.ENVIRONMENT_KEY] = str(args.formal_accounting.resolve(strict=True))
        execution_accounting.policy()
        execution_matrix.load_provider_environment(args.env_file.resolve(strict=True))
        root = execution_matrix.configure_appworld(args.appworld_root)
        os.environ["APPWORLD_LM_LOGGER_MODULE_PATH"] = str(root / "experiments/code/common/lm_logger.py")
        from appworld import load_task_ids

        manifests = load_existing_campaign_manifests(root, args.campaign, loader=load_task_ids)
        create_or_load_queue(queue_path, manifests, runtime_root, base_port=args.base_port)
        config = CoordinatorConfig(
            campaign=args.campaign,
            queue_path=str(queue_path),
            runtime_root=str(runtime_root),
            appworld_root=str(root),
            service_python=str(service_python),
            es_url=args.es_url,
            task_timeout=args.task_timeout,
            heartbeat_interval=args.heartbeat_interval,
            poll_interval=args.poll_interval,
        )
        summary = Coordinator(config).run()
        print(json.dumps(summary, sort_keys=True))
        return 0 if summary["status"] == "complete" else 1
    except (CoordinatorError, QueueError, execution_accounting.AccountingError, OSError, ValueError) as error:
        print(
            json.dumps({"status": "refused", "error_type": type(error).__name__, "error": str(error)}), file=sys.stderr
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
