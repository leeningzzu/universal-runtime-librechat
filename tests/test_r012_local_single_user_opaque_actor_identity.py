from __future__ import annotations

import json
import re

import pytest

import universal_runtime.core.human_decision_authority as hda_module
from universal_runtime.core.artifact_store import ArtifactStore
from universal_runtime.core.hashing import sha256_bytes
from universal_runtime.core.human_decision_authority import (
    HumanDecisionAuthority,
    HumanDecisionAuthorityError,
)
from universal_runtime.core.job_authority import JobAuthorityRegistry


def _human(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts")
    authority = tmp_path / "authority"
    job = JobAuthorityRegistry(authority, store)
    return HumanDecisionAuthority(authority, store, job), authority


def test_r012_local_actor_identity_mints_once_replays_and_has_explicit_ceiling(tmp_path, monkeypatch):
    human, authority = _human(tmp_path)
    calls = []

    def fake_urandom(n: int) -> bytes:
        calls.append(n)
        return b"\xa5" * n

    monkeypatch.setattr(hda_module.os, "urandom", fake_urandom)

    first = human.load_or_mint_local_single_user_opaque_actor_identity_v1()
    second = human.load_or_mint_local_single_user_opaque_actor_identity_v1()
    exact = human.load_exact_local_single_user_opaque_actor_identity_v1()

    expected = sha256_bytes(
        b"RUNTIME_LOCAL_SINGLE_USER_OPAQUE_ACTOR_IDENTITY_V1\x00" + b"\xa5" * 32
    )

    assert calls[0] == 32
    assert calls.count(32) == 1
    assert first == second == exact
    assert first["actor_authority_identity_sha256"] == expected
    assert re.fullmatch(r"[0-9a-f]{64}", expected)
    assert first["identity_class"] == "LOCAL_SINGLE_USER_OPAQUE"
    assert first["use_scope"] == "EXPLICIT_HUMAN_DECISION_ACTION_IDENTITY_BINDING_ONLY"
    assert first["derivation_class"] == "RUNTIME_RANDOM_LOCAL_OPAQUE_NOT_PERSONAL_DATA_DERIVED"
    assert first["represents_real_person_identity"] is False
    assert first["provides_authentication"] is False
    assert first["provides_authorization"] is False
    assert first["grants_permission"] is False

    path = (
        authority
        / "_authoritative"
        / "human_decision_authority"
        / "actor_identities"
        / "local_single_user_v1.json"
    )
    raw = path.read_bytes()
    parsed = json.loads(raw.decode("utf-8"))
    canonical = json.dumps(
        parsed,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    assert raw == canonical

    forbidden_keys = {
        "name", "email", "username", "chat_id", "project_id", "os_account",
        "runtime_execution_identity", "authentication_token", "permission",
    }
    assert forbidden_keys.isdisjoint(parsed)


def test_r012_local_actor_identity_corrupt_semantic_ceiling_fails_closed(tmp_path, monkeypatch):
    human, authority = _human(tmp_path)
    monkeypatch.setattr(hda_module.os, "urandom", lambda n: b"\x11" * n)
    human.load_or_mint_local_single_user_opaque_actor_identity_v1()

    path = (
        authority
        / "_authoritative"
        / "human_decision_authority"
        / "actor_identities"
        / "local_single_user_v1.json"
    )
    parsed = json.loads(path.read_text(encoding="utf-8"))
    parsed["provides_authentication"] = True
    path.write_text(
        json.dumps(
            parsed,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ),
        encoding="utf-8",
        newline="",
    )

    with pytest.raises(HumanDecisionAuthorityError, match="semantic ceiling mismatch"):
        human.load_exact_local_single_user_opaque_actor_identity_v1()
