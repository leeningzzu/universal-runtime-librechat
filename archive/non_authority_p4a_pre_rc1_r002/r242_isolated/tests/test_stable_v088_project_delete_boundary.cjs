'use strict';
// Exact LibreChat v0.8.8 native Project router with only its DELETE replaced.
// No DB, Docker, network, account, model API or real file effects.
const assert=require('node:assert/strict');
const Module=require('node:module');
const path=require('node:path');
const stats={normal:0,legacyDeletes:0};
const recorded=[];
const router={};
for(const m of ['use','get','post','put','patch','delete']){
  router[m]=(pattern,fn)=>{recorded.push({m,pattern,fn});return router};
}
const handlers={
  listProjects:(req,res)=>{stats.normal++;return res.status(200).json({status:'LIST_OK'})},
  createProject:(req,res)=>{stats.normal++;return res.status(201).json({status:'CREATE_OK'})},
  getProject:(req,res)=>{stats.normal++;return res.status(200).json({status:'READ_OK'})},
  updateProject:(req,res)=>{stats.normal++;return res.status(200).json({status:'EDIT_OK'})},
  assignConversationToProject:(req,res)=>{stats.normal++;return res.status(200).json({status:'ASSIGN_OK'})},
  deleteProject:()=>{stats.legacyDeletes++;throw Error('LEGACY_UNASSIGN_FORBIDDEN');},
};
const db=Object.fromEntries([
'listChatProjects','createChatProject','getChatProject',
'updateChatProject','deleteChatProject','assignConversationToProject'
].map(x=>[x,()=>{}]));
const stubs={
  express:{Router:()=>router},
  '@librechat/api':{createProjectHandlers:()=>handlers},
  '~/server/middleware/requireJwtAuth':()=>{},
  '~/models':db
};
const old=Module._load;
let routes;
try{
 Module._load=function(name,parent,isMain){
   if(Object.prototype.hasOwnProperty.call(stubs,name))return stubs[name];
   return old.apply(this,arguments);
 };
 routes=require(path.join(__dirname,'../../windows/inquiry_desk/payload/product/overlay/librechat/projects.js'));
}finally{Module._load=old;}
assert.equal(routes,router);
function exact(m,p){
 const all=recorded.filter(x=>x.m===m&&x.pattern===p);
 assert.equal(all.length,1);
 return all[0].fn;
}
function response(){
 return {statusCode:200,body:null,
  status(code){this.statusCode=code;return this;},
  json(body){this.body=body;return this;}};
}
(async()=>{
 for(const [m,p] of [['get','/'],['post','/'],['get','/:projectId'],
  ['patch','/:projectId'],['put','/conversations/:conversationId']]){
  const res=response();
  await exact(m,p)({params:{projectId:'507f1f77bcf86cd799439011'}},res);
  assert.match(res.body.status,/_OK$/);
 }
 assert.equal(stats.normal,5);
 const res=response();
 await exact('delete','/:projectId')({params:{projectId:'507f1f77bcf86cd799439011'}},res);
 assert.equal(res.statusCode,409);
 assert.equal(res.body.verified,false);
 assert.equal(res.body.retryAutomatically,false);
 assert.equal(res.body.code,'C5_NATIVE_OWNER_WRITER_RECOVERY_VECTOR_CONSUMER_NOT_INSTALLED');
 assert.equal(stats.legacyDeletes,0);
 console.log('GATE3_ACTUAL_V088_PROJECT_ROUTER_NORMAL_5=PASS');
 console.log('GATE3_V088_INCOMPLETE_DELETE_FAIL_CLOSED=PASS_NO_UNASSIGN');
 console.log('GATE3_COMPLETE_PERMANENT_DELETE=NOT_PROVEN');
})().catch(e=>{console.error(e);process.exitCode=1;});
