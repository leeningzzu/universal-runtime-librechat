'use strict';
const assert=require('node:assert/strict');
const {createC5CanonicalNativeRetirementHandler,
  isC5CanonicalNativeRetirementHandler}=require('./c5CanonicalNativeRetirement.candidate.js');
const {createC5RuntimeOwnerNativeBridge}=require('./c5RuntimeOwnerNativeBridge.candidate.js');
const {createC5CurrentNativeRetirementCallbacks}=
  require('./c5CurrentNativeRetirementCallbacks.candidate.js');

const P='507f1f77bcf86cd799439011';
const U='507f191e810c19729de860ea';
let assertions=0,cases=0;
const eq=(a,b)=>{assert.deepEqual(a,b);assertions++};
const req={user:{id:U},params:{projectId:P},
  headers:{authorization:'Bearer isolated-no-network'}};
const res=()=>({statusCode:200,body:null,
  status(n){this.statusCode=n;return this;},
  json(body){this.body=body;return this;},
});

function fakeOwner(getRuntimeProject,history){
  return {
    getRuntimeProject,
    prepareRuntimeRetirement:async()=>{history.effects++;throw Error('prepare forbidden')},
    confirmRuntimeLibreChatDeleted:async()=>{history.effects++;throw Error('confirm forbidden')},
    abortRuntimeRetirement:async()=>{history.effects++;throw Error('abort forbidden')},
    commitRuntimeRetirement:async()=>{history.effects++;throw Error('commit forbidden')},
    deleteLibreChatProject:async()=>{history.effects++;throw Error('native deletion forbidden')},
    isNativeOwnerAuthorized:async()=>true,
    verifyNativeDeletionComplete:async()=>({complete:false}),
  };
}
async function mustFail(action, expectedCode) {
  await assert.rejects(action,(err)=>err?.code===expectedCode);
  assertions++;
}
(async()=>{
  {
    const log={effects:0};
    const guarded=createC5CanonicalNativeRetirementHandler(
      fakeOwner(async()=>({found:false,native_only_verified:true}),log));
    eq(isC5CanonicalNativeRetirementHandler(guarded),true);
    await mustFail(()=>guarded(req,res()),
      'C5_CANONICAL_RUNTIME_OWNER_MISSING_NO_NATIVE_ONLY_DELETE');
    eq(log.effects,0);cases++;
  }
  {
    const log={effects:0};
    const guarded=createC5CanonicalNativeRetirementHandler(
      fakeOwner(async()=>({found:true,status:'ACTIVE',project_revision:5}),log));
    // Preflight saw an existing Runtime, then point-of-use owner disappears.
    const bridge=createC5RuntimeOwnerNativeBridge({
      request:req,nativeC5RetirementHandler:guarded,
      adapterBase:'http://ur-runtime-adapter:9000',
      shellKey:'no-network-guard-key-123',
      doFetch:async()=>({status:200,json:async()=>({
        found:true,project_id:'PRJ_0123456789ABCDEF0123456789AB',
         status:'ACTIVE',project_revision:5,
      })}),
    });
    // Use separate dynamic read: the guarded callback itself is still
    // authoritative; force a GET race at that point rather than a fake 200.
    const afterAdmission=createC5CanonicalNativeRetirementHandler(
      fakeOwner(async()=>({found:false,native_only_verified:true}),log));
    const raced=createC5RuntimeOwnerNativeBridge({
      request:req,nativeC5RetirementHandler:afterAdmission,
      adapterBase:'http://ur-runtime-adapter:9000',
      shellKey:'no-network-guard-key-123',
      doFetch:async()=>({status:200,json:async()=>({
        found:true,project_id:'PRJ_0123456789ABCDEF0123456789AB',
         status:'ACTIVE',project_revision:5,
      })}),
    });
    eq(typeof bridge.executeAcceptedRetirement,'function');
    await mustFail(()=>raced.executeAcceptedRetirement(req),
      'C5_NATIVE_RETIREMENT_OUTCOME_UNKNOWN');
    eq(log.effects,0);cases++;
  }
  {
    // The bridge now refuses an arbitrary injected native handler, even
    // when that function claims to return a synthetic successful delete.
    await mustFail(async()=>createC5RuntimeOwnerNativeBridge({
      request:req,nativeC5RetirementHandler:async()=>({status:200}),
      adapterBase:'http://ur-runtime-adapter:9000',
      shellKey:'no-network-guard-key-123',doFetch:async()=>{},
    }), 'C5_NATIVE_RETIREMENT_HANDLER_NOT_CANONICAL_RUNTIME_ONLY');
    cases++;
  }
  {
    const history={native:0,adapterGet:0};
    const callbacks=createC5CurrentNativeRetirementCallbacks({
      request:req,
      nativeDb:{getChatProject:async()=>({_id:P,user:U})},
      nativeModels:{
        ChatProject:{countDocuments:async()=>0},
        Conversation:{countDocuments:async()=>0},
      },
      upstreamProjectHandlers:{
        deleteProject:async()=>{history.native++;throw Error('no effect allowed')},
      },
      adapterBase:'http://ur-runtime-adapter:9000',
      shellKey:'no-network-guard-key-123',
      doFetch:async(url,options)=>{
        eq(options.method,'GET');
        eq(url.endsWith('/v1/runtime-project-retirement'),true);
        history.adapterGet++;
        return {status:200,json:async()=>({found:false,native_only_verified:true})};
      },
    });
    const guarded=createC5CanonicalNativeRetirementHandler(callbacks);
    await mustFail(()=>guarded(req,res()),
      'C5_CANONICAL_RUNTIME_OWNER_MISSING_NO_NATIVE_ONLY_DELETE');
    eq(history.native,0);eq(history.adapterGet,1);cases++;
  }
  {
    // The original native callback must carry the same authenticated actor
    // and explicit C5 Project retirement intent that the first-party
    // Adapter validates for all four PREPARE/CONFIRM/ABORT/COMMIT stages.
    let posts=0,phaseCalls=0;
    const RID='RETIRE_'+('A'.repeat(24));
    const callbacks=createC5CurrentNativeRetirementCallbacks({
      request:req,
      nativeDb:{getChatProject:async()=>({_id:P,user:U})},
      nativeModels:{
        ChatProject:{countDocuments:async()=>0},
        Conversation:{countDocuments:async()=>0},
      },
      upstreamProjectHandlers:{
        deleteProject:async()=>{throw Error('native delete forbidden')},
      },
      adapterBase:'http://ur-runtime-adapter:9000',
      shellKey:'no-network-guard-key-123',
      doFetch:async(url,options)=>{
        posts++;
        eq(options.method,'POST');
        eq(options.headers['X-LibreChat-Project-ID'],P);
        eq(options.headers['X-LibreChat-Authenticated-User-ID'],U);
        eq(options.headers['X-C5-Native-Project-Delete-Intent'],
          'confirmed-irreversible-project-delete');
        const action=url.split('/').at(-1);
        eq(['prepare','confirm','abort','commit'].includes(action),true);
        eq(JSON.parse(options.body).retirement_id,RID);
        phaseCalls++;
        return {status:200,json:async()=>({retirement_id:RID,
          project:{project_id:'PRJ_SYNTHETIC_CURRENT',status:'RETIRE_PENDING'}})};
      },
    });
    for(const call of [
      ()=>callbacks.prepareRuntimeRetirement({projectId:P,retirementId:RID,expectedProjectRevision:1}),
      ()=>callbacks.confirmRuntimeLibreChatDeleted({projectId:P,retirementId:RID}),
      ()=>callbacks.abortRuntimeRetirement({projectId:P,retirementId:RID,reasonCode:'LIBRECHAT_DELETE_FAILED'}),
      ()=>callbacks.commitRuntimeRetirement({projectId:P,retirementId:RID}),
    ]){
      const result=await call();
      eq(result.retirement_id,RID);
    }
    eq(posts,4);eq(phaseCalls,4);cases++;
  }
  console.log('C5_REAL_NATIVE_RETIREMENT_NO_NATIVE_ONLY_FALLBACK=PASS');
  console.log('CASES='+cases);
  console.log('ASSERTIONS='+assertions);
  console.log('LEGACY_UNASSIGN_WHEN_RUNTIME_DISAPPEARS=BLOCKED');
  console.log('PRODUCTION_NETWORK_OR_USER_DELETE_EFFECT=0');
  console.log('PROOF_CEILING=ISOLATED_POINT_OF_USE_NATIVE_OWNER_GUARD');
})().catch(err=>{console.error('C5_CANONICAL_NATIVE_GUARD_STOP',String(err.stack||err));process.exitCode=1;});
