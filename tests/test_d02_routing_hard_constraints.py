import hashlib
from pathlib import Path

import pytest

from universal_runtime.core.routing import RouteAction, RoutingContext, RoutingError, route_review


SHA = "a" * 64


def review(verdict="PASS", sha=SHA, **overrides):
    value = {
        "verdict": verdict,
        "reviewed_sha256": sha,
        "summary": "review",
        "revision_targets": [] if verdict != "REVISE" else ["parent"],
        "blocker_details": None if verdict != "HISTORY_BOUNDARY_BLOCKER" else {"missing_input": "ledger boundary", "reason": "unknown history", "required_return_interface": "controller.review"},
        "return_action": "arbitrary-provider-action",
    }
    value.update(overrides)
    if verdict == "REVISE" and "return_action" not in overrides:
        value["return_action"] = "P08 / ACTION_ID = P08_MAP_CURRENT_PARENT"
    return value


def context():
    return RoutingContext("artifact-1", 3, SHA)


def test_pass_is_gate_candidate_only():
    d = route_review(review(), context())
    assert d.action is RouteAction.GATE_CANDIDATE
    assert not d.author_approval_granted and not d.p09_authorized
    assert not d.formal_write_authorized and not d.publish_authorized


def test_arbitrary_pass_action_is_not_authority():
    assert route_review(review(return_action="PUBLISH_NOW"), context()).action is RouteAction.GATE_CANDIDATE


def test_revise_requires_fresh_chain_and_no_direct_retry():
    d = route_review(review("REVISE"), context())
    assert d.action is RouteAction.RETURN_TO_P08
    assert d.p08a_repersist_required and d.new_revision_required
    assert d.new_sha_binding_required and d.fresh_p08b_required
    assert not d.direct_p08b_retry_allowed


def test_revise_action_contract_is_checked():
    with pytest.raises(RoutingError):
        route_review(review("REVISE", return_action="P08B_RETRY"), context())


def test_blocker_stops_and_preserves_metadata():
    d = route_review(review("HISTORY_BOUNDARY_BLOCKER", return_action="STOP / REQUIRED_RETURN_INTERFACE"), context())
    assert d.action is RouteAction.STOP_BLOCKER and d.stop
    assert d.blocker_details == {"missing_input": "ledger boundary", "reason": "unknown history", "required_return_interface": "controller.review"}
    assert d.return_interface_metadata == "controller.review"
    assert d.return_action == "STOP / REQUIRED_RETURN_INTERFACE"
    assert not d.fallback_progression_allowed
    assert not d.p09_authorized and not d.formal_write_authorized and not d.publish_authorized


def test_arbitrary_blocker_action_is_not_authority():
    with pytest.raises(RoutingError):
        route_review(review("HISTORY_BOUNDARY_BLOCKER", return_action="PUBLISH"), context())


def test_blocker_missing_structured_field_fails_closed():
    payload = review("HISTORY_BOUNDARY_BLOCKER", return_action="STOP / REQUIRED_RETURN_INTERFACE")
    del payload["blocker_details"]["reason"]
    with pytest.raises(RoutingError):
        route_review(payload, context())


@pytest.mark.parametrize("sha", ["b" * 64, "", "A" * 64, "not-a-sha", "a" * 63])
def test_sha_must_match_current_lowercase_exactly(sha):
    with pytest.raises(RoutingError):
        route_review(review(sha=sha), context())


def test_unknown_verdict_fails_closed():
    with pytest.raises(RoutingError):
        route_review(review("UNKNOWN"), context())


def test_malformed_required_fields_fail_closed():
    for key, value in (("summary", ""), ("revision_targets", None), ("return_action", "")):
        payload = review()
        payload[key] = value
        with pytest.raises(RoutingError):
            route_review(payload, context())


def test_idempotent_exact_duplicate_returns_prior_without_advance():
    c = context()
    first = route_review(review(), c)
    replay = route_review(review(), c)
    assert replay.action is first.action
    assert replay.idempotent_replay and not replay.advance_permitted


def test_conflicting_duplicate_is_rejected():
    c = context()
    route_review(review(), c)
    with pytest.raises(RoutingError):
        route_review(review(summary="different"), c)


def test_revision_binding_and_context_validation():
    with pytest.raises(RoutingError):
        route_review(review(), RoutingContext("", 1, SHA))
    with pytest.raises(RoutingError):
        route_review(review(), RoutingContext("artifact", 0, SHA))
    with pytest.raises(RoutingError):
        route_review(review(), RoutingContext("artifact", 1, "A" * 64))


def test_no_forbidden_provider_imports_or_schema_changes():
    source = Path(__file__).parents[1] / "src" / "universal_runtime" / "core" / "routing.py"
    text = source.read_text(encoding="utf-8").lower()
    assert all(name not in text for name in ("maf", "openai", "deepseek"))
    assert hashlib.sha256((Path(__file__).parents[1] / "schemas" / "p08_structure_draft.schema.json").read_bytes()).hexdigest() == "f73e692562d8687def230c950ac184f571aaacf002d57306321584d5410528d6"
    assert hashlib.sha256((Path(__file__).parents[1] / "schemas" / "p08_gate_result.schema.json").read_bytes()).hexdigest() == "91749e80ba20be2ed643c0c36443a64e9dac09af07f06e12c37b78c4043e2cd3"
