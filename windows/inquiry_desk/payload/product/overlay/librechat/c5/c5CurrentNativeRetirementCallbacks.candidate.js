'use strict';
/**
 * Current C5 native retirement owner bindings. Reuse the accepted native
 * Project handler and existing Adapter/Runtime Project-retirement endpoints.
 *
 * Distinct from full cascade: native Project retirement may unassign Chat
 * references temporarily before the C5 owner deletes owned Chats/Files.
 * Never expose native-only Project deletion or synthesize completion.
 *
 * No new DB, second HTTP server, task engine, alternate Runtime authority,
 * fixture fault injection, or external network.
 */
const ID=/^[a-f0-9]{24}$/i;
const ALLOWED_HOSTS=new Set([
  'ur-runtime-adapter','ur-web-r004-daily-adapter-r005','c5-adapter','127.0.0.1',
]);
class C5NativeRetirementOwnerStop extends Error {
  constructor(code){super(code);this.code=code;this.name='C5NativeRetirementOwnerStop';}
}
const requireOwner=(ok,code)=>{
  if(!ok)throw new C5NativeRetirementOwnerStop(code);
};
function createC5CurrentNativeRetirementCallbacks({
  request, nativeDb, nativeModels, upstreamProjectHandlers,
  adapterBase=process.env.UR_RUNTIME_ADAPTER_BASE,
  shellKey=process.env.UR_SHELL_ADAPTER_KEY,
  doFetch=globalThis.fetch,
}) {
  const projectId=String(request?.params?.projectId||'');
  const actor=String(request?.user?.id??request?.user?._id??'');
  requireOwner(ID.test(projectId)&&ID.test(actor),
    'C5_AUTHENTICATED_NATIVE_OWNER_PROJECT_REQUIRED');
  requireOwner(nativeDb && typeof nativeDb.getChatProject==='function' &&
    upstreamProjectHandlers && typeof upstreamProjectHandlers.deleteProject==='function',
    'C5_EXISTING_LIBRECHAT_PROJECT_DELETE_OWNER_UNAVAILABLE');
  requireOwner(nativeModels?.ChatProject && nativeModels?.Conversation,
    'C5_EXISTING_LIBRECHAT_PROJECT_MODELS_UNAVAILABLE');
  requireOwner(typeof shellKey==='string'&&shellKey.length>=12 &&
    typeof adapterBase==='string'&&typeof doFetch==='function',
    'C5_EXISTING_RUNTIME_ADAPTER_AUTH_UNAVAILABLE');
  const base=new URL(adapterBase);
  requireOwner(base.protocol==='http:'&&ALLOWED_HOSTS.has(base.hostname)&&
    base.pathname==='/'&&base.search===''&&!base.hash&&!base.username&&!base.password,
    'C5_EXISTING_RUNTIME_ADAPTER_ORIGIN_UNTRUSTED');

  async function retireViaAdapter(action,p,payload) {
    requireOwner(p===projectId &&
      ['get','prepare','confirm','abort','commit'].includes(action),
      'C5_ADAPTER_RETIREMENT_SCOPE_CHANGED');
    const url=base.origin+'/v1/runtime-project-retirement'+
      (action==='get'?'':'/'+action);
    let response;
    try {
      response=await doFetch(url,{
        method:action==='get'?'GET':'POST',
        headers:{
          Authorization:'Bearer '+shellKey,
          'X-LibreChat-Project-ID':projectId,
          'X-LibreChat-Authenticated-User-ID':actor,
          ...(action==='get'?{}:{
            'X-C5-Native-Project-Delete-Intent':'confirmed-irreversible-project-delete',
          }),
          Accept:'application/json',
          ...(payload===undefined?{}:{'Content-Type':'application/json'}),
        },
        ...(payload===undefined?{}:{body:JSON.stringify(payload)}),
        redirect:'error',cache:'no-store',
      });
    } catch {
      throw new C5NativeRetirementOwnerStop('C5_RUNTIME_ADAPTER_OUTCOME_UNKNOWN');
    }
    requireOwner(response?.status===200,'C5_RUNTIME_RETIREMENT_NOT_CONFIRMED');
    let body;
    try {body=await response.json();}
    catch {throw new C5NativeRetirementOwnerStop('C5_RUNTIME_RESULT_UNREADABLE');}
    requireOwner(body && typeof body==='object'&&!Array.isArray(body),
      'C5_RUNTIME_RETIREMENT_RESULT_INVALID');
    return body;
  }

  async function getRuntimeProject(p) {
    const current=await retireViaAdapter('get',p);
    // The canonical wrapper independently rejects found:false, even when
    // native-only verified, on every Runtime authority read.
    if (current.found!==true) return current;
    requireOwner(['ACTIVE','RETIRE_PENDING','RETIRED'].includes(current.status)&&
      Number.isInteger(current.project_revision)&&current.project_revision>0,
      'C5_RUNTIME_PROJECT_REVISION_OR_STATE_INVALID');
    return current;
  }
  async function verifyNativeDeletionComplete(req) {
    requireOwner(req===request,'C5_NATIVE_VERIFICATION_REQUEST_SWITCH');
    const [projects,assigned]=await Promise.all([
      nativeModels.ChatProject.countDocuments({_id:projectId}),
      nativeModels.Conversation.countDocuments({chatProjectId:projectId}),
    ]);
    // Strictly READ ONLY, no original unassign repair/updateMany:
    // unknown effects are reconciled by the existing durable C5 receipt.
    return {complete:projects===0&&assigned===0,
      reason:projects!==0?'NATIVE_PROJECT_REMAINS':assigned!==0?
        'NATIVE_PROJECT_CHAT_BINDINGS_REMAIN':'VERIFIED'};
  }
  async function deleteLibreChatProject(req) {
    requireOwner(req===request,'C5_NATIVE_DELETE_REQUEST_SWITCH');
    const captured={
      statusCode:200,body:null,
      status(n){this.statusCode=n;return this;},
      json(value){this.body=value;return this;},
    };
    // This is the exact current LibreChat handler with its own model writes,
    // not a handcrafted Mongo delete or synthetic response.
    await upstreamProjectHandlers.deleteProject(req,captured);
    requireOwner(captured.statusCode===200 &&
      captured.body?.deletedCount===1,
      'C5_NATIVE_PROJECT_EFFECT_UNKNOWN_OR_NOT_COMPLETE');
    return captured.body;
  }

  return {
    getRuntimeProject,
    prepareRuntimeRetirement:({projectId:p,retirementId,expectedProjectRevision})=>
      retireViaAdapter('prepare',p,{retirement_id:retirementId,
        expected_project_revision:expectedProjectRevision}),
    confirmRuntimeLibreChatDeleted:({projectId:p,retirementId})=>
      retireViaAdapter('confirm',p,{retirement_id:retirementId}),
    abortRuntimeRetirement:({projectId:p,retirementId,reasonCode})=>
      retireViaAdapter('abort',p,{retirement_id:retirementId,reason_code:reasonCode}),
    commitRuntimeRetirement:({projectId:p,retirementId})=>
      retireViaAdapter('commit',p,{retirement_id:retirementId}),
    isNativeOwnerAuthorized:async(req)=>{
      requireOwner(req===request,'C5_NATIVE_AUTH_REQUEST_SWITCH');
      const row=await nativeDb.getChatProject(actor,projectId);
      return row!=null && String(row._id)===projectId && String(row.user)===actor;
    },
    verifyNativeDeletionComplete,
    deleteLibreChatProject,
  };
}
module.exports={
  createC5CurrentNativeRetirementCallbacks,
  C5NativeRetirementOwnerStop,
};
