from __future__ import annotations

import hashlib

import pytest

from universal_runtime.core.https_executor import (
    HttpsExecutorError,
    _AuthorizedRedirectHandler,
    execute_authorized_https_gets,
)
from universal_runtime.core.job_pins import JobPackPin
from universal_runtime.core.network_permissions import (
    JobNetworkPermissionError,
    JobNetworkPermissionPlan,
    NetworkPlan,
    NetworkRequest,
)


def pin() -> JobPackPin:
    return JobPackPin("f3b-https-executor-r001", "biomedical_statistics_research", "0.1.0", "a" * 64)


def grant(*, allow_redirects: bool = False, max_response_bytes: int = 4096) -> JobNetworkPermissionPlan:
    return JobNetworkPermissionPlan.from_job_pin(
        pin(),
        ["example.org"],
        max_requests=2,
        max_response_bytes=max_response_bytes,
        timeout_seconds=7,
        allow_redirects=allow_redirects,
    )


def authorized(permission: JobNetworkPermissionPlan, *, byte_budget: int = 1024):
    request = NetworkRequest(
        "req-1",
        "https://example.org/api?q=delayed",
        "scholarly_search",
        byte_budget=byte_budget,
    )
    plan = NetworkPlan.from_requests(
        plan_id="f3b-https-r001",
        required_requests=[request],
        execution_budget=1,
        response_budget=byte_budget,
    )
    return permission.authorize_network_plan(pin(), plan)


class FakeResponse:
    def __init__(self, body: bytes, url: str = "https://example.org/api?q=delayed") -> None:
        self.status = 200
        self._body = body
        self._url = url
        self.headers = {"Content-Type": "application/json", "Content-Length": str(len(body))}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def getcode(self):
        return self.status

    def geturl(self):
        return self._url

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            return self._body
        return self._body[:size]


class FakeOpener:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.calls = []

    def open(self, request, timeout):
        self.calls.append((request, timeout))
        return self.response


def test_stale_permission_fails_before_transport(monkeypatch):
    permission = grant(max_response_bytes=4096)
    auth = authorized(permission)
    changed = grant(max_response_bytes=2048)

    def forbidden_build_opener(*_args, **_kwargs):
        raise AssertionError("transport must not be constructed before authority revalidation")

    monkeypatch.setattr("universal_runtime.core.https_executor.build_opener", forbidden_build_opener)

    with pytest.raises(HttpsExecutorError, match="stale"):
        execute_authorized_https_gets(changed, auth)


def test_authorized_get_returns_bounded_hash_provenance(monkeypatch):
    permission = grant()
    auth = authorized(permission)
    body = b'{"ok":true}'
    opener = FakeOpener(FakeResponse(body))

    monkeypatch.setattr("universal_runtime.core.https_executor.build_opener", lambda *_handlers: opener)

    results = execute_authorized_https_gets(permission, auth)

    assert len(results) == 1
    result = results[0]
    assert result.body == body
    assert result.response_bytes == len(body)
    assert result.response_sha256 == hashlib.sha256(body).hexdigest()
    assert result.status_code == 200
    assert result.requested_url == "https://example.org/api?q=delayed"
    assert result.final_url == result.requested_url
    assert result.content_type == "application/json"
    assert result.provenance()["response_sha256"] == result.response_sha256

    assert len(opener.calls) == 1
    sent, timeout = opener.calls[0]
    assert sent.get_method() == "GET"
    assert sent.full_url == result.requested_url
    assert timeout == 7


def test_response_larger_than_request_budget_fails(monkeypatch):
    permission = grant()
    auth = authorized(permission, byte_budget=4)
    opener = FakeOpener(FakeResponse(b"12345"))

    monkeypatch.setattr("universal_runtime.core.https_executor.build_opener", lambda *_handlers: opener)

    with pytest.raises(HttpsExecutorError, match="Declared response length exceeds byte_budget"):
        execute_authorized_https_gets(permission, auth)


def test_redirect_denied_before_following_target():
    permission = grant(allow_redirects=False)
    handler = _AuthorizedRedirectHandler(permission)

    from urllib.request import Request

    request = Request("https://example.org/a", method="GET")
    with pytest.raises(JobNetworkPermissionError, match="Redirects are denied"):
        handler.redirect_request(request, None, 302, "Found", {}, "https://example.org/b")


def test_cross_host_redirect_rejected_even_when_redirects_enabled():
    permission = grant(allow_redirects=True)
    handler = _AuthorizedRedirectHandler(permission)

    from urllib.request import Request

    request = Request("https://example.org/a", method="GET")
    with pytest.raises(JobNetworkPermissionError, match="not granted"):
        handler.redirect_request(request, None, 302, "Found", {}, "https://other.example/b")
