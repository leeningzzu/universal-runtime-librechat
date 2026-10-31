'use strict';
const assert=require('node:assert/strict');
const {captureCurrentProjectRuntimeReferences}=
  require('./c5CurrentRuntimeSourceRefOwner.candidate.js');
const NATIVE='507f1f77bcf86cd799439011',OWNER='507f191e810c19729de860ea';
const PRJ='PRJ_0123456789ABCDEF0123456789AB';
let cases=0,assertions=0;
const equal=(a,b)=>{assert.deepEqual(a,b);assertions++};
const clone=x=>JSON.parse(JSON.stringify(x));
function fixture(){
  const resolved={found:true,project_id:PRJ,project_revision:9,status:'ACTIVE'};
  const sourceId='SRC_0123456789ABCDEF';
  const resumed={
    project:{project_id:PRJ,project_revision:9,status:'ACTIVE',
      source_ref_ids:[sourceId]},
    sources:[{
      // First-party Project Instructions canonical currentness, never text.
      source_ref:{
        source_ref_id:sourceId,project_id:PRJ,
        origin_class:'CHAT_OUTPUT',
        provenance:{conversation_id:'owned-conversation'},
        source_artifact_binding:{sha256:'a'.repeat(64)},
      },
      binding:{revision:1,sha256:'b'.repeat(64)},
    }],
    instructions:{current_empty:false},
    job_scope:{
      schema:'AIDES_C5_PROJECT_JOB_SCOPE_FROM_NATIVE_AUTHORITY_R001',
      source:'RUNTIME_JOB_AUTHORITY_FORMAL_INTAKE_INPUT_SET_CURRENTNESS',
      logical_project_id:PRJ,scope_verified:true,
      initial_membership_sha256:'a'.repeat(64),
      running_projection_sha256:'b'.repeat(64),
      project_active_pinned_jobs:0,
      project_unresolved_nonexecutable_jobs:0,
      project_terminal_history_scope:'NOT_EVALUATED_NOT_DELETE_RELEVANT',
      global_active_pinned_jobs:1,
      global_unresolved_jobs:0,
      protected_nonexecutable_history_without_project_scope:0,
      project_effect_safe_from_job_history:true,
      writer_exclusivity_proven:false,backup_restore_proven:false,
      delete_permitted:false,
    },

  };
  const memory={
    schema:'UR_WEB_PROJECT_MEMORY_LIST_R001',
    project_id:PRJ,state_revision:3,
    memories:[
      {memory_id:'MEM_AAAA',project_id:PRJ,memory_revision:1,lifecycle_state:'ACTIVE'},
      {memory_id:'MEM_BBBB',project_id:PRJ,memory_revision:2,lifecycle_state:'DISABLED'},
    ],
  };
  return {nativeProjectId:NATIVE,actorId:OWNER,resolved,resumed,memory};
}
function rejects(change,code){
  const x=fixture();change(x);
  assert.throws(()=>captureCurrentProjectRuntimeReferences(x),err=>err?.code===code);
  assertions++;cases++;
}
{
 const p=captureCurrentProjectRuntimeReferences(fixture());
 equal(p.nativeProjectId,NATIVE);equal(p.actorId,OWNER);
 equal(p.projectInstructionsCurrentEmpty,false);
 equal(Object.hasOwn(p,'projectJobsScopeVerified'),false);
 equal(Object.hasOwn(p,'projectActivePinnedJobs'),false);
 equal(p.sourceRefsProvenComplete,true);equal(p.sourceRefCount,1);
 equal(p.sources[0].source_ref_id,'SRC_0123456789ABCDEF');
 equal(p.activeMemoryCount,1);equal(p.visibleMemoryCount,2);
 equal(p.writerBackupAdmissionProven,false);
 equal(p.nativeFileReferencesProvenComplete,false);
 equal(p.physicalBlobOrVectorDeletionProven,false);
 cases++;
}
{
 const x=fixture();x.resolved.status='RETIRED';x.resolved.project_revision=10;
 x.resumed.project.status='RETIRED';x.resumed.project.project_revision=10;
 x.resumed.project.source_ref_ids=[];x.resumed.sources=[];
 x.resumed.instructions.current_empty=true;
 x.memory.memories=[];x.memory.state_revision=4;
 const p=captureCurrentProjectRuntimeReferences(x);
 equal(p.runtimeProjectStatus,'RETIRED');equal(p.sourceRefCount,0);
 equal(p.visibleMemoryCount,0);cases++;
 equal(p.projectInstructionsCurrentEmpty,true);
}


{
 // Accepted R044: old global 113 JobAuthority records are not a Project
 // SourceRef/Memory precondition. Current target executable/in-flight work
 // is independently checked by the native point-of-effect admissionOwner.
 const x=fixture();
 x.resumed.job_scope.project_active_pinned_jobs=1;
 x.resumed.job_scope.project_effect_safe_from_job_history=false;
 x.resumed.job_scope.global_unresolved_jobs=113;
 x.resumed.job_scope.project_terminal_history_scope='HISTORY_UNBOUNDED';
 x.resumed.job_scope.scope_verified=false;
 x.resumed.job_scope.logical_project_id='PRJ_HISTORICAL_FOREIGN';
 const p=captureCurrentProjectRuntimeReferences(x);
 equal(p.sourceRefsProvenComplete,true);
 equal(p.visibleMemoryCount,2);
 equal(Object.hasOwn(p,'projectJobsQuiescent'),false);
 cases++;
}
{
 const x=fixture();delete x.resumed.job_scope;
 const p=captureCurrentProjectRuntimeReferences(x);
 equal(p.runtimeProjectId,PRJ);cases++;
}
rejects(x=>{x.resolved.status='RETIRED';x.resumed.project.status='RETIRED';},
  'C5_CANONICAL_RUNTIME_PROJECT_INSTRUCTIONS_NOT_CLEARED');
rejects(x=>{x.resumed.project.project_revision=10},
  'C5_CANONICAL_RUNTIME_PROJECT_REFERENCE_CURRENTNESS_LOST');
rejects(x=>{x.resumed.project.source_ref_ids=[]},
  'C5_RUNTIME_SOURCE_REFERENCE_COUNT_MISMATCH');
rejects(x=>{x.resumed.sources[0].source_ref.project_id='PRJ_FOREIGN'},
  'C5_RUNTIME_SOURCE_REFERENCE_OWNER_OR_ARTIFACT_INCOMPLETE');
rejects(x=>{x.resumed.sources[0].source_ref.source_artifact_binding.sha256='NOT_SHA'},
  'C5_RUNTIME_SOURCE_REFERENCE_OWNER_OR_ARTIFACT_INCOMPLETE');
rejects(x=>{x.resumed.project.source_ref_ids.push(x.resumed.project.source_ref_ids[0])},
  'C5_RUNTIME_SOURCE_REFERENCE_IDS_INVALID');
rejects(x=>{x.memory.project_id='PRJ_FOREIGN'},
  'C5_RUNTIME_PROJECT_MEMORY_OWNER_UNAVAILABLE');
rejects(x=>{x.memory.memories[1].memory_id=x.memory.memories[0].memory_id},
  'C5_RUNTIME_MEMORY_REFERENCE_STATE_INCOMPLETE');
rejects(x=>{x.resolved.found=false},
  'C5_CANONICAL_RUNTIME_PROJECT_NOT_RESOLVED');
rejects(x=>{x.actorId='anonymous'},
  'C5_NATIVE_PROJECT_ACTOR_IDENTITY_REQUIRED');
console.log('C5_AUTHENTIC_RUNTIME_PROJECT_SOURCE_REF_MEMORY_PROJECTION=PASS');
console.log('SCENARIOS='+cases);
console.log('ASSERTIONS='+assertions);
console.log('REAL_RUNTIME_BACKEND_REUSED_PROJECT_RESUME_AND_MEMORY=SOURCE_CODE_CONFIRMED');
console.log('PRODUCTION_EFFECT=0');
console.log('PROOF_CEILING=ISOLATED_READ_ONLY_PROJECTION_SEMANTICS_NOT_LIVE_CURRENT_DATA');
