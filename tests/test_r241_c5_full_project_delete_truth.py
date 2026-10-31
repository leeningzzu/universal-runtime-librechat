"""C5 actual Runtime source-module synthetic positive/negative Project deletion proofs.

Zero contact with a user's LibreChat, Project, SQLite/Mongo, Docker, vector DB,
GitHub write APIs or real Source data. Exercise the actual installed module.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / "windows/inquiry_desk/payload/product/runtime/src"
sys.dont_write_bytecode = True
sys.path.insert(0, str(SOURCE))
from universal_runtime import c5_runtime_operation_receipt as c5

NATIVE = "a" * 24
OWNER = "b" * 24
RUNTIME = "PRJ_SYNTHETIC_C5_READBACK"
SOURCE_ID = "SRC_AABBCCDD"
SOURCE_SHA = "f" * 64
EVIDENCE = "e" * 64


def file_seal():
    return {
        "schema": "C5_NATIVE_FILE_SEAL_R001",
        "rowPresent": True,
        "ownedTargetStorage": True,
        "messageOnlyTargetOwned": False,
        "knownMissingOriginal": False,
        "bytes": 17,
        "logicalPaths": [],
        "source": None,
        "vectorDeleteRequired": False,
        "vectorOwnerAvailable": True,
        "codeEnvDeleteRequired": False,
        "codeEnvOwnerAvailable": True,
        "unsupportedStorage": False,
        "refs": [],
    }


def complete_fixture():
    plan = {
        "projectId": NATIVE,
        "ownerId": OWNER,
        "revision": 1,
        "chats": ["chat-owned", "chat-archived-owned"],
        "exclusive": [{"id": "file-owned", "bytes": 17}],
        "retained": [{"id": "file-shared"}],
    }
    plan["planSha256"] = c5._plan_sha256(plan)
    snapshot = {
        "schema": "C5_PROJECT_DELETE_DURABLE_SNAPSHOT_R001",
        "projectId": NATIVE,
        "ownerId": OWNER,
        "planSha256": plan["planSha256"],
        "runtimeSources": [{"source_ref_id": SOURCE_ID, "source_sha256": SOURCE_SHA}],
        "protectedAssetCensusSha256": "c" * 64,
        "files": [
            {"id": "file-owned", "classification": "EXCLUSIVE", "retentionReason": None, "seal": file_seal()},
            {"id": "file-shared", "classification": "RETAINED", "retentionReason": "OTHER_PROJECT", "seal": file_seal()},
        ],
    }
    snapshot["snapshotSha256"] = c5._canonical_sha256(snapshot)
    return {
        "schema": "C5_PROJECT_CASCADE_R001",
        "projectId": NATIVE,
        "ownerId": OWNER,
        "plan": plan,
        "phase": "COMPLETE",
        "c5Confirmed": True,
        "nativeEffectOutcomeUnknown": False,
        "deletedChats": ["chat-owned", "chat-archived-owned"],
        "deletedFiles": ["file-owned"],
        "retiredSources": [SOURCE_ID],
        "durableSnapshot": snapshot,
    }


class FakeStore:
    def __init__(self, folder: Path):
        self.root = folder
    def _manifest_dir(self, artifact_id):
        return self.root / "manifest" / artifact_id
    def _r009_exact_paths(self, opaque_id):
        return opaque_id, self.root / "r009" / opaque_id, self.root / "r009_manifest" / opaque_id


class FakeService:
    def __init__(self, folder):
        self.store = FakeStore(folder)
        self.status = "RETIRED"
        self.sources = []
    def _raw_project(self, project_id):
        if project_id != RUNTIME:
            raise AssertionError("FOREIGN_RUNTIME_PROJECT")
        return {"project_id": RUNTIME, "status": self.status, "source_ref_ids": list(self.sources)}, None


class C5CompleteTruthTest(unittest.TestCase):
    def assert_rejected(self, record, expected):
        with self.assertRaises(c5.C5ReceiptStop) as stopped:
            c5._assert_receipt(record, NATIVE, OWNER)
        self.assertEqual(str(stopped.exception), expected)

    def test_complete_positive_exact_frozen_cascade(self):
        c5._assert_receipt(complete_fixture(), NATIVE, OWNER)

    def test_complete_fails_on_missing_archived_chat(self):
        r = complete_fixture()
        r["deletedChats"].remove("chat-archived-owned")
        self.assert_rejected(r, "C5_COMPLETE_OWNED_CHAT_CASCADE_INCOMPLETE")

    def test_complete_fails_on_missing_exclusive_file(self):
        r = complete_fixture()
        r["deletedFiles"] = []
        self.assert_rejected(r, "C5_COMPLETE_EXCLUSIVE_OR_SHARED_FILE_SCOPE_MISMATCH")

    def test_complete_fails_if_shared_file_was_deleted(self):
        r = complete_fixture()
        r["deletedFiles"].append("file-shared")
        self.assert_rejected(r, "C5_COMPLETE_EXCLUSIVE_OR_SHARED_FILE_SCOPE_MISMATCH")

    def test_complete_fails_if_any_frozen_source_not_retired(self):
        r = complete_fixture()
        r["retiredSources"] = []
        self.assert_rejected(r, "C5_COMPLETE_RUNTIME_SOURCE_PAYLOADS_NOT_RETIRED")

    def test_complete_fails_without_native_confirmation(self):
        r = complete_fixture()
        r["c5Confirmed"] = False
        self.assert_rejected(r, "C5_COMPLETE_NATIVE_DELETE_EFFECT_UNVERIFIED")

    def test_complete_fails_with_unknown_native_effect(self):
        r = complete_fixture()
        r["nativeEffectOutcomeUnknown"] = True
        self.assert_rejected(r, "C5_COMPLETE_NATIVE_DELETE_EFFECT_UNVERIFIED")

    def test_complete_fails_without_durable_snapshot(self):
        r = complete_fixture()
        del r["durableSnapshot"]
        self.assert_rejected(r, "C5_COMPLETE_DURABLE_SNAPSHOT_AND_SOURCE_RECEIPTS_REQUIRED")

    def test_partially_deleted_project_remains_legally_partial(self):
        r = complete_fixture()
        r["phase"] = "PARTIAL_OR_BLOCKED"
        r["retiredSources"] = []
        r["deletedFiles"] = []
        c5._assert_receipt(r, NATIVE, OWNER)

    @staticmethod
    def source_row(state="CONTENT_RETIRED", bound=False):
        return {
            "source_ref_id": SOURCE_ID,
            "retirement_state": state,
            "active_project_binding": bound,
            "completed_native_binding": {
                "binding_evidence_sha256": EVIDENCE,
                "source_ref_ids": [SOURCE_ID],
            },
        }

    @staticmethod
    def complete_marker():
        return {
            "state": "COMPLETED",
            "project_id": RUNTIME,
            "source_ref_id": SOURCE_ID,
            "native_binding": {"binding_evidence_sha256": EVIDENCE, "source_ref_ids": [SOURCE_ID]},
            "retired_payload_count": 3,
            "content_sha256_records": [
                {"id": "RUNTIME_OPAQUE_" + "A" * 64, "sha256": "1" * 64, "bytes": 11},
                {"id": "WEB_TEXT_DERIVATION_" + SOURCE_ID, "sha256": "2" * 64, "bytes": 22},
                {"id": "WEB_COMMAND_" + "B" * 64, "sha256": "3" * 64, "bytes": 33},
            ],
        }

    def with_readback(self, mutate=None, rows=None):
        with tempfile.TemporaryDirectory(prefix="inquiry-r241-c5-synthetic-only-") as work:
            service = FakeService(Path(work))
            marker = (service.store._manifest_dir("WEB_SOURCE_REF_" + SOURCE_ID) /
                      "PERMANENT_CONTENT_ERASURE_COMPLETE_R001.json")
            marker.parent.mkdir(parents=True, exist_ok=True)
            receipt = self.complete_marker()
            use_rows = [self.source_row()] if rows is None else rows
            if mutate is not None:
                mutate(service, receipt, use_rows)
            marker.write_text(json.dumps(receipt), encoding="utf8")
            with patch.object(c5, "list_project_source_retirement_candidates",
                              return_value=use_rows):
                c5._assert_complete_runtime_source_content_current(
                    service, RUNTIME, complete_fixture()
                )

    def test_physical_content_absent_passes(self):
        self.with_readback()

    def test_runtime_project_not_retired_fails(self):
        def mutate(service, marker, rows):
            service.status = "ACTIVE"
        with self.assertRaisesRegex(c5.C5ReceiptStop, "C5_COMPLETE_RUNTIME_PROJECT_STILL_ACTIVE_OR_BOUND"):
            self.with_readback(mutate)

    def test_content_detached_but_not_erased_fails(self):
        with self.assertRaisesRegex(c5.C5ReceiptStop, "C5_COMPLETE_SOURCE_CONTENT_RETIREMENT_NOT_PROVEN"):
            self.with_readback(rows=[self.source_row("DETACHED_RETAINED")])

    def test_extra_runtime_source_not_in_snapshot_fails(self):
        with self.assertRaisesRegex(c5.C5ReceiptStop, "C5_COMPLETE_RUNTIME_SOURCE_INVENTORY_NOT_EXHAUSTIVE"):
            self.with_readback(rows=[self.source_row(), {"source_ref_id": "SRC_99999999"}])

    def test_retirement_marker_invalid_owner_fails(self):
        def mutate(service, receipt, rows):
            receipt["project_id"] = "PRJ_WRONG"
        with self.assertRaisesRegex(c5.C5ReceiptStop, "C5_COMPLETE_SOURCE_ERASURE_RECEIPT_MISMATCH"):
            self.with_readback(mutate)

    def test_retired_source_payload_reappears_fails(self):
        def mutate(service, receipt, rows):
            target = service.store._r009_exact_paths("a"*64)[1]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"synthetic-reappeared-only")
        with self.assertRaisesRegex(c5.C5ReceiptStop, "C5_COMPLETE_RETIRED_SOURCE_PAYLOAD_STILL_PRESENT"):
            self.with_readback(mutate)

    def test_erasure_marker_missing_fails(self):
        with tempfile.TemporaryDirectory(prefix="inquiry-r241-c5-synthetic-only-") as work:
            service = FakeService(Path(work))
            with patch.object(c5, "list_project_source_retirement_candidates",
                              return_value=[self.source_row()]):
                with self.assertRaisesRegex(c5.C5ReceiptStop, "C5_COMPLETE_SOURCE_ERASURE_MARKER_MISSING"):
                    c5._assert_complete_runtime_source_content_current(
                        service, RUNTIME, complete_fixture()
                    )


if __name__ == "__main__":
    unittest.main(verbosity=2)
