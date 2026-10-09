"""Fail-closed C7 guard: final Windows shell contains no user Pack payload.

This checks a proposed release *directory*, not a live Runtime root, a
development source repository, an Installed-Pack projection, or a Docker image.
It does not create an installer, backup service, Skill engine, or Pack manager.

Core and the optional-Pack lifecycle *code* are allowed; any prebundled
Academic/Novel/Report/Market/General Pack *content or installed receipt* is
not. A fresh user may install Packs later via the governed Runtime lifecycle.
"""
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

FORBIDDEN_PAYLOAD_ROOTS = (
    "packs",
    "pack_content",
    "pack_bundles",
    "_authoritative/packs",
    "_installed/packs",
    "_installed/receipts",
    "app/packs",
    "app/pack_content",
    "app/_authoritative/packs",
    "app/_installed/packs",
    "runtime/packs",
    "runtime/_authoritative/packs",
    "runtime/_installed/packs",
    "resources/packs",
    "resources/pack_content",
)
RELEASE_MANIFESTS = (
    "release_manifest.json",
    "install_manifest.json",
    "manifest.json",
)
AUTO_ADOPT_FIELDS = (
    "preinstalled_packs",
    "auto_install_packs",
    "activated_packs",
    "default_active_packs",
    "bundled_pack_content",
)


def inspect_packless_shell(root: Path) -> list[str]:
    if not root.is_dir() or root.is_symlink():
        return ["NO_VALID_RELEASE_DIRECTORY"]
    findings: list[str] = []
    for rel in FORBIDDEN_PAYLOAD_ROOTS:
        path = root / rel
        if path.is_symlink():
            findings.append(f"PACK_PATH_LINK:{rel}")
        elif path.is_file():
            findings.append(f"PACK_PAYLOAD_FILE:{rel}")
        elif path.is_dir():
            try:
                if next(path.iterdir(), None) is not None:
                    findings.append(f"PACK_PAYLOAD_DIRECTORY:{rel}")
            except OSError:
                findings.append(f"PACK_DIRECTORY_UNREADABLE:{rel}")
    for rel in RELEASE_MANIFESTS:
        manifest = root / rel
        if manifest.is_symlink():
            findings.append(f"RELEASE_MANIFEST_LINK:{rel}")
            continue
        if not manifest.exists():
            continue
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (ValueError, UnicodeError, OSError):
            findings.append(f"RELEASE_MANIFEST_INVALID:{rel}")
            continue
        if not isinstance(data, dict):
            findings.append(f"RELEASE_MANIFEST_NOT_OBJECT:{rel}")
            continue
        for key in AUTO_ADOPT_FIELDS:
            value = data.get(key)
            if value not in (None, "", [], {}, False):
                findings.append(f"RELEASE_AUTO_PACK_ACTIVATION:{rel}:{key}")
    return findings


def _self_test() -> None:
    def scenario(name: str, build, accepted: bool) -> None:
        with tempfile.TemporaryDirectory(prefix="PACKLESS_SHELL_TEST_") as temp:
            root = Path(temp)
            (root / "app").mkdir()
            (root / "app" / "librechat.yaml").write_text(
                "version: 1.3.17\n", encoding="utf-8"
            )
            build(root)
            failures = inspect_packless_shell(root)
            if bool(failures) == accepted:
                raise AssertionError(f"{name}: expected_pass={accepted}")
        print("PASS " + name)

    def add(root: Path, rel: str) -> None:
        f = root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("SYNTHETIC_TEST_PACK_NOT_REAL_DATA\n", encoding="utf-8")

    def write_manifest(root: Path, packs: list[str]) -> None:
        (root / "release_manifest.json").write_text(
            json.dumps({"preinstalled_packs": packs}), encoding="utf-8"
        )

    scenario("clean_Core_without_any_Pack", lambda root: None, True)
    scenario(
        "optional_Runtime_Pack_lifecycle_code_not_Pack_content",
        lambda root: add(root, "src/universal_runtime/packs/registry.py"),
        True,
    )
    scenario(
        "LibreChat_native_Skill_primitive_not_a_Pack",
        lambda root: add(root, "app/skill/native_skill.md"),
        True,
    )
    scenario(
        "empty_optional_installed_Pack_directory",
        lambda root: (root / "_installed" / "packs").mkdir(parents=True),
        True,
    )
    scenario(
        "reject_Academic_Pack_bundled",
        lambda root: add(root, "packs/academic_paper/0.5.1/pack.yaml"),
        False,
    )
    scenario(
        "reject_hidden_General_Pack_prebaked_in_authority",
        lambda root: add(root, "_authoritative/packs/general_chat_system/0.1.0/pack.yaml"),
        False,
    )
    scenario(
        "reject_Novel_Pack_in_Desktop_app",
        lambda root: add(root, "app/packs/universal_novel/pack.yaml"),
        False,
    )
    scenario(
        "reject_installed_Pack_and_its_content_projection",
        lambda root: add(root, "_installed/packs/academic_paper/0.5.0/install_receipt.json"),
        False,
    )
    scenario(
        "reject_historical_Pack_install_receipts",
        lambda root: add(root, "_installed/receipts/install/receipt.json"),
        False,
    )
    scenario(
        "reject_auto_activated_Pack_manifest",
        lambda root: write_manifest(root, ["academic_paper"]),
        False,
    )
    scenario(
        "accept_empty_optional_Pack_manifest",
        lambda root: write_manifest(root, []),
        True,
    )
    print("PACKLESS_RELEASE_PAYLOAD_SELF_TEST=PASS 11/11")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("release_root", type=Path, nargs="?")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        _self_test()
        return
    if args.release_root is None:
        parser.error("provide release_root (final staged payload), or --self-test")
    findings = inspect_packless_shell(args.release_root)
    for code in findings:
        print("STOP " + code)
    if findings:
        raise SystemExit(1)
    print("PACKLESS_FINAL_SHELL_CONTENT=PASS")
    print("NOTE: contents-only check; Core natural-use/install/uninstall acceptance separate")


if __name__ == "__main__":
    main()
