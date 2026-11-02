'use strict';
/** R242: direct REAL frozen R006 composer through the isolated Project Router.
 * No mock C5 composer, no HTTP, no DB, no models, no user mutation. */
const assert=require('node:assert/strict');
const path=require('node:path');
const Module=require('node:module');
const real=require(path.join(__dirname,'../../native_c5_candidate/R006_mature_uninstalled/api/server/routes/c5WholeProjectProductNativeRoute.candidate.js'));
assert.equal(typeof real.createC5NativeWholeProjectProductRoute,'function');
const P='507f1f77bcf86cd799439011';
const U='507f191e810c19729de860ea';
const tally={upstreamDelete:0,ownerReads:0,dbReads:0,normal:0};
const registered=[];
const router={};
for(const method of ['use','get','post','put','patch','delete']){
  router[method]=(url,fn)=>{registered.push({method,url,fn});return router;};
}
const upstream={
  listProjects:(_r,res)=>{tally.normal++;return res.status(200).json({list:true});},
  createProject(){},getProject(){},updateProject(){},
  assignConversationToProject(){},
  deleteProject(){tally.upstreamDelete++;throw Error('LEGACY_DELETE_MUST_NOT_RUN');},
};
const db={
  listChatProjects(){},createChatProject(){},
  getChatProject(){tally.dbReads++;throw Error('DB_MUST_NOT_READ_UNAUTHORIZED');},
  updateChatProject(){},deleteChatProject(){},
  assignConversationToProject(){},
  getSharedResourceFileIds(){throw Error('FILE_GRAPH_MUST_NOT_READ_UNAUTHORIZED');},
};
const stub={
  express:{Router:()=>router},
  '@librechat/api':{createProjectHandlers:()=>upstream},
  '~/server/middleware/requireJwtAuth':()=>{},
  './runtimeProjects':{},
  '~/models':db,
  mongoose:{models:{}},
  './c5WholeProjectProductNativeRoute.candidate.js':real,
};
const old=Module._load;
let native;
try{
  Module._load=function(req,parent,isMain){
    if(Object.prototype.hasOwnProperty.call(stub,req)) return stub[req];
    return old.apply(this,arguments);
  };
  native=require(path.join(__dirname,'../native/projects.js'));
}finally{Module._load=old;}
function response(){return{
  statusCode:200,body:null,headersSent:false,
  status(code){this.statusCode=code;return this;},
  json(body){this.body=body;this.headersSent=true;return this;},
};}
function handler(method,url){
  const found=registered.filter(x=>x.method===method && x.url===url);
  assert.equal(found.length,1);
  return found[0].fn;
}
function req(confirm){
  return {user:{id:U},params:{projectId:P},
    headers:confirm?{'x-c5-irreversible-confirmed':native.R242_EXPLICIT_CONFIRMATION}:{},
    app:{locals:{}},body:{}};
}
(async()=>{
  let res=response();await handler('get','/')(req(false),res);
  assert.equal(res.statusCode,200);assert.equal(tally.normal,1);
  res=response();await handler('get','/:projectId/c5-whole-delete/readiness')(req(false),res);
  assert.equal(res.statusCode,409);assert.equal(res.body.verified,false);
  assert.equal(res.body.retryAutomatically,false);
  res=response();await handler('delete','/:projectId')(req(true),res);
  assert.equal(res.statusCode,409);assert.equal(res.body.verified,false);
  assert.equal(res.body.retryAutomatically,false);
  assert.equal(tally.upstreamDelete,0);
  assert.equal(tally.dbReads,0);
  console.log('R242_REAL_FROZEN_R006_ROUTER_COMPOSITION=PASS_MISSING_OWNER_FAIL_CLOSED');
  console.log('R242_NORMAL_PROJECT_READ=PASS; UPSTREAM_UNASSIGN_DELETE=ZERO');
  console.log('R242_EFFECT=NONE;NO_DOCKER_NO_USER_DATA_NO_NETWORK');
})().catch(e=>{console.error(e);process.exitCode=1;});
