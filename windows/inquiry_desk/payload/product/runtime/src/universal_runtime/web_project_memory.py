from __future__ import annotations

import hashlib
import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from universal_runtime.core.artifact_store import ArtifactCurrentnessError, ArtifactStore
from universal_runtime.core.enums import PersistenceClass


MEMORY_STATE_SCHEMA = "UR_WEB_PROJECT_MEMORY_STATE_R001"
MEMORY_CONTEXT_SCHEMA = "UR_WEB_PROJECT_MEMORY_CONTEXT_R001"
MEMORY_STATE_GUARD_SCHEMA = "UR_WEB_PROJECT_MEMORY_STATE_GUARD_R001"
MEMORY_ITEM_AUTHORITY = "RUNTIME_AUTHORITATIVE_PROJECT_MEMORY_ITEM"
MEMORY_STATE_AUTHORITY = "RUNTIME_AUTHORITATIVE_PROJECT_MEMORY_STATE"
MEMORY_CONTEXT_AUTHORITY = "NON_AUTHORITY_FORMAL_INPUT_PROPOSAL"
MAX_MEMORY_CHARS = 2000
MAX_MEMORY_ITEMS = 100
MAX_ACTIVE_MEMORY_ITEMS = 20
MAX_COMMAND_RECORDS = 500
_ID_RE = re.compile(r"^[A-Z0-9_]{3,96}$")
_COMMAND_RE = re.compile(r"^[A-Za-z0-9._:-]{1,160}$")
_HIGH_SIGNAL_SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", re.I),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\b(?:api[_ -]?key|access[_ -]?token|secret|password)\s*[:=]\s*[^\s]{8,}", re.I),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]{20,}=*\b", re.I),
)
_MEMORY_LOCK = threading.RLock()


class ProjectMemoryError(ValueError):
    def __init__(self, code: str, message: str, *, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _stable_id(prefix: str, *parts: str, length: int = 24) -> str:
    return f"{prefix}_{hashlib.sha256(chr(31).join(parts).encode('utf-8')).hexdigest()[:length].upper()}"


def _validate_project_id(project_id: str) -> str:
    if not isinstance(project_id, str) or _ID_RE.fullmatch(project_id) is None or not project_id.startswith("PRJ_"):
        raise ProjectMemoryError("INVALID_PROJECT_ID", "project_id must be one exact Runtime Project identity")
    return project_id


def _validate_command_id(command_id: str) -> str:
    if not isinstance(command_id, str) or _COMMAND_RE.fullmatch(command_id) is None:
        raise ProjectMemoryError("INVALID_COMMAND_ID", "command_id must be 1-160 safe characters")
    return command_id


def _contains_high_signal_secret(text: str) -> bool:
    return any(pattern.search(text) is not None for pattern in _HIGH_SIGNAL_SECRET_PATTERNS)


def _validate_content(content: str) -> str:
    if not isinstance(content, str):
        raise ProjectMemoryError("INVALID_MEMORY_CONTENT", "memory content must be text")
    content = content.strip()
    if not content or len(content) > MAX_MEMORY_CHARS:
        raise ProjectMemoryError(
            "INVALID_MEMORY_CONTENT",
            f"memory content must be 1-{MAX_MEMORY_CHARS} characters after trimming",
        )
    if any(ord(ch) < 32 and ch not in "\n\t" for ch in content):
        raise ProjectMemoryError("INVALID_MEMORY_CONTENT", "memory content contains forbidden control characters")
    if _contains_high_signal_secret(content):
        raise ProjectMemoryError(
            "MEMORY_SECRET_LIKE_CONTENT_FORBIDDEN",
            "high-signal secret-like content is forbidden in Project Memory first slice",
            status_code=409,
        )
    return content


def _memory_item_sha(item: dict[str, Any]) -> str:
    stable = {
        "memory_id": item["memory_id"],
        "memory_revision": item["memory_revision"],
        "lifecycle_state": item["lifecycle_state"],
        "content": item["content"],
        "content_sha256": item["content_sha256"],
        "created_at_utc": item["created_at_utc"],
        "updated_at_utc": item["updated_at_utc"],
        "provenance": item["provenance"],
        "previous_memory_item_sha256": item.get("previous_memory_item_sha256"),
    }
    return _sha(stable)


class ProjectMemoryService:
    """Project-scoped explicit Memory authority for the P2B first slice.

    One project has one authoritative state Artifact. Each user mutation appends exactly
    one ArtifactStore revision, avoiding multi-artifact partial commit. Model output does
    not create/edit Memory in this slice.
    """

    def __init__(self, artifact_store: ArtifactStore):
        self.store = artifact_store

    @staticmethod
    def state_artifact_id(project_id: str) -> str:
        project_id = _validate_project_id(project_id)
        return "WEB_PROJECT_MEMORY_STATE_" + hashlib.sha256(project_id.encode("utf-8")).hexdigest().upper()

    def _state_exists(self, project_id: str) -> bool:
        artifact_id = self.state_artifact_id(project_id)
        return self.store.manifest_path(artifact_id, 1).parent.is_dir()

    def _binding(self, manifest: Any) -> dict[str, Any]:
        return {
            "artifact_id": manifest.artifact_id,
            "revision": manifest.revision,
            "sha256": manifest.sha256,
        }

    def _load_state(self, project_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        project_id = _validate_project_id(project_id)
        artifact_id = self.state_artifact_id(project_id)
        if not self._state_exists(project_id):
            return (
                {
                    "schema": MEMORY_STATE_SCHEMA,
                    "authority_class": MEMORY_STATE_AUTHORITY,
                    "project_id": project_id,
                    "state_revision": 0,
                    "items": [],
                    "command_records": [],
                    "created_at_utc": None,
                    "updated_at_utc": None,
                },
                {"artifact_id": artifact_id, "revision": 0, "sha256": None},
            )
        try:
            manifest = self.store.current_manifest(artifact_id)
        except ArtifactCurrentnessError as exc:
            raise ProjectMemoryError("MEMORY_STATE_STALE_OR_TAMPERED", str(exc), status_code=409) from exc
        try:
            raw = Path(manifest.path).read_bytes()
            if _sha_bytes(raw) != manifest.sha256:
                raise ProjectMemoryError("MEMORY_STATE_STALE_OR_TAMPERED", "memory state bytes differ from manifest", status_code=409)
            state = json.loads(raw.decode("utf-8"))
        except ProjectMemoryError:
            raise
        except Exception as exc:
            raise ProjectMemoryError("MEMORY_STATE_CORRUPT", "memory state is not valid canonical JSON", status_code=500) from exc
        if (
            not isinstance(state, dict)
            or state.get("schema") != MEMORY_STATE_SCHEMA
            or state.get("authority_class") != MEMORY_STATE_AUTHORITY
            or state.get("project_id") != project_id
            or state.get("state_revision") != manifest.revision
            or not isinstance(state.get("items"), list)
            or not isinstance(state.get("command_records"), list)
        ):
            raise ProjectMemoryError("MEMORY_STATE_CORRUPT", "memory state identity/revision is invalid", status_code=500)
        for item in state["items"]:
            self._validate_item_record(item, project_id=project_id)
        return state, self._binding(manifest)

    def _persist_state(self, *, state: dict[str, Any], operation_execution_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        project_id = _validate_project_id(state.get("project_id"))
        artifact_id = self.state_artifact_id(project_id)
        next_revision = self.store.next_revision(artifact_id)
        payload = dict(state)
        payload["schema"] = MEMORY_STATE_SCHEMA
        payload["authority_class"] = MEMORY_STATE_AUTHORITY
        payload["state_revision"] = next_revision
        payload["updated_at_utc"] = _utc_now()
        if not payload.get("created_at_utc"):
            payload["created_at_utc"] = payload["updated_at_utc"]
        relative = f"web_memory/{hashlib.sha256(project_id.encode('utf-8')).hexdigest().upper()}/R{next_revision:03d}.json"
        manifest = self.store.persist_exact_text(
            artifact_id=artifact_id,
            relative_path=relative,
            text=_canonical_bytes(payload).decode("utf-8"),
            job_id=operation_execution_id,
            persistence_class=PersistenceClass.AUTHORITATIVE,
            input_fingerprint=None,
            metadata={
                "web_project_memory": True,
                "project_id": project_id,
                "authority_class": MEMORY_STATE_AUTHORITY,
                "operation_execution_id": operation_execution_id,
            },
        )
        if manifest.revision != next_revision:
            raise ProjectMemoryError("MEMORY_REVISION_RACE", "memory state revision changed during persist", status_code=409)
        return payload, self._binding(manifest)

    def _validate_item_record(self, item: Any, *, project_id: str) -> dict[str, Any]:
        if not isinstance(item, dict):
            raise ProjectMemoryError("MEMORY_STATE_CORRUPT", "memory item must be object", status_code=500)
        memory_id = item.get("memory_id")
        if not isinstance(memory_id, str) or not memory_id.startswith("MEM_") or _ID_RE.fullmatch(memory_id) is None:
            raise ProjectMemoryError("MEMORY_STATE_CORRUPT", "memory_id invalid", status_code=500)
        if item.get("project_id") != project_id:
            raise ProjectMemoryError("MEMORY_CROSS_PROJECT_FORBIDDEN", "memory item project scope mismatch", status_code=409)
        revision = item.get("memory_revision")
        state = item.get("lifecycle_state")
        content = item.get("content")
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
            raise ProjectMemoryError("MEMORY_STATE_CORRUPT", "memory revision invalid", status_code=500)
        if state not in {"ACTIVE", "DISABLED", "DELETED"}:
            raise ProjectMemoryError("MEMORY_STATE_CORRUPT", "memory lifecycle invalid", status_code=500)
        if not isinstance(content, str):
            raise ProjectMemoryError("MEMORY_STATE_CORRUPT", "memory content invalid", status_code=500)
        if state != "DELETED":
            _validate_content(content)
        elif content != "":
            raise ProjectMemoryError("MEMORY_STATE_CORRUPT", "deleted memory current tombstone must not expose content", status_code=500)
        expected_content_sha = _sha_bytes(content.encode("utf-8"))
        if item.get("content_sha256") != expected_content_sha:
            raise ProjectMemoryError("MEMORY_STATE_CORRUPT", "memory content SHA mismatch", status_code=500)
        if item.get("memory_item_sha256") != _memory_item_sha(item):
            raise ProjectMemoryError("MEMORY_STATE_CORRUPT", "memory item semantic SHA mismatch", status_code=500)
        provenance = item.get("provenance")
        if not isinstance(provenance, dict) or provenance.get("origin_class") != "USER_EXPLICIT_WEB":
            raise ProjectMemoryError("MEMORY_STATE_CORRUPT", "memory provenance invalid", status_code=500)
        return item

    def _command_fingerprint(self, *, project_id: str, command_id: str, command_type: str, payload: dict[str, Any]) -> str:
        return _sha({
            "schema": "UR_WEB_PROJECT_MEMORY_COMMAND_FINGERPRINT_R001",
            "project_id": project_id,
            "command_id": command_id,
            "command_type": command_type,
            "payload": payload,
        })

    def _find_command(self, state: dict[str, Any], command_id: str) -> dict[str, Any] | None:
        matches = [r for r in state.get("command_records", []) if isinstance(r, dict) and r.get("command_id") == command_id]
        if len(matches) > 1:
            raise ProjectMemoryError("MEMORY_STATE_CORRUPT", "duplicate memory command record", status_code=500)
        return matches[0] if matches else None

    def _item_by_id(self, state: dict[str, Any], memory_id: str) -> dict[str, Any]:
        matches = [x for x in state.get("items", []) if isinstance(x, dict) and x.get("memory_id") == memory_id]
        if len(matches) != 1:
            raise ProjectMemoryError("MEMORY_NOT_FOUND", "memory_id not found exactly once", status_code=404)
        return matches[0]

    def _operation_id(self, project_id: str, command_id: str, command_type: str) -> str:
        return "MEMOP_" + _sha({"project_id": project_id, "command_id": command_id, "command_type": command_type})

    def _response(self, *, item: dict[str, Any], state: dict[str, Any], binding: dict[str, Any], replayed: bool) -> dict[str, Any]:
        return {
            "memory": dict(item),
            "memory_binding": {
                **dict(binding),
                "memory_id": item["memory_id"],
                "memory_revision": item["memory_revision"],
                "memory_item_sha256": item["memory_item_sha256"],
            },
            "state_revision": state["state_revision"],
            "replayed": replayed,
        }

    def _append_command_record(
        self,
        *,
        state: dict[str, Any],
        command_id: str,
        command_type: str,
        fingerprint: str,
        memory_id: str,
        memory_revision: int,
        result_state_revision: int,
    ) -> list[dict[str, Any]]:
        history = list(state.get("command_records", []))
        if len(history) >= MAX_COMMAND_RECORDS:
            raise ProjectMemoryError("MEMORY_COMMAND_HISTORY_LIMIT", "memory command history limit reached", status_code=409)
        history.append({
            "command_id": command_id,
            "command_type": command_type,
            "input_fingerprint_sha256": fingerprint,
            "memory_id": memory_id,
            "memory_revision": memory_revision,
            "result_state_revision": result_state_revision,
            "created_at_utc": _utc_now(),
        })
        return history

    def create_memory(
        self,
        *,
        command_id: str,
        project_id: str,
        content: str,
        project_revision_at_create: int,
    ) -> dict[str, Any]:
        command_id = _validate_command_id(command_id)
        project_id = _validate_project_id(project_id)
        content = _validate_content(content)
        if isinstance(project_revision_at_create, bool) or not isinstance(project_revision_at_create, int) or project_revision_at_create < 1:
            raise ProjectMemoryError("INVALID_PROJECT_REVISION", "positive current project revision required")
        fingerprint = self._command_fingerprint(
            project_id=project_id,
            command_id=command_id,
            command_type="MEMORY_CREATE",
            payload={"content_sha256": _sha_bytes(content.encode("utf-8")), "project_revision": project_revision_at_create},
        )
        with _MEMORY_LOCK:
            state, binding = self._load_state(project_id)
            prior = self._find_command(state, command_id)
            if prior is not None:
                if prior.get("input_fingerprint_sha256") != fingerprint:
                    raise ProjectMemoryError("IDEMPOTENCY_CONFLICT", "memory command_id reused with different input", status_code=409)
                if state["state_revision"] != prior.get("result_state_revision"):
                    raise ProjectMemoryError("IDEMPOTENCY_REPLAY_STALE", "memory command replay is stale after later memory mutation", status_code=409)
                return self._response(item=self._item_by_id(state, prior["memory_id"]), state=state, binding=binding, replayed=True)
            if len(state["items"]) >= MAX_MEMORY_ITEMS:
                raise ProjectMemoryError("MEMORY_ITEM_LIMIT", "project memory item limit reached", status_code=409)
            memory_id = _stable_id("MEM", project_id, command_id)
            if any(x.get("memory_id") == memory_id for x in state["items"] if isinstance(x, dict)):
                raise ProjectMemoryError("MEMORY_ID_COLLISION", "memory identity collision", status_code=409)
            now = _utc_now()
            item = {
                "schema": "UR_WEB_PROJECT_MEMORY_ITEM_R001",
                "authority_class": MEMORY_ITEM_AUTHORITY,
                "project_id": project_id,
                "memory_id": memory_id,
                "memory_revision": 1,
                "lifecycle_state": "ACTIVE",
                "content": content,
                "content_sha256": _sha_bytes(content.encode("utf-8")),
                "created_at_utc": now,
                "updated_at_utc": now,
                "provenance": {
                    "origin_class": "USER_EXPLICIT_WEB",
                    "created_by_command_id": command_id,
                    "project_revision_at_create": project_revision_at_create,
                    "model_generated": False,
                    "external_source": None,
                },
                "previous_memory_item_sha256": None,
            }
            item["memory_item_sha256"] = _memory_item_sha(item)
            next_state_revision = state["state_revision"] + 1
            next_state = dict(state)
            next_state["items"] = list(state["items"]) + [item]
            next_state["command_records"] = self._append_command_record(
                state=state,
                command_id=command_id,
                command_type="MEMORY_CREATE",
                fingerprint=fingerprint,
                memory_id=memory_id,
                memory_revision=1,
                result_state_revision=next_state_revision,
            )
            persisted, new_binding = self._persist_state(
                state=next_state,
                operation_execution_id=self._operation_id(project_id, command_id, "MEMORY_CREATE"),
            )
            return self._response(item=self._item_by_id(persisted, memory_id), state=persisted, binding=new_binding, replayed=False)

    def _mutate_memory(
        self,
        *,
        command_id: str,
        project_id: str,
        memory_id: str,
        expected_memory_revision: int,
        command_type: str,
        new_content: str | None = None,
        new_state: str | None = None,
    ) -> dict[str, Any]:
        command_id = _validate_command_id(command_id)
        project_id = _validate_project_id(project_id)
        if not isinstance(memory_id, str) or not memory_id.startswith("MEM_"):
            raise ProjectMemoryError("INVALID_MEMORY_ID", "memory_id invalid")
        if isinstance(expected_memory_revision, bool) or not isinstance(expected_memory_revision, int) or expected_memory_revision < 1:
            raise ProjectMemoryError("INVALID_MEMORY_REVISION", "positive expected memory revision required")
        if new_content is not None:
            new_content = _validate_content(new_content)
        if new_state is not None and new_state not in {"ACTIVE", "DISABLED", "DELETED"}:
            raise ProjectMemoryError("INVALID_MEMORY_STATE", "invalid target memory state")
        fingerprint = self._command_fingerprint(
            project_id=project_id,
            command_id=command_id,
            command_type=command_type,
            payload={
                "memory_id": memory_id,
                "expected_memory_revision": expected_memory_revision,
                "new_content_sha256": _sha_bytes(new_content.encode("utf-8")) if new_content is not None else None,
                "new_state": new_state,
            },
        )
        with _MEMORY_LOCK:
            state, binding = self._load_state(project_id)
            prior = self._find_command(state, command_id)
            if prior is not None:
                if prior.get("input_fingerprint_sha256") != fingerprint:
                    raise ProjectMemoryError("IDEMPOTENCY_CONFLICT", "memory command_id reused with different input", status_code=409)
                if state["state_revision"] != prior.get("result_state_revision"):
                    raise ProjectMemoryError("IDEMPOTENCY_REPLAY_STALE", "memory command replay is stale after later memory mutation", status_code=409)
                return self._response(item=self._item_by_id(state, memory_id), state=state, binding=binding, replayed=True)
            current = self._item_by_id(state, memory_id)
            if current["project_id"] != project_id:
                raise ProjectMemoryError("MEMORY_CROSS_PROJECT_FORBIDDEN", "memory does not belong to project", status_code=409)
            if current["memory_revision"] != expected_memory_revision:
                raise ProjectMemoryError("STALE_MEMORY_REVISION", "expected memory revision is stale", status_code=409)
            if current["lifecycle_state"] == "DELETED":
                raise ProjectMemoryError("MEMORY_DELETED", "deleted memory cannot be mutated", status_code=410)
            target_content = current["content"] if new_content is None else new_content
            target_state = current["lifecycle_state"] if new_state is None else new_state
            if target_state == "DELETED":
                target_content = ""
            if target_content == current["content"] and target_state == current["lifecycle_state"]:
                raise ProjectMemoryError("MEMORY_NO_OP", "memory mutation would make no change", status_code=409)
            next_item = dict(current)
            next_item["memory_revision"] = current["memory_revision"] + 1
            next_item["lifecycle_state"] = target_state
            next_item["content"] = target_content
            next_item["content_sha256"] = _sha_bytes(target_content.encode("utf-8"))
            next_item["updated_at_utc"] = _utc_now()
            next_item["previous_memory_item_sha256"] = current["memory_item_sha256"]
            next_item["memory_item_sha256"] = _memory_item_sha(next_item)
            next_items = [next_item if x.get("memory_id") == memory_id else x for x in state["items"]]
            next_state_revision = state["state_revision"] + 1
            next_state = dict(state)
            next_state["items"] = next_items
            next_state["command_records"] = self._append_command_record(
                state=state,
                command_id=command_id,
                command_type=command_type,
                fingerprint=fingerprint,
                memory_id=memory_id,
                memory_revision=next_item["memory_revision"],
                result_state_revision=next_state_revision,
            )
            persisted, new_binding = self._persist_state(
                state=next_state,
                operation_execution_id=self._operation_id(project_id, command_id, command_type),
            )
            return self._response(item=self._item_by_id(persisted, memory_id), state=persisted, binding=new_binding, replayed=False)

    def revise_memory(self, *, command_id: str, project_id: str, memory_id: str, expected_memory_revision: int, content: str) -> dict[str, Any]:
        return self._mutate_memory(
            command_id=command_id,
            project_id=project_id,
            memory_id=memory_id,
            expected_memory_revision=expected_memory_revision,
            command_type="MEMORY_REVISE",
            new_content=content,
        )

    def set_memory_enabled(self, *, command_id: str, project_id: str, memory_id: str, expected_memory_revision: int, enabled: bool) -> dict[str, Any]:
        if not isinstance(enabled, bool):
            raise ProjectMemoryError("INVALID_MEMORY_STATE", "enabled must be boolean")
        return self._mutate_memory(
            command_id=command_id,
            project_id=project_id,
            memory_id=memory_id,
            expected_memory_revision=expected_memory_revision,
            command_type="MEMORY_ENABLE" if enabled else "MEMORY_DISABLE",
            new_state="ACTIVE" if enabled else "DISABLED",
        )

    def delete_memory(self, *, command_id: str, project_id: str, memory_id: str, expected_memory_revision: int) -> dict[str, Any]:
        return self._mutate_memory(
            command_id=command_id,
            project_id=project_id,
            memory_id=memory_id,
            expected_memory_revision=expected_memory_revision,
            command_type="MEMORY_DELETE",
            new_state="DELETED",
        )

    def list_memories(self, *, project_id: str, include_deleted: bool = False) -> dict[str, Any]:
        project_id = _validate_project_id(project_id)
        with _MEMORY_LOCK:
            state, binding = self._load_state(project_id)
            items = [dict(x) for x in state["items"] if include_deleted or x.get("lifecycle_state") != "DELETED"]
            items.sort(key=lambda x: x["memory_id"])
            return {
                "schema": "UR_WEB_PROJECT_MEMORY_LIST_R001",
                "project_id": project_id,
                "state_binding": binding if state["state_revision"] > 0 else None,
                "state_revision": state["state_revision"],
                "memories": items,
            }

    def current_context(self, *, project_id: str) -> dict[str, Any]:
        project_id = _validate_project_id(project_id)
        with _MEMORY_LOCK:
            state, binding = self._load_state(project_id)
            active = [x for x in state["items"] if x.get("lifecycle_state") == "ACTIVE"]
            active.sort(key=lambda x: x["memory_id"])
            if len(active) > MAX_ACTIVE_MEMORY_ITEMS:
                raise ProjectMemoryError("ACTIVE_MEMORY_LIMIT", "too many ACTIVE memories for first-slice Job input", status_code=409)
            for item in active:
                _validate_content(item["content"])

            state_guard = {
                "schema": MEMORY_STATE_GUARD_SCHEMA,
                "project_id": project_id,
                "state_artifact_id": binding["artifact_id"],
                "state_artifact_revision": binding["revision"],
                "state_artifact_sha256": binding["sha256"],
                "state_snapshot_sha256": _sha(state),
                "active_memory_count": len(active),
            }
            projection = {
                "schema": "UR_WEB_PROJECT_MEMORY_CONTEXT_PROJECTION_R002",
                "project_id": project_id,
                "active_memory_count": len(active),
                "project_memory_state_guard": state_guard,
                "project_memory_state_guard_sha256": _sha(state_guard),
                "state_binding": dict(binding),
            }
            if not active:
                return {
                    **projection,
                    "project_memory_context": None,
                    "project_memory_context_sha256": None,
                }

            context = {
                "schema": MEMORY_CONTEXT_SCHEMA,
                "authority_class": MEMORY_CONTEXT_AUTHORITY,
                "project_id": project_id,
                "state_binding": dict(binding),
                "active_memory_count": len(active),
                "items": [
                    {
                        "memory_id": item["memory_id"],
                        "memory_revision": item["memory_revision"],
                        "memory_item_sha256": item["memory_item_sha256"],
                        "content": item["content"],
                        "content_sha256": item["content_sha256"],
                        "provenance": dict(item["provenance"]),
                    }
                    for item in active
                ],
            }
            return {
                **projection,
                "project_memory_context": context,
                "project_memory_context_sha256": _sha(context),
            }

    def validate_state_guard_current(
        self,
        *,
        project_id: str,
        project_memory_state_guard: dict[str, Any] | None,
        project_memory_state_guard_sha256: str | None,
    ) -> dict[str, Any]:
        project_id = _validate_project_id(project_id)
        if (
            not isinstance(project_memory_state_guard, dict)
            or not isinstance(project_memory_state_guard_sha256, str)
        ):
            raise ProjectMemoryError(
                "PROJECT_MEMORY_STATE_GUARD_REQUIRED",
                "exact Project Memory state guard and SHA are required for Memory-opted Job input",
                status_code=409,
            )
        if (
            project_memory_state_guard.get("schema") != MEMORY_STATE_GUARD_SCHEMA
            or project_memory_state_guard.get("project_id") != project_id
        ):
            raise ProjectMemoryError(
                "PROJECT_MEMORY_STATE_GUARD_INVALID",
                "Project Memory state guard scope/schema mismatch",
                status_code=409,
            )
        if _sha(project_memory_state_guard) != project_memory_state_guard_sha256:
            raise ProjectMemoryError(
                "PROJECT_MEMORY_STATE_GUARD_SHA_MISMATCH",
                "Project Memory state guard semantic SHA mismatch",
                status_code=409,
            )
        current = self.current_context(project_id=project_id)
        if (
            current["project_memory_state_guard_sha256"] != project_memory_state_guard_sha256
            or current["project_memory_state_guard"] != project_memory_state_guard
        ):
            raise ProjectMemoryError(
                "PROJECT_MEMORY_STATE_GUARD_STALE",
                "Project Memory state changed after Job input freeze",
                status_code=409,
            )
        return project_memory_state_guard

    def validate_context_current(
        self,
        *,
        project_id: str,
        project_memory_context: dict[str, Any] | None,
        project_memory_context_sha256: str | None,
    ) -> dict[str, Any] | None:
        project_id = _validate_project_id(project_id)
        if project_memory_context is None and project_memory_context_sha256 is None:
            return None
        if not isinstance(project_memory_context, dict) or not isinstance(project_memory_context_sha256, str):
            raise ProjectMemoryError("PROJECT_MEMORY_CONTEXT_INVALID", "memory context and SHA must be supplied together", status_code=409)
        if project_memory_context.get("schema") != MEMORY_CONTEXT_SCHEMA or project_memory_context.get("project_id") != project_id:
            raise ProjectMemoryError("PROJECT_MEMORY_CONTEXT_INVALID", "memory context scope/schema mismatch", status_code=409)
        if _sha(project_memory_context) != project_memory_context_sha256:
            raise ProjectMemoryError("PROJECT_MEMORY_CONTEXT_SHA_MISMATCH", "memory context semantic SHA mismatch", status_code=409)
        current = self.current_context(project_id=project_id)
        if (
            current["project_memory_context_sha256"] != project_memory_context_sha256
            or current["project_memory_context"] != project_memory_context
        ):
            raise ProjectMemoryError("PROJECT_MEMORY_CONTEXT_STALE", "project memory changed after Job input freeze", status_code=409)
        return project_memory_context


def build_plain_memory_user_payload(*, project_memory_context: dict[str, Any], user_request: str) -> str:
    if not isinstance(user_request, str) or not user_request:
        raise ProjectMemoryError("PROJECT_MEMORY_USER_REQUEST_INVALID", "user request must be non-empty")
    items = project_memory_context.get("items") if isinstance(project_memory_context, dict) else None
    if not isinstance(items, list) or not items:
        raise ProjectMemoryError("PROJECT_MEMORY_CONTEXT_INVALID", "memory context items unavailable")
    return _canonical_bytes({
        "project_memory": [
            {
                "memory_id": item["memory_id"],
                "content": item["content"],
            }
            for item in items
        ],
        "memory_semantics": "user-managed project-scoped background context; does not override the current user request",
        "user_request": user_request,
    }).decode("utf-8")
