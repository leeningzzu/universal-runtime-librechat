'use strict';
const assert = require('node:assert/strict');
const { createC5WholeProjectProductEndpoints } = require('./c5WholeProjectProductEndpoints.candidate.js');
const PROJECT='507f1f77bcf86cd799439011', OWNER='507f191e810c19729de860ea';
let assertions=0,scenarios=0;
function eq(a,b){assert.deepEqual(a,b);assertions++}
function response(){return {statusCode:0,body:null,status(n){this.statusCode=n;return this},json(b){this.body=b;return this}}}
function fixture(overrides={}){
 const audit={owner:0,readiness:0,effectGate:0,cascade:0,final:0};
 const input={projectId:PROJECT,ownerId:OWNER};
 const readiness={...input,scope:'C5_WHOLE_PROJECT_IRREVERSIBLE',
  sourceClass:'LIVE_NATIVE_AND_RUNTIME_AUTHORITIES',
  nativeCascadeInstalled:true,exclusiveWriter:true,
  coherentProtectedBackup:true,projectMembershipSealed:true,
  activePinnedJobs:0,projectRevision:7};
 const gate={...input,permitted:true,exclusiveWriter:true,
  coherentProtectedBackup:true,activePinnedJobs:0,projectRevision:7};
 const final={...input,sourceClass:'LIVE_NATIVE_AND_RUNTIME_AUTHORITIES',
  projectAndRuntimeRetired:true,allOwnedChatsMessagesRemoved:true,
  sourceMemoryAndOwnedFileReferencesCleared:true,
  exclusiveBlobsAndIndexesVerified:true,movedChatAndSharedFilesRetained:true,
  allCrossPlaneReferencesVerified:true,userRecoverable:false,receiptRevision:11};
 const deps={
  verifyNativeOwner:async()=>{audit.owner++;return {...input,owned:true}},
  proveWholeProjectReadiness:async()=>{audit.readiness++;return readiness},
  verifyPointOfEffectAdmission:async()=>{audit.effectGate++;return gate},
  executeAcceptedC5Cascade:async()=>{audit.cascade++;return {
    httpStatus:200,c5OperationPhase:'COMPLETE',cascadeResultComplete:true
  }},
  verifyFinalProductDeletion:async()=>{audit.final++;return final},
  ...overrides,
 };
 const handlers=createC5WholeProjectProductEndpoints(deps);
 const req={params:{projectId:PROJECT},user:{id:OWNER}};
 return {handlers,req,audit};
}
(async()=>{
 {
  const v=fixture();const r=response();
  await v.handlers.readiness(v.req,r);
  eq(r.statusCode,200);eq(r.body.status,'C5_WHOLE_PROJECT_DELETE_READY');
  eq(v.audit.cascade,0);scenarios++;
 }
 {
  const v=fixture();const r=response();
  await v.handlers.deleteProject(v.req,r);
  eq(r.statusCode,200);eq(r.body.status,'COMPLETE_VERIFIED_PROJECT_DELETE');
  eq(r.body.projectId,PROJECT);eq(r.body.verified,true);
  eq(r.body.userRecoverable,false);eq(r.body.receiptRevision,11);
  eq(v.audit.cascade,1);eq(v.audit.final,1);scenarios++;
 }
 {
  const v=fixture({proveWholeProjectReadiness:async()=>({status:'native-only'})});
  const r=response();await v.handlers.deleteProject(v.req,r);
  eq(r.statusCode,409);eq(r.body.verified,false);
  eq(r.body.code,'C5_FULL_NATIVE_CASCADE_NOT_READY');
  eq(v.audit.cascade,0);scenarios++;
 }
 {
  const v=fixture({verifyNativeOwner:async()=>({owned:false})});
  const r=response();await v.handlers.deleteProject(v.req,r);
  eq(r.statusCode,404);eq(r.body.code,'C5_PROJECT_OWNER_UNVERIFIED');
  eq(v.audit.cascade,0);scenarios++;
 }
 {
  const v=fixture({verifyPointOfEffectAdmission:async()=>({permitted:false})});
  const r=response();await v.handlers.deleteProject(v.req,r);
  eq(r.statusCode,409);eq(r.body.code,'C5_POINT_OF_EFFECT_SAFETY_UNPROVEN');
  eq(v.audit.cascade,0);scenarios++;
 }
 {
  // Upstream native unassign responds with only deletedCount/modifiedCount.
  const v=fixture({executeAcceptedC5Cascade:async()=>({deletedCount:1,modifiedCount:3})});
  const r=response();await v.handlers.deleteProject(v.req,r);
  eq(r.statusCode,409);eq(r.body.verified,false);
  eq(r.body.code,'C5_PROJECT_DELETE_PARTIAL_OR_BLOCKED');
  eq(v.audit.final,0);scenarios++;
 }
 {
  const v=fixture({executeAcceptedC5Cascade:async()=>({
    httpStatus:202,c5OperationPhase:'PARTIAL',cascadeResultComplete:false
  })});
  const r=response();await v.handlers.deleteProject(v.req,r);
  eq(r.statusCode,409);eq(r.body.code,'C5_PROJECT_DELETE_PARTIAL_OR_BLOCKED');
  eq(r.body.retryAutomatically,false);scenarios++;
 }
 {
  const v=fixture({verifyFinalProductDeletion:async()=>({
    projectId:PROJECT,ownerId:OWNER,userRecoverable:false,receiptRevision:11,
    sourceClass:'LIVE_NATIVE_AND_RUNTIME_AUTHORITIES',
    projectAndRuntimeRetired:true,allOwnedChatsMessagesRemoved:true,
    sourceMemoryAndOwnedFileReferencesCleared:true,
    exclusiveBlobsAndIndexesVerified:false,
    movedChatAndSharedFilesRetained:true,allCrossPlaneReferencesVerified:true
  })});
  const r=response();await v.handlers.deleteProject(v.req,r);
  eq(r.statusCode,409);eq(r.body.code,'C5_PROJECT_DELETE_FINAL_VERIFICATION_UNPROVEN');
  eq(r.body.verified,false);scenarios++;
 }
 {
  const v=fixture({executeAcceptedC5Cascade:async()=>{throw Error('unknown result')}});
  const r=response();await v.handlers.deleteProject(v.req,r);
  eq(r.statusCode,409);eq(r.body.code,'C5_PROJECT_DELETE_EFFECT_OUTCOME_UNKNOWN');
  eq(r.body.retryAutomatically,false);scenarios++;
 }
 console.log('C5_WHOLE_PROJECT_PRODUCT_USER_CONSUMER=PASS');
 console.log('SCENARIOS='+scenarios);
 console.log('ASSERTIONS='+assertions);
 console.log('LEGACY_NATIVE_UNASSIGN_PARTIAL_UNPROVEN=NEVER_USER_SUCCESS');
 console.log('PRODUCTION_API_MONGO_RUNTIME_EFFECT=0');
 console.log('PROOF_CEILING=ISOLATED_CONTRACT_NOT_INSTALLED_OR_HUMAN_ACCEPTED');
})().catch(e=>{console.error('C5_PRODUCT_CONSUMER_STOP',String(e.stack||e).slice(0,1500));process.exitCode=1});
