from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping


class WebConversationGraphError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def validate_event_index(chat: Mapping[str, Any], events_by_id: Mapping[str, Mapping[str, Any]]) -> None:
    chat_id = chat.get("chat_id")
    event_ids = chat.get("event_ids")
    if not isinstance(chat_id, str) or not chat_id:
        raise WebConversationGraphError("INVALID_CHAT_ID", "chat_id is required")
    if not isinstance(event_ids, list) or any(not isinstance(item, str) or not item for item in event_ids):
        raise WebConversationGraphError("INVALID_EVENT_IDS", "chat.event_ids must be a list of non-empty event ids")
    if len(set(event_ids)) != len(event_ids):
        raise WebConversationGraphError("DUPLICATE_EVENT_ID", "chat.event_ids contains duplicate event ids")
    if set(events_by_id) != set(event_ids):
        raise WebConversationGraphError("EVENT_INDEX_MISMATCH", "event index must exactly cover chat.event_ids")

    for event_id in event_ids:
        event = events_by_id[event_id]
        if event.get("event_id") != event_id:
            raise WebConversationGraphError("EVENT_ID_MISMATCH", "event record id differs from chat membership")
        if event.get("chat_id") != chat_id:
            raise WebConversationGraphError("CROSS_CHAT_EVENT", "event belongs to another chat")
        parent = event.get("parent_event_id")
        if parent is not None and parent not in events_by_id:
            raise WebConversationGraphError("ORPHAN_PARENT", "event parent is missing from the same chat")


def children_index(chat: Mapping[str, Any], events_by_id: Mapping[str, Mapping[str, Any]]) -> dict[str, list[str]]:
    validate_event_index(chat, events_by_id)
    result = {event_id: [] for event_id in chat["event_ids"]}
    for event_id in chat["event_ids"]:
        parent = events_by_id[event_id].get("parent_event_id")
        if parent is not None:
            result[parent].append(event_id)
    return result


def resolve_active_ancestry_ids(chat: Mapping[str, Any], events_by_id: Mapping[str, Mapping[str, Any]]) -> list[str]:
    validate_event_index(chat, events_by_id)
    head = chat.get("head_event_id")
    if head is None:
        if chat.get("event_ids"):
            raise WebConversationGraphError("HEAD_MISSING", "non-empty chat must have an active head")
        return []
    if head not in events_by_id:
        raise WebConversationGraphError("HEAD_NOT_MEMBER", "chat head must be one of chat.event_ids")

    reverse_path: list[str] = []
    seen: set[str] = set()
    current: str | None = head
    while current is not None:
        if current in seen:
            raise WebConversationGraphError("LINEAGE_CYCLE", "conversation lineage contains a cycle")
        seen.add(current)
        reverse_path.append(current)
        parent = events_by_id[current].get("parent_event_id")
        if parent is not None and parent not in events_by_id:
            raise WebConversationGraphError("ORPHAN_PARENT", "active lineage parent is missing")
        current = parent
    reverse_path.reverse()
    return reverse_path


def validate_leaf_head_target(
    chat: Mapping[str, Any],
    events_by_id: Mapping[str, Mapping[str, Any]],
    target_event_id: str,
) -> None:
    child_map = children_index(chat, events_by_id)
    if target_event_id not in child_map:
        raise WebConversationGraphError("TARGET_HEAD_NOT_MEMBER", "target head is not a persisted event in this chat")
    if child_map[target_event_id]:
        raise WebConversationGraphError("TARGET_HEAD_NOT_LEAF", "target head must be a leaf event")


def leaf_event_ids(
    chat: Mapping[str, Any],
    events_by_id: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    """Return persisted leaf event ids in stable event-sequence order."""
    child_map = children_index(chat, events_by_id)
    leaves = [event_id for event_id in chat["event_ids"] if not child_map[event_id]]
    leaves.sort(key=lambda event_id: int(events_by_id[event_id].get("event_sequence_1_based") or 0))
    head = chat.get("head_event_id")
    if head is not None:
        validate_leaf_head_target(chat, events_by_id, head)
        if head not in leaves:
            raise WebConversationGraphError("HEAD_NOT_LEAF", "active head must be one of the persisted leaf events")
    return leaves


def active_ancestry_projection(
    *,
    chat: Mapping[str, Any],
    events_by_id: Mapping[str, Mapping[str, Any]],
    bindings_by_id: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    ids = resolve_active_ancestry_ids(chat, events_by_id)
    ordered_events = []
    for event_id in ids:
        event = events_by_id[event_id]
        binding = bindings_by_id.get(event_id)
        if not isinstance(binding, Mapping):
            raise WebConversationGraphError("EVENT_BINDING_MISSING", "exact event binding is required")
        ordered_events.append(
            {
                "event_id": event_id,
                "event_type": event.get("event_type"),
                "actor_class": event.get("actor_class"),
                "parent_event_id": event.get("parent_event_id"),
                "content_sha256": event.get("content_sha256"),
                "artifact_id": binding.get("artifact_id"),
                "artifact_revision": binding.get("revision"),
                "artifact_sha256": binding.get("sha256"),
            }
        )
    identity = {
        "schema": "WEB_CHAT_ACTIVE_ANCESTRY_V1",
        "chat_id": chat.get("chat_id"),
        "chat_revision": chat.get("chat_revision"),
        "head_event_id": chat.get("head_event_id"),
        "ordered_events": ordered_events,
    }
    identity["active_ancestry_sha256"] = _sha256_bytes(_canonical_json_bytes(identity))
    return identity


def build_active_context_snapshot(
    *,
    active_ancestry: Mapping[str, Any],
    events: list[Mapping[str, Any]],
) -> dict[str, Any]:
    if active_ancestry.get("schema") != "WEB_CHAT_ACTIVE_ANCESTRY_V1":
        raise WebConversationGraphError("ACTIVE_ANCESTRY_SCHEMA", "active ancestry schema is invalid")
    ordered = active_ancestry.get("ordered_events")
    if not isinstance(ordered, list) or not isinstance(events, list) or len(ordered) != len(events):
        raise WebConversationGraphError("ACTIVE_CONTEXT_LENGTH", "active ancestry events and content records must align")
    messages: list[dict[str, Any]] = []
    for descriptor, event in zip(ordered, events):
        if not isinstance(descriptor, Mapping) or not isinstance(event, Mapping):
            raise WebConversationGraphError("ACTIVE_CONTEXT_EVENT", "active context event record is invalid")
        event_id = descriptor.get("event_id")
        if event.get("event_id") != event_id:
            raise WebConversationGraphError("ACTIVE_CONTEXT_EVENT_ID", "event content differs from exact ancestry descriptor")
        event_type = descriptor.get("event_type")
        actor_class = descriptor.get("actor_class")
        if event_type == "USER_MESSAGE" and actor_class == "USER":
            role = "user"
        elif event_type == "ASSISTANT_MESSAGE" and actor_class == "ASSISTANT":
            role = "assistant"
        else:
            raise WebConversationGraphError("UNSUPPORTED_CONTEXT_EVENT", "only USER_MESSAGE and ASSISTANT_MESSAGE are supported")
        content = event.get("content")
        if not isinstance(content, str) or content == "":
            raise WebConversationGraphError("ACTIVE_CONTEXT_CONTENT", "active context message content must be non-empty text")
        content_sha = _sha256_bytes(content.encode("utf-8"))
        if content_sha != descriptor.get("content_sha256") or content_sha != event.get("content_sha256"):
            raise WebConversationGraphError("ACTIVE_CONTEXT_CONTENT_SHA", "active context message content SHA differs")
        messages.append(
            {
                "event_id": event_id,
                "role": role,
                "content": content,
                "content_sha256": content_sha,
                "parent_event_id": descriptor.get("parent_event_id"),
                "artifact_id": descriptor.get("artifact_id"),
                "artifact_revision": descriptor.get("artifact_revision"),
                "artifact_sha256": descriptor.get("artifact_sha256"),
            }
        )
    if messages:
        if messages[-1]["event_id"] != active_ancestry.get("head_event_id"):
            raise WebConversationGraphError("ACTIVE_CONTEXT_HEAD", "active context final event must be the active head")
        previous = None
        for item in messages:
            if item.get("parent_event_id") != previous:
                raise WebConversationGraphError("ACTIVE_CONTEXT_LINEAGE", "active context messages must form one contiguous ancestry path")
            previous = item["event_id"]
    snapshot = {
        "schema": "WEB_CHAT_ACTIVE_CONTEXT_SNAPSHOT_V1",
        "chat_id": active_ancestry.get("chat_id"),
        "chat_revision": active_ancestry.get("chat_revision"),
        "head_event_id": active_ancestry.get("head_event_id"),
        "active_ancestry_sha256": active_ancestry.get("active_ancestry_sha256"),
        "ordered_messages": messages,
    }
    snapshot["active_context_snapshot_sha256"] = _sha256_bytes(_canonical_json_bytes(snapshot))
    return snapshot


def validate_active_context_snapshot(snapshot: Mapping[str, Any]) -> str:
    if snapshot.get("schema") != "WEB_CHAT_ACTIVE_CONTEXT_SNAPSHOT_V1":
        raise WebConversationGraphError("ACTIVE_CONTEXT_SCHEMA", "active context snapshot schema is invalid")
    claimed = snapshot.get("active_context_snapshot_sha256")
    if not isinstance(claimed, str) or len(claimed) != 64:
        raise WebConversationGraphError("ACTIVE_CONTEXT_SHA", "active context snapshot SHA is invalid")
    body = dict(snapshot)
    body.pop("active_context_snapshot_sha256", None)
    actual = _sha256_bytes(_canonical_json_bytes(body))
    if actual != claimed:
        raise WebConversationGraphError("ACTIVE_CONTEXT_SHA", "active context snapshot SHA differs")
    messages = snapshot.get("ordered_messages")
    if not isinstance(messages, list) or not messages:
        raise WebConversationGraphError("ACTIVE_CONTEXT_EMPTY", "active context snapshot requires at least one message")
    if messages[-1].get("event_id") != snapshot.get("head_event_id"):
        raise WebConversationGraphError("ACTIVE_CONTEXT_HEAD", "active context final message is not the head")
    previous = None
    for item in messages:
        if not isinstance(item, Mapping):
            raise WebConversationGraphError("ACTIVE_CONTEXT_EVENT", "active context message record invalid")
        if item.get("role") not in {"user", "assistant"}:
            raise WebConversationGraphError("ACTIVE_CONTEXT_ROLE", "active context role is unsupported")
        content = item.get("content")
        if not isinstance(content, str) or not content:
            raise WebConversationGraphError("ACTIVE_CONTEXT_CONTENT", "active context content required")
        if _sha256_bytes(content.encode("utf-8")) != item.get("content_sha256"):
            raise WebConversationGraphError("ACTIVE_CONTEXT_CONTENT_SHA", "active context content SHA differs")
        if item.get("parent_event_id") != previous:
            raise WebConversationGraphError("ACTIVE_CONTEXT_LINEAGE", "active context message lineage is not contiguous")
        previous = item.get("event_id")
    return claimed


def build_provider_messages_from_active_context(
    *,
    system_prompt: str,
    active_context_snapshot: Mapping[str, Any],
    current_source_text: str,
    current_user_request: str,
) -> list[dict[str, str]]:
    validate_active_context_snapshot(active_context_snapshot)
    messages = active_context_snapshot["ordered_messages"]
    if messages[-1].get("role") != "user":
        raise WebConversationGraphError("ACTIVE_CONTEXT_CURRENT_ROLE", "active context head must be the initiating USER message")
    result: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
    for item in messages[:-1]:
        result.append({"role": item["role"], "content": item["content"]})
    result.append(
        {
            "role": "user",
            "content": json.dumps(
                {"source_text": current_source_text, "user_request": current_user_request},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        }
    )
    return result


def validate_current_context_guard(
    *,
    active_context_snapshot: Mapping[str, Any],
    guard: Mapping[str, Any],
) -> None:
    snapshot_sha = validate_active_context_snapshot(active_context_snapshot)
    if not isinstance(guard, Mapping):
        raise WebConversationGraphError("ACTIVE_CONTEXT_GUARD_REQUIRED", "current Web context guard required")
    if (
        guard.get("chat_revision") != active_context_snapshot.get("chat_revision")
        or guard.get("head_event_id") != active_context_snapshot.get("head_event_id")
        or guard.get("active_context_snapshot_sha256") != snapshot_sha
    ):
        raise WebConversationGraphError("ACTIVE_CONTEXT_GUARD_STALE", "current Web context differs from frozen snapshot")
