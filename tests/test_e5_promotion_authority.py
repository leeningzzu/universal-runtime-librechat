import json
from pathlib import Path

import pytest

from universal_runtime.core.hashing import sha256_bytes
from universal_runtime.core.promotion import ApprovalEvidence, PromotionAuthority, PromotionError, PromotionRequest
from universal_runtime.core.routing import RouteAction, RouteDecision


def setup_candidate(tmp_path: Path):
    candidate = tmp_path / "candidate.md"
    candidate.write_bytes(b"candidate R1")
    digest = sha256_bytes(candidate.read_bytes())
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"artifact_id": "artifact", "revision": 1, "sha256": digest}), encoding="utf-8")
    route = RouteDecision(action=RouteAction.GATE_CANDIDATE, artifact_id="artifact", revision=1, reviewed_sha256=digest)
    approval = ApprovalEvidence("approval-1", "human-1", "job-1", "artifact", 1, digest, digest, True)
    return candidate, manifest, route, approval


def test_promotion_preserves_bytes_and_is_idempotent(tmp_path):
    candidate, manifest, route, approval = setup_candidate(tmp_path)
    request = PromotionRequest(route, candidate, manifest, approval)
    authority = PromotionAuthority(tmp_path)
    first = authority.promote(request)
    second = PromotionAuthority(tmp_path).promote(request)
    bundle = tmp_path / "_authoritative" / first.promotion_id
    assert second == first
    assert (bundle / "artifact").read_bytes() == b"candidate R1"
    assert json.loads((bundle / "manifest.json").read_text())["persistence_class"] == "AUTHORITATIVE"
    assert len(list((tmp_path / "_authoritative").iterdir())) == 1


@pytest.mark.parametrize("mutator", [
    lambda a: ApprovalEvidence(a.approval_id, a.approver_id, a.job_id, a.artifact_id, a.revision, a.candidate_sha256, a.reviewed_sha256, False),
    lambda a: ApprovalEvidence(a.approval_id, a.approver_id, a.job_id, "other", a.revision, a.candidate_sha256, a.reviewed_sha256, True),
])
def test_invalid_approval_fails_closed(tmp_path, mutator):
    candidate, manifest, route, approval = setup_candidate(tmp_path)
    with pytest.raises(PromotionError):
        PromotionAuthority(tmp_path).promote(PromotionRequest(route, candidate, manifest, mutator(approval)))
    assert not any((tmp_path / "_authoritative").glob("*/artifact"))


def test_candidate_change_after_review_fails_closed(tmp_path):
    candidate, manifest, route, approval = setup_candidate(tmp_path)
    candidate.write_bytes(b"tampered")
    with pytest.raises(PromotionError):
        PromotionAuthority(tmp_path).promote(PromotionRequest(route, candidate, manifest, approval))


def test_revise_and_blocker_are_rejected(tmp_path):
    candidate, manifest, route, approval = setup_candidate(tmp_path)
    for action in (RouteAction.RETURN_TO_P08, RouteAction.STOP_BLOCKER):
        bad_route = RouteDecision(action=action, artifact_id=route.artifact_id, revision=route.revision, reviewed_sha256=route.reviewed_sha256)
        with pytest.raises(PromotionError):
            PromotionAuthority(tmp_path).promote(PromotionRequest(bad_route, candidate, manifest, approval))
