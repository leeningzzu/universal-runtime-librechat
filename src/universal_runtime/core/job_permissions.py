from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .job_pins import JobPackPin
from .load_plan import LoadPlan
from .permissions import PermissionPolicy


class JobPermissionError(ValueError):
    """Raised when a job-scoped filesystem permission check fails closed."""


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _digest(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _inside(path: Path, roots: tuple[Path, ...]) -> bool:
    return any(path == root or root in path.parents for root in roots)


def _canonical_roots(values: Iterable[Path | str], *, require_absolute: bool = False, base: Path | None = None) -> tuple[Path, ...]:
    result: set[Path] = set()
    for value in values:
        raw = Path(value)
        if not raw.is_absolute():
            if require_absolute or base is None:
                raise JobPermissionError("Permission roots must be absolute paths.")
            raw = base / raw
        result.add(raw.resolve())
    return tuple(sorted(result, key=lambda item: str(item)))


def _canonical_reference(reference: str, project_root: Path) -> Path:
    raw = Path(reference)
    if ".." in raw.parts:
        raise JobPermissionError("Path traversal is not allowed.")
    return (raw if raw.is_absolute() else project_root / raw).resolve()


def _load_plan_fingerprint(plan: LoadPlan) -> str:
    project_root = Path(plan.project_root).resolve()
    allowed_roots = _canonical_roots(plan.allowed_roots, base=project_root)
    inputs = [
        {
            "reference": item.reference,
            "role": item.role,
            "expected_sha256": item.expected_sha256,
            "parse_mode": item.parse_mode,
            "persistence_class": str(item.persistence_class),
            "required": item.required,
            "byte_budget": item.byte_budget,
        }
        for item in plan.required_inputs
    ]
    return _digest(
        {
            "plan_id": plan.plan_id,
            "project_root": str(project_root),
            "allowed_roots": [str(root) for root in allowed_roots],
            "required_inputs": inputs,
            "execution_budget": plan.execution_budget,
            "load_budget": plan.load_budget,
        }
    )


@dataclass(frozen=True)
class AuthorizedJobLoadPlan:
    job_id: str
    pack_id: str
    pack_version: str
    pack_manifest_sha256: str
    permission_plan_sha256: str
    load_plan_sha256: str
    load_plan: LoadPlan


@dataclass(frozen=True)
class JobFilesystemPermissionPlan:
    job_id: str
    pack_id: str
    pack_version: str
    pack_manifest_sha256: str
    allowed_read_roots: tuple[str, ...]

    @classmethod
    def from_job_pin(cls, pin: JobPackPin, allowed_read_roots: Iterable[Path | str]) -> "JobFilesystemPermissionPlan":
        roots = _canonical_roots(allowed_read_roots, require_absolute=True)
        return cls(
            job_id=pin.job_id,
            pack_id=pin.pack_id,
            pack_version=pin.pack_version,
            pack_manifest_sha256=pin.pack_manifest_sha256,
            allowed_read_roots=tuple(str(root) for root in roots),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "pack_id": self.pack_id,
            "pack_version": self.pack_version,
            "pack_manifest_sha256": self.pack_manifest_sha256,
            "allowed_read_roots": list(self.allowed_read_roots),
        }

    def fingerprint(self) -> str:
        return _digest(self.to_dict())

    def assert_matches_pin(self, pin: JobPackPin) -> None:
        expected = (self.job_id, self.pack_id, self.pack_version, self.pack_manifest_sha256)
        actual = (pin.job_id, pin.pack_id, pin.pack_version, pin.pack_manifest_sha256)
        if expected != actual:
            raise JobPermissionError("Permission plan does not match the exact JobPackPin.")

    def _policy(self) -> PermissionPolicy:
        return PermissionPolicy(allowed_read_roots=[Path(root) for root in self.allowed_read_roots], allowed_write_roots=[])

    def require_read(self, path: Path | str) -> None:
        self._policy().require_read(Path(path))

    def authorize_load_plan(self, pin: JobPackPin, plan: LoadPlan) -> AuthorizedJobLoadPlan:
        self.assert_matches_pin(pin)
        try:
            plan.validate()
        except ValueError as exc:
            raise JobPermissionError(str(exc)) from exc

        project_root = Path(plan.project_root).resolve()
        try:
            declared_roots = _canonical_roots(plan.allowed_roots, base=project_root)
        except JobPermissionError:
            raise
        job_roots = tuple(Path(root) for root in self.allowed_read_roots)
        if any(not _inside(root, job_roots) for root in declared_roots):
            raise JobPermissionError("LoadPlan allowed roots exceed the Job filesystem grant.")

        for item in plan.required_inputs:
            if not item.reference and not item.required:
                continue
            if not isinstance(item.expected_sha256, str) or not _SHA256_RE.fullmatch(item.expected_sha256):
                raise JobPermissionError("Concrete authorized inputs require a lowercase 64-hex expected_sha256.")
            try:
                resolved = _canonical_reference(item.reference, project_root)
            except (OSError, RuntimeError) as exc:
                raise JobPermissionError(str(exc)) from exc
            if not _inside(resolved, job_roots) or not _inside(resolved, declared_roots):
                raise JobPermissionError("Declared input is outside the Job grant or LoadPlan roots.")

        return AuthorizedJobLoadPlan(
            job_id=self.job_id,
            pack_id=self.pack_id,
            pack_version=self.pack_version,
            pack_manifest_sha256=self.pack_manifest_sha256,
            permission_plan_sha256=self.fingerprint(),
            load_plan_sha256=_load_plan_fingerprint(plan),
            load_plan=plan,
        )



def _require_nonempty_string(value: str, field: str) -> None:
    if not isinstance(value, str) or not value:
        raise JobPermissionError(f"{field} must be a non-empty string.")


def _require_nonnegative_int(value: int, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise JobPermissionError(f"{field} must be a nonnegative integer.")


def _require_sha256(value: str, field: str) -> None:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise JobPermissionError(f"{field} must be lowercase 64-hex SHA-256.")


def _contains_wildcard(value: str) -> bool:
    return any(token in value for token in ("*", "?", "[", "]"))


def _pin_identity(pin: JobPackPin) -> tuple[str, str, str, str]:
    return (pin.job_id, pin.pack_id, pin.pack_version, pin.pack_manifest_sha256)


@dataclass(frozen=True)
class ExternalActionRequest:
    request_id: str
    action_id: str
    adapter_id: str
    adapter_revision: str
    destination_binding_id: str
    destination_binding_revision: str
    destination_binding_sha256: str
    request_payload_sha256: str

    def __post_init__(self) -> None:
        for field in (
            "request_id",
            "action_id",
            "adapter_id",
            "adapter_revision",
            "destination_binding_id",
            "destination_binding_revision",
        ):
            _require_nonempty_string(getattr(self, field), field)
        if _contains_wildcard(self.action_id):
            raise JobPermissionError("External action_id must not contain wildcard syntax.")
        _require_sha256(self.destination_binding_sha256, "destination_binding_sha256")
        _require_sha256(self.request_payload_sha256, "request_payload_sha256")

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "action_id": self.action_id,
            "adapter_id": self.adapter_id,
            "adapter_revision": self.adapter_revision,
            "destination_binding_id": self.destination_binding_id,
            "destination_binding_revision": self.destination_binding_revision,
            "destination_binding_sha256": self.destination_binding_sha256,
            "request_payload_sha256": self.request_payload_sha256,
        }


@dataclass(frozen=True)
class ExternalActionPlan:
    plan_id: str
    job_id: str
    pack_id: str
    pack_version: str
    pack_manifest_sha256: str
    required_requests: tuple[ExternalActionRequest, ...]
    execution_budget: int

    def __post_init__(self) -> None:
        for field in ("plan_id", "job_id", "pack_id", "pack_version"):
            _require_nonempty_string(getattr(self, field), field)
        _require_sha256(self.pack_manifest_sha256, "pack_manifest_sha256")
        _require_nonnegative_int(self.execution_budget, "execution_budget")
        if not isinstance(self.required_requests, tuple):
            raise JobPermissionError("required_requests must be a finite tuple.")
        if len(self.required_requests) > self.execution_budget:
            raise JobPermissionError("ExternalActionPlan request count exceeds execution_budget.")
        request_ids: set[str] = set()
        for request in self.required_requests:
            if not isinstance(request, ExternalActionRequest):
                raise JobPermissionError("required_requests must contain ExternalActionRequest values.")
            if request.request_id in request_ids:
                raise JobPermissionError("ExternalActionPlan request_id values must be unique.")
            request_ids.add(request.request_id)

    @classmethod
    def from_job_pin(
        cls,
        pin: JobPackPin,
        *,
        plan_id: str,
        required_requests: Iterable[ExternalActionRequest],
        execution_budget: int,
    ) -> "ExternalActionPlan":
        return cls(
            plan_id=plan_id,
            job_id=pin.job_id,
            pack_id=pin.pack_id,
            pack_version=pin.pack_version,
            pack_manifest_sha256=pin.pack_manifest_sha256,
            required_requests=tuple(required_requests),
            execution_budget=execution_budget,
        )

    def assert_matches_pin(self, pin: JobPackPin) -> None:
        if (self.job_id, self.pack_id, self.pack_version, self.pack_manifest_sha256) != _pin_identity(pin):
            raise JobPermissionError("ExternalActionPlan does not match the exact JobPackPin.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "job_id": self.job_id,
            "pack_id": self.pack_id,
            "pack_version": self.pack_version,
            "pack_manifest_sha256": self.pack_manifest_sha256,
            "required_requests": [request.to_dict() for request in self.required_requests],
            "execution_budget": self.execution_budget,
        }

    def fingerprint(self) -> str:
        return _digest(self.to_dict())


@dataclass(frozen=True)
class AuthorizedJobExternalActionPlan:
    job_id: str
    pack_id: str
    pack_version: str
    pack_manifest_sha256: str
    external_action_permission_plan_sha256: str
    external_action_plan_sha256: str
    external_action_plan: ExternalActionPlan

    def __post_init__(self) -> None:
        _require_sha256(self.external_action_permission_plan_sha256, "external_action_permission_plan_sha256")
        _require_sha256(self.external_action_plan_sha256, "external_action_plan_sha256")
        if self.external_action_plan_sha256 != self.external_action_plan.fingerprint():
            raise JobPermissionError("Authorized external-action plan fingerprint does not match the exact plan.")

    def assert_current(
        self,
        pin: JobPackPin,
        permission_plan: "JobExternalActionPermissionPlan",
        action_plan: ExternalActionPlan,
    ) -> None:
        expected = (self.job_id, self.pack_id, self.pack_version, self.pack_manifest_sha256)
        if expected != _pin_identity(pin):
            raise JobPermissionError("Authorized external-action plan does not match the exact JobPackPin.")
        permission_plan.assert_matches_pin(pin)
        action_plan.assert_matches_pin(pin)
        if self.external_action_permission_plan_sha256 != permission_plan.fingerprint():
            raise JobPermissionError("Authorized external-action permission-plan fingerprint is stale or mismatched.")
        if self.external_action_plan_sha256 != action_plan.fingerprint():
            raise JobPermissionError("Authorized external-action plan fingerprint is stale or mismatched.")
        if self.external_action_plan != action_plan:
            raise JobPermissionError("Authorized external-action plan bytes/structure differ from the exact plan.")


@dataclass(frozen=True)
class JobExternalActionPermissionPlan:
    job_id: str
    pack_id: str
    pack_version: str
    pack_manifest_sha256: str
    adapter_id: str
    adapter_revision: str
    destination_binding_id: str
    destination_binding_revision: str
    destination_binding_sha256: str
    allowed_actions: tuple[str, ...]
    max_action_calls: int

    def __post_init__(self) -> None:
        for field in (
            "job_id",
            "pack_id",
            "pack_version",
            "adapter_id",
            "adapter_revision",
            "destination_binding_id",
            "destination_binding_revision",
        ):
            _require_nonempty_string(getattr(self, field), field)
        _require_sha256(self.pack_manifest_sha256, "pack_manifest_sha256")
        _require_sha256(self.destination_binding_sha256, "destination_binding_sha256")
        _require_nonnegative_int(self.max_action_calls, "max_action_calls")
        if not isinstance(self.allowed_actions, tuple):
            raise JobPermissionError("allowed_actions must be a finite tuple.")
        normalized: set[str] = set()
        for action_id in self.allowed_actions:
            _require_nonempty_string(action_id, "allowed action_id")
            if _contains_wildcard(action_id):
                raise JobPermissionError("External action grants must not contain wildcard syntax.")
            normalized.add(action_id)
        object.__setattr__(self, "allowed_actions", tuple(sorted(normalized)))

    @classmethod
    def from_job_pin(
        cls,
        pin: JobPackPin,
        *,
        adapter_id: str,
        adapter_revision: str,
        destination_binding_id: str,
        destination_binding_revision: str,
        destination_binding_sha256: str,
        allowed_actions: Iterable[str],
        max_action_calls: int,
    ) -> "JobExternalActionPermissionPlan":
        return cls(
            job_id=pin.job_id,
            pack_id=pin.pack_id,
            pack_version=pin.pack_version,
            pack_manifest_sha256=pin.pack_manifest_sha256,
            adapter_id=adapter_id,
            adapter_revision=adapter_revision,
            destination_binding_id=destination_binding_id,
            destination_binding_revision=destination_binding_revision,
            destination_binding_sha256=destination_binding_sha256,
            allowed_actions=tuple(allowed_actions),
            max_action_calls=max_action_calls,
        )

    def assert_matches_pin(self, pin: JobPackPin) -> None:
        if (self.job_id, self.pack_id, self.pack_version, self.pack_manifest_sha256) != _pin_identity(pin):
            raise JobPermissionError("External-action permission plan does not match the exact JobPackPin.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "pack_id": self.pack_id,
            "pack_version": self.pack_version,
            "pack_manifest_sha256": self.pack_manifest_sha256,
            "adapter_id": self.adapter_id,
            "adapter_revision": self.adapter_revision,
            "destination_binding_id": self.destination_binding_id,
            "destination_binding_revision": self.destination_binding_revision,
            "destination_binding_sha256": self.destination_binding_sha256,
            "allowed_actions": list(self.allowed_actions),
            "max_action_calls": self.max_action_calls,
        }

    def fingerprint(self) -> str:
        return _digest(self.to_dict())

    def authorize_action_plan(self, pin: JobPackPin, plan: ExternalActionPlan) -> AuthorizedJobExternalActionPlan:
        self.assert_matches_pin(pin)
        plan.assert_matches_pin(pin)
        if plan.execution_budget > self.max_action_calls:
            raise JobPermissionError("ExternalActionPlan execution_budget exceeds the Job external-action grant.")
        if len(plan.required_requests) > self.max_action_calls:
            raise JobPermissionError("ExternalActionPlan request count exceeds the Job external-action grant.")
        for request in plan.required_requests:
            if request.action_id not in self.allowed_actions:
                raise JobPermissionError("External action_id is not in the explicit Job allowlist.")
            if (request.adapter_id, request.adapter_revision) != (self.adapter_id, self.adapter_revision):
                raise JobPermissionError("External action request adapter binding does not match the Job grant.")
            if (
                request.destination_binding_id,
                request.destination_binding_revision,
                request.destination_binding_sha256,
            ) != (
                self.destination_binding_id,
                self.destination_binding_revision,
                self.destination_binding_sha256,
            ):
                raise JobPermissionError("External action request destination binding does not match the Job grant.")
        return AuthorizedJobExternalActionPlan(
            job_id=self.job_id,
            pack_id=self.pack_id,
            pack_version=self.pack_version,
            pack_manifest_sha256=self.pack_manifest_sha256,
            external_action_permission_plan_sha256=self.fingerprint(),
            external_action_plan_sha256=plan.fingerprint(),
            external_action_plan=plan,
        )

def load_plan_fingerprint(plan: LoadPlan) -> str:
    """Return the canonical deterministic fingerprint used by authorized bindings."""
    return _load_plan_fingerprint(plan)
