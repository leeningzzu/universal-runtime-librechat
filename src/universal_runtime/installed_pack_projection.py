from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from universal_runtime.core.job_pins import JobPackPin
from universal_runtime.packs.registry import PackRegistry, PackResolutionError, ResolvedPack


INSTALLED_PACK_LIFECYCLE_CONTRACT = "INSTALLED_PACK_LIFECYCLE_THIN_PROJECTION_R001"
INSTALLED_PACK_CONSUMER_SCOPE_CONTRACT = "INSTALLED_PACK_LIFECYCLE_CONSUMER_SCOPE_R002"
INSTALL_RECEIPT_SCHEMA = "RUNTIME_INSTALLED_PACK_RECEIPT_R001"
UNINSTALL_RECEIPT_SCHEMA = "RUNTIME_UNINSTALLED_PACK_RECEIPT_R002"

_CURRENT_REQUIRED_CONSUMER_KINDS = frozenset({"PROJECT_BINDING", "JOB_PIN"})
_CONDITIONAL_CONSUMER_KINDS = frozenset({"ROLLBACK", "MIGRATION", "NAMED_CONSUMER"})
_ALLOWED_CONSUMER_KINDS = _CURRENT_REQUIRED_CONSUMER_KINDS | _CONDITIONAL_CONSUMER_KINDS
_INSTALL_LOCK = threading.RLock()


class InstalledPackLifecycleError(ValueError):
    """Raised when the machine-local Installed Pack projection fails closed."""


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(ch in "0123456789abcdef" for ch in value)
    )


def _canonical_bytes(payload: dict[str, Any]) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _validate_component(value: str, *, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value in {".", ".."}
        or "/" in value
        or "\\" in value
        or ":" in value
    ):
        raise InstalledPackLifecycleError(f"invalid {field}")
    return value


def _portable_relative(value: str, *, field: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise InstalledPackLifecycleError(f"{field} must be a portable relative locator")
    pure = PurePosixPath(value)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise InstalledPackLifecycleError(f"{field} must be a portable relative locator")
    if ":" in pure.parts[0]:
        raise InstalledPackLifecycleError(f"{field} must not contain a drive or scheme")
    return pure.as_posix()


def _runtime_locator(runtime_root: Path, target: Path, *, field: str) -> str:
    root = runtime_root.resolve()
    resolved = target.resolve()
    try:
        rel = resolved.relative_to(root).as_posix()
    except ValueError as exc:
        raise InstalledPackLifecycleError(f"{field} escapes machine Runtime root") from exc
    return _portable_relative(rel, field=field)


@dataclass(frozen=True)
class InstalledPackRecord:
    pack_id: str
    pack_version: str
    pack_manifest_sha256: str
    pack_content_manifest_sha256: str
    pack_promotion_receipt_sha256: str
    install_receipt_sha256: str
    installed_locator: str

    def to_identity(self) -> tuple[str, str, str, str, str]:
        return (
            self.pack_id,
            self.pack_version,
            self.pack_manifest_sha256,
            self.pack_content_manifest_sha256,
            self.pack_promotion_receipt_sha256,
        )


@dataclass(frozen=True)
class InstalledPackConsumerRef:
    consumer_kind: str
    consumer_id: str
    pack_id: str
    pack_version: str
    pack_manifest_sha256: str
    pack_content_manifest_sha256: str
    pack_promotion_receipt_sha256: str

    def __post_init__(self) -> None:
        if self.consumer_kind not in _ALLOWED_CONSUMER_KINDS:
            raise InstalledPackLifecycleError("unsupported Installed Pack consumer kind")
        if not isinstance(self.consumer_id, str) or not self.consumer_id:
            raise InstalledPackLifecycleError("consumer_id must be non-empty")
        _validate_component(self.pack_id, field="consumer pack_id")
        _validate_component(self.pack_version, field="consumer pack_version")
        for value in (
            self.pack_manifest_sha256,
            self.pack_content_manifest_sha256,
            self.pack_promotion_receipt_sha256,
        ):
            if not _is_sha256(value):
                raise InstalledPackLifecycleError(
                    "consumer Pack identity must use lowercase SHA-256"
                )

    @classmethod
    def from_project_binding(
        cls,
        project_id: str,
        binding: dict[str, str],
    ) -> "InstalledPackConsumerRef":
        required = {
            "pack_id",
            "pack_version",
            "pack_manifest_sha256",
            "pack_content_manifest_sha256",
            "pack_promotion_receipt_sha256",
        }
        if not isinstance(project_id, str) or not project_id:
            raise InstalledPackLifecycleError("project_id must be non-empty")
        if not isinstance(binding, dict) or set(binding) != required:
            raise InstalledPackLifecycleError("Project Pack binding is not exact")
        return cls(
            "PROJECT_BINDING",
            project_id,
            binding["pack_id"],
            binding["pack_version"],
            binding["pack_manifest_sha256"],
            binding["pack_content_manifest_sha256"],
            binding["pack_promotion_receipt_sha256"],
        )

    @classmethod
    def from_job_pin(cls, pin: JobPackPin) -> "InstalledPackConsumerRef":
        if (
            pin.pack_content_manifest_sha256 is None
            or pin.pack_promotion_receipt_sha256 is None
        ):
            raise InstalledPackLifecycleError(
                "Job Pack pin must carry promotion-aware exact identity"
            )
        return cls(
            "JOB_PIN",
            pin.job_id,
            pin.pack_id,
            pin.pack_version,
            pin.pack_manifest_sha256,
            pin.pack_content_manifest_sha256,
            pin.pack_promotion_receipt_sha256,
        )

    @classmethod
    def for_record(
        cls,
        *,
        consumer_kind: str,
        consumer_id: str,
        record: InstalledPackRecord,
    ) -> "InstalledPackConsumerRef":
        return cls(
            consumer_kind,
            consumer_id,
            record.pack_id,
            record.pack_version,
            record.pack_manifest_sha256,
            record.pack_content_manifest_sha256,
            record.pack_promotion_receipt_sha256,
        )

    def matches(self, record: InstalledPackRecord) -> bool:
        return (
            self.pack_id,
            self.pack_version,
            self.pack_manifest_sha256,
            self.pack_content_manifest_sha256,
            self.pack_promotion_receipt_sha256,
        ) == record.to_identity()


@dataclass(frozen=True)
class InstalledPackConditionalAuthorityCheck:
    consumer_kind: str
    producer_id: str
    pack_id: str
    pack_version: str
    pack_manifest_sha256: str
    pack_content_manifest_sha256: str
    pack_promotion_receipt_sha256: str
    consumers: tuple[InstalledPackConsumerRef, ...] = ()
    authority_evidence_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if self.consumer_kind not in _CONDITIONAL_CONSUMER_KINDS:
            raise InstalledPackLifecycleError(
                "conditional authority check must target a conditional consumer kind"
            )
        _validate_component(self.producer_id, field="conditional authority producer_id")
        _validate_component(self.pack_id, field="conditional authority pack_id")
        _validate_component(self.pack_version, field="conditional authority pack_version")
        for value in (
            self.pack_manifest_sha256,
            self.pack_content_manifest_sha256,
            self.pack_promotion_receipt_sha256,
        ):
            if not _is_sha256(value):
                raise InstalledPackLifecycleError(
                    "conditional authority Pack identity must use lowercase SHA-256"
                )
        if not isinstance(self.consumers, tuple):
            raise InstalledPackLifecycleError("conditional authority consumers must be a tuple")
        consumer_ids: set[str] = set()
        for consumer in self.consumers:
            if not isinstance(consumer, InstalledPackConsumerRef):
                raise InstalledPackLifecycleError(
                    "conditional authority consumers must be exact consumer refs"
                )
            if consumer.consumer_kind != self.consumer_kind:
                raise InstalledPackLifecycleError(
                    "conditional authority check consumer kind mismatch"
                )
            if not self.matches_consumer(consumer):
                raise InstalledPackLifecycleError(
                    "conditional authority check consumer Pack identity mismatch"
                )
            if consumer.consumer_id in consumer_ids:
                raise InstalledPackLifecycleError(
                    "conditional authority check contains duplicate consumer_id"
                )
            consumer_ids.add(consumer.consumer_id)
        object.__setattr__(
            self,
            "authority_evidence_sha256",
            _sha256_bytes(_canonical_bytes(self.authority_evidence_payload())),
        )

    @classmethod
    def for_record(
        cls,
        *,
        consumer_kind: str,
        producer_id: str,
        record: InstalledPackRecord,
        consumers: Iterable[InstalledPackConsumerRef] = (),
    ) -> "InstalledPackConditionalAuthorityCheck":
        return cls(
            consumer_kind=consumer_kind,
            producer_id=producer_id,
            pack_id=record.pack_id,
            pack_version=record.pack_version,
            pack_manifest_sha256=record.pack_manifest_sha256,
            pack_content_manifest_sha256=record.pack_content_manifest_sha256,
            pack_promotion_receipt_sha256=record.pack_promotion_receipt_sha256,
            consumers=tuple(consumers),
        )

    def to_identity(self) -> tuple[str, str, str, str, str]:
        return (
            self.pack_id,
            self.pack_version,
            self.pack_manifest_sha256,
            self.pack_content_manifest_sha256,
            self.pack_promotion_receipt_sha256,
        )

    def matches_consumer(self, consumer: InstalledPackConsumerRef) -> bool:
        return (
            consumer.pack_id,
            consumer.pack_version,
            consumer.pack_manifest_sha256,
            consumer.pack_content_manifest_sha256,
            consumer.pack_promotion_receipt_sha256,
        ) == self.to_identity()

    def authority_evidence_payload(self) -> dict[str, Any]:
        return {
            "schema_revision": "RUNTIME_INSTALLED_PACK_CONDITIONAL_AUTHORITY_EVIDENCE_R001",
            "consumer_kind": self.consumer_kind,
            "producer_id": self.producer_id,
            "pack_id": self.pack_id,
            "pack_version": self.pack_version,
            "pack_manifest_sha256": self.pack_manifest_sha256,
            "pack_content_manifest_sha256": self.pack_content_manifest_sha256,
            "pack_promotion_receipt_sha256": self.pack_promotion_receipt_sha256,
            "consumer_ids": sorted(consumer.consumer_id for consumer in self.consumers),
            "exact_consumer_count": len(self.consumers),
        }

    def receipt_summary(self) -> dict[str, Any]:
        return {
            "consumer_kind": self.consumer_kind,
            "producer_id": self.producer_id,
            "authority_evidence_sha256": self.authority_evidence_sha256,
            "exact_consumer_count": len(self.consumers),
        }


@dataclass(frozen=True)
class InstalledPackConsumerSnapshot:
    snapshot_id: str
    pack_id: str
    pack_version: str
    pack_manifest_sha256: str
    pack_content_manifest_sha256: str
    pack_promotion_receipt_sha256: str
    checked_consumer_kinds: tuple[str, ...]
    active_conditional_consumer_kinds: tuple[str, ...] = ()
    conditional_authority_checks: tuple[InstalledPackConditionalAuthorityCheck, ...] = ()
    consumers: tuple[InstalledPackConsumerRef, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.snapshot_id, str) or not self.snapshot_id:
            raise InstalledPackLifecycleError("consumer snapshot_id must be non-empty")
        _validate_component(self.pack_id, field="snapshot pack_id")
        _validate_component(self.pack_version, field="snapshot pack_version")
        for value in (
            self.pack_manifest_sha256,
            self.pack_content_manifest_sha256,
            self.pack_promotion_receipt_sha256,
        ):
            if not _is_sha256(value):
                raise InstalledPackLifecycleError(
                    "consumer snapshot Pack identity must use lowercase SHA-256"
                )
        if len(self.checked_consumer_kinds) != len(_CURRENT_REQUIRED_CONSUMER_KINDS) or set(
            self.checked_consumer_kinds
        ) != _CURRENT_REQUIRED_CONSUMER_KINDS:
            raise InstalledPackLifecycleError(
                "consumer snapshot must prove every current uninstall-blocking consumer class was checked"
            )
        if len(self.active_conditional_consumer_kinds) != len(
            set(self.active_conditional_consumer_kinds)
        ) or not set(self.active_conditional_consumer_kinds).issubset(
            _CONDITIONAL_CONSUMER_KINDS
        ):
            raise InstalledPackLifecycleError("active conditional consumer kinds are invalid")
        checks_by_kind: dict[str, InstalledPackConditionalAuthorityCheck] = {}
        for check in self.conditional_authority_checks:
            if not isinstance(check, InstalledPackConditionalAuthorityCheck):
                raise InstalledPackLifecycleError(
                    "conditional authority checks must use exact check objects"
                )
            if check.consumer_kind in checks_by_kind:
                raise InstalledPackLifecycleError(
                    "conditional consumer kind has more than one authority check"
                )
            checks_by_kind[check.consumer_kind] = check
        if set(checks_by_kind) != set(self.active_conditional_consumer_kinds):
            raise InstalledPackLifecycleError(
                "active conditional consumer capability lacks exact authority check"
            )
        expected = (
            self.pack_id,
            self.pack_version,
            self.pack_manifest_sha256,
            self.pack_content_manifest_sha256,
            self.pack_promotion_receipt_sha256,
        )
        for consumer in self.consumers:
            if consumer.consumer_kind not in _CURRENT_REQUIRED_CONSUMER_KINDS:
                raise InstalledPackLifecycleError(
                    "conditional consumer requires an exact conditional authority check"
                )
            actual = (
                consumer.pack_id,
                consumer.pack_version,
                consumer.pack_manifest_sha256,
                consumer.pack_content_manifest_sha256,
                consumer.pack_promotion_receipt_sha256,
            )
            if actual != expected:
                raise InstalledPackLifecycleError(
                    "consumer snapshot contains a non-target Pack identity"
                )
        for check in self.conditional_authority_checks:
            if check.to_identity() != expected:
                raise InstalledPackLifecycleError(
                    "conditional authority check does not bind the target Pack identity"
                )
            for consumer in check.consumers:
                actual = (
                    consumer.pack_id,
                    consumer.pack_version,
                    consumer.pack_manifest_sha256,
                    consumer.pack_content_manifest_sha256,
                    consumer.pack_promotion_receipt_sha256,
                )
                if actual != expected:
                    raise InstalledPackLifecycleError(
                        "conditional authority check contains a non-target Pack identity"
                    )

    @classmethod
    def for_record(
        cls,
        *,
        snapshot_id: str,
        record: InstalledPackRecord,
        consumers: Iterable[InstalledPackConsumerRef] = (),
        active_conditional_consumer_kinds: Iterable[str] = (),
        conditional_authority_checks: Iterable[InstalledPackConditionalAuthorityCheck] = (),
    ) -> "InstalledPackConsumerSnapshot":
        return cls(
            snapshot_id=snapshot_id,
            pack_id=record.pack_id,
            pack_version=record.pack_version,
            pack_manifest_sha256=record.pack_manifest_sha256,
            pack_content_manifest_sha256=record.pack_content_manifest_sha256,
            pack_promotion_receipt_sha256=record.pack_promotion_receipt_sha256,
            checked_consumer_kinds=tuple(sorted(_CURRENT_REQUIRED_CONSUMER_KINDS)),
            active_conditional_consumer_kinds=tuple(sorted(active_conditional_consumer_kinds)),
            conditional_authority_checks=tuple(conditional_authority_checks),
            consumers=tuple(consumers),
        )

    @property
    def blocking_consumers(self) -> tuple[InstalledPackConsumerRef, ...]:
        conditional = tuple(
            consumer
            for check in self.conditional_authority_checks
            for consumer in check.consumers
        )
        return self.consumers + conditional

    def conditional_receipt_summaries(self) -> list[dict[str, Any]]:
        return [
            check.receipt_summary()
            for check in sorted(
                self.conditional_authority_checks,
                key=lambda item: item.consumer_kind,
            )
        ]

    def matches(self, record: InstalledPackRecord) -> bool:
        return (
            self.pack_id,
            self.pack_version,
            self.pack_manifest_sha256,
            self.pack_content_manifest_sha256,
            self.pack_promotion_receipt_sha256,
        ) == record.to_identity()


class InstalledPackProjection:
    """Versioned machine-local lifecycle state over existing promoted Pack Authority."""

    def __init__(self, runtime_root: Path):
        self.runtime_root = runtime_root.resolve()
        self.installed_root = self.runtime_root / "_installed" / "packs"
        self.receipt_root = self.runtime_root / "_installed" / "receipts"

    def _version_root(self, pack_id: str, pack_version: str) -> Path:
        return (
            self.installed_root
            / _validate_component(pack_id, field="pack_id")
            / _validate_component(pack_version, field="pack_version")
        )

    def _receipt_path(self, pack_id: str, pack_version: str) -> Path:
        return self._version_root(pack_id, pack_version) / "install_receipt.json"

    def _audit_receipt_path(
        self,
        kind: str,
        pack_id: str,
        pack_version: str,
        receipt_sha256: str,
    ) -> Path:
        return (
            self.receipt_root
            / kind
            / _validate_component(pack_id, field="pack_id")
            / _validate_component(pack_version, field="pack_version")
            / f"{receipt_sha256}.json"
        )

    def _install_payload(self, promoted: ResolvedPack) -> dict[str, Any]:
        if (
            promoted.content_manifest_sha256 is None
            or promoted.promotion_receipt_sha256 is None
        ):
            raise InstalledPackLifecycleError("promoted Pack identity is incomplete")
        version_root = self._version_root(promoted.pack_id, promoted.version)
        return {
            "schema_revision": INSTALL_RECEIPT_SCHEMA,
            "lifecycle_contract_revision": INSTALLED_PACK_LIFECYCLE_CONTRACT,
            "persistence_class": "MACHINE_LOCAL_INSTALLED_PROJECTION",
            "source_authority": "RUNTIME_PROMOTED_PACK_AUTHORITY",
            "pack_id": promoted.pack_id,
            "pack_version": promoted.version,
            "pack_manifest_sha256": promoted.manifest_sha256,
            "pack_content_manifest_sha256": promoted.content_manifest_sha256,
            "pack_promotion_receipt_sha256": promoted.promotion_receipt_sha256,
            "installed_locator": _runtime_locator(
                self.runtime_root,
                version_root,
                field="installed_locator",
            ),
            "content_transport_state": "REUSE_PROMOTED_AUTHORITY_CONTENT",
        }

    @staticmethod
    def _record_from_receipt(
        payload: dict[str, Any],
        *,
        receipt_sha256: str,
    ) -> InstalledPackRecord:
        expected = {
            "schema_revision",
            "lifecycle_contract_revision",
            "persistence_class",
            "source_authority",
            "pack_id",
            "pack_version",
            "pack_manifest_sha256",
            "pack_content_manifest_sha256",
            "pack_promotion_receipt_sha256",
            "installed_locator",
            "content_transport_state",
        }
        if not isinstance(payload, dict) or set(payload) != expected:
            raise InstalledPackLifecycleError("install receipt shape mismatch")
        if (
            payload["schema_revision"] != INSTALL_RECEIPT_SCHEMA
            or payload["lifecycle_contract_revision"] != INSTALLED_PACK_LIFECYCLE_CONTRACT
            or payload["persistence_class"] != "MACHINE_LOCAL_INSTALLED_PROJECTION"
            or payload["source_authority"] != "RUNTIME_PROMOTED_PACK_AUTHORITY"
            or payload["content_transport_state"] != "REUSE_PROMOTED_AUTHORITY_CONTENT"
        ):
            raise InstalledPackLifecycleError("install receipt contract mismatch")
        for field in (
            "pack_manifest_sha256",
            "pack_content_manifest_sha256",
            "pack_promotion_receipt_sha256",
            "install_receipt_sha256",
        ):
            value = receipt_sha256 if field == "install_receipt_sha256" else payload[field]
            if not _is_sha256(value):
                raise InstalledPackLifecycleError("install receipt SHA identity is invalid")
        return InstalledPackRecord(
            pack_id=_validate_component(payload["pack_id"], field="pack_id"),
            pack_version=_validate_component(payload["pack_version"], field="pack_version"),
            pack_manifest_sha256=payload["pack_manifest_sha256"],
            pack_content_manifest_sha256=payload["pack_content_manifest_sha256"],
            pack_promotion_receipt_sha256=payload["pack_promotion_receipt_sha256"],
            install_receipt_sha256=receipt_sha256,
            installed_locator=_portable_relative(
                payload["installed_locator"], field="installed_locator"
            ),
        )

    def install_from_promoted(
        self,
        promoted_registry: PackRegistry,
        pack_id: str,
        pack_version: str,
    ) -> dict[str, Any]:
        promoted = promoted_registry.resolve_promoted_pack(pack_id, pack_version)
        payload = self._install_payload(promoted)
        receipt_bytes = _canonical_bytes(payload)
        receipt_sha = _sha256_bytes(receipt_bytes)
        version_root = self._version_root(pack_id, pack_version)

        with _INSTALL_LOCK:
            if version_root.exists():
                current = self.resolve_installed_record(pack_id, pack_version)
                if current.to_identity() != (
                    promoted.pack_id,
                    promoted.version,
                    promoted.manifest_sha256,
                    promoted.content_manifest_sha256,
                    promoted.promotion_receipt_sha256,
                ):
                    raise InstalledPackLifecycleError(
                        "installed Pack identity conflicts with promoted source"
                    )
                return {
                    "action": "NO_OP_ALREADY_INSTALLED",
                    "changed": False,
                    "receipt": payload,
                    "receipt_sha256": receipt_sha,
                    "record": current,
                }

            version_root.parent.mkdir(parents=True, exist_ok=True)
            temp_root = Path(
                tempfile.mkdtemp(
                    prefix=f".{pack_version}.installing-",
                    dir=str(version_root.parent),
                )
            )
            audit_path = self._audit_receipt_path(
                "install", pack_id, pack_version, receipt_sha
            )
            moved_into_place = False
            try:
                (temp_root / "install_receipt.json").write_bytes(receipt_bytes)
                temp_root.replace(version_root)
                moved_into_place = True
                audit_path.parent.mkdir(parents=True, exist_ok=True)
                if audit_path.exists() and audit_path.read_bytes() != receipt_bytes:
                    raise InstalledPackLifecycleError("install audit receipt collision")
                audit_path.write_bytes(receipt_bytes)
            except Exception:
                if temp_root.exists():
                    shutil.rmtree(temp_root, ignore_errors=True)
                if moved_into_place and version_root.exists():
                    shutil.rmtree(version_root, ignore_errors=True)
                raise

        record = self.resolve_installed_record(pack_id, pack_version)
        return {
            "action": "INSTALL",
            "changed": True,
            "receipt": payload,
            "receipt_sha256": receipt_sha,
            "record": record,
        }

    def resolve_installed_record(
        self,
        pack_id: str,
        pack_version: str,
    ) -> InstalledPackRecord:
        version_root = self._version_root(pack_id, pack_version)
        receipt_path = self._receipt_path(pack_id, pack_version)
        if not version_root.is_dir() or not receipt_path.is_file():
            raise InstalledPackLifecycleError(
                f"Pack is not installed: {pack_id}@{pack_version}"
            )
        raw = receipt_path.read_bytes()
        receipt_sha = _sha256_bytes(raw)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise InstalledPackLifecycleError("cannot parse install receipt") from exc
        record = self._record_from_receipt(payload, receipt_sha256=receipt_sha)
        if (
            record.pack_id != pack_id
            or record.pack_version != pack_version
            or record.installed_locator
            != _runtime_locator(
                self.runtime_root, version_root, field="installed_locator"
            )
        ):
            raise InstalledPackLifecycleError("installed Pack receipt identity mismatch")
        audit_path = self._audit_receipt_path(
            "install", pack_id, pack_version, receipt_sha
        )
        if not audit_path.is_file() or audit_path.read_bytes() != raw:
            raise InstalledPackLifecycleError("installed Pack audit receipt mismatch")
        return record

    def list_installed_packs(self) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        if not self.installed_root.exists():
            return rows
        for pack_dir in sorted(
            (item for item in self.installed_root.iterdir() if item.is_dir()),
            key=lambda item: item.name,
        ):
            for version_dir in sorted(
                (item for item in pack_dir.iterdir() if item.is_dir()),
                key=lambda item: item.name,
            ):
                record = self.resolve_installed_record(pack_dir.name, version_dir.name)
                rows.append(
                    {
                        "pack_id": record.pack_id,
                        "pack_version": record.pack_version,
                        "pack_manifest_sha256": record.pack_manifest_sha256,
                        "pack_content_manifest_sha256": record.pack_content_manifest_sha256,
                        "pack_promotion_receipt_sha256": record.pack_promotion_receipt_sha256,
                        "install_receipt_sha256": record.install_receipt_sha256,
                    }
                )
        return rows

    def uninstall(
        self,
        pack_id: str,
        pack_version: str,
        *,
        consumer_snapshot: InstalledPackConsumerSnapshot | None = None,
    ) -> dict[str, Any]:
        with _INSTALL_LOCK:
            version_root = self._version_root(pack_id, pack_version)
            if not version_root.exists():
                return {
                    "action": "NO_OP_ALREADY_UNINSTALLED",
                    "changed": False,
                    "receipt": None,
                    "receipt_sha256": None,
                }
            record = self.resolve_installed_record(pack_id, pack_version)
            if consumer_snapshot is None:
                raise InstalledPackLifecycleError(
                    "complete exact-consumer snapshot is required before uninstall"
                )
            if not consumer_snapshot.matches(record):
                raise InstalledPackLifecycleError(
                    "consumer snapshot does not match exact installed Pack identity"
                )
            blockers = consumer_snapshot.blocking_consumers
            if blockers:
                summary = ", ".join(
                    f"{item.consumer_kind}:{item.consumer_id}"
                    for item in sorted(
                        blockers,
                        key=lambda item: (item.consumer_kind, item.consumer_id),
                    )
                )
                raise InstalledPackLifecycleError(
                    f"cannot uninstall Pack with exact consumers: {summary}"
                )

            payload = {
                "schema_revision": UNINSTALL_RECEIPT_SCHEMA,
                "lifecycle_contract_revision": INSTALLED_PACK_LIFECYCLE_CONTRACT,
                "consumer_scope_contract_revision": INSTALLED_PACK_CONSUMER_SCOPE_CONTRACT,
                "persistence_class": "MACHINE_LOCAL_INSTALL_AUDIT",
                "pack_id": record.pack_id,
                "pack_version": record.pack_version,
                "pack_manifest_sha256": record.pack_manifest_sha256,
                "pack_content_manifest_sha256": record.pack_content_manifest_sha256,
                "pack_promotion_receipt_sha256": record.pack_promotion_receipt_sha256,
                "install_receipt_sha256": record.install_receipt_sha256,
                "removed_installed_locator": record.installed_locator,
                "consumer_snapshot_id": consumer_snapshot.snapshot_id,
                "checked_consumer_kinds": list(consumer_snapshot.checked_consumer_kinds),
                "conditional_reentry_consumer_kinds": sorted(_CONDITIONAL_CONSUMER_KINDS),
                "conditional_consumer_authority_checks": consumer_snapshot.conditional_receipt_summaries(),
                "exact_consumer_count": 0,
            }
            receipt_bytes = _canonical_bytes(payload)
            receipt_sha = _sha256_bytes(receipt_bytes)
            audit_path = self._audit_receipt_path(
                "uninstall", pack_id, pack_version, receipt_sha
            )
            audit_path.parent.mkdir(parents=True, exist_ok=True)
            if audit_path.exists() and audit_path.read_bytes() != receipt_bytes:
                raise InstalledPackLifecycleError("uninstall audit receipt collision")
            audit_path.write_bytes(receipt_bytes)
            shutil.rmtree(version_root)
            pack_dir = version_root.parent
            if pack_dir.is_dir() and not any(pack_dir.iterdir()):
                pack_dir.rmdir()

        return {
            "action": "UNINSTALL",
            "changed": True,
            "receipt": payload,
            "receipt_sha256": receipt_sha,
        }


class InstalledPackBindingResolver:
    """Thin adapter: installed state gates existing promoted Pack resolution."""

    def __init__(
        self,
        projection: InstalledPackProjection,
        promoted_registry: PackRegistry,
    ):
        self.projection = projection
        self.promoted_registry = promoted_registry

    def resolve_promoted_pack(self, pack_id: str, version: str) -> ResolvedPack:
        try:
            record = self.projection.resolve_installed_record(pack_id, version)
        except InstalledPackLifecycleError as exc:
            raise PackResolutionError(str(exc)) from exc
        promoted = self.promoted_registry.resolve_promoted_pack(pack_id, version)
        if record.to_identity() != (
            promoted.pack_id,
            promoted.version,
            promoted.manifest_sha256,
            promoted.content_manifest_sha256,
            promoted.promotion_receipt_sha256,
        ):
            raise PackResolutionError(
                f"Installed Pack identity is stale: {pack_id}@{version}"
            )
        return promoted

    def assert_current(self, resolved_or_pin: ResolvedPack | Any) -> ResolvedPack:
        pack_id = getattr(resolved_or_pin, "pack_id", None)
        version = getattr(resolved_or_pin, "version", None)
        if version is None:
            version = getattr(resolved_or_pin, "pack_version", None)
        if not isinstance(pack_id, str) or not isinstance(version, str):
            raise PackResolutionError("Invalid installed Pack resolution or pin")
        current = self.resolve_promoted_pack(pack_id, version)
        expected_manifest = (
            getattr(resolved_or_pin, "manifest_sha256", None)
            or getattr(resolved_or_pin, "pack_manifest_sha256", None)
        )
        expected_content = (
            getattr(resolved_or_pin, "content_manifest_sha256", None)
            or getattr(resolved_or_pin, "pack_content_manifest_sha256", None)
        )
        expected_promotion = (
            getattr(resolved_or_pin, "promotion_receipt_sha256", None)
            or getattr(resolved_or_pin, "pack_promotion_receipt_sha256", None)
        )
        if current.manifest_sha256 != expected_manifest:
            raise PackResolutionError(f"Stale installed pack.yaml: {pack_id}@{version}")
        if current.content_manifest_sha256 != expected_content:
            raise PackResolutionError(
                f"Stale installed Pack content manifest: {pack_id}@{version}"
            )
        if current.promotion_receipt_sha256 != expected_promotion:
            raise PackResolutionError(
                f"Stale installed Pack promotion identity: {pack_id}@{version}"
            )
        return current
