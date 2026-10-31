"""C5 retirement methods composed onto the CURRENT installed-pack-aware Runtime.
No new App, Pack binding owner, ArtifactStore, Job registrar or Source database.
"""
from universal_runtime.c5_project_retirement_owner import RetirementWebContinuityService
from universal_runtime.installed_pack_web_continuity_adapter import InstalledPackWebContinuityService


class C5InstalledPackRetirementWebContinuityService(
    RetirementWebContinuityService, InstalledPackWebContinuityService
):
    """Retain InstalledPackWebContinuityService behavior; add C5 guarded retirement."""
