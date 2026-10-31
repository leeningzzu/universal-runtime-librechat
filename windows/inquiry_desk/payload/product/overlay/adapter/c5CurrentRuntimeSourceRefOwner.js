'use strict';
/**
 * C5 scoped read-only projection of EXISTING canonical Runtime Project,
 * SourceRef and Project Memory owners. No new Source store or file graph.
 *
 * Native LibreChat controller authenticates actor/Project. The Runtime
 * resolve endpoint verifies the canonical logical Project identity. This
 * result proves only Runtime Project SourceRef/Memory scope, not that
 * native FileIDs, all Agent consumers, Blob, vector, writer or backup
 * are globally complete.
 */
const NATIVE_ID=/^[a-f0-9]{24}$/i;
const RUNTIME_ID=/^PRJ_[A-Za-z0-9_]+$/;
const SHA=/^[a-f0-9]{64}$/i;
class C5RuntimeSourceOwnerStop extends Error {
  constructor(code){super(code);this.code=code;this.name='C5RuntimeSourceOwnerStop';}
}
function check(ok,code){if(!ok)throw new C5RuntimeSourceOwnerStop(code);}
function captureCurrentProjectRuntimeReferences({
  nativeProjectId,actorId,resolved,resumed,memory,
}) {
  check(NATIVE_ID.test(nativeProjectId) && NATIVE_ID.test(actorId),
    'C5_NATIVE_PROJECT_ACTOR_IDENTITY_REQUIRED');
  check(resolved?.found===true && RUNTIME_ID.test(resolved.project_id||'') &&
    Number.isInteger(resolved.project_revision) && resolved.project_revision>0 &&
    ['ACTIVE','RETIRE_PENDING','RETIRED'].includes(resolved.status),
    'C5_CANONICAL_RUNTIME_PROJECT_NOT_RESOLVED');
  const project=resumed?.project;
  check(project && project.project_id===resolved.project_id &&
    project.project_revision===resolved.project_revision &&
    project.status===resolved.status &&
    Array.isArray(project.source_ref_ids) && Array.isArray(resumed.sources) &&
    Array.isArray(resumed.retirement_sources) &&
    typeof resumed.protected_asset_census_sha256==='string' &&
    SHA.test(resumed.protected_asset_census_sha256),
    'C5_CANONICAL_RUNTIME_PROJECT_REFERENCE_CURRENTNESS_LOST');
  check(resumed.instructions &&
    typeof resumed.instructions.current_empty==='boolean' &&
    (resolved.status!=='RETIRED' ||
      resumed.instructions.current_empty===true),
    'C5_CANONICAL_RUNTIME_PROJECT_INSTRUCTIONS_NOT_CLEARED');
  // This is a SOURCE/MEMORY projection, not a JobAuthority scan or release
  // admission. Historical/global Job evidence must not block native Project
  // Source reads. The independent current TARGET_PROJECT_CURRENT_EFFECTS
  // admissionOwner owns executable/in-flight Job and writer/backup checks.
  const ids=project.source_ref_ids;
  check(ids.length<=20000 && new Set(ids).size===ids.length &&
    ids.every(id=>typeof id==='string' && id.length>0 && id.length<=256),
    'C5_RUNTIME_SOURCE_REFERENCE_IDS_INVALID');
  check(resumed.sources.length===ids.length,
    'C5_RUNTIME_SOURCE_REFERENCE_COUNT_MISMATCH');
  const expected=new Set(ids),seen=new Set();
  const sources=[];
  for(const row of resumed.sources){
    const ref=row?.source_ref;
    const binding=row?.binding;
    const artifact=ref?.source_artifact_binding;
    check(ref && ref.project_id===resolved.project_id &&
      typeof ref.source_ref_id==='string' &&
      expected.has(ref.source_ref_id) && !seen.has(ref.source_ref_id) &&
      artifact && typeof artifact.sha256==='string' &&
      SHA.test(artifact.sha256) && binding &&
      Number.isInteger(binding.revision) && binding.revision>0,
      'C5_RUNTIME_SOURCE_REFERENCE_OWNER_OR_ARTIFACT_INCOMPLETE');
    seen.add(ref.source_ref_id);
    // Crucial: SourceRef origin_class is NOT a native LibreChat file_id.
    // Keep only identities; a separate File/Agent/Library owner must check
    // cross-consumer FileIDs before any physical file deletion.
    sources.push({
      source_ref_id:ref.source_ref_id,
      origin_class:typeof ref.origin_class==='string'?ref.origin_class:null,
      source_sha256:artifact.sha256,
      origin_conversation_id:
        typeof ref.provenance?.conversation_id==='string'?
        ref.provenance.conversation_id:null,
    });
  }
  check(seen.size===expected.size,
    'C5_RUNTIME_SOURCE_REFERENCE_GRAPH_NOT_EXHAUSTIVE');
  check(resumed.retirement_sources.length<=20000,
    'C5_RUNTIME_RETIREMENT_SOURCE_ROWS_UNBOUNDED');
  const retirementSources=[];
  const retirementIds=new Set();
  const activeRetirementIds=new Set();
  for(const row of resumed.retirement_sources){
    const binding=row?.completed_native_binding;
    check(row && typeof row.source_ref_id==='string' &&
      row.source_ref_id.length>0 && row.source_ref_id.length<=256 &&
      !retirementIds.has(row.source_ref_id) &&
      typeof row.filename==='string' && row.filename.length>0 &&
      typeof row.origin_input_sha256==='string' &&
      SHA.test(row.origin_input_sha256) &&
      Number.isInteger(row.origin_input_byte_size) &&
      row.origin_input_byte_size>0 &&
      Number.isInteger(row.shared_content_artifact_count) &&
      row.shared_content_artifact_count>=0 &&
      typeof row.active_project_binding==='boolean' &&
      ['ACTIVE','DETACHED_RETAINED','CONTENT_RETIRED'].includes(row.retirement_state),
    'C5_RUNTIME_RETIREMENT_SOURCE_ROW_INVALID');
    if(row.retirement_state==='CONTENT_RETIRED'){
      check(binding && typeof binding==='object' &&
        binding.binding_class==='EXACT_RUNTIME_SOURCE_ONLY' &&
        Array.isArray(binding.native_file_ids) &&
        binding.native_file_ids.length===0 &&
        Array.isArray(binding.source_ref_ids) &&
        binding.source_ref_ids.length===1 &&
        binding.source_ref_ids[0]===row.source_ref_id &&
        typeof binding.binding_evidence_sha256==='string' &&
        SHA.test(binding.binding_evidence_sha256),
      'C5_RUNTIME_RETIREMENT_SOURCE_COMPLETION_INVALID');
    } else {
      check(binding==null,
        'C5_RUNTIME_RETIREMENT_SOURCE_COMPLETION_STATE_MISMATCH');
    }
    retirementIds.add(row.source_ref_id);
    if(row.active_project_binding===true) activeRetirementIds.add(row.source_ref_id);
    retirementSources.push({
      source_ref_id:row.source_ref_id,
      filename:row.filename,
      origin_input_sha256:row.origin_input_sha256,
      origin_input_byte_size:row.origin_input_byte_size,
      shared_content_artifact_count:row.shared_content_artifact_count,
      active_project_binding:row.active_project_binding,
      retirement_state:row.retirement_state,
      completed_native_binding:binding==null?null:{
        binding_class:binding.binding_class,
        native_file_ids:[...binding.native_file_ids],
        source_ref_ids:[...binding.source_ref_ids],
        binding_evidence_sha256:binding.binding_evidence_sha256,
      },
    });
  }
  check(activeRetirementIds.size===expected.size &&
    [...expected].every(id=>activeRetirementIds.has(id)),
  'C5_RUNTIME_RETIREMENT_ACTIVE_SOURCE_SET_MISMATCH');
  check(memory && memory.schema==='UR_WEB_PROJECT_MEMORY_LIST_R001' &&
    memory.project_id===resolved.project_id &&
    Number.isInteger(memory.state_revision) &&
    memory.state_revision>=0 && Array.isArray(memory.memories),
    'C5_RUNTIME_PROJECT_MEMORY_OWNER_UNAVAILABLE');
  const remembered=new Set();
  let activeMemories=0;
  for(const item of memory.memories){
    check(item && typeof item.memory_id==='string' &&
      item.memory_id.length>0 && !remembered.has(item.memory_id) &&
      Number.isInteger(item.memory_revision) && item.memory_revision>0 &&
      item.project_id===resolved.project_id &&
      ['ACTIVE','DISABLED'].includes(item.lifecycle_state),
      'C5_RUNTIME_MEMORY_REFERENCE_STATE_INCOMPLETE');
    remembered.add(item.memory_id);
    if(item.lifecycle_state==='ACTIVE')activeMemories++;
  }
  return {
    schema:'AIDES_C5_CANONICAL_RUNTIME_PROJECT_REFERENCES_R001',
    authority_class:'CURRENT_RUNTIME_PROJECT_SOURCE_REF_AND_MEMORY_READ_ONLY',
    nativeProjectId,
    actorId,
    runtimeProjectId:resolved.project_id,
    runtimeProjectRevision:project.project_revision,
    runtimeProjectStatus:project.status,
    sourceRefsProvenComplete:true,
    projectInstructionsCurrentEmpty:resumed.instructions.current_empty,
    // No Job PASS is claimed here: actual target-Project admission is a
    // separate point-of-effect authority with its own currentness proof.
    sourceRefCount:ids.length,
    sources,
    retirementSourceCount:retirementSources.length,
    retirementSources,
    protectedAssetCensusSha256:resumed.protected_asset_census_sha256,
    memoryStateRevision:memory.state_revision,
    visibleMemoryCount:memory.memories.length,
    activeMemoryCount:activeMemories,
    nativeFileReferencesProvenComplete:false,
    physicalBlobOrVectorDeletionProven:false,
    writerBackupAdmissionProven:false,
  };
}
module.exports={captureCurrentProjectRuntimeReferences,C5RuntimeSourceOwnerStop};
