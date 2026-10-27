"""Opt-in, cross-process USD reservation guard for the authorized smoke only.

The append-only ledger is not a second canonical LLM log. It contains budget
reservations keyed by the physical IDs used by the shared LLM logger. Unfinished,
failed, or usage-less requests retain their full reservation. Published-rate
estimates are not provider invoices. Model request parameters remain unchanged.
"""

import fcntl
import hashlib
import json
import os
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path

ENVIRONMENT_KEY = "REME_SMOKE_BUDGET_FILE"


class BudgetStopped(BaseException):
    """Cancellation, deliberately not a retryable provider Exception."""


def decimal(value):
    result = Decimal(str(value))
    if not result.is_finite() or result < 0:
        raise ValueError("Budget values must be finite and nonnegative")
    return result


def policy():
    path = Path(os.environ[ENVIRONMENT_KEY]).resolve(strict=True)
    raw = path.read_bytes()
    data = json.loads(raw)
    if not Decimal(0) < decimal(data["limit_usd"]) < Decimal(100):
        raise ValueError("Smoke budget must be positive and below USD 100")
    if decimal(data["prior_allowance_usd"]) >= decimal(data["limit_usd"]):
        raise ValueError("Prior allowance exhausts smoke budget")
    for spec in data["models"].values():
        for key in ("input", "output", "cached", "reserve_usd"):
            decimal(spec[key])
    return path, data, hashlib.sha256(raw).hexdigest()


@contextmanager
def ledger():
    path, data, digest = policy()
    # Lock the append-only file itself: no replacement or truncated rewrite.
    with path.with_suffix(".ledger.jsonl").open("a+", encoding="utf-8") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        try:
            stream.seek(0)
            rows = [json.loads(line) for line in stream if line.strip()]
            if any(row["policy_sha256"] != digest for row in rows):
                raise BudgetStopped("Budget policy changed after its first reservation")

            def append(row):
                stream.seek(0, os.SEEK_END)
                stream.write(json.dumps({**row, "policy_sha256": digest}, sort_keys=True) + "\n")
                stream.flush()
                os.fsync(stream.fileno())

            yield data, rows, append
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def states(rows):
    result = {}
    for row in rows:
        if row["event"] == "reserve":
            if row["id"] in result:
                raise BudgetStopped("Duplicate budget reservation")
            result[row["id"]] = row
        elif row["event"] == "settle":
            prior = result[row["id"]]
            if prior["event"] != "reserve":
                raise BudgetStopped("Duplicate budget settlement")
            result[row["id"]] = {**prior, **row}
    return result


def reserve(physical_id, url, request, identity):
    if not os.environ.get(ENVIRONMENT_KEY):
        return False
    if not identity:
        raise BudgetStopped("Budgeted provider call lacks audit identity")
    with ledger() as (data, rows, append):
        spec = data["models"].get(request.get("model"))
        if not spec or url not in spec["urls"] or request.get("n", 1) != 1:
            raise BudgetStopped("Unapproved model, endpoint, or multiple completions")
        if "input" in request:
            inputs = request["input"]
            if (
                not isinstance(inputs, list)
                or not 1 <= len(inputs) <= 10
                or not all(isinstance(x, str) for x in inputs)
            ):
                raise BudgetStopped("Embedding reservation requires 1–10 text inputs")
        current = states(rows)
        charged = decimal(data["prior_allowance_usd"]) + sum(decimal(r["held_usd"]) for r in current.values())
        amount = decimal(spec["reserve_usd"])
        if physical_id in current or charged + amount >= decimal(data["limit_usd"]):
            raise BudgetStopped("Cumulative smoke budget cannot reserve another request")
        append(
            {
                "event": "reserve",
                "id": physical_id,
                "model": request["model"],
                "run_directory": identity["run_directory"],
                "task_id": identity.get("task_id"),
                "held_usd": str(amount),
            }
        )
    return True


def usage_cost(model, usage, data):
    if not isinstance(usage, dict):
        return None
    prompt = usage.get("prompt_tokens", usage.get("input_tokens"))
    completion = 0 if model == "text-embedding-v4" else usage.get("completion_tokens", usage.get("output_tokens"))
    cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0)
    if any(type(n) is not int or n < 0 for n in (prompt, completion, cached)) or cached > prompt:
        return None
    spec = data["models"][model]
    return (
        (prompt - cached) * decimal(spec["input"])
        + cached * decimal(spec["cached"])
        + completion * decimal(spec["output"])
    ) / Decimal(1_000_000)


def settle(physical_id, output, failed):
    with ledger() as (data, rows, append):
        row = states(rows)[physical_id]
        if row["event"] != "reserve":
            raise BudgetStopped("Reservation already settled")
        cost = None if failed else usage_cost(row["model"], output.get("usage"), data)
        if cost is not None and cost > decimal(row["held_usd"]):
            raise BudgetStopped("Observed cost exceeds conservative reservation; stop campaign")
        append(
            {
                "event": "settle",
                "id": physical_id,
                "status": "retained" if cost is None else "priced",
                "held_usd": row["held_usd"] if cost is None else str(cost),
                "estimated_usd": None if cost is None else str(cost),
                "usage": output.get("usage"),
            }
        )


def cost_evidence(calls):
    with ledger() as (_, rows, __):
        current = states(rows)
    if len({call["id"] for call in calls}) != len(calls):
        raise RuntimeError("Duplicate canonical physical call ID")
    entries = [current.get(call["id"]) for call in calls]
    if any(not row or row.get("status") != "priced" for row in entries):
        raise RuntimeError("Provider cost evidence is missing or unresolved")
    return {
        "status": "published_rate_estimate",
        "physical_calls": len(calls),
        "dollars": float(sum(decimal(row["estimated_usd"]) for row in entries)),
        "missing_usage_calls": 0,
        "usage": [call["output"].get("usage") for call in calls],
        "budget_policy": os.environ[ENVIRONMENT_KEY],
        "billed_dollars": None,
    }


def summary():
    with ledger() as (data, rows, _):
        current = states(rows)
    known = sum(decimal(r["estimated_usd"]) for r in current.values() if r.get("status") == "priced")
    return {
        "limit_usd": data["limit_usd"],
        "prior_allowance_usd": data["prior_allowance_usd"],
        "physical_requests": len(current),
        "estimated_usd": float(known),
        "held_with_prior_usd": float(
            decimal(data["prior_allowance_usd"]) + sum(decimal(r["held_usd"]) for r in current.values())
        ),
        "unresolved_requests": sum(r.get("status") != "priced" for r in current.values()),
        "billed_dollars": None,
    }
