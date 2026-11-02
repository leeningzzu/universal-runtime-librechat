'use strict';
/** Real v0.8.8 Project CRUD + R195 C5 owner binding consumer test.
 * Synthetic-only: no Docker, DB writes, HTTP, File/Blob/Vector or paid model.
 */
const assert = require('node:assert/strict');
const Module = require('node:module');
const path = require('node:path');
const P='507f1f77bcf86cd799439011', U='507f191e810c19729de860ea';
const calls={normal:[],legacyDelete:0,r195Build:0,resolve:0,mutation:0,unbind:0};
const entries=[];
const router={};
for (const method of ['use','get','post','put','patch','delete']) {
 router[method]=(pattern,fn)=>{entries.push({method,pattern,fn});return router;};
}
function reply(){return{
 statusCode:200,headersSent:false,body:null,
 status(code){this.statusCode=code;return this;},
 json(body){this.headersSent=true;this.body=body;return this;}
};}
const normal=(name)=> (_req,res)=>{
 calls.normal.push(name);return res.status(200).json({normal:name});
};
const upstream={
 listProjects:normal('list'),
 createProject:normal('create'),
 getProject:normal('get'),
 updateProject:normal('update'),
 assignConversationToProject:normal('move'),
 deleteProject:()=>{calls.legacyDelete++;throw Error('LEGACY_UNASSIGN_DELETE_FORBIDDEN');},
};
const db={
 listChatProjects(){},createChatProject(){},getChatProject(){},
 updateChatProject(){},deleteChatProject(){},assignConversationToProject(){},
 getSharedResourceFileIds:async()=>new Set()
};
const models={ChatProject:{},Conversation:{},File:{}};
const realOwner=require(path.join(__dirname,'../../windows/inquiry_desk/payload/product/overlay/librechat/C5WholeProjectDeleteOwners.js'));
assert.equal(typeof realOwner.createC5WholeProjectDeleteOwners,'function');
// Exercise an actual mature owner fail-close guard, not just a stub.
assert.throws(()=>realOwner.createC5WholeProjectDeleteOwners({
 request:{params:{projectId:P},user:{id:U},app:{locals:{}}},
 models:{},nativeDb:{}
}),/C5_CURRENT_NATIVE_MODELS_REQUIRED/);
const fakeC5={
 createC5NativeWholeProjectProductRoute:({nativeDb,upstreamProjectHandlers,
    getNativeModels,resolveCurrentOwnerBindings,afterVerifiedProjectDeletion})=>{
    calls.r195Build++;
    assert.equal(nativeDb,db);assert.equal(upstreamProjectHandlers,upstream);
    assert.equal(getNativeModels(),models);
    assert.equal(typeof afterVerifiedProjectDeletion,'function');
    // No irreversible effect. Only inspect whether live owner binding is
    // wired through the existing app request.
    const action=(name)=>async(req,res)=>{
      calls.mutation++;calls.resolve++;
      try{await resolveCurrentOwnerBindings(req);}catch(_e) {
        return res.status(409).json({verified:false,retryAutomatically:false});
      }
      return res.status(202).json({status:'SYNTHETIC_C5_'+name,verified:false});
    };
    return {readiness:action('READINESS'),status:action('STATUS'),
      prepare:action('PREPARE'),deleteProject:action('DELETE')};
 },
};
const stubs={
 express:{Router:()=>router},
 mongoose:{models},
 '@librechat/api':{createProjectHandlers:()=>upstream},
 '~/server/middleware/requireJwtAuth':()=>{},
 '~/models':db,
 './runtimeProjects':()=>{},
 './c5/c5WholeProjectProductNativeRoute.candidate.js':fakeC5,
 '~/server/services/C5WholeProjectDeleteOwners':realOwner,
 '~/server/services/ProjectNativeFile':{
  unbindAllNativeFileSourcesForProject:async()=>{calls.unbind++;},
 },
};
const prev=Module._load;
let native;
try {
 Module._load=function(id,parent,isMain) {
  if(Object.hasOwn(stubs,id))return stubs[id];
  return prev.apply(this,arguments);
 };
 native=require(path.join(__dirname,'../../windows/inquiry_desk/payload/product/overlay/librechat/projects.js'));
}finally{Module._load=prev;}
assert.equal(native,router);
function route(method,pattern){
 const found=entries.filter(x=>x.method===method&&x.pattern===pattern);
 assert.equal(found.length,1,method+' '+pattern);
 return found[0].fn;
}
function req({writer=false,user=U,modelOwners=true}={}){
 const locals=writer?{aidesC5WriteFence:{acquire(){},acquirePrepare(){},assertHeld(){},release(){}}}:{};
 if(!modelOwners)delete db.getSharedResourceFileIds;
 return {params:{projectId:P},user:{id:user},app:{locals},method:'DELETE',headers:{},body:{}};
}
(async()=>{
 for(const [method,pattern] of [['get','/'],['post','/'],
  ['get','/:projectId'],['patch','/:projectId'],
  ['put','/conversations/:conversationId']]){
  const res=reply();await route(method,pattern)(req(),res);
  assert.equal(res.statusCode,200);assert.equal(typeof res.body.normal,'string');
 }
 assert.equal(calls.normal.length,5);
 const d=route('delete','/:projectId');
 let res=reply();await d(req(),res);
 assert.equal(res.statusCode,409);
 assert.equal(res.body.code,'C5_EXISTING_NATIVE_WRITE_FENCE_NOT_BOUND');
 assert.equal(res.body.verified,false);
 assert.equal(res.body.retryAutomatically,false);
 assert.equal(calls.r195Build,0);
 res=reply();await d(req({writer:true,user:'outsider'}),res);
 assert.equal(res.statusCode,409);
 assert.equal(res.body.code,'C5_CURRENT_NATIVE_PROJECT_OWNER_REQUIRED');
 res=reply();await d(req({writer:true,modelOwners:false}),res);
 assert.equal(res.statusCode,409);
 assert.equal(res.body.code,'C5_CURRENT_NATIVE_FILE_AND_PROJECT_OWNERS_MISSING');
 db.getSharedResourceFileIds=async()=>new Set();
 res=reply();await route('get','/:projectId/c5-whole-delete/readiness')(req({writer:true}),res);
 assert.equal(res.statusCode,409);assert.equal(res.body.verified,false);
 res=reply();await route('post','/:projectId/c5-whole-delete/prepare')(req({writer:true}),res);
 assert.equal(res.statusCode,409);assert.equal(res.body.verified,false);
 res=reply();await d(req({writer:true}),res);
 assert.equal(res.statusCode,409);assert.equal(res.body.verified,false);
 assert.equal(calls.legacyDelete,0);
 assert.equal(calls.unbind,0);
 assert.equal(calls.r195Build,3);
 // The R195 runtime-specific Project source and Memory router must be mounted
 // after normal Project CRUD, not shadow creation or deletion.
 assert.equal(entries.at(-1).method,'use');
 assert.equal(entries.at(-1).pattern,'/');
 console.log('C5_R195_ACTUAL_NATIVE_OWNER_MISSING=FAIL_CLOSED_SAFE');
 console.log('C5_V088_CORE_CRUD_5_ROUTES=PASS');
 console.log('C5_NATIVE_READINESS_STATUS_PREPARE_DELETE_ROUTED=PASS');
 console.log('C5_UPSTREAM_UNASSIGN_AND_FALSE_COMPLETE=ZERO');
 console.log('C5_REAL_USER_PROJECT_EFFECT=NOT_RUN');
})().catch(e=>{console.error(e);process.exitCode=1;});
