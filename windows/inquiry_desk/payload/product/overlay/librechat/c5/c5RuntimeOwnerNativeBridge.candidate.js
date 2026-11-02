'use strict';
const { isC5CanonicalNativeRetirementHandler } =
  require('./c5CanonicalNativeRetirement.candidate.js');
/**
 * Aides C5 current native route -> existing Adapter -> Runtime owner bridge.
 * Pure C5-specific composition: NO second Project DB/Runtime/router/Job engine.
 *
 * The caller must be an authenticated LibreChat owner whose exact
 * DELETE /api/projects/:projectId request is already owned by the native
 * Project controller. This adapter does not create Runtime Project records.
 * It composes the accepted C5 native retirement handler and the exact same
 * protected Adapter/Runtime receipt endpoints. Missing/foreign state fails
 * closed; unknown-effect response always stays PARTIAL, not success.
 */
class C5RuntimeBridgeStop extends Error {
  constructor(code) { super(code); this.code=code; this.name='C5RuntimeBridgeStop'; }
}
const requireState=(truth,code)=>{if(!truth)throw new C5RuntimeBridgeStop(code);};
const ID=/^[a-f0-9]{24}$/i;
function createC5RuntimeOwnerNativeBridge({
  request, nativeC5RetirementHandler,
  adapterBase = process.env.UR_RUNTIME_ADAPTER_BASE,
  shellKey = process.env.UR_SHELL_ADAPTER_KEY,
  doFetch = globalThis.fetch,
}) {
  requireState(isC5CanonicalNativeRetirementHandler(nativeC5RetirementHandler),
    'C5_NATIVE_RETIREMENT_HANDLER_NOT_CANONICAL_RUNTIME_ONLY');
  const p=String(request?.params?.projectId||'');
  const u=String(request?.user?.id||request?.user?._id||'');
  requireState(ID.test(p)&&ID.test(u),'C5_AUTHENTICATED_NATIVE_OWNER_INVALID');
  requireState(typeof shellKey==='string'&&shellKey.length>=12,
    'C5_EXISTING_ADAPTER_AUTH_KEY_UNAVAILABLE');
  requireState(typeof adapterBase==='string'&&adapterBase.length>0,
    'C5_CURRENT_ADAPTER_BASE_UNAVAILABLE');
  const base=new URL(adapterBase);
  requireState(base.protocol==='http:'&&
    ['c5-adapter','ur-runtime-adapter','ur-web-r004-daily-adapter-r005','127.0.0.1'].includes(base.hostname)&&
    base.pathname==='/'&& !base.username && !base.password && !base.hash,
    'C5_CURRENT_INTERNAL_ADAPTER_ORIGIN_INVALID');
  requireState(typeof doFetch==='function','C5_NATIVE_FETCH_UNAVAILABLE');

  const reqHeaders={
    Authorization:'Bearer '+shellKey,
    'X-LibreChat-Project-ID':p,
    'X-LibreChat-Authenticated-User-ID':u,
    Accept:'application/json',
  };

  async function viaAdapter(method,path,payload,confirmedNativeProjectDelete=false) {
    requireState(confirmedNativeProjectDelete===false || (
      method==='POST' && path==='/v1/runtime-project-retirement/ensure'),
    'C5_CONFIRMED_DELETE_INTENT_MUST_BE_EFFECT_SCOPED');
    let response;
    try {
      response=await doFetch(base.origin+path,{
        method,headers:{
          ...reqHeaders,
          ...(payload!==undefined?{'Content-Type':'application/json'}:{}),
          ...(confirmedNativeProjectDelete?{
            'X-C5-Native-Project-Delete-Intent':'confirmed-irreversible-project-delete'
          }:{})
        },
        ...(payload!==undefined?{body:JSON.stringify(payload)}:{}),
        redirect:'error',cache:'no-store',
      });
    } catch {
      throw new C5RuntimeBridgeStop('C5_RUNTIME_ADAPTER_OUTCOME_UNKNOWN');
    }
    requireState(response?.status===200,
      'C5_RUNTIME_ADAPTER_REJECTED_OR_STALE');
    let result;
    try{result=await response.json();}
    catch{throw new C5RuntimeBridgeStop('C5_RUNTIME_ADAPTER_RESULT_UNREADABLE');}
    requireState(result&&typeof result==='object'&&!Array.isArray(result),
      'C5_RUNTIME_ADAPTER_RESULT_INVALID');
    return result;
  }

  function verifyActor(projectId,ownerId) {
    requireState(projectId===p&&ownerId===u,
      'C5_RUNTIME_OWNER_OR_PROJECT_SCOPE_CHANGED');
  }

  async function loadOperationReceipt({projectId,ownerId}){
    verifyActor(projectId,ownerId);
    const result=await viaAdapter(
      'GET','/v1/runtime-project-cascade-receipt');
    requireState(typeof result.found==='boolean',
      'C5_RUNTIME_RECEIPT_FOUND_STATUS_MISSING');
    if(!result.found){
      requireState(result.record===null,
        'C5_RUNTIME_RECEIPT_ABSENCE_AMBIGUOUS');
      return null;
    }
    requireState(result.record?.projectId===p&&result.record?.ownerId===u&&
      result.record?.schema==='C5_PROJECT_CASCADE_R001'&&
      Number.isInteger(result.record?.c5_receipt_revision),
      'C5_RUNTIME_RECEIPT_FOREIGN_OR_STALE');
    return result.record;
  }

  async function persistOperationReceipt(record) {
    requireState(record?.projectId===p&&record?.ownerId===u&&
      record?.schema==='C5_PROJECT_CASCADE_R001',
      'C5_RUNTIME_RECEIPT_WRITE_SCOPE_CHANGED');
    const saved=await viaAdapter(
      'POST','/v1/runtime-project-cascade-receipt',record);
    requireState(saved.durable===true&&saved.projectId===p&&
      saved.ownerId===u&&Number.isInteger(saved.revision)&&
      saved.revision>0,
      'C5_RUNTIME_RECEIPT_PERSISTENCE_UNVERIFIED');
    return saved;
  }

  async function executeAcceptedRetirement(actualRequest) {
    requireState(actualRequest===request,
      'C5_NATIVE_RETIREMENT_REQUEST_IDENTITY_CHANGED');
    // No fallthrough into upstream native-only unassign when the canonical
    // Runtime owner is absent, stale or already in an effect phase.
    const current = await readRetirementState({projectId:p,ownerId:u});
    requireState(current.status==='ACTIVE',
      'C5_CANONICAL_RUNTIME_PRE_EFFECT_ACTIVE_STATE_REQUIRED');

    let result;
    const capture={
      statusCode:200,data:null,
      status(code){this.statusCode=code;return this;},
      json(data){this.data=data;return this;},
    };
    try{await nativeC5RetirementHandler(request,capture);}
    catch{throw new C5RuntimeBridgeStop('C5_NATIVE_RETIREMENT_OUTCOME_UNKNOWN');}
    requireState(capture.statusCode===200&&
      capture.data?.retirement_state==='RETIRED'&&
      capture.data?.native_only!==true,
      'C5_NATIVE_RUNTIME_RETIREMENT_NOT_CONFIRMED');
    result={status:200,nativeAndRuntimeConfirmed:true};
    return result;
  }

  async function readNativeProjectBoundState({projectId,ownerId}){
    verifyActor(projectId,ownerId);
    const result=await viaAdapter('GET','/v1/runtime-project-retirement');
    if(result.found===false){
      requireState(result.native_only_verified===true &&
        /^PRJ_[A-Za-z0-9_]{8,128}$/.test(result.project_id||''),
        'C5_NATIVE_ONLY_RUNTIME_ORPHAN_STATE_UNVERIFIED');
      return result;
    }
    requireState(result.found===true &&
      /^PRJ_[A-Za-z0-9_]{8,128}$/.test(result.project_id||'') &&
      ['ACTIVE','RETIRE_PENDING','RETIRED'].includes(result.status) &&
      Number.isInteger(result.project_revision) && result.project_revision>0,
      'C5_EXISTING_CANONICAL_RUNTIME_PROJECT_NOT_PROVEN');
    return result;
  }
  async function ensureNativeProjectBoundForDelete({
    projectId,ownerId,admissionProven,
  }){
    verifyActor(projectId,ownerId);
    requireState(admissionProven===true,
      'C5_NATIVE_RUNTIME_ENROLLMENT_WRITER_BACKUP_ADMISSION_REQUIRED');
    const existing=await readNativeProjectBoundState({projectId,ownerId});
    if(existing.found===true)return {...existing,newly_bound:false};
    // Confirmed authenticated Project DELETE only, after user Project
    // owner, accepted C5 writer/backup and scope verification in caller.
    const after=await viaAdapter(
      'POST','/v1/runtime-project-retirement/ensure',undefined,true,
    );
    requireState(after.found===true && after.project_id===existing.project_id &&
      after.status==='ACTIVE' && after.newly_bound===true &&
      Number.isInteger(after.project_revision) && after.project_revision>0,
      'C5_NATIVE_PROJECT_RUNTIME_ENROLLMENT_RESULT_UNVERIFIED');
    return after;
  }

  async function readRetirementState({projectId,ownerId}) {
    verifyActor(projectId,ownerId);
    const current=await readNativeProjectBoundState({projectId,ownerId});
    requireState(current.found===true &&
      ['ACTIVE','RETIRE_PENDING','RETIRED'].includes(current.status) &&
      Number.isInteger(current.project_revision),
      'C5_NATIVE_RUNTIME_RETIREMENT_STATE_UNVERIFIED');
    return {
      authoritative:true,projectId:p,status:current.status,
      project_revision:current.project_revision,
    };
  }


  async function readCurrentRuntimeReferences({projectId,ownerId}) {
    verifyActor(projectId,ownerId);
    const current=await viaAdapter(
      'GET','/v1/runtime-project-c5-source-ref-inventory');
    requireState(
      current.schema==='AIDES_C5_CANONICAL_RUNTIME_PROJECT_REFERENCES_R001' &&
      current.authority_class==='CURRENT_RUNTIME_PROJECT_SOURCE_REF_AND_MEMORY_READ_ONLY' &&
      current.nativeProjectId===p && current.actorId===u &&
      /^PRJ_[A-Za-z0-9_]+$/.test(current.runtimeProjectId||'') &&
      Number.isInteger(current.runtimeProjectRevision) &&
      current.runtimeProjectRevision>0 &&
      ['ACTIVE','RETIRE_PENDING','RETIRED'].includes(current.runtimeProjectStatus) &&
      current.sourceRefsProvenComplete===true &&
      Number.isInteger(current.sourceRefCount) && current.sourceRefCount>=0 &&
      Array.isArray(current.sources) &&
      current.sources.length===current.sourceRefCount &&
      Number.isInteger(current.memoryStateRevision) &&
      current.memoryStateRevision>=0 &&
      Number.isInteger(current.visibleMemoryCount) &&
      current.visibleMemoryCount>=0,
      'C5_RUNTIME_SOURCE_REF_MEMORY_READBACK_UNVERIFIED');
    return current;
  }
  return {
    loadOperationReceipt,persistOperationReceipt,
    executeAcceptedRetirement,readRetirementState,
    readNativeProjectBoundState,ensureNativeProjectBoundForDelete,
    readCurrentRuntimeReferences,
  };
}
module.exports={createC5RuntimeOwnerNativeBridge,C5RuntimeBridgeStop};
