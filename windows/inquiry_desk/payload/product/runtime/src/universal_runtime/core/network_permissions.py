from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import ipaddress
import json
import re
from typing import Any, Iterable
from urllib.parse import urlsplit, urlunsplit

from .job_pins import JobCapabilityPin


class JobNetworkPermissionError(ValueError):
    """Raised when a job-scoped network authorization fails closed."""


_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _digest(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _canonical_host(value: str) -> str:
    if not isinstance(value, str):
        raise JobNetworkPermissionError("Allowed host must be a string.")
    host = value.strip().lower().rstrip(".")
    if not host or "*" in host or "/" in host or "\\" in host or ":" in host:
        raise JobNetworkPermissionError("Allowed hosts must be exact DNS hostnames without wildcards or ports.")
    if not re.fullmatch(r"[a-z0-9.-]+", host) or ".." in host:
        raise JobNetworkPermissionError("Allowed host is not a canonical DNS hostname.")
    labels = host.split(".")
    if any(not label or len(label) > 63 or label.startswith("-") or label.endswith("-") for label in labels):
        raise JobNetworkPermissionError("Allowed host contains an invalid DNS label.")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise JobNetworkPermissionError("Direct IP network grants are not allowed.")
    return host


def _canonical_url(url: str, allowed_hosts: tuple[str, ...]) -> str:
    if not isinstance(url, str) or not url or any(ord(ch) < 32 or ch == " " for ch in url):
        raise JobNetworkPermissionError("Network URL must be a non-empty control-character-free string.")
    parts = urlsplit(url)
    if parts.scheme.lower() != "https":
        raise JobNetworkPermissionError("Only HTTPS network access is allowed.")
    if parts.username is not None or parts.password is not None:
        raise JobNetworkPermissionError("Credentials in network URLs are not allowed.")
    if parts.fragment:
        raise JobNetworkPermissionError("URL fragments are not allowed in authorized network requests.")
    try:
        port = parts.port
    except ValueError as exc:
        raise JobNetworkPermissionError("Invalid network URL port.") from exc
    if port not in (None, 443):
        raise JobNetworkPermissionError("Only the default HTTPS port is allowed.")
    if parts.hostname is None:
        raise JobNetworkPermissionError("Network URL must include a hostname.")
    host = _canonical_host(parts.hostname)
    if host not in allowed_hosts:
        raise JobNetworkPermissionError(f"Network host is not granted for this Job: {host}")
    path = parts.path or "/"
    return urlunsplit(("https", host, path, parts.query, ""))


@dataclass(frozen=True)
class NetworkRequest:
    request_id: str
    url: str
    role: str
    method: str = "GET"
    byte_budget: int = 1_000_000
    request_body_sha256: str | None = None
    request_body_bytes: int = 0
    content_type: str | None = None
    requires_bearer_authorization: bool = False

    def validate(self) -> None:
        if not isinstance(self.request_id, str) or not self.request_id:
            raise JobNetworkPermissionError("request_id must be a non-empty string.")
        if not isinstance(self.role, str) or not self.role:
            raise JobNetworkPermissionError("network request role must be a non-empty string.")
        if self.method not in {"GET", "POST"}:
            raise JobNetworkPermissionError("Only GET or bounded POST application/json requests are structurally supported.")
        if not isinstance(self.byte_budget, int) or self.byte_budget <= 0:
            raise JobNetworkPermissionError("byte_budget must be a positive integer.")
        if not isinstance(self.requires_bearer_authorization, bool):
            raise JobNetworkPermissionError("requires_bearer_authorization must be boolean.")

        if self.method == "GET":
            if (
                self.request_body_sha256 is not None
                or self.request_body_bytes != 0
                or self.content_type is not None
                or self.requires_bearer_authorization
            ):
                raise JobNetworkPermissionError("GET requests cannot carry POST body/auth metadata.")
            return

        if self.content_type != "application/json":
            raise JobNetworkPermissionError("POST requests must use exact content_type application/json.")
        if not isinstance(self.request_body_sha256, str) or not _HEX64.fullmatch(self.request_body_sha256):
            raise JobNetworkPermissionError("POST request_body_sha256 must be lowercase 64-hex.")
        if not isinstance(self.request_body_bytes, int) or self.request_body_bytes <= 0:
            raise JobNetworkPermissionError("POST request_body_bytes must be a positive integer.")


@dataclass(frozen=True)
class NetworkPlan:
    plan_id: str
    required_requests: tuple[NetworkRequest, ...]
    execution_budget: int
    response_budget: int

    @classmethod
    def from_requests(
        cls,
        *,
        plan_id: str,
        required_requests: Iterable[NetworkRequest],
        execution_budget: int,
        response_budget: int,
    ) -> "NetworkPlan":
        return cls(plan_id, tuple(required_requests), execution_budget, response_budget)

    def validate(self) -> None:
        if not isinstance(self.plan_id, str) or not self.plan_id:
            raise JobNetworkPermissionError("network plan_id must be a non-empty string.")
        if not isinstance(self.execution_budget, int) or self.execution_budget < 0:
            raise JobNetworkPermissionError("execution_budget must be a non-negative integer.")
        if not isinstance(self.response_budget, int) or self.response_budget < 0:
            raise JobNetworkPermissionError("response_budget must be a non-negative integer.")
        if len(self.required_requests) > self.execution_budget:
            raise JobNetworkPermissionError("NetworkPlan request count exceeds execution_budget.")
        seen: set[str] = set()
        total = 0
        for request in self.required_requests:
            request.validate()
            if request.request_id in seen:
                raise JobNetworkPermissionError("NetworkPlan request_id values must be unique.")
            seen.add(request.request_id)
            total += request.byte_budget
        if total > self.response_budget:
            raise JobNetworkPermissionError("NetworkPlan byte budgets exceed response_budget.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "required_requests": [
                (
                    {
                        "request_id": item.request_id,
                        "url": item.url,
                        "role": item.role,
                        "method": item.method,
                        "byte_budget": item.byte_budget,
                    }
                    if item.method == "GET"
                    else {
                        "request_id": item.request_id,
                        "url": item.url,
                        "role": item.role,
                        "method": item.method,
                        "byte_budget": item.byte_budget,
                        "request_body_sha256": item.request_body_sha256,
                        "request_body_bytes": item.request_body_bytes,
                        "content_type": item.content_type,
                        "requires_bearer_authorization": item.requires_bearer_authorization,
                    }
                )
                for item in self.required_requests
            ],
            "execution_budget": self.execution_budget,
            "response_budget": self.response_budget,
        }

    def fingerprint(self) -> str:
        return _digest(self.to_dict())


@dataclass(frozen=True)
class AuthorizedJobNetworkPlan:
    job_id: str
    capability_id: str
    capability_revision: str
    capability_manifest_sha256: str
    network_permission_plan_sha256: str
    network_plan_sha256: str
    network_plan: NetworkPlan


@dataclass(frozen=True)
class JobNetworkPermissionPlan:
    job_id: str
    capability_id: str
    capability_revision: str
    capability_manifest_sha256: str
    allowed_hosts: tuple[str, ...]
    max_requests: int
    max_response_bytes: int
    timeout_seconds: float
    allow_redirects: bool = False
    allow_post_json: bool = False
    max_request_body_bytes: int = 0
    allow_bearer_authorization: bool = False

    @classmethod
    def from_job_pin(
        cls,
        pin: JobCapabilityPin,
        allowed_hosts: Iterable[str],
        *,
        max_requests: int,
        max_response_bytes: int,
        timeout_seconds: float = 20.0,
        allow_redirects: bool = False,
        allow_post_json: bool = False,
        max_request_body_bytes: int = 0,
        allow_bearer_authorization: bool = False,
    ) -> "JobNetworkPermissionPlan":
        hosts = tuple(sorted({_canonical_host(host) for host in allowed_hosts}))
        if not isinstance(max_requests, int) or max_requests < 0:
            raise JobNetworkPermissionError("max_requests must be a non-negative integer.")
        if not isinstance(max_response_bytes, int) or max_response_bytes < 0:
            raise JobNetworkPermissionError("max_response_bytes must be a non-negative integer.")
        if not isinstance(timeout_seconds, (int, float)) or not (0 < float(timeout_seconds) <= 120):
            raise JobNetworkPermissionError("timeout_seconds must be > 0 and <= 120.")
        if not isinstance(allow_post_json, bool):
            raise JobNetworkPermissionError("allow_post_json must be boolean.")
        if not isinstance(max_request_body_bytes, int) or max_request_body_bytes < 0:
            raise JobNetworkPermissionError("max_request_body_bytes must be a non-negative integer.")
        if not isinstance(allow_bearer_authorization, bool):
            raise JobNetworkPermissionError("allow_bearer_authorization must be boolean.")
        if not allow_post_json and max_request_body_bytes != 0:
            raise JobNetworkPermissionError("max_request_body_bytes requires allow_post_json=True.")
        if allow_post_json and max_request_body_bytes <= 0:
            raise JobNetworkPermissionError("allow_post_json=True requires positive max_request_body_bytes.")
        if allow_bearer_authorization and not allow_post_json:
            raise JobNetworkPermissionError("Bearer authorization is allowed only for bounded POST JSON in this capability slice.")
        return cls(
            job_id=pin.job_id,
            capability_id=pin.capability_id,
            capability_revision=pin.capability_revision,
            capability_manifest_sha256=pin.capability_manifest_sha256,
            allowed_hosts=hosts,
            max_requests=max_requests,
            max_response_bytes=max_response_bytes,
            timeout_seconds=float(timeout_seconds),
            allow_redirects=bool(allow_redirects),
            allow_post_json=allow_post_json,
            max_request_body_bytes=max_request_body_bytes,
            allow_bearer_authorization=allow_bearer_authorization,
        )

    def to_dict(self) -> dict[str, Any]:
        base = {
            "job_id": self.job_id,
            "capability_id": self.capability_id,
            "capability_revision": self.capability_revision,
            "capability_manifest_sha256": self.capability_manifest_sha256,
            "mode": "HTTPS_GET_READ_ONLY",
            "allowed_hosts": list(self.allowed_hosts),
            "max_requests": self.max_requests,
            "max_response_bytes": self.max_response_bytes,
            "timeout_seconds": self.timeout_seconds,
            "allow_redirects": self.allow_redirects,
        }
        if not self.allow_post_json and self.max_request_body_bytes == 0 and not self.allow_bearer_authorization:
            return base
        return {
            **base,
            "mode": "HTTPS_GET_PLUS_BOUNDED_POST_JSON",
            "allow_post_json": self.allow_post_json,
            "max_request_body_bytes": self.max_request_body_bytes,
            "allow_bearer_authorization": self.allow_bearer_authorization,
        }

    def fingerprint(self) -> str:
        return _digest(self.to_dict())

    def assert_matches_pin(self, pin: JobCapabilityPin) -> None:
        expected = (self.job_id, self.capability_id, self.capability_revision, self.capability_manifest_sha256)
        actual = (pin.job_id, pin.capability_id, pin.capability_revision, pin.capability_manifest_sha256)
        if expected != actual:
            raise JobNetworkPermissionError("Network permission plan does not match the exact JobCapabilityPin.")

    def authorize_network_plan(self, pin: JobCapabilityPin, plan: NetworkPlan) -> AuthorizedJobNetworkPlan:
        self.assert_matches_pin(pin)
        plan.validate()
        if len(plan.required_requests) > self.max_requests or plan.execution_budget > self.max_requests:
            raise JobNetworkPermissionError("NetworkPlan exceeds the Job request grant.")
        if plan.response_budget > self.max_response_bytes:
            raise JobNetworkPermissionError("NetworkPlan exceeds the Job response-byte grant.")

        total_request_body_bytes = 0
        for request in plan.required_requests:
            if request.method == "GET":
                continue
            if request.method != "POST" or not self.allow_post_json:
                raise JobNetworkPermissionError("Only GET network requests are allowed by this Job network permission plan.")
            total_request_body_bytes += request.request_body_bytes
            if request.requires_bearer_authorization and not self.allow_bearer_authorization:
                raise JobNetworkPermissionError("Bearer authorization is not granted for this Job network permission plan.")
        if total_request_body_bytes > self.max_request_body_bytes:
            raise JobNetworkPermissionError("NetworkPlan exceeds the Job request-body byte grant.")

        canonical_requests = tuple(
            replace(request, url=_canonical_url(request.url, self.allowed_hosts))
            for request in plan.required_requests
        )
        canonical_plan = NetworkPlan(
            plan_id=plan.plan_id,
            required_requests=canonical_requests,
            execution_budget=plan.execution_budget,
            response_budget=plan.response_budget,
        )
        return AuthorizedJobNetworkPlan(
            job_id=self.job_id,
            capability_id=self.capability_id,
            capability_revision=self.capability_revision,
            capability_manifest_sha256=self.capability_manifest_sha256,
            network_permission_plan_sha256=self.fingerprint(),
            network_plan_sha256=canonical_plan.fingerprint(),
            network_plan=canonical_plan,
        )

    def authorize_redirect(self, source_url: str, target_url: str) -> str:
        _canonical_url(source_url, self.allowed_hosts)
        if not self.allow_redirects:
            raise JobNetworkPermissionError("Redirects are denied by this Job network permission plan.")
        return _canonical_url(target_url, self.allowed_hosts)
