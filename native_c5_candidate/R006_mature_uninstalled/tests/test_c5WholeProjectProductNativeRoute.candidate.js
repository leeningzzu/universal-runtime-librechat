'use strict';
const assert=require('node:assert/strict');
const crypto=require('node:crypto');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const {createC5NativeWholeProjectProductRoute}=
  require('./c5WholeProjectProductNativeRoute.candidate.js');

const P='507f1f77bcf86cd799439011';
const U='507f191e810c19729de860ea';
let checks=0,cases=0;
const eq=(a,b)=>{assert.deepEqual(a,b);checks++};
function response(){return {
  statusCode:200,body:null,
  status(v){this.statusCode=v;return this;},
  json(v){this.body=v;return this;},
}}
function makeFixture(options={}){
  const actions={nativeDeletes:0,runtimeReceipts:0,dbReads:0};
  // Only an exact authenticated, immutable Runtime C5 receipt grants
  // recovery once the native Project is absent.
  const sealed={projectId:P,ownerId:U,revision:7,
    chats:[],exclusive:[],retained:[]};
  const digest=crypto.createHash('sha256').update(JSON.stringify(sealed)).digest('hex');
  const receipt={schema:'C5_PROJECT_CASCADE_R001',projectId:P,
    ownerId:options.foreignReceipt?'other-user':U,
    phase:'PARTIAL_OR_BLOCKED',plan:{...sealed,
      planSha256:options.corruptReceipt?'0'.repeat(64):digest},
    c5Confirmed:true,c5_receipt_revision:3,deletedChats:[],deletedFiles:[]};

  const models={};
  for(const model of ['ChatProject','Conversation','Message','ToolCall','SharedLink','File','Assistant']){
    models[model]={
      countDocuments:async()=>model==='ChatProject'&&options.foreignProjectExists?1:0,
      find:()=>({select(){return this},lean:async()=>[]}),
    };
  }
  const nativeDb={
    getChatProject:async(user,project)=>{
      actions.dbReads++;
      return options.notOwned?null:user===U&&project===P?{_id:P,user:U}:null;
    },
    getSharedResourceFileIds:async()=>[],
  };
  const runtimeOwner={
    loadOperationReceipt:async()=>options.withReceipt?receipt:null,
    persistOperationReceipt:async()=>{actions.runtimeReceipts++;throw Error('test must not persist')},
    executeAcceptedRetirement:async()=>{actions.nativeDeletes++;throw Error('test must not delete')},
    readRetirementState:async()=>({authoritative:!options.runtimeMissing,projectId:P,
      project_revision:7,
      status:options.runtimeMissing?'UNKNOWN':options.withReceipt?'RETIRED':'ACTIVE'}),
    readCurrentRuntimeReferences:async()=>({
      schema:'AIDES_C5_CANONICAL_RUNTIME_PROJECT_REFERENCES_R001',
      authority_class:'CURRENT_RUNTIME_PROJECT_SOURCE_REF_AND_MEMORY_READ_ONLY',
      nativeProjectId:P,actorId:U,runtimeProjectId:'PRJ_SYNTHETIC_CURRENT',
      runtimeProjectRevision:options.sourceRefRevisionChanged?8:7,
      runtimeProjectStatus:options.withReceipt?'RETIRED':'ACTIVE',
      sourceRefsProvenComplete:!options.sourceRefsIncomplete,
      projectInstructionsCurrentEmpty:Boolean(options.withReceipt && !options.instructionsStillBound),
      // Legacy records may be present, incomplete or foreign. They are
      // NOT the current target-Project point-of-effect Job admission.
      ...(options.globalHistoricalJobNoise?{
        projectJobsScopeVerified:false,projectJobsQuiescent:false,
        projectActivePinnedJobs:113,projectUnresolvedJobs:113,
        projectJobsCurrentnessSha256:'unavailable',
        projectJobsInitialMembershipSha256:'unavailable',
      }:{}),
      sourceRefCount:0,sources:[],
      memoryStateRevision:0,visibleMemoryCount:0,activeMemoryCount:0,
    }),
  };
  const admissionOwner={
    proveInventoryFence:async()=>({
      projectId:options.foreignAdmissionProject?'FOREIGN_PROJECT':P,
      ownerId:U,
      jobScope:options.globalOnlyJobProof||options.jobScopeInvalid?
        'GLOBAL_HISTORICAL_JOB_COUNT':'TARGET_PROJECT_CURRENT_EFFECTS',
      permitted:!options.blockBackup&&!options.projectHasOrphan,
      exclusiveWriter:true,
      protectedBackupReady:!options.blockBackup,
      activePinnedJobs:options.projectHasRunningJob?1:0,
      projectRevision:7,
      projectMembershipSealed:true,
    }),
    recheckEffectFence:async()=>({
      projectId:P,ownerId:U,jobScope:'TARGET_PROJECT_CURRENT_EFFECTS',
      permitted:!options.blockBackup&&!options.projectHasOrphan,
      exclusiveWriter:true,
      protectedBackupReady:!options.blockBackup,
      activePinnedJobs:options.projectHasRunningJob?1:0,
      projectMembershipSealed:true,
    }),
  };
  const referenceOwner={
    readCompleteProjectFileGraph:async()=>({
      projectId:P,ownerId:U,projectRevision:7,
      authoritative:true,complete:!options.blockGraph,
      files:[],
    }),
    recheckExclusiveFile:async()=>{throw Error('no file effects in read-only test')},
    verifyFileBytesAndDerivativesAbsent:async()=>{throw Error('no file effects in read-only test')},
    verifyRetainedFileBytesPresent:async()=>{throw Error('no file effects in read-only test')},
    verifyCrossPlaneNoReferences:async()=>{throw Error('no delete in read-only test')},
  };
  const req={
    user:{id:U},params:{projectId:P},
    headers:{authorization:'Bearer synthetic.readonly.token'},
    app:{locals:{}},
  };
  const owners={runtimeOwner,admissionOwner,referenceOwner};
  const contract={
    nativeDb,getNativeModels:()=>models,
    resolveCurrentOwnerBindings:async()=>options.missingOwners?null:owners,
    nativeFetch:async()=>{actions.nativeDeletes++;throw Error('network forbidden')},
  };
  return {req,owners,contract,models,nativeDb,actions};
}

(async()=>{
  // This real route composer must return READY on owner-admitted read-only
  // inventory, without writing an operation receipt or calling native Delete.
  {
    const x=makeFixture();
    const c=createC5NativeWholeProjectProductRoute(x.contract);
    const r=response();await c.readiness(x.req,r);
    eq(r.statusCode,200);eq(r.body.status,'C5_WHOLE_PROJECT_DELETE_READY');
    eq(r.body.projectId,P);eq(r.body.wholeProjectCascadeReady,true);
    eq(x.actions.nativeDeletes,0);eq(x.actions.runtimeReceipts,0);cases++;
  }
  for(const condition of ['missingOwners','blockBackup','blockGraph','notOwned','runtimeMissing','sourceRefsIncomplete','sourceRefRevisionChanged','jobScopeInvalid','projectHasRunningJob','projectHasOrphan']){
    const x=makeFixture({[condition]:true});
    const c=createC5NativeWholeProjectProductRoute(x.contract);
    const r=response();await c.readiness(x.req,r);
    eq([404,409].includes(r.statusCode),true);
    eq(r.body.verified,false);eq(r.body.retryAutomatically,false);
    eq(x.actions.nativeDeletes,0);eq(x.actions.runtimeReceipts,0);cases++;
  }

  {
    // Global historical Job audits cannot overrule an admitted, current,
    // owner-scoped, zero-active-Job Project lifecycle read.
    const x=makeFixture({globalHistoricalJobNoise:true});
    const c=createC5NativeWholeProjectProductRoute(x.contract);
    const r=response();await c.readiness(x.req,r);
    eq(r.statusCode,200);eq(r.body.wholeProjectCascadeReady,true);
    eq(x.actions.nativeDeletes,0);eq(x.actions.runtimeReceipts,0);cases++;
  }

  // Sealed C5 recovery works after the native Project is gone.
  {
    const x=makeFixture({notOwned:true,withReceipt:true});
    const c=createC5NativeWholeProjectProductRoute(x.contract);
    const r=response();await c.readiness(x.req,r);
    eq(r.statusCode,200);eq(r.body.wholeProjectCascadeReady,true);
    eq(x.actions.nativeDeletes,0);eq(x.actions.runtimeReceipts,0);cases++;
  }
  for(const option of [
    {notOwned:true,withReceipt:true,corruptReceipt:true},
    {notOwned:true,withReceipt:true,instructionsStillBound:true},
    {notOwned:true,withReceipt:true,foreignReceipt:true},
    {notOwned:true,withReceipt:true,foreignProjectExists:true},
    {notOwned:true,withReceipt:true,blockBackup:true},
  ]) {
    const x=makeFixture(option);
    const c=createC5NativeWholeProjectProductRoute(x.contract);
    const r=response();await c.readiness(x.req,r);
    eq(r.statusCode,option.foreignProjectExists?404:409);
    eq(r.body.verified,false);
    eq(x.actions.nativeDeletes,0);eq(x.actions.runtimeReceipts,0);cases++;
  }
  {
    const x=makeFixture({missingOwners:true});
    const c=createC5NativeWholeProjectProductRoute(x.contract);
    const r=response();await c.deleteProject(x.req,r);
    eq(r.statusCode,409);eq(r.body.verified,false);
    eq(r.body.retryAutomatically,false);eq(x.actions.nativeDeletes,0);
    eq(x.actions.runtimeReceipts,0);cases++;
  }

  // Native canonical owner + actual Runtime bridge, with no external network
  // and no destructive call, proves the real product compose path.
  for(const canonicalFound of [true,false]){
    const x=makeFixture();
    let adapterGets=0,upstreamDeletes=0;
    const adapterFetch=async(url,options)=>{
      eq(options.method,'GET');
      adapterGets++;
      if(url.endsWith('/v1/runtime-project-cascade-receipt')) {
        return {status:200,json:async()=>({found:false,record:null})};
      }
      if(url.endsWith('/v1/runtime-project-retirement')) {
        return {status:200,json:async()=>canonicalFound?
          {found:true,project_id:'PRJ_SYNTHETIC_CURRENT',status:'ACTIVE',project_revision:7}:
          {found:false,project_id:'PRJ_SYNTHETIC_CURRENT',native_only_verified:true}};
      }

      if(url.endsWith('/v1/runtime-project-c5-source-ref-inventory')) {
        return {status:200,json:async()=>({
          schema:'AIDES_C5_CANONICAL_RUNTIME_PROJECT_REFERENCES_R001',
          authority_class:'CURRENT_RUNTIME_PROJECT_SOURCE_REF_AND_MEMORY_READ_ONLY',
          nativeProjectId:P,actorId:U,runtimeProjectId:'PRJ_SYNTHETIC_CURRENT',
          runtimeProjectRevision:7,runtimeProjectStatus:'ACTIVE',
          sourceRefsProvenComplete:true,sourceRefCount:0,sources:[],
          projectInstructionsCurrentEmpty:false,
          projectJobsScopeVerified:true,projectJobsQuiescent:true,
          projectActivePinnedJobs:0,projectUnresolvedJobs:0,
          projectJobsCurrentnessSha256:'b'.repeat(64),
          projectJobsInitialMembershipSha256:'a'.repeat(64),

          memoryStateRevision:0,visibleMemoryCount:0,activeMemoryCount:0,
        })};
      }
      throw Error('unexpected native transport '+url);
    };
    const oldBase=process.env.UR_RUNTIME_ADAPTER_BASE;
    const oldKey=process.env.UR_SHELL_ADAPTER_KEY;
    try {
      process.env.UR_RUNTIME_ADAPTER_BASE='http://ur-runtime-adapter:9000';
      process.env.UR_SHELL_ADAPTER_KEY='synthetic-key-no-network-123';
      const c=createC5NativeWholeProjectProductRoute({
        ...x.contract,nativeFetch:adapterFetch,
        upstreamProjectHandlers:{
          deleteProject:async()=>{upstreamDeletes++;throw Error('native mutation forbidden')},
        },
      });
      const r=response();await c.readiness(x.req,r);
      eq(r.statusCode,canonicalFound?200:409);
      eq(r.body.verified===true,false);
      eq(upstreamDeletes,0);eq(x.actions.runtimeReceipts,0);
      eq(adapterGets>=2,true);cases++;
    } finally {
      if(oldBase===undefined)delete process.env.UR_RUNTIME_ADAPTER_BASE;
      else process.env.UR_RUNTIME_ADAPTER_BASE=oldBase;
      if(oldKey===undefined)delete process.env.UR_SHELL_ADAPTER_KEY;
      else process.env.UR_SHELL_ADAPTER_KEY=oldKey;
    }
  }
  // Confirmed UI user action -> real current Adapter bridge -> existing Runtime
  // idempotent Project enrollment, guarded by native Project owner & writer/
  // backup/Job admission. Readiness alone must never create Runtime state.
  {
    const oldBase=process.env.UR_RUNTIME_ADAPTER_BASE;
    const oldKey=process.env.UR_SHELL_ADAPTER_KEY;
    process.env.UR_RUNTIME_ADAPTER_BASE='http://ur-runtime-adapter:9000';
    process.env.UR_SHELL_ADAPTER_KEY='synthetic-key-no-network-123';
    try{
      for(const state of [
        {name:'native-only',initiallyBound:false,expect:200,post:1},
        {name:'already-bound',initiallyBound:true,expect:200,post:0},
        {name:'missing-confirmation',omitConfirmation:true,expect:409,post:0},
        {name:'backup-denied',blockBackup:true,expect:409,post:0},
        {name:'foreign-fence',foreignAdmissionProject:true,expect:409,post:0},
        {name:'global-history-not-job-scope',globalOnlyJobProof:true,expect:409,post:0},
        {name:'foreign-owner',notOwned:true,expect:409,post:0},
        {name:'orphan-provenance',nativeProofInvalid:true,expect:409,post:0},
      ]){
        const x=makeFixture({blockBackup:state.blockBackup,
          notOwned:state.notOwned,
          foreignAdmissionProject:state.foreignAdmissionProject,
          globalOnlyJobProof:state.globalOnlyJobProof});
        x.req.body=state.omitConfirmation?{}:
          {confirmedIrreversibleProjectDelete:true};
        let bound=state.initiallyBound===true,posts=0;
        const adapterFetch=async(url,options)=>{
          if(url.endsWith('/v1/runtime-project-retirement')){
            eq(options.method,'GET');
            return {status:200,json:async()=>bound?
              {found:true,project_id:'PRJ_SYNTHETIC_CURRENT',status:'ACTIVE',
               project_revision:7}:
              {found:false,project_id:'PRJ_SYNTHETIC_CURRENT',
               native_only_verified:!state.nativeProofInvalid}};
          }
          if(url.endsWith('/v1/runtime-project-retirement/ensure')){
            eq(options.method,'POST');
            eq(options.headers['X-C5-Native-Project-Delete-Intent'],
              'confirmed-irreversible-project-delete');
            posts++;bound=true;
            return {status:200,json:async()=>({
              found:true,project_id:'PRJ_SYNTHETIC_CURRENT',
              project_revision:7,status:'ACTIVE',newly_bound:true})};
          }
          if(url.endsWith('/v1/runtime-project-cascade-receipt')){
            return {status:200,json:async()=>({found:false,record:null})};
          }
          if(url.endsWith('/v1/runtime-project-c5-source-ref-inventory')){
            return {status:200,json:async()=>({
              schema:'AIDES_C5_CANONICAL_RUNTIME_PROJECT_REFERENCES_R001',
              authority_class:'CURRENT_RUNTIME_PROJECT_SOURCE_REF_AND_MEMORY_READ_ONLY',
              nativeProjectId:P,actorId:U,runtimeProjectId:'PRJ_SYNTHETIC_CURRENT',
              runtimeProjectRevision:7,runtimeProjectStatus:'ACTIVE',
              sourceRefsProvenComplete:true,sourceRefCount:0,sources:[],
              projectInstructionsCurrentEmpty:false,
              projectJobsScopeVerified:true,projectJobsQuiescent:true,
              projectActivePinnedJobs:0,projectUnresolvedJobs:0,
              projectJobsCurrentnessSha256:'b'.repeat(64),
              projectJobsInitialMembershipSha256:'a'.repeat(64),
              memoryStateRevision:0,visibleMemoryCount:0,activeMemoryCount:0,
            })};
          }
          throw Error('NO_EXTERNAL_OR_REAL_DELETE_TOOL_CALLS');
        };
        const c=createC5NativeWholeProjectProductRoute({
          ...x.contract,nativeFetch:adapterFetch,
          upstreamProjectHandlers:{
            deleteProject:async()=>{x.actions.nativeDeletes++;throw Error('effect forbidden')},
          },
        });
        if(!state.initiallyBound&&!state.notOwned){
          const initial=response();await c.readiness(x.req,initial);
          eq(initial.statusCode,409);eq(posts,0);
        }
        const prepared=response();await c.prepare(x.req,prepared);
        eq(prepared.statusCode,state.expect);
        eq(posts,state.post);
        eq(x.actions.nativeDeletes,0);eq(x.actions.runtimeReceipts,0);
        if(state.expect===200){
          eq(prepared.body.status,'C5_WHOLE_PROJECT_DELETE_READY');
          const second=response();await c.readiness(x.req,second);
          eq(second.statusCode,200);eq(posts,state.post);
        }
        cases++;
      }
    }finally{
      if(oldBase===undefined)delete process.env.UR_RUNTIME_ADAPTER_BASE;
      else process.env.UR_RUNTIME_ADAPTER_BASE=oldBase;
      if(oldKey===undefined)delete process.env.UR_SHELL_ADAPTER_KEY;
      else process.env.UR_SHELL_ADAPTER_KEY=oldKey;
    }
  }
  // Exercise the ACTUAL route source, not a copied ideal API mock:
  // only one DELETE :projectId, newly reachable readiness GET, and
  // NEVER the original unassign-only handlers.deleteProject.
  {
    const x=makeFixture({missingOwners:true});
    const routes=new Map();let legacyCalls=0;
    const router={
      use(){},
      get:(key,fn)=>routes.set('GET '+key,fn),
      post:(key,fn)=>routes.set('POST '+key,fn),
      put:(key,fn)=>routes.set('PUT '+key,fn),
      patch:(key,fn)=>routes.set('PATCH '+key,fn),
      delete:(key,fn)=>routes.set('DELETE '+key,fn),
    };
    const methods={
      listProjects:()=>{},createProject:()=>{},
      assignConversationToProject:()=>{},getProject:()=>{},
      updateProject:()=>{},
      deleteProject:()=>{legacyCalls++;throw Error('legacy unassign MUST NOT be used')},
    };
    const nativeRoute=fs.readFileSync(
      path.join(__dirname,'projects.c5.whole_product_route.candidate.js'),'utf8'
    );
    const script=new vm.Script(nativeRoute,{filename:'C5_PRODUCT_NATIVE_PROJECTS_ROUTE'});
    const localModule={exports:{}};
    const fakeRequire=(name)=>{
      switch(name){
        case 'express':return {Router:()=>router};
        case '@librechat/api':return {createProjectHandlers:()=>methods};
        case '~/server/middleware/requireJwtAuth':return ()=>{};
        case './runtimeProjects':return ()=>{};
        case '~/models':return x.nativeDb;
        case 'mongoose':return {models:x.models};
        case './c5WholeProjectProductNativeRoute.candidate.js':
          return {createC5NativeWholeProjectProductRoute};
        default:throw Error('UNEXPECTED_RUNTIME_IMPORT_'+name);
      }
    };
    script.runInNewContext({require:fakeRequire,module:localModule,exports:localModule.exports});
    eq(routes.has('GET /:projectId/c5-whole-delete/readiness'),true);
    eq(routes.has('DELETE /:projectId'),true);
    eq([...routes.keys()].filter(k=>k==='DELETE /:projectId').length,1);
    const r1=response();await routes.get('GET /:projectId/c5-whole-delete/readiness')(x.req,r1);
    eq(r1.statusCode,409);eq(r1.body.verified,false);
    const r2=response();await routes.get('DELETE /:projectId')(x.req,r2);
    eq(r2.statusCode,409);eq(r2.body.verified,false);
    eq(legacyCalls,0);eq(x.actions.nativeDeletes,0);
    eq(x.actions.runtimeReceipts,0);cases++;
  }
  console.log('C5_CURRENT_NATIVE_PRODUCT_USER_ROUTE=PASS');
  console.log('CASES='+cases);
  console.log('ASSERTIONS='+checks);
  console.log('REAL_NATIVE_PROJECTS_ROUTER_GUARDED_WITHOUT_UNASSIGN_FALLBACK=PASS');
  console.log('READINESS_IS_OWNER_BACKED_NO_EFFECT=PASS');
  console.log('PROOF_CEILING=ISOLATED_NATIVE_ROUTE_AND_NO_EFFECT_CONSUMER_NOT_DAILY');
})().catch(e=>{console.error('C5_PRODUCT_NATIVE_ROUTE_STOP',String(e.stack||e));process.exitCode=1;});
