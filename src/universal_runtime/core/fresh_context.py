"""Runtime-owned authorization for an isolated P08B fresh context.

This module only constructs and authorizes a context plan.  It deliberately
does not create a model session, inspect conversation contents, or perform any
workflow transition.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Iterable

from .enums import PersistenceClass
from .file_resolver import FileResolver, FileResolutionError
from .load_plan import LoadInput, LoadPlan, ParseMode


class ProvenanceClass(StrEnum):
    FORMAL_AUTHORITY = "FORMAL_AUTHORITY"
    PERSISTED_REVIEW_TARGET = "PERSISTED_REVIEW_TARGET"
    PERSISTED_SOURCE = "PERSISTED_SOURCE"
    AUDIT_ONLY = "AUDIT_ONLY"
    PRIVATE_REASONING = "PRIVATE_REASONING"
    SELF_EVALUATION = "SELF_EVALUATION"
    DEBUG_TRANSCRIPT = "DEBUG_TRANSCRIPT"
    UNPERSISTED_DRAFT = "UNPERSISTED_DRAFT"
    SECRET = "SECRET"
    UNTRUSTED_DISCOVERY = "UNTRUSTED_DISCOVERY"
    SESSION_HISTORY = "SESSION_HISTORY"


class FreshContextError(ValueError):
    """Raised when a proposed fresh context cannot be proven safe."""


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED_PROVENANCE = frozenset(
    {
        ProvenanceClass.FORMAL_AUTHORITY,
        ProvenanceClass.PERSISTED_REVIEW_TARGET,
        ProvenanceClass.PERSISTED_SOURCE,
    }
)
_PERSISTED = frozenset(
    {PersistenceClass.AUTHORITATIVE, PersistenceClass.AUDIT, PersistenceClass.WORKING}
)


@dataclass(frozen=True)
class FreshContextInput:
    """One explicitly authorized, file-backed input descriptor."""

    reference: str | Path
    role: str
    provenance: ProvenanceClass | str
    expected_sha256: str
    parse_mode: str = ParseMode.BYTES
    persistence_class: PersistenceClass = PersistenceClass.AUTHORITATIVE
    required: bool = True
    byte_budget: int | None = None
    approved_permission: bool = True
    explicitly_authorized: bool = True
    artifact_id: str | None = None
    revision: int | None = None
    # Compatibility aliases used by callers that model permissions explicitly.
    permission: bool | None = None
    secret: bool = False


@dataclass(frozen=True)
class FreshContextRequest:
    """Authorization request; flags describe inheritance evidence only."""

    inputs: tuple[FreshContextInput, ...] = field(default_factory=tuple)
    project_root: str | Path = "."
    allowed_roots: tuple[str | Path, ...] = field(default_factory=tuple)
    execution_id: str | None = None
    execution_id_runtime_owned: bool = True
    plan_id: str | None = None
    execution_budget: int | None = None
    load_budget: int | None = None
    network_allowed: bool = False
    model_requested_network: bool = False
    previous_p08b_result: object | None = None
    inherits_p08_session: bool = False
    inherits_previous_p08b_session: bool = False
    inherits_controller_chat: bool = False
    inherits_debug_chat: bool = False
    inherits_checkpoint_conversation: bool = False
    inherits_model_thread_history: bool = False
    # General aliases make the evidence unambiguous for integrations.
    inherits_session: bool = False
    inherits_thread: bool = False
    inherits_conversation: bool = False


@dataclass(frozen=True)
class FreshContextPlan:
    execution_id: str
    context_id: str
    load_plan: LoadPlan
    network_allowed: bool = False
    inherits_p08_session: bool = False
    inherits_previous_p08b_session: bool = False
    inherits_controller_chat: bool = False
    inherits_debug_chat: bool = False
    inherits_checkpoint_conversation: bool = False
    inherits_model_thread_history: bool = False
    bundle_fingerprint: str = ""

    @property
    def inputs(self) -> tuple[LoadInput, ...]:
        return self.load_plan.required_inputs


@dataclass(frozen=True)
class FreshContextAuthorization:
    authorized: bool
    plan: FreshContextPlan | None = None
    reasons: tuple[str, ...] = field(default_factory=tuple)

    @property
    def fresh_context_authorized(self) -> bool:
        return self.authorized

    @property
    def fingerprint(self) -> str | None:
        return self.plan.bundle_fingerprint if self.plan else None


def _as_provenance(value: ProvenanceClass | str) -> ProvenanceClass:
    try:
        return value if isinstance(value, ProvenanceClass) else ProvenanceClass(value)
    except (TypeError, ValueError) as exc:
        raise FreshContextError("Unknown provenance is not authorized.") from exc


def _secret_path(path: Path) -> bool:
    for component in path.parts:
        name = component.lower()
        if name == ".env" or name.startswith(".env."):
            return True
        if any(token in name for token in ("secret", "credential", "api_key", "apikey", "token")):
            return True
    return False


def _fingerprint(*, execution_id: str, context_id: str, inputs: Iterable[dict], network_allowed: bool) -> str:
    payload = {
        "execution_id": execution_id,
        "context_id": context_id,
        "inputs": list(inputs),
        "network_allowed": network_allowed,
    }
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def authorize_fresh_context(request: FreshContextRequest) -> FreshContextAuthorization:
    """Authorize a deterministic, persisted-only P08B context or fail closed."""
    reasons: list[str] = []
    inheritance = (
        request.inherits_p08_session,
        request.inherits_previous_p08b_session,
        request.inherits_controller_chat,
        request.inherits_debug_chat,
        request.inherits_checkpoint_conversation,
        request.inherits_model_thread_history,
        request.inherits_session,
        request.inherits_thread,
        request.inherits_conversation,
    )
    if any(inheritance):
        reasons.append("Inherited session, conversation, thread, checkpoint, or debug history is forbidden.")
    if request.previous_p08b_result is not None:
        reasons.append("Previous P08B result is audit-only and cannot be context.")
    if request.network_allowed or request.model_requested_network:
        reasons.append("Network access is denied by the P08B fresh-context policy.")
    execution_id = request.execution_id or uuid.uuid4().hex
    if not request.execution_id_runtime_owned:
        reasons.append("Execution identity must be Runtime-owned.")
    context_id = hashlib.sha256(f"p08b-fresh-context:{execution_id}".encode()).hexdigest()
    if not execution_id:
        reasons.append("A runtime execution identity is required.")
    project_root = Path(request.project_root).resolve()
    roots = tuple(Path(root).resolve() for root in (request.allowed_roots or (project_root,)))
    resolver = FileResolver(roots)
    load_inputs: list[LoadInput] = []
    fingerprint_inputs: list[dict] = []
    for item in request.inputs:
        try:
            provenance = _as_provenance(item.provenance)
        except FreshContextError as exc:
            reasons.append(str(exc)); continue
        if provenance not in _ALLOWED_PROVENANCE:
            reasons.append(f"Provenance {provenance} is not authorized."); continue
        if item.secret or provenance == ProvenanceClass.SECRET:
            reasons.append("Secret-bearing input is forbidden."); continue
        if not item.explicitly_authorized:
            reasons.append("Input was not explicitly authorized by the execution-specific plan."); continue
        if item.permission is False or not item.approved_permission:
            reasons.append("Input permission is not approved."); continue
        if item.persistence_class not in _PERSISTED:
            reasons.append("Only persisted input classes may enter fresh context."); continue
        if item.parse_mode not in {ParseMode.BYTES, ParseMode.MARKDOWN, ParseMode.DOCX}:
            reasons.append("Input parse mode is not approved."); continue
        if not isinstance(item.expected_sha256, str) or not _SHA256.fullmatch(item.expected_sha256):
            reasons.append("Expected SHA-256 must be lowercase hexadecimal."); continue
        ref = Path(item.reference)
        if _secret_path(ref):
            reasons.append("Secret-bearing path is forbidden."); continue
        if item.revision is not None and (item.revision < 1 or not item.artifact_id):
            reasons.append("Artifact revision requires an artifact identity."); continue
        if provenance == ProvenanceClass.PERSISTED_REVIEW_TARGET and (
            not item.artifact_id or item.revision is None or item.revision < 1
        ):
            reasons.append("Persisted review target requires artifact identity and revision."); continue
        resolved_ref = ref if ref.is_absolute() else project_root / ref
        try:
            resolved = resolver.resolve(resolved_ref)
            assert resolved is not None
            actual = hashlib.sha256(resolved.path.read_bytes()).hexdigest()
        except (FileResolutionError, FileNotFoundError, OSError) as exc:
            reasons.append(str(exc)); continue
        if actual != item.expected_sha256:
            reasons.append("SHA-256 mismatch."); continue
        load_inputs.append(
            LoadInput(
                reference=str(resolved.path), role=item.role, expected_sha256=item.expected_sha256,
                parse_mode=item.parse_mode, persistence_class=item.persistence_class,
                required=item.required, byte_budget=item.byte_budget,
            )
        )
        fingerprint_inputs.append(
            {
                "reference": str(resolved.path), "role": item.role, "provenance": provenance.value,
                "artifact_id": item.artifact_id, "revision": item.revision,
                "expected_sha256": item.expected_sha256, "parse_mode": item.parse_mode,
                "persistence_class": item.persistence_class.value, "required": item.required,
            }
        )
    if not load_inputs and not reasons:
        reasons.append("At least one authorized input is required.")
    if reasons:
        return FreshContextAuthorization(False, None, tuple(reasons))
    plan = LoadPlan.from_inputs(
        plan_id=request.plan_id or f"p08b-fresh-{execution_id}", project_root=str(project_root),
        allowed_roots=tuple(str(root) for root in roots), required_inputs=load_inputs,
        execution_budget=request.execution_budget, load_budget=request.load_budget,
    )
    fingerprint = _fingerprint(execution_id=execution_id, context_id=context_id, inputs=fingerprint_inputs, network_allowed=False)
    fresh_plan = FreshContextPlan(
        execution_id=execution_id, context_id=context_id, load_plan=plan,
        network_allowed=False, inherits_p08_session=False, inherits_previous_p08b_session=False,
        inherits_controller_chat=False, inherits_debug_chat=False,
        inherits_checkpoint_conversation=False, inherits_model_thread_history=False,
        bundle_fingerprint=fingerprint,
    )
    return FreshContextAuthorization(True, fresh_plan, ())


class FreshContextAuthorizer:
    """Small object-oriented façade for callers that prefer an authorizer."""

    authorize = staticmethod(authorize_fresh_context)


__all__ = [
    "ProvenanceClass", "FreshContextError", "FreshContextInput", "FreshContextRequest",
    "FreshContextPlan", "FreshContextAuthorization", "FreshContextAuthorizer", "authorize_fresh_context",
]
