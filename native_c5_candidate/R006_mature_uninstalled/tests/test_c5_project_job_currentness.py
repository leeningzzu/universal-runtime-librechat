"""No-effect C5 scoped Job admission source tests (synthetic input only)."""
from __future__ import annotations
import hashlib
import sys
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.dont_write_bytecode = True
sys.path.insert(0,str(ROOT/"src"))
import universal_runtime
universal_runtime.__path__.insert(0,str(Path(__file__).parent/"universal_runtime"))
from universal_runtime.core.job_authority import JobAuthorityRegistry
from universal_runtime.core.formal_model_job import FormalModelJobError
from universal_runtime.running_job_currentness import RunningJobPinCurrentnessProjection
from universal_runtime.c5_project_job_currentness import (
    project_scoped_job_facts,C5ProjectJobCurrentnessStop,
)

TARGET="PRJ_0123456789ABCDEF0123456789AB"
OTHER="PRJ_FEDCBA9876543210FEDCBA987654"
assert TARGET!=OTHER

def source(job,initial,scope):
    intake_sha=hashlib.sha256(("intake"+job).encode()).hexdigest()
    input_sha=hashlib.sha256(("input"+job).encode()).hexdigest()
    legacy="CURRENT_TEST_EVENT_"+job
    pair={
        "project_id":scope,"chat_id":"CHAT_"+job,
        "initiating_user_event_id":legacy,
        "initiating_user_event_artifact_id":"WEB_EVENT_"+job,
        "initiating_user_event_artifact_identity_sha256":
            hashlib.sha256(("LEGACY_ARTIFACT_ID:WEB_EVENT_"+job).encode()).hexdigest(),
        "initiating_user_event_artifact_revision":1,
        "initiating_user_event_artifact_sha256":"f"*64,
        "initiating_content_sha256":"e"*64,
        "accepted_chat_revision":3,
        "accepted_head_event_id":"EVENT_"+job,
    }
    intake=dict(pair,schema="WEB_FORMAL_JOB_INTAKE_BINDING_V1",
                job_id=job,job_bundle_sha256="d"*64)
    inp=dict(pair,schema="RUNTIME_S1_GENERAL_CHAT_INPUT_SET_V1")
    row={
        "job_id":job,"job_authority_event_id":initial,
        "job_bundle_sha256":"d"*64,
        "web_formal_job_intake_binding_sha256":intake_sha,
        "web_formal_job_intake_artifact_identity_sha256":hashlib.sha256(("ii"+job).encode()).hexdigest(),
        "web_formal_job_intake_artifact_revision":1,
        "web_formal_job_intake_artifact_sha256":intake_sha,
        "input_set_sha256":input_sha,
        "input_set_artifact_identity_sha256":hashlib.sha256(("is"+job).encode()).hexdigest(),
        "input_set_artifact_revision":1,
        "input_set_artifact_sha256":input_sha,
    }
    return row,{intake_sha:intake,input_sha:inp}

class Ledger:
    def __init__(self,sources):self.sources=sources;self.read_count=0
    def load_record(self,binding):
        self.read_count+=1
        try:
            return deepcopy(self.sources[binding["artifact_sha256"]])
        except KeyError as error:
            raise FormalModelJobError(
                "STALE_OR_TAMPERED", "missing synthetic-only historical Intake"
            ) from error

class Authority:
    _require_initial_input_set_matches_intake=staticmethod(
        JobAuthorityRegistry._require_initial_input_set_matches_intake
    )

def fixture():
    x,bx=source("JOB_A","JAE_A",TARGET)
    y,by=source("JOB_B","JAE_B",OTHER)
    return [x,y],Ledger({**bx,**by})

def projection(running,orphan,terminal):
    return RunningJobPinCurrentnessProjection(
        running_pins=tuple(object() for _ in running),
        evidence={
            "initial_job_count":2,
            "schema_revision":"RUNTIME_RUNNING_JOB_PIN_CURRENTNESS_R001",
            "source_authority":"JOB_AUTHORITY_PLUS_FORMAL_MODEL_JOB_PLUS_HUMAN_DECISION",

            "running_job_count":len(running),
            "orphaned_nonexecutable_job_count":len(orphan),
            "terminal_job_count":len(terminal),
            "running_jobs":[{"job_id":j,"initial_job_authority_event_id":"JAE_"+j[-1]} for j in running],
            "orphaned_nonexecutable_jobs":[{
                "job_id":j,
                "initial_job_authority_event_id":"JAE_"+j[-1],
                "disposition":"ORPHANED_NONEXECUTABLE",
                "reason_code":"R009OpaqueArtifactError",
            } for j in orphan],
            "terminal_jobs":[{"job_id":j,"initial_job_authority_event_id":"JAE_"+j[-1]} for j in terminal],
        }
    )

def read(initial,ledger,p):
    return project_scoped_job_facts(
        target_project_id=TARGET, initial_sources=initial,
        projection=p, formal_ledger=ledger,
        job_authority=Authority(),
    )

def stop(fn,expected):
    try:fn()
    except C5ProjectJobCurrentnessStop as err:
        assert str(err)==expected,(str(err),expected)
    else:raise AssertionError("C5_FALSE_JOB_SCOPE_ACCEPTANCE")

def main():
    cases=0
    first,ledger=fixture()
    # Another Project's pinned running Job must never be reported as
    # directly belonging to this Project.
    result=read(first,ledger,projection(["JOB_B"],[],["JOB_A"]))
    assert result["project_effect_safe_from_job_history"] is True
    assert result["global_active_pinned_jobs"]==1
    assert result["project_active_pinned_jobs"]==0
    assert result["writer_exclusivity_proven"] is False
    assert result["backup_restore_proven"] is False
    assert result["delete_permitted"] is False
    cases+=1
    # Target Job still running => strict C5 STOP, regardless of global count.
    result=read(first,ledger,projection(["JOB_A"],[],["JOB_B"]))
    assert result["project_active_pinned_jobs"]==1
    assert result["project_effect_safe_from_job_history"] is False
    cases+=1
    # First-party nonexecutable old Job is protected history, not live effect.
    result=read(first,ledger,projection([],["JOB_A"],["JOB_B"]))
    assert result["project_unresolved_nonexecutable_jobs"]==0
    assert result["protected_nonexecutable_history_without_project_scope"]==1
    assert result["project_effect_safe_from_job_history"] is True
    cases+=1
    # Unrelated orphan is not implicitly the current Project's live Job.
    result=read(first,ledger,projection([],["JOB_B"],["JOB_A"]))
    assert result["project_effect_safe_from_job_history"] is True
    assert result["global_unresolved_jobs"]==1
    cases+=1
    # The actual machine has missing Intake for 79 FIRST-PARTY
    # nonexecutable historical rows. This must not make a NEW Project's
    # read-only readiness fail forever. Records remain protected/unscoped,
    # while REAL writer/backup deletion permission is still False.
    missing=Ledger(deepcopy(ledger.sources))
    missing.sources.pop(first[1]["web_formal_job_intake_artifact_sha256"])
    result=read(first,missing,projection([],["JOB_B"],["JOB_A"]))
    assert result["protected_nonexecutable_history_without_project_scope"]==1
    assert result["unscoped_historical_job_project_ids"]=="NOT_RECOVERABLE_DO_NOT_INFER"
    assert result["project_effect_safe_from_job_history"] is True
    assert result["global_unresolved_jobs"]==1
    assert result["writer_exclusivity_proven"] is False
    assert result["backup_restore_proven"] is False
    assert result["delete_permitted"] is False
    cases+=1
    # A missing Intake on a RUNNABLE Job must still STOP, never be accepted.
    missing_running=Ledger(deepcopy(ledger.sources))
    missing_running.sources.pop(first[0]["web_formal_job_intake_artifact_sha256"])
    stop(lambda:read(first,missing_running,projection(["JOB_A"],[],["JOB_B"])),
         "C5_CURRENT_EXECUTABLE_JOB_INTAKE_UNVERIFIED")
    cases+=1
    # An orphan with an unrecognized reason cannot be excluded from scope.
    invalid=projection([],["JOB_B"],["JOB_A"])
    invalid.evidence["orphaned_nonexecutable_jobs"][0]["reason_code"]="UNKNOWN"
    stop(lambda:read(first,missing,invalid),
         "C5_NONEXECUTABLE_HISTORY_CLASS_NOT_EXACT")
    cases+=1
    # The formerly accepted global historical-input gate was overbroad:
    # malformed SHA or old JAE identity on a classified TERMINAL record
    # must not block current unrelated Project admission or open old Intake.
    corrupted=deepcopy(first)
    corrupted[0]["web_formal_job_intake_binding_sha256"]="0"*64
    empty_ledger=Ledger({})
    past=read(corrupted,empty_ledger,projection([],[],["JOB_A","JOB_B"]))
    assert past["project_effect_safe_from_job_history"]
    assert empty_ledger.read_count==0
    cases+=1
    wrong=deepcopy(first)
    wrong[0]["job_authority_event_id"]="JAE_SWITCHED"
    past=read(wrong,Ledger({}),projection([],[],["JOB_A","JOB_B"]))
    assert past["project_effect_safe_from_job_history"]
    cases+=1
    # A CURRENT runnable Job with the same defects must still STOP.
    stop(lambda:read(corrupted,ledger,projection(["JOB_A"],[],["JOB_B"])),
         "C5_CURRENT_EXECUTABLE_INITIAL_BINDING_DISAGREES")
    cases+=1
    stop(lambda:read(wrong,ledger,projection(["JOB_A"],[],["JOB_B"])),
         "C5_JOB_CURRENT_TO_INITIAL_SCOPE_NOT_PROVEN")
    cases+=1
    broken=projection([],[],["JOB_A","JOB_B"])
    broken.evidence["terminal_jobs"].pop()
    stop(lambda:read(first,ledger,broken),
         "C5_EXACT_JOB_CURRENTNESS_ROWS_INCOMPLETE")
    cases+=1
    intake_corrupted=Ledger(deepcopy(ledger.sources))
    key=first[0]["web_formal_job_intake_artifact_sha256"]
    intake_corrupted.sources[key]["project_id"]=OTHER
    stop(lambda:read(first,intake_corrupted,projection(["JOB_A"],[],["JOB_B"])),
         "C5_RUNTIME_INTAKE_PROVENANCE_NOT_MATCHED")
    cases+=1
    # Unrelated historical terminal artifacts are not opened as Project prereq.
    empty_ledger=Ledger({})
    proof=read(first,empty_ledger,projection([],[],["JOB_A","JOB_B"]))
    assert empty_ledger.read_count==0 and proof["project_effect_safe_from_job_history"]
    cases+=1
    only_other=Ledger(deepcopy(ledger.sources))
    proof=read(first,only_other,projection(["JOB_B"],[],["JOB_A"]))
    assert only_other.read_count==2 and proof["project_active_pinned_jobs"]==0
    cases+=1
    broken_scope=Ledger(deepcopy(ledger.sources))
    broken_scope.sources[first[0]["web_formal_job_intake_artifact_sha256"]]["schema"]="BAD"
    stop(lambda:read(first,broken_scope,projection(["JOB_A"],[],["JOB_B"])),
         "C5_CURRENT_EXECUTABLE_JOB_INTAKE_IDENTITY_CHANGED")
    cases+=1
    print("C5_NATIVE_PROJECT_SCOPED_JOB_AUTHORITY_REUSE=PASS")
    print("CASES="+str(cases))
    print("CURRENT_REAL_JOB_PROJECTION_EXECUTED=NO")
    print("OLD_JOB_AUTHORITY_SOURCES_MODIFIED=0")
    print("PROOF_CEILING=ISOLATED_NATIVE_SOURCE_MAPPING_NOT_RELEASE_ADMISSION")
if __name__=="__main__":
    main()
