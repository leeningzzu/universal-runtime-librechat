from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SHA_RE = re.compile(r"^[0-9a-f]{64}$")
MODES = {"STATIC_ACCEPTANCE", "LOCAL_INTEGRATION_ACCEPTANCE", "LIVE_EVIDENCE_ACCEPTANCE", "PROMOTION_READINESS"}


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class ProtectedBinding:
    path: str
    required: bool = True
    expected_sha256: str | None = None
    kind: str = "OTHER"

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ProtectedBinding":
        allowed = {"path", "required", "expected_sha256", "kind"}
        unknown = set(d) - allowed
        if unknown:
            raise ValueError(f"unknown protected binding field(s): {sorted(unknown)}")
        digest = d.get("expected_sha256")
        if digest is not None and not SHA_RE.fullmatch(str(digest)):
            raise ValueError("expected_sha256 must be lowercase 64-hex")
        return cls(str(d["path"]), bool(d.get("required", True)), digest, str(d.get("kind", "OTHER")))


@dataclass(frozen=True)
class ExpectedSkip:
    node_id: str
    platform: str | None = None
    reason_contains: str = ""


@dataclass(frozen=True)
class PytestConfig:
    targeted_args: tuple[str, ...] = ()
    full_args: tuple[str, ...] = ()
    timeout_seconds: float = 300.0


@dataclass(frozen=True)
class AcceptanceSpec:
    spec_version: str
    task_id: str
    mode: str
    project_root: str
    protected_bindings: tuple[ProtectedBinding, ...] = ()
    compile_targets: tuple[str, ...] = ()
    pytest: PytestConfig = field(default_factory=PytestConfig)
    expected_skips: tuple[ExpectedSkip, ...] = ()
    maf_smoke: dict[str, Any] | None = None
    live_evidence_checks: tuple[dict[str, Any], ...] = ()
    artifact_manifest_checks: tuple[dict[str, Any], ...] = ()
    timeout_seconds: float = 300.0
    output_budget: int = 200_000
    report_root: str | None = None
    network_allowed: bool = False
    model_call_allowed: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any], *, source: Path | None = None) -> "AcceptanceSpec":
        allowed = {"spec_version", "task_id", "mode", "project_root", "protected_bindings", "compile_targets", "pytest", "expected_skips", "maf_smoke", "live_evidence_checks", "artifact_manifest_checks", "timeout_seconds", "output_budget", "report_root", "network_allowed", "model_call_allowed"}
        unknown = set(data) - allowed
        if unknown:
            raise ValueError(f"unknown spec field(s): {sorted(unknown)}")
        mode = str(data.get("mode", "STATIC_ACCEPTANCE"))
        if mode not in MODES:
            raise ValueError(f"unsupported mode: {mode}")
        root = data.get("project_root")
        if root is None:
            root = str(source.parent.parent.parent) if source else str(Path.cwd())
        pc = data.get("pytest") or {}
        if not isinstance(pc, dict):
            raise ValueError("pytest must be an object")
        p_allowed = {"targeted_args", "full_args", "timeout_seconds"}
        if set(pc) - p_allowed:
            raise ValueError(f"unknown pytest field(s): {sorted(set(pc)-p_allowed)}")
        skips = []
        for item in data.get("expected_skips", []):
            if set(item) - {"node_id", "platform", "reason_contains"} or "node_id" not in item:
                raise ValueError("invalid expected skip entry")
            skips.append(ExpectedSkip(str(item["node_id"]), item.get("platform"), str(item.get("reason_contains", ""))))
        root_path = Path(str(root))
        if source is not None and not root_path.is_absolute():
            root_path = source.parent / root_path
        return cls(
            str(data.get("spec_version", "1")), str(data["task_id"]), mode, str(root_path.resolve()),
            tuple(ProtectedBinding.from_dict(x) for x in data.get("protected_bindings", [])),
            tuple(map(str, data.get("compile_targets", []))),
            PytestConfig(tuple(map(str, pc.get("targeted_args", []))), tuple(map(str, pc.get("full_args", []))), float(pc.get("timeout_seconds", data.get("timeout_seconds", 300)))),
            tuple(skips), data.get("maf_smoke"), tuple(data.get("live_evidence_checks", [])), tuple(data.get("artifact_manifest_checks", [])),
            float(data.get("timeout_seconds", 300)), int(data.get("output_budget", 200_000)), data.get("report_root"), bool(data.get("network_allowed", False)), bool(data.get("model_call_allowed", False)),
        )

    def as_dict(self) -> dict[str, Any]:
        return {"spec_version": self.spec_version, "task_id": self.task_id, "mode": self.mode, "project_root": self.project_root, "protected_bindings": [b.__dict__ for b in self.protected_bindings], "compile_targets": list(self.compile_targets), "pytest": {"targeted_args": list(self.pytest.targeted_args), "full_args": list(self.pytest.full_args), "timeout_seconds": self.pytest.timeout_seconds}, "expected_skips": [s.__dict__ for s in self.expected_skips], "maf_smoke": self.maf_smoke, "live_evidence_checks": list(self.live_evidence_checks), "artifact_manifest_checks": list(self.artifact_manifest_checks), "timeout_seconds": self.timeout_seconds, "output_budget": self.output_budget, "report_root": self.report_root, "network_allowed": self.network_allowed, "model_call_allowed": self.model_call_allowed}


@dataclass
class AcceptanceReport:
    data: dict[str, Any]
    def to_dict(self) -> dict[str, Any]: return self.data
    def canonical_bytes(self) -> bytes: return canonical_json(self.data)


def load_spec(path: str | Path) -> AcceptanceSpec:
    p = Path(path).resolve()
    return AcceptanceSpec.from_dict(json.loads(p.read_text(encoding="utf-8")), source=p)
