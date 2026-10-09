from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from universal_runtime.core.formal_model_job import FormalModelJobLedger
from universal_runtime.core.job_authority import JobAuthorityRegistry
from universal_runtime.packs.registry import PackRegistry, PackResolutionError, ResolvedPack

if __package__:
    from .installed_pack_projection import (
        InstalledPackBindingResolver,
        InstalledPackConditionalAuthorityCheck,
        InstalledPackLifecycleError,
        InstalledPackProjection,
    )
    from .runtime_consumer_projection import RuntimeInstalledPackConsumerComposer
else:
    from installed_pack_projection import (
        InstalledPackBindingResolver,
        InstalledPackConditionalAuthorityCheck,
        InstalledPackLifecycleError,
        InstalledPackProjection,
    )
    from runtime_consumer_projection import RuntimeInstalledPackConsumerComposer


USER_INSTALLABLE_POLICY_CONTRACT = "RUNTIME_USER_INSTALLABLE_PACK_POLICY_R001"


class UserInstallablePackEligibilityError(ValueError):
    """Raised when promoted manifest Authority does not permit user lifecycle mutation."""


def user_installable_pack_evidence(pack: ResolvedPack) -> dict[str, Any]:
    manifest = pack.manifest
    visibility = manifest.get("visibility")
    if visibility is None:
        eligibility = "USER_INSTALLABLE_COMPAT_DEFAULT"
    elif visibility == "hidden_system":
        raise UserInstallablePackEligibilityError(
            f"Pack is hidden_system and outside user Installed lifecycle: "
            f"{pack.pack_id}@{pack.version}"
        )
    elif visibility == "user":
        eligibility = "USER_INSTALLABLE_EXPLICIT"
    else:
        raise UserInstallablePackEligibilityError(
            f"Unknown Pack visibility requires lifecycle re-entry: {visibility!r}"
        )
    return {
        "schema_revision": USER_INSTALLABLE_POLICY_CONTRACT,
        "pack_id": pack.pack_id,
        "pack_version": pack.version,
        "pack_manifest_sha256": pack.manifest_sha256,
        "pack_content_manifest_sha256": pack.content_manifest_sha256,
        "pack_promotion_receipt_sha256": pack.promotion_receipt_sha256,
        "visibility": visibility,
        "eligibility": eligibility,
    }


class UserInstalledPackBindingResolver:
    """Project binding resolver: user eligibility + installed exact identity + promotion currentness."""

    def __init__(
        self,
        projection: InstalledPackProjection,
        promoted_registry: PackRegistry,
    ):
        self.projection = projection
        self.promoted_registry = promoted_registry
        self._installed = InstalledPackBindingResolver(projection, promoted_registry)

    def resolve_promoted_pack(self, pack_id: str, version: str) -> ResolvedPack:
        promoted = self.promoted_registry.resolve_promoted_pack(pack_id, version)
        try:
            user_installable_pack_evidence(promoted)
        except UserInstallablePackEligibilityError as exc:
            raise PackResolutionError(str(exc)) from exc
        return self._installed.resolve_promoted_pack(pack_id, version)

    def assert_current(self, resolved_or_pin: ResolvedPack | Any) -> ResolvedPack:
        current = self.resolve_promoted_pack(
            getattr(resolved_or_pin, "pack_id", None),
            getattr(resolved_or_pin, "version", None)
            or getattr(resolved_or_pin, "pack_version", None),
        )
        return self._installed.assert_current(resolved_or_pin)


@dataclass(frozen=True)
class UserInstalledPackCatalogRow:
    pack_id: str
    pack_version: str
    installed: bool
    eligibility: str
    visibility: str | None


class InstalledPackUserLifecycleCoordinator:
    """Narrow user-Pack lifecycle surface over accepted existing authorities.

    It intentionally owns no registry or database. Project consumer serialization
    is delegated to the Installed-aware WebContinuity owner guard. Current Job
    consumers are re-read from Runtime Authority on every uninstall.
    """

    def __init__(
        self,
        *,
        projection: InstalledPackProjection,
        promoted_registry: PackRegistry,
        web_service: Any,
        job_authority: JobAuthorityRegistry,
        formal_ledger: FormalModelJobLedger,
    ):
        guard = getattr(web_service, "installed_pack_project_consumer_guard", None)
        if not callable(guard):
            raise InstalledPackLifecycleError(
                "Installed-aware Project consumer serialization guard is unavailable"
            )
        self.projection = projection
        self.promoted_registry = promoted_registry
        self.web_service = web_service
        self.composer = RuntimeInstalledPackConsumerComposer(
            installed_projection=projection,
            web_service=web_service,
            job_authority=job_authority,
            formal_ledger=formal_ledger,
        )

    def _eligible(self, pack_id: str, pack_version: str) -> tuple[ResolvedPack, dict[str, Any]]:
        promoted = self.promoted_registry.resolve_promoted_pack(pack_id, pack_version)
        try:
            evidence = user_installable_pack_evidence(promoted)
        except UserInstallablePackEligibilityError as exc:
            raise InstalledPackLifecycleError(str(exc)) from exc
        return promoted, evidence

    def list_user_installable_packs(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for promoted_row in self.promoted_registry.list_promoted_packs():
            pack_id = promoted_row["pack_id"]
            version = promoted_row["version"]
            promoted = self.promoted_registry.resolve_promoted_pack(pack_id, version)
            try:
                evidence = user_installable_pack_evidence(promoted)
            except UserInstallablePackEligibilityError:
                continue
            try:
                self.projection.resolve_installed_record(pack_id, version)
                installed = True
            except InstalledPackLifecycleError:
                installed = False
            rows.append(
                {
                    **evidence,
                    "installed": installed,
                }
            )
        return rows

    def install_user_pack(self, pack_id: str, pack_version: str) -> dict[str, Any]:
        _promoted, eligibility = self._eligible(pack_id, pack_version)
        result = self.projection.install_from_promoted(
            self.promoted_registry,
            pack_id,
            pack_version,
        )
        return {**result, "user_installable_eligibility": eligibility}

    def uninstall_user_pack(
        self,
        pack_id: str,
        pack_version: str,
        *,
        snapshot_id: str,
        active_conditional_consumer_kinds: Iterable[str] = (),
        conditional_authority_checks: Iterable[
            InstalledPackConditionalAuthorityCheck
        ] = (),
    ) -> dict[str, Any]:
        _promoted, eligibility = self._eligible(pack_id, pack_version)
        with self.web_service.installed_pack_project_consumer_guard():
            result = self.composer.uninstall(
                pack_id=pack_id,
                pack_version=pack_version,
                snapshot_id=snapshot_id,
                active_conditional_consumer_kinds=active_conditional_consumer_kinds,
                conditional_authority_checks=conditional_authority_checks,
            )
        return {**result, "user_installable_eligibility": eligibility}
