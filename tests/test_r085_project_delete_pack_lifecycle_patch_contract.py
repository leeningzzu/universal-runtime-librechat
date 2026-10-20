from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT / "patches/librechat/r085-project-delete-pack-lifecycle-r001.patch"
MANIFEST = ROOT / "patches/librechat/r085-project-delete-pack-lifecycle-r001.manifest.json"
MATRIX = ROOT / "docs/CAPABILITY_LIFECYCLE_MATRIX.md"
BASELINE = ROOT / "docs/CURRENT_PUBLIC_BASELINE.md"
AGENTS = ROOT / "AGENTS.md"


def test_r085_patch_manifest_identity_and_scope() -> None:
    patch = PATCH.read_text(encoding="utf-8")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    assert manifest["schema"] == "UR_R085_PROJECT_DELETE_PACK_LIFECYCLE_SOURCE_PATCH_R001"
    assert hashlib.sha256(PATCH.read_bytes()).hexdigest() == manifest["patch_sha256"]
    assert manifest["upstream"] == {
        "repository": "https://github.com/LibreChat-AI/LibreChat",
        "release": "v0.8.8",
        "commit": "e8f3be08623663d4ad7f7241e693c94469b63bb0",
    }
    assert {row["path"] for row in manifest["files"]} == {
        "client/src/data-provider/Projects/mutations.ts",
        "client/src/components/Projects/ProjectDeleteDialog.tsx",
        "client/src/components/Projects/RuntimeProjectWorkspace.tsx",
        "api/server/routes/runtimeProjects.js",
    }
    assert manifest["production_mutation"] is False
    assert manifest["real_user_project_delete"] is False
    assert manifest["proof_ceiling"].endswith("NOT_PRODUCTION_ADOPTION_OR_PRODUCT_PASS")

    additions = "\n".join(
        line[1:] for line in patch.splitlines() if line.startswith("+") and not line.startswith("+++")
    )
    assert "prepare-status" not in additions
    assert "prepare-start" not in additions
    assert "FORWARD_ONLY_DURABLE_RECEIPT_R001" in additions
    assert "CONFIRMED_C5_WHOLE_PROJECT_DELETE_R001" in additions
    assert "No global backup is" in additions
    assert "runtime-user-installable-packs" in additions
    assert "runtime-user-pack-install" in additions
    assert "Install stores one exact Pack revision" in additions
    assert "Deactivate keeps it installed" in additions
    assert "never auto-adopts it or rewrites history" in additions
    assert "PACKLESS PROJECT" in additions
    assert "ONE PRIMARY PACK" in additions


def test_r085_patch_is_public_source_safe_and_cumulative() -> None:
    patch = PATCH.read_text(encoding="utf-8")
    lower = patch.lower()
    for forbidden in (
        "c:\\users\\",
        "localuniversalruntime_v0_1",
        "/mnt/data/",
        "jwt_secret=",
        "creds_key=",
        "delete_speed_acceptance_r002",
    ):
        assert forbidden not in lower

    assert "bearer eyj" not in lower
    assert "bearer sk-" not in lower
    matrix = MATRIX.read_text(encoding="utf-8")
    baseline = BASELINE.read_text(encoding="utf-8")
    agents = AGENTS.read_text(encoding="utf-8")
    assert "direct-forward" in matrix
    assert "Install != Activate" in matrix
    assert "one exact Primary Pack" in matrix
    assert "R085" in baseline
    assert "not Production authority" in baseline
    assert "local capability slice" in agents
    assert "whole Project-first Product" in agents
