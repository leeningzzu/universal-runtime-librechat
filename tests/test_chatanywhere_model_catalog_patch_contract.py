from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT / "patches/librechat/chatanywhere-native-model-catalog-r002.patch"
MANIFEST = ROOT / "patches/librechat/chatanywhere-native-model-catalog-r002.manifest.json"
CONTRACT = ROOT / "docs/PROVIDER_MODEL_CATALOG_CONTRACT.md"
PROMOTION = ROOT / "governance/PROJECT_SOURCE_RUNTIME_DEVELOPMENT_STRATEGY_v0_7_PROMOTION_RECEIPT_R001.md"


def test_chatanywhere_patch_manifest_and_scope() -> None:
    patch = PATCH.read_text(encoding="utf-8")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert hashlib.sha256(PATCH.read_bytes()).hexdigest() == manifest["patch_sha256"]
    assert manifest["compiled_parent_sha256"] == "a9b119a170e7ccc3cd5a61c8943f114048fcdd17d41f37344a83638e249787a7"
    assert manifest["compiled_candidate_sha256"] == "b3956edb6db79e709800216daf57d6400c3fb4fedbacea234be7627bebb5d5a2"
    assert "skipCache: name.toLowerCase() !== 'chatanywhere'" in patch
    assert "timeoutMs: name.toLowerCase() === 'chatanywhere' ? 20000 : 5000" in patch
    assert "Time.TEN_MINUTES" in patch
    assert "OtherUserEndpoint" in patch
    assert manifest["other_provider_change"] is False
    assert manifest["production_image_rebuild"] is False


def test_provider_contract_and_strategy_promotion_are_bound() -> None:
    contract = CONTRACT.read_text(encoding="utf-8")
    receipt = PROMOTION.read_text(encoding="utf-8")
    assert "must not silently narrow the authorized catalogue" in contract
    assert "must not send an inference request" in contract
    assert "PASS_DISPLAY" in contract
    assert "65f704d52f7be1473dfe045924abcbae8c9280a2ddacb81b56c08835bd0fa439" in receipt
    assert "SUPERSEDES = PROJECT_SOURCE_RUNTIME_DEVELOPMENT_STRATEGY_v0_6.md" in receipt
