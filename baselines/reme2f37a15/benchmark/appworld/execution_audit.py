"""Request-scoped audit helpers for the pinned actor and isolated reme2 service."""

import contextvars
import copy
import hashlib
import importlib.util
import json
import os
import sys
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from functools import wraps

try:
    from . import execution_accounting, execution_budget, execution_recovery
except ImportError:
    import execution_accounting
    import execution_budget
    import execution_recovery

AUDIT = contextvars.ContextVar("reme_execution_audit", default=None)
_LOGGER_MODULE = None


def now():
    # AppWorld freezes datetime/time.time to a simulated task date. Audit UTC
    # must instead measure the OS wall clock, unaffected by that simulation.
    return datetime.fromtimestamp(time.clock_gettime(time.CLOCK_REALTIME), timezone.utc).isoformat()


def shared_logger():
    global _LOGGER_MODULE
    if _LOGGER_MODULE is None:
        path = Path(os.environ["APPWORLD_LM_LOGGER_MODULE_PATH"]).resolve(strict=True)
        spec = importlib.util.spec_from_file_location("reme_pinned_shared_lm_logger", path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        module._utc_now = now
        _LOGGER_MODULE = module
    return _LOGGER_MODULE


@contextmanager
def audit_scope(identity):
    token = AUDIT.set(identity)
    try:
        yield
    finally:
        AUDIT.reset(token)


@contextmanager
def operation_scope(name):
    identity = AUDIT.get()
    if identity is None:
        yield
    else:
        with audit_scope({**identity, "operation": name}):
            yield


def logger_for(identity):
    module = shared_logger()
    root, task = Path(identity["run_directory"]), identity.get("task_id")
    path = (
        root / "tasks" / task / "logs/lm_calls.jsonl"
        if task
        else (root / "baseline_artifacts/reme/initialization_lm_calls.jsonl")
    )
    return module.LLMCallLogger(
        sink=module.ProcessSafeJsonlSink(path),
        experiment_name=root.name,
        baseline="reme",
        root_task_id=task or "__initialization__",
    )


def pool_state(records):
    rows = sorted(records, key=lambda r: r["memory_id"])
    ids = [r["memory_id"] for r in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate memory IDs")
    content = [{k: r.get(k, "") for k in ("memory_id", "when_to_use", "content")} for r in rows]

    def digest(value):
        return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    return {"ids": ids, "count": len(ids), "content_sha256": digest(content), "state_sha256": digest(rows)}


def mapping_contains(observed, required):
    """Return whether an Elasticsearch mapping recursively contains required.

    A fresh ReMe index has only its declared base mapping.  Checkpoints made
    after writes also contain Elasticsearch's deterministic dynamic metadata
    fields.  Recovery may add those fields, but it must never replace or
    conflict with the base mapping already created by the pinned service.
    """

    if isinstance(required, dict):
        return isinstance(observed, dict) and all(
            key in observed and mapping_contains(observed[key], value) for key, value in required.items()
        )
    if isinstance(required, list):
        return observed == required
    return observed == required


def normalize_es_mappings(mappings):
    """Make implicit Elasticsearch object-field defaults explicit."""

    normalized = copy.deepcopy(mappings)

    def visit(field):
        properties = field.get("properties")
        if isinstance(properties, dict):
            field.setdefault("type", "object")
            field.setdefault("enabled", True)
            for child in properties.values():
                if isinstance(child, dict):
                    visit(child)

    properties = normalized.get("properties") if isinstance(normalized, dict) else None
    if isinstance(properties, dict):
        for field in properties.values():
            if isinstance(field, dict):
                visit(field)
    return normalized


def append_event(path, event):
    module = shared_logger()
    module.ProcessSafeJsonlSink(Path(path)).append(module.redact_secrets({"id": uuid.uuid4().hex, **event}))


def assert_current_owner(identity):
    """Fence actor/service work against the durable run ownership record."""
    token = identity.get("owner_token") if identity else None
    generation = identity.get("ownership_generation") if identity else None
    if token is None and generation is None:
        return
    if not token or type(generation) is not int:
        raise execution_recovery.StaleOwner("Incomplete run ownership identity")
    root = Path(identity["run_directory"]).resolve(strict=True)
    state = json.loads((root / execution_recovery.CLAIM_FILE).read_text())
    expected = (token, generation, "active")
    actual = (state.get("owner_token"), state.get("generation"), state.get("status"))
    if actual != expected:
        raise execution_recovery.StaleOwner("Provider work was fenced by a newer run owner")


def checked_response(response):
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict) or data.get("success") is not True:
        raise RuntimeError("Memory service did not acknowledge successful execution")
    return data


def audit_store_failures(store):
    """Retain infrastructure failures even if a summary helper catches them."""
    if getattr(store, "_execution_audited", False):
        return

    def guarded(function):
        @wraps(function)
        async def call(*args, **kwargs):
            try:
                return await function(*args, **kwargs)
            except Exception as error:
                if identity := AUDIT.get():
                    identity.setdefault("errors", []).append(type(error).__name__)
                raise

        return call

    for name in ("list", "get", "search", "insert", "update", "delete", "delete_all", "get_embeddings"):
        if hasattr(store, name):
            setattr(store, name, guarded(getattr(store, name)))
    store._execution_audited = True


class MemoryClient:
    def __init__(self, base_url, identity, token, session=None):
        import requests

        self.base_url, self.identity, self.token = base_url.rstrip("/") + "/", identity, token
        self.session = session or requests

    def call(self, endpoint, payload):
        task = self.identity.get("task_id")
        headers = {
            "X-ReMe-Audit-Token": self.token,
            "X-ReMe-Task": task or "",
            "X-ReMe-Request": uuid.uuid4().hex,
            "X-ReMe-Task-Attempt": self.identity.get("task_attempt_id", ""),
            "X-ReMe-Attempt-Kind": self.identity.get("attempt_kind", ""),
            "X-ReMe-Owner-Token": self.identity.get("owner_token", ""),
            "X-ReMe-Owner-Generation": str(self.identity.get("ownership_generation", "")),
        }
        logged_request = payload
        if endpoint == "audit/restore":
            logged_request = {
                "records_count": len(payload.get("records", [])),
                "records_sha256": payload.get("records_sha256"),
                "index_config_sha256": execution_recovery.json_sha256(payload.get("index_config", {})),
            }
        event = {
            "endpoint": endpoint,
            "request": logged_request,
            "started_at": now(),
            "task_attempt_id": self.identity.get("task_attempt_id"),
            "attempt_kind": self.identity.get("attempt_kind"),
            "ownership_generation": self.identity.get("ownership_generation"),
        }
        directory = Path(self.identity["run_directory"]) / "baseline_artifacts/reme"
        path = directory / task / "memory_events.jsonl" if task else directory / "initialization_events.jsonl"
        try:
            before = self.snapshot() if not endpoint.startswith("audit/") else None
            result = checked_response(
                self.session.post(self.base_url + endpoint, json=payload, headers=headers, timeout=1800)
            )
            if before is not None:
                after = self.snapshot()
                verify_mutation(endpoint, payload, result, before, after)
                previous, current = {r["memory_id"]: r for r in before}, {r["memory_id"]: r for r in after}
                event.update(
                    before=pool_state(before),
                    after=pool_state(after),
                    added_ids=sorted(current.keys() - previous.keys()),
                    deleted_ids=sorted(previous.keys() - current.keys()),
                    updated_ids=sorted(k for k in previous.keys() & current.keys() if previous[k] != current[k]),
                )
            logged_result = result
            if endpoint.startswith("audit/"):
                metadata = result.get("metadata", {})
                logged_result = {
                    "success": True,
                    "metadata": {
                        key: metadata.get(key)
                        for key in (
                            "records_sha256",
                            "index_config_sha256",
                        )
                        if key in metadata
                    },
                }
                if "records" in metadata:
                    logged_result["metadata"]["records_count"] = len(metadata["records"])
            event.update(status="success", response=logged_result)
            return result
        except BaseException as error:
            event.update(status="error", error_type=type(error).__name__, error=str(error))
            raise
        finally:
            event["finished_at"] = now()
            append_event(path, event)

    def snapshot(self):
        return self.call("audit/snapshot", {})["metadata"]["records"]

    def checkpoint(self):
        return self.call("audit/checkpoint", {})["metadata"]

    def restore(self, checkpoint):
        return self.call("audit/restore", checkpoint)["metadata"]

    def vector_search(self, vector, limit=5):
        return self.call("audit/vector-search", {"vector": vector, "limit": limit})["metadata"]


def verify_mutation(endpoint, payload, result, before, after):
    previous, current = {r["memory_id"]: r for r in before}, {r["memory_id"]: r for r in after}
    if endpoint in ("retrieve_task_memory", "summary_task_memory"):
        if pool_state(before)["state_sha256"] != pool_state(after)["state_sha256"]:
            raise RuntimeError("Retrieval/summary unexpectedly mutated the pool")
        if endpoint == "retrieve_task_memory":
            retrieved = result.get("metadata", {}).get("memory_list")
            if not isinstance(retrieved, list) or any(r["memory_id"] not in previous for r in retrieved):
                raise RuntimeError("Retrieved memory outside the acknowledged prior pool")
    elif endpoint == "add_task_memory":
        expected = dict(previous)
        for record in payload["memory_list"]:
            record = dict(record)
            record["memory_id"] = record.get("memory_id") or hashlib.sha256(record["content"].encode()).hexdigest()[:16]
            expected[record["memory_id"]] = record
        if pool_state(list(expected.values()))["content_sha256"] != pool_state(after)["content_sha256"]:
            raise RuntimeError("Memory addition was not fully committed")
    elif endpoint == "record_task_memory":
        if pool_state(before)["content_sha256"] != pool_state(after)["content_sha256"]:
            raise RuntimeError("Metadata recording changed pool membership/content")
        for record in payload["memory_list"]:
            meta = current[record["memory_id"]]["metadata"]
            old = record.get("metadata", {})
            if meta.get("freq") != old.get("freq", 0) + 1:
                raise RuntimeError("Frequency update not committed")
            if meta.get("utility", 0) != old.get("utility", 0) + int(payload["update_utility"]):
                raise RuntimeError("Utility update not committed")
    elif endpoint == "delete_task_memory":
        removed = {
            k
            for k, r in previous.items()
            if r.get("metadata", {}).get("freq", 0) >= payload["freq_threshold"]
            and r["metadata"]["freq"] > 0
            and r["metadata"].get("utility", 0) / r["metadata"]["freq"] < payload["utility_threshold"]
        }
        expected = [r for k, r in previous.items() if k not in removed]
        if pool_state(expected)["content_sha256"] != pool_state(after)["content_sha256"]:
            raise RuntimeError("Memory deletion was not fully committed")


def install_service_audit(service):
    """Opt-in local service contract; clients cannot choose arbitrary log paths."""
    run_directory = os.environ.get("REME_AUDIT_RUN_DIRECTORY")
    if not run_directory:
        return
    import secrets
    from fastapi import Request
    from fastapi.responses import JSONResponse
    from reme.core.schema.memory_node import MemoryNode

    root = Path(run_directory).resolve(strict=True)
    manifest = json.loads((root / "run_manifest.json").read_text())
    expected_token = os.environ["REME_AUDIT_TOKEN"]

    def fenced(request):
        expected_owner = os.environ.get("REME_AUDIT_OWNER_TOKEN")
        expected_generation = os.environ.get("REME_AUDIT_OWNER_GENERATION")
        if not expected_owner and not expected_generation:
            return None
        if not expected_owner or not expected_generation:
            raise RuntimeError("Incomplete service ownership fence")
        claim = json.loads((root / execution_recovery.CLAIM_FILE).read_text())
        actual = (
            request.headers.get("X-ReMe-Owner-Token"),
            request.headers.get("X-ReMe-Owner-Generation"),
            claim.get("owner_token"),
            str(claim.get("generation")),
            claim.get("status"),
        )
        expected = (expected_owner, expected_generation, expected_owner, expected_generation, "active")
        if actual != expected:
            raise execution_recovery.StaleOwner("Service request was fenced by a newer run owner")
        return int(expected_generation)

    async def raw_checkpoint():
        store = service.service_context.vector_stores["default"]
        nodes = await store.list()
        count = await store.client.count(index=store.collection_name)
        if count["count"] != len(nodes):
            raise RuntimeError("Memory checkpoint is incomplete")
        records = execution_recovery.normalize_vector_records([node.model_dump(mode="json") for node in nodes], 1024)
        mapping = await store.client.indices.get_mapping(index=store.collection_name)
        settings = await store.client.indices.get_settings(index=store.collection_name)
        index_settings = settings[store.collection_name]["settings"]["index"]
        index_config = {
            "mappings": normalize_es_mappings(mapping[store.collection_name]["mappings"]),
            "settings": {key: index_settings.get(key) for key in ("number_of_shards", "number_of_replicas")},
        }
        return {
            "records": records,
            "records_sha256": execution_recovery.vector_records_sha256(records, 1024),
            "index_config": index_config,
            "index_config_sha256": execution_recovery.json_sha256(index_config),
        }

    @service.http_service.middleware("http")
    async def attributed_request(request: Request, call_next):
        if request.url.path == "/health":
            return await call_next(request)
        if not secrets.compare_digest(request.headers.get("X-ReMe-Audit-Token", ""), expected_token):
            return JSONResponse({"success": False}, status_code=403)
        try:
            owner_generation = fenced(request)
        except (OSError, ValueError, execution_recovery.RecoveryError):
            return JSONResponse({"success": False, "answer": "stale run owner"}, status_code=409)
        task = request.headers.get("X-ReMe-Task") or None
        if task is not None and task not in manifest["task_ids"]:
            return JSONResponse({"success": False}, status_code=400)
        audit_store_failures(service.service_context.vector_stores["default"])
        identity = {
            "run_directory": str(root),
            "task_id": task,
            "phase": request.url.path.strip("/"),
            "request_id": request.headers.get("X-ReMe-Request"),
            "campaign": manifest.get("campaign"),
            "run": manifest.get("experiment_name", root.name),
            "stage": request.url.path.strip("/"),
            "task_attempt_id": request.headers.get("X-ReMe-Task-Attempt") or "initialization",
            "attempt_kind": request.headers.get("X-ReMe-Attempt-Kind") or "primary",
            "ownership_generation": owner_generation,
            "owner_token": request.headers.get("X-ReMe-Owner-Token") or None,
            "attempts": {},
            "errors": [],
        }
        with audit_scope(identity):
            response = await call_next(request)
            if identity["errors"]:
                return JSONResponse({"success": False, "answer": "Provider failure; run incomplete"}, status_code=502)
            return response

    @service.http_service.post("/audit/snapshot")
    async def snapshot():
        store = service.service_context.vector_stores["default"]
        nodes = await store.list()
        count = await store.client.count(index=store.collection_name)
        if count["count"] != len(nodes):
            raise RuntimeError("Memory snapshot is incomplete")
        if any(not n.vector or len(n.vector) != 1024 for n in nodes):
            raise RuntimeError("Memory snapshot has missing or invalid embeddings")
        records = [MemoryNode.from_vector_node(n).model_dump(mode="json", exclude={"vector"}) for n in nodes]
        return {"success": True, "metadata": {"records": records}}

    @service.http_service.post("/audit/checkpoint")
    async def checkpoint():
        return {"success": True, "metadata": await raw_checkpoint()}

    @service.http_service.post("/audit/restore")
    async def restore(payload: dict):
        from reme.core.schema.vector_node import VectorNode

        store = service.service_context.vector_stores["default"]
        if await store.list():
            raise RuntimeError("Recovery restore requires a fresh empty collection")
        records = execution_recovery.normalize_vector_records(payload.get("records", []), 1024)
        if execution_recovery.vector_records_sha256(records, 1024) != payload.get("records_sha256"):
            raise RuntimeError("Recovery vector digest mismatch")
        desired_config = payload.get("index_config")
        if not isinstance(desired_config, dict):
            raise RuntimeError("Recovery index configuration is invalid")
        current = await raw_checkpoint()
        if current["index_config"]["settings"] != desired_config.get("settings") or not mapping_contains(
            desired_config.get("mappings"), current["index_config"]["mappings"]
        ):
            raise RuntimeError("Recovery index configuration conflicts with the fresh service")
        if current["index_config"]["mappings"] != desired_config.get("mappings"):
            await store.client.indices.put_mapping(index=store.collection_name, body=desired_config["mappings"])
            mapped = await raw_checkpoint()
            if mapped["index_config"] != desired_config:
                raise RuntimeError("Recovery index mapping could not be reproduced")
        if records:
            await store.insert([VectorNode.model_validate(record) for record in records])
        restored = await raw_checkpoint()
        if restored["records_sha256"] != payload["records_sha256"] or restored[
            "index_config_sha256"
        ] != execution_recovery.json_sha256(desired_config):
            raise RuntimeError("Recovery restore verification failed")
        return {"success": True, "metadata": restored}

    @service.http_service.post("/audit/vector-search")
    async def vector_search(payload: dict):
        store = service.service_context.vector_stores["default"]
        vector = payload.get("vector")
        limit = payload.get("limit", 5)
        execution_recovery.normalize_vector_records(
            [{"vector_id": "query", "content": "", "vector": vector, "metadata": {}}], 1024
        )
        if type(limit) is not int or not 1 <= limit <= 20:
            raise ValueError("Vector-search limit must be 1-20")
        response = await store.client.search(
            index=store.collection_name,
            knn={
                "field": "vector",
                "query_vector": vector,
                "k": limit,
                "num_candidates": max(20, limit),
            },
            size=limit,
            source=["vector_id"],
        )
        hits = [
            {"vector_id": hit["_source"].get("vector_id", hit["_id"]), "score": hit.get("_score")}
            for hit in response["hits"]["hits"]
        ]
        return {"success": True, "metadata": {"hits": hits}}

    @service.http_service.post("/audit/identity")
    async def identity():
        ctx = service.service_context
        return {
            "success": True,
            "metadata": {
                "collection": ctx.vector_stores["default"].collection_name,
                "backend": ctx.service_config.vector_stores["default"].backend,
                "model": ctx.llms["default"].model_name,
                "embedding_model": ctx.embedding_models["default"].model_name,
                "dimensions": ctx.embedding_models["default"].dimensions,
            },
        }


def provider_http_client(async_mode=False, transport=None):
    """Observe physical HTTP attempts below SDK retries without changing yielded bytes."""
    import httpx
    from openai import DefaultAsyncHttpxClient, DefaultHttpxClient

    class Attempt:
        def __init__(self, request):
            self.identity, self.started = AUDIT.get(), now()
            if os.environ.get("REME_AUDIT_RUN_DIRECTORY") and self.identity is None:
                raise RuntimeError("Audited service provider call lacks request attribution")
            if self.identity:
                assert_current_owner(self.identity)
            self.parts, self.done, self.status_code = [], False, None
            self.response_headers = {}
            self.request = json.loads(request.content) if request.content else {}
            self.logical = hashlib.sha256(json.dumps(self.request, sort_keys=True).encode()).hexdigest()
            formal = bool(os.environ.get(execution_accounting.ENVIRONMENT_KEY))
            smoke = bool(os.environ.get(execution_budget.ENVIRONMENT_KEY))
            if formal and smoke:
                raise RuntimeError("Smoke budget and formal accounting cannot both be active")
            self.accounting_mode = "formal" if formal else "smoke" if smoke else None
            self.physical_id = execution_accounting.new_physical_id() if formal else uuid.uuid4().hex
            self.budgeted = False
            if formal:
                if not self.identity:
                    raise RuntimeError("Formal provider call lacks execution identity")
                accounting_identity = {
                    "campaign": self.identity.get("campaign"),
                    "run": self.identity.get("run"),
                    "stage": self.identity.get("stage", self.identity.get("phase")),
                    "task": self.identity.get("task_id"),
                    "task_attempt_id": self.identity.get("task_attempt_id"),
                    "attempt_kind": self.identity.get("attempt_kind"),
                    "ownership_generation": self.identity.get("ownership_generation"),
                }
                execution_accounting.start(
                    self.physical_id,
                    str(request.url),
                    self.request,
                    accounting_identity,
                    started_at=self.started,
                )
            elif smoke:
                self.budgeted = execution_budget.reserve(
                    self.physical_id, str(request.url), self.request, self.identity
                )
            if self.identity:
                attempts = self.identity.setdefault("attempts", {})
                attempts[self.logical] = attempts.get(self.logical, 0) + 1
                self.attempt = attempts[self.logical]

        def finish(self, error=None, closed=False):
            if self.done or not self.identity:
                return
            self.done = True
            assert_current_owner(self.identity)
            # The transport yields compressed wire bytes, before HTTPX's normal
            # response decoding. Decode only this audit copy; forward the exact
            # original bytes to the SDK, including for streamed responses.
            try:
                decoded = httpx.Response(
                    self.status_code or 200, headers=self.response_headers, content=b"".join(self.parts)
                ).content
            except Exception as decoding_error:
                error = error or decoding_error
                decoded = b""
            raw = decoded.decode("utf-8", errors="replace")
            # OpenAI's stream iterator stops at [DONE] without advancing the
            # transport iterator to EOF. That explicit terminal is completion,
            # not a prematurely abandoned stream. Preserve genuine read errors.
            terminal = any(line.strip() == "data: [DONE]" for line in raw.splitlines())
            if closed and not terminal:
                error = error or RuntimeError("Response stream closed before completion")
            try:
                output = json.loads(raw)
            except ValueError:
                chunks = []
                for line in raw.splitlines():
                    if line.startswith("data: ") and line != "data: [DONE]":
                        try:
                            chunks.append(json.loads(line[6:]))
                        except ValueError:
                            error = error or ValueError("Malformed provider stream")
                output = {
                    "chunks": chunks,
                    "usage": next((c["usage"] for c in reversed(chunks) if c.get("usage")), None),
                }
                output["model"] = next((c["model"] for c in chunks if c.get("model")), None)
                if not chunks:
                    output["body"] = raw
            module = shared_logger()
            if "input" in self.request and error is None and self.status_code == 200:
                output = module.EmbeddingSerializer().response(output)
            failed = error is not None or self.status_code is None or self.status_code >= 400
            if failed:
                output = {
                    "response": output,
                    "error_type": type(error).__name__ if error else "HTTPError",
                    "error": str(error) if error else str(self.status_code),
                }
                self.identity.setdefault("errors", []).append(output["error_type"])
            if self.budgeted:
                execution_budget.settle(self.physical_id, output, failed)
            elif self.accounting_mode == "formal":
                execution_accounting.settle(self.physical_id, output, failed, finished_at=now())
            context = module.LLMCallContext(
                phase=self.identity.get("phase", "executor"),
                component=self.identity.get("operation", "reme2" if async_mode else "executor"),
                logical_call_id=f'{self.identity.get("request_id", "executor")}:{self.logical}',
                attempt=self.attempt,
                metadata={
                    "http_status": self.status_code,
                    "campaign": self.identity.get("campaign"),
                    "run": self.identity.get("run"),
                    "stage": self.identity.get("stage", self.identity.get("phase")),
                    "task_attempt_id": self.identity.get("task_attempt_id"),
                    "attempt_kind": self.identity.get("attempt_kind"),
                    "ownership_generation": self.identity.get("ownership_generation"),
                },
            )
            logger_for(self.identity)._record(
                physical_id=self.physical_id,
                request=self.request,
                output=output,
                context=context,
                started_at=self.started,
                status="error" if failed else "success",
            )

    class SyncStream(httpx.SyncByteStream):
        def __init__(self, wrapped, attempt):
            self.wrapped, self.attempt = wrapped, attempt

        def __iter__(self):
            try:
                for chunk in self.wrapped:
                    self.attempt.parts.append(chunk)
                    yield chunk
                self.attempt.finish()
            except BaseException as error:
                self.attempt.finish(error)
                raise

        def close(self):
            self.wrapped.close()
            if not self.attempt.done:
                self.attempt.finish(closed=True)

    class AsyncStream(httpx.AsyncByteStream):
        def __init__(self, wrapped, attempt):
            self.wrapped, self.attempt = wrapped, attempt

        async def __aiter__(self):
            try:
                async for chunk in self.wrapped:
                    self.attempt.parts.append(chunk)
                    yield chunk
                self.attempt.finish()
            except BaseException as error:
                self.attempt.finish(error)
                raise

        async def aclose(self):
            await self.wrapped.aclose()
            if not self.attempt.done:
                self.attempt.finish(closed=True)

    class SyncTransport(httpx.BaseTransport):
        def __init__(self):
            self.inner = transport or httpx.HTTPTransport()

        def handle_request(self, request):
            attempt = Attempt(request)
            try:
                response = self.inner.handle_request(request)
                attempt.status_code = response.status_code
                attempt.response_headers = {"content-encoding": response.headers.get("content-encoding", "identity")}
                response.stream = SyncStream(response.stream, attempt)
                return response
            except BaseException as error:
                attempt.finish(error)
                raise

        def close(self):
            self.inner.close()

    class AsyncTransport(httpx.AsyncBaseTransport):
        def __init__(self):
            self.inner = transport or httpx.AsyncHTTPTransport()

        async def handle_async_request(self, request):
            attempt = Attempt(request)
            try:
                response = await self.inner.handle_async_request(request)
                attempt.status_code = response.status_code
                attempt.response_headers = {"content-encoding": response.headers.get("content-encoding", "identity")}
                response.stream = AsyncStream(response.stream, attempt)
                return response
            except BaseException as error:
                attempt.finish(error)
                raise

        async def aclose(self):
            await self.inner.aclose()

    return (
        DefaultAsyncHttpxClient(transport=AsyncTransport())
        if async_mode
        else (DefaultHttpxClient(transport=SyncTransport()))
    )
