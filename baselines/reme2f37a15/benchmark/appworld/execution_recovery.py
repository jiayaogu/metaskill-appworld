"""Durable recovery primitives for ordered AppWorld/ReMe runs.

This module is deliberately independent from the live execution driver.  It
contains only local-filesystem state transitions and checkpoint validation, so
its behavior can be tested without AppWorld, Elasticsearch, or provider calls.
"""

from __future__ import annotations

import errno
import fcntl
import hashlib
import json
import math
import os
import shutil
import socket
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


SCHEMA_VERSION = 1
DEFAULT_MAX_RESTARTS = 2
RECOVERY_DIRECTORY = Path("baseline_artifacts/reme/recovery")
CHECKPOINT_DIRECTORY = RECOVERY_DIRECTORY / "checkpoints"
COMMIT_DIRECTORY = RECOVERY_DIRECTORY / "commits"
CLAIM_FILE = RECOVERY_DIRECTORY / "claim.json"
CLAIM_LOCK_FILE = RECOVERY_DIRECTORY / "claim.lock"
RETRY_FILE = RECOVERY_DIRECTORY / "retries.json"


class RecoveryError(RuntimeError):
    """Base class for corrupt or conflicting durable recovery state."""


class ClaimBusy(RecoveryError):
    """Another process currently owns the run claim lock."""


class StaleOwner(RecoveryError):
    """An operation was attempted by an owner that has been fenced out."""


class CommitConflict(RecoveryError):
    """An immutable commit path already contains different bytes."""


class RetryLimitExceeded(RecoveryError):
    """The bounded infrastructure-restart allowance is exhausted."""


def _now() -> str:
    # AppWorld may monkeypatch datetime/time.time. CLOCK_REALTIME remains the
    # operating-system wall clock used by the audit layer.
    return datetime.fromtimestamp(time.clock_gettime(time.CLOCK_REALTIME), timezone.utc).isoformat()


def canonical_json_bytes(value: Any) -> bytes:
    """Return deterministic UTF-8 JSON bytes suitable for hashing."""

    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def json_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _ensure_directory(path: Path) -> None:
    """Create and durably publish every missing directory component."""

    path = path.resolve()
    missing: list[Path] = []
    cursor = path
    while not cursor.exists():
        missing.append(cursor)
        cursor = cursor.parent
    if not cursor.is_dir():
        raise NotADirectoryError(cursor)
    for directory in reversed(missing):
        try:
            os.mkdir(directory)
        except FileExistsError:
            if not directory.is_dir():
                raise
        _fsync_directory(directory.parent)
        _fsync_directory(directory)


def _write_synced_temporary(target: Path, payload: bytes, mode: int = 0o600) -> Path:
    temporary = target.parent / f".{target.name}.{uuid.uuid4().hex}.tmp"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise
    return temporary


def atomic_write_bytes(path: str | Path, payload: bytes, mode: int = 0o600) -> None:
    """Replace one file atomically and fsync both its data and directory entry."""

    path = Path(path)
    _ensure_directory(path.parent)
    temporary = _write_synced_temporary(path, payload, mode)
    try:
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    except BaseException:
        try:
            temporary.unlink()
            _fsync_directory(path.parent)
        except FileNotFoundError:
            pass
        raise


def atomic_write_json(path: str | Path, value: Any) -> None:
    payload = json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True).encode() + b"\n"
    atomic_write_bytes(path, payload)


def atomic_write_jsonl(path: str | Path, rows: Iterable[Any]) -> None:
    payload = b"".join(canonical_json_bytes(row) + b"\n" for row in rows)
    atomic_write_bytes(path, payload)


def publish_immutable_json(path: str | Path, value: Any) -> bool:
    """Publish JSON without replacement.

    Returns True for a new publication and False for an idempotent replay of
    byte-identical content.  Different existing content is always a conflict.
    """

    path = Path(path)
    _ensure_directory(path.parent)
    payload = json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True).encode() + b"\n"
    temporary = _write_synced_temporary(path, payload)
    published = False
    try:
        try:
            os.link(temporary, path)
            published = True
            _fsync_directory(path.parent)
        except FileExistsError:
            if path.read_bytes() != payload:
                raise CommitConflict(f"Immutable file conflicts with existing content: {path}")
            # A prior caller may have linked the file and failed before its
            # directory fsync returned.  Make an idempotent retry durable.
            _fsync_directory(path.parent)
        return published
    finally:
        try:
            temporary.unlink()
            _fsync_directory(path.parent)
        except FileNotFoundError:
            pass


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RecoveryError(f"Unreadable JSON recovery state: {path}") from error


def _json_copy(value: Any) -> Any:
    try:
        return json.loads(canonical_json_bytes(value))
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise RecoveryError("Recovery state is not finite JSON data") from error


def normalize_vector_records(records: Iterable[Mapping[str, Any]], dimensions: int) -> list[dict[str, Any]]:
    """Validate and deterministically order raw VectorNode-shaped records."""

    if type(dimensions) is not int or dimensions <= 0:
        raise ValueError("dimensions must be a positive integer")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source in records:
        if not isinstance(source, Mapping):
            raise RecoveryError("Checkpoint vector record is not an object")
        record = _json_copy(dict(source))
        vector_id = record.get("vector_id")
        content = record.get("content")
        vector = record.get("vector")
        metadata = record.get("metadata")
        if not isinstance(vector_id, str) or not vector_id or vector_id in seen:
            raise RecoveryError("Checkpoint vector IDs must be nonempty and unique")
        if not isinstance(content, str) or not isinstance(metadata, dict):
            raise RecoveryError("Checkpoint vector content/metadata has an invalid type")
        if not isinstance(vector, list) or len(vector) != dimensions:
            raise RecoveryError("Checkpoint vector has an invalid dimension")
        if any(
            isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number)
            for number in vector
        ):
            raise RecoveryError("Checkpoint vector contains a non-finite or non-numeric value")
        seen.add(vector_id)
        normalized.append(record)
    return sorted(normalized, key=lambda row: row["vector_id"])


def vector_records_sha256(records: Iterable[Mapping[str, Any]], dimensions: int) -> str:
    return json_sha256(normalize_vector_records(records, dimensions))


@dataclass(frozen=True)
class Checkpoint:
    path: Path
    manifest: dict[str, Any]
    records: tuple[dict[str, Any], ...]
    manifest_sha256: str

    @property
    def records_sha256(self) -> str:
        return self.manifest["memory"]["records_sha256"]


def create_checkpoint(
    path: str | Path,
    *,
    sequence: int,
    records: Iterable[Mapping[str, Any]],
    dimensions: int,
    index_config: Mapping[str, Any],
    owner_token: str,
    owner_generation: int,
    task_id: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> Checkpoint:
    """Create one immutable vector-preserving checkpoint directory."""

    path = Path(path)
    if type(sequence) is not int or sequence < 0:
        raise ValueError("sequence must be a nonnegative integer")
    if sequence == 0 and task_id is not None:
        raise ValueError("checkpoint zero cannot name a task")
    if sequence > 0 and (not isinstance(task_id, str) or not task_id):
        raise ValueError("task checkpoints require a task_id")
    if not isinstance(owner_token, str) or not owner_token or type(owner_generation) is not int or owner_generation < 1:
        raise ValueError("checkpoint owner identity is invalid")
    rows = normalize_vector_records(records, dimensions)
    index = _json_copy(dict(index_config))
    extra = _json_copy(dict(metadata or {}))
    _ensure_directory(path.parent)
    if path.exists():
        raise FileExistsError(f"Checkpoint is immutable: {path}")
    temporary = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
    os.mkdir(temporary)
    _fsync_directory(path.parent)
    try:
        records_path = temporary / "vectors.jsonl"
        atomic_write_jsonl(records_path, rows)
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "kind": "initialization" if sequence == 0 else "task",
            "sequence": sequence,
            "task_id": task_id,
            "created_at": _now(),
            "owner": {"token": owner_token, "generation": owner_generation},
            "memory": {
                "count": len(rows),
                "dimensions": dimensions,
                "records_sha256": json_sha256(rows),
                "file": "vectors.jsonl",
                "file_sha256": file_sha256(records_path),
            },
            "index_config": index,
            "index_config_sha256": json_sha256(index),
            "metadata": extra,
        }
        atomic_write_json(temporary / "checkpoint.json", manifest)
        _fsync_directory(temporary)
        try:
            os.rename(temporary, path)
        except OSError as error:
            if error.errno in (errno.EEXIST, errno.ENOTEMPTY):
                raise FileExistsError(f"Checkpoint is immutable: {path}") from error
            raise
        _fsync_directory(path.parent)
        return load_checkpoint(path, expected_dimensions=dimensions)
    except BaseException:
        if temporary.exists():
            shutil.rmtree(temporary)
            _fsync_directory(path.parent)
        raise


def load_checkpoint(path: str | Path, expected_dimensions: int | None = None) -> Checkpoint:
    path = Path(path)
    manifest_path = path / "checkpoint.json"
    manifest = _load_json(manifest_path)
    if not isinstance(manifest, dict) or manifest.get("schema_version") != SCHEMA_VERSION:
        raise RecoveryError(f"Unsupported checkpoint manifest: {manifest_path}")
    sequence = manifest.get("sequence")
    task_id = manifest.get("task_id")
    if (
        type(sequence) is not int
        or sequence < 0
        or manifest.get("kind") != ("initialization" if sequence == 0 else "task")
        or (sequence == 0 and task_id is not None)
        or (sequence > 0 and (not isinstance(task_id, str) or not task_id))
        or not isinstance(manifest.get("metadata"), dict)
    ):
        raise RecoveryError("Checkpoint identity is invalid")
    memory = manifest.get("memory")
    if not isinstance(memory, dict) or memory.get("file") != "vectors.jsonl":
        raise RecoveryError("Checkpoint memory manifest is invalid")
    dimensions = memory.get("dimensions")
    if type(dimensions) is not int or dimensions <= 0:
        raise RecoveryError("Checkpoint dimensions are invalid")
    if expected_dimensions is not None and dimensions != expected_dimensions:
        raise RecoveryError("Checkpoint dimensions differ from the expected service dimensions")
    records_path = path / "vectors.jsonl"
    try:
        observed_file_hash = file_sha256(records_path)
        records = [json.loads(line) for line in records_path.read_text(encoding="utf-8").splitlines() if line]
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RecoveryError("Checkpoint vector file is unreadable") from error
    if observed_file_hash != memory.get("file_sha256"):
        raise RecoveryError("Checkpoint vector file hash mismatch")
    rows = normalize_vector_records(records, dimensions)
    if len(rows) != memory.get("count") or json_sha256(rows) != memory.get("records_sha256"):
        raise RecoveryError("Checkpoint vector records differ from the manifest")
    index = manifest.get("index_config")
    if not isinstance(index, dict) or json_sha256(index) != manifest.get("index_config_sha256"):
        raise RecoveryError("Checkpoint index configuration hash mismatch")
    owner = manifest.get("owner")
    if (
        not isinstance(owner, dict)
        or not isinstance(owner.get("token"), str)
        or not owner["token"]
        or type(owner.get("generation")) is not int
        or owner["generation"] < 1
    ):
        raise RecoveryError("Checkpoint owner identity is invalid")
    return Checkpoint(path.resolve(), manifest, tuple(rows), file_sha256(manifest_path))


class RunClaim:
    """A process-held flock plus a persistent, monotonically fenced identity."""

    def __init__(self, run_root: Path, run_id: str, token: str, generation: int, descriptor: int):
        self.run_root = run_root
        self.run_id = run_id
        self.token = token
        self.generation = generation
        self._descriptor = descriptor
        self._held = True

    @classmethod
    def acquire(
        cls,
        run_root: str | Path,
        run_id: str,
        *,
        owner_token: str | None = None,
        blocking: bool = False,
    ) -> "RunClaim":
        run_root = Path(run_root).resolve()
        if not isinstance(run_id, str) or not run_id:
            raise ValueError("run_id must be nonempty")
        token = owner_token or uuid.uuid4().hex
        if not isinstance(token, str) or not token:
            raise ValueError("owner_token must be nonempty")
        recovery = run_root / RECOVERY_DIRECTORY
        _ensure_directory(recovery)
        descriptor = os.open(recovery / "claim.lock", os.O_RDWR | os.O_CREAT, 0o600)
        operation = fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB)
        try:
            fcntl.flock(descriptor, operation)
        except BlockingIOError as error:
            os.close(descriptor)
            raise ClaimBusy(f"Run is already claimed: {run_root}") from error
        claim_path = run_root / CLAIM_FILE
        try:
            prior = _load_json(claim_path) if claim_path.exists() else None
            if prior is not None:
                if not isinstance(prior, dict) or prior.get("schema_version") != SCHEMA_VERSION:
                    raise RecoveryError("Persistent claim state is invalid")
                if prior.get("run_id") != run_id:
                    raise RecoveryError("Persistent claim belongs to a different run")
                prior_generation = prior.get("generation")
                if type(prior_generation) is not int or prior_generation < 1:
                    raise RecoveryError("Persistent claim generation is invalid")
            else:
                prior_generation = 0
            generation = prior_generation + 1
            state = {
                "schema_version": SCHEMA_VERSION,
                "run_id": run_id,
                "owner_token": token,
                "generation": generation,
                "status": "active",
                "pid": os.getpid(),
                "hostname": socket.gethostname(),
                "acquired_at": _now(),
            }
            atomic_write_json(claim_path, state)
            return cls(run_root, run_id, token, generation, descriptor)
        except BaseException:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)
            raise

    @property
    def identity(self) -> dict[str, Any]:
        return {"token": self.token, "generation": self.generation}

    def assert_current(self) -> dict[str, Any]:
        if not self._held:
            raise StaleOwner("Run claim is no longer held")
        try:
            fcntl.flock(self._descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (BlockingIOError, OSError) as error:
            raise StaleOwner("Run claim lock is no longer owned") from error
        state = _load_json(self.run_root / CLAIM_FILE)
        expected = (self.run_id, self.token, self.generation, "active")
        actual = (
            state.get("run_id"),
            state.get("owner_token"),
            state.get("generation"),
            state.get("status"),
        )
        if actual != expected:
            raise StaleOwner("Run ownership generation/token has been superseded")
        return state

    def release(self) -> None:
        if not self._held:
            return
        try:
            state = self.assert_current()
            atomic_write_json(
                self.run_root / CLAIM_FILE,
                {**state, "status": "released", "released_at": _now()},
            )
        finally:
            fcntl.flock(self._descriptor, fcntl.LOCK_UN)
            os.close(self._descriptor)
            self._held = False

    def abandon(self) -> None:
        """Model process death: release the OS lock but leave active state."""

        if self._held:
            fcntl.flock(self._descriptor, fcntl.LOCK_UN)
            os.close(self._descriptor)
            self._held = False

    def __enter__(self) -> "RunClaim":
        self.assert_current()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.release()


def make_commit_record(
    *,
    run_root: str | Path,
    checkpoint: Checkpoint,
    frozen_manifest_sha256: str,
    previous_commit_sha256: str | None,
    committed_task_ids: Sequence[str],
) -> dict[str, Any]:
    """Build a commit record bound to one validated checkpoint."""

    run_root = Path(run_root).resolve()
    try:
        relative_checkpoint = checkpoint.path.relative_to(run_root)
    except ValueError as error:
        raise ValueError("Checkpoint must be inside the run root") from error
    manifest = checkpoint.manifest
    sequence = manifest["sequence"]
    task_id = manifest["task_id"]
    expected_count = sequence
    if len(committed_task_ids) != expected_count:
        raise ValueError("Committed task prefix length must equal checkpoint sequence")
    if sequence and committed_task_ids[-1] != task_id:
        raise ValueError("Task checkpoint does not end with its committed task")
    if sequence == 0 and previous_commit_sha256 is not None:
        raise ValueError("Initialization commit cannot have a predecessor")
    if sequence > 0 and not previous_commit_sha256:
        raise ValueError("Task commit requires a predecessor hash")
    if not _is_sha256(frozen_manifest_sha256):
        raise ValueError("Frozen manifest hash must be a SHA-256 hex digest")
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": manifest["kind"],
        "sequence": sequence,
        "task_id": task_id,
        "committed_task_ids": list(committed_task_ids),
        "published_at": _now(),
        "owner": dict(manifest["owner"]),
        "frozen_manifest_sha256": frozen_manifest_sha256,
        "previous_commit_sha256": previous_commit_sha256,
        "checkpoint": {
            "path": relative_checkpoint.as_posix(),
            "manifest_sha256": checkpoint.manifest_sha256,
            "records_sha256": checkpoint.records_sha256,
        },
    }


def _validate_commit_record(run_root: Path, record: Mapping[str, Any]) -> Checkpoint:
    sequence = record.get("sequence")
    task_id = record.get("task_id")
    prefix = record.get("committed_task_ids")
    predecessor = record.get("previous_commit_sha256")
    if (
        record.get("schema_version") != SCHEMA_VERSION
        or type(sequence) is not int
        or sequence < 0
        or record.get("kind") != ("initialization" if sequence == 0 else "task")
        or not isinstance(prefix, list)
        or len(prefix) != sequence
        or len(prefix) != len(set(prefix))
        or any(not isinstance(item, str) or not item for item in prefix)
        or (sequence == 0 and (task_id is not None or predecessor is not None))
        or (sequence > 0 and (not isinstance(task_id, str) or not task_id or prefix[-1] != task_id))
        or (sequence > 0 and not _is_sha256(predecessor))
        or not _is_sha256(record.get("frozen_manifest_sha256"))
    ):
        raise RecoveryError("Commit record identity is invalid")
    owner = record.get("owner")
    if (
        not isinstance(owner, dict)
        or not isinstance(owner.get("token"), str)
        or not owner["token"]
        or type(owner.get("generation")) is not int
        or owner["generation"] < 1
    ):
        raise RecoveryError("Commit owner identity is invalid")
    reference = record.get("checkpoint")
    if (
        not isinstance(reference, dict)
        or not isinstance(reference.get("path"), str)
        or not _is_sha256(reference.get("manifest_sha256"))
        or not _is_sha256(reference.get("records_sha256"))
    ):
        raise RecoveryError("Commit checkpoint reference is invalid")
    checkpoint = load_checkpoint(_inside(run_root, reference["path"]))
    if (
        checkpoint.manifest_sha256 != reference["manifest_sha256"]
        or checkpoint.records_sha256 != reference["records_sha256"]
        or checkpoint.manifest.get("sequence") != sequence
        or checkpoint.manifest.get("task_id") != task_id
        or checkpoint.manifest.get("owner") != owner
    ):
        raise RecoveryError("Commit record does not match its checkpoint")
    return checkpoint


def publish_commit(run_root: str | Path, record: Mapping[str, Any], claim: RunClaim) -> tuple[Path, bool]:
    """Fence and atomically publish one immutable authoritative marker."""

    run_root = Path(run_root).resolve()
    claim.assert_current()
    if claim.run_root != run_root:
        raise StaleOwner("Claim belongs to a different run root")
    data = _json_copy(dict(record))
    if data.get("owner") != claim.identity:
        raise StaleOwner("Commit owner does not match the current claim")
    _validate_commit_record(run_root, data)
    sequence = data["sequence"]
    marker = run_root / COMMIT_DIRECTORY / f"{sequence:06d}.json"
    return marker, publish_immutable_json(marker, data)


@dataclass(frozen=True)
class CommittedPrefix:
    initialized: bool
    task_ids: tuple[str, ...]
    next_task_id: str | None
    last_commit_sha256: str | None
    last_checkpoint: Checkpoint | None
    owner_generation: int | None


def _inside(root: Path, relative: str) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute():
        raise RecoveryError("Recovery state contains an absolute path")
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise RecoveryError("Recovery state escapes the run root") from error
    return resolved


def discover_committed_prefix(
    run_root: str | Path,
    ordered_task_ids: Sequence[str],
    frozen_manifest_sha256: str,
    *,
    expected_dimensions: int | None = None,
) -> CommittedPrefix:
    """Validate the immutable marker chain and return its task prefix."""

    run_root = Path(run_root).resolve()
    tasks = tuple(ordered_task_ids)
    if len(tasks) != len(set(tasks)) or any(not isinstance(task, str) or not task for task in tasks):
        raise ValueError("Ordered task IDs must be nonempty and unique")
    directory = run_root / COMMIT_DIRECTORY
    if not directory.exists():
        return CommittedPrefix(False, (), tasks[0] if tasks else None, None, None, None)
    markers: dict[int, Path] = {}
    for path in directory.iterdir():
        if path.name.startswith(".") and path.name.endswith(".tmp"):
            continue
        if not path.is_file() or len(path.stem) != 6 or not path.stem.isdigit() or path.suffix != ".json":
            raise RecoveryError(f"Unexpected entry in commit directory: {path.name}")
        markers[int(path.stem)] = path
    if not markers:
        return CommittedPrefix(False, (), tasks[0] if tasks else None, None, None, None)
    if sorted(markers) != list(range(max(markers) + 1)):
        raise RecoveryError("Commit marker sequence has a gap")
    if max(markers) > len(tasks):
        raise RecoveryError("Commit prefix is longer than the frozen task order")
    previous_hash = None
    previous_generation = None
    previous_owner_token = None
    checkpoint = None
    for sequence in range(max(markers) + 1):
        marker_path = markers[sequence]
        record = _load_json(marker_path)
        expected_kind = "initialization" if sequence == 0 else "task"
        expected_task = None if sequence == 0 else tasks[sequence - 1]
        expected_prefix = list(tasks[:sequence])
        if (
            not isinstance(record, dict)
            or record.get("schema_version") != SCHEMA_VERSION
            or record.get("sequence") != sequence
            or record.get("kind") != expected_kind
            or record.get("task_id") != expected_task
            or record.get("committed_task_ids") != expected_prefix
            or record.get("frozen_manifest_sha256") != frozen_manifest_sha256
            or record.get("previous_commit_sha256") != previous_hash
        ):
            raise RecoveryError(f"Commit marker {sequence} conflicts with the frozen run")
        owner = record.get("owner")
        generation = owner.get("generation") if isinstance(owner, dict) else None
        if (
            not isinstance(owner, dict)
            or not isinstance(owner.get("token"), str)
            or not owner["token"]
            or type(generation) is not int
            or generation < 1
            or (previous_generation is not None and generation < previous_generation)
            or (
                previous_generation is not None
                and generation == previous_generation
                and owner["token"] != previous_owner_token
            )
        ):
            raise RecoveryError("Commit owner generations are invalid or regress")
        checkpoint_ref = record.get("checkpoint")
        if not isinstance(checkpoint_ref, dict):
            raise RecoveryError("Commit checkpoint reference is invalid")
        checkpoint = load_checkpoint(
            _inside(run_root, checkpoint_ref.get("path", "")),
            expected_dimensions=expected_dimensions,
        )
        if (
            checkpoint.manifest_sha256 != checkpoint_ref.get("manifest_sha256")
            or checkpoint.records_sha256 != checkpoint_ref.get("records_sha256")
            or checkpoint.manifest.get("sequence") != sequence
            or checkpoint.manifest.get("task_id") != expected_task
            or checkpoint.manifest.get("owner") != owner
        ):
            raise RecoveryError("Commit marker does not match its checkpoint")
        previous_hash = file_sha256(marker_path)
        previous_generation = generation
        previous_owner_token = owner["token"]
    committed = tasks[: max(markers)]
    next_task = tasks[len(committed)] if len(committed) < len(tasks) else None
    return CommittedPrefix(True, committed, next_task, previous_hash, checkpoint, previous_generation)


def _retry_state(path: Path, max_restarts: int) -> dict[str, Any]:
    if type(max_restarts) is not int or not 0 <= max_restarts <= DEFAULT_MAX_RESTARTS:
        raise ValueError(f"max_restarts must be between zero and {DEFAULT_MAX_RESTARTS}")
    if not path.exists():
        return {
            "schema_version": SCHEMA_VERSION,
            "max_restarts": max_restarts,
            "counters": [],
        }
    state = _load_json(path)
    if (
        not isinstance(state, dict)
        or state.get("schema_version") != SCHEMA_VERSION
        or state.get("max_restarts") != max_restarts
        or not isinstance(state.get("counters"), list)
    ):
        raise RecoveryError("Persistent retry state is invalid")
    seen = set()
    for row in state["counters"]:
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("stage"), str)
            or not row["stage"]
            or (row.get("task_id") is not None and (not isinstance(row["task_id"], str) or not row["task_id"]))
            or (row["stage"], row.get("task_id")) in seen
        ):
            raise RecoveryError("Persistent retry counter scope is invalid or duplicated")
        seen.add((row["stage"], row.get("task_id")))
    return state


def retry_count(
    run_root: str | Path,
    stage: str,
    task_id: str | None = None,
    *,
    max_restarts: int = DEFAULT_MAX_RESTARTS,
) -> int:
    state = _retry_state(Path(run_root).resolve() / RETRY_FILE, max_restarts)
    matches = [row for row in state["counters"] if row.get("stage") == stage and row.get("task_id") == task_id]
    if len(matches) > 1:
        raise RecoveryError("Persistent retry state contains duplicate scopes")
    if not matches:
        return 0
    value = matches[0].get("restarts")
    if type(value) is not int or not 0 <= value <= max_restarts:
        raise RecoveryError("Persistent retry count is invalid")
    return value


def record_infrastructure_restart(
    run_root: str | Path,
    claim: RunClaim,
    stage: str,
    task_id: str | None = None,
    *,
    max_restarts: int = DEFAULT_MAX_RESTARTS,
) -> int:
    """Persist a restart reservation before launching the replacement attempt."""

    run_root = Path(run_root).resolve()
    claim.assert_current()
    if claim.run_root != run_root:
        raise StaleOwner("Claim belongs to a different run root")
    if not isinstance(stage, str) or not stage:
        raise ValueError("Retry stage/max_restarts is invalid")
    if task_id is not None and (not isinstance(task_id, str) or not task_id):
        raise ValueError("task_id must be nonempty when supplied")
    path = run_root / RETRY_FILE
    state = _retry_state(path, max_restarts)
    matches = [row for row in state["counters"] if row.get("stage") == stage and row.get("task_id") == task_id]
    if len(matches) > 1:
        raise RecoveryError("Persistent retry state contains duplicate scopes")
    current = retry_count(run_root, stage, task_id, max_restarts=max_restarts)
    if current >= max_restarts:
        raise RetryLimitExceeded(f"Infrastructure restart limit reached for {stage}:{task_id or '-'}")
    row = matches[0] if matches else None
    if row is None:
        row = {"stage": stage, "task_id": task_id, "restarts": 0, "events": []}
        state["counters"].append(row)
    if not isinstance(row.get("events"), list) or len(row["events"]) != current:
        raise RecoveryError("Persistent retry event history is invalid")
    row["restarts"] = current + 1
    row["events"].append({"restart": current + 1, "recorded_at": _now(), "owner": claim.identity})
    state["counters"].sort(key=lambda item: (item["stage"], item["task_id"] or ""))
    atomic_write_json(path, state)
    return current + 1
