from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re


class JobPinError(ValueError):
    """Raised when an exact Job capability/runtime pin is invalid or stale."""


_LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")


def _label(value: str, field: str) -> str:
    if not isinstance(value, str) or _LABEL_RE.fullmatch(value) is None:
        raise JobPinError(f"invalid {field}")
    return value


def _sha(value: str, field: str) -> str:
    if not isinstance(value, str) or _SHA_RE.fullmatch(value) is None:
        raise JobPinError(f"invalid {field}")
    return value


def _file_sha(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise JobPinError(f"capability manifest unavailable: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True)
class JobCapabilityPin:
    job_id: str
    capability_id: str
    capability_revision: str
    capability_manifest_sha256: str

    def __post_init__(self) -> None:
        _label(self.job_id, "job_id")
        _label(self.capability_id, "capability_id")
        _label(self.capability_revision, "capability_revision")
        _sha(self.capability_manifest_sha256, "capability_manifest_sha256")

    @classmethod
    def from_manifest(cls, *, job_id: str, manifest_path: Path) -> "JobCapabilityPin":
        path = Path(manifest_path)
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise JobPinError("capability manifest is not readable canonical JSON") from exc
        if record.get("schema") != "UR_CORE_CAPABILITY_MANIFEST_V1":
            raise JobPinError("capability manifest schema mismatch")
        return cls(
            job_id=job_id,
            capability_id=_label(record.get("capability_id"), "capability_id"),
            capability_revision=_label(record.get("capability_revision"), "capability_revision"),
            capability_manifest_sha256=_file_sha(path),
        )

    def assert_current(self, manifest_path: Path) -> None:
        current = JobCapabilityPin.from_manifest(job_id=self.job_id, manifest_path=manifest_path)
        if current != self:
            raise JobPinError("capability pin no longer matches exact manifest")

    def to_dict(self) -> dict[str, str]:
        return {
            "job_id": self.job_id,
            "capability_id": self.capability_id,
            "capability_revision": self.capability_revision,
            "capability_manifest_sha256": self.capability_manifest_sha256,
        }


@dataclass(frozen=True)
class JobRuntimeContractPin:
    job_id: str
    runtime_contract_manifest_sha256: str

    def __post_init__(self) -> None:
        _label(self.job_id, "job_id")
        _sha(self.runtime_contract_manifest_sha256, "runtime_contract_manifest_sha256")

    def to_dict(self) -> dict[str, str]:
        return {
            "job_id": self.job_id,
            "runtime_contract_manifest_sha256": self.runtime_contract_manifest_sha256,
        }
