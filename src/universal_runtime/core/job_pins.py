from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
from pathlib import Path
import re
from typing import Any

from universal_runtime.packs.registry import PackRegistry, PackResolutionError, ResolvedPack


class JobPinError(ValueError):
    """Raised when an immutable Job execution pin cannot be created or checked."""


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _exact_file_sha256(path: str | Path) -> str:
    target = Path(path)
    if not target.is_file():
        raise JobPinError(f"Runtime contract manifest not found: {target}")
    return hashlib.sha256(target.read_bytes()).hexdigest()


@dataclass(frozen=True)
class JobPackPin:
    job_id: str
    pack_id: str
    pack_version: str
    pack_manifest_sha256: str
    pack_content_manifest_sha256: str | None = None
    pack_promotion_receipt_sha256: str | None = None

    def __post_init__(self) -> None:
        if (self.pack_content_manifest_sha256 is None) != (self.pack_promotion_receipt_sha256 is None):
            raise JobPinError('promotion-aware Pack pin fields must be present together')
        for field in ('pack_content_manifest_sha256', 'pack_promotion_receipt_sha256'):
            value = getattr(self, field)
            if value is not None and (not isinstance(value, str) or not _SHA256_RE.fullmatch(value)):
                raise JobPinError(f'{field} must be lowercase 64-hex SHA-256')

    @classmethod
    def from_resolved_pack(cls, job_id: str, pack: ResolvedPack) -> 'JobPackPin':
        if not isinstance(job_id, str) or not job_id:
            raise JobPinError('job_id must be a non-empty string')
        return cls(
            job_id, pack.pack_id, pack.version, pack.manifest_sha256,
            pack.content_manifest_sha256, pack.promotion_receipt_sha256,
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        return {key: value for key, value in data.items() if value is not None}

    def assert_current(self, registry: PackRegistry) -> ResolvedPack:
        try:
            return registry.assert_current(self)
        except PackResolutionError as exc:
            raise JobPinError(str(exc)) from exc


@dataclass(frozen=True)
class JobRuntimeContractPin:
    job_id: str
    runtime_contract_manifest_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.job_id, str) or not self.job_id:
            raise JobPinError('job_id must be a non-empty string')
        if not isinstance(self.runtime_contract_manifest_sha256, str) or not _SHA256_RE.fullmatch(
            self.runtime_contract_manifest_sha256
        ):
            raise JobPinError('runtime_contract_manifest_sha256 must be lowercase 64-hex SHA-256')

    @classmethod
    def from_manifest(cls, job_id: str, manifest_path: str | Path) -> 'JobRuntimeContractPin':
        return cls(job_id, _exact_file_sha256(manifest_path))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def assert_current(self, manifest_path: str | Path) -> str:
        current = _exact_file_sha256(manifest_path)
        if current != self.runtime_contract_manifest_sha256:
            raise JobPinError(
                'Runtime contract manifest is stale for this Job: '
                f'pinned={self.runtime_contract_manifest_sha256} current={current}'
            )
        return current
