"""Persistent, provider-free scheduler for the formal ReMe AppWorld campaign.

The scheduler owns only campaign ordering and run-level ownership.  It never
starts Ray, ReMe, AppWorld, Elasticsearch, or a model provider.  A coordinator
claims a run, starts the existing runner with the returned runtime allocation,
and validates the claim generation/token before publishing durable run state.

Ordering is deliberately score-blind:

1. quick2h_test_normal_v2: fixed, dynamic, cold_start;
2. all remaining cells by descending task count;
3. ties by dataset name, arm order (fixed, dynamic, cold_start), repetition,
   then experiment name.

The queue is protected by a POSIX advisory lock and replaced atomically after
every mutation.  Claims do not expire automatically: a missing worker must be
audited and its processes fenced before ``replace_claim`` is called.
"""

from __future__ import annotations

import copy
import fcntl
import hashlib
import json
import os
import re
import secrets
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence


SCHEMA_VERSION = 1
MAX_CONCURRENT_CLAIMS = 3
FIRST_DATASET = "quick2h_test_normal_v2"
ARM_ORDER = {"fixed": 0, "dynamic": 1, "cold_start": 2}
TERMINAL_STATES = {"complete", "stopped"}
CLAIMABLE_STATES = {"pending", "resumable"}
KNOWN_STATES = CLAIMABLE_STATES | TERMINAL_STATES | {"claimed"}
HASH_RE = re.compile(r"[0-9a-f]{64}")


class QueueError(RuntimeError):
    """Base error for an invalid or inconsistent campaign queue."""


class StaleClaim(QueueError):
    """The supplied generation/token no longer owns the run."""


class FrozenManifestMismatch(QueueError):
    """A run manifest no longer matches the campaign's frozen identity."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(payload).hexdigest()


def _manifest_path(manifest: Mapping[str, Any]) -> Path:
    if manifest.get("manifest_path"):
        return Path(str(manifest["manifest_path"])).resolve()
    return (Path(str(manifest["output_root"])) / str(manifest["experiment_name"]) / "run_manifest.json").resolve()


def frozen_manifest_identity(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Return only behavior/source fields that must not change during a run."""

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
    return {key: copy.deepcopy(manifest.get(key)) for key in keys}


def validate_source_hashes(manifest: Mapping[str, Any]) -> None:
    source_hashes = manifest.get("source_sha256")
    if not isinstance(source_hashes, Mapping) or not source_hashes:
        raise FrozenManifestMismatch("Manifest has no source_sha256 mapping")
    for path, digest in source_hashes.items():
        if not isinstance(path, str) or not isinstance(digest, str) or not HASH_RE.fullmatch(digest):
            raise FrozenManifestMismatch("Manifest contains an invalid source SHA-256")
    for key in ("dataset_sha256", "pool_sha256", "shared_logger_sha256"):
        if not isinstance(manifest.get(key), str) or not HASH_RE.fullmatch(str(manifest[key])):
            raise FrozenManifestMismatch(f"Manifest has no valid {key}")
    if not manifest.get("source_commit"):
        raise FrozenManifestMismatch("Manifest has no source commit")


def verify_frozen_manifest(run: Mapping[str, Any], manifest: Mapping[str, Any]) -> None:
    validate_source_hashes(manifest)
    observed = _canonical_hash(frozen_manifest_identity(manifest))
    if observed != run["frozen_manifest_sha256"]:
        raise FrozenManifestMismatch(f"Frozen manifest changed for {run['run_id']}")


def deterministic_run_order(manifests: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Return manifests in the formal campaign's fixed, score-blind order."""

    rows = list(manifests)

    def key(manifest: Mapping[str, Any]) -> tuple[Any, ...]:
        dataset = str(manifest["dataset"])
        arm = str(manifest["arm"])
        if arm not in ARM_ORDER:
            raise QueueError(f"Unknown arm: {arm}")
        tasks = manifest.get("task_ids")
        if not isinstance(tasks, Sequence) or isinstance(tasks, (str, bytes)):
            raise QueueError("task_ids must be an ordered sequence")
        repetition = int(manifest.get("repetition", 1))
        name = str(manifest["experiment_name"])
        if dataset == FIRST_DATASET:
            return (0, ARM_ORDER[arm], repetition, name)
        return (1, -len(tasks), dataset, ARM_ORDER[arm], repetition, name)

    return sorted(rows, key=key)


@dataclass(frozen=True)
class Claim:
    run_id: str
    worker_id: str
    generation: int
    token: str = field(repr=False)
    slot: int = 0
    port: int = 0
    ray_temp_dir: str = ""
    manifest_path: str = ""
    run_root: str = ""

    @classmethod
    def from_run(cls, run: Mapping[str, Any]) -> "Claim":
        claim = run.get("claim")
        if not isinstance(claim, Mapping):
            raise QueueError(f"Run {run.get('run_id')} is not claimed")
        return cls(
            run_id=str(run["run_id"]),
            worker_id=str(claim["worker_id"]),
            generation=int(claim["generation"]),
            token=str(claim["token"]),
            slot=int(claim["slot"]),
            port=int(claim["port"]),
            ray_temp_dir=str(claim["ray_temp_dir"]),
            manifest_path=str(run["manifest_path"]),
            run_root=str(Path(run["manifest_path"]).parent),
        )

    def public_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value.pop("token")
        return value


def _validate_queue(data: Mapping[str, Any]) -> None:
    if data.get("schema_version") != SCHEMA_VERSION:
        raise QueueError("Unsupported queue schema")
    maximum = data.get("max_concurrent_claims")
    if type(maximum) is not int or not 1 <= maximum <= MAX_CONCURRENT_CLAIMS:
        raise QueueError("max_concurrent_claims must be between 1 and 3")
    runs = data.get("runs")
    if not isinstance(runs, list) or not runs:
        raise QueueError("Campaign queue has no runs")
    ids = [run.get("run_id") for run in runs]
    if len(ids) != len(set(ids)):
        raise QueueError("Campaign queue has duplicate run IDs")
    active_slots: list[int] = []
    active_workers: list[str] = []
    active_ray_dirs: list[str] = []
    for position, run in enumerate(runs):
        if run.get("queue_index") != position or run.get("status") not in KNOWN_STATES:
            raise QueueError("Campaign queue ordering/status is corrupt")
        if type(run.get("generation")) is not int or run["generation"] < 0:
            raise QueueError("Campaign queue has an invalid claim generation")
        if run.get("task_count") != len(run.get("task_ids", [])):
            raise QueueError("Campaign queue task count is corrupt")
        claim = run.get("claim")
        if run["status"] == "claimed":
            if not isinstance(claim, Mapping) or int(claim.get("generation", -1)) != int(run["generation"]):
                raise QueueError("Claim metadata is missing or inconsistent")
            slot = int(claim["slot"])
            if not 0 <= slot < maximum or int(claim["port"]) != int(data["base_port"]) + slot:
                raise QueueError("Claim has an invalid runtime slot or port")
            if not claim.get("token") or not claim.get("worker_id") or not claim.get("ray_temp_dir"):
                raise QueueError("Claim ownership/runtime identity is incomplete")
            active_slots.append(slot)
            active_workers.append(str(claim["worker_id"]))
            active_ray_dirs.append(str(claim["ray_temp_dir"]))
        elif claim is not None:
            raise QueueError("Unclaimed run retains claim metadata")
    if len(active_slots) > maximum or len(active_slots) != len(set(active_slots)):
        raise QueueError("Campaign has too many claims or duplicate worker slots")
    if len(active_workers) != len(set(active_workers)) or len(active_ray_dirs) != len(set(active_ray_dirs)):
        raise QueueError("A worker or Ray directory is assigned to multiple active runs")


class CampaignQueue:
    """Atomic persistent queue with exclusive generation-token run claims."""

    def __init__(self, path: os.PathLike[str] | str):
        self.path = Path(path).resolve()
        self.lock_path = self.path.with_suffix(self.path.suffix + ".lock")

    @contextmanager
    def _lock(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+", encoding="utf-8") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)

    def _read(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError as error:
            raise QueueError(f"Campaign queue does not exist: {self.path}") from error
        except json.JSONDecodeError as error:
            raise QueueError(f"Campaign queue is invalid JSON: {self.path}") from error
        _validate_queue(data)
        return data

    def _write(self, data: dict[str, Any]) -> None:
        _validate_queue(data)
        temporary = self.path.with_name(f".{self.path.name}.{os.getpid()}.{secrets.token_hex(8)}.tmp")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(data, stream, indent=2, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            directory = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if temporary.exists():
                temporary.unlink()

    @classmethod
    def create(
        cls,
        path: os.PathLike[str] | str,
        manifests: Iterable[Mapping[str, Any]],
        runtime_root: os.PathLike[str] | str,
        *,
        base_port: int = 18101,
        max_concurrent_claims: int = MAX_CONCURRENT_CLAIMS,
        require_source_hashes: bool = True,
    ) -> "CampaignQueue":
        if not 1 <= max_concurrent_claims <= MAX_CONCURRENT_CLAIMS:
            raise ValueError("Formal campaign concurrency must be between 1 and 3")
        if not 1024 <= base_port <= 65535 - max_concurrent_claims:
            raise ValueError("Invalid worker service port range")
        ordered = deterministic_run_order(manifests)
        if not ordered:
            raise ValueError("Cannot create an empty campaign queue")
        campaigns = {manifest.get("campaign") for manifest in ordered}
        if len(campaigns) != 1:
            raise QueueError("All run manifests must belong to one campaign")
        records = []
        for index, manifest in enumerate(ordered):
            if require_source_hashes:
                validate_source_hashes(manifest)
            run_id = str(manifest["experiment_name"])
            records.append(
                {
                    "queue_index": index,
                    "run_id": run_id,
                    "dataset": str(manifest["dataset"]),
                    "arm": str(manifest["arm"]),
                    "repetition": int(manifest.get("repetition", 1)),
                    "task_count": len(manifest["task_ids"]),
                    "task_ids": list(manifest["task_ids"]),
                    "manifest_path": str(_manifest_path(manifest)),
                    "frozen_manifest_sha256": _canonical_hash(frozen_manifest_identity(manifest)),
                    "status": "pending",
                    "generation": 0,
                    "claim": None,
                    "completed_task_ids": [],
                    "last_rebuild": None,
                }
            )
        queue = cls(path)
        data = {
            "schema_version": SCHEMA_VERSION,
            "campaign": next(iter(campaigns)),
            "created_at": utc_now(),
            "updated_at": utc_now(),
            "revision": 0,
            "max_concurrent_claims": max_concurrent_claims,
            "base_port": base_port,
            "ray_temp_root": str(Path(runtime_root).resolve() / "ray"),
            "runs": records,
        }
        with queue._lock():
            if queue.path.exists():
                raise FileExistsError(f"Campaign queue already exists: {queue.path}")
            queue._write(data)
        return queue

    def snapshot(self) -> dict[str, Any]:
        with self._lock():
            return copy.deepcopy(self._read())

    @staticmethod
    def _find(data: Mapping[str, Any], run_id: str) -> dict[str, Any]:
        for run in data["runs"]:
            if run["run_id"] == run_id:
                return run
        raise QueueError(f"Unknown run: {run_id}")

    @staticmethod
    def _matches(run: Mapping[str, Any], claim: Claim) -> bool:
        current = run.get("claim") or {}
        return (
            run.get("status") == "claimed"
            and run.get("run_id") == claim.run_id
            and current.get("worker_id") == claim.worker_id
            and current.get("generation") == claim.generation
            and secrets.compare_digest(str(current.get("token", "")), claim.token)
        )

    def _commit(self, data: dict[str, Any]) -> None:
        data["revision"] += 1
        data["updated_at"] = utc_now()
        self._write(data)

    @staticmethod
    def _new_claim(data: Mapping[str, Any], run: dict[str, Any], worker_id: str, slot: int) -> Claim:
        generation = int(run["generation"]) + 1
        token = secrets.token_hex(24)
        # Ray appends a long session/sockets suffix and AF_UNIX permits only
        # 107 bytes on Linux. The random owner token keeps this short path
        # unique across campaigns, runs, generations, and slots.
        ray_temp_dir = Path(data["ray_temp_root"]) / token[:12]
        run["generation"] = generation
        run["status"] = "claimed"
        run["claim"] = {
            "worker_id": worker_id,
            "generation": generation,
            "token": token,
            "slot": slot,
            "port": int(data["base_port"]) + slot,
            "ray_temp_dir": str(ray_temp_dir),
            "claimed_at": utc_now(),
            "heartbeat_at": utc_now(),
        }
        return Claim.from_run(run)

    def claim_next(self, worker_id: str, *, dataset: str | None = None) -> Claim | None:
        if not worker_id or not re.fullmatch(r"[a-zA-Z0-9_.:-]{1,128}", worker_id):
            raise ValueError("worker_id must be a short path-safe identifier")
        with self._lock():
            data = self._read()
            owned = [run for run in data["runs"] if (run.get("claim") or {}).get("worker_id") == worker_id]
            if len(owned) > 1:
                raise QueueError("Worker owns more than one run")
            if owned:
                return Claim.from_run(owned[0])
            active = [run for run in data["runs"] if run["status"] == "claimed"]
            if len(active) >= data["max_concurrent_claims"]:
                return None
            run = next(
                (
                    candidate
                    for candidate in data["runs"]
                    if candidate["status"] in CLAIMABLE_STATES and (dataset is None or candidate["dataset"] == dataset)
                ),
                None,
            )
            if run is None:
                return None
            path = Path(run["manifest_path"])
            if not path.is_file():
                raise FrozenManifestMismatch(f"Run manifest is missing: {path}")
            verify_frozen_manifest(run, json.loads(path.read_text(encoding="utf-8")))
            used_slots = {int(candidate["claim"]["slot"]) for candidate in active}
            slot = next(slot for slot in range(data["max_concurrent_claims"]) if slot not in used_slots)
            claim = self._new_claim(data, run, worker_id, slot)
            self._commit(data)
            return claim

    def validate_claim(self, claim: Claim) -> bool:
        with self._lock():
            data = self._read()
            return self._matches(self._find(data, claim.run_id), claim)

    def acquire_recovery_claim(self, claim: Claim):
        """Acquire the optional run-local recovery lock for a queue claim.

        The returned ``execution_recovery.RunClaim`` must remain held by the
        worker for its whole run attempt.  Its generation is a separate,
        run-local fence; the shared owner token joins it to this queue claim.
        """

        if not self.validate_claim(claim):
            raise StaleClaim(f"Stale queue claim for {claim.run_id}")
        try:
            from execution_recovery import RunClaim
        except ImportError as error:
            raise QueueError("execution_recovery is unavailable") from error
        recovery_claim = RunClaim.acquire(claim.run_root, claim.run_id, owner_token=claim.token, blocking=False)
        if not self.validate_claim(claim):
            recovery_claim.release()
            raise StaleClaim(f"Queue claim changed while acquiring recovery lock for {claim.run_id}")
        return recovery_claim

    def heartbeat(self, claim: Claim) -> None:
        with self._lock():
            data = self._read()
            run = self._find(data, claim.run_id)
            if not self._matches(run, claim):
                raise StaleClaim(f"Stale claim for {claim.run_id}")
            run["claim"]["heartbeat_at"] = utc_now()
            self._commit(data)

    def finish_claim(self, claim: Claim, status: str, completed_task_ids: Sequence[str] | None = None) -> None:
        if status not in CLAIMABLE_STATES | TERMINAL_STATES:
            raise ValueError("A released claim must become pending, resumable, complete, or stopped")
        with self._lock():
            data = self._read()
            run = self._find(data, claim.run_id)
            if not self._matches(run, claim):
                raise StaleClaim(f"Stale claim for {claim.run_id}")
            committed = list(completed_task_ids if completed_task_ids is not None else run["completed_task_ids"])
            self._validate_prefix(run, committed)
            if status == "pending" and committed:
                raise QueueError("A run with committed tasks must be resumable, not pending")
            if status == "complete" and committed != run["task_ids"]:
                raise QueueError("A complete run must commit every task")
            run.update(status=status, claim=None, completed_task_ids=committed)
            self._commit(data)

    def replace_claim(self, previous: Claim, worker_id: str) -> Claim:
        """Fence a verified old claim and mint a new generation/token.

        The coordinator must stop or otherwise fence the old owned processes
        before calling this method.  The scheduler cannot kill external state.
        """

        if not worker_id or not re.fullmatch(r"[a-zA-Z0-9_.:-]{1,128}", worker_id):
            raise ValueError("worker_id must be a short path-safe identifier")
        with self._lock():
            data = self._read()
            run = self._find(data, previous.run_id)
            if not self._matches(run, previous):
                raise StaleClaim(f"Stale claim for {previous.run_id}")
            if any(
                candidate["run_id"] != run["run_id"] and (candidate.get("claim") or {}).get("worker_id") == worker_id
                for candidate in data["runs"]
            ):
                raise QueueError("Replacement worker already owns another run")
            slot = int(run["claim"]["slot"])
            replacement = self._new_claim(data, run, worker_id, slot)
            self._commit(data)
            return replacement

    @staticmethod
    def _validate_prefix(run: Mapping[str, Any], committed: Sequence[str]) -> None:
        if list(committed) != list(run["task_ids"][: len(committed)]):
            raise QueueError(f"Committed tasks are not a dataset-order prefix for {run['run_id']}")

    def verify_manifest(self, run_id: str, loader: Callable[[Path], Mapping[str, Any]] | None = None) -> None:
        loader = loader or (lambda path: json.loads(path.read_text(encoding="utf-8")))
        with self._lock():
            run = copy.deepcopy(self._find(self._read(), run_id))
        verify_frozen_manifest(run, loader(Path(run["manifest_path"])))

    def rebuild_statuses(
        self,
        resolver: Callable[[Mapping[str, Any]], Mapping[str, Any] | str],
        *,
        preserve_claims: bool = True,
    ) -> dict[str, Any]:
        """Rebuild queue indexes from authoritative, caller-resolved run state.

        ``resolver`` may inspect manifests, immutable commit markers, or another
        durable store.  It returns a state string or a mapping with ``status``
        and optional ``completed_task_ids``.  Existing claims are preserved by
        default; set ``preserve_claims=False`` only after process ownership has
        been audited and old writers have been fenced.
        """

        with self._lock():
            data = self._read()
            for run in data["runs"]:
                observation = resolver(copy.deepcopy(run))
                if isinstance(observation, str):
                    observation = {"status": observation}
                status = str(observation["status"])
                if status not in CLAIMABLE_STATES | TERMINAL_STATES:
                    raise QueueError(f"Invalid rebuilt status for {run['run_id']}: {status}")
                committed = list(observation.get("completed_task_ids", run["completed_task_ids"]))
                self._validate_prefix(run, committed)
                if status == "complete" and committed != run["task_ids"]:
                    raise QueueError("A complete rebuilt run must commit every task")
                run["completed_task_ids"] = committed
                run["last_rebuild"] = utc_now()
                if run["status"] == "claimed" and preserve_claims and status != "complete":
                    continue
                run["status"] = status
                run["claim"] = None
            self._commit(data)
            return copy.deepcopy(data)

    def rebuild_from_manifests(
        self,
        *,
        manifest_loader: Callable[[Path], Mapping[str, Any]] | None = None,
        committed_loader: Callable[[Mapping[str, Any], Mapping[str, Any]], Sequence[str]] | None = None,
        preserve_claims: bool = True,
    ) -> dict[str, Any]:
        manifest_loader = manifest_loader or (lambda path: json.loads(path.read_text(encoding="utf-8")))

        def resolve(run: Mapping[str, Any]) -> Mapping[str, Any]:
            path = Path(str(run["manifest_path"]))
            if not path.is_file():
                return {"status": "stopped", "completed_task_ids": run["completed_task_ids"]}
            manifest = manifest_loader(path)
            verify_frozen_manifest(run, manifest)
            committed = list(
                committed_loader(run, manifest)
                if committed_loader is not None
                else manifest.get("completed_task_ids", [])
            )
            self._validate_prefix(run, committed)
            manifest_status = manifest.get("status")
            if manifest_status == "complete":
                status = "complete" if committed == run["task_ids"] else "stopped"
            elif manifest_status == "planned" and not committed:
                status = "pending"
            elif manifest_status in {"planned", "running", "incomplete"}:
                status = "resumable"
            else:
                status = "stopped"
            return {"status": status, "completed_task_ids": committed}

        return self.rebuild_statuses(resolve, preserve_claims=preserve_claims)
