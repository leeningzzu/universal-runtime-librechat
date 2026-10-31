"""Verify exact older C5 native source archive is present for future real LibreChat binding.

These SIX native Node tests exercise the existing 13-hook cascade, owner
admissions, same-owner File/Chat scope and Project route with synthetic
in-memory fixtures. No user's live DB/files or Docker service is used.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
ARCHIVE = REPO / "native_c5_candidate/R006_mature_uninstalled"
PROVENANCE = ARCHIVE / "SOURCE_PROVENANCE_R241.json"
TESTS = (
    "test_c5CanonicalNativeRetirement.candidate.js",
    "test_c5CurrentRuntimeSourceRefOwner.candidate.js",
    "test_c5NativeChatFileConsumers.candidate.js",
    "test_c5NativeWholeProjectBinding.candidate.js",
    "test_c5WholeProjectProductEndpoints.candidate.js",
    "test_c5WholeProjectProductNativeRoute.candidate.js",
)


class MatureC5ReuseTests(unittest.TestCase):
    def test_exact_frozen_source_provenance(self):
        record = json.loads(PROVENANCE.read_text(encoding="utf8"))
        self.assertEqual(record["archive_file_count"], 36)
        self.assertEqual(record["zip_sha256"], "c644f65e107ed6c949d2fa0d1d78a52c7ac1a1b3b1e5be3421075e4a37b27d35")
        self.assertIs(record["real_Product_c5_native_GUI_adopted"], False)
        found = set()
        for row in record["archive_entries"]:
            rel = Path(row["path"])
            self.assertNotIn("..", rel.parts)
            target = ARCHIVE / rel
            self.assertTrue(target.is_file() and not target.is_symlink())
            self.assertEqual(hashlib.sha256(target.read_bytes()).hexdigest(), row["sha256"])
            self.assertEqual(target.stat().st_size, row["bytes"])
            self.assertNotIn(row["path"], found)
            found.add(row["path"])
        self.assertEqual(len(found), 36)

    def test_six_native_synthetic_cascade_consumer_suites(self):
        node = shutil.which("node")
        self.assertIsNotNone(node, "GitHub Windows runner must provide installed Node")
        record = json.loads(PROVENANCE.read_text(encoding="utf8"))
        with tempfile.TemporaryDirectory(prefix="r241-native-c5-synthetic-only-") as temp:
            root = Path(temp)
            for entry in record["archive_entries"]:
                source = ARCHIVE / entry["path"]
                if source.suffix != ".js":
                    continue
                if not (
                    entry["path"].startswith(("tests/", "api/server/routes/", "adapter/"))
                ):
                    continue
                dest = root / source.name
                self.assertFalse(dest.exists(), "Native C5 test relocation has duplicate module names")
                dest.write_bytes(source.read_bytes())
            # Existing R006 test reads the current native Project router under
            # its old local candidate label. Restore ONLY that test filename,
            # without editing or adapting the implementation.
            alias = root / "projects.c5.whole_product_route.candidate.js"
            alias.write_bytes((ARCHIVE / "api/server/routes/projects.js").read_bytes())
            for name in TESTS:
                result = subprocess.run(
                    [node, str(root / name)],
                    cwd=root,
                    capture_output=True,
                    text=True,
                    encoding="utf8",
                    errors="replace",
                    timeout=45,
                )
                self.assertEqual(
                    result.returncode, 0,
                    msg=f"{name} failed: {result.stderr[-500:]}",
                )
        # NOTE: This proves historical source tests only: the actual running
        # LibreChat v0.8.8 Delete route remains unbound and Product PASS = NO.


if __name__ == "__main__":
    unittest.main(verbosity=2)
