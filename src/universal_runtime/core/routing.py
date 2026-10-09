"""Deterministic, Runtime-owned routing decisions for validated gate results.

This module intentionally contains no workflow execution or persistence.  It
only validates the routing-critical binding and maps a gate verdict to a
closed internal action.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
import re
from typing import Any, Mapping


class RoutingError(ValueError):
    """Raised when a review cannot be authorized by Runtime policy."""


class RouteAction(StrEnum):
    GATE_CANDIDATE = "GATE_CANDIDATE"
    RETURN_TO_P08 = "RETURN_TO_P08"
    STOP_BLOCKER = "STOP_BLOCKER"


@dataclass(frozen=True)
class ConsumedReview:
    """In-memory record of the one review consumed for a binding."""

    identity: str
    payload_digest: str
    decision: "RouteDecision"


@dataclass
class RoutingContext:
    """Current immutable artifact/revision binding plus optional retry state."""

    artifact_id: str
    revision: int | str
    current_sha256: str
    consumed_review: ConsumedReview | None = None


@dataclass(frozen=True)
class RouteDecision:
    """Runtime-authorized route; fields explicitly deny downstream authority."""

    action: RouteAction
    artifact_id: str
    revision: int | str
    reviewed_sha256: str
    idempotent_replay: bool = False
    advance_permitted: bool = True
    author_approval_granted: bool = False
    p09_authorized: bool = False
    formal_write_authorized: bool = False
    publish_authorized: bool = False
    fallback_progression_allowed: bool = False
    direct_p08b_retry_allowed: bool = False
    p08a_repersist_required: bool = False
    new_revision_required: bool = False
    new_sha_binding_required: bool = False
    fresh_p08b_required: bool = False
    stop: bool = False
    blocker_details: Any = None
    return_interface_metadata: str | None = None
    return_action: str | None = None


_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_REVISE_RETURN_ACTION = "P08 / ACTION_ID = P08_MAP_CURRENT_PARENT"
_BLOCKER_RETURN_ACTION = "STOP / REQUIRED_RETURN_INTERFACE"


def _as_mapping(result: Any) -> Mapping[str, Any]:
    if isinstance(result, Mapping):
        return result
    if hasattr(result, "model_dump"):
        value = result.model_dump()
        if isinstance(value, Mapping):
            return value
    if hasattr(result, "dict"):
        value = result.dict()
        if isinstance(value, Mapping):
            return value
    raise RoutingError("malformed review result")


def _payload_digest(data: Mapping[str, Any]) -> str:
    try:
        encoded = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise RoutingError("malformed review result") from exc
    return hashlib.sha256(encoded).hexdigest()


def _validate_context(context: RoutingContext) -> None:
    if not isinstance(context.artifact_id, str) or not context.artifact_id.strip():
        raise RoutingError("artifact_id must be non-empty")
    if isinstance(context.revision, bool):
        raise RoutingError("revision is invalid")
    if isinstance(context.revision, int):
        if context.revision < 1:
            raise RoutingError("revision is invalid")
    elif not isinstance(context.revision, str) or not context.revision.strip():
        raise RoutingError("revision is invalid")
    if not isinstance(context.current_sha256, str) or not _SHA_RE.fullmatch(context.current_sha256):
        raise RoutingError("current_sha256 must be lowercase 64-hex")


def route_review(result: Any, context: RoutingContext) -> RouteDecision:
    """Validate a gate result and return its deterministic Runtime route.

    The context's in-memory consumed binding provides idempotent replay without
    introducing a persistence layer.  The first accepted result is recorded;
    an exact retry returns the same decision, while a conflicting retry fails
    closed.
    """

    _validate_context(context)
    data = _as_mapping(result)
    verdict = data.get("verdict")
    reviewed_sha = data.get("reviewed_sha256")
    if not isinstance(verdict, str) or verdict not in {"PASS", "REVISE", "HISTORY_BOUNDARY_BLOCKER"}:
        raise RoutingError("unknown or malformed verdict")
    if not isinstance(reviewed_sha, str) or not _SHA_RE.fullmatch(reviewed_sha):
        raise RoutingError("reviewed_sha256 must be lowercase 64-hex")
    if reviewed_sha != context.current_sha256:
        raise RoutingError("reviewed SHA does not match current artifact")
    if not isinstance(data.get("summary"), str) or not data["summary"]:
        raise RoutingError("summary is required")
    if not isinstance(data.get("revision_targets"), list):
        raise RoutingError("revision_targets is required")
    if "blocker_details" not in data:
        raise RoutingError("blocker_details is malformed")
    if not isinstance(data.get("return_action"), str) or not data["return_action"]:
        raise RoutingError("return_action is required")

    if verdict == "REVISE":
        targets = data.get("revision_targets")
        if not isinstance(targets, list) or not targets or any(not isinstance(item, str) or not item for item in targets):
            raise RoutingError("REVISE requires revision_targets")
        if data.get("blocker_details") is not None:
            raise RoutingError("REVISE blocker_details is malformed")
        if data.get("return_action") != _REVISE_RETURN_ACTION:
            raise RoutingError("REVISE return_action is incompatible")
    elif verdict == "PASS":
        if data.get("revision_targets"):
            raise RoutingError("PASS cannot carry revision_targets")
        if data.get("blocker_details") is not None:
            raise RoutingError("PASS blocker_details is malformed")
    elif verdict == "HISTORY_BOUNDARY_BLOCKER":
        if data.get("revision_targets"):
            raise RoutingError("blocker cannot carry revision_targets")
        details = data.get("blocker_details")
        if (
            not isinstance(details, Mapping)
            or set(details) != {"missing_input", "reason", "required_return_interface"}
            or any(not isinstance(details[key], str) or not details[key] for key in details)
        ):
            raise RoutingError("blocker_details is required")
        if data.get("return_action") != _BLOCKER_RETURN_ACTION:
            raise RoutingError("blocker return_action is incompatible")

    digest = _payload_digest(data)
    identity = f"{context.artifact_id}|{context.revision}|{context.current_sha256}"
    consumed = context.consumed_review
    if consumed is not None:
        if consumed.identity != identity:
            raise RoutingError("review binding is not current")
        if consumed.payload_digest == digest:
            prior = consumed.decision
            return RouteDecision(**{**prior.__dict__, "idempotent_replay": True, "advance_permitted": False})
        raise RoutingError("conflicting duplicate review")

    if verdict == "PASS":
        decision = RouteDecision(
            action=RouteAction.GATE_CANDIDATE,
            artifact_id=context.artifact_id,
            revision=context.revision,
            reviewed_sha256=reviewed_sha,
        )
    elif verdict == "REVISE":
        decision = RouteDecision(
            action=RouteAction.RETURN_TO_P08,
            artifact_id=context.artifact_id,
            revision=context.revision,
            reviewed_sha256=reviewed_sha,
            p08a_repersist_required=True,
            new_revision_required=True,
            new_sha_binding_required=True,
            fresh_p08b_required=True,
        )
    else:
        decision = RouteDecision(
            action=RouteAction.STOP_BLOCKER,
            artifact_id=context.artifact_id,
            revision=context.revision,
            reviewed_sha256=reviewed_sha,
            stop=True,
            blocker_details=data["blocker_details"],
            return_interface_metadata=data["blocker_details"]["required_return_interface"],
            return_action=data.get("return_action"),
        )

    context.consumed_review = ConsumedReview(identity, digest, decision)
    return decision


__all__ = ["ConsumedReview", "RouteAction", "RouteDecision", "RoutingContext", "RoutingError", "route_review"]
