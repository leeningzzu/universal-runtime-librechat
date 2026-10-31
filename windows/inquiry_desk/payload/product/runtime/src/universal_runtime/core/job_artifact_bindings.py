from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from .job_permissions import AuthorizedJobLoadPlan
from .job_pins import JobCapabilityPin
from .models import ArtifactManifest


class JobArtifactBindingError(ValueError):
    """Raised when a Runtime-selected Job artifact binding is malformed or stale."""


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _sha256_payload(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _non_empty(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise JobArtifactBindingError(f"{name} must be a non-empty string")
    return value


def _sha256(value: object, name: str, *, optional: bool = False) -> str | None:
    if optional and value is None:
        return None
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise JobArtifactBindingError(f"{name} must be lowercase 64-hex SHA-256")
    return value


def _revision(value: object, name: str = "revision") -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise JobArtifactBindingError(f"{name} must be an integer >= 1")
    return value


def _validate_pin(pin: JobCapabilityPin) -> None:
    if not isinstance(pin, JobCapabilityPin):
        raise JobArtifactBindingError("job_pin must be an exact JobCapabilityPin")
    _non_empty(pin.job_id, "job_id")
    _non_empty(pin.capability_id, "capability_id")
    _non_empty(pin.capability_revision, "capability_revision")
    _sha256(pin.capability_manifest_sha256, "capability_manifest_sha256")


@dataclass(frozen=True)
class JobArtifactBinding:
    role: str
    artifact_id: str
    revision: int
    sha256: str

    def __post_init__(self) -> None:
        _non_empty(self.role, "role")
        _non_empty(self.artifact_id, "artifact_id")
        _revision(self.revision)
        _sha256(self.sha256, "sha256")

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "artifact_id": self.artifact_id,
            "revision": self.revision,
            "sha256": self.sha256,
        }


def _plan_payload(
    *,
    job_id: str,
    capability_id: str,
    capability_revision: str,
    capability_manifest_sha256: str,
    permission_plan_sha256: str | None,
    load_plan_sha256: str | None,
    bindings: tuple[JobArtifactBinding, ...],
) -> dict[str, Any]:
    return {
        "job_id": job_id,
        "capability_id": capability_id,
        "capability_revision": capability_revision,
        "capability_manifest_sha256": capability_manifest_sha256,
        "permission_plan_sha256": permission_plan_sha256,
        "load_plan_sha256": load_plan_sha256,
        "bindings": [
            binding.to_dict()
            for binding in sorted(bindings, key=lambda item: item.role)
        ],
    }


@dataclass(frozen=True)
class JobArtifactBindingPlan:
    """Immutable Runtime/Job-Authority-selected artifact bindings for one execution."""

    job_id: str
    capability_id: str
    capability_revision: str
    capability_manifest_sha256: str
    permission_plan_sha256: str | None
    load_plan_sha256: str | None
    bindings: tuple[JobArtifactBinding, ...]
    binding_plan_sha256: str

    def __post_init__(self) -> None:
        _non_empty(self.job_id, "job_id")
        _non_empty(self.capability_id, "capability_id")
        _non_empty(self.capability_revision, "capability_revision")
        _sha256(self.capability_manifest_sha256, "capability_manifest_sha256")
        _sha256(self.permission_plan_sha256, "permission_plan_sha256", optional=True)
        _sha256(self.load_plan_sha256, "load_plan_sha256", optional=True)
        _sha256(self.binding_plan_sha256, "binding_plan_sha256")

        if not isinstance(self.bindings, tuple) or not self.bindings:
            raise JobArtifactBindingError("bindings must be a non-empty tuple")

        roles: set[str] = set()
        for binding in self.bindings:
            if not isinstance(binding, JobArtifactBinding):
                raise JobArtifactBindingError("bindings must contain JobArtifactBinding values")
            if binding.role in roles:
                raise JobArtifactBindingError(f"duplicate artifact binding role: {binding.role}")
            roles.add(binding.role)

        expected = _sha256_payload(
            _plan_payload(
                job_id=self.job_id,
                capability_id=self.capability_id,
                capability_revision=self.capability_revision,
                capability_manifest_sha256=self.capability_manifest_sha256,
                permission_plan_sha256=self.permission_plan_sha256,
                load_plan_sha256=self.load_plan_sha256,
                bindings=self.bindings,
            )
        )
        if self.binding_plan_sha256 != expected:
            raise JobArtifactBindingError("binding_plan_sha256 does not match plan content")

    def to_dict(self) -> dict[str, Any]:
        payload = _plan_payload(
            job_id=self.job_id,
            capability_id=self.capability_id,
            capability_revision=self.capability_revision,
            capability_manifest_sha256=self.capability_manifest_sha256,
            permission_plan_sha256=self.permission_plan_sha256,
            load_plan_sha256=self.load_plan_sha256,
            bindings=self.bindings,
        )
        payload["binding_plan_sha256"] = self.binding_plan_sha256
        return payload

    def binding_for_role(self, role: str) -> JobArtifactBinding:
        _non_empty(role, "role")
        matches = tuple(binding for binding in self.bindings if binding.role == role)
        if len(matches) != 1:
            raise JobArtifactBindingError(f"current artifact binding role not found exactly once: {role}")
        return matches[0]


def _selected_pairs(
    selected: Mapping[str, ArtifactManifest] | Iterable[tuple[str, ArtifactManifest]],
) -> tuple[tuple[str, ArtifactManifest], ...]:
    values = selected.items() if isinstance(selected, Mapping) else selected
    pairs: list[tuple[str, ArtifactManifest]] = []
    try:
        for item in values:
            if not isinstance(item, tuple) or len(item) != 2:
                raise JobArtifactBindingError("selected bindings must be (role, ArtifactManifest) pairs")
            role, manifest = item
            pairs.append((role, manifest))
    except TypeError as exc:
        raise JobArtifactBindingError("selected bindings are not iterable") from exc
    if not pairs:
        raise JobArtifactBindingError("selected bindings must be non-empty")
    return tuple(pairs)


def _validate_authorized_load(
    *,
    pin: JobCapabilityPin,
    authorized_load: AuthorizedJobLoadPlan,
    bindings: tuple[JobArtifactBinding, ...],
) -> tuple[str, str]:
    if not isinstance(authorized_load, AuthorizedJobLoadPlan):
        raise JobArtifactBindingError("authorized_load must be an AuthorizedJobLoadPlan")

    expected_identity = (
        pin.job_id,
        pin.capability_id,
        pin.capability_revision,
        pin.capability_manifest_sha256,
    )
    actual_identity = (
        authorized_load.job_id,
        authorized_load.capability_id,
        authorized_load.capability_revision,
        authorized_load.capability_manifest_sha256,
    )
    if actual_identity != expected_identity:
        raise JobArtifactBindingError("authorized_load does not match the exact JobCapabilityPin")

    permission_sha = _sha256(
        authorized_load.permission_plan_sha256,
        "permission_plan_sha256",
    )
    load_sha = _sha256(authorized_load.load_plan_sha256, "load_plan_sha256")
    assert permission_sha is not None and load_sha is not None

    by_role: dict[str, list[Any]] = {}
    for item in authorized_load.load_plan.required_inputs:
        by_role.setdefault(item.role, []).append(item)

    for binding in bindings:
        matched = by_role.get(binding.role, [])
        if not matched:
            continue
        if len(matched) != 1:
            raise JobArtifactBindingError(
                f"authorized_load must contain exactly one input for selected role: {binding.role}"
            )
        if matched[0].expected_sha256 != binding.sha256:
            raise JobArtifactBindingError(
                f"authorized_load SHA does not match selected artifact binding for role: {binding.role}"
            )

    return permission_sha, load_sha


def create_job_artifact_binding_plan(
    *,
    job_pin: JobCapabilityPin,
    selected: Mapping[str, ArtifactManifest] | Iterable[tuple[str, ArtifactManifest]],
    authorized_load: AuthorizedJobLoadPlan | None = None,
) -> JobArtifactBindingPlan:
    """Record an explicit Runtime/Job-Authority selection; do not discover "latest".

    `selected` is Authority input supplied by Runtime/Job assembly before capability execution.
    This function never scans ArtifactStore history, never selects a revision, never
    reads bytes, grants permission, persists state, or consults Promotion.
    """

    _validate_pin(job_pin)

    bindings: list[JobArtifactBinding] = []
    roles: set[str] = set()
    for role, manifest in _selected_pairs(selected):
        _non_empty(role, "role")
        if role in roles:
            raise JobArtifactBindingError(f"duplicate artifact binding role: {role}")
        roles.add(role)

        if not isinstance(manifest, ArtifactManifest):
            raise JobArtifactBindingError("selected values must be exact Runtime ArtifactManifest objects")
        binding = JobArtifactBinding(
            role=role,
            artifact_id=manifest.artifact_id,
            revision=manifest.revision,
            sha256=manifest.sha256,
        )
        bindings.append(binding)

    binding_tuple = tuple(sorted(bindings, key=lambda item: item.role))
    permission_sha: str | None = None
    load_sha: str | None = None
    if authorized_load is not None:
        permission_sha, load_sha = _validate_authorized_load(
            pin=job_pin,
            authorized_load=authorized_load,
            bindings=binding_tuple,
        )

    payload = _plan_payload(
        job_id=job_pin.job_id,
        capability_id=job_pin.capability_id,
        capability_revision=job_pin.capability_revision,
        capability_manifest_sha256=job_pin.capability_manifest_sha256,
        permission_plan_sha256=permission_sha,
        load_plan_sha256=load_sha,
        bindings=binding_tuple,
    )
    return JobArtifactBindingPlan(
        job_id=job_pin.job_id,
        capability_id=job_pin.capability_id,
        capability_revision=job_pin.capability_revision,
        capability_manifest_sha256=job_pin.capability_manifest_sha256,
        permission_plan_sha256=permission_sha,
        load_plan_sha256=load_sha,
        bindings=binding_tuple,
        binding_plan_sha256=_sha256_payload(payload),
    )


def assert_job_artifact_binding_current(
    plan: JobArtifactBindingPlan,
    *,
    job_id: str,
    role: str,
    artifact_id: str,
    revision: int,
    sha256: str,
) -> JobArtifactBinding:
    """Fail closed unless a candidate exact triple matches Runtime's Job/role plan."""

    if not isinstance(plan, JobArtifactBindingPlan):
        raise JobArtifactBindingError("plan must be a JobArtifactBindingPlan")

    # Re-validate the immutable envelope at query time so object-level tampering
    # cannot silently bypass the deterministic fingerprint.
    JobArtifactBindingPlan(**plan.__dict__)

    _non_empty(job_id, "job_id")
    if job_id != plan.job_id:
        raise JobArtifactBindingError("job_id does not match the binding plan")

    _non_empty(role, "role")
    _non_empty(artifact_id, "artifact_id")
    _revision(revision)
    _sha256(sha256, "sha256")

    current = plan.binding_for_role(role)
    if current.artifact_id != artifact_id:
        raise JobArtifactBindingError(f"artifact_id is not current for role: {role}")
    if current.revision != revision:
        raise JobArtifactBindingError(f"revision is not current for role: {role}")
    if current.sha256 != sha256:
        raise JobArtifactBindingError(f"sha256 is not current for role: {role}")
    return current


__all__ = [
    "JobArtifactBinding",
    "JobArtifactBindingError",
    "JobArtifactBindingPlan",
    "assert_job_artifact_binding_current",
    "create_job_artifact_binding_plan",
]
