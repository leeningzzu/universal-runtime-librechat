'use strict';
// R242 synthetic-only route test: no external dependencies, no network/DB/delete.
const assert=require('node:assert/strict');
const Module=require('node:module');
const path=require('node:path');
const P='507f1f77bcf86cd799439011';
const U='507f191e810c19729de860ea';
const tally={normal:0,upstreamDelete:0,construct:0,c5:0};
const entries=[];
const router={};
for(const method of ['use','get','post','put','patch','delete']){
  router[method]=(pattern,handler)=>{entries.push({method,pattern,handler});return router;};
}
const upstream={
  listProjects:(_req,res)=>{tally.normal++;return res.status(200).json({normal:true});},
  createProject:(_req,res)=>{tally.normal++;return res.status(201).json({normal:true});},
  getProject:(_req,res)=>{tally.normal++;return res.status(200).json({normal:true});},
  updateProject:(_req,res)=>{tally.normal++;return res.status(200).json({normal:true});},
  assignConversationToProject:(_req,res)=>{tally.normal++;return res.status(200).json({normal:true});},
  deleteProject:()=>{tally.upstreamDelete++;throw Error('FORBIDDEN_UPSTREAM_UNASSIGN');},
};
const db={
  listChatProjects(){},createChatProject(){},getChatProject(){},
  updateChatProject(){},deleteChatProject(){},assignConversationToProject(){},
};
const stubs={
  express:{Router:()=>router},
  '@librechat/api':{createProjectHandlers:()=>upstream},
  '~/server/middleware/requireJwtAuth':()=>{},
  './runtimeProjects':{},
  '~/models':db,
  mongoose:{models:{}},
  './c5WholeProjectProductNativeRoute.candidate.js':{
    createC5NativeWholeProjectProductRoute:(input)=>{
      tally.construct++;
      assert.equal(input.upstreamProjectHandlers,upstream);
      const dispatch=async(req,res)=>{
        tally.c5++;
        const owners=await input.resolveCurrentOwnerBindings(req);
        if(!owners?.admissionOwner || !owners?.referenceOwner){
          return res.status(409).json({verified:false,retryAutomatically:false});
        }
        return res.status(202).json({status:'SYNTHETIC_DELEGATION_ONLY',verified:false});
      };
      return {readiness:dispatch,prepare:dispatch,deleteProject:dispatch};
    },
  },
};
const previous=Module._load;
let native;
try{
  Module._load=function(req,parent,isMain){
    if(Object.prototype.hasOwnProperty.call(stubs,req))return stubs[req];
    return previous.apply(this,arguments);
  };
  native=require(path.join(__dirname,'../native/projects.js'));
}finally{Module._load=previous;}
assert.equal(native,router);
function exact(method,pattern){
  const items=entries.filter(e=>e.method===method && e.pattern===pattern);
  assert.equal(items.length,1,method+' '+pattern);
  return items[0].handler;
}
const response=()=>({statusCode:200,headersSent:false,body:null,
  status(v){this.statusCode=v;return this;},
  json(v){this.body=v;this.headersSent=true;return this;}});
const request=({confirm=false,prep=false,owners=false,user=U}={})=>({
  params:{projectId:P},user:{id:user},
  body:prep?{confirmedIrreversibleProjectDelete:true}:{},
  headers:confirm?{'x-c5-irreversible-confirmed':native.R242_EXPLICIT_CONFIRMATION}:{},
  app:{locals:owners?{aidesC5WholeProjectDeleteOwners:async()=>({
    admissionOwner:{},referenceOwner:{},
  })}:{}}});
const blocked=(res)=>{
  assert.equal(res.statusCode,409);
  assert.equal(res.body.verified,false);
  assert.equal(res.body.retryAutomatically,false);
};
(async()=>{
  for(const [method,route] of [['get','/'],['post','/'],
    ['get','/:projectId'],['patch','/:projectId'],
    ['put','/conversations/:conversationId']]){
    const r=response();
    await exact(method,route)(request(),r);
    assert.equal(r.body.normal,true);
  }
  assert.equal(tally.normal,5);
  const del=exact('delete','/:projectId');
  let r=response();
  await del(request(),r);blocked(r);
  assert.equal(r.body.code,'C5_EXPLICIT_IRREVERSIBLE_CONFIRMATION_REQUIRED');
  assert.equal(tally.construct,0);
  r=response();await del(request({confirm:true}),r);blocked(r);
  r=response();await del(request({confirm:true,user:'foreign'}),r);blocked(r);
  const ready=exact('get','/:projectId/c5-whole-delete/readiness');
  r=response();await ready(request(),r);blocked(r);
  const prepare=exact('post','/:projectId/c5-whole-delete/prepare');
  r=response();await prepare(request(),r);blocked(r);
  assert.equal(r.body.code,'C5_EXPLICIT_IRREVERSIBLE_CONFIRMATION_REQUIRED');
  r=response();await prepare(request({prep:true}),r);blocked(r);
  r=response();await ready(request({owners:true}),r);
  assert.equal(r.statusCode,202);assert.equal(r.body.verified,false);
  r=response();await del(request({owners:true,confirm:true}),r);
  assert.equal(r.statusCode,202);assert.equal(r.body.verified,false);
  assert.equal(r.body.status,'SYNTHETIC_DELEGATION_ONLY');
  assert.equal(tally.upstreamDelete,0);
  console.log('R242_NATIVE_C5_ROUTE=PASS_5_NORMAL_ROUTES_7_NEGATIVE_OR_SYNTHETIC_CASES');
  console.log('R242_REAL_DELETE=NOT_RUN;NO_DB_NO_NETWORK_NO_USER_EFFECT');
})().catch(error=>{console.error(error);process.exitCode=1;});
