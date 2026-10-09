from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from universal_runtime.core.formal_model_job import FormalModelJobLedger
from universal_runtime.core.job_authority import JobAuthorityRegistry
from universal_runtime.web_continuity import WebContinuityService

if __package__:
    from .running_job_currentness import (
        RunningJobCurrentnessError,
        RunningJobPinCurrentnessProjector,
    )
    from .installed_pack_projection import (
        InstalledPackConditionalAuthorityCheck,
        InstalledPackConsumerRef,
        InstalledPackConsumerSnapshot,
        InstalledPackProjection,
        InstalledPackRecord,
    )
else:
    from running_job_currentness import (
        RunningJobCurrentnessError,
        RunningJobPinCurrentnessProjector,
    )
    from installed_pack_projection import (
        InstalledPackConditionalAuthorityCheck,
        InstalledPackConsumerRef,
        InstalledPackConsumerSnapshot,
        InstalledPackProjection,
        InstalledPackRecord,
    )


RUNTIME_CONSUMER_PROJECTION_CONTRACT = "INSTALLED_PACK_RUNTIME_CONSUMER_PROJECTION_R002"


class RuntimeInstalledPackConsumerProjectionError(ValueError):
    """Fail-closed error for the isolated Runtime consumer projection seam."""


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _is_reparse_or_symlink(path: Path) -> bool:
    try:
        if path.is_symlink():
            return True
        info = os.lstat(path)
    except OSError as exc:
        raise RuntimeInstalledPackConsumerProjectionError(
            f"cannot inspect authority path: {path}"
        ) from exc
    attrs = getattr(info, "st_file_attributes", 0)
    return bool(attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _target_identity(record: InstalledPackRecord) -> dict[str, str]:
    return {
        "pack_id": record.pack_id,
        "pack_version": record.pack_version,
        "pack_manifest_sha256": record.pack_manifest_sha256,
        "pack_content_manifest_sha256": record.pack_content_manifest_sha256,
        "pack_promotion_receipt_sha256": record.pack_promotion_receipt_sha256,
    }


@dataclass(frozen=True)
class RuntimeInstalledPackConsumerProjection:
    snapshot: InstalledPackConsumerSnapshot
    project_authority_evidence_sha256: str
    job_pin_authority_evidence_sha256: str
    aggregate_authority_evidence_sha256: str

    def to_receipt(self) -> dict[str, Any]:
        return {
            "schema_revision": RUNTIME_CONSUMER_PROJECTION_CONTRACT,
            "pack_id": self.snapshot.pack_id,
            "pack_version": self.snapshot.pack_version,
            "pack_manifest_sha256": self.snapshot.pack_manifest_sha256,
            "pack_content_manifest_sha256": self.snapshot.pack_content_manifest_sha256,
            "pack_promotion_receipt_sha256": self.snapshot.pack_promotion_receipt_sha256,
            "snapshot_id": self.snapshot.snapshot_id,
            "project_authority_evidence_sha256": self.project_authority_evidence_sha256,
            "job_pin_authority_evidence_sha256": self.job_pin_authority_evidence_sha256,
            "aggregate_authority_evidence_sha256": self.aggregate_authority_evidence_sha256,
            "exact_consumers": [
                {
                    "consumer_kind": item.consumer_kind,
                    "consumer_id": item.consumer_id,
                }
                for item in sorted(
                    self.snapshot.blocking_consumers,
                    key=lambda item: (item.consumer_kind, item.consumer_id),
                )
            ],
            "active_conditional_consumer_kinds": list(
                self.snapshot.active_conditional_consumer_kinds
            ),
        }


class RuntimeInstalledPackConsumerComposer:
    """Read-only join over existing Runtime Project and Job Authority surfaces.

    This is deliberately not a consumer registry.  Every call re-reads the
    existing owner surfaces and emits a request-scoped exact snapshot.
    """

    def __init__(
        self,
        *,
        installed_projection: InstalledPackProjection,
        web_service: WebContinuityService,
        job_authority: JobAuthorityRegistry,
        formal_ledger: FormalModelJobLedger,
    ):
        if not isinstance(installed_projection, InstalledPackProjection):
            raise RuntimeInstalledPackConsumerProjectionError(
                "installed_projection must be an InstalledPackProjection"
            )
        if not isinstance(web_service, WebContinuityService):
            raise RuntimeInstalledPackConsumerProjectionError(
                "WebContinuity Project authority surface is unavailable"
            )
        if not isinstance(job_authority, JobAuthorityRegistry):
            raise RuntimeInstalledPackConsumerProjectionError(
                "JobAuthority source surface is unavailable"
            )
        if not isinstance(formal_ledger, FormalModelJobLedger):
            raise RuntimeInstalledPackConsumerProjectionError(
                "FormalModelJob JobBundle surface is unavailable"
            )
        if formal_ledger.store.root != job_authority.artifact_store.root:
            raise RuntimeInstalledPackConsumerProjectionError(
                "JobAuthority and FormalModelJob must share the exact ArtifactStore root"
            )
        self.installed_projection = installed_projection
        self.web_service = web_service
        self.job_authority = job_authority
        self.formal_ledger = formal_ledger

    def _project_rows(
        self,
        record: InstalledPackRecord,
    ) -> tuple[list[InstalledPackConsumerRef], dict[str, Any]]:
        service = self.web_service
        manifest_root = service.store.root / "_manifests"
        project_dirs: list[Path] = []
        if manifest_root.exists():
            if not manifest_root.is_dir() or _is_reparse_or_symlink(manifest_root):
                raise RuntimeInstalledPackConsumerProjectionError(
                    "Project manifest authority root is unavailable or redirected"
                )
            for entry in sorted(manifest_root.iterdir(), key=lambda item: item.name):
                if not entry.name.startswith("WEB_PROJECT_PRJ_"):
                    continue
                if not entry.is_dir() or _is_reparse_or_symlink(entry):
                    raise RuntimeInstalledPackConsumerProjectionError(
                        "Project authority namespace contains an invalid entry"
                    )
                project_dirs.append(entry)

        try:
            catalog_exists = service._record_exists("WEB_PROJECT_CATALOG")
        except Exception as exc:
            raise RuntimeInstalledPackConsumerProjectionError(
                "Project catalog authority surface is unavailable"
            ) from exc

        if not catalog_exists:
            if project_dirs:
                raise RuntimeInstalledPackConsumerProjectionError(
                    "Project catalog is absent while Project authority records exist"
                )
            evidence = {
                "schema_revision": "RUNTIME_INSTALLED_PACK_PROJECT_CONSUMER_EVIDENCE_R001",
                "target_pack_identity": _target_identity(record),
                "catalog_binding": None,
                "projects": [],
            }
            return [], evidence

        try:
            catalog, catalog_binding = service._load_current_json("WEB_PROJECT_CATALOG")
        except Exception as exc:
            raise RuntimeInstalledPackConsumerProjectionError(
                "Project catalog currentness cannot be proven"
            ) from exc

        expected_catalog_fields = {
            "project_ids",
            "updated_at_utc",
            "authority_class",
            "catalog_revision",
        }
        if set(catalog) != expected_catalog_fields:
            raise RuntimeInstalledPackConsumerProjectionError(
                "Project catalog exact field set is invalid"
            )
        project_ids = catalog.get("project_ids")
        if (
            catalog.get("authority_class") != "RUNTIME_PROJECT_CATALOG"
            or not isinstance(project_ids, list)
            or any(not isinstance(item, str) or not item for item in project_ids)
            or project_ids != sorted(set(project_ids))
        ):
            raise RuntimeInstalledPackConsumerProjectionError(
                "Project catalog authority projection is invalid"
            )

        discovered: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
        for directory in project_dirs:
            artifact_id = directory.name
            try:
                project, project_artifact_binding = service._load_current_json(artifact_id)
            except Exception as exc:
                raise RuntimeInstalledPackConsumerProjectionError(
                    f"Project authority record cannot be read exactly: {artifact_id}"
                ) from exc
            project_id = project.get("project_id")
            if (
                not isinstance(project_id, str)
                or not project_id
                or service._project_artifact_id(project_id) != artifact_id
                or project_id in discovered
            ):
                raise RuntimeInstalledPackConsumerProjectionError(
                    "Project authority record identity is invalid or duplicated"
                )
            discovered[project_id] = (project, project_artifact_binding)

        if set(discovered) != set(project_ids):
            raise RuntimeInstalledPackConsumerProjectionError(
                "Project catalog and exact Project authority namespace disagree"
            )

        consumers: list[InstalledPackConsumerRef] = []
        evidence_rows: list[dict[str, Any]] = []
        for project_id in project_ids:
            project, project_artifact_binding = discovered[project_id]
            try:
                projection = service.get_project_pack_binding(project_id=project_id)
            except Exception as exc:
                raise RuntimeInstalledPackConsumerProjectionError(
                    f"Project Pack binding authority unavailable: {project_id}"
                ) from exc
            if projection.get("project_revision") != project.get("project_revision"):
                raise RuntimeInstalledPackConsumerProjectionError(
                    "Project Pack binding projection revision mismatch"
                )
            binding = projection.get("binding")
            evidence_rows.append(
                {
                    "project_id": project_id,
                    "project_revision": projection["project_revision"],
                    "project_artifact_binding": project_artifact_binding,
                    "pack_binding": binding,
                }
            )
            if binding is None:
                continue
            candidate = InstalledPackConsumerRef.from_project_binding(project_id, binding)
            if candidate.matches(record):
                consumers.append(candidate)

        evidence = {
            "schema_revision": "RUNTIME_INSTALLED_PACK_PROJECT_CONSUMER_EVIDENCE_R001",
            "target_pack_identity": _target_identity(record),
            "catalog_binding": catalog_binding,
            "projects": evidence_rows,
        }
        return consumers, evidence

    def _job_rows(
        self,
        record: InstalledPackRecord,
    ) -> tuple[list[InstalledPackConsumerRef], dict[str, Any]]:
        try:
            currentness = RunningJobPinCurrentnessProjector(
                job_authority=self.job_authority,
                formal_ledger=self.formal_ledger,
            ).project()
        except RunningJobCurrentnessError as exc:
            raise RuntimeInstalledPackConsumerProjectionError(
                f"running Job currentness cannot be proven: {exc}"
            ) from exc

        consumers: list[InstalledPackConsumerRef] = []
        for pin in currentness.running_pins:
            same_id_version = (
                pin.pack_id == record.pack_id
                and pin.pack_version == record.pack_version
            )
            if not same_id_version:
                continue
            candidate = InstalledPackConsumerRef.from_job_pin(pin)
            if not candidate.matches(record):
                raise RuntimeInstalledPackConsumerProjectionError(
                    "running target-version Job pin conflicts with exact installed Pack identity"
                )
            consumers.append(candidate)

        evidence = {
            "schema_revision": "RUNTIME_INSTALLED_PACK_JOB_PIN_CONSUMER_EVIDENCE_R002",
            "target_pack_identity": _target_identity(record),
            "running_job_currentness_evidence_sha256": currentness.evidence_sha256(),
            "running_job_currentness": currentness.evidence,
        }
        return consumers, evidence

    def compose(
        self,
        *,
        pack_id: str,
        pack_version: str,
        snapshot_id: str,
        active_conditional_consumer_kinds: Iterable[str] = (),
        conditional_authority_checks: Iterable[
            InstalledPackConditionalAuthorityCheck
        ] = (),
    ) -> RuntimeInstalledPackConsumerProjection:
        try:
            record = self.installed_projection.resolve_installed_record(
                pack_id, pack_version
            )
        except Exception as exc:
            raise RuntimeInstalledPackConsumerProjectionError(
                "exact installed Pack target cannot be resolved"
            ) from exc

        project_consumers, project_evidence = self._project_rows(record)
        job_consumers, job_evidence = self._job_rows(record)
        combined = project_consumers + job_consumers
        identities = [(item.consumer_kind, item.consumer_id) for item in combined]
        if len(identities) != len(set(identities)):
            raise RuntimeInstalledPackConsumerProjectionError(
                "Runtime consumer projection produced duplicate consumer identities"
            )
        combined.sort(key=lambda item: (item.consumer_kind, item.consumer_id))

        snapshot = InstalledPackConsumerSnapshot.for_record(
            snapshot_id=snapshot_id,
            record=record,
            consumers=combined,
            active_conditional_consumer_kinds=active_conditional_consumer_kinds,
            conditional_authority_checks=conditional_authority_checks,
        )
        project_sha = _sha256(project_evidence)
        job_sha = _sha256(job_evidence)
        aggregate = {
            "schema_revision": RUNTIME_CONSUMER_PROJECTION_CONTRACT,
            "target_pack_identity": _target_identity(record),
            "snapshot_id": snapshot.snapshot_id,
            "project_authority_evidence_sha256": project_sha,
            "job_pin_authority_evidence_sha256": job_sha,
            "consumer_identities": identities,
            "active_conditional_consumer_kinds": list(
                snapshot.active_conditional_consumer_kinds
            ),
            "conditional_authority_evidence_sha256": [
                check.authority_evidence_sha256
                for check in sorted(
                    snapshot.conditional_authority_checks,
                    key=lambda item: item.consumer_kind,
                )
            ],
        }
        return RuntimeInstalledPackConsumerProjection(
            snapshot=snapshot,
            project_authority_evidence_sha256=project_sha,
            job_pin_authority_evidence_sha256=job_sha,
            aggregate_authority_evidence_sha256=_sha256(aggregate),
        )

    def uninstall(
        self,
        *,
        pack_id: str,
        pack_version: str,
        snapshot_id: str,
        active_conditional_consumer_kinds: Iterable[str] = (),
        conditional_authority_checks: Iterable[
            InstalledPackConditionalAuthorityCheck
        ] = (),
    ) -> dict[str, Any]:
        projection = self.compose(
            pack_id=pack_id,
            pack_version=pack_version,
            snapshot_id=snapshot_id,
            active_conditional_consumer_kinds=active_conditional_consumer_kinds,
            conditional_authority_checks=conditional_authority_checks,
        )
        result = self.installed_projection.uninstall(
            pack_id,
            pack_version,
            consumer_snapshot=projection.snapshot,
        )
        return {
            **result,
            "runtime_consumer_projection": projection.to_receipt(),
        }
