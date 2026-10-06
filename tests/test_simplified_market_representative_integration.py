"""Cross-domain representative integration: existing Market Pack + frozen Runtime contracts."""

from __future__ import annotations

from dataclasses import asdict
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

from universal_runtime.core.artifact_store import ArtifactStore
from universal_runtime.core.job_permissions import JobFilesystemPermissionPlan
from universal_runtime.core.job_pins import JobPackPin, JobRuntimeContractPin
from universal_runtime.core.load_plan import LoadInput, LoadPlan
from universal_runtime.packs.registry import PackRegistry


ROOT = Path(__file__).parents[1]
PACKS = ROOT / "packs"
PACK_ROOT = PACKS / "simplified_market_reference"
FIXTURE_ROOT = PACK_ROOT / "fixtures"
CSV_PATH = FIXTURE_ROOT / "sample_ohlcv.csv"
EXECUTOR_PATH = PACK_ROOT / "scripts" / "macd_divergence.py"
RUNTIME_CONTRACT_MANIFEST = ROOT / "schemas" / "runtime_contract_manifest.json"

EXPECTED_PACK_MANIFEST_SHA256 = "906d0f9092c2dcfc837774fe46a3b9ae1b71312f160551f4a70e2b6860b8b0d0"
EXPECTED_INPUT_SHA256 = "d3879f1fab8b8c076ddc4cbc6a1ce2e97c16a810548c6783a4fc848b034dd14e"
EXPECTED_EXECUTOR_SHA256 = "8d900f25f8d64e0d3090f8970af7dff1a65ab78d6ce52bf0e108b7b7c995872e"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_market_module():
    spec = importlib.util.spec_from_file_location("simplified_market_representative_macd", EXECUTOR_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_simplified_market_reuses_runtime_contracts_without_core_extension(tmp_path: Path) -> None:
    job_id = "simplified-market-representative-v0"

    registry = PackRegistry(PACKS)
    resolved = registry.resolve_pack("simplified_market_reference", "0.1.0")
    assert resolved.manifest_sha256 == EXPECTED_PACK_MANIFEST_SHA256

    pack_pin = JobPackPin.from_resolved_pack(job_id, resolved)
    assert pack_pin.assert_current(registry).manifest_sha256 == EXPECTED_PACK_MANIFEST_SHA256

    runtime_pin = JobRuntimeContractPin.from_manifest(job_id, RUNTIME_CONTRACT_MANIFEST)
    assert runtime_pin.assert_current(RUNTIME_CONTRACT_MANIFEST) == runtime_pin.runtime_contract_manifest_sha256

    input_sha256 = _sha256(CSV_PATH)
    executor_sha256 = _sha256(EXECUTOR_PATH)
    assert input_sha256 == EXPECTED_INPUT_SHA256
    assert executor_sha256 == EXPECTED_EXECUTOR_SHA256

    permission = JobFilesystemPermissionPlan.from_job_pin(pack_pin, [FIXTURE_ROOT])
    permission.require_read(CSV_PATH)

    load_plan = LoadPlan.from_inputs(
        plan_id="simplified-market-representative-v0-load",
        project_root=str(PACK_ROOT),
        allowed_roots=(str(FIXTURE_ROOT),),
        required_inputs=(
            LoadInput(
                reference="fixtures/sample_ohlcv.csv",
                role="market_ohlcv_fixture",
                expected_sha256=input_sha256,
            ),
        ),
        execution_budget=1,
        load_budget=CSV_PATH.stat().st_size,
    )
    authorized = permission.authorize_load_plan(pack_pin, load_plan)
    assert authorized.permission_plan_sha256 == permission.fingerprint()
    assert authorized.load_plan.required_inputs[0].expected_sha256 == input_sha256

    market = _load_market_module()
    signal = market.detect_bottom_divergence(market.load_close(CSV_PATH))
    assert asdict(signal) == {
        "status": "CONFIRMED",
        "first_index": 28,
        "second_index": 40,
        "reason": "Price lower low with DIF higher low",
    }

    result_text = json.dumps(
        asdict(signal),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ) + "\n"

    provenance = {
        "input_sha256": input_sha256,
        "executor_sha256": executor_sha256,
        "pack_manifest_sha256": pack_pin.pack_manifest_sha256,
        "runtime_contract_manifest_sha256": runtime_pin.runtime_contract_manifest_sha256,
        "permission_plan_sha256": authorized.permission_plan_sha256,
        "load_plan_sha256": authorized.load_plan_sha256,
    }
    input_fingerprint = hashlib.sha256(
        json.dumps(provenance, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    store = ArtifactStore(tmp_path / "artifacts")
    artifact = store.persist_exact_text(
        artifact_id="SIMPLIFIED_MARKET_REPRESENTATIVE_SIGNAL",
        relative_path="market/signal.json",
        text=result_text,
        job_id=job_id,
        input_fingerprint=input_fingerprint,
        metadata=provenance,
    )

    assert artifact.revision == 1
    assert artifact.sha256 == hashlib.sha256(result_text.encode("utf-8")).hexdigest()
    assert artifact.input_fingerprint == input_fingerprint
    assert artifact.metadata == provenance
    assert Path(artifact.path).read_bytes() == result_text.encode("utf-8")

    persisted_manifest = json.loads(
        store.manifest_path(artifact.artifact_id, artifact.revision).read_text(encoding="utf-8")
    )
    assert persisted_manifest["sha256"] == artifact.sha256
    assert persisted_manifest["job_id"] == job_id
    assert persisted_manifest["metadata"] == provenance
