from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from universal_runtime.core.artifact_store import ArtifactStore
from universal_runtime.packs.registry import PackRegistry
from universal_runtime.web_continuity import WebContinuityService

if __package__:
    from .installed_pack_projection import InstalledPackProjection
    from .installed_pack_user_lifecycle import UserInstalledPackBindingResolver
else:
    from installed_pack_projection import InstalledPackProjection
    from installed_pack_user_lifecycle import UserInstalledPackBindingResolver


class InstalledPackWebContinuityService(WebContinuityService):
    """Installed-aware Project Pack owner using the existing Project RLock."""

    def __init__(
        self,
        artifact_store: ArtifactStore,
        *,
        installed_projection: InstalledPackProjection,
        promoted_registry: PackRegistry,
        base_runtime_tree_sha256: str | None = None,
        web_contract_sha256: str | None = None,
        machine_local_state_root: Any | None = None,
    ):
        kwargs: dict[str, Any] = {
            "pack_registry": UserInstalledPackBindingResolver(
                installed_projection,
                promoted_registry,
            )
        }
        if base_runtime_tree_sha256 is not None:
            kwargs["base_runtime_tree_sha256"] = base_runtime_tree_sha256
        if web_contract_sha256 is not None:
            kwargs["web_contract_sha256"] = web_contract_sha256
        if machine_local_state_root is not None:
            kwargs["machine_local_state_root"] = machine_local_state_root
        super().__init__(artifact_store, **kwargs)
        self.installed_projection = installed_projection
        self.promoted_registry = promoted_registry

    @contextmanager
    def installed_pack_project_consumer_guard(self) -> Iterator[None]:
        """Serialize Project Pack consumer snapshot/effect against bind/unbind."""
        with self._lock:
            yield

    def bind_project_pack(
        self,
        *,
        command_id: str,
        project_id: str,
        expected_project_revision: int,
        pack_id: str,
        pack_version: str,
    ) -> dict[str, Any]:
        # The parent resolves target Pack before entering its own RLock. Hold the
        # same re-entrant owner lock around the whole call so resolution and
        # commit cannot straddle an uninstall guarded by this owner.
        with self._lock:
            return super().bind_project_pack(
                command_id=command_id,
                project_id=project_id,
                expected_project_revision=expected_project_revision,
                pack_id=pack_id,
                pack_version=pack_version,
            )
