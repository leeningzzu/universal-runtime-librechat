from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from universal_runtime.core.job_pins import JobPackPin
from universal_runtime.core.network_permissions import (
    JobNetworkPermissionError,
    JobNetworkPermissionPlan,
    NetworkPlan,
    NetworkRequest,
)

ROOT = Path(__file__).parents[1]
SCHEMAS = ROOT / "schemas"
CURRENT_JOB_SCHEMA = SCHEMAS / "job_bundle.schema.json"
CURRENT_RUNTIME_MANIFEST = SCHEMAS / "runtime_contract_manifest.json"
CANDIDATE_JOB_SCHEMA = SCHEMAS / "job_bundle_network_candidate.schema.json"
CANDIDATE_RUNTIME_MANIFEST = SCHEMAS / "runtime_contract_manifest_network_candidate.json"

EXPECTED_CURRENT_JOB_SCHEMA_SHA = "fb4464f0f646ce1320a2ad95c15622a6e83a084f70dc270b3a0667f9c836169f"
EXPECTED_CURRENT_RUNTIME_MANIFEST_SHA = "442650f62bb12a0e977c269711d2711b5c52016f8057f966feb458f92153ced9"


def pin(job_id: str = "f3b-network-boundary-r001") -> JobPackPin:
    return JobPackPin(job_id, "biomedical_statistics_research", "0.2.0", "a" * 64)


def grant(*, hosts=("example.org",), redirects=False, max_requests=3, max_bytes=3000):
    return JobNetworkPermissionPlan.from_job_pin(
        pin(),
        hosts,
        max_requests=max_requests,
        max_response_bytes=max_bytes,
        timeout_seconds=15,
        allow_redirects=redirects,
    )


def plan(*requests: NetworkRequest, execution_budget=None, response_budget=None):
    return NetworkPlan.from_requests(
        plan_id="f3b-network-plan-r001",
        required_requests=requests,
        execution_budget=len(requests) if execution_budget is None else execution_budget,
        response_budget=sum(r.byte_budget for r in requests) if response_budget is None else response_budget,
    )


def test_exact_pin_binding_and_stable_network_fingerprints() -> None:
    permission = grant(hosts=("Example.Org.", "example.org"))
    assert permission.allowed_hosts == ("example.org",)
    request = NetworkRequest("req-1", "https://example.org/api?q=x", "scholarly_search", byte_budget=1000)
    authorized = permission.authorize_network_plan(pin(), plan(request))
    assert len(authorized.network_permission_plan_sha256) == 64
    assert len(authorized.network_plan_sha256) == 64
    assert authorized.network_permission_plan_sha256 == permission.fingerprint()
    assert authorized.network_plan.required_requests[0].url == "https://example.org/api?q=x"


def test_default_deny_empty_grant_and_wrong_pin_fail_closed() -> None:
    permission = grant(hosts=())
    request = NetworkRequest("req-1", "https://example.org/api", "search", byte_budget=1000)
    with pytest.raises(JobNetworkPermissionError, match="not granted"):
        permission.authorize_network_plan(pin(), plan(request))
    with pytest.raises(JobNetworkPermissionError, match="exact JobPackPin"):
        grant().authorize_network_plan(JobPackPin("other", "biomedical_statistics_research", "0.2.0", "a" * 64), plan(request))


@pytest.mark.parametrize(
    "url",
    [
        "http://example.org/api",
        "https://user:secret@example.org/api",
        "https://example.org:444/api",
        "https://other.example/api",
        "https://example.org/api#fragment",
        "https://127.0.0.1/api",
    ],
)
def test_url_boundary_fails_closed(url: str) -> None:
    with pytest.raises(JobNetworkPermissionError):
        grant().authorize_network_plan(pin(), plan(NetworkRequest("req-1", url, "search")))


def test_wildcard_and_ip_grants_are_forbidden() -> None:
    for host in ("*.example.org", "127.0.0.1", "example.org:443"):
        with pytest.raises(JobNetworkPermissionError):
            grant(hosts=(host,))


def test_request_and_response_budgets_fail_closed() -> None:
    one = NetworkRequest("req-1", "https://example.org/a", "search", byte_budget=700)
    two = NetworkRequest("req-2", "https://example.org/b", "search", byte_budget=700)
    with pytest.raises(JobNetworkPermissionError, match="request grant"):
        grant(max_requests=1).authorize_network_plan(pin(), plan(one, two))
    with pytest.raises(JobNetworkPermissionError, match="response-byte grant"):
        grant(max_bytes=1000).authorize_network_plan(pin(), plan(one, two, response_budget=1400))


def test_default_get_only_and_explicit_bounded_post_json_authorization() -> None:
    body = b'{"q":"x"}'
    request = NetworkRequest(
        "req-1",
        "https://example.org/api",
        "search",
        method="POST",
        request_body_sha256=hashlib.sha256(body).hexdigest(),
        request_body_bytes=len(body),
        content_type="application/json",
        byte_budget=1000,
    )
    with pytest.raises(JobNetworkPermissionError, match="Only GET"):
        grant().authorize_network_plan(pin(), plan(request))

    post_permission = JobNetworkPermissionPlan.from_job_pin(
        pin(),
        ("example.org",),
        max_requests=1,
        max_response_bytes=3000,
        timeout_seconds=15,
        allow_redirects=False,
        allow_post_json=True,
        max_request_body_bytes=len(body),
        allow_bearer_authorization=False,
    )
    authorized = post_permission.authorize_network_plan(pin(), plan(request))
    assert authorized.network_plan.required_requests == (request,)
    assert post_permission.to_dict()["mode"] == "HTTPS_GET_PLUS_BOUNDED_POST_JSON"


def test_redirects_require_explicit_grant_and_target_revalidation() -> None:
    source = "https://example.org/start"
    target = "https://example.org/final"
    with pytest.raises(JobNetworkPermissionError, match="Redirects are denied"):
        grant().authorize_redirect(source, target)
    permission = grant(redirects=True)
    assert permission.authorize_redirect(source, target) == target
    with pytest.raises(JobNetworkPermissionError, match="not granted"):
        permission.authorize_redirect(source, "https://other.example/final")


def test_candidate_contract_is_side_by_side_and_current_contract_bytes_are_unchanged() -> None:
    assert hashlib.sha256(CURRENT_JOB_SCHEMA.read_bytes()).hexdigest() == EXPECTED_CURRENT_JOB_SCHEMA_SHA
    assert hashlib.sha256(CURRENT_RUNTIME_MANIFEST.read_bytes()).hexdigest() == EXPECTED_CURRENT_RUNTIME_MANIFEST_SHA

    candidate_schema = json.loads(CANDIDATE_JOB_SCHEMA.read_text(encoding="utf-8"))
    required = set(candidate_schema["required"])
    assert {"network_permission_plan_sha256", "network_plan_sha256"} <= required
    network = candidate_schema["properties"]["permissions"]["properties"]["network"]
    assert candidate_schema["properties"]["permissions"]["required"] == ["read_roots", "network"]
    assert network["properties"]["mode"]["const"] == "HTTPS_GET_READ_ONLY"
    assert network["properties"]["allowed_hosts"]["uniqueItems"] is True

    candidate_manifest = json.loads(CANDIDATE_RUNTIME_MANIFEST.read_text(encoding="utf-8"))
    assert candidate_manifest["schema_version"] == 2
    assert candidate_manifest["status"] == "CANDIDATE_F3B_NETWORK_PERMISSION_BOUNDARY_R001"
    entry = candidate_manifest["contracts"]["job_bundle"]
    target = SCHEMAS / entry["path"]
    assert target == CANDIDATE_JOB_SCHEMA
    assert hashlib.sha256(target.read_bytes()).hexdigest() == entry["sha256"]
