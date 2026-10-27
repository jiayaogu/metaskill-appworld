"""Mandatory, uncapped accounting for formal AppWorld execution.

This module is intentionally separate from :mod:`execution_budget`, which is
the immutable spending guard for the historical smoke campaign.  Formal
accounting never rejects a request because of cumulative spend, but it does
fail closed on policy, model, endpoint, identity, or ledger inconsistencies.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import uuid
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path


ENVIRONMENT_KEY = "REME_FORMAL_ACCOUNTING_FILE"
SMOKE_ENVIRONMENT_KEY = "REME_SMOKE_BUDGET_FILE"
POLICY_SCHEMA_VERSION = 1
LEDGER_SCHEMA_VERSION = 1
IDENTITY_FIELDS = (
    "campaign",
    "run",
    "stage",
    "task",
    "task_attempt_id",
    "attempt_kind",
    "ownership_generation",
)


class AccountingError(RuntimeError):
    """Formal accounting policy or evidence is invalid."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def decimal(value) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise AccountingError("Accounting values must be finite and nonnegative") from error
    if not result.is_finite() or result < 0:
        raise AccountingError("Accounting values must be finite and nonnegative")
    return result


def _validate_mode() -> None:
    if os.environ.get(ENVIRONMENT_KEY) and os.environ.get(SMOKE_ENVIRONMENT_KEY):
        raise AccountingError("Smoke budget and formal accounting cannot both be active")


def _validate_policy(data) -> None:
    if not isinstance(data, dict):
        raise AccountingError("Formal accounting policy must be a JSON object")
    if data.get("schema_version") != POLICY_SCHEMA_VERSION:
        raise AccountingError(f"Formal accounting policy schema_version must be {POLICY_SCHEMA_VERSION}")
    if data.get("mode") != "formal_accounting":
        raise AccountingError("Formal accounting policy mode must be formal_accounting")
    if "limit_usd" not in data or data["limit_usd"] is not None:
        raise AccountingError("Formal accounting policy limit_usd must be null")
    models = data.get("models")
    if not isinstance(models, dict) or not models:
        raise AccountingError("Formal accounting policy requires a nonempty model allowlist")
    for model, spec in models.items():
        if not isinstance(model, str) or not model or not isinstance(spec, dict):
            raise AccountingError("Invalid model accounting specification")
        for key in ("input", "output", "cached"):
            if key not in spec:
                raise AccountingError(f"Model {model} is missing the {key} rate")
            decimal(spec[key])
        urls = spec.get("urls")
        if (
            not isinstance(urls, list)
            or not urls
            or any(not isinstance(url, str) or not url for url in urls)
            or len(urls) != len(set(urls))
        ):
            raise AccountingError(f"Model {model} requires unique nonempty endpoint URLs")


def policy():
    """Return the immutable formal policy path, parsed data, and byte hash."""
    _validate_mode()
    configured = os.environ.get(ENVIRONMENT_KEY)
    if not configured:
        raise AccountingError(f"Set {ENVIRONMENT_KEY} for formal execution")
    path = Path(configured).resolve(strict=True)
    raw = path.read_bytes()
    try:
        data = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AccountingError("Formal accounting policy is not valid JSON") from error
    _validate_policy(data)
    return path, data, hashlib.sha256(raw).hexdigest()


def ledger_path() -> Path:
    path, _, _ = policy()
    return path.with_suffix(".ledger.jsonl")


@contextmanager
def ledger():
    """Lock the append-only ledger and expose its validated rows and appender."""
    path, data, digest = policy()
    target = path.with_suffix(".ledger.jsonl")
    with target.open("a+", encoding="utf-8") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            stream.seek(0)
            try:
                rows = [json.loads(line) for line in stream if line.strip()]
            except json.JSONDecodeError as error:
                raise AccountingError("Formal accounting ledger contains invalid JSON") from error
            for row in rows:
                if row.get("schema_version") != LEDGER_SCHEMA_VERSION:
                    raise AccountingError("Formal accounting ledger schema changed")
                if row.get("policy_sha256") != digest:
                    raise AccountingError("Formal accounting policy changed after the ledger was created")

            def append(row):
                event = {
                    "schema_version": LEDGER_SCHEMA_VERSION,
                    "policy_sha256": digest,
                    **row,
                }
                stream.seek(0, os.SEEK_END)
                stream.write(json.dumps(event, sort_keys=True, allow_nan=False) + "\n")
                stream.flush()
                os.fsync(stream.fileno())

            yield data, rows, append
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def states(rows):
    """Fold start/settle events into one state per physical request."""
    result = {}
    for row in rows:
        event = row.get("event")
        physical_id = row.get("id")
        if event == "start":
            if physical_id in result:
                raise AccountingError("Duplicate formal accounting physical ID")
            result[physical_id] = row
        elif event == "settle":
            prior = result.get(physical_id)
            if prior is None:
                raise AccountingError("Formal accounting settlement has no start event")
            if prior.get("event") != "start":
                raise AccountingError("Duplicate formal accounting settlement")
            result[physical_id] = {**prior, **row}
        else:
            raise AccountingError("Unknown formal accounting ledger event")
    return result


def new_physical_id() -> str:
    """Create the globally unique ID shared by the ledger and canonical log."""
    return uuid.uuid4().hex


def _validate_physical_id(physical_id) -> str:
    if not isinstance(physical_id, str):
        raise AccountingError("Physical ID must be a UUID4 string")
    try:
        parsed = uuid.UUID(physical_id)
    except (ValueError, AttributeError) as error:
        raise AccountingError("Physical ID must be a UUID4 string") from error
    if parsed.version != 4:
        raise AccountingError("Physical ID must be a UUID4 string")
    return parsed.hex


def _validate_identity(identity):
    if not isinstance(identity, dict) or any(field not in identity for field in IDENTITY_FIELDS):
        raise AccountingError("Formal call lacks complete execution identity")
    for field in ("campaign", "run", "stage", "task_attempt_id"):
        if not isinstance(identity[field], str) or not identity[field]:
            raise AccountingError(f"Formal identity {field} must be a nonempty string")
    if identity["task"] is not None and (not isinstance(identity["task"], str) or not identity["task"]):
        raise AccountingError("Formal identity task must be null or a nonempty string")
    if identity["attempt_kind"] not in ("primary", "recovery"):
        raise AccountingError("Formal identity attempt_kind must be primary or recovery")
    if type(identity["ownership_generation"]) is not int or identity["ownership_generation"] < 1:
        raise AccountingError("Formal identity ownership_generation must be a positive integer")
    return {field: identity[field] for field in IDENTITY_FIELDS}


def start(physical_id, url, request, identity, *, started_at=None):
    """Durably record a physical request before transport, without a spend gate."""
    physical_id = _validate_physical_id(physical_id)
    identity = _validate_identity(identity)
    if not isinstance(request, dict):
        raise AccountingError("Provider request must be a dictionary")
    with ledger() as (data, rows, append):
        model = request.get("model")
        spec = data["models"].get(model)
        if spec is None or url not in spec["urls"]:
            raise AccountingError("Unapproved formal model or endpoint")
        if request.get("n", 1) != 1:
            raise AccountingError("Formal accounting requires one completion per request")
        if physical_id in states(rows):
            raise AccountingError("Duplicate formal accounting physical ID")
        request_bytes = json.dumps(request, sort_keys=True, separators=(",", ":"), default=repr).encode()
        append(
            {
                "event": "start",
                "id": physical_id,
                "model": model,
                "url": url,
                "request_kind": "embedding" if "input" in request else "chat",
                "request_sha256": hashlib.sha256(request_bytes).hexdigest(),
                "started_at": started_at or _now(),
                **identity,
            }
        )
    return True


def usage_cost(model, usage, data, *, request_kind="chat"):
    """Return a published-rate estimate, or ``None`` for unusable usage."""
    if not isinstance(usage, dict):
        return None
    prompt = usage.get("prompt_tokens", usage.get("input_tokens"))
    completion = usage.get("completion_tokens", usage.get("output_tokens"))
    if request_kind == "embedding" and completion is None:
        completion = 0
    prompt_details = usage.get("prompt_tokens_details") or usage.get("input_tokens_details") or {}
    cached = prompt_details.get("cached_tokens", 0) if isinstance(prompt_details, dict) else None
    if any(type(value) is not int or value < 0 for value in (prompt, completion, cached)) or cached > prompt:
        return None
    spec = data["models"][model]
    return (
        (prompt - cached) * decimal(spec["input"])
        + cached * decimal(spec["cached"])
        + completion * decimal(spec["output"])
    ) / Decimal(1_000_000)


def settle(physical_id, output, failed, *, finished_at=None):
    """Settle one started request; failures and missing usage remain visible."""
    physical_id = _validate_physical_id(physical_id)
    if not isinstance(output, dict) or type(failed) is not bool:
        raise AccountingError("Settlement requires a dictionary output and boolean failed flag")
    with ledger() as (data, rows, append):
        row = states(rows).get(physical_id)
        if row is None:
            raise AccountingError("Formal accounting settlement has no start event")
        if row.get("event") != "start":
            raise AccountingError("Duplicate formal accounting settlement")
        usage = output.get("usage")
        cost = usage_cost(row["model"], usage, data, request_kind=row["request_kind"])
        append(
            {
                "event": "settle",
                "id": physical_id,
                "status": "failed" if failed else ("priced" if cost is not None else "unknown"),
                "estimated_usd": None if cost is None else str(cost),
                "usage": usage,
                "finished_at": finished_at or _now(),
            }
        )


def _selected_states(rows, filters):
    selected = states(rows)
    for field, expected in filters.items():
        if field not in IDENTITY_FIELDS:
            raise AccountingError(f"Unknown accounting identity filter: {field}")
        selected = {key: row for key, row in selected.items() if row.get(field) == expected}
    return selected


def _summarize(current):
    values = list(current.values())
    priced = [row for row in values if row.get("status") == "priced"]
    unknown = [row for row in values if row.get("status") == "unknown"]
    failed = [row for row in values if row.get("status") == "failed"]
    unsettled = [row for row in values if row.get("event") == "start"]
    known_costs = [decimal(row["estimated_usd"]) for row in values if row.get("estimated_usd") is not None]
    by_attempt_kind = {}
    for kind in ("primary", "recovery"):
        subset = {key: row for key, row in current.items() if row["attempt_kind"] == kind}
        by_attempt_kind[kind] = {
            "physical_requests": len(subset),
            "estimated_usd": float(
                sum(
                    (decimal(row["estimated_usd"]) for row in subset.values() if row.get("estimated_usd") is not None),
                    Decimal(0),
                )
            ),
        }
    return {
        "mode": "formal_accounting",
        "limit_usd": None,
        "physical_requests": len(values),
        "priced_requests": len(priced),
        "unknown_requests": len(unknown),
        "failed_requests": len(failed),
        "failed_priced_requests": sum(row.get("estimated_usd") is not None for row in failed),
        "failed_unknown_requests": sum(row.get("estimated_usd") is None for row in failed),
        "unsettled_requests": len(unsettled),
        "estimated_usd": float(sum(known_costs, Decimal(0))),
        "by_attempt_kind": by_attempt_kind,
        "billed_dollars": None,
    }


def summary(**identity_filters):
    """Summarize all or an identity-filtered subset of the formal ledger."""
    path, _, digest = policy()
    with ledger() as (_, rows, __):
        current = _selected_states(rows, identity_filters)
    result = _summarize(current)
    result["accounting_policy"] = str(path)
    result["accounting_policy_sha256"] = digest
    return result


def reconcile(calls, **identity_filters):
    """Compare canonical physical-call IDs with matching formal ledger IDs."""
    if not isinstance(calls, list) or any(not isinstance(call, dict) for call in calls):
        raise AccountingError("Canonical calls must be a list of dictionaries")
    log_ids = [call.get("id") for call in calls]
    invalid_log_ids = sorted(str(value) for value in log_ids if not isinstance(value, str))
    valid_log_ids = [value for value in log_ids if isinstance(value, str)]
    duplicate_log_ids = sorted(value for value, count in Counter(valid_log_ids).items() if count > 1)
    with ledger() as (_, rows, __):
        current = _selected_states(rows, identity_filters)
    ledger_ids, canonical_ids = set(current), set(valid_log_ids)
    result = {
        "status": "matched",
        "joined_ids": sorted(ledger_ids & canonical_ids),
        "ledger_only_ids": sorted(ledger_ids - canonical_ids),
        "log_only_ids": sorted(canonical_ids - ledger_ids),
        "duplicate_log_ids": duplicate_log_ids,
        "invalid_log_ids": invalid_log_ids,
        "summary": _summarize(current),
    }
    if any(result[key] for key in ("ledger_only_ids", "log_only_ids", "duplicate_log_ids", "invalid_log_ids")):
        result["status"] = "mismatch"
    return result
