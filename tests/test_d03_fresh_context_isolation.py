import hashlib
from pathlib import Path

import pytest

from universal_runtime.core.enums import PersistenceClass
from universal_runtime.core.fresh_context import (
    FreshContextInput,
    FreshContextRequest,
    ProvenanceClass,
    authorize_fresh_context,
)


def _make(tmp_path: Path, name: str = "authority.md", data: bytes = b"formal authority\n"):
    path = tmp_path / name
    path.write_bytes(data)
    return path, hashlib.sha256(data).hexdigest()


def _request(tmp_path: Path, path: Path, digest: str, **kwargs):
    item = FreshContextInput(
        reference=path, role="authority", provenance=ProvenanceClass.FORMAL_AUTHORITY,
        expected_sha256=digest, parse_mode="markdown", persistence_class=PersistenceClass.AUTHORITATIVE,
    )
    return FreshContextRequest(inputs=(item,), project_root=tmp_path, allowed_roots=(tmp_path,), **kwargs)


def test_valid_persisted_input_and_new_execution_context(tmp_path):
    path, digest = _make(tmp_path)
    first = authorize_fresh_context(_request(tmp_path, path, digest, execution_id="runtime-exec-1"))
    second = authorize_fresh_context(_request(tmp_path, path, digest, execution_id="runtime-exec-2"))
    assert first.authorized and second.authorized
    assert first.plan and second.plan
    assert first.plan.execution_id != second.plan.execution_id
    assert first.fingerprint != second.fingerprint
    assert first.plan.network_allowed is False


@pytest.mark.parametrize("flag", [
    "inherits_p08_session", "inherits_previous_p08b_session", "inherits_controller_chat",
    "inherits_debug_chat", "inherits_checkpoint_conversation", "inherits_model_thread_history",
    "inherits_session", "inherits_thread", "inherits_conversation",
])
def test_any_history_inheritance_is_rejected(tmp_path, flag):
    path, digest = _make(tmp_path)
    result = authorize_fresh_context(_request(tmp_path, path, digest, **{flag: True}))
    assert not result.authorized


@pytest.mark.parametrize("provenance", [
    ProvenanceClass.PRIVATE_REASONING, ProvenanceClass.SELF_EVALUATION,
    ProvenanceClass.DEBUG_TRANSCRIPT, ProvenanceClass.UNPERSISTED_DRAFT,
    ProvenanceClass.SECRET, ProvenanceClass.UNTRUSTED_DISCOVERY,
    ProvenanceClass.SESSION_HISTORY, "not-a-provenance",
])
def test_forbidden_or_unknown_provenance_is_rejected(tmp_path, provenance):
    path, digest = _make(tmp_path)
    item = FreshContextInput(reference=path, role="x", provenance=provenance, expected_sha256=digest)
    result = authorize_fresh_context(FreshContextRequest(inputs=(item,), project_root=tmp_path, allowed_roots=(tmp_path,)))
    assert not result.authorized


def test_previous_result_and_model_network_request_rejected(tmp_path):
    path, digest = _make(tmp_path)
    result = authorize_fresh_context(_request(tmp_path, path, digest, previous_p08b_result={"verdict": "PASS"}))
    assert not result.authorized
    result = authorize_fresh_context(_request(tmp_path, path, digest, model_requested_network=True))
    assert not result.authorized


def test_env_path_rejected_without_reading_contents(tmp_path):
    path, digest = _make(tmp_path, ".env")
    result = authorize_fresh_context(_request(tmp_path, path, digest))
    assert not result.authorized


def test_optional_discovered_file_not_in_plan(tmp_path):
    path, digest = _make(tmp_path)
    optional, optional_digest = _make(tmp_path, "discovered.md", b"discovered")
    result = authorize_fresh_context(_request(tmp_path, path, digest))
    assert result.authorized
    assert all(str(optional.resolve()) != item.reference for item in result.plan.inputs)


@pytest.mark.parametrize("sha", ["A" * 64, "0" * 63, "not-a-sha"])
def test_invalid_sha_rejected(tmp_path, sha):
    path, _ = _make(tmp_path)
    assert not authorize_fresh_context(_request(tmp_path, path, sha)).authorized


def test_wrong_and_stale_sha_rejected(tmp_path):
    path, digest = _make(tmp_path)
    assert authorize_fresh_context(_request(tmp_path, path, digest)).authorized
    path.write_bytes(b"revised")
    assert not authorize_fresh_context(_request(tmp_path, path, digest)).authorized


def test_outside_root_rejected(tmp_path):
    root = tmp_path / "root"; root.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_bytes(b"outside")
    digest = hashlib.sha256(outside.read_bytes()).hexdigest()
    item = FreshContextInput(reference=outside, role="x", provenance=ProvenanceClass.FORMAL_AUTHORITY, expected_sha256=digest)
    result = authorize_fresh_context(FreshContextRequest(inputs=(item,), project_root=root, allowed_roots=(root,)))
    assert not result.authorized


def test_semantic_blacklist_not_used(tmp_path):
    path, digest = _make(tmp_path, data=b"debug reasoning draft are ordinary words")
    assert authorize_fresh_context(_request(tmp_path, path, digest)).authorized
    path2, digest2 = _make(tmp_path, "private.md", b"ordinary")
    item = FreshContextInput(reference=path2, role="x", provenance=ProvenanceClass.PRIVATE_REASONING, expected_sha256=digest2)
    assert not authorize_fresh_context(FreshContextRequest(inputs=(item,), project_root=tmp_path, allowed_roots=(tmp_path,))).authorized


def test_fingerprint_deterministic_and_sha_bound(tmp_path):
    path, digest = _make(tmp_path)
    a = authorize_fresh_context(_request(tmp_path, path, digest, execution_id="same"))
    b = authorize_fresh_context(_request(tmp_path, path, digest, execution_id="same"))
    assert a.fingerprint == b.fingerprint
    other, other_digest = _make(tmp_path, "other.md", b"other")
    c = authorize_fresh_context(_request(tmp_path, other, other_digest, execution_id="same"))
    assert a.fingerprint != c.fingerprint


def test_model_cannot_self_grant_provenance_or_network(tmp_path):
    path, digest = _make(tmp_path)
    item = FreshContextInput(reference=path, role="x", provenance="MODEL_GRANTED", expected_sha256=digest)
    result = authorize_fresh_context(FreshContextRequest(inputs=(item,), project_root=tmp_path, allowed_roots=(tmp_path,), network_allowed=True))
    assert not result.authorized
