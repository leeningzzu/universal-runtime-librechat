"""Bounded no-effect test: read-only C5 Runtime Project SourceRefs after retirement."""
from __future__ import annotations
import copy
import os
import sys
import threading
from pathlib import Path
from fastapi import FastAPI, HTTPException
from starlette.requests import Request

ROOT = Path(__file__).resolve().parents[2]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / "src"))
import universal_runtime

universal_runtime.__path__.insert(0, str(Path(__file__).parent / "universal_runtime"))
from universal_runtime.c5_retirement_runtime_routes import install_project_retirement_routes
import universal_runtime.c5_retirement_runtime_routes as retirement_routes

# No mock Job admission and no JobAuthority scan. The isolated Source/Memory
# owner has no Job store/ledger; accidental reintroduction must fail.
assert not hasattr(retirement_routes, "_read_c5_project_job_scope")

PROJECT = "PRJ_0123456789ABCDEF0123456789AB"
SOURCE = "SRC_AAAA1111"
KEY = "isolated-c5-runtime-no-user-data-secret"


class Memory:
    def __init__(self, service):
        self.service = service

    def list_memories(self, *, project_id, include_deleted=False):
        assert project_id == PROJECT and include_deleted is False
        return {
            "schema": "UR_WEB_PROJECT_MEMORY_LIST_R001",
            "project_id": PROJECT,
            "state_revision": self.service.memory_revision,
            "memories": copy.deepcopy(self.service.memory),
        }


class IsolatedOwner:
    def __init__(self, status, *, source_ids=None, memory=None, instructions=None):
        self._lock = threading.RLock()
        self.status = status
        self.instructions = instructions if instructions is not None else (
            "" if status == "RETIRED" else "synthetic-current-instructions"
        )
        self.source_ids = source_ids or []
        self.memory = memory or []
        self.memory_revision = 2
        self.memory_service = Memory(self)
        self.raw_reads = 0
        self.race_after_first_read = False
        self.foreign_source = False

    def _raw_project(self, project_id):
        assert project_id == PROJECT
        self.raw_reads += 1
        rev = 13 if self.race_after_first_read and self.raw_reads > 1 else 12
        return {
            "project_id": PROJECT,
            "status": self.status,
            "project_revision": rev,
            "project_instruction_binding": {"artifact_id": "SYNTHETIC_ONLY"},
            "source_ref_ids": copy.deepcopy(self.source_ids),
        }, {"revision": rev}


    def _load_exact_text_binding(self, binding):
        assert binding == {"artifact_id": "SYNTHETIC_ONLY"}
        return self.instructions

    def _source_ref(self, source_ref_id):
        assert source_ref_id in self.source_ids
        return {
            "project_id": "PRJ_UNRELATED" if self.foreign_source else PROJECT,
            "source_ref_id": source_ref_id,
            "origin_class": "CHAT_OUTPUT",
            "source_artifact_binding": {"sha256": "a" * 64},
            "provenance": {"conversation_id": "this-project-chat"},
        }, {"revision": 1}


def current_endpoint(owner):
    app = FastAPI()
    install_project_retirement_routes(app, lambda: owner)
    matches = [
        route for route in app.routes
        if route.path == "/api/web/projects/{project_id}/c5-reference-inventory"
    ]
    assert len(matches) == 1
    return matches[0].endpoint


def request(key=KEY):
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/api/web/projects/" + PROJECT + "/c5-reference-inventory",
        "query_string": b"",
        "headers": [(b"x-ur-runtime-proxy", key.encode("utf-8"))],
        "client": ("127.0.0.1", 31337),
        "server": ("127.0.0.1", 8000),
    })


def must_stop(fn, expected_status):
    try:
        fn()
    except HTTPException as err:
        assert err.status_code == expected_status, (err.status_code, expected_status)
    else:
        raise AssertionError("C5_REFERENCE_READ_FAILED_TO_STOP")


def main():
    original = os.environ.get("UR_RUNTIME_PROXY_KEY")
    os.environ["UR_RUNTIME_PROXY_KEY"] = KEY
    try:
        owner = IsolatedOwner("RETIRED")
        proof = current_endpoint(owner)(PROJECT, request())
        assert proof["project"]["status"] == "RETIRED"
        assert proof["project"]["source_ref_ids"] == []
        assert proof["sources"] == []
        assert proof["memory"]["memories"] == []
        assert proof["instructions"]["current_empty"] is True
        assert "job_scope" not in proof
        print("RETIRED_PROJECT_INDEPENDENT_REFERENCE_READBACK=PASS")

        owner = IsolatedOwner(
            "ACTIVE",
            source_ids=[SOURCE],
            memory=[{
                "project_id": PROJECT,
                "memory_id": "MEM_001",
                "memory_revision": 2,
                "lifecycle_state": "DISABLED",
                "content": "sensitive-memory-content-must-not-be-returned",
            }],
        )
        endpoint = current_endpoint(owner)
        current = endpoint(PROJECT, request())
        assert len(current["sources"]) == len(current["project"]["source_ref_ids"]) == 1
        assert len(current["memory"]["memories"]) == 1
        assert "sensitive-memory-content-must-not-be-returned" not in str(current)
        assert current["sources"][0]["source_ref"]["project_id"] == PROJECT
        assert current["instructions"]["current_empty"] is False
        assert "synthetic-current-instructions" not in str(current)
        assert "job_scope" not in current
        print("ACTIVE_PROJECT_SOURCE_MEMORY_METADATA_MINIMIZATION=PASS")
        print("HISTORICAL_GLOBAL_JOB_GATE_NOT_IN_SOURCE_MEMORY_PRODUCER=PASS")

        owner.raw_reads = 0
        owner.race_after_first_read = True
        must_stop(lambda: endpoint(PROJECT, request()), 409)
        owner.race_after_first_read = False
        owner.raw_reads = 0
        print("PROJECT_REVISION_CHANGE_DURING_INVENTORY=STOP")

        owner.foreign_source = True
        must_stop(lambda: endpoint(PROJECT, request()), 409)
        owner.foreign_source = False
        print("FOREIGN_SOURCE_REFERENCE=STOP")


        retired_with_stale_instructions = IsolatedOwner(
            "RETIRED", instructions="still-bound-private-instructions"
        )
        must_stop(
            lambda: current_endpoint(retired_with_stale_instructions)(PROJECT, request()),
            409,
        )
        print("RETIRED_PROJECT_STALE_INSTRUCTIONS_READBACK=STOP")

        must_stop(lambda: endpoint(PROJECT, request("not-authorized")), 401)
        print("UNAUTHORIZED_RUNTIME_REFERENCE_REQUEST=STOP")

        print("C5_NO_EFFECT_RETIRED_PROJECT_SOURCE_OWNER_TEST=PASS_6_CASES")
        print("LIVE_PROJECT_RUNTIME_MONGO_EFFECTS=0")
        print("PROOF_CEILING=ISOLATED_RUNTIME_REFERENCE_READBACK_NOT_PRODUCT_DELETE")
    finally:
        if original is None:
            os.environ.pop("UR_RUNTIME_PROXY_KEY", None)
        else:
            os.environ["UR_RUNTIME_PROXY_KEY"] = original


if __name__ == "__main__":
    main()
