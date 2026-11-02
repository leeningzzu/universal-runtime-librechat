'use strict';
// Exact R195 native Project Files + C5 native routing. No real DB/network/effect.
const assert=require('node:assert/strict');
const Module=require('node:module');
const path=require('node:path');
const nativeRoot=path.resolve(__dirname,'../../windows/inquiry_desk/payload/product/overlay/librechat');
const routes=[];
const router={};
for(const m of ['use','get','post','put','patch','delete']){
 router[m]=(...args)=>{routes.push({method:m,path:args[0],handlers:args.slice(1)});return router};
}
const calls={normal:[],c5:[],legacyDelete:0,after:0};
const makeNormal=(label)=>(req,res)=>{
 calls.normal.push(label);return res.status(200).json({operation:label,verified:false});
};
const handlers={};
for(const name of ['listProjects','createProject','assignConversationToProject',
'listAvailableProjectFiles','listProjectFiles','addProjectFile','removeProjectFile',
'getProject','updateProject'])handlers[name]=makeNormal(name);
handlers.deleteProject=()=>{
 calls.legacyDelete++;throw Error('UNASSIGN_ONLY_DELETION_FORBIDDEN');
};
const db={
 listChatProjects(){},createChatProject(){},getChatProject(){},updateChatProject(){},
 deleteChatProject(){},assignConversationToProject(){},
 addChatProjectFile(){},removeChatProjectFile(){},getProjectFiles(){},getAvailableProjectFiles(){}
};
const jwtAuth=function jwtAuth(_req,_res,next){return next?.();};
const configMiddleware=function configMiddleware(_req,_res,next){return next?.();};
let injectedDeps;
const stubs={
 express:{Router:()=>router},
 '@librechat/api':{createProjectHandlers:deps=>{injectedDeps=deps;return handlers}},
 '~/server/middleware':{configMiddleware,requireJwtAuth:jwtAuth},
 '~/models':db,
 mongoose:{models:{}},
 './runtimeProjects':()=>{},
 './c5/c5WholeProjectProductNativeRoute.candidate.js':{
   createC5NativeWholeProjectProductRoute:options=>{
    assert.equal(options.nativeDb,db);
    assert.equal(options.upstreamProjectHandlers,handlers);
    assert.equal(typeof options.resolveCurrentOwnerBindings,'function');
    assert.equal(typeof options.afterVerifiedProjectDeletion,'function');
    return Object.fromEntries(['readiness','status','prepare','deleteProject'].map(name=>
      [name,(req,res)=>{
        calls.c5.push(name);
        return res.status(409).json({code:'C5_UNPROVEN_OWNERS_NO_DELETE',
          verified:false,retryAutomatically:false});
      }]));
  }},
 '~/server/services/C5WholeProjectDeleteOwners':{createC5WholeProjectDeleteOwners(){throw Error('UNAUTHORIZED_OWNER_BINDING_NOT_ACTIVATED')}},
 '~/server/services/ProjectNativeFile':{unbindAllNativeFileSourcesForProject(){calls.after++;}},
};
const originalLoad=Module._load;
let imported;
try {
 Module._load=function(id,parent,isMain){
  if(Object.prototype.hasOwnProperty.call(stubs,id))return stubs[id];
  return originalLoad.apply(this,arguments);
 };
 imported=require(path.join(nativeRoot,'projects.js'));
}finally{Module._load=originalLoad;}
assert.equal(imported,router);
assert.equal(routes[0].method,'use');
assert.equal(routes[0].path,jwtAuth);
assert.equal(routes[0].handlers.length,0);
assert.equal(routes.at(-1).method,'use');
assert.equal(routes.at(-1).path,'/');
for(const field of ['addChatProjectFile','removeChatProjectFile','getProjectFiles','getAvailableProjectFiles']){
 assert.equal(typeof injectedDeps[field],'function',field);
}
const expected=[
 ['get','/', 'listProjects'],
 ['post','/', 'createProject'],
 ['put','/conversations/:conversationId','assignConversationToProject'],
 ['get','/:projectId/files/available','listAvailableProjectFiles'],
 ['get','/:projectId/files','listProjectFiles'],
 ['post','/:projectId/files','addProjectFile'],
 ['delete','/:projectId/files/:fileId','removeProjectFile'],
 ['get','/:projectId','getProject'],
 ['patch','/:projectId','updateProject'],
];
function exactRoute(method,route){
 const matching=routes.filter(r=>r.method===method&&r.path===route);
 assert.equal(matching.length,1,'Expected exactly one '+method+' '+route);
 return matching[0];
}
function resp(){return {statusCode:200,status(c){this.statusCode=c;return this},
 json(body){this.body=body;return this}}}
(async()=>{
 for(const [method,route,handler] of expected){
  const x=exactRoute(method,route);
  assert.equal(x.handlers.at(-1),handlers[handler]);
  const shouldConfig=(method==='post'&&(route==='/'||route.endsWith('/files')))||method==='patch';
  if(shouldConfig){assert.equal(x.handlers.length,2);assert.equal(x.handlers[0],configMiddleware);}
  else assert.equal(x.handlers.length,1);
  const res=resp();
  await x.handlers.at(-1)({user:{id:'507f1f77bcf86cd799439012'},
    params:{projectId:'507f1f77bcf86cd799439011'}},res);
  assert.equal(res.body.operation,handler);
 }
 assert.equal(calls.normal.length,9);
 for(const [method,route,name] of [
  ['get','/:projectId/c5-whole-delete/readiness','readiness'],
  ['get','/:projectId/c5-whole-delete/status','status'],
  ['post','/:projectId/c5-whole-delete/prepare','prepare'],
  ['delete','/:projectId','deleteProject']]){
   const res=resp();
   await exactRoute(method,route).handlers.at(-1)({params:{projectId:'507f1f77bcf86cd799439011'}},res);
   assert.equal(res.statusCode,409);
   assert.equal(res.body.verified,false);
   assert.equal(res.body.retryAutomatically,false);
 }
 assert.deepEqual(calls.c5,['readiness','status','prepare','deleteProject']);
 assert.equal(calls.legacyDelete,0);
 assert.equal(calls.after,0);
 console.log('OFFICIAL_RC1_PROJECT_FILES_ROUTE=PASS_4_OF_4_NATIVE');
 console.log('OFFICIAL_RC1_PROJECT_CORE_CRUD=PASS_5_NATIVE');
 console.log('OFFICIAL_RC1_PROJECT_DELETE_C5_NEGATIVE=PASS_4_NO_UNASSIGN_FALLBACK');
 console.log('REAL_USER_FILE_EFFECT_AND_DELETE=NOT_RUN');
})().catch(e=>{console.error(e);process.exitCode=1});
