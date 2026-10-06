from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

import yaml

from universal_runtime.core.pack_promotion import PackPromotionError, validate_committed_promoted_pack


class PackResolutionError(ValueError):
    """Raised when a pack cannot be resolved to one authoritative manifest."""


def _freeze_metadata(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze_metadata(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze_metadata(item) for item in value)
    return value


@dataclass(frozen=True)
class ResolvedPack:
    pack_id: str
    version: str
    manifest_sha256: str
    manifest_path: str
    manifest: Mapping[str, Any]
    content_manifest_sha256: str | None = None
    promotion_receipt_sha256: str | None = None
    content_root: str | None = None


class PackRegistry:
    def __init__(self, packs_root: Path):
        self.packs_root = packs_root.resolve()
        self.runtime_root = self.packs_root.parent
        self.authoritative_packs_root = self.runtime_root / '_authoritative' / 'packs'

    def list_packs(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        if not self.packs_root.exists():
            return result
        for manifest in sorted(self.packs_root.glob('*/pack.yaml')):
            data = yaml.safe_load(manifest.read_text(encoding='utf-8')) or {}
            data['_manifest_path'] = str(manifest)
            result.append(data)
        return result

    def list_promoted_packs(self) -> list[dict[str, Any]]:
        """Project the Runtime-promoted Pack catalog without changing legacy list_packs semantics."""
        result: list[dict[str, Any]] = []
        if not self.authoritative_packs_root.exists():
            return result
        for pack_dir in sorted(
            (item for item in self.authoritative_packs_root.iterdir() if item.is_dir()),
            key=lambda item: item.name,
        ):
            for version_dir in sorted(
                (item for item in pack_dir.iterdir() if item.is_dir()),
                key=lambda item: item.name,
            ):
                resolved = self.resolve_promoted_pack(pack_dir.name, version_dir.name)
                purpose = resolved.manifest.get('purpose', '')
                capabilities = resolved.manifest.get('capabilities')
                if not isinstance(purpose, str):
                    raise PackResolutionError(
                        f'Promoted Pack purpose must be text: {resolved.pack_id}@{resolved.version}'
                    )
                if not isinstance(capabilities, tuple) or not all(
                    isinstance(item, str) and item for item in capabilities
                ):
                    raise PackResolutionError(
                        f'Promoted Pack capabilities must be non-empty text items: '
                        f'{resolved.pack_id}@{resolved.version}'
                    )
                if (
                    not isinstance(resolved.content_manifest_sha256, str)
                    or not isinstance(resolved.promotion_receipt_sha256, str)
                ):
                    raise PackResolutionError(
                        f'Promoted Pack Authority identity is incomplete: '
                        f'{resolved.pack_id}@{resolved.version}'
                    )
                result.append(
                    {
                        'pack_id': resolved.pack_id,
                        'version': resolved.version,
                        'promotion_status': 'PROMOTED',
                        'purpose': purpose,
                        'capabilities': list(capabilities),
                        'manifest_sha256': resolved.manifest_sha256,
                        'content_manifest_sha256': resolved.content_manifest_sha256,
                        'promotion_receipt_sha256': resolved.promotion_receipt_sha256,
                    }
                )
        return result

    @staticmethod
    def _validated_manifest(path: Path) -> tuple[bytes, dict[str, Any]]:
        try:
            raw = path.read_bytes()
            data = yaml.safe_load(raw)
        except (OSError, UnicodeError, yaml.YAMLError) as exc:
            raise PackResolutionError(f'Cannot read or parse pack manifest: {path}') from exc
        if not isinstance(data, dict):
            raise PackResolutionError(f'Pack manifest must be a mapping: {path}')
        required_types = {
            'pack_id': str,
            'version': str,
            'status': str,
            'capabilities': list,
            'permissions': dict,
        }
        for field, expected_type in required_types.items():
            if field not in data or not isinstance(data[field], expected_type):
                raise PackResolutionError(f'Invalid pack manifest field {field!r}: {path}')
        return raw, data

    def resolve_pack(self, pack_id: str, version: str) -> ResolvedPack:
        """Resolve one exact pack identity from the configured packs root."""
        matches: list[tuple[Path, bytes, dict[str, Any]]] = []
        if not self.packs_root.exists():
            raise PackResolutionError(f'Pack not found: {pack_id}@{version}')
        for path in sorted(self.packs_root.glob('*/pack.yaml')):
            raw, manifest = self._validated_manifest(path)
            if manifest['pack_id'] == pack_id and manifest['version'] == version:
                matches.append((path, raw, manifest))
        if not matches:
            raise PackResolutionError(f'Pack not found: {pack_id}@{version}')
        if len(matches) > 1:
            raise PackResolutionError(f'Duplicate pack identity: {pack_id}@{version}')
        path, raw, manifest = matches[0]
        return ResolvedPack(
            pack_id=pack_id,
            version=version,
            manifest_sha256=hashlib.sha256(raw).hexdigest(),
            manifest_path=str(path),
            manifest=_freeze_metadata(manifest),
        )

    def resolve_promoted_pack(self, pack_id: str, version: str) -> ResolvedPack:
        """Resolve one exact Runtime-promoted Pack without interpreting pack.yaml.status."""
        try:
            record = validate_committed_promoted_pack(
                self.runtime_root,
                pack_id,
                version,
            )
        except PackPromotionError as exc:
            raise PackResolutionError(f'Cannot resolve promoted Pack: {pack_id}@{version}: {exc}') from exc
        manifest_path = Path(record['pack_yaml_path'])
        raw, manifest = self._validated_manifest(manifest_path)
        manifest_sha = hashlib.sha256(raw).hexdigest()
        if manifest['pack_id'] != pack_id or manifest['version'] != version:
            raise PackResolutionError(f'Promoted pack.yaml identity mismatch: {pack_id}@{version}')
        if manifest_sha != record['pack_yaml_sha256']:
            raise PackResolutionError(f'Promoted pack.yaml SHA mismatch: {pack_id}@{version}')
        return ResolvedPack(
            pack_id=pack_id,
            version=version,
            manifest_sha256=manifest_sha,
            manifest_path=str(manifest_path),
            manifest=_freeze_metadata(manifest),
            content_manifest_sha256=record['content_manifest_sha256'],
            promotion_receipt_sha256=record['promotion_receipt_sha256'],
            content_root=record['content_root'],
        )

    def assert_current(self, resolved_or_pin: ResolvedPack | Any) -> ResolvedPack:
        """Re-resolve a prior pack resolution or JobPackPin and reject stale bytes."""
        pack_id = getattr(resolved_or_pin, 'pack_id', None)
        version = getattr(resolved_or_pin, 'version', None)
        if version is None:
            version = getattr(resolved_or_pin, 'pack_version', None)
        expected_sha = getattr(resolved_or_pin, 'manifest_sha256', None)
        if expected_sha is None:
            expected_sha = getattr(resolved_or_pin, 'pack_manifest_sha256', None)
        expected_content_sha = getattr(resolved_or_pin, 'content_manifest_sha256', None)
        if expected_content_sha is None:
            expected_content_sha = getattr(resolved_or_pin, 'pack_content_manifest_sha256', None)
        expected_receipt_sha = getattr(resolved_or_pin, 'promotion_receipt_sha256', None)
        if expected_receipt_sha is None:
            expected_receipt_sha = getattr(resolved_or_pin, 'pack_promotion_receipt_sha256', None)
        if not all(isinstance(value, str) for value in (pack_id, version, expected_sha)):
            raise PackResolutionError('Invalid pack resolution or pin')
        if (expected_content_sha is None) != (expected_receipt_sha is None):
            raise PackResolutionError('Promotion-aware Pack identity is incomplete')
        if expected_content_sha is not None:
            if not isinstance(expected_content_sha, str) or not isinstance(expected_receipt_sha, str):
                raise PackResolutionError('Invalid promotion-aware Pack identity')
            current = self.resolve_promoted_pack(pack_id, version)
            if current.manifest_sha256 != expected_sha:
                raise PackResolutionError(f'Stale promoted pack.yaml: {pack_id}@{version}')
            if current.content_manifest_sha256 != expected_content_sha:
                raise PackResolutionError(f'Stale promoted Pack content manifest: {pack_id}@{version}')
            if current.promotion_receipt_sha256 != expected_receipt_sha:
                raise PackResolutionError(f'Stale promoted Pack receipt: {pack_id}@{version}')
            return current
        current = self.resolve_pack(pack_id, version)
        if current.manifest_sha256 != expected_sha:
            raise PackResolutionError(f'Stale pack manifest: {pack_id}@{version}')
        return current
