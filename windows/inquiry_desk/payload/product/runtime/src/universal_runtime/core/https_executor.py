from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .job_pins import JobCapabilityPin
from .network_permissions import (
    AuthorizedJobNetworkPlan,
    JobNetworkPermissionError,
    JobNetworkPermissionPlan,
)


class HttpsExecutorError(RuntimeError):
    "Raised when bounded HTTPS execution cannot complete safely."


_BEARER_TOKEN_RE = re.compile(r"^[A-Za-z0-9\-._~+/]+=*$")
_AUTHORIZATION_HEADER_RE = re.compile(r"^Bearer [A-Za-z0-9\-._~+/]+=*$")
_MAX_BEARER_TOKEN_CHARS = 4096


def _validated_execution_bearer_authorization_header(value: str | None) -> str:
    if value is None or (type(value) is str and not value):
        raise HttpsExecutorError("Execution-time Bearer token is required for this authorized network plan.")
    if type(value) is not str:
        raise HttpsExecutorError("Execution-time Bearer token must be an exact built-in str.")
    if len(value) > _MAX_BEARER_TOKEN_CHARS or _BEARER_TOKEN_RE.fullmatch(value) is None:
        raise HttpsExecutorError("Execution-time Bearer token is not header-safe.")

    authorization = "Bearer " + value
    if (
        type(authorization) is not str
        or _AUTHORIZATION_HEADER_RE.fullmatch(authorization) is None
        or "\r" in authorization
        or "\n" in authorization
    ):
        raise HttpsExecutorError("Execution-time Authorization header is not header-safe.")
    try:
        authorization.encode("ascii", errors="strict")
    except UnicodeEncodeError as exc:
        raise HttpsExecutorError("Execution-time Authorization header is not ASCII-safe.") from exc
    return authorization


@dataclass(frozen=True)
class HttpsResponse:
    request_id: str
    role: str
    requested_url: str
    final_url: str
    status_code: int
    body: bytes
    response_bytes: int
    response_sha256: str
    executed_at_utc: str
    content_type: str | None

    def provenance(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "role": self.role,
            "requested_url": self.requested_url,
            "final_url": self.final_url,
            "status_code": self.status_code,
            "response_bytes": self.response_bytes,
            "response_sha256": self.response_sha256,
            "executed_at_utc": self.executed_at_utc,
            "content_type": self.content_type,
        }


class _AuthorizedRedirectHandler(HTTPRedirectHandler):
    def __init__(self, permission: JobNetworkPermissionPlan) -> None:
        super().__init__()
        self._permission = permission

    def redirect_request(
        self,
        req: Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> Request | None:
        if req.get_method().upper() != "GET":
            raise JobNetworkPermissionError(
                "Redirects are denied for non-GET authorized network requests."
            )
        canonical_target = self._permission.authorize_redirect(req.full_url, newurl)
        return super().redirect_request(req, fp, code, msg, headers, canonical_target)


def _revalidate_authorized_plan(
    permission: JobNetworkPermissionPlan,
    authorized: AuthorizedJobNetworkPlan,
) -> None:
    identity = (
        permission.job_id,
        permission.capability_id,
        permission.capability_revision,
        permission.capability_manifest_sha256,
    )
    authorized_identity = (
        authorized.job_id,
        authorized.capability_id,
        authorized.capability_revision,
        authorized.capability_manifest_sha256,
    )
    if identity != authorized_identity:
        raise HttpsExecutorError("Authorized network plan does not match the execution permission identity.")

    if permission.fingerprint() != authorized.network_permission_plan_sha256:
        raise HttpsExecutorError("Authorized network plan is stale for the supplied permission fingerprint.")

    if authorized.network_plan.fingerprint() != authorized.network_plan_sha256:
        raise HttpsExecutorError("Authorized network plan fingerprint no longer matches its exact request plan.")

    pin = JobCapabilityPin(
        authorized.job_id,
        authorized.capability_id,
        authorized.capability_revision,
        authorized.capability_manifest_sha256,
    )
    reauthorized = permission.authorize_network_plan(pin, authorized.network_plan)

    if (
        reauthorized.network_permission_plan_sha256
        != authorized.network_permission_plan_sha256
        or reauthorized.network_plan_sha256 != authorized.network_plan_sha256
    ):
        raise HttpsExecutorError("Reauthorization changed the exact authorized network plan.")


def _validated_post_body(
    item: Any,
    request_bodies: Mapping[str, bytes],
) -> bytes:
    if item.request_id not in request_bodies:
        raise HttpsExecutorError(f"Exact POST body is missing for request_id={item.request_id}.")
    body = request_bodies[item.request_id]
    if not isinstance(body, bytes):
        raise HttpsExecutorError(f"POST body must be exact bytes for request_id={item.request_id}.")
    if len(body) != item.request_body_bytes:
        raise HttpsExecutorError(f"POST body byte length mismatch for request_id={item.request_id}.")
    if hashlib.sha256(body).hexdigest() != item.request_body_sha256:
        raise HttpsExecutorError(f"POST body SHA256 mismatch for request_id={item.request_id}.")
    try:
        parsed = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HttpsExecutorError(f"POST body must be valid UTF-8 JSON for request_id={item.request_id}.") from exc
    if not isinstance(parsed, dict):
        raise HttpsExecutorError(f"POST JSON body must be an object for request_id={item.request_id}.")
    return body


def execute_authorized_https_requests(
    permission: JobNetworkPermissionPlan,
    authorized: AuthorizedJobNetworkPlan,
    *,
    request_bodies: Mapping[str, bytes] | None = None,
    bearer_token: str | None = None,
) -> tuple[HttpsResponse, ...]:
    """Execute an exact authorized HTTPS plan containing GET and/or bounded POST JSON.

    POST body bytes are supplied only at execution time and must match the SHA/byte
    metadata already frozen in the authorized NetworkPlan.  A Bearer token is also
    execution-time-only: the secret value is never added to the NetworkPlan or
    returned in provenance.
    """
    _revalidate_authorized_plan(permission, authorized)

    bodies = {} if request_bodies is None else dict(request_bodies)
    post_ids = {item.request_id for item in authorized.network_plan.required_requests if item.method == "POST"}
    if set(bodies) != post_ids:
        missing = sorted(post_ids - set(bodies))
        extra = sorted(set(bodies) - post_ids)
        raise HttpsExecutorError(
            f"Execution POST body map must match exact POST request ids; missing={missing}, extra={extra}."
        )

    bearer_required = any(
        item.method == "POST" and item.requires_bearer_authorization
        for item in authorized.network_plan.required_requests
    )
    validated_authorization_header = None
    if bearer_required:
        if not permission.allow_bearer_authorization:
            raise HttpsExecutorError("Bearer authorization is not granted by the supplied Job network permission.")
        validated_authorization_header = _validated_execution_bearer_authorization_header(bearer_token)
    elif bearer_token is not None:
        raise HttpsExecutorError("Bearer token was supplied but the authorized network plan does not require it.")

    validated_post_bodies = {
        item.request_id: _validated_post_body(item, bodies)
        for item in authorized.network_plan.required_requests
        if item.method == "POST"
    }

    opener = build_opener(ProxyHandler({}), _AuthorizedRedirectHandler(permission))
    results: list[HttpsResponse] = []
    total_response_bytes = 0

    for item in authorized.network_plan.required_requests:
        if item.method == "GET":
            body = None
            headers = {
                "User-Agent": "UniversalRuntime/0.1",
                "Accept": "*/*",
            }
        elif item.method == "POST":
            body = validated_post_bodies[item.request_id]
            headers = {
                "User-Agent": "UniversalRuntime/0.1",
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
            if item.requires_bearer_authorization:
                headers["Authorization"] = validated_authorization_header
        else:
            raise HttpsExecutorError(f"Unsupported authorized method for request_id={item.request_id}.")

        request = Request(
            item.url,
            data=body,
            method=item.method,
            headers=headers,
        )
        try:
            with opener.open(request, timeout=permission.timeout_seconds) as response:
                status = int(getattr(response, "status", response.getcode()))
                if status < 200 or status >= 300:
                    raise HttpsExecutorError(
                        f"HTTP status {status} is outside the accepted 2xx range for request_id={item.request_id}."
                    )

                final_url = str(response.geturl())
                if final_url != item.url:
                    if item.method != "GET":
                        raise HttpsExecutorError(
                            f"POST final URL changed outside the exact authorized request for request_id={item.request_id}."
                        )
                    final_url = permission.authorize_redirect(item.url, final_url)

                content_length = response.headers.get("Content-Length")
                if content_length is not None:
                    try:
                        declared_length = int(content_length)
                    except (TypeError, ValueError):
                        declared_length = None
                    if declared_length is not None and declared_length > item.byte_budget:
                        raise HttpsExecutorError(
                            f"Declared response length exceeds byte_budget for request_id={item.request_id}."
                        )

                response_body = response.read(item.byte_budget + 1)
                if len(response_body) > item.byte_budget:
                    raise HttpsExecutorError(
                        f"Response exceeded byte_budget for request_id={item.request_id}."
                    )

                total_response_bytes += len(response_body)
                if total_response_bytes > authorized.network_plan.response_budget:
                    raise HttpsExecutorError("Actual response bytes exceeded the authorized plan response_budget.")

                digest = hashlib.sha256(response_body).hexdigest()
                content_type = response.headers.get("Content-Type")
                executed_at = datetime.now(timezone.utc).isoformat()

                results.append(
                    HttpsResponse(
                        request_id=item.request_id,
                        role=item.role,
                        requested_url=item.url,
                        final_url=final_url,
                        status_code=status,
                        body=response_body,
                        response_bytes=len(response_body),
                        response_sha256=digest,
                        executed_at_utc=executed_at,
                        content_type=content_type,
                    )
                )
        except JobNetworkPermissionError:
            raise
        except HttpsExecutorError:
            raise
        except HTTPError as exc:
            raise HttpsExecutorError(
                f"HTTP request failed with status {exc.code} for request_id={item.request_id}."
            ) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise HttpsExecutorError(
                f"HTTPS transport failed for request_id={item.request_id}: {type(exc).__name__}."
            ) from exc

    return tuple(results)


def execute_authorized_https_gets(
    permission: JobNetworkPermissionPlan,
    authorized: AuthorizedJobNetworkPlan,
) -> tuple[HttpsResponse, ...]:
    "Execute exactly the already-authorized HTTPS GET plan."
    if any(item.method != "GET" for item in authorized.network_plan.required_requests):
        raise HttpsExecutorError("execute_authorized_https_gets accepts GET-only authorized plans.")
    return execute_authorized_https_requests(permission, authorized)


__all__ = [
    "HttpsExecutorError",
    "HttpsResponse",
    "execute_authorized_https_gets",
    "execute_authorized_https_requests",
]
